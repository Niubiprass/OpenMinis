import SwiftUI

struct MiniSightPermissionsPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared

    var body: some View {
        List {
            Section {
                Toggle("允许主动发起对话", isOn: $config.proactive)
                LabeledContent("主动互动间隔 \(Int(config.proactiveInterval)) 分钟") {
                    Slider(value: $config.proactiveInterval, in: 10...120, step: 5)
                }
            } header: { Text("主动互动") } footer: {
                Text("默认关闭；开启后会联网。锁屏、隐藏或没有可用 AI 配置时暂停，连续无回应会延长间隔。")
            }

            Section {
                Toggle("允许 AI 提议调整桌宠", isOn: $config.aiAdjust)
            } footer: {
                Text("关闭时 AI 不能改桌宠。开启后，只有勾选的项可直接执行；未勾选项先在气泡询问。")
            }

            Section {
                ForEach(MiniSightAIPermission.allCases, id: \.self) { permission in
                    Toggle(permission.title, isOn: Binding(
                        get: { config.permissions.contains(permission) },
                        set: { config.setPermission(permission, allowed: $0) }
                    ))
                }
                Button("全部取消") {
                    for permission in MiniSightAIPermission.allCases { config.setPermission(permission, allowed: false) }
                }
                Button("全部允许") {
                    for permission in MiniSightAIPermission.allCases { config.setPermission(permission, allowed: true) }
                }
            } header: { Text("可直接执行") }

            Section {
                if config.adjustments.isEmpty {
                    Text("还没有 AI 调整记录").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(Array(config.adjustments.enumerated()), id: \.offset) { _, text in
                    Text(text).font(.caption)
                }
            } header: { Text("最近调整") }

            Section {
                Picker("调整确认", selection: Binding(
                    get: { config.permissions.isEmpty ? "ask" : "ask" },
                    set: { _ in }
                )) {
                    Text("未授权项先询问").tag("ask")
                }
                .disabled(true)
            } footer: {
                Text("白名单只覆盖桌宠本身，不会修改服务商 Key、任意文件或手机状态。")
            }
        }
        .navigationTitle("主动互动与权限")
        .onDisappear { config.persistAll() }
    }
}
