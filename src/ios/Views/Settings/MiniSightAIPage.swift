import Foundation
import SwiftUI

/// One connection editor. A provider label is only a URL preset, never proof
/// that a key/model was tested. The test saves exactly these three fields first.
struct MiniSightAIPage: View {
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var supplier = MiniSightSupplier.custom.rawValue
    @State private var url = ""
    @State private var key = ""
    @State private var model = ""
    @State private var persona = ""
    @State private var notice = ""
    @State private var failed = false
    @State private var testing = false
    @State private var client: MiniSightAI?
    @State private var generation = 0
    @State private var cooldownUntil = Date.distantPast
    @State private var personaWork: DispatchWorkItem?
    private let presets: [MiniSightSupplier] = [.custom, .deepseek, .chatgpt, .gemini, .qwen, .kimi, .minimax]

    var body: some View {
        List {
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(presets, id: \.self) { item in
                            Button(item.title) { applySupplier(item.rawValue) }
                                .buttonStyle(.bordered)
                                .tint(item.rawValue == supplier ? .accentColor : .secondary)
                                .disabled(testing)
                        }
                    }.padding(.vertical, 2)
                }
                TextField("接口链接（Base URL 或完整 chat/completions）", text: $url)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    .disabled(testing)
                SecureField("API Key", text: $key).disabled(testing)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                TextField("模型 ID", text: $model)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().disabled(testing)
            } header: { Text("AI 连接") } footer: {
                Text("只支持 OpenAI 兼容接口。Claude 请使用中转/兼容链接；切换预设会清空旧 Key 和模型，避免发错服务。")
            }
            Section {
                TextField("人设（可选，自动保存）", text: $persona)
                    .font(.footnote).textInputAutocapitalization(.never)
                    .onChange(of: persona) { _ in schedulePersona() }
            } header: { Text("人设") }
            Section {
                Button("保存连接") { _ = saveConnection() }.disabled(testing)
                Button(testing ? "等待真实回答…" : "保存并测试真实回答") { Task { await runTest() } }
                    .disabled(testing || cooldownUntil > Date())
                if testing { Button("取消测试") { cancelTest() } }
                if !notice.isEmpty { Text(notice).font(.caption).foregroundStyle(failed ? Color.red : Color.secondary) }
            } footer: {
                Text("收到真实回答才算成功；HTTP 200 空正文也会报错。保存连接不等于对话已成功。")
            }
        }
        .navigationTitle("AI 连接")
        .onAppear(perform: load)
        .onDisappear { if testing { cancelTest() } }
    }
    private func load() {
        let stored = MiniSightPetFile.loadAI()
        url = stored.0; key = stored.1; model = stored.2; persona = stored.3
        supplier = presets.first { preset in
            guard let endpoint = preset.endpoint else { return false }
            return url == endpoint || url == endpoint + "/chat/completions"
        }?.rawValue ?? MiniSightSupplier.custom.rawValue
    }
    private func applySupplier(_ raw: String) {
        guard raw != supplier, let item = MiniSightSupplier(rawValue: raw) else { return }
        supplier = raw; url = item.endpoint ?? ""; key = ""; model = ""
        notice = "请填写此接口的 Key 和模型，再保存测试。"; failed = false
    }
    @discardableResult private func saveConnection() -> Bool {
        let cleanKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanModel = model.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let endpoint = MiniSightAITest.endpoint(for: url), let parsed = URLComponents(string: endpoint),
              parsed.user == nil, parsed.password == nil, parsed.fragment == nil,
              parsed.host?.lowercased() != "api.anthropic.com",
              !cleanKey.isEmpty, cleanKey.rangeOfCharacter(from: .controlCharacters) == nil,
              !cleanModel.isEmpty, cleanModel.rangeOfCharacter(from: .controlCharacters) == nil else {
            notice = "未保存：请填写有效的兼容链接、Key 和模型。"; failed = true
            MSDiagEvent("ai_test", "skip", "skipped", ["source": "settings", "reason": "invalid_connection"])
            return false
        }
        let request = UUID().uuidString
        MSDiagEvent("settings", "save", "pending", ["source": "settings", "setting": "ai_connection", "request": request])
        do {
            try MiniSightPetFile.saveAI(url: endpoint, key: cleanKey, model: cleanModel, systemPrompt: persona)
            config.supplier = supplier
            notice = "连接已保存，尚未测试回答。"; failed = false
            MSDiagEvent("settings", "readback", "ok", ["source": "settings", "setting": "ai_connection", "request": request, "readback": true])
            return true
        } catch {
            notice = "保存失败，原连接未确认替换。"; failed = true
            MSDiagEvent("settings", "readback", "failed", ["source": "settings", "setting": "ai_connection", "request": request, "code": (error as NSError).code])
            return false
        }
    }
    private func schedulePersona() {
        personaWork?.cancel()
        let work = DispatchWorkItem { savePersonaNow() }
        personaWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: work)
    }
    private func savePersonaNow() {
        guard !persona.isEmpty || MiniSightPetFile.loadAI().3.isEmpty else { return }
        do {
            _ = try MiniSightPetFile.savePersona(persona)
            MSDiagEvent("settings", "save", "ok", ["source": "settings", "setting": "ai_persona"])
        } catch {
            notice = "人设保存失败。"; failed = true
        }
    }
    private func runTest() async {
        guard saveConnection() else { return }
        testing = true; failed = false; notice = "正在等待回答…"
        generation &+= 1
        let owned = generation, request = UUID().uuidString, started = Date()
        let client = MiniSightAI(container: MiniSightPetFile.containerPath)
        self.client = client
        MSDiagEvent("ai_test", "click", "pending", ["source": "settings", "request": request])
        let reply: MiniSightAIReply = await withCheckedContinuation { cont in
            client.send("请用中文回答：1+1等于几？") { cont.resume(returning: $0) }
        }
        guard owned == generation else { return }
        testing = false; self.client = nil
        failed = !reply.isSuccess
        if reply.status == 429 { cooldownUntil = Date().addingTimeInterval(30) }
        notice = reply.isSuccess ? "测试回答：" + String(reply.text.prefix(180)) : reply.displayText
        MSDiagEvent("ai_test", "response", reply.isSuccess ? "ok" : "failed",
                    ["source": "settings", "request": request, "code": reply.status,
                     "chars": reply.text.count, "duration_ms": Int(Date().timeIntervalSince(started) * 1000)])
        // Keep only the outcome, never the answer, key, URL or model in diagnostics.
        try? MiniSightPetFile.saveTestRecord(ok: reply.isSuccess, status: reply.isSuccess ? "真实回答通过" : "测试失败 HTTP \(reply.status)",
                                            cooldownUntil: cooldownUntil, revision: MiniSightPetFile.aiConfigRevision)
    }
    private func cancelTest() {
        generation &+= 1; client?.cancel(); client = nil; testing = false
        notice = "测试已取消。"; failed = false
    }
}
