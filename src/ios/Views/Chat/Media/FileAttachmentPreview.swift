import Foundation
import QuickLook
import SwiftUI
import UIKit
import Darwin

// [T-queued-video-preview] The reusable cell emits a LOCAL queue intent only.
struct OpenQueuedVideoAction {
    var handler: (InputAttachment, UUID) -> Bool

    @discardableResult
    func callAsFunction(_ attachment: InputAttachment, messageID: UUID) -> Bool {
        handler(attachment, messageID)
    }
}

private struct OpenQueuedVideoKey: EnvironmentKey {
    static let defaultValue = OpenQueuedVideoAction { _, _ in false }
}

extension EnvironmentValues {
    var openQueuedVideo: OpenQueuedVideoAction {
        get { self[OpenQueuedVideoKey.self] }
        set { self[OpenQueuedVideoKey.self] = newValue }
    }
}

// MARK: - Queued video retained source (Foundation/POSIX; native fixture extracts this)

/// Independent copy owned by a presentation, never by the queue. No hard links:
/// cache and temporary directories can live on different volumes. Deletion is
/// off-main and only targets the unique directory created by this lease.
final class QueuedVideoPreviewLease: @unchecked Sendable {
    let url: URL
    private let directory: URL

    init(url: URL, directory: URL) {
        self.url = url
        self.directory = directory
    }

    deinit {
        let directory = directory
        DispatchQueue.global(qos: .utility).async {
            try? FileManager.default.removeItem(at: directory)
        }
    }
}

/// One bounded, nonblocking open at tap time pins the inode BEFORE the main
/// queue can drain/unlink it. Metadata, validation, and all byte IO are done by
/// the detached copy task. Only that single worker ever reads this handle.
final class QueuedVideoPreviewSource: @unchecked Sendable {
    enum Failure: Error { case invalidFile, cancelled, copyFailed }
    static let maximumBytes: Int64 = 512 * 1024 * 1024
    static let chunkBytes = 256 * 1024
    private let handle: FileHandle
    private let fileExtension: String

