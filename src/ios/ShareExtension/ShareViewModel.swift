import Foundation
import UIKit
import UniformTypeIdentifiers

/// Processes NSExtensionItems from the share sheet, saves files to the shared
/// container, and writes a PendingShare for the main app to consume.
final class ShareViewModel {
    private var pendingItems: [PendingShare.Item] = []
    private var failureCount = 0
    private let inlineTextLimit = 1000

    /// Per-provider deadline. iOS 15 Photos / Files providers occasionally never
    /// call back; one hung provider used to stall the whole extension until the
    /// outer timeout tore the process down BEFORE anything was saved — the
    /// "shared file never arrives" report. Bounding each load means a hung
    /// provider costs this one item, not the entire share.
    /// 5s proved too tight for cold iCloud/Files providers and silently
    /// dropped shared originals; the pre-44e4591 implementation had no deadline
    /// and worked. 20s matches the extension's outer safety net.
    private static let perItemTimeout: TimeInterval = 12.0

    /// Run the whole pipeline off the main thread, returning whether a share
    /// record was written.
    ///
    /// [T-share-offmain] The extension's UI is a blank view; the expensive part
    /// is provider loading + copying, which must not sit on the main thread —
    /// that is what the extension watchdog punishes.
    ///
    /// `hardTimeout` is a safety net only. On expiry the pipeline is left
    /// running (cancellation cannot interrupt an NSItemProvider callback) so a
    /// late save still lands.
    static func processAndSave(_ items: [NSExtensionItem],
                              hardTimeout: TimeInterval = 30.0) async -> (saved: Bool, timedOut: Bool) {
        let vm = ShareViewModel()
        let gate = ShareCompletion<Bool>()
        let work = Task.detached(priority: .userInitiated) { () -> Bool in
            await vm.processExtensionItems(items)
            let saved = vm.save()
            gate.finish(saved)
            return saved
        }
        // The timeout is a real deadline: do NOT await the losing task in a
        // task group (exiting it waits for the provider). The detached work
        // keeps running and can still save a late result.
        gate.armTimeout(after: hardTimeout, returning: false)
        let result = await gate.wait()
        let timedOut = gate.didTimeOut
        if timedOut {
            NSLog("[ShareExt] processAndSave: deadline hit after %.0fs; late save may still land", hardTimeout)
        }
        // Keep the detached task alive through the extension's short grace
        // period by retaining its handle in a global.
        Self.lastWork = work
        return (result, timedOut)
    }

    private static var lastWork: Task<Bool, Never>?

    /// Load one item with a deadline, so a silent provider cannot stall the
    /// entire share. Returns nil on timeout or error.
    private static func loadItem(_ provider: NSItemProvider,
                                 _ typeIdentifier: String) async -> NSSecureCoding? {
        await withCheckedContinuation { (cont: CheckedContinuation<NSSecureCoding?, Never>) in
            let lock = NSLock()
            var finished = false
            let finish: (NSSecureCoding?) -> Void = { value in
                lock.lock()
                if finished { lock.unlock(); return }
                finished = true
                lock.unlock()
                cont.resume(returning: value)
            }
            provider.loadItem(forTypeIdentifier: typeIdentifier, options: nil) { item, _ in
                finish(item)
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + perItemTimeout) {
                finish(nil)
            }
        }
    }

