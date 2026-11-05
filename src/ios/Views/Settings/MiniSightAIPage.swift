import SwiftUI
import UIKit

/// AI connection, persona and test. Connection save never implies a successful
/// reply; test and both chat surfaces use the same MiniSightAI client.
struct MiniSightAIPage: View {
    @EnvironmentObject private var config: MiniSightConfigStore
    @State private var url = ""
    @State private var key = ""
    @State private var model = ""
    @State private var savedSnapshot: [String] = []
    @State private var savedAt: Date?
    @State private var saveNotice: String?
    @State private var saveOK = false
    @State private var testStatus: String?
    @State private var testOK = false
    @State private var testing = false
    @State private var client: MiniSightAI?
    @State private var testGeneration = 0
    @State private var cooldownUntil: Date?
    @State private var loaded = false
    @State private var personaStatus = "人设尚未读取"
    @State private var personaFailed = false
    @State private var saveWork: DispatchWorkItem?
    @State private var saveGeneration = 0
    @State private var request = ""

    private var descendant: String { config.persona }

    var body: some View {
        List {
            Section("接口连接") {
                TextField("接口地址，例如 https://api.openai.com/v1", text: $url)
                    .font(.system(.footnote, design: .monospaced))
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("API Key", text: $key).font(.system(.footnote, design: .monospaced))
                TextField("模型名", text: $model)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                HStack {
                    Button("保存") { saveConnection() }.buttonStyle(.bordered)
                    Button(testing ? "测试中…" : "测试真实回答") { Task { await runTest() } }
                        .buttonStyle(.bordered).disabled(testing || (cooldownUntil ?? .distantPast) > Date())
                    if testing { Button("取消") { cancelTest() }.buttonStyle(.bordered) }
                }
                if let saveNotice {
                    Text(saveNotice).font(.caption)
                        .foregroundStyle(saveOK ? Color.secondary : Color.red)
                }
                Text(testStatus ?? "还没有测试过；测试只使用已保存的配置。")
                    .font(.caption)
                    .foregroundStyle(testOK ? Color.green : (testStatus == nil ? Color.secondary : Color.red))
            } footer: {
                Text("地址、Key、模型需要点保存；两者读取同一份 ai.json。收到真实正文才算成功，HTTP 200 空正文按失败处理。")
            }

            Section("AI 人设") {
                TextEditor(text: $config.persona)
                    .frame(minHeight: 110)
                    .onChange(of: config.persona) { value in schedulePersona(value) }
                Text(personaStatus).font(.caption).foregroundStyle(personaFailed ? Color.red : Color.secondary)
                Button("恢复默认人设") { config.persona = ""; savePersonaNow() }
            } footer: {
                Text("停止输入片刻或离开页面自动保存到 ai.json；最多 2000 字，失败保留输入。")
            }

            Section {
                TextField("例如：小北", text: $config.nickname)
                    .textInputAutocapitalization(.never)
            } header: { Text("用户称呼") } footer: {
                Text("会加入给桌宠的系统提示词；留空不写入。")
            }
        }
        .navigationTitle("AI 服务与人设")
        .onAppear(perform: load)
        .onDisappear { savePersonaNow() }
        .onChange(of: config.darkMode) { _ in config.persistAll() }
    }

    private var aiURL: URL { MiniSightPetFile.aiConfigURL }

    private func load() {
        let ai = MiniSightPetFile.loadAI()
        url = ai.0; key = ai.1; model = ai.2
        savedSnapshot = [ai.0, ai.1, ai.2]
        savedAt = MiniSightPetFile.aiConfigSavedAt
        loaded = true
        if config.persona != ai.3 {
            config.persona = ai.3
        }
        personaStatus = ai.3.isEmpty ? "默认人设" : "已从本机读取"
        restoreTestStatus()
    }

