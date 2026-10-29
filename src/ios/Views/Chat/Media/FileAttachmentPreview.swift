import Foundation
import QuickLook
import SwiftUI

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
        case text, markdown, html, audio, document, share
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

@MainActor
final class FileAttachmentPresenter: ObservableObject {
    @Published var sheet: FileAttachmentSheet?
    @Published var unavailableName: String?
    private var ownerSessionId: String?
    private var requestToken = UUID()

    func bind(to sessionId: String?) {
        guard ownerSessionId != sessionId else { return }
        reset()
        ownerSessionId = sessionId
    }

    func reset() {
        requestToken = UUID()
        sheet = nil
        unavailableName = nil
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
                    else { kind = .share }
                    return FileAttachmentPreviewItem(id: ref.id, title: ref.title, localURL: local, kind: kind)
                }
            }.value
            guard let self, self.requestToken == token, self.ownerSessionId == sessionId else { return }
            guard let selected = resolved.first(where: { $0.id == selectedID }) else {
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
            // Unknown formats retain the original share/export fallback, not
            // an empty QuickLook page. They never auto-open while paging.
            guard canPreview(selected) else {
                self.sheet = .share(id: UUID(), url: selected.localURL)
                return
            }
            let items = resolved.filter { canPreview($0) }
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
