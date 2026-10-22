//
//  SessionMemoryView.swift
//  MinisApp
//
//  Shows all memory used in the current session: auto-injected + tool-recalled.
//

import SwiftUI

struct SessionMemoryView: View {
    @ObservedObject var vm: AIChatViewModel
    @Environment(\.dismiss) private var dismiss
    private let libraryRoots: [MemoryLibraryRoot]?
    private let onSaveDirty: MemorySaveDirty?
    @State private var runtimeRoots: [MemoryLibraryRoot]?
    @State private var runtimeReady = false
    @State private var runtimeError: String?

    /// The runtime owner supplies its actual authorized directories. Passing
    /// roots never falls back to a global scan or the legacy log-entry writer.
    /// nil preserves the existing session-injection/activity screen.
    init(vm: AIChatViewModel, roots: [MemoryLibraryRoot]? = nil,
         onSaveDirty: MemorySaveDirty? = nil) {
        self.vm = vm
        self.libraryRoots = roots
        self.onSaveDirty = onSaveDirty
    }

    var body: some View {
        NavigationStack {
            if let roots = libraryRoots ?? runtimeRoots {
                ScopedMemoryLibraryView(title: AppLocalized("Memories in Session"),
                                        roots: roots, onSaveDirty: onSaveDirty)
                    .toolbar {
                        ToolbarItem(placement: .primaryAction) {
                            Button("Done") { dismiss() }
                        }
                    }
            } else if !runtimeReady {
                ProgressView()
            } else if let runtimeError {
                Text(runtimeError).padding().foregroundColor(.red)
            } else {
                sessionContents
            }
        }
        .task {
            guard libraryRoots == nil else { return }
            do {
                try await vm.refreshFolderRuntimeContext()
                if let context = vm.folderRuntimeContext, context.usesFolderMemory {
                    var roots = [MemoryLibraryRoot(id: "folder-" + (context.folderId ?? ""), title: "本组记忆", directory: context.memoryDirectory, isReadOnly: false, isGlobal: false)]
                    if context.configuration.readsGlobalMemory {
                        roots.append(MemoryLibraryRoot(id: "global-read-only", title: "全局记忆（只读）", directory: AIChatViewModel.minisMemoryPersistentDir, isReadOnly: true, isGlobal: true))
                    }
                    runtimeRoots = roots
                }
            } catch { runtimeError = error.localizedDescription }
            runtimeReady = true
        }
    }

    private var sessionContents: some View {
            List {
                // Section 1: Auto-injected memories
                Section {
                    ForEach(autoInjected, id: \.name) { item in
                        NavigationLink {
                            if let fileURL = item.fileURL {
                                MemoryContentView(root: .sharedMemory, fileName: fileURL.lastPathComponent,
                                                  title: item.name)
                            } else {
                                Text(item.content).textSelection(.enabled)
                            }
                        } label: {
                            row(name: item.name, detail: item.detail, icon: item.icon)
                        }
                    }
                } header: {
                    Text("Auto-injected")
                } footer: {
                    Text("Loaded into system prompt at the start of each agent turn.")
                }

                // Section 2: Tool-recalled memories
                if !toolMemories.isEmpty {
                    Section {
                        ForEach(toolMemories) { item in
                            NavigationLink {
                                if item.isWrite {
                                    MemoryWriteDetailView(item: item)
                                } else {
                                    MemoryGetDetailView(item: item)
                                }
                            } label: {
                                row(name: item.title, detail: item.detail, icon: item.isWrite ? "square.and.pencil" : "magnifyingglass")
                            }
                        }
                    } header: {
                        Text("Tool Activity")
                    } footer: {
                        Text("Memory reads and writes performed by the agent during this session.")
                    }
                }
            }
            .navigationTitle("Memories in Session")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
    }

    // MARK: - Row

    private func row(name: String, detail: String, icon: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .foregroundStyle(.pink)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.body)
                if !detail.isEmpty {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
    }

    // MARK: - Auto-injected

    private struct AutoItem {
        let name: String
        let detail: String
        let icon: String
        let content: String
        let fileURL: URL?
    }

