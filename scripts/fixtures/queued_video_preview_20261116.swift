// Platform mocks only. The runner inserts ACTUAL production source + V3 bridge.
import Foundation
import Darwin
import Combine

struct AppLogger {
    static var stages: [String] = []
    init(category: String) {}
    func info(_ value: String) { Self.stages.append(value) }
}
struct AttachmentMeta {
    let id: UUID
    let fileName: String
    let path: String
    let isImage: Bool
    let isVideo: Bool
    let pastedId: String?
}
struct QLPreviewController {
    static func canPreview(_ item: NSURL) -> Bool { true }
}
let minisMarkdownExtensions: Set<String> = ["md"]
let minisTextExtensions: Set<String> = ["txt"]
let minisHTMLExtensions: Set<String> = ["html"]
let minisAudioExtensions: Set<String> = ["m4a"]
let minisDocumentExtensions: Set<String> = ["pdf"]
let minisVideoExtensions: Set<String> = ["mp4", "mov", "m4v"]
func resolveMinisFileURL(url: URL, sessionId: String) -> URL? {
    // Queue previews must not call the minis/session resolver at all.
    fatalError("queued preview incorrectly used sent-file resolver")
}
struct MockMessage {
    let id: UUID
    var isQueued: Bool
    var inputAttachments: [InputAttachment]
}
@MainActor final class MockVM {
    var sessionId: String?
    var messages: [MockMessage]
    init(sessionId: String, messages: [MockMessage]) {
        self.sessionId = sessionId
        self.messages = messages
    }
}

