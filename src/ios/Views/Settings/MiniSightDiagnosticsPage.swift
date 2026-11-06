import SwiftUI
import UIKit

struct MiniSightDiagnosticsPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var showLogs = false
    @State private var exportURL: URL?
    @State private var resetAppearance = false
    @State private var clearChat = false
    @State private var assets: [(String, Int)] = []
    @State private var deleteAssets = false
    @State private var notice: String?

    var body: some View {
        List {
            Section {
                Toggle("操作时录屏", isOn: $config.record)
                Toggle("长按指示器切换录屏", isOn: $config.longPressRecord)
                Text("保存在本机 Documents/MiniSight/recordings；只有文件通过校验才提示保存成功。")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("录屏") }

            Section {
                Toggle("记录详细诊断", isOn: $config.diagnostics)
                Button { showLogs = true } label: { Label("查看运行日志", systemImage: "doc.text.magnifyingglass") }
                Button { exportLogs() } label: { Label("导出脱敏日志", systemImage: "square.and.arrow.up") }
            } header: { Text("诊断") } footer: {
                Text("基础状态事件始终本机记录，开关只控制详细日志。导出不含 Key、人设或聊天正文。")
            }

            Section {
                if assets.isEmpty {
                    Text("没有可删除的已导入素材包").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(assets, id: \.0) { item in
                    HStack { Text(item.0).font(.caption); Spacer(); Text("\(item.1 / 1024) KB").font(.caption2).foregroundStyle(.secondary) }
                }
                if !assets.isEmpty {
                    Button("删除已导入素材包", role: .destructive) { deleteAssets = true }
                }
            } header: { Text("素材") }

            Section {
                Button("清除桌宠聊天记录", role: .destructive) { clearChat = true }
                Button("重置外观与位置", role: .destructive) { resetAppearance = true }
            } header: { Text("清理") } footer: {
                Text("清聊天只清桌宠对话，不删主会话或服务商配置；重置不会删除精灵图。")
            }

            if let notice {
                Section { Text(notice).font(.caption) }
            }
        }
        .navigationTitle("录屏与诊断")
        .onAppear { assets = MiniSightAssetCatalog.load().map { ($0.name, $0.bytes) } }
        .sheet(isPresented: $showLogs) { MiniSightRuntimeLogView() }
        .sheet(item: Binding(get: { exportURL.map(MiniSightExport.init) }, set: { exportURL = $0?.url })) {
            MiniSightShareSheet(url: $0.url)
        }
        .alert("删除全部素材包？", isPresented: $deleteAssets) {
            Button("删除", role: .destructive) { removeAssets() }
            Button("取消", role: .cancel) {}
        } message: { Text("只删除本地导入副本；当前精灵图不会被替换。") }
        .alert("清除桌宠聊天记录？", isPresented: $clearChat) {
            Button("清除", role: .destructive) {
                MiniSightChatPanel.existing()?.clearConversation()
                notice = "桌宠聊天已清除。"
            }
            Button("取消", role: .cancel) {}
        }
        .alert("重置外观和位置？", isPresented: $resetAppearance) {
            Button("重置", role: .destructive) { resetAll() }
            Button("取消", role: .cancel) {}
        } message: { Text("会恢复默认配色、大小、气泡外观和默认位置，不删除 AI 配置。") }
    }

    private func exportLogs() {
        do { exportURL = try MiniSightSettingsDiagnostics.exportBundle() }
        catch {
            notice = "导出失败：\(error.localizedDescription)"
            MSDiagEvent("settings", "load", "failed", ["setting": "runtime_logs", "code": (error as NSError).code])
        }
    }

    private func removeAssets() {
        let dir = MiniSightAssetCatalog.dir
        for name in assets.map(\.0) { try? FileManager.default.removeItem(at: dir.appendingPathComponent(name)) }
        assets = []
        notice = "素材包已删除。"
    }

    private func resetAll() {
        config.tint = "natural"
        config.costume = ""
        config.petSize = 96
        config.bubbleScale = 1
        config.textScale = 1
        config.dwell = 1
        config.darkMode = "system"
        config.bottomGap = 12
        UserDefaults.standard.removeObject(forKey: "minisight.pet.x")
        UserDefaults.standard.removeObject(forKey: "minisight.pet.y")
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName("com.openminis.minisight.position" as CFString), nil, nil, true)
        config.persistAll()
        notice = "外观和位置已重置。"
    }
}

private struct MiniSightExport: Identifiable { let url: URL; var id: String { url.path } }

private struct MiniSightShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ viewController: UIActivityViewController, context: Context) {}
}

extension MiniSightSettingsDiagnostics {
    /// Build the same sanitized text the viewer shows, plus the plugin tail.
    static func exportBundle() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("MiniSight-export-\(Int(Date().timeIntervalSince1970))", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        for (index, name) in logFiles.enumerated() where name.hasPrefix("diagnostic-app") || name.hasPrefix("diagnostic-plugin") {
            let file = MiniSightPetFile.directory.appendingPathComponent(name)
            guard let data = try? Data(contentsOf: file) else { continue }
            let safe = data.split(separator: 10).compactMap { sanitizedEvent(String(decoding: $0, as: UTF8.self)) }.joined(separator: "\n")
            guard !safe.isEmpty else { continue }
            try safe.write(to: dir.appendingPathComponent(name + ".txt"), atomically: true, encoding: .utf8)
        }
        let zip = FileManager.default.temporaryDirectory.appendingPathComponent(dir.lastPathComponent + ".zip")
        try? FileManager.default.removeItem(at: zip)
        // A folder is acceptable to the share sheet; keep it simple and honest.
        _ = index
        return dir
    }
}