    private func saveConnection() {
        let cleanKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
        let cleanModel = model.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let endpoint = MiniSightAITest.endpoint(for: url),
              !cleanKey.isEmpty, !cleanModel.isEmpty else {
            saveNotice = "未保存：地址、Key 或模型不完整。"; saveOK = false; return
        }
        MSDiagEvent("settings", "save", "pending", ["setting": "ai_connection", "source": "settings"])
        do {
            try MiniSightPetFile.saveAI(url: endpoint, key: cleanKey, model: cleanModel, systemPrompt: config.persona)
            savedSnapshot = [endpoint, cleanKey, cleanModel]
            savedAt = MiniSightPetFile.aiConfigSavedAt ?? Date()
            saveNotice = "已保存并核对（只写本机文件）。"; saveOK = true
            MSDiagEvent("settings", "readback", "ok", ["setting": "ai_connection", "source": "settings", "readback": true])
        } catch {
            saveNotice = "保存失败：写盘或读回核对失败。"; saveOK = false
            MSDiagEvent("settings", "readback", "failed", ["setting": "ai_connection", "code": (error as NSError).code])
        }
    }

    private func schedulePersona(_ value: String) {
        guard loaded else { return }
        saveWork?.cancel(); saveGeneration += 1
        let generation = saveGeneration
        let work = DispatchWorkItem { guard generation == saveGeneration, loaded else { return }; savePersonaNow() }
        saveWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: work)
    }

    private func savePersonaNow() {
        saveWork?.cancel(); saveWork = nil; saveGeneration += 1
        let prompt = MiniSightAIConfigFile.normalizedPersona(config.persona)
        MSDiagEvent("settings", "save", "pending", ["setting": "ai_persona", "source": "settings"])
        do {
            _ = try MiniSightPetFile.savePersona(prompt)
            personaFailed = false
            personaStatus = "人设已保存并核对"
            MSDiagEvent("settings", "readback", "ok", ["setting": "ai_persona", "readback": true])
        } catch {
            personaFailed = true
            personaStatus = "人设保存失败，输入仍保留。"
            MSDiagEvent("settings", "readback", "failed", ["setting": "ai_persona", "code": (error as NSError).code])
        }
    }

    private func runTest() async {
        request = UUID().uuidString
        MSDiagEvent("ai_test", "click", "pending", ["request": request, "source": "settings"])
        guard let endpoint = MiniSightAITest.endpoint(for: url),
              let target = URL(string: endpoint),
              !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            testStatus = "未测试：地址、Key 或模型不完整"; testOK = false
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "invalid_input"])
            return
        }
        savePersonaNow()
        testing = true; testOK = false
        testStatus = "请求中…"
        testGeneration += 1
        let generation = testGeneration
        let client = MiniSightAI(container: MiniSightPetFile.containerPath)
        self.client = client
        let started = Date()
        let reply: MiniSightAIReply = await withCheckedContinuation { cont in
            client.send("你好，请只回答一句简短的中文。") { reply in cont.resume(returning: reply) }
        }
        defer { if generation == testGeneration { testing = false; self.client = nil } }
        guard generation == testGeneration else { return }
        let duration = Int(Date().timeIntervalSince(started) * 1000)
        MSDiagEvent("ai_test", "response", reply.isSuccess ? "ok" : "failed",
                    ["request": request, "code": reply.status, "chars": reply.text.count, "duration_ms": duration])
        if reply.status == 429 { cooldownUntil = Date().addingTimeInterval(30) }
        testOK = reply.isSuccess
        testStatus = reply.isSuccess ? "收到真实回答（\(reply.text.count) 字）" : "失败：\(reply.issue.rawValue)，状态 \(reply.status)"
        try? MiniSightPetFile.saveTestRecord(ok: testOK, status: testStatus ?? "", cooldownUntil: cooldownUntil,
                                            revision: MiniSightPetFile.aiConfigRevision)
        _ = target
    }

    private func cancelTest() {
        testGeneration += 1
        testing = false
        client?.cancel()
        client = nil
        testStatus = "测试已取消"
        testOK = false
    }

    private func restoreTestStatus() {
        if let item = MiniSightPetFile.loadTestRecord() {
            testStatus = item.status; testOK = item.ok; cooldownUntil = item.cooldown
        }
    }
}
