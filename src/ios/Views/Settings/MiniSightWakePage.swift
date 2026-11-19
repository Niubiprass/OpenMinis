import SwiftUI

/// Background name wake is removed. Manual ChatPanel microphone input remains.
struct MiniSightWakePage: View {
    @AppStorage("minisight.wake.enabled") private var wakeEnabled = false
    @AppStorage("minisight.wake.name") private var wakeName = ""
    @AppStorage("minisight.wake.pronunciation") private var wakePronunciation = ""

    var body: some View {
        List {
            Section {
                Text("后台名字唤醒已移除")
                Text("后台持续监听会长期占用麦克风并显示系统隐私提示，普通 App 不能像 Siri 一样使用系统级低功耗唤醒。手动语音输入仍保留，请点击聊天输入框的麦克风按钮。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                TextField("历史唤醒名字（兼容保留）", text: $wakeName)
                    .disabled(true)
                TextField("历史读音（兼容保留）", text: $wakePronunciation)
                    .disabled(true)
                Text("旧设置不会启动监听，也不会申请麦克风权限。")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("兼容数据") }
        }
        .navigationTitle("名字唤醒")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { wakeEnabled = false }
    }
}
