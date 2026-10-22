//
//  MemoryManagementView.swift
//  MinisApp
//
//  Settings-level memory management: unified file list with edit/delete.
//

import SwiftUI
import UniformTypeIdentifiers
import UIKit

private enum MemoryTab: String, CaseIterable, Identifiable {
    case daily
    case global
    case persona

    var id: String { rawValue }

    var title: String {
        switch self {
        case .daily: return AppLocalized("日记忆")
        case .global: return AppLocalized("全局")
        case .persona: return AppLocalized("人格")
        }
    }
}

struct MemoryManagementView: View {
    @State private var forceSyncToast: String?
    /// [T-memory-global-toggle-settings-ui-ios] Global default for whether
    /// a NEW session starts with memory enabled. Default true preserves
    /// today's behavior. Already-created sessions keep their own per-
    /// session memoryEnabled value (toggled via the /memory slash command)
    /// and are not affected when this global is changed.
    @AppStorage("memory.global.enabled") private var memoryGlobalEnabled: Bool = true
    /// [T-memory-import] Sheet + result toast.
    @State private var showImport = false
    @State private var importToast: String?
    @ObservedObject private var personaStore = PersonaStore.shared
    @ObservedObject private var sharedStore = SharedMemoryStore.shared
    @State private var folderMemoryRoots: [MemoryLibraryRoot] = []
    @State private var personaEntryCounts: [String: Int] = [:]
    @State private var memoryWarning: String?
    @State private var tab: MemoryTab = .daily
    @State private var exportShare: MemoryShareItem?

    private var memoryDirectory: URL { AIChatViewModel.minisMemoryPersistentDir }
    private var personaDirectory: URL {
        memoryDirectory.appendingPathComponent("personas", isDirectory: true)
    }

