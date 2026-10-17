import SwiftUI

typealias MemorySaveDirty = (MemoryLibraryRoot, String) -> Void

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
            ForEach(roots) { root in
                Section {
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
                                    row(document)
                                }
                            }
                            .disabled(!document.exists)
                        } else {
                            NavigationLink {
                                MemoryContentView(root: root, fileName: document.fileName, onSaveDirty: onSaveDirty)
                            } label: { row(document) }
                        }
                    }
                } header: { Text(root.title) }
                footer: { Text("Sharing saved Markdown does not change memory visibility or group access.") }
            }
            if documents.isEmpty { Text("No memory documents") }
            else if roots.allSatisfy({ filtered($0).isEmpty }) { Text("No matching memories") }
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
            $0.rootID == root.id && (term.isEmpty || $0.fileName.localizedCaseInsensitiveContains(term) ||
                root.title.localizedCaseInsensitiveContains(term) || $0.originalText.localizedCaseInsensitiveContains(term))
        }
    }

    private func row(_ document: MemoryDocumentStore.Snapshot) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(document.fileName)
            Text(document.exists ? String(document.originalText.prefix(140)) : AppLocalized("Not created — open to create GLOBAL.md"))
                .font(.caption).foregroundColor(.secondary).lineLimit(2)
        }
    }

    private func reload() {
        do {
            documents = try store.list()
            selected.formIntersection(Set(roots.flatMap { filtered($0) }.filter { $0.exists }.map { $0.id }))
            error = nil
        } catch {
            documents = []; selected.removeAll(); self.error = error.localizedDescription
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
