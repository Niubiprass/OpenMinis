//
//  PluginDevView.swift
//  Minis
//
//  [T-plugin-dev] One place for tweak projects. The work happens in chat —
//  this screen only lists projects, their target and their last build, so a
//  half-finished tweak is never "lost". New projects are created from a single
//  effect description; the agent decides the target itself.
//

import Foundation
import SwiftUI
import UIKit

/// [T-host-access-master-switch] One gate for every jailbreak MCP command.
/// Default OFF does NOT mean "all MCP blocked": read-only calls (screenshots,
/// app lists, logs, file reads) still work, because that is what the agent
/// needs to inspect and explain. The switch only unlocks the calls that can
/// change the device — terminal commands, file writes, install/uninstall and
/// touch control. The per-command approval dialog sits on top of this.
enum HostAccessPermission {
    static let key = "permissions.hostAccess"

    static var isEnabled: Bool {
        UserDefaults.standard.bool(forKey: key)
    }

    static func setEnabled(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: key)
    }

    /// 每次都要点头的三件：跑命令、写文件、卸 App。
    /// 点击/滑动/按键/截图/安装/调亮度都不再问，免得测试时一直挡路。
    static let dangerousTools = ["run_command", "write_file", "uninstall_app"]

    static func isDangerous(_ command: String) -> Bool {
        guard command.contains("minis-mcp-cli") else { return false }
        return dangerousTools.contains { command.contains($0) }
    }
}

enum PluginProjectStatus: String, Codable, CaseIterable, Hashable {
    case planning, analysis, coding, building, testing, done

    var label: String {
        switch self {
        case .planning: return "待开始"
        case .analysis: return "逆向分析"
        case .coding:   return "写源码"
        case .building: return "编译中"
        case .testing:  return "测试中"
        case .done:     return "已完成"
        }
    }

    var color: Color {
        switch self {
        case .planning: return .gray
        case .analysis: return .purple
        case .coding:   return .blue
        case .building: return .indigo
        case .testing:  return .orange
        case .done:     return .green
        }
    }
}

/// 逆向分析是插件项目中的一个阶段，不再单独占设置入口。
enum PluginAnalysisKind: String, Codable, CaseIterable, Hashable {
    case app, ipa, deb, dylib, macho, system

    var label: String {
        switch self {
        case .app:   return "已安装 App"
        case .ipa:   return "IPA"
        case .deb:   return "DEB 插件包"
        case .dylib: return "dylib / Mach-O"
        case .macho: return "裸 Mach-O"
        case .system:return "系统组件"
        }
    }
}

struct PluginProject: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var effect: String
    var target: String
    var status: PluginProjectStatus
    var createdAt = Date()
    var updatedAt = Date()

    // These fields are deliberately plain text: the actual analysis happens
    // in the conversation/MCP workflow, while the project keeps the handoff.
    var analysisKind: PluginAnalysisKind = .app
    var analysisMaterial: String = ""
    var analysisQuestion: String = ""
    var analysisResult: String = ""
    var artifact: String = ""
    var lastError: String = ""

    private enum CodingKeys: String, CodingKey {
        case id, name, effect, target, status, createdAt, updatedAt
        case analysisKind, analysisMaterial, analysisQuestion, analysisResult
        case artifact, lastError
    }

    init(id: UUID = UUID(), name: String, effect: String, target: String,
         status: PluginProjectStatus, createdAt: Date = Date(), updatedAt: Date = Date(),
         analysisKind: PluginAnalysisKind = .app, analysisMaterial: String = "",
         analysisQuestion: String = "", analysisResult: String = "",
         artifact: String = "", lastError: String = "") {
        self.id = id
        self.name = name
        self.effect = effect
        self.target = target
        self.status = status
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.analysisKind = analysisKind
        self.analysisMaterial = analysisMaterial
        self.analysisQuestion = analysisQuestion
        self.analysisResult = analysisResult
        self.artifact = artifact
        self.lastError = lastError
    }

    // Existing plugin-projects.json files predate the analysis fields.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? "未命名"
        effect = try c.decodeIfPresent(String.self, forKey: .effect) ?? ""
        target = try c.decodeIfPresent(String.self, forKey: .target) ?? "自动判断"
        status = try c.decodeIfPresent(PluginProjectStatus.self, forKey: .status) ?? .planning
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt) ?? Date()
        updatedAt = try c.decodeIfPresent(Date.self, forKey: .updatedAt) ?? createdAt
        analysisKind = try c.decodeIfPresent(PluginAnalysisKind.self, forKey: .analysisKind) ?? .app
        analysisMaterial = try c.decodeIfPresent(String.self, forKey: .analysisMaterial) ?? ""
        analysisQuestion = try c.decodeIfPresent(String.self, forKey: .analysisQuestion) ?? ""
        analysisResult = try c.decodeIfPresent(String.self, forKey: .analysisResult) ?? ""
        artifact = try c.decodeIfPresent(String.self, forKey: .artifact) ?? ""
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError) ?? ""
    }
}

