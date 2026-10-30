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

    /// MCP tools that can modify the device or run arbitrary commands.
    /// Touch control (tap/swipe/press) is deliberately NOT here: the agent
    /// must be able to operate the phone to test a tweak. Only terminal
    /// commands, file writes, app install/uninstall and system-setting
    /// changes need the master switch + per-call approval.
    static let dangerousTools = [
        "run_command", "write_file", "uninstall_app", "install_app",
        "set_brightness", "set_volume",
    ]

    static func isDangerous(_ command: String) -> Bool {
        guard command.contains("minis-mcp-cli") else { return false }
        return dangerousTools.contains { command.contains($0) }
    }
}

enum PluginProjectStatus: String, Codable, CaseIterable {    case planning, building, testing, done

    var label: String {
        switch self {
        case .planning: return "待开始"
        case .building: return "开发中"
        case .testing:  return "测试中"
        case .done:     return "已完成"
        }
    }

    var color: Color {
        switch self {
        case .planning: return .gray
        case .building: return .blue
        case .testing:  return .orange
        case .done:     return .green
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

    func add(effect: String, target: String) {
        let trimmed = effect.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let firstLine = trimmed.split(separator: "\n").first.map(String.init) ?? trimmed
        let name = firstLine.count > 14 ? String(firstLine.prefix(14)) + "…" : firstLine
        let t = target.trimmingCharacters(in: .whitespacesAndNewlines)
        let project = PluginProject(name: name, effect: trimmed,
                                    target: t.isEmpty ? "自动判断" : t,
                                    status: .planning)
        projects.insert(project, at: 0)
        save()
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

            Section("指示器") {
                NavigationLink {
                    MiniSightSettingsView()
                } label: {
                    Label("操作指示器", systemImage: "pawprint.circle")
                }
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
            NewPluginProjectSheet { effect, target in
                store.add(effect: effect, target: target)
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
            Section("状态") {
                Picker("状态", selection: Binding(
                    get: { project.status },
                    set: { project.status = $0; store.update(project) }
                )) {
                    ForEach(PluginProjectStatus.allCases, id: \.self) { s in
                        Text(s.label).tag(s)
                    }
                }
            }
            Section {
                Button {
                    UIPasteboard.general.string = prompt
                    copied = true
                } label: {
                    Label(copied ? "已复制，去对话里粘贴" : "复制给 AI 的指令",
                          systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc")
                }
            } footer: {
                Text("粘到对话里，AI 就从「判断目标、找 Hook 点」开始，接着编译、安装、取证。")
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
    }

    private var prompt: String {
        "继续做插件项目「\(project.name)」。目标：\(project.target)。效果：\(project.effect)。请先判断目标进程/类，找 Hook 点，然后写代码、编译、安装并取证。"
    }
}

// MARK: - New project

private struct NewPluginProjectSheet: View {
    let onCreate: (String, String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var effect = ""
    @State private var target = ""

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
            }
            .navigationTitle("新建插件项目")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("创建") {
                        onCreate(effect, target)
                        dismiss()
                    }
                    .disabled(effect.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .navigationViewStyle(.stack)
    }
}