    private var autoInjected: [AutoItem] {
        var items: [AutoItem] = []
        let fm = FileManager.default
        let memDir = AIChatViewModel.minisMemoryPersistentDir

        // SOUL.md — listed first because it's the identity/personality
        // layer that SystemPromptBuilder.identitySection() injects at
        // the very top of every turn's system prompt. The Memory Sheet
        // previously only surfaced GLOBAL.md + daily logs, so users had
        // no way to confirm SOUL.md was reaching the model.
        let soulURL = memDir.appendingPathComponent("SOUL.md")
        if fm.fileExists(atPath: soulURL.path),
           let content = try? String(contentsOf: soulURL, encoding: .utf8),
           !content.isEmpty {
            let lineCount = content.components(separatedBy: "\n").count
            items.append(AutoItem(
                name: "SOUL.md",
                detail: "\(lineCount) lines (full)",
                icon: "person.fill",
                content: content,
                fileURL: soulURL
            ))
        } else {
            items.append(AutoItem(name: "SOUL.md", detail: "Empty", icon: "person", content: "(empty)", fileURL: soulURL))
        }

        // GLOBAL.md
        let globalURL = memDir.appendingPathComponent("GLOBAL.md")
        if fm.fileExists(atPath: globalURL.path),
           let content = try? String(contentsOf: globalURL, encoding: .utf8),
           !content.isEmpty {
            let lineCount = content.components(separatedBy: "\n").count
            items.append(AutoItem(
                name: "GLOBAL.md",
                detail: "\(lineCount) lines (full)",
                icon: "star.fill",
                content: content,
                fileURL: globalURL
            ))
        } else {
            items.append(AutoItem(name: "GLOBAL.md", detail: "Empty", icon: "star", content: "(empty)", fileURL: globalURL))
        }

        // Most recent 3 daily logs with content (matches system prompt injection logic)
        let dateFmt = DateFormatter()
        dateFmt.dateFormat = "yyyy-MM-dd"
        let today = Date()
        var found = 0
        var dayOffset = 0
        let maxLookback = 30

        while found < 3 && dayOffset < maxLookback {
            let date = today.addingTimeInterval(-Double(dayOffset) * 86400)
            let dateStr = dateFmt.string(from: date)
            let fileName = "\(dateStr).md"
            let fileURL = memDir.appendingPathComponent(fileName)
            if fm.fileExists(atPath: fileURL.path),
               let content = try? String(contentsOf: fileURL, encoding: .utf8),
               !content.isEmpty {
                let lineCount = content.components(separatedBy: "\n").count
                let injected = min(lineCount, 200)
                let detail = lineCount > 200
                    ? "\(injected)/\(lineCount) lines injected"
                    : "\(lineCount) lines (full)"
                let label: String
                switch dayOffset {
                case 0: label = AppLocalized("Today")
                case 1: label = AppLocalized("Yesterday")
                default: label = dateStr
                }
                items.append(AutoItem(
                    name: "\(label) — \(fileName)",
                    detail: detail,
                    icon: "calendar",
                    content: content,
                    fileURL: fileURL
                ))
                found += 1
            }
            dayOffset += 1
        }

        return items
    }

    // MARK: - Tool memories

    struct ToolMemoryItem: Identifiable {
        let id = UUID()
        let title: String
        let detail: String
        /// The tool result output (what the tool returned to the agent).
        let content: String
        let isWrite: Bool
        /// The original content written by memory_write, parsed from toolInputArgs.
        let writtenContent: String?
        /// Keywords used for memory_get search.
        let keywords: String?
    }

    private var toolMemories: [ToolMemoryItem] {
        var items: [ToolMemoryItem] = []
        for message in vm.messages {
            for block in message.blocks {
                guard case .memoryTool(let action) = block.kind else { continue }
                let isWrite = action == "memory_write"
                let summary = block.toolSummary ?? action

                var writtenContent: String?
                var keywords: String?

                if let argsJson = block.toolInputArgs,
                   let data = argsJson.data(using: .utf8),
                   let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    if isWrite {
                        writtenContent = dict["content"] as? String
                    } else {
                        keywords = dict["keywords"] as? String
                    }
                }

                // Build a meaningful detail preview
                let detail: String
                if isWrite, let written = writtenContent {
                    // Show what was written
                    let firstLine = written.components(separatedBy: "\n").first(where: { !$0.isEmpty }) ?? ""
                    detail = String(firstLine.prefix(100))
                } else if !isWrite {
                    // Show keywords + result summary
                    let resultLines = block.content.components(separatedBy: "\n").filter { !$0.isEmpty }
                    if let kw = keywords, !kw.isEmpty {
                        let matchCount = resultLines.filter { $0.hasPrefix("---") || $0.hasPrefix("## ") }.count
                        detail = "Search: \(kw)" + (matchCount > 0 ? " (\(matchCount) files)" : "")
                    } else {
                        detail = String((resultLines.first ?? "").prefix(100))
                    }
                } else {
                    detail = String(block.content.prefix(100))
                }

                items.append(ToolMemoryItem(
                    title: summary,
                    detail: detail,
                    content: block.content,
                    isWrite: isWrite,
                    writtenContent: writtenContent,
                    keywords: keywords
                ))
            }
        }
        return items
    }
}