    init?(url: URL) {
        guard url.isFileURL else { return nil }
        let ext = url.pathExtension.lowercased()
        guard ["mp4", "mov", "m4v", "3gp", "3g2", "avi", "mkv", "webm", "mpg", "mpeg"].contains(ext) else { return nil }
        // NOFOLLOW rejects a final-component symlink; NONBLOCK means even a
        // malicious FIFO cannot stall a tap. fstat below rejects non-files.
        let descriptor = url.path.withCString {
            Darwin.open($0, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
        }
        guard descriptor >= 0 else { return nil }
        handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        fileExtension = ext
    }

    /// MUST run off-main. Fixed metadata + bounded chunks, not readToEnd/Data
    /// of a 60 MB video. The handle survives unlink during this copy as well.
    func retainCopy(isCancelled: () -> Bool) throws -> QueuedVideoPreviewLease {
        guard !isCancelled() else { throw Failure.cancelled }
        var metadata = stat()
        guard fstat(handle.fileDescriptor, &metadata) == 0,
              (metadata.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              metadata.st_size > 0, metadata.st_size <= Self.maximumBytes else {
            throw Failure.invalidFile
        }
        let manager = FileManager.default
        let directory = manager.temporaryDirectory
            .appendingPathComponent("queued-video-preview-" + UUID().uuidString, isDirectory: true)
        try manager.createDirectory(at: directory, withIntermediateDirectories: false,
                                    attributes: [.posixPermissions: 0o700])
        var committed = false
        defer { if !committed { try? manager.removeItem(at: directory) } }
        let destination = directory.appendingPathComponent("preview." + fileExtension)
        guard manager.createFile(atPath: destination.path, contents: nil,
                                 attributes: [.posixPermissions: 0o600]) else { throw Failure.copyFailed }
        let output = try FileHandle(forWritingTo: destination)
        defer { try? output.close() }
        try handle.seek(toOffset: 0)
        var remaining = Int64(metadata.st_size)
        while remaining > 0 {
            guard !isCancelled() else { throw Failure.cancelled }
            let count = Int(min(remaining, Int64(Self.chunkBytes)))
            guard let data = try handle.read(upToCount: count), !data.isEmpty else { throw Failure.copyFailed }
            try output.write(contentsOf: data)
            remaining -= Int64(data.count)
        }
        guard !isCancelled() else { throw Failure.cancelled }
        // Reject a source truncated/grown in place; unlink alone is harmless.
        var finalMetadata = stat()
        guard fstat(handle.fileDescriptor, &finalMetadata) == 0,
              finalMetadata.st_size == metadata.st_size else { throw Failure.invalidFile }
        let lease = QueuedVideoPreviewLease(url: destination, directory: directory)
        committed = true
        return lease
    }
}

// MARK: - End queued video retained source

// [T-file-group-preview-fix] A cell emits intent only. The stable list overlay
// owns presentation, and the owning VM supplies the session (never the global
// activeSessionId). Keep selection and items together in one immutable payload.
struct OpenFileAttachmentsAction {
    var handler: ([AttachmentMeta], UUID) -> Bool

    @discardableResult
    func callAsFunction(_ attachments: [AttachmentMeta], startingAt id: UUID) -> Bool {
        handler(attachments, id)
    }
}

private struct OpenFileAttachmentsKey: EnvironmentKey {
    static let defaultValue = OpenFileAttachmentsAction { _, _ in false }
}

extension EnvironmentValues {
    var openFileAttachments: OpenFileAttachmentsAction {
        get { self[OpenFileAttachmentsKey.self] }
        set { self[OpenFileAttachmentsKey.self] = newValue }
    }
}

// MARK: - Pure preview planning (also exercised by the standalone Swift tests)

/// AttachmentMeta.path is an unescaped Linux filename. URL(string:) would
/// interpret a literal # or ? as URL syntax, or reject spaces on older iOS.
/// URLComponents encodes the PATH exactly once, including literal percent signs.
enum FileAttachmentResourceURL {
    static func make(path: String) -> URL? {
        guard path.hasPrefix("/var/minis/") else { return nil }
        let relative = path.dropFirst("/var/minis/".count)
        let pieces = relative.split(separator: "/", maxSplits: 1, omittingEmptySubsequences: false)
        guard pieces.count == 2, !pieces[0].isEmpty, !pieces[1].isEmpty else { return nil }
        var components = URLComponents()
        components.scheme = "minis"
        components.host = String(pieces[0])
        components.path = "/" + String(pieces[1])
        return components.url
    }
}

struct FileAttachmentPreviewItem: Identifiable, Sendable {
    enum Kind: Sendable {
        case text, markdown, html, audio, video, document, share
    }
    let id: UUID
    let title: String
    let localURL: URL
    let kind: Kind
}

struct FileAttachmentPreviewGroup: Identifiable {
    let id = UUID()
    let ownerSessionId: String
    let items: [FileAttachmentPreviewItem]
    let selectedID: UUID
    let excludedCount: Int

    init?(ownerSessionId: String, items: [FileAttachmentPreviewItem], selectedID: UUID, excludedCount: Int) {
        // Filtering missing/unsupported siblings must not silently open the
        // first file instead of the one tapped. Selection is an attachment ID.
        guard !items.isEmpty, items.contains(where: { $0.id == selectedID }) else { return nil }
        self.ownerSessionId = ownerSessionId
        self.items = items
        self.selectedID = selectedID
        self.excludedCount = excludedCount
    }
}

// MARK: - Stable overlay presentation

enum FileAttachmentSheet: Identifiable {
    case preview(FileAttachmentPreviewGroup)
    case share(id: UUID, url: URL)

    var id: UUID {
        switch self {
        case .preview(let group): return group.id
        case .share(let id, _): return id
        }
    }
}

/// Fullscreen video presentation requested by tapping a sent video tile.
/// Videos never go through `.share`; they get a real player (2026-10-30).
struct FileAttachmentVideoPresentation: Identifiable {
    let id = UUID()
    let url: URL
    // The cover's immutable payload retains this even after reset/session
    // change sets videoSheet to nil, until its player actually disappears.
    let queuedLease: QueuedVideoPreviewLease?

    init(url: URL, queuedLease: QueuedVideoPreviewLease? = nil) {
        self.url = url
        self.queuedLease = queuedLease
    }
}

@MainActor
final class FileAttachmentPresenter: ObservableObject {
    @Published var sheet: FileAttachmentSheet?
    @Published var videoSheet: FileAttachmentVideoPresentation?
    @Published var unavailableName: String?
    private var ownerSessionId: String?
    private var requestToken = UUID()
    private var queuedVideoCopyTask: Task<QueuedVideoPreviewLease?, Never>?
    private let queuedVideoLogger = AppLogger(category: "QueuedVideoPreview")

    deinit { queuedVideoCopyTask?.cancel() }

    func bind(to sessionId: String?) {
        guard ownerSessionId != sessionId else { return }
        reset()
        ownerSessionId = sessionId
    }

    func reset() {
        requestToken = UUID()
        queuedVideoCopyTask?.cancel()
        queuedVideoCopyTask = nil
        sheet = nil
        videoSheet = nil
        unavailableName = nil
    }

    /// A queued preview is read-only. It never sends, withdraws, deletes the
    /// queue entry, or changes read state. Pin the source before returning to
    /// the runloop, then validate/copy off-main and hand off to openVideo.
    @discardableResult
    func openQueuedVideo(_ attachment: InputAttachment, sessionId: String?) -> Bool {
        queuedVideoLogger.info("[QueuedVideoPreview] stage=request")
        guard let sessionId, !sessionId.isEmpty, sessionId == ownerSessionId,
              attachment.kind == .video, attachment.loadState == .ready,
              attachment.cacheURL.isFileURL else {
            queuedVideoLogger.info("[QueuedVideoPreview] stage=rejected")
            return false
        }
        reset()
        guard let source = QueuedVideoPreviewSource(url: attachment.cacheURL) else {
            unavailableName = attachment.fileName
            queuedVideoLogger.info("[QueuedVideoPreview] stage=unavailable")
            return true
        }
        let token = requestToken
        let name = attachment.fileName
        let worker = Task.detached(priority: .userInitiated) { () -> QueuedVideoPreviewLease? in
            try? source.retainCopy(isCancelled: { Task.isCancelled })
        }
        queuedVideoCopyTask = worker
        Task { [weak self] in
            let lease = await worker.value
            guard let self else { return }
            guard self.requestToken == token, self.ownerSessionId == sessionId else {
                self.queuedVideoLogger.info("[QueuedVideoPreview] stage=discarded")
                return
            }
            self.queuedVideoCopyTask = nil
            guard let lease else {
                self.unavailableName = name
                self.queuedVideoLogger.info("[QueuedVideoPreview] stage=unavailable")
                return
            }
            self.queuedVideoLogger.info("[QueuedVideoPreview] stage=retained")
            self.openVideo(lease.url, queuedLease: lease)
        }
        return true
    }

    /// Called by this specific cover's disappearance, not by cell reuse.
    /// An old dismiss callback must never clear a newer presentation.
    func queuedVideoDidDisappear(id: UUID) {
        guard videoSheet?.id == id else { return }
        videoSheet = nil
        queuedVideoLogger.info("[QueuedVideoPreview] stage=closed")
    }

    /// Tapping a sent video opens the player directly. Previously the URL
    /// router had no video branch, classified `.mp4`/`.mov` as `.share`, and
    /// iOS popped the share sheet instead of playing the file.
    func openVideo(_ url: URL, queuedLease: QueuedVideoPreviewLease? = nil) {
        reset()
        videoSheet = FileAttachmentVideoPresentation(url: url, queuedLease: queuedLease)
        if queuedLease != nil { queuedVideoLogger.info("[QueuedVideoPreview] stage=present") }
    }

    func open(_ attachments: [AttachmentMeta], startingAt selectedID: UUID, sessionId: String?) {
        guard let tapped = attachments.first(where: { $0.id == selectedID }) else { return }
        // No owner means we cannot safely resolve a per-session attachment.
        // In particular, do NOT let the resolver guess activeSessionId.
        guard let sessionId, !sessionId.isEmpty, sessionId == ownerSessionId else {
            unavailableName = tapped.fileName
            return
        }
        reset()
        // Videos have a dedicated player. Do not let the generic file pager
        // classify .mp4 as an unknown document and open UIActivityViewController.
        if tapped.isVideo {
            guard let url = FileAttachmentResourceURL.make(path: tapped.path) else {
                unavailableName = tapped.fileName
                return
            }
            // The player needs a real file:// URL. AVPlayer given minis://
            // opens its chrome and then sits at 0:00 on black (2026-11-08).
            let token = requestToken
            let name = tapped.fileName
            Task { [weak self] in
                let local = await Task.detached(priority: .userInitiated) {
                    resolveMinisFileURL(url: url, sessionId: sessionId)
                }.value
                guard let self, self.requestToken == token, self.ownerSessionId == sessionId else { return }
                guard let local, local.isFileURL,
                      FileManager.default.fileExists(atPath: local.path) else {
                    self.unavailableName = name
                    return
                }
                self.openVideo(local)
            }
            return
        }
        let token = requestToken
        let candidates = tapped.pastedId != nil ? [tapped] : attachments.filter {
            !$0.isImage && !$0.isVideo && $0.pastedId == nil
        }
        // Capture value-only references for the off-main filesystem work.
        let references = candidates.compactMap { meta -> Reference? in
            guard let url = FileAttachmentResourceURL.make(path: meta.path) else { return nil }
            return Reference(id: meta.id, title: meta.fileName, url: url)
        }
        let tappedName = tapped.fileName
        let candidateCount = candidates.count
        Task { [weak self] in
            let resolved = await Task.detached(priority: .userInitiated) {
                references.compactMap { ref -> FileAttachmentPreviewItem? in
                    guard let local = resolveMinisFileURL(url: ref.url, sessionId: sessionId),
                          local.isFileURL else { return nil }
                    var isDirectory: ObjCBool = false
                    guard FileManager.default.fileExists(atPath: local.path, isDirectory: &isDirectory),
                          !isDirectory.boolValue,
                          FileManager.default.isReadableFile(atPath: local.path) else { return nil }
                    let ext = local.pathExtension.lowercased()
                    let kind: FileAttachmentPreviewItem.Kind
                    if minisMarkdownExtensions.contains(ext) { kind = .markdown }
                    else if minisTextExtensions.contains(ext) { kind = .text }
                    else if minisHTMLExtensions.contains(ext) { kind = .html }
                    else if minisAudioExtensions.contains(ext) { kind = .audio }
                    else if minisDocumentExtensions.contains(ext) { kind = .document }
                    else if minisVideoExtensions.contains(ext) { kind = .video }
                    else { kind = .share }
                    return FileAttachmentPreviewItem(id: ref.id, title: ref.title, localURL: local, kind: kind)
                }
            }.value
            guard let self, self.requestToken == token, self.ownerSessionId == sessionId else { return }
            guard resolved.contains(where: { $0.id == selectedID }) else {
                self.unavailableName = tappedName
                return
            }
            func canPreview(_ item: FileAttachmentPreviewItem) -> Bool {
                switch item.kind {
                case .share: return false
                case .document: return QLPreviewController.canPreview(item.localURL as NSURL)
                default: return true
                }
            }
            // Unsupported formats join the pager as a share-only page, so a
            // message with several .deb/.zip files still swipes left/right.
            // A single non-previewable file keeps the original direct share
            // sheet (no extra tap just to reach the same sheet).
            let items = resolved
            if items.count == 1, !canPreview(items[0]) {
                self.sheet = .share(id: UUID(), url: items[0].localURL)
                return
            }
            guard let group = FileAttachmentPreviewGroup(
                ownerSessionId: sessionId, items: items, selectedID: selectedID,
                excludedCount: candidateCount - items.count
            ) else {
                self.unavailableName = tappedName
                return
            }
            self.sheet = .preview(group)
        }
    }

    private struct Reference: Sendable {
        let id: UUID
        let title: String
        let url: URL
    }
}

// MARK: - Mixed-format pager (one message, original attachment order)

struct FileAttachmentGroupPreview: View {
    let group: FileAttachmentPreviewGroup
    let onClose: () -> Void
    @State private var selectedID: UUID
    @State private var expandedHTML: URL?

    init(group: FileAttachmentPreviewGroup, onClose: @escaping () -> Void) {
        self.group = group
        self.onClose = onClose
        _selectedID = State(initialValue: group.selectedID)
    }

    var body: some View {
        VStack(spacing: 0) {
            TabView(selection: $selectedID) {
                ForEach(group.items) { item in
                    Group {
                        // TabView preloads neighbours. Do not autoplay another
                        // audio file or launch a neighbour's WKWebView/QuickLook.
                        if item.id == selectedID {
                            page(for: item)
                        } else {
                            Color.clear
                        }
                    }
                    .tag(item.id)
                    .id(item.id)
                }
            }
            .tabViewStyle(PageTabViewStyle(indexDisplayMode: .never))

            if group.items.count > 1 || group.excludedCount > 0 {
                pagingBar
            }
        }
        .modifier(WideSheetSizingModifier())
        .fullScreenCover(item: $expandedHTML) { url in
            // Expansion is a child cover: closing it returns to the same
            // attachment page instead of dismantling the group sheet.
            MinisSafariView(url: url, localFile: true, onCollapse: { expandedHTML = nil })
        }
    }

    @ViewBuilder
    private func page(for item: FileAttachmentPreviewItem) -> some View {
        switch item.kind {
        case .text:
            MinisTextPreviewView(fileURL: item.localURL, onClose: onClose)
        case .markdown:
            MinisMarkdownPreviewView(fileURL: item.localURL, onClose: onClose)
        case .html:
            MinisHTMLPreviewView(fileURL: item.localURL, onExpand: { _ in
                expandedHTML = item.localURL
            }, onClose: onClose, sourceSessionId: group.ownerSessionId)
        case .audio:
            MinisAudioPreviewView(fileURL: item.localURL, onClose: onClose)
        case .video:
            MinisVideoFullscreenPlayer(fileURL: item.localURL)
        case .document:
            FileAttachmentDocumentPage(item: item, onClose: onClose)
        case .share:
            // Not normally included by the planner. A defensive fallback,
            // never a silent empty page if a new file kind is added later.
            FileAttachmentUnavailablePage(item: item, onClose: onClose)
        }
    }

    private var selectedIndex: Int {
        group.items.firstIndex(where: { $0.id == selectedID }) ?? 0
    }

    private var pagingBar: some View {
        HStack(spacing: 12) {
            Button { select(offset: -1) } label: {
                Image(systemName: "chevron.left").frame(width: 44, height: 36)
            }
            .disabled(selectedIndex == 0)
            .accessibilityLabel(AppLocalized("Previous File"))
            VStack(spacing: 2) {
                Text("\(selectedIndex + 1) / \(group.items.count)")
                    .font(.caption.monospacedDigit())
                if group.excludedCount > 0 {
                    Text(AppLocalized("Some attachments cannot be previewed"))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity)
            Button { select(offset: 1) } label: {
                Image(systemName: "chevron.right").frame(width: 44, height: 36)
            }
            .disabled(selectedIndex + 1 >= group.items.count)
            .accessibilityLabel(AppLocalized("Next File"))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 12)
        .background(Color(UIColor.secondarySystemBackground))
    }

    private func select(offset: Int) {
        let next = selectedIndex + offset
        guard group.items.indices.contains(next) else { return }
        selectedID = group.items[next].id
    }
}

/// Only real, readable file URLs reach this data source. The outer page owns
/// Done/Share explicitly; a child QLPreviewController has no modal toolbar.
private struct FileAttachmentDocumentContent: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> QLPreviewController {
        let controller = QLPreviewController()
        controller.dataSource = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: QLPreviewController, context: Context) {
        guard context.coordinator.url != url else { return }
        context.coordinator.url = url
        controller.reloadData()
    }

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }
        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem {
            url as NSURL
        }
    }
}

