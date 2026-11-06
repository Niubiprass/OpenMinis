import SwiftUI

struct MiniSightDialoguePage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared

    var body: some View {
        List {
            Section {
                LabeledContent("气泡大小 \(String(format: "%.2f", config.bubbleScale))×") {
                    Slider(value: $config.bubbleScale, in: 0.8...1.35, step: 0.05)
                }
                LabeledContent("文字大小 \(String(format: "%.2f", config.textScale))×") {
                    Slider(value: $config.textScale, in: 0.8...1.35, step: 0.05)
                }
                LabeledContent("停留速度 \(String(format: "%.2f", config.dwell))×") {
                    Slider(value: $config.dwell, in: 0.5...2.0, step: 0.05)
                }
            } header: { Text("气泡与文字") } footer: {
                Text("气泡与文字同时影响 App 内和越狱桌宠的短气泡。长回复保持限高可滚动。")
            }

            Section {
                Picker("回车键", selection: $config.returnKey) {
                    Text("发送").tag("send")
                    Text("换行").tag("newline")
                }
                .pickerStyle(.segmented)
            } header: { Text("输入") }

            Section {
                Toggle("对话朗读", isOn: $config.voiceReply)
                Toggle("语音输入", isOn: $config.voiceInput)
                Picker("入睡打鼾", selection: $config.snore) {
                    Text("关闭").tag("off")
                    Text("约 8 秒").tag("short")
                    Text("醒来前持续").tag("until_wake")
                }
            } header: { Text("声音") } footer: {
                Text(config.voiceInput
                     ? "语音输入已启用：点输入条的麦克风开始听写，转写进入草稿，仍需手动发送。"
                     : "语音输入开启后会申请麦克风和语音识别权限；拒绝时仍可用键盘。")
            }
        }
        .navigationTitle("气泡、聊天与声音")
        .onDisappear { config.persistAll() }
    }
}
