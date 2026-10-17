//
//  MemoryManagementView.swift
//  MinisApp
//
//  Settings-level memory management: unified file list with edit/delete.
//

import SwiftUI

struct MemoryManagementView: View {
    @State private var forceSyncToast: String?
    /// [T-memory-global-toggle-settings-ui-ios] Global default for whether
    /// a NEW session starts with memory enabled. Default true preserves
    /// today's behavior. Already-created sessions keep their own per-
    /// session memoryEnabled value (toggled via the /memory slash command)
    /// and are not affected when this global is changed.
    @AppStorage("memory.global.enabled") private var memoryGlobalEnabled: Bool = true

    var body: some View {
        // One real shared directory, not a per-model/group facade. The library
        // reuses MemoryContentView -> MemoryFileEditView for document actions.
        ScopedMemoryLibraryView(title: AppLocalized("Memory"), roots: [.sharedMemory]) {
            Section {
                Toggle(AppLocalized("settings_memory_global_enabled"), isOn: $memoryGlobalEnabled)
            } footer: {
                Text(AppLocalized("settings_memory_global_enabled_footer"))
            }
        }
        .toolbar {

                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button {
                            Task { if #available(iOS 17.0, *) { await forceSyncMemory() } }
                        } label: {
                            Label(AppLocalized("Force iCloud Sync"),
                                  systemImage: "arrow.triangle.2.circlepath.icloud")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            
        }
        .overlay(alignment: .top) {
            if let msg = forceSyncToast {
                Text(msg)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.accentColor, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.3), value: forceSyncToast)
    }

    @available(iOS 17.0, *)
    private func forceSyncMemory() async {
        let count = await ForceSyncHelper.markMemoryDirty()
        await ForceSyncHelper.bidirectionalSync(
            recordTypes: ["MemoryGlobalV2", "MemoryDailyV2"])
        forceSyncToast = AppLocalized("Synced \(count) memory files")
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            forceSyncToast = nil
        }
    }

}

extension MemoryLibraryRoot {
    /// These files really are shared by every session today. `isGlobal` only
    /// enables the existing sync mapping; it is NOT a group-access boundary.
    static var sharedMemory: MemoryLibraryRoot {
        MemoryLibraryRoot(id: "shared-memory", title: AppLocalized("Global Memory"),
                          directory: AIChatViewModel.minisMemoryPersistentDir,
                          isReadOnly: false, isGlobal: true)
    }
}

// MARK: - Memory File Edit View

@MainActor
struct MemoryFileEditView: View {
    let root: MemoryLibraryRoot
    let snapshot: MemoryDocumentStore.Snapshot
    let onSaveDirty: MemorySaveDirty?
    let onSaved: (MemoryDocumentStore.Snapshot) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var content: String
    @State private var saveError: String?
    private let store: MemoryDocumentStore

    init(root: MemoryLibraryRoot, snapshot: MemoryDocumentStore.Snapshot,
         onSaveDirty: MemorySaveDirty? = nil,
         onSaved: @escaping (MemoryDocumentStore.Snapshot) -> Void) {
        self.root = root
        self.snapshot = snapshot
        self.onSaveDirty = onSaveDirty
        self.onSaved = onSaved
        self.store = MemoryDocumentStore(roots: [root])
        _content = State(initialValue: snapshot.originalText)
    }

    private var fileName: String { snapshot.fileName }
    private var isGlobal: Bool { root.isGlobal && fileName == "GLOBAL.md" }

    var body: some View {
        VStack(spacing: 0) {
            if isGlobal {
                Text("Persistent instructions and preferences visible to the agent in every session. You can edit it here, or just ask the agent to help organize and update this memory.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
            }

            if let saveError {
                Text(saveError)
                    .foregroundStyle(.red)
                    .font(.caption)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 4)
            }

            if root.isReadOnly {
                Label("Read-only", systemImage: "lock")
                    .font(.caption)
                    .padding(.horizontal, 16)
            }
            Text("Save or cancel this draft before sharing.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 16)

            TextEditor(text: $content)
                .font(.system(.caption, design: .monospaced))
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .disabled(root.isReadOnly)
        }
        // Daily-log path renders only the TextEditor inside the VStack —
        // without an explicit container max-height the TextEditor's
        // intrinsic content size collapses to 0 on iOS 26 and the file
        // body never appears (user screenshot 2026-05-23 17:02 — fully
        // blank pane under "2026-05-21.md" nav title). Anchor the VStack
        // to the available space so the TextEditor has somewhere to live.
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle(fileName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                // Cancelling never writes, marks dirty, or announces success.
                Button("Cancel") { dismiss() }
            }
            // [T-global-memory-save-always-visible] Do not depend on onChange
            // for Save visibility (paste/IME can defer that callback).
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") { save() }.disabled(root.isReadOnly)
            }
        }
        // A sheet owns an immutable base snapshot. Notifications cannot
        // overwrite even an unchanged/empty draft; save performs byte CAS.
        .interactiveDismissDisabled(true)
    }

    private func save() {
        do {
            let saved = try store.save(snapshot, text: content)
            saveError = nil
            if let onSaveDirty = onSaveDirty { onSaveDirty(root, fileName) }
            else { markGlobalMemoryDirty(root: root, fileName: fileName) }
            onSaved(saved)
            NotificationCenter.default.post(name: .memoryFilesDidChange, object: nil)
            dismiss()
        } catch {
            // Keep both editor and draft open. Read-only, encoding, conflict,
            // coordination, and I/O failures never emit Saved/dirty/refresh.
            saveError = error.localizedDescription
        }
    }
}

extension Notification.Name {
    /// Posted after a memory file (GLOBAL.md or daily log) is written
    /// locally — either by the user editing in MemoryManagementView, by
    /// memory_write tool, or by an inbound iCloud sync merge. Observers
    /// can use this to refresh their in-memory snapshot of memory files.
    static let memoryFilesDidChange = Notification.Name("com.openminis.app.memoryFilesDidChange")
}
