import SwiftUI

/// Name editing is transactional: validating/cancelling never starts a mic or
/// writes settings. Only an explicit saved toggle can request record permission.
struct MiniSightWakePage: View {
    @StateObject private var config = MiniSightConfigStore.shared
    @StateObject private var wake = MiniSightWakeController.shared
    @State private var name = ""
    @State private var pronunciation = ""
    @State private var validating = false
    @State private var prepared: MiniSightWakeName.Prepared?
    @State private var confirmReading = false
    @State private var confirmMicrophone = false
    @State private var notice = ""
    @State private var loaded = false
    @State private var validation = UUID()

    var body: some View {
        List {
            Section {
                TextField("比如：小鱼、小肥鱼", text: $name)
                    .textInputAutocapitalization(.never).disableAutocorrection(true)
                    .disabled(validating || wake.permissionPending)
                TextField("多音字可填：xiao3 yu2（可选）", text: $pronunciation)
                    .textInputAutocapitalization(.never).disableAutocorrection(true)
                    .disabled(validating || wake.permissionPending)
                Button("检查读音并保存名字") { validate() }
                    .disabled(validating || wake.permissionPending)
                if validating { ProgressView("正在本机检查；尚未开麦") }
                if !notice.isEmpty { Text(notice).font(.caption).foregroundStyle(.secondary) }
                if !config.wakeName.isEmpty {
                    Text("已保存：\(config.wakeName) · \(config.wakePronunciation)")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } header: { Text("桌宠的唤醒名字") } footer: {
                Text("名字使用 2–8 个汉字，避免过短误唤醒。普通字先本地转换拼音，多音字或生僻字需要校读。保存前请确认显示的读音；不是每个名字都能可靠识别。不修改 Siri，不需要说“嘿 Siri”。")
            }
            Section {
                Toggle("后台名字唤醒", isOn: Binding(
                    get: { config.wakeEnabled },
                    set: { on in
                        if on { confirmMicrophone = true }
                        else { wake.requestEnabled(false) }
                    }))
                    .disabled(wake.permissionPending || validating)
                if wake.permissionPending { ProgressView("等待你允许麦克风权限") }
                Text(wake.status).font(.caption).foregroundStyle(.secondary)
                if config.wakeEnabled {
                    Button("重新检查监听") { wake.retry() }
                        .disabled(wake.permissionPending || validating)
                }
            } header: { Text("名字监听") } footer: {
                Text("默认关闭。开启并允许权限后，回到主屏幕或打开其他 App 仍在本机等你喊名字，由越狱插件在当前屏幕回应。关闭立即停止名字监听、释放麦克风，名字保留。系统会显示麦克风指示，监听有额外耗电；日常声音不保存、不上传。通话、录屏、锁定或其他语音占用时临时退让。需要 App 和插件配套更新；强退、系统回收或重启后需再次打开 App，不保证被杀后永驻。音乐与蓝牙效果还需真机验证。")
            }
            Section {
                Text("喊到名字后先回应“我在”，再进入现有短语音输入。转写进草稿，仍需你手动发送；不会自动执行命令或代你同意审批。唤醒后的语音识别与聊天遵循原设置和权限，不宣称全部离线。")
                    .font(.caption).foregroundStyle(.secondary)
            } header: { Text("回应与对话") }
        }
        .navigationTitle("名字唤醒")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("确认这个读音？", isPresented: $confirmReading, titleVisibility: .visible) {
            Button("按这个读音保存") {
                guard let prepared else { return }
                wake.saveName(prepared)
                pronunciation = prepared.pronunciation
                notice = "名字和读音已保存；开关关闭时不会启动监听。"
                self.prepared = nil
            }
            Button("取消", role: .cancel) { prepared = nil }
        } message: {
            if let prepared { Text("\(prepared.name) → \(prepared.pronunciation)") }
        }
        .confirmationDialog("允许本机名字监听？", isPresented: $confirmMicrophone, titleVisibility: .visible) {
            Button("开启并允许麦克风、语音权限") { wake.requestEnabled(true) }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会使用麦克风并出现系统指示，离开 App 后继续在本机等你喊名字。日常声音不保存、不上传；通话、录屏和锁定时停止。先保存并确认名字读音。本次还会申请后续短语音识别的权限；后台命中不会自动弹权限页或发送消息。")
        }
        .onAppear {
            wake.install()
            if !loaded { name = config.wakeName; pronunciation = config.wakePronunciation; loaded = true }
        }
        .onDisappear {
            validation = UUID(); validating = false; prepared = nil; confirmReading = false
        }
    }
    private func validate() {
        let ticket = UUID(); validation = ticket; validating = true; notice = ""
        let candidate = name, reading = pronunciation
        wake.validate(name: candidate, pronunciation: reading) { result in
            guard validation == ticket else { return }
            validating = false
            switch result {
            case .success(let value): prepared = value; confirmReading = true
            case .failure(let error): notice = error.localizedDescription
            }
        }
    }
}