extension PluginProject {
    /// The single handoff used by chat, MCP and the future background runner.
    /// Keeping it on the project prevents the old standalone reverse-analysis
    /// prompt from drifting away from the plugin-development workflow.
    var workflowPrompt: String {
        var lines = [
            "继续做插件项目「\(name)」。",
            "目标：\(target)。",
            "效果：\(effect)。",
            "当前阶段：\(status.label)。",
            "请遵循 tweak-workflow：先本地分析和写源码，推送或安装前分别征得同意。"
        ]
        if !analysisMaterial.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines += [
                "这是项目内的逆向分析阶段，不要把它当成独立工具：",
                "分析类型：\(analysisKind.label)。",
                "分析对象/资料：\(analysisMaterial)。"
            ]
        }
        if !analysisQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.append("逆向问题：\(analysisQuestion)。")
        }
        if !analysisResult.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.append("已有分析结果（请在此基础上继续核对，不要丢失）：\n\(analysisResult)")
        }
        lines.append("请把分析结论直接用于 Hook 点、源码、静态检查和后续取证；不要另开一个孤立的逆向项目。")
        return lines.joined(separator: "\n")
    }
}

@MainActor
final class PluginProjectStore: ObservableObject {
    static let shared = PluginProjectStore()

    @Published private(set) var projects: [PluginProject] = []

    private let fileURL: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let dir = base.appendingPathComponent("Minis", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("plugin-projects.json")
    }()

    private init() { load() }

    var activeCount: Int { projects.filter { $0.status != .done }.count }

    @discardableResult
    func add(effect: String, target: String, analysisKind: PluginAnalysisKind,
             analysisMaterial: String, analysisQuestion: String) -> PluginProject {
        let trimmed = effect.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return PluginProject(name: "未命名", effect: "", target: "", status: .planning)
        }
        let firstLine = trimmed.split(separator: "\n").first.map(String.init) ?? trimmed
        let name = firstLine.count > 14 ? String(firstLine.prefix(14)) + "…" : firstLine
        let t = target.trimmingCharacters(in: .whitespacesAndNewlines)
        let material = analysisMaterial.trimmingCharacters(in: .whitespacesAndNewlines)
        let question = analysisQuestion.trimmingCharacters(in: .whitespacesAndNewlines)
        let project = PluginProject(name: name, effect: trimmed,
                                    target: t.isEmpty ? "自动判断" : t,
                                    status: .planning,
                                    analysisKind: analysisKind,
                                    analysisMaterial: material,
                                    analysisQuestion: question)
        projects.insert(project, at: 0)
        save()
        return project
    }

    func update(_ project: PluginProject) {
        guard let idx = projects.firstIndex(where: { $0.id == project.id }) else { return }
        var copy = project
        copy.updatedAt = Date()
        projects[idx] = copy
        save()
    }

    func delete(_ project: PluginProject) {
        projects.removeAll { $0.id == project.id }
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let decoded = try? JSONDecoder().decode([PluginProject].self, from: data) else { return }
        projects = decoded
    }

    private func save() {
        do {
            let data = try JSONEncoder().encode(projects)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            AppLogger(category: "PluginDev").error("[PluginDev] save failed: \(error.localizedDescription)")
        }
    }
}