// MARK: - Content Detail

@MainActor
struct MemoryContentView: View {
    private let title: String
    private let root: MemoryLibraryRoot
    private let fileName: String
    private let store: MemoryDocumentStore
    private let onSaveDirty: MemorySaveDirty?
    @State private var snapshot: MemoryDocumentStore.Snapshot?
    // A presented editor owns its base snapshot, including an unchanged draft.
    @State private var editingSnapshot: MemoryDocumentStore.Snapshot?
    @State private var error: String?
    @State private var saved = false
    @State private var share: MemoryShareItem?
    @State private var shareToPersona = false
    @State private var moveMemory = false
    @Environment(\.dismiss) private var dismiss

    private var sourcePersona: AgentPersona? {
        guard root.id.hasPrefix("persona-") else { return nil }
        let id = String(root.id.dropFirst("persona-".count))
        return PersonaStore.shared.persona(id: id)
    }

    /// Persona memory and orphan files can be moved. GLOBAL.md is the
    /// destination side, not a source: moving it would empty the global memory.
    private var canMoveMemory: Bool {
        guard snapshot?.exists == true else { return false }
        return sourcePersona != nil || root.id == "persona-orphan"
    }

    init(root: MemoryLibraryRoot, fileName: String, title: String? = nil,
         onSaveDirty: MemorySaveDirty? = nil) {
        self.root = root
        self.fileName = fileName
        self.title = title ?? fileName
        self.store = MemoryDocumentStore(roots: [root])
        self.onSaveDirty = onSaveDirty
    }

    var body: some View {
        VStack(spacing: 0) {
            if root.isReadOnly {
                Label("Read-only", systemImage: "lock")
                    .font(.caption)
                    .padding(.top, 8)
            }
            if let snapshot = snapshot {
                ScrollView {
                    Text(snapshot.exists ? snapshot.originalText : AppLocalized("This memory file has not been created."))
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                        .textSelection(.enabled)
                }
            } else {
                Button("Reload") { reload() }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if let persona = sourcePersona, let snapshot, snapshot.exists {
                Button {
                    shareToPersona = true
                } label: {
                    Label(AppLocalizedFormat("分享给其他人格（来自 %@）", persona.name),
                          systemImage: "person.line.dotted.person")
                }
                .padding(.horizontal)
                .padding(.bottom, 4)
            }
            if canMoveMemory {
                Button {
                    moveMemory = true
                } label: {
                    Label(AppLocalized("移动到其他人格 / 全局记忆"),
                          systemImage: "arrow.turn.up.right")
                }
                .padding(.horizontal)
                .padding(.bottom, 4)
            }
            Text("Share exports the saved snapshot, not a draft. It does not change group access.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    saved = false
                    editingSnapshot = snapshot
                } label: {
                    Label("Edit", systemImage: "pencil")
                }
                .disabled(root.isReadOnly || snapshot == nil || editingSnapshot != nil)
            }
            ToolbarItem(placement: .bottomBar) {
                Button { shareSaved() } label: { Label("Share", systemImage: "square.and.arrow.up") }
                    .disabled(editingSnapshot != nil || snapshot?.exists != true)
            }
        }
        .overlay(alignment: .bottom) {
            if saved {
                Text("Saved")
                    .font(.caption)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color(UIColor.tertiarySystemFill), in: Capsule())
                    .padding(.bottom, 8)
            }
        }
        .onAppear { reload() }
        .onReceive(NotificationCenter.default.publisher(for: .memoryFilesDidChange)) { _ in
            guard editingSnapshot == nil else { return }
            reload()
        }
        .sheet(item: $editingSnapshot, onDismiss: { reload() }) { base in
            NavigationView {
                MemoryFileEditView(root: root, snapshot: base, onSaveDirty: onSaveDirty) { result in
                    snapshot = result
                    error = nil
                    saved = true
                }
            }
            .navigationViewStyle(StackNavigationViewStyle())
            .interactiveDismissDisabled(true)
        }
        .sheet(isPresented: $shareToPersona) {
            if let persona = sourcePersona, let snapshot {
                PersonaShareSheet(source: persona, title: fileName, content: snapshot.originalText)
            }
        }
        .sheet(isPresented: $moveMemory) {
            PersonaMemoryMoveSheet(root: root, fileName: fileName, sourcePersona: sourcePersona) { moved in
                if moved { dismiss() }
            }
        }
        .sheet(item: $share) { MinisShareSheet(url: $0.url) }
        .alert("Memory error", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK", role: .cancel) { error = nil }
        } message: { Text(error ?? "") }
    }

    private func reload() {
        guard editingSnapshot == nil else { return }
        do {
            snapshot = try store.readSnapshot(rootID: root.id, fileName: fileName)
            error = nil
        } catch {
            snapshot = nil
            saved = false
            self.error = error.localizedDescription
        }
    }

    private func shareSaved() {
        guard editingSnapshot == nil, let snapshot = snapshot else { return }
        do { share = MemoryShareItem(url: try store.export([snapshot])) }
        catch { self.error = error.localizedDescription }
    }
}