    /// Process all extension items from the share context.
    func processExtensionItems(_ extensionItems: [NSExtensionItem]) async {
        pendingItems.removeAll()

        let fm = FileManager.default
        if let dir = SharedContainerStore.sharedFileDirectory {
            try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }

        for extensionItem in extensionItems {
            guard let attachments = extensionItem.attachments else { continue }

            for provider in attachments {
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    await processURL(provider)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    await processText(provider)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                    await processImage(provider)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.movie.identifier) {
                    await processVideo(provider)
                } else if provider.hasItemConformingToTypeIdentifier(UTType.item.identifier) {
                    await processFile(provider)
                }
            }
        }
    }

    /// Save pending share and return true on success.
    /// [T-share-buffer-merge] MERGE with any unconsumed previous share instead
    /// of overwriting it. Rapid consecutive shares (user shares screenshot A,
    /// then B a few seconds later, before the main app ran
    /// processPendingShare) used to silently lose A: this save() replaced the
    /// App Group record wholesale. Attachment file names are UUID-suffixed so
    /// the merged item lists never collide on disk. The 300s window matches
    /// checkForPendingShare's staleness cutoff; anything older is abandoned
    /// content whose files the main app will clean up.
    func save() -> Bool {
        var items = pendingItems
        if let existing = SharedContainerStore.loadPendingShare(),
           Date().timeIntervalSince(existing.timestamp) < 300 {
            NSLog("[ShareExt] save: merging %d existing unconsumed items with %d new",
                  existing.items.count, pendingItems.count)
            // Drop only exact duplicates (same kind + same value), then give
            // every legacy item a stable id so two consumers cannot erase
            // each other's text by value. Keep the older share first.
            let extra = existing.items.filter { old in
                !items.contains(where: { $0.kind == old.kind && $0.value == old.value })
            }
            items.insert(contentsOf: extra, at: 0)
        }
        guard !items.isEmpty else {
            NSLog("[ShareExt] save: no item survived (failures=\(failureCount))")
            return false
        }
        let share = PendingShare(items: items, timestamp: Date()).assigningItemIDs()
        let ok = SharedContainerStore.savePendingShare(share)
        NSLog("[ShareExt] save: %d item(s), failures=%d, wrote=%@",
              items.count, failureCount, ok ? "YES" : "NO")
        return ok
    }

    // MARK: - Processors

    private func processURL(_ provider: NSItemProvider) async {
        guard let item = await Self.loadItem(provider, UTType.url.identifier),
              let url = item as? URL else { return }

        // file:// URLs are local files — treat as file attachment, not inline text
        if url.isFileURL {
            await copyFileToShared(from: url)
            return
        }

        pendingItems.append(.init(kind: .inlineText, value: url.absoluteString))
    }

    /// Copy a local file URL to the shared container as an attachment.
    /// Original bytes are preserved (PNG transparency/GIF animation/HEIC/EXIF);
    /// re-encoding every image to JPEG lost all of those.
    private func copyFileToShared(from url: URL) async {
        guard let name = Self.copyNow(url: url,
                                      prefix: "shared",
                                      fallbackExtension: "dat") else {
            failureCount += 1
            NSLog("[ShareExt] copyFileToShared failed: %@", url.lastPathComponent)
            return
        }
        pendingItems.append(.init(kind: .attachment, value: name))
    }

    /// Copy a provider file representation synchronously inside its callback,
    /// because the callback URL expires immediately afterwards.
    private static func copyNow(url: URL, prefix: String, fallbackExtension: String) -> String? {
        guard let dir = SharedContainerStore.sharedFileDirectory else { return nil }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let ext = url.pathExtension.isEmpty ? fallbackExtension : url.pathExtension
        let name = "\(prefix)-\(UUID().uuidString.prefix(8)).\(ext)"
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        do {
            try FileManager.default.copyItem(at: url, to: dir.appendingPathComponent(name))
            return name
        } catch {
            NSLog("[ShareExt] copy %@ failed: %@", url.lastPathComponent, error.localizedDescription)
            return nil
        }
    }

    /// Load a file representation from a provider without waiting past the
    /// deadline; the representation is copied before its callback returns.
    private static func copyRepresentation(_ provider: NSItemProvider,
                                           typeIdentifier: String,
                                           prefix: String,
                                           fallbackExtension: String) async -> (name: String?, timedOut: Bool) {
        let gate = ShareCompletion<String?>()
        provider.loadFileRepresentation(forTypeIdentifier: typeIdentifier) { url, error in
            guard gate.claimCallback() else { return }
            guard let url else {
                gate.finish(nil)
                return
            }
            // MUST be synchronous: the provider deletes this URL as soon as the
            // callback returns.
            gate.finish(copyNow(url: url, prefix: prefix,
                                fallbackExtension: fallbackExtension))
        }
        gate.armTimeout(after: perItemTimeout, returning: nil)
        let name = await gate.wait()
        return (name, gate.didTimeOut)
    }

    private func processText(_ provider: NSItemProvider) async {
        guard let item = await Self.loadItem(provider, UTType.plainText.identifier),
              let text = item as? String else { return }

        if text.count <= inlineTextLimit {
            pendingItems.append(.init(kind: .inlineText, value: text))
        } else {
            let fileName = "shared-text-\(UUID().uuidString.prefix(8)).txt"
            if let dir = SharedContainerStore.sharedFileDirectory {
                let fileURL = dir.appendingPathComponent(fileName)
                try? text.write(to: fileURL, atomically: true, encoding: .utf8)
                pendingItems.append(.init(kind: .attachment, value: fileName))
            }
        }
    }

    private func processImage(_ provider: NSItemProvider) async {
        // Preferred: original encoded file, byte for byte.
        let copied = await Self.copyRepresentation(provider,
                                                   typeIdentifier: UTType.image.identifier,
                                                   prefix: "shared-image",
                                                   fallbackExtension: "jpg")
        if let name = copied.name {
            pendingItems.append(.init(kind: .attachment, value: name))
            return
        }
        // A timed-out file request would only stall again; fall back solely
        // when the provider answered with no usable representation.
        if copied.timedOut {
            failureCount += 1
            return
        }

        // Fallback for providers that only expose decoded pixels/Data.
        guard let item = await Self.loadItem(provider, UTType.image.identifier) else {
            failureCount += 1
            return
        }
        var data: Data?
        var ext = "jpg"
        if let image = item as? UIImage {
            data = image.jpegData(compressionQuality: 0.92)
        } else if let raw = item as? Data {
            data = raw
            ext = Self.imageExtension(raw) ?? "jpg"
        } else if let url = item as? URL {
            data = try? Data(contentsOf: url)
            ext = url.pathExtension.isEmpty ? (Self.imageExtension(data ?? Data()) ?? "jpg") : url.pathExtension
        }
        guard let data, let dir = SharedContainerStore.sharedFileDirectory else {
            failureCount += 1
            return
        }
        let name = "shared-image-\(UUID().uuidString.prefix(8)).\(ext)"
        do {
            try data.write(to: dir.appendingPathComponent(name), options: .atomic)
            pendingItems.append(.init(kind: .attachment, value: name))
        } catch {
            failureCount += 1
        }
    }

    private static func imageExtension(_ data: Data) -> String? {
        let b = [UInt8](data.prefix(12))
        guard b.count >= 4 else { return nil }
        if b.starts(with: [0xff, 0xd8, 0xff]) { return "jpg" }
        if b.starts(with: [0x89, 0x50, 0x4e, 0x47]) { return "png" }
        if b.starts(with: [0x47, 0x49, 0x46, 0x38]) { return "gif" }
        return nil
    }

    private func processVideo(_ provider: NSItemProvider) async {
        let copied = await Self.copyRepresentation(provider,
                                                   typeIdentifier: UTType.movie.identifier,
                                                   prefix: "shared-video",
                                                   fallbackExtension: "mov")
        if let name = copied.name {
            pendingItems.append(.init(kind: .attachment, value: name))
            return
        }
        if copied.timedOut {
            failureCount += 1
            return
        }
        guard let item = await Self.loadItem(provider, UTType.movie.identifier),
              let url = item as? URL,
              let name = Self.copyNow(url: url, prefix: "shared-video", fallbackExtension: "mov") else {
            failureCount += 1
            return
        }
        pendingItems.append(.init(kind: .attachment, value: name))
    }

    private func processFile(_ provider: NSItemProvider) async {
        let copied = await Self.copyRepresentation(provider,
                                                   typeIdentifier: UTType.item.identifier,
                                                   prefix: "shared",
                                                   fallbackExtension: "dat")
        if let name = copied.name {
            pendingItems.append(.init(kind: .attachment, value: name))
            return
        }
        if copied.timedOut {
            failureCount += 1
            return
        }
        // Some document providers only vend a URL/Data object. Keep a fallback
        // so a conforming-but-representation-less provider is not lost.
        guard let item = await Self.loadItem(provider, UTType.item.identifier) else {
            failureCount += 1
            return
        }
        if let url = item as? URL,
           let name = Self.copyNow(url: url, prefix: "shared", fallbackExtension: "dat") {
            pendingItems.append(.init(kind: .attachment, value: name))
            return
        }
        if let data = item as? Data, let dir = SharedContainerStore.sharedFileDirectory {
            let name = "shared-\(UUID().uuidString.prefix(8)).dat"
            if (try? data.write(to: dir.appendingPathComponent(name), options: .atomic)) != nil {
                pendingItems.append(.init(kind: .attachment, value: name))
                return
            }
        }
        failureCount += 1
    }
}