// MARK: - List

struct PluginDevView: View {
    @ObservedObject private var store = PluginProjectStore.shared
    @State private var showNew = false

    private var active: [PluginProject] { store.projects.filter { $0.status != .done } }
    private var finished: [PluginProject] { store.projects.filter { $0.status == .done } }

    var body: some View {
        List {
            Section {
                Button {
                    showNew = true
                } label: {
                    Label("新建插件项目", systemImage: "plus.circle.fill")
                }
            } footer: {
                Text("直接说你想要的效果，目标交给 AI 判断；也可以附参考视频或别人的 DEB。项目建好后在对话里继续。")
            }

            Section {
                Toggle("允许 AI 操作手机（主机命令）", isOn: Binding(
                    get: { HostAccessPermission.isEnabled },
                    set: { HostAccessPermission.setEnabled($0) }
                ))
            } header: {
                Text("安全")
            } footer: {
                Text("默认只放行只读操作（截图、列 App、读日志、读文件）。终端命令、写文件、装/卸 App、点击控制会被拦截；打开后这些才放行。")
            }

            Section {
                NavigationLink {
                    MiniSightSettingsView()
                } label: {
                    Label("操作指示器", systemImage: "pawprint.circle")
                }
            } header: {
                Text("指示器")
            } footer: {
                Text("AI 操作手机时顶部的提示：胶囊或会动的桌宠。桌宠素材自己导入。")
            }

            if !active.isEmpty {
                Section("进行中") {
                    ForEach(active) { project in
                        NavigationLink {
                            PluginProjectDetailView(project: project)
                        } label: {
                            row(project)
                        }
                    }
                }
            }

            if !finished.isEmpty {
                Section("已完成") {
                    ForEach(finished) { project in
                        NavigationLink {
                            PluginProjectDetailView(project: project)
                        } label: {
                            row(project)
                        }
                    }
                }
            }
        }
        .navigationTitle("插件开发")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showNew) {
            NewPluginProjectSheet { effect, target, analysisKind, material, question in
                let project = store.add(effect: effect, target: target,
                                       analysisKind: analysisKind,
                                       analysisMaterial: material,
                                       analysisQuestion: question)
                UIPasteboard.general.string = project.workflowPrompt
                QuickActionRouter.shared.postNewChat()
            }
        }
    }

    private func row(_ project: PluginProject) -> some View {
        HStack(spacing: 10) {
            Circle()
                .fill(project.status.color)
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text(project.name).font(.body)
                Text("\(project.target) · \(project.status.label)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Detail

struct PluginProjectDetailView: View {
    @State var project: PluginProject
    @ObservedObject private var store = PluginProjectStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var copied = false
    @State private var saved = false

    var body: some View {
        List {
            Section("效果") {
                Text(project.effect)
                    .font(.body)
            }
            Section("目标") {
                Text(project.target)
                    .foregroundStyle(.secondary)
            }

            Section("逆向分析（项目内阶段）") {
                Picker("资料类型", selection: Binding(
                    get: { project.analysisKind },
                    set: { project.analysisKind = $0; saveProject() }
                )) {
                    ForEach(PluginAnalysisKind.allCases, id: \.self) { kind in
                        Text(kind.label).tag(kind)
                    }
                }
                TextField("分析对象 / 文件路径 / Bundle ID", text: Binding(
                    get: { project.analysisMaterial },
                    set: { project.analysisMaterial = $0; saved = false }
                ))
                TextEditor(text: Binding(
                    get: { project.analysisQuestion },
                    set: { project.analysisQuestion = $0; saved = false }
                ))
                .frame(minHeight: 72)
                if !project.analysisResult.isEmpty {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("已有分析结果")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(project.analysisResult)
                            .font(.footnote)
                    }
                }
                Button {
                    project.status = .analysis
                    saveProject()
                    UIPasteboard.general.string = project.workflowPrompt
                    copied = true
                    QuickActionRouter.shared.postNewChat()
                } label: {
                    Label("在当前对话开始 / 继续逆向分析",
                          systemImage: "magnifyingglass.circle.fill")
                }
            } footer: {
                Text("逆向分析属于这个插件项目：分析 App、IPA、DEB 或 dylib 后，结论直接用于 Hook 点和源码，不再另开孤立的逆向工具页面。")
            }

            Section("流水线状态") {
                Picker("当前阶段", selection: Binding(
                    get: { project.status },
                    set: { project.status = $0; saveProject() }
                )) {
                    ForEach(PluginProjectStatus.allCases, id: \.self) { status in
                        Text(status.label).tag(status)
                    }
                }
                if !project.artifact.isEmpty {
                    TextField("产物", text: Binding(
                        get: { project.artifact },
                        set: { project.artifact = $0; saved = false }
                    ))
                }
                if !project.lastError.isEmpty {
                    Text(project.lastError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
                Button {
                    saveProject()
                } label: {
                    Label(saved ? "项目资料已保存" : "保存项目资料",
                          systemImage: saved ? "checkmark.circle.fill" : "externaldrive")
                }
            }

            Section {
                Button {
                    saveProject()
                    UIPasteboard.general.string = project.workflowPrompt
                    copied = true
                } label: {
                    Label(copied ? "已复制，去对话里粘贴" : "复制完整工作流指令",
                          systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc")
                }
            } footer: {
                Text("对话负责实际分析、写源码和取证；这里保存项目阶段、分析对象和结果交接，避免换会话后丢失。")
            }
        }
        .navigationTitle(project.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button(role: .destructive) {
                        store.delete(project)
                        dismiss()
                    } label: {
                        Label("删除项目", systemImage: "trash")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .onDisappear {
            store.update(project)
        }
    }

    private func saveProject() {
        store.update(project)
        saved = true
    }
}

// MARK: - New project

private struct NewPluginProjectSheet: View {
    let onCreate: (String, String, PluginAnalysisKind, String, String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var effect = ""
    @State private var target = ""
    @State private var analysisKind: PluginAnalysisKind = .app
    @State private var analysisMaterial = ""
    @State private var analysisQuestion = ""

    var body: some View {
        NavigationView {
            Form {
                Section("你想要什么效果？") {
                    TextEditor(text: $effect)
                        .frame(minHeight: 110)
                }
                Section {
                    TextField("可留空，AI 自己判断", text: $target)
                } header: {
                    Text("指定目标（可选）")
                } footer: {
                    Text("比如 SpringBoard、控制中心，或某个 App 的名称。")
                }
                Section("项目内逆向分析（可选）") {
                    Picker("资料类型", selection: $analysisKind) {
                        ForEach(PluginAnalysisKind.allCases, id: \.self) { kind in
                            Text(kind.label).tag(kind)
                        }
                    }
                    TextField("App 名、Bundle ID、IPA/DEB/dylib 路径或链接", text: $analysisMaterial)
                    TextEditor(text: $analysisQuestion)
                        .frame(minHeight: 72)
                } footer: {
                    Text("填了资料后，创建项目会把逆向分析作为第一阶段交给同一个插件项目，不再打开独立逆向页面。")
                }
            }
            .navigationTitle("新建插件项目")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("创建并开始") {
                        onCreate(effect, target, analysisKind, analysisMaterial, analysisQuestion)
                        dismiss()
                    }
                    .disabled(effect.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .navigationViewStyle(.stack)
    }
}
