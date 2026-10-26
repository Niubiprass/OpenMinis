//
//  SessionSkillsView.swift
//  MinisApp
//
//  Per-session skill toggle sheet: override which skills are active in a chat.
//

import SwiftUI

struct SessionSkillsView: View {
    /// The real session id, or nil for a draft chat that hasn't sent its first
    /// message yet. Never coerced to "" — an empty-string key would write the
    /// override to a phantom session and accumulate stale state across drafts
    /// (T-ios-session-skill-override-init-timing).
    let sessionId: String?
    /// Materializes the draft into a real, persisted session and returns its id.
    /// Called lazily on the first toggle so a pre-first-message override binds
    /// to the session the chat will actually use. Mirrors SessionModelPicker.
    var ensureSessionId: (() async -> String)?
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var store = SkillStore.shared
    @ObservedObject private var personaStore = PersonaStore.shared
    @State private var searchQuery = ""
    /// The id reads/writes resolve against. Seeded from `sessionId`; once a
    /// draft is materialized on first toggle it holds the real id so the rest
    /// of the sheet stays consistent without re-creating the session.
    @State private var resolvedSessionId: String?
    @State private var showSoulEditor = false
    @State private var showPersonaPicker = false
    @State private var folderLoadError: String?

    init(sessionId: String?, ensureSessionId: (() async -> String)? = nil) {
        self.sessionId = sessionId
        self.ensureSessionId = ensureSessionId
        _resolvedSessionId = State(initialValue: sessionId)
    }

    /// Whether `skill` is enabled for this session. With no resolved session
    /// (draft, pre-first-message) this reads the skill's GLOBAL default so the
    /// sheet shows the correct initial state.
    private func isEnabled(_ skill: Skill) -> Bool {
        if let sid = resolvedSessionId {
            return store.isEnabledForSession(skill.id, sessionId: sid)
        }
        return skill.isEnabled
    }

    /// Apply a toggle: materialize the draft session if needed, then write the
    /// override against the real id. Runs async because session creation is.
    private func setOverride(_ skill: Skill, _ enabled: Bool) {
        if let sid = resolvedSessionId {
            store.setSessionOverride(skillId: skill.id, sessionId: sid, enabled: enabled)
            return
        }
        Task {
            guard let sid = await ensureSessionId?() else { return }
            await MainActor.run {
                resolvedSessionId = sid
                store.setSessionOverride(skillId: skill.id, sessionId: sid, enabled: enabled)
            }
        }
    }

    /// Enable/Disable All: materialize the draft session ONCE (not per-skill, to
    /// avoid racing N createSession calls), then write every override.
    private func applyToAll(_ scope: [Skill], enabled: Bool) {
        if let sid = resolvedSessionId {
            for skill in scope {
                store.setSessionOverride(skillId: skill.id, sessionId: sid, enabled: enabled)
            }
            return
        }
        Task {
            guard let sid = await ensureSessionId?() else { return }
            await MainActor.run {
                resolvedSessionId = sid
                for skill in scope {
                    store.setSessionOverride(skillId: skill.id, sessionId: sid, enabled: enabled)
                }
            }
        }
    }