private struct FileAttachmentDocumentPage: View {
    let item: FileAttachmentPreviewItem
    let onClose: () -> Void
    @State private var showShare = false

    var body: some View {
        NavigationView {
            FileAttachmentDocumentContent(url: item.localURL)
                .navigationTitle(item.title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(AppLocalized("Done"), action: onClose)
                    }
                    ToolbarItem(placement: .primaryAction) {
                        Button { showShare = true } label: {
                            Image(systemName: "square.and.arrow.up")
                        }
                        .accessibilityLabel(AppLocalized("Share"))
                    }
                }
        }
        .navigationViewStyle(.stack)
        .sheet(isPresented: $showShare) { MinisShareSheet(url: item.localURL) }
    }
}

private struct FileAttachmentUnavailablePage: View {
    let item: FileAttachmentPreviewItem
    let onClose: () -> Void
    @State private var showShare = false

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                Image(systemName: "doc").font(.largeTitle)
                Text(AppLocalized("Preview unavailable"))
                Button(AppLocalized("Share")) { showShare = true }
            }
            .navigationTitle(item.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("Done"), action: onClose)
                }
            }
        }
        .navigationViewStyle(.stack)
        .sheet(isPresented: $showShare) { MinisShareSheet(url: item.localURL) }
    }
}
