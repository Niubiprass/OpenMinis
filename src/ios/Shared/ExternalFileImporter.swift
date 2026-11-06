import Foundation

private let importLog = AppLogger(category: "Share")

/// Ingests a `file://` URL that arrived via "Open in Minis" / "Copy to Minis"
/// from the Files app (or any document provider) into the SAME PendingShare
/// pipeline the Share Extension uses. The file is copied into the App Group
/// shared transfer directory and surfaced as a `.attachment` item, so it flows
/// through AIChatView.injectPendingShareIfNeeded — which already detects a
/// Provider-export JSON and prompts import-vs-attach (#678). No separate
/// detection path. [T-ios-json-open-provider-import-prompt]
enum ExternalFileImporter {

    /// True if `url` is a local file we should ingest (vs a `minis://` deep link).
    static func canIngest(_ url: URL) -> Bool {
        url.isFileURL
    }

    /// Copy the incoming file into the shared transfer dir and raise a pending
    /// share so the normal consume → detect → prompt flow runs. Returns true if
    /// the file was staged (the copy itself runs in the background — see below).
    ///
    /// [T-share-open-in-copy-offmain] The NSFileCoordinator copy used to run
    /// synchronously on the main thread inside `.onOpenURL` / the scene URL
    /// handler. For a large file (or an iCloud item that still has to be
    /// materialised) that is seconds of main-thread I/O: the app froze long
    /// enough for the scene-update watchdog to kill it (0x8badf00d, 2026-11-06
    /// stacks). The coordinator still brackets the read with
    /// start/stopAccessingSecurityScopedResource, but now inside the detached
    /// task, and the pending share is raised on the main actor once the bytes
    /// are actually on disk.
    @discardableResult
    static func ingest(_ url: URL, into coordinator: ShareCoordinator,
                       accompanyingText: String? = nil) -> Bool {
        guard url.isFileURL else { return false }
        guard let dir = SharedContainerStore.sharedFileDirectory else {
            importLog.error("[Share] ingest: sharedFileDirectory is nil — cannot stage \(url.lastPathComponent)")
            return false
        }

        let fm = FileManager.default
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)

        // Use a unique on-disk name to avoid colliding with a concurrent share,
        // but keep the original extension so downstream type checks (e.g. the
        // .json gate in providerExportJSON) still work.
        let ext = url.pathExtension
        let stagedName = "open-\(UUID().uuidString)" + (ext.isEmpty ? "" : ".\(ext)")
        let dest = dir.appendingPathComponent(stagedName)

        Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                // NSFileCoordinator gives the document provider a chance to
                // materialize a not-yet-downloaded iCloud file before we copy.
                var coordErr: NSError?
                var copyErr: Error?
                NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordErr) { readURL in
                    do {
                        if fm.fileExists(atPath: dest.path) { try fm.removeItem(at: dest) }
                        try fm.copyItem(at: readURL, to: dest)
                    } catch { copyErr = error }
                }
                if let coordErr { throw coordErr }
                if let copyErr { throw copyErr }
            } catch {
                importLog.error("[Share] ingest: failed to copy \(url.lastPathComponent): \(error.localizedDescription)")
                return
            }

            var items: [PendingShare.Item] = []
            if let text = accompanyingText?.trimmingCharacters(in: .whitespacesAndNewlines),
               !text.isEmpty {
                // A crash report is sent to chat with one short instruction already
                // in the composer, so the user only has to hit send.
                items.append(PendingShare.Item(kind: .inlineText, value: text))
            }
            items.append(PendingShare.Item(kind: .attachment, value: stagedName))
            let share = PendingShare(items: items, timestamp: Date())
            SharedContainerStore.savePendingShare(share)
            importLog.info("[Share] ingest: staged \(url.lastPathComponent) as \(stagedName) and raising pending share")
            await MainActor.run { coordinator.raisePendingShare() }
        }
        return true
    }
}
