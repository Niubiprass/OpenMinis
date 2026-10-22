import SwiftUI

typealias MemorySaveDirty = (MemoryLibraryRoot, String) -> Void

private struct MemoryRootSection: Identifiable {
    let title: String
    let roots: [MemoryLibraryRoot]
    var id: String { title }
}

/// Caller-supplied roots describe real directories only. This view does not
/// create per-group stores or change the agent's memory visibility.
@MainActor
struct ScopedMemoryLibraryView<Header: View>: View {
    private let title: String
    private let roots: [MemoryLibraryRoot]
    private let store: MemoryDocumentStore
    private let onSaveDirty: MemorySaveDirty?
    private let header: Header
    @State private var documents: [MemoryDocumentStore.Snapshot] = []
    @State private var isLibraryVisible = false
    @State private var loaded = false
    @State private var reloadGeneration = 0
    @State private var query = ""
    @State private var selecting = false
    @State private var selected: Set<String> = []
    @State private var error: String?
    @State private var share: MemoryShareItem?

    init(title: String, roots: [MemoryLibraryRoot], onSaveDirty: MemorySaveDirty? = nil,
         @ViewBuilder header: () -> Header) {
        self.title = title
        self.roots = roots
        self.store = MemoryDocumentStore(roots: roots)
        self.onSaveDirty = onSaveDirty
        self.header = header()
    }

    var body: some View {
        List {
            header
            if !loaded {
                HStack {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
                .padding(.vertical, 24)
            } else if sections.isEmpty {
                Text(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                     ? AppLocalized("No memory documents")
                     : AppLocalized("No matching memories"))
                    .foregroundStyle(.secondary)
            } else {
                ForEach(sections) { section in
                    Section {
                        ForEach(section.roots) { root in
                            if root.title != section.title {
                                Text(root.title)
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.secondary)
                            }
                            if root.isReadOnly {
                                Label("Read-only", systemImage: "lock")
                            }
                            ForEach(filtered(root)) { document in
                                if selecting {
                                    Button {
                                        if !selected.insert(document.id).inserted { selected.remove(document.id) }
                                    } label: {
                                        HStack {
                                            Image(systemName: selected.contains(document.id) ? "checkmark.circle.fill" : "circle")
                                            row(document, root: root)
                                        }
                                    }
                                    .disabled(!document.exists)
                                } else {
                                    NavigationLink {
                                        MemoryContentView(root: root, fileName: document.fileName, onSaveDirty: onSaveDirty)
                                    } label: { row(document, root: root) }
                                }
                            }
                        }
                    } header: { Text(section.title) }
                }
                Section {
                } footer: {
                    Text("Sharing saved Markdown does not change memory visibility or group access.")
                }
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "Search memories")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(selecting ? AppLocalized("Done") : AppLocalized("Select")) {
                    selecting.toggle(); selected.removeAll()
                }
            }
            ToolbarItem(placement: .bottomBar) {
                if selecting {
                    Button { shareSelected() } label: {
                        Label(String(format: AppLocalized("Share (%lld)"), Int64(selected.count)),
                              systemImage: "square.and.arrow.up")
                    }
                        .disabled(selected.isEmpty)
                }
            }
        }
        .onAppear { isLibraryVisible = true; reload() }
        .onDisappear { isLibraryVisible = false }
        .onReceive(NotificationCenter.default.publisher(for: .memoryFilesDidChange)) { _ in
            // Do not remove a navigation row underneath an open document/draft.
            guard isLibraryVisible else { return }
            reload()
        }
        .onChange(of: roots.map { $0.id }) { _ in
            // Persona list / group list can arrive after the first render (the
            // folder lookup is async). Without this, the rows came from the
            // previous root set and the new section looked empty.
            reload()
        }
        .onChange(of: query) { _ in
            // Hidden search results must not be accidentally shared.
            selected.formIntersection(Set(roots.flatMap { filtered($0) }.map { $0.id }))
        }
        .sheet(item: $share) { MinisShareSheet(url: $0.url) }
        .alert("Memory error", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK", role: .cancel) { error = nil }
        } message: { Text(error ?? "") }
    }

    private func filtered(_ root: MemoryLibraryRoot) -> [MemoryDocumentStore.Snapshot] {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return documents.filter {
            $0.rootID == root.id
                && (root.nameFilter?($0.fileName) ?? true)
                && (term.isEmpty || $0.fileName.localizedCaseInsensitiveContains(term) ||
                root.title.localizedCaseInsensitiveContains(term) || $0.originalText.localizedCaseInsensitiveContains(term))
        }
    }

    /// Group roots under one visible header (all personas under 「人格记忆」,
    /// all group memories under 「分组记忆」) and drop empty sections. This is
    /// what removes the long wall of empty headers on the memory page.
    private var sections: [MemoryRootSection] {
        var order: [String] = []
        var buckets: [String: [MemoryLibraryRoot]] = [:]
        for root in roots {
            let hasRows = !filtered(root).isEmpty
            guard root.alwaysShow || hasRows else { continue }
            if buckets[root.sectionTitle] == nil { order.append(root.sectionTitle) }
            buckets[root.sectionTitle, default: []].append(root)
        }
        return order.map { MemoryRootSection(title: $0, roots: buckets[$0] ?? []) }
    }

    private func row(_ document: MemoryDocumentStore.Snapshot, root: MemoryLibraryRoot) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(root.itemTitle ?? document.fileName)
            Text(root.itemSubtitle
                 ?? (document.exists
                     ? String(document.originalText.prefix(140))
                     : AppLocalized("Not created — open to create GLOBAL.md")))
                .font(.caption).foregroundColor(.secondary).lineLimit(2)
        }
    }

    private func reload() {
        // File I/O belongs off the main thread: the memory page can contain
        // hundreds of daily/group files, and a synchronous `list()` here was
        // one more way to hold up the first frame. A generation counter drops
        // an older result if the user switched tabs/roots while it ran.
        reloadGeneration += 1
        let generation = reloadGeneration
        let store = self.store
        Task.detached(priority: .userInitiated) {
            let result = Result { try store.list() }
            await MainActor.run {
                guard generation == reloadGeneration else { return }
                switch result {
                case .success(let list):
                    documents = list
                    selected.formIntersection(Set(roots.flatMap { filtered($0) }.filter { $0.exists }.map { $0.id }))
                    error = nil
                case .failure(let failure):
                    documents = []
                    selected.removeAll()
                    error = failure.localizedDescription
                }
                loaded = true
            }
        }
    }

    private func shareSelected() {
        do { share = MemoryShareItem(url: try store.export(documents.filter { selected.contains($0.id) })) }
        catch { self.error = error.localizedDescription }
    }
}