    private func dayStamp(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    private func monthStamp(_ date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM"
        return formatter.string(from: date)
    }

    /// The page is split into three tabs. Keeping the roots tab-specific is
    /// what stops one long list of daily + global + every persona + every
    /// group from being shown at once.
    private var memoryRoots: [MemoryLibraryRoot] {
        switch tab {
        case .daily:
            return dailyRoots + folderMemoryRoots
        case .global:
            return [globalRoot]
        case .persona:
            return personaRoots
        }
    }

    private var dailyRoots: [MemoryLibraryRoot] {
        let dir = memoryDirectory
        let today = dayStamp()
        let month = monthStamp()
        let dayPattern = #"^\d{4}-\d{2}-\d{2}\.md$"#
        let monthPattern = #"^\d{4}-\d{2}\.md$"#
        let todayRoot = MemoryLibraryRoot(
            id: "daily-today",
            title: AppLocalized("今天"),
            directory: dir,
            isReadOnly: false,
            isGlobal: false,
            nameFilter: { $0 == "\(today).md" },
            sectionTitle: AppLocalized("今天"))
        let monthRoot = MemoryLibraryRoot(
            id: "daily-month",
            title: AppLocalized("本月"),
            directory: dir,
            isReadOnly: false,
            isGlobal: false,
            nameFilter: { name in
                name != "\(today).md"
                    && name.hasPrefix("\(month)-")
                    && name.hasSuffix(".md")
            },
            sectionTitle: AppLocalized("本月"))
        let olderDailyRoot = MemoryLibraryRoot(
            id: "daily-older",
            title: AppLocalized("更早（月记忆）"),
            directory: dir,
            isReadOnly: false,
            isGlobal: false,
            nameFilter: { name in
                name.range(of: dayPattern, options: .regularExpression) != nil
                    && !name.hasPrefix("\(month)-")
            },
            sectionTitle: AppLocalized("更早（月记忆）"))
        let monthlyRoot = MemoryLibraryRoot(
            id: "daily-monthly",
            title: AppLocalized("更早（月记忆）"),
            directory: dir,
            isReadOnly: false,
            isGlobal: false,
            nameFilter: { $0.range(of: monthPattern, options: .regularExpression) != nil },
            sectionTitle: AppLocalized("更早（月记忆）"))
        return [todayRoot, monthRoot, monthlyRoot, olderDailyRoot]
    }

    private var globalRoot: MemoryLibraryRoot {
        MemoryLibraryRoot(
            id: "global-memory",
            title: AppLocalized("全局记忆"),
            directory: memoryDirectory,
            isReadOnly: false,
            isGlobal: true,
            nameFilter: { $0 == "GLOBAL.md" },
            sectionTitle: AppLocalized("全局记忆"),
            itemTitle: "GLOBAL.md",
            alwaysShow: true)
    }

    private var personaRoots: [MemoryLibraryRoot] {
        let personaDir = personaDirectory
        let knownFiles = Set(personaStore.personas.map { "\($0.id).md" })
        var roots: [MemoryLibraryRoot] = personaStore.personas.map { persona in
            let count = personaEntryCounts[persona.id] ?? 0
            let countText = count > 0
                ? String(format: AppLocalized("%lld 条"), Int64(count))
                : AppLocalized("还没有记忆")
            let subtitle = persona.style.isEmpty ? countText : "\(countText) · \(persona.style)"
            return MemoryLibraryRoot(
                id: "persona-\(persona.id)",
                title: AppLocalized("人格记忆"),
                directory: personaDir,
                isReadOnly: false,
                isGlobal: false,
                nameFilter: { $0 == "\(persona.id).md" },
                sectionTitle: AppLocalized("人格记忆"),
                itemTitle: persona.name,
                itemSubtitle: subtitle)
        }
        roots.append(MemoryLibraryRoot(
            id: "persona-orphan",
            title: AppLocalized("未归属"),
            directory: personaDir,
            isReadOnly: false,
            isGlobal: false,
            nameFilter: { !knownFiles.contains($0) },
            sectionTitle: AppLocalized("未归属")))
        return roots
    }

    var body: some View {
        VStack(spacing: 0) {
            Picker(AppLocalized("记忆分类"), selection: $tab) {
                ForEach(MemoryTab.allCases) { item in
                    Text(item.title).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)

            // One real shared directory, not a per-model/group facade. The library
            // reuses MemoryContentView -> MemoryFileEditView for document actions.
            ScopedMemoryLibraryView(title: AppLocalized("Memory"), roots: memoryRoots,
                                    onShare: { url in
                                        exportShare = MemoryShareItem(url: url)
                                    }) {
            Section {
                Toggle(AppLocalized("settings_memory_global_enabled"), isOn: $memoryGlobalEnabled)
                if let memoryWarning {
                    Text(memoryWarning).font(.caption).foregroundStyle(.orange)
                }
            } footer: {
                Text(AppLocalized("settings_memory_global_enabled_footer"))
            }
            Section {
                NavigationLink {
                    SharedMemoryListView()
                } label: {
                    HStack {
                        Label(AppLocalized("共享给我"), systemImage: "tray.full")
                        Spacer()
                        Text("\(sharedStore.records.count)")
                            .foregroundStyle(.secondary)
                    }
                }
            } footer: {
                Text(AppLocalized("共享记忆是只读快照；点“复制到我的记忆”后才进入你自己的人格记忆。"))
            }
            }
            .id(tab)
        }
        .onAppear {
            try? FileManager.default.createDirectory(
                at: AIChatViewModel.minisMemoryPersistentDir.appendingPathComponent("personas", isDirectory: true),
                withIntermediateDirectories: true)
        }
        .task {
            await loadFolderMemoryRoots()
            refreshPersonaCounts()
            let result = await Task.detached(priority: .utility) {
                MemoryMaintenance.runIfNeeded()
            }.value
            await MainActor.run { memoryWarning = result.warning }
        }
        .onReceive(NotificationCenter.default.publisher(for: .personaDidChange)) { _ in
            refreshPersonaCounts()
        }
        .onReceive(NotificationCenter.default.publisher(for: .memoryFilesDidChange)) { _ in
            refreshPersonaCounts()
        }
        .toolbar {

                // [T-memory-import] Import entry. Sits before the ellipsis so
                // it stays a one-tap action; the sheet asks for the destination
                // and resolves same-name conflicts explicitly.
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showImport = true
                    } label: {
                        Label(AppLocalized("导入"), systemImage: "square.and.arrow.down")
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button {
                            exportAllMemory()
                        } label: {
                            Label(AppLocalized("导出全部记忆"), systemImage: "square.and.arrow.up")
                        }
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
        .sheet(item: $exportShare) { MinisShareSheet(url: $0.url) }
        .sheet(isPresented: $showImport) {
            MemoryImportView(store: MemoryDocumentStore(roots: [.sharedMemory])) { message in
                importToast = message
                DispatchQueue.main.asyncAfter(deadline: .now() + 3) { importToast = nil }
            }
        }
        .overlay(alignment: .top) {
            if let msg = importToast {
                Text(msg)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.green, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
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

    private func refreshPersonaCounts() {
        let ids = personaStore.personas.map { $0.id }
        Task.detached(priority: .utility) {
            var counts: [String: Int] = [:]
            for id in ids {
                counts[id] = PersonaStore.shared.memoryEntryCount(for: id)
            }
            await MainActor.run { personaEntryCounts = counts }
        }
    }

    /// [T-memory-export-all] One ZIP with every memory file. The existing
    /// per-file share stays; this is the "take everything" entry. Store-only
    /// ZIP writer is the one already used for skill archives, so no new
    /// dependency and no full backup pipeline.
    private func exportAllMemory() {
        let roots = dailyRoots + [globalRoot] + personaRoots + folderMemoryRoots
        let store = MemoryDocumentStore(roots: roots)
        var extras: [(relativePath: String, data: Data)] = []
        if let data = try? JSONEncoder().encode(personaStore.personas) {
            extras.append(("personas.json", data))
        }
        let soul = memoryDirectory.appendingPathComponent("SOUL.md")
        if let data = try? Data(contentsOf: soul) {
            extras.append(("soul/SOUL.md", data))
        }
        do {
            exportShare = MemoryShareItem(url: try store.exportArchive(extraFiles: extras))
        } catch {
            forceSyncToast = AppLocalized("没有可导出的记忆")
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { forceSyncToast = nil }
        }
    }

    /// Only folders that actually chose independent memory get a section.
    private func loadFolderMemoryRoots() async {
        let folders = await ChatStore.shared.listFolders()
        var roots: [MemoryLibraryRoot] = []
        for folder in folders {
            guard let config = try? await ChatStore.shared.getFolderConfiguration(folder.id),
                  config.memoryPolicy == .folder else { continue }
            let dir = AIChatViewModel.minisFolderMemoryPersistentDir(for: folder.id)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            roots.append(MemoryLibraryRoot(
                id: "folder-\(folder.id)",
                title: folder.name,
                directory: dir,
                isReadOnly: false,
                isGlobal: false,
                sectionTitle: AppLocalized("分组记忆")))
        }
        await MainActor.run { folderMemoryRoots = roots }
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

// MARK: - [T-memory-import] Import memory files

/// Where an imported document lands. Chosen explicitly by the user every
/// time — an import never writes straight into a folder.
enum MemoryImportTarget: String, CaseIterable, Identifiable {
    case globalMemory
    case dailyMemory
    case customName

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .globalMemory: return "全局记忆"
        case .dailyMemory: return "作为每日记忆"
        case .customName: return "自定义文件名"
        }
    }

    var subtitleKey: String {
        switch self {
        case .globalMemory: return "所有会话都能读到"
        case .dailyMemory: return "按文件名日期归档，如 2026-10-19.md"
        case .customName: return "手动输入文件名，存入全局记忆目录"
        }
    }
}

/// Same-name policy, asked per conflicting file.
enum MemoryImportConflict: String, Identifiable {
    case overwrite
    case rename
    case skip

    var id: String { rawValue }
}

/// One import request in flight. Held by the sheet so a conflict prompt can
/// resume the exact same payload after the user chooses.
private struct MemoryImportRequest {
    var fileName: String
    var text: String
    var target: MemoryImportTarget
}

/// Import sheet: pick a source, choose a destination, then confirm.
///
/// Sources covered: the Files picker, the clipboard, and any Markdown handed
/// to the app by another app's share sheet (see `MemoryImportInbox`).
struct MemoryImportView: View {
    /// Pre-loaded content, used when another app shared a file into Minis.
    struct Prefill {
        let fileName: String
        let text: String
    }

    let store: MemoryDocumentStore
    var prefill: Prefill? = nil
    var onFinished: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var target: MemoryImportTarget = .globalMemory
    @State private var fileName = ""
    @State private var text = ""
    @State private var hasPayload = false
    @State private var didApplyPrefill = false
    @State private var showFilePicker = false
    @State private var conflict: MemoryImportConflict?
    @State private var pending: MemoryImportRequest?
    @State private var errorMessage: String?
    @State private var busy = false

    var body: some View {
        NavigationView {
            Form {
                Section {
                    Button {
                        showFilePicker = true
                    } label: {
                        Label("从「文件」选择", systemImage: "folder")
                    }
                    Button {
                        pasteFromClipboard()
                    } label: {
                        Label("从剪贴板导入", systemImage: "doc.on.clipboard")
                    }
                } header: {
                    Text("来源")
                }

                if hasPayload {
                    Section {
                        TextField("文件名", text: $fileName)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                        Text(String(format: AppLocalized("已读取 %lld 个字符"), Int64(text.count)))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } header: {
                        Text("文件名")
                    }

                    Section {
                        ForEach(MemoryImportTarget.allCases) { option in
                            Button {
                                target = option
                                applyTargetNaming()
                            } label: {
                                HStack(alignment: .top, spacing: 10) {
                                    Image(systemName: target == option ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(target == option ? Color.accentColor : Color.secondary)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(AppLocalized(option.titleKey))
                                            .foregroundStyle(.primary)
                                        Text(AppLocalized(option.subtitleKey))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                    } header: {
                        Text("导入到")
                    }
                }
            }
            .navigationTitle(Text("导入记忆"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(busy ? "导入中…" : "导入") { beginImport() }
                        .disabled(!hasPayload || busy)
                }
            }
            .sheet(isPresented: $showFilePicker) {
                MemoryDocumentPicker { picked in
                    showFilePicker = false
                    if let picked { load(fileName: picked.name, text: picked.text) }
                }
            }
            .onAppear {
                guard !didApplyPrefill, let prefill else { return }
                didApplyPrefill = true
                load(fileName: prefill.fileName, text: prefill.text)
            }
            .actionSheet(item: $conflict) { choice in
                ActionSheet(
                    title: Text("文件已存在"),
                    message: Text(pending?.fileName ?? ""),
                    buttons: conflictButtons()
                )
            }
            .alert("导入失败", isPresented: Binding(
                get: { errorMessage != nil },
                set: { if !$0 { errorMessage = nil } }
            )) {
                Button("好") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
        }
        .navigationViewStyle(.stack)
    }

    private func conflictButtons() -> [ActionSheet.Button] {
        [
            .destructive(Text("覆盖原文件")) { resolve(.overwrite) },
            .default(Text("重命名")) { resolve(.rename) },
            .cancel(Text("跳过这个文件")) { resolve(.skip) }
        ]
    }

    private func load(fileName name: String, text body: String) {
        fileName = name
        text = body
        hasPayload = true
        applyTargetNaming()
    }

    /// Daily memory implies a date-shaped name; other targets keep whatever
    /// the user typed.
    private func applyTargetNaming() {
        guard target == .dailyMemory else { return }
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_US_POSIX")
        df.dateFormat = "yyyy-MM-dd"
        let stem = (fileName as NSString).deletingPathExtension
        // Keep an already-valid date; otherwise stamp today.
        let valid = stem.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil
        fileName = valid ? stem + ".md" : df.string(from: Date()) + ".md"
    }

    private func pasteFromClipboard() {
        guard let clip = UIPasteboard.general.string, !clip.isEmpty else {
            errorMessage = AppLocalized("剪贴板里没有文本")
            return
        }
        load(fileName: "imported.md", text: clip)
    }

    private func beginImport() {
        var name = fileName.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty { name = "imported.md" }
        if !name.lowercased().hasSuffix(".md") { name += ".md" }
        fileName = name
        let request = MemoryImportRequest(fileName: name, text: text, target: target)
        pending = request
        if store.documentExists(rootID: MemoryLibraryRoot.sharedMemory.id, fileName: name) {
            conflict = .overwrite
        } else {
            write(request, overwrite: false)
        }
    }

    private func resolve(_ choice: MemoryImportConflict) {
        guard let request = pending else { return }
        conflict = nil
        switch choice {
        case .overwrite:
            write(request, overwrite: true)
        case .rename:
            var candidate = request.fileName
            var n = 2
            let stem = (request.fileName as NSString).deletingPathExtension
            while store.documentExists(rootID: MemoryLibraryRoot.sharedMemory.id, fileName: candidate) {
                candidate = "\(stem) \(n).md"
                n += 1
                if n > 999 { break }
            }
            write(MemoryImportRequest(fileName: candidate, text: request.text, target: request.target),
                  overwrite: false)
        case .skip:
            pending = nil
            onFinished(AppLocalized("已跳过同名文件"))
            dismiss()
        }
    }

    private func write(_ request: MemoryImportRequest, overwrite: Bool) {
        busy = true
        do {
            try store.importDocument(
                rootID: MemoryLibraryRoot.sharedMemory.id,
                fileName: request.fileName,
                text: request.text,
                overwrite: overwrite
            )
            markGlobalMemoryDirty(root: .sharedMemory, fileName: request.fileName)
            NotificationCenter.default.post(name: .memoryFilesDidChange, object: nil)
            busy = false
            pending = nil
            onFinished(String(format: AppLocalized("已导入 %@"), request.fileName))
            dismiss()
        } catch {
            busy = false
            errorMessage = error.localizedDescription
        }
    }
}

/// Minimal Files picker for `.md`. Reads the file inside the security scope so
/// iCloud placeholders are materialised before the scope closes.
private struct MemoryDocumentPicker: UIViewControllerRepresentable {
    var onPicked: ((name: String, text: String)?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPicked: onPicked) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.plainText, .text, .data]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        picker.allowsMultipleSelection = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        private let onPicked: ((name: String, text: String)?) -> Void
        init(onPicked: @escaping ((name: String, text: String)?) -> Void) {
            self.onPicked = onPicked
        }

        func documentPicker(_ controller: UIDocumentPickerViewController,
                            didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { onPicked(nil); return }
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: url),
                  let text = String(data: data, encoding: .utf8) else { onPicked(nil); return }
            onPicked((name: url.lastPathComponent, text: text))
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            onPicked(nil)
        }
    }
}