// MARK: - Native cases
struct TestFailure: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}
@main struct NativeQueuedVideoTests {
    @MainActor static func expect(_ value: Bool, _ message: String) throws {
        if !value { throw TestFailure(message) }
    }
    @MainActor static func until(_ predicate: () -> Bool) async throws {
        for _ in 0..<200 {
            if predicate() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        throw TestFailure("timed out waiting for production callback/lease cleanup")
    }
    static func previewDirectories() -> Set<String> {
        Set((try? FileManager.default.contentsOfDirectory(atPath: FileManager.default.temporaryDirectory.path)) ?? [])
            .filter { $0.hasPrefix("queued-video-preview-") }
    }
    @MainActor static func main() async throws {
        let manager = FileManager.default
        let root = manager.temporaryDirectory.appendingPathComponent("queued-video-fixture-" + UUID().uuidString)
        try manager.createDirectory(at: root, withIntermediateDirectories: false)
        defer { try? manager.removeItem(at: root) }
        let bytes = Data([0, 0, 0, 16, 102, 116, 121, 112, 113, 116, 32, 32]) +
            Data(repeating: 0x7a, count: QueuedVideoPreviewSource.chunkBytes * 2 + 19)
        let original = root.appendingPathComponent("待发 #33% video.mov")
        try bytes.write(to: original)

        // Capture the real descriptor, then unlink BEFORE any off-main copy.
        guard let source = QueuedVideoPreviewSource(url: original) else { throw TestFailure("capture failed") }
        try manager.removeItem(at: original)
        var pinned: QueuedVideoPreviewLease? = try await Task.detached {
            try source.retainCopy(isCancelled: { false })
        }.value
        let pinnedURL = pinned!.url
        try expect(try Data(contentsOf: pinnedURL) == bytes, "drain lost retained bytes")
        try expect(pinnedURL != original && pinnedURL.isFileURL, "player did not get independent local file")
        pinned = nil
        try await until { !manager.fileExists(atPath: pinnedURL.deletingLastPathComponent().path) }

        // Bounded metadata/file validation: non-local, missing, zero, dir,
        // symlink, FIFO and a sparse oversized file are rejected, not copied.
        try expect(QueuedVideoPreviewSource(url: URL(string: "minis://attachments/a.mov")!) == nil, "accepted minis URL")
        try expect(QueuedVideoPreviewSource(url: original) == nil, "accepted missing source")
        let empty = root.appendingPathComponent("empty.mov")
        try Data().write(to: empty)
        let directory = root.appendingPathComponent("directory.mov")
        try manager.createDirectory(at: directory, withIntermediateDirectories: false)
        let huge = root.appendingPathComponent("huge.mov")
        manager.createFile(atPath: huge.path, contents: nil)
        let hugeHandle = try FileHandle(forWritingTo: huge)
        try hugeHandle.truncate(atOffset: UInt64(QueuedVideoPreviewSource.maximumBytes + 1))
        try hugeHandle.close()
        let fifo = root.appendingPathComponent("fifo.mov")
        try expect(fifo.path.withCString { mkfifo($0, 0o600) } == 0, "could not create FIFO fixture")
        for invalid in [empty, directory, huge, fifo] {
            guard let candidate = QueuedVideoPreviewSource(url: invalid) else { continue }
            do {
                _ = try await Task.detached { try candidate.retainCopy(isCancelled: { false }) }.value
                throw TestFailure("accepted invalid file kind/size")
            } catch QueuedVideoPreviewSource.Failure.invalidFile {}
        }
        try bytes.write(to: original)
        let symlink = root.appendingPathComponent("symlink.mov")
        try manager.createSymbolicLink(at: symlink, withDestinationURL: original)
        try expect(QueuedVideoPreviewSource(url: symlink) == nil, "followed final symlink")

        // Mid-copy cancellation cleans only its own partial directory.
        let beforeCancel = previewDirectories()
        guard let cancellable = QueuedVideoPreviewSource(url: original) else { throw TestFailure("cancel source missing") }
        do {
            _ = try await Task.detached {
                var checks = 0
                return try cancellable.retainCopy(isCancelled: { checks += 1; return checks >= 3 })
            }.value
            throw TestFailure("copy ignored cancellation")
        } catch QueuedVideoPreviewSource.Failure.cancelled {}
        try expect(previewDirectories().subtracting(beforeCancel).isEmpty, "partial retained copy leaked")
        try expect(try Data(contentsOf: original) == bytes, "cancellation changed queue source")

        let presenter = FileAttachmentPresenter()
        presenter.bind(to: "owner-A")
        let attachment = InputAttachment(fileName: "local.mov", cacheURL: original, kind: .video)
        let messageID = UUID()
        let vm = MockVM(sessionId: "owner-A", messages: [MockMessage(id: messageID, isQueued: true, inputAttachments: [attachment])])
        let bridge = NativeQueueBridge(vm: vm, presenter: presenter)
        try expect(!bridge.openQueuedVideo(attachment, messageID: UUID(), sessionId: "owner-A"), "stale message accepted")
        try expect(!bridge.openQueuedVideo(attachment, messageID: messageID, sessionId: "owner-B"), "wrong session accepted")
        var loading = attachment
        loading.loadState = .loading
        vm.messages[0].inputAttachments = [loading]
        try expect(!bridge.openQueuedVideo(loading, messageID: messageID, sessionId: "owner-A"), "loading accepted")
        loading.loadState = .failed
        vm.messages[0].inputAttachments = [loading]
        try expect(!bridge.openQueuedVideo(loading, messageID: messageID, sessionId: "owner-A"), "failed accepted")
        vm.messages[0].inputAttachments = [attachment]
        var staleURL = attachment
        staleURL.cacheURL = root.appendingPathComponent("old.mov")
        try expect(!bridge.openQueuedVideo(staleURL, messageID: messageID, sessionId: "owner-A"), "stale path accepted")
        vm.messages[0].isQueued = false
        try expect(!bridge.openQueuedVideo(attachment, messageID: messageID, sessionId: "owner-A"), "drained row accepted")
        vm.messages[0].isQueued = true

        // Real Button-bridge/presenter handoff; opening alone leaves queue intact.
        try expect(bridge.openQueuedVideo(attachment, messageID: messageID, sessionId: "owner-A"), "queue handoff failed")
        try expect(vm.messages.count == 1 && vm.messages[0].isQueued &&
                   vm.messages[0].inputAttachments[0].id == attachment.id, "opening mutated queue")
        try expect(manager.fileExists(atPath: original.path), "opening deleted queue source")
        // Simulate queue drain immediately, before awaiting the copy callback.
        vm.messages.removeAll()
        try manager.removeItem(at: original)
        try await until { presenter.videoSheet != nil }
        var coverPayload = presenter.videoSheet
        let coverURL = coverPayload!.url
        weak var coverLease = coverPayload!.queuedLease
        try expect(coverLease != nil && coverURL != original && coverURL.isFileURL, "missing cover lease")
        try expect(try Data(contentsOf: coverURL) == bytes && presenter.sheet == nil, "not retained player handoff")
        presenter.bind(to: "owner-B")
        try expect(presenter.videoSheet == nil, "session change did not close presenter")
        try expect(manager.fileExists(atPath: coverURL.path) && coverLease != nil, "lease died before player close")
        coverPayload = nil
        try await until { coverLease == nil && !manager.fileExists(atPath: coverURL.deletingLastPathComponent().path) }

        // Cancellation after request invalidates its token: no stale cover or
        // late File Not Found in the new owner. Await actual discarded log.
        try bytes.write(to: original)
        presenter.bind(to: "owner-A")
        AppLogger.stages.removeAll()
        try expect(presenter.openQueuedVideo(attachment, sessionId: "owner-A"), "cancel handoff failed")
        presenter.reset()
        try await until { AppLogger.stages.contains("[QueuedVideoPreview] stage=discarded") }
        try expect(presenter.videoSheet == nil && presenter.unavailableName == nil, "cancelled callback presented")
        AppLogger.stages.removeAll()
        try expect(presenter.openQueuedVideo(attachment, sessionId: "owner-A"), "session handoff failed")
        presenter.bind(to: "owner-C")
        try await until { AppLogger.stages.contains("[QueuedVideoPreview] stage=discarded") }
        try expect(presenter.videoSheet == nil && presenter.unavailableName == nil, "old session callback presented")

        // A later request supersedes an unfinished queued copy; the old close
        // notification cannot dismiss the replacement (sent preview unchanged).
        presenter.bind(to: "owner-A")
        AppLogger.stages.removeAll()
        try expect(presenter.openQueuedVideo(attachment, sessionId: "owner-A"), "supersede handoff failed")
        presenter.openVideo(original)
        let replacementID = presenter.videoSheet!.id
        presenter.queuedVideoDidDisappear(id: UUID())
        try await until { AppLogger.stages.contains("[QueuedVideoPreview] stage=discarded") }
        try expect(presenter.videoSheet?.id == replacementID, "stale close/callback cleared replacement")
        presenter.queuedVideoDidDisappear(id: replacementID)
        try expect(presenter.videoSheet == nil, "matching close failed")
        // Descriptor validation failure reports stable availability, never a sheet.
        presenter.bind(to: "owner-A")
        let missing = InputAttachment(fileName: "missing.mov", cacheURL: root.appendingPathComponent("missing.mov"), kind: .video)
        try expect(presenter.openQueuedVideo(missing, sessionId: "owner-A"), "missing intent not handled")
        try expect(presenter.unavailableName == "missing.mov" && presenter.videoSheet == nil, "missing file silently presented")
        presenter.reset()
        try expect(try Data(contentsOf: original) == bytes, "preview/cancel changed original")
        print("PASS native production queued-video handoff/session/cancel/drain/lease")
    }
}