extension ScopedMemoryLibraryView where Header == EmptyView {
    init(title: String, roots: [MemoryLibraryRoot], onSaveDirty: MemorySaveDirty? = nil) {
        self.init(title: title, roots: roots, onSaveDirty: onSaveDirty) { EmptyView() }
    }
}

/// Preserves the draft's public entry point without a second editor/share implementation.
@MainActor
struct ScopedMemoryDocumentView: View {
    let root: MemoryLibraryRoot
    let fileName: String
    var onSaveDirty: MemorySaveDirty? = nil

    var body: some View {
        MemoryContentView(root: root, fileName: fileName, onSaveDirty: onSaveDirty)
    }
}

/// A custom callback replaces this default; it never decides which roots are visible.
@MainActor
func markGlobalMemoryDirty(root: MemoryLibraryRoot, fileName: String) {
    guard root.isGlobal else { return }
    let recordType: String
    let recordID: String
    switch fileName {
    case "GLOBAL.md": recordType = "MemoryGlobalV2"; recordID = "memory-global"
    case "SOUL.md":
        SoulStore.refreshCache()
        recordType = "SoulV2"; recordID = "soul"
    default:
        guard fileName.range(of: #"^\d{4}-\d{2}-\d{2}\.md$"#, options: .regularExpression) != nil else { return }
        let stem = String(fileName.dropLast(3))
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"; formatter.isLenient = false
        guard let date = formatter.date(from: stem), formatter.string(from: date) == stem else { return }
        recordType = "MemoryDailyV2"; recordID = stem
    }
    Task { await ChatStore.shared.markDirty(recordType: recordType, recordId: recordID) }
}

struct MemoryShareItem: Identifiable {
    let id = UUID()
    let url: URL
}
