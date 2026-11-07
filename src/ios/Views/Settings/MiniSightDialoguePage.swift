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
                Toggle("操作时录屏", isOn: $config.record)
                Text("录像保存在本机 Documents/MiniSight/recordings，文件校验通过才提示成功。")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("录屏") }

            Section {
                Toggle("对话朗读", isOn: $config.voiceReply)
                Toggle("语音输入", isOn: $config.voiceInput)
                Picker("入睡打鼾", selection: $config.snore) {
                    Text("关闭").tag("off")
                    Text("约 8 秒").tag("short")
                    Text("醒来前持续").tag("until_wake")
                }
            } header: { Text("声音") } footer: {
                Text("点输入条麦克风开始，再点一次结束；转写进入草稿，仍需手动发送。首次会申请麦克风/语音权限，拒绝或引擎不可用时保留键盘输入。")
            }
        }
        .navigationTitle("聊天、语音与录屏")
        .onDisappear { config.persistAll() }
    }
}