    private var filteredSkills: [Skill] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return store.skills }
        return store.skills.filter {
            $0.name.lowercased().contains(q) || $0.description.lowercased().contains(q)
        }
    }

    private var personaLabel: String {
        guard let sid = resolvedSessionId,
              let pid = UserDefaults.standard.string(forKey: "session.persona.id.\(sid)") else {
            return "跟随分组"
        }
        if pid.isEmpty { return "空白" }
        return PersonaStore.shared.persona(id: pid)?.name ?? "未知人格"
    }

    var body: some View {
        // Reference the version counter so SwiftUI refreshes on override changes.
        let _ = store.sessionOverrideVersion

        NavigationStack {
            List {
                Section {
                    Button {
                        showPersonaPicker = true
                    } label: {
                        HStack {
                            Text("会话人格")
                            Spacer()
                            Text(personaLabel)
                                .foregroundStyle(.secondary)
                        }
                    }
                    Button("会话灵魂提示词") { showSoulEditor = true }
                    Button("技能恢复继承分组／全局") {
                        if let sid = resolvedSessionId {
                            for skill in store.skills { store.clearSessionOverride(skillId: skill.id, sessionId: sid) }
                        }
                    }
                    .disabled(resolvedSessionId == nil)
                    if let folderLoadError { Text(folderLoadError).foregroundColor(.red) }
                }
                if store.skills.isEmpty {
                    Section {
                        Text("No skills installed. Add skills in Settings.")
                            .foregroundStyle(.secondary)
                            .font(.subheadline)
                    }
                } else if filteredSkills.isEmpty {
                    Section {
                        Text(AppLocalized("No skills match \"\(searchQuery)\"."))
                            .foregroundStyle(.secondary)
                            .font(.subheadline)
                    }
                } else {
                    Section(footer: Text("Toggles override the skill's default for this session only.")) {
                        ForEach(filteredSkills) { skill in
                            NavigationLink {
                                SessionSkillDetailView(skill: skill)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(skill.name).font(.body)
                                        if !skill.description.isEmpty {
                                            Text(skill.description)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(2)
                                        }
                                    }
                                    Spacer()
                                    Toggle("", isOn: Binding(
                                        get: { isEnabled(skill) },
                                        set: { setOverride(skill, $0) }
                                    ))
                                    .labelsHidden()
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Skills in Session")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $searchQuery, placement: .navigationBarDrawer(displayMode: .always),
                        prompt: Text(AppLocalized("Search skills")))
            .onAppear { store.reload() }
            .task(id: resolvedSessionId) {
                guard let sid = resolvedSessionId else { return }
                do {
                    let context = try await ChatStore.shared.resolveFolderRuntimeContext(for: sid)
                    store.setFolderSkillDefaults(context.configuration.skillDefaults, for: sid)
                    folderLoadError = nil
                } catch { folderLoadError = error.localizedDescription }
            }
            .sheet(isPresented: $showPersonaPicker) {
                PersonaPickerSheet(sessionId: resolvedSessionId,
                                   ensureSessionId: ensureSessionId,
                                   onResolved: { resolvedSessionId = $0 })
            }
            .sheet(isPresented: $showSoulEditor) {
                SessionSoulPromptSheet(sessionId: resolvedSessionId, ensureSessionId: ensureSessionId)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if !filteredSkills.isEmpty {
                        let scope = filteredSkills
                        let allEnabled = scope.allSatisfy { isEnabled($0) }
                        Button(allEnabled ? "Disable All" : "Enable All") {
                            let newValue = !allEnabled
                            applyToAll(scope, enabled: newValue)
                        }
                        .font(.subheadline)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

private struct SessionSkillDetailView: View {
    let skill: Skill
    @ObservedObject private var store = SkillStore.shared

    private var additionalFiles: [String] {
        store.listSkillFiles(skill.id).filter { $0 != "SKILL.md" }
    }

    var body: some View {
        List {
            Section("SKILL.md") {
                let content = store.readSkillContent(skill.id) ?? "(empty)"
                Text(content)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
            }

            if !additionalFiles.isEmpty {
                Section("Other Files") {
                    ForEach(additionalFiles, id: \.self) { relativePath in
                        NavigationLink {
                            SkillFilePreviewView(skillId: skill.id, relativePath: relativePath)
                        } label: {
                            Label {
                                Text(relativePath)
                                    .font(.system(.subheadline, design: .monospaced))
                            } icon: {
                                Image(systemName: iconName(for: relativePath))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(skill.name)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func iconName(for path: String) -> String {
        switch (path as NSString).pathExtension.lowercased() {
        case "md": return "doc.text"
        case "py": return "chevron.left.forwardslash.chevron.right"
        case "json": return "curlybraces"
        case "sh": return "terminal"
        case "yaml", "yml": return "list.bullet.indent"
        case "png", "jpg", "jpeg", "gif", "webp": return "photo"
        default: return "doc"
        }
    }
}

private struct SkillFilePreviewView: View {
    let skillId: String
    let relativePath: String

    @ObservedObject private var store = SkillStore.shared
    @State private var content: String = ""

    private var fileName: String {
        (relativePath as NSString).lastPathComponent
    }

    private var isImage: Bool {
        ["png", "jpg", "jpeg", "gif", "webp"].contains((relativePath as NSString).pathExtension.lowercased())
    }

    var body: some View {
        Group {
            if isImage {
                let fileURL = store.skillDirectoryURL(for: skillId).appendingPathComponent(relativePath)
                if let data = try? Data(contentsOf: fileURL),
                   let uiImage = UIImage(data: data) {
                    ScrollView {
                        Image(uiImage: uiImage)
                            .resizable()
                            .scaledToFit()
                            .padding()
                    }
                } else {
                    Text("Could not load image.")
                        .foregroundStyle(.secondary)
                }
            } else {
                ScrollView {
                    Text(content)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
            }
        }
        .navigationTitle(fileName)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if !isImage {
                content = store.readSkillFile(skillId, relativePath: relativePath) ?? ""
            }
        }
    }
}

struct PersonaPickerSheet: View {
    let sessionId: String?
    let ensureSessionId: (() async -> String)?
    let onResolved: (String) -> Void

    @ObservedObject private var store = PersonaStore.shared
    @Environment(\.dismiss) private var dismiss

    private var current: String? {
        guard let sid = sessionId else { return nil }
        return UserDefaults.standard.string(forKey: "session.persona.id.\(sid)")
    }

    var body: some View {
        NavigationView {
            List {
                Section {
                    option("跟随分组", "用分组或全局的默认人格", selected: current == nil) {
                        apply(nil)
                    }
                    option("无（空白）", "不注入任何人格提示词", selected: current == "") {
                        apply("")
                    }
                }
                Section("人格") {
                    if store.personas.isEmpty {
                        Text("还没有人格；先到设置 → 灵魂里新建。")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(store.personas) { persona in
                            option(persona.name,
                                   persona.style.isEmpty ? "未设置风格" : persona.style,
                                   selected: current == persona.id) {
                                apply(persona.id)
                            }
                        }
                    }
                }
            }
            .navigationTitle("会话人格")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    private func option(_ title: String, _ subtitle: String,
                        selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if selected {
                    Image(systemName: "checkmark")
                        .foregroundStyle(.tint)
                }
            }
            // [T-persona-row-hitarea] 整行可点。
            //
            // `.buttonStyle(.plain)` 的行内按钮只把"内容"算进点击区域 —— 中间的
            // 空白（Spacer）和右侧没有勾选图标的空地都不响应，于是「无（空白）」
            // 这一行（没有勾，右边一整片是空的）点上去像坏了，只有正好戳在文字
            // 上才生效；「跟随分组」带着勾，看着反而"好用"。用户看到的就是
            // "只有第一行能点"。
            //
            // contentShape + 撑满宽度，把整行矩形都变成命中区域。
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func apply(_ personaId: String?) {
        Task {
            let sid: String
            if let sessionId {
                sid = sessionId
            } else if let made = await ensureSessionId?() {
                sid = made
            } else {
                return
            }
            await MainActor.run {
                if let personaId {
                    UserDefaults.standard.set(personaId, forKey: "session.persona.id.\(sid)")
                } else {
                    UserDefaults.standard.removeObject(forKey: "session.persona.id.\(sid)")
                }
                onResolved(sid)
                NotificationCenter.default.post(name: .personaDidChange, object: nil)
                dismiss()
            }
        }
    }
}

/// New session-level adapter. nil inherits; explicit empty suppresses the
/// inherited personality body. Saving never rewrites the global SOUL.md.
@MainActor
private struct SessionSoulPromptSheet: View {
    let sessionId: String?
    let ensureSessionId: (() async -> String)?
    @Environment(\.dismiss) private var dismiss
    @State private var inherits = true
    @State private var draft = ""
    @State private var saving = false
    @State private var failure: String?

    var body: some View {
        NavigationView {
            Form {
                Toggle("继承分组／全局灵魂", isOn: $inherits)
                if !inherits {
                    TextEditor(text: $draft).frame(minHeight: 180)
                    Text("显式留空表示本会话不使用继承的人格正文。名称、图标和系统能力不变。")
                        .font(.caption).foregroundColor(.secondary)
                }
                if let failure { Text(failure).foregroundColor(.red) }
                Text("保存后从下一轮请求生效；取消不改配置。此覆盖仅保存在本机。")
                    .font(.caption).foregroundColor(.secondary)
            }
            .navigationTitle("会话灵魂提示词")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(saving) }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { Task { await save() } }.disabled(saving || (!inherits && SoulStore.isOverLimit(draft).isOverLimit))
                }
            }
        }
        .navigationViewStyle(.stack)
        .interactiveDismissDisabled(saving)
        .onAppear {
            if let sid = sessionId, let value = UserDefaults.standard.string(forKey: "session.soul.body.\(sid)") {
                inherits = false; draft = value
            }
        }
    }

    private func save() async {
        saving = true
        let sid: String?
        if let existing = sessionId { sid = existing }
        else { sid = await ensureSessionId?() }
        guard let sid, !sid.isEmpty else { failure = "无法创建会话，配置未保存。"; saving = false; return }
        let key = "session.soul.body.\(sid)"
        if inherits { UserDefaults.standard.removeObject(forKey: key) }
        else { UserDefaults.standard.set(draft, forKey: key) }
        saving = false
        dismiss()
    }
}