// MARK: - [T-persona-memory-move] Move a memory to another persona/global

private struct PersonaMoveTarget: Identifiable {
    let id: String
    let name: String
    let icon: String
    let personaId: String?
}

struct PersonaMemoryMoveSheet: View {
    let root: MemoryLibraryRoot
    let fileName: String
    let sourcePersona: AgentPersona?
    let completion: (Bool) -> Void

    @ObservedObject private var store = PersonaStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var error: String?

    private var targets: [PersonaMoveTarget] {
        var list = store.personas
            .filter { $0.id != sourcePersona?.id }
            .map { PersonaMoveTarget(id: $0.id, name: $0.name,
                                     icon: $0.icon.isEmpty ? "🙂" : $0.icon,
                                     personaId: $0.id) }
        list.append(PersonaMoveTarget(id: "global", name: AppLocalized("全局记忆"),
                                      icon: "🌐", personaId: nil))
        return list
    }

    var body: some View {
        NavigationView {
            List {
                Section {
                    ForEach(targets) { target in
                        Button {
                            move(to: target)
                        } label: {
                            HStack(spacing: 10) {
                                Text(target.icon)
                                    .font(.system(size: 20))
                                    .frame(width: 30)
                                Text(target.name)
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(.tertiary)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                } footer: {
                    Text(sourcePersona == nil
                         ? AppLocalized("移动后原文件会删除；人格本身不会被删除。")
                         : AppLocalized("移动后原人格的记忆会清空；人格本身不会被删除。"))
                }
                if let error {
                    Section {
                        Text(error).foregroundStyle(.red).font(.caption)
                    }
                }
            }
            .navigationTitle(AppLocalized("移动记忆"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("取消")) { dismiss() }
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    private func move(to target: PersonaMoveTarget) {
        let ok: Bool
        if let source = sourcePersona {
            if let targetId = target.personaId {
                ok = store.moveMemory(fromPersonaId: source.id, toPersonaId: targetId)
            } else {
                ok = store.moveMemoryFile(named: "\(source.id).md", toPersonaId: nil)
            }
        } else {
            ok = store.moveMemoryFile(named: fileName, toPersonaId: target.personaId)
        }
        if ok {
            completion(true)
            dismiss()
        } else {
            error = AppLocalized("移动失败：目标为空或文件不可读。")
        }
    }
}

// MARK: - Memory Write Detail (with revoke)

private struct MemoryWriteDetailView: View {
    let item: SessionMemoryView.ToolMemoryItem
    @Environment(\.dismiss) private var dismiss
    @State private var isEditing = false
    @State private var editedContent: String = ""
    @State private var showRevokeAlert = false
    @State private var revokeResult: String?
    @State private var showResultAlert = false
    @State private var saved = false

    var body: some View {
        Group {
            if isEditing {
                TextEditor(text: $editedContent)
                    .font(.system(.caption, design: .monospaced))
                    .padding(.horizontal, 8)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        if let written = item.writtenContent {
                            SectionHeader(title: "Written Content")
                            Text(written)
                                .font(.system(.caption, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal)
                                .textSelection(.enabled)
                        }

                        SectionHeader(title: "Tool Result")
                        Text(item.content)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal)
                            .textSelection(.enabled)
                    }
                    .padding(.vertical, 8)
                }
            }
        }
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                if isEditing {
                    Button("Save") { saveEdit() }
                } else {
                    if item.writtenContent != nil {
                        Button {
                            editedContent = item.writtenContent ?? ""
                            isEditing = true
                        } label: {
                            Image(systemName: "pencil")
                        }
                    }
                    Button {
                        showRevokeAlert = true
                    } label: {
                        Image(systemName: "arrow.uturn.backward")
                    }
                    .disabled(item.writtenContent == nil)
                }
            }
        }
        .overlay(alignment: .bottom) {
            if saved {
                Text("Saved")
                    .font(.caption)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color(UIColor.tertiarySystemFill), in: Capsule())
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .alert("Revoke Memory", isPresented: $showRevokeAlert) {
            Button("Cancel", role: .cancel) {}
            Button("Revoke", role: .destructive) {
                revokeResult = revokeEntry()
                showResultAlert = true
            }
        } message: {
            Text("Remove this memory entry from the daily log? This cannot be undone.")
        }
        .alert(revokeResult ?? "", isPresented: $showResultAlert) {
            Button("OK") {
                if revokeResult?.hasPrefix("Removed") == true {
                    dismiss()
                }
            }
        }
    }

    private func saveEdit() {
        guard let written = item.writtenContent else { return }
        let result = replaceEntryInLog(oldContent: written, newContent: editedContent)
        if result != nil {
            isEditing = false
            withAnimation { saved = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                withAnimation { saved = false }
            }
        }
    }

    /// Find entry matching `oldContent` in daily logs and replace its body with `newContent`.
    /// Returns the filename on success, nil on failure.
    private func replaceEntryInLog(oldContent: String, newContent: String) -> String? {
        let fm = FileManager.default
        let memDir = AIChatViewModel.minisMemoryPersistentDir
        let dateFmt = DateFormatter()
        dateFmt.dateFormat = "yyyy-MM-dd"
        let candidates = [
            dateFmt.string(from: Date()),
            dateFmt.string(from: Date().addingTimeInterval(-86400))
        ]

        for dateStr in candidates {
            let fileURL = memDir.appendingPathComponent("\(dateStr).md")
            guard fm.fileExists(atPath: fileURL.path),
                  let fileContent = try? String(contentsOf: fileURL, encoding: .utf8) else {
                continue
            }

            let pattern = "<!-- \\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2} -->\n"
            guard let regex = try? NSRegularExpression(pattern: pattern) else { continue }

            let nsContent = fileContent as NSString
            let matches = regex.matches(in: fileContent, range: NSRange(location: 0, length: nsContent.length))

            for (i, match) in matches.enumerated() {
                let contentStart = match.range.location + match.range.length
                let entryEnd: Int
                if i + 1 < matches.count {
                    entryEnd = matches[i + 1].range.location
                } else {
                    entryEnd = nsContent.length
                }

                let bodyRange = NSRange(location: contentStart, length: entryEnd - contentStart)
                let body = nsContent.substring(with: bodyRange)
                let trimmedBody = body.trimmingCharacters(in: .whitespacesAndNewlines)
                let trimmedOld = oldContent.trimmingCharacters(in: .whitespacesAndNewlines)

                if trimmedBody == trimmedOld {
                    let replacement = newContent.trimmingCharacters(in: .whitespacesAndNewlines) + "\n\n"
                    let newFileContent = nsContent.replacingCharacters(in: bodyRange, with: replacement)
                    if let _ = try? newFileContent.write(to: fileURL, atomically: true, encoding: .utf8) {
                        return dateStr
                    }
                }
            }
        }
        return nil
    }

    /// [T-ios-memory-write-revoke] Delegates to the shared revoker, which the
    /// tool capsule's long-press menu uses too — the entry-deletion logic must
    /// not drift between the two entry points.
    private func revokeEntry() -> String {
        guard let written = item.writtenContent else {
            return AppLocalized("No written content to revoke.")
        }
        return MemoryWriteRevoker.revoke(writtenContent: written)
    }
}

// MARK: - Memory Get Detail

private struct MemoryGetDetailView: View {
    let item: SessionMemoryView.ToolMemoryItem

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let kw = item.keywords, !kw.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "magnifyingglass")
                            .foregroundStyle(.secondary)
                        Text(kw)
                            .font(.subheadline)
                    }
                    .padding(.horizontal)
                    .padding(.top, 8)
                }

                Text(item.content)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .textSelection(.enabled)
            }
            .padding(.bottom)
        }
        .navigationTitle(item.title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Section Header

private struct SectionHeader: View {
    let title: String
    var body: some View {
        Text(title)
            .font(.caption)
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
            .padding(.horizontal)
    }
}
