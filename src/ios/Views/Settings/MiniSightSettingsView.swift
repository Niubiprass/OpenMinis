//
//  MiniSightSettingsView.swift
//  Minis
//
//  [T-minisight-pet] Settings for the MiniSight operation indicator. The pet
//  artwork is user-imported (Photos or Files, Petdex 9-row sheets); nothing is
//  bundled, matching how SwipeDeck / Bottom-x do it. The imported sheet is
//  downscaled to 768 px wide and written to the app's Documents so the
//  SpringBoard tweak can read it without any sandbox escape.
//

import CoreFoundation
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import UIKit

private enum MiniSightPetFile {
    static var directory: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let dir = base.appendingPathComponent("MiniSight", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static var url: URL { directory.appendingPathComponent("pet.png") }

    static func load() -> UIImage? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return UIImage(data: data)
    }

    /// 9-row sheets are 1536 px wide on Petdex; 768 is plenty for a 96 pt pet.
    static func save(_ image: UIImage) -> Bool {
        let maxWidth: CGFloat = 768
        let scale = min(1, maxWidth / max(image.size.width, 1))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: size)
        let scaled = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        guard let data = scaled.pngData() else { return false }
        do {
            try data.write(to: url, options: .atomic)
            return true
        } catch {
            return false
        }
    }

    static func delete() {
        try? FileManager.default.removeItem(at: url)
    }

    static var aiConfigURL: URL { directory.appendingPathComponent("ai.json") }
    static var shownURL: URL { directory.appendingPathComponent("shown") }

    static func loadShown() -> Bool {
        guard let data = try? Data(contentsOf: shownURL) else { return true }
        return String(data: data, encoding: .utf8) != "0"
    }

    static func saveShown(_ on: Bool) {
        try? Data((on ? "1" : "0").utf8).write(to: shownURL, options: .atomic)
    }

    static func loadAI() -> (String, String, String) {
        guard let data = try? Data(contentsOf: aiConfigURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        else { return ("", "", "") }
        return (obj["url"] ?? "", obj["key"] ?? "", obj["model"] ?? "")
    }

    static func saveAI(url: String, key: String, model: String) throws {
        let obj = ["url": url, "key": key, "model": model]
        let data = try JSONSerialization.data(withJSONObject: obj)
        try data.write(to: aiConfigURL, options: .atomic)
    }

    /// 配置文件的落盘时间；没有文件时为 nil。给「已保存」状态单独一行用，
    /// 与网络测试结果互不影响（也不改动 ai.json 的既有格式）。
    static var aiConfigSavedAt: Date? {
        let path = aiConfigURL.path
        guard FileManager.default.fileExists(atPath: path),
              let attributes = try? FileManager.default.attributesOfItem(atPath: path) else { return nil }
        return attributes[.modificationDate] as? Date
    }
}

/// 仅供设置页的显式单次测试使用；不记录原始错误响应。
private enum MiniSightAITest {
    static let maxBodyBytes = 64 * 1024

    static func endpoint(for base: String) -> String? {
        let raw = base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty,
              raw.rangeOfCharacter(from: .whitespacesAndNewlines.union(.controlCharacters)) == nil,
              var parts = URLComponents(string: raw),
              let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.fragment == nil else { return nil }
        parts.scheme = scheme
        // 操作编码后的路径，保留查询参数以及自定义网关前缀，不猜测服务商。
        var path = parts.percentEncodedPath
        while path.hasSuffix("/") { path.removeLast() }
        if path.isEmpty { path = "/v1/chat/completions" }
        else if !path.hasSuffix("/chat/completions") { path += "/chat/completions" }
        parts.percentEncodedPath = path
        return parts.url?.absoluteString
    }

    /// Retry-After 支持整数秒和 HTTP-date；异常头默认 30 秒，冷却限定 1…300 秒。
    static func retryDelay(_ header: String?, now: Date) -> TimeInterval {
        guard let value = header?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty, value.utf8.count <= 128 else { return 30 }
        if value.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }) {
            guard let seconds = TimeInterval(value), seconds.isFinite else { return 300 }
            return min(300, max(1, seconds))
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.isLenient = false
        for format in ["EEE, dd MMM yyyy HH:mm:ss zzz", "EEEE, dd-MMM-yy HH:mm:ss zzz", "EEE MMM d HH:mm:ss yyyy"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value) {
                return min(300, max(1, ceil(date.timeIntervalSince(now))))
            }
        }
        return 30
    }

    /// 先脱敏再截断：包括已知 Key/查询值、Bearer、常见 sk- token 和链接。
    private static func safeText(_ text: String, secrets: [String], limit: Int) -> String {
        var cleaned = text
        for secret in Set(secrets.filter { !$0.isEmpty }).sorted(by: { $0.count > $1.count }) {
            cleaned = cleaned.replacingOccurrences(of: secret, with: "[已隐藏]")
            if let encoded = secret.addingPercentEncoding(withAllowedCharacters: .alphanumerics), encoded != secret {
                cleaned = cleaned.replacingOccurrences(of: encoded, with: "[已隐藏]", options: .caseInsensitive)
            }
        }
        for pattern in ["(?i)https?://[^\\s<>\"']+", "(?i)\\bBearer\\s+[^\\s,;\"'<>]+", "(?i)\\bsk-[A-Za-z0-9_-]+"] {
            cleaned = cleaned.replacingOccurrences(of: pattern, with: "[已隐藏]", options: .regularExpression)
        }
        cleaned = cleaned.unicodeScalars.map { scalar in
            CharacterSet.controlCharacters.contains(scalar) || CharacterSet.whitespacesAndNewlines.contains(scalar)
                ? " " : String(scalar)
        }.joined().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        return String(cleaned.prefix(limit)) + (cleaned.count > limit ? "…" : "")
    }

    private static func object(_ data: Data) -> [String: Any]? {
        guard data.count <= maxBodyBytes, String(data: data, encoding: .utf8) != nil else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    static func failure(_ status: Int, data: Data, tooLarge: Bool, secrets: [String]) -> String {
        let summary: String
        if status == 429 {
            summary = "HTTP 429（限流／配额／上游拥堵）：这是本次测试请求被拒，与配置有没有保存无关；按 Retry-After 冷却（无效时 30 秒，最长 300 秒），不会自动重试，也不影响已保存的配置。"
        } else if (300...399).contains(status) {
            summary = "测试返回 HTTP \(status)；为保护凭据未跟随重定向（不影响已保存的配置）。"
        } else {
            summary = "测试失败：HTTP \(status)（这次测试不发网络以外的影响，已保存的配置保持原样）。"
        }
        guard !tooLarge, data.count <= maxBodyBytes else {
            return summary + " 错误详情超过 64 KiB，已忽略。"
        }
        guard let error = object(data)?["error"] as? [String: Any] else {
            return summary + " 未提供可解析的 OpenAI JSON 错误详情（不回显原始响应）。"
        }
        var fields: [String] = []
        for (name, limit) in [("code", 64), ("type", 64), ("message", 200)] {
            let raw = (error[name] as? String) ?? (error[name] as? NSNumber)?.stringValue ?? ""
            let value = safeText(raw, secrets: secrets, limit: limit)
            if !value.isEmpty { fields.append("\(name)=\(value)") }
        }
        return summary + (fields.isEmpty ? " 错误详情为空。" : "\n" + fields.joined(separator: "；"))
    }

    static func reply(_ data: Data, tooLarge: Bool, secrets: [String]) -> String {
        guard !tooLarge, data.count <= maxBodyBytes else {
            return "HTTP 200，但响应超过 64 KiB，未解析（非 HTTP 错误）。"
        }
        guard let obj = object(data) else {
            return "HTTP 200，但响应不是有效 UTF-8 JSON（非 HTTP 错误）。"
        }
        let choices = obj["choices"] as? [[String: Any]]
        let message = choices?.first?["message"] as? [String: Any]
        var content = message?["content"] as? String ?? ""
        if let segments = message?["content"] as? [[String: Any]] {
            content = segments.compactMap { segment -> String? in
                guard let type = segment["type"] as? String, ["text", "output_text"].contains(type) else { return nil }
                return segment["text"] as? String
            }.joined(separator: "\n")
        }
        let result = safeText(content, secrets: secrets, limit: 240)
        return result.isEmpty
            ? "HTTP 200，但没有可显示的 message.content（非 HTTP 错误；不把推理字段当回复）。"
            : "测试成功：" + result
    }
}

private final class MiniSightAITestRedirectGuard: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

struct MiniSightSettingsView: View {
    /// 0 = capsule, 1 = pet.
    @AppStorage("minisight.style") private var style = 0
    @AppStorage("minisight.record") private var record = false
    @AppStorage("minisight.longPress") private var longPressToRecord = true
    @AppStorage("minisight.mode") private var mode = 0   // 0 = 仅调用时，1 = 常驻
    @State private var shown = true
    @AppStorage("minisight.petSize") private var petSize = 96.0
    @AppStorage("minisight.gravity") private var gravity = false

    @State private var aiURL = ""
    @State private var aiKey = ""
    @State private var aiModel = ""
    /// 「配置是否已保存」和「上次测试结果」是两条独立状态，各自一行、各自着色：
    /// 保存只写本机文件，测试只发网络请求，任何一方都不会改写另一方的显示。
    @State private var aiSavedAt: Date?
    @State private var aiSavedSnapshot: [String] = []
    @State private var aiSaveNotice: String?
    @State private var aiSaveOK = false
    @State private var aiTestStatus: String?
    @State private var aiTestOK = false
    @State private var aiTesting = false
    @State private var aiCooldownUntil: Date?
    @State private var petImage: UIImage?
    @State private var showPhotoPicker = false
    @State private var showFilePicker = false
    @State private var importError: String?

    var body: some View {
        List {
            Section {
                Picker("样式", selection: $style) {
                    Text("胶囊").tag(0)
                    Text("桌宠").tag(1)
                }
                .pickerStyle(.segmented)
            } footer: {
                Text("切换后立即生效。桌宠只在导入后可用。")
            }

            Section {
                Toggle("显示桌宠", isOn: $shown)
            } footer: {
                Text("双击桌宠也会关掉它；关掉后 MCP 调用也不再出现，要恢复就在这里打开。")
            }

            Section {
                Picker("显示方式", selection: $mode) {
                    Text("仅调用时").tag(0)
                    Text("常驻").tag(1)
                }
                .pickerStyle(.segmented)
            } header: {
                Text("显示方式")
            } footer: {
                Text("仅调用时：只有 AI 调用越狱 MCP 才出现，结束收起。常驻：一直在桌面，MCP 调用时额外弹说话气泡。")
            }

            Section {
                HStack(spacing: 12) {
                    if let petImage {
                        Image(uiImage: petImage)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 56, height: 60)
                            .background(Color.secondary.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    } else {
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.secondary.opacity(0.12))
                            .frame(width: 56, height: 60)
                            .overlay(Image(systemName: "pawprint").foregroundStyle(.secondary))
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(petImage == nil ? "还没有导入桌宠" : "已导入桌宠")
                        if petImage != nil {
                            Text("9 行 Petdex 精灵图").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Button { showPhotoPicker = true } label: {
                    Label("从相册导入（768×936 PNG）", systemImage: "photo.on.rectangle")
                }
                Button { showFilePicker = true } label: {
                    Label("从文件导入（Petdex webp）", systemImage: "folder")
                }
                if petImage != nil {
                    Button(role: .destructive) {
                        MiniSightPetFile.delete()
                        petImage = nil
                        style = 0
                    } label: {
                        Label("删除当前桌宠", systemImage: "trash")
                    }
                }
            } header: {
                Text("桌宠")
            } footer: {
                Text("素材从 petdex.dev 下载后导入；图集是 9 行动作（待机/走/跑/跳…），不是单张图。")
            }

            Section {
                HStack(spacing: 12) {
                    Text("大小")
                    Slider(value: $petSize, in: 36...140, step: 2)
                    Text("\(Int(petSize))")
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 34, alignment: .trailing)
                }
            } header: {
                Text("桌宠大小")
            } footer: {
                Text("36–140，立即生效。")
            }

            Section {
                Toggle("重力感应", isOn: $gravity)
            } header: {
                Text("桌宠重力感应")
            } footer: {
                Text("开启后，倾斜会左右摇摆，快速晃手机会触发摔倒/失衡感；关闭更省电。")
            }

            Section {
                TextField("接口地址，如 https://api.openai.com/v1", text: $aiURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.footnote, design: .monospaced))
                SecureField("API Key", text: $aiKey)
                    .font(.system(.footnote, design: .monospaced))
                TextField("模型名", text: $aiModel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                HStack(spacing: 10) {
                    Button {
                        Task { @MainActor in saveAIConfig() }
                    } label: {
                        Text("保存").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    // 「保存」不受测试中 / 冷却影响：测试失败或限流时也必须能存。
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let remaining = Self.cooldownSeconds(until: aiCooldownUntil, now: context.date)
                        Button {
                            Task { @MainActor in await testAI() }
                        } label: {
                            Text(aiTesting ? "测试中…" : (remaining > 0 ? "冷却中（\(remaining) 秒）" : "测试"))
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(aiTesting || remaining > 0)
                    }
                }
                VStack(alignment: .leading, spacing: 4) {
                    statusLine(title: "配置状态", text: saveStateText,
                               tint: (aiSavedAt != nil && aiDirty) ? Color.orange : Color.secondary)
                    statusLine(title: "上次测试",
                               text: aiTestStatus ?? "还没有测试过（测试不改动已保存的配置）。",
                               tint: aiTestOK ? Color.green : (aiTestStatus == nil ? Color.secondary : Color.red))
                    if let aiSaveNotice {
                        statusLine(title: "保存结果", text: aiSaveNotice,
                                   tint: aiSaveOK ? Color.secondary : Color.red)
                    }
                }
            } header: {
                Text("桌宠 AI")
            } footer: {
                Text("给桌宠点击说话用，OpenAI 兼容接口。不填或失败就用预置句子。Key 存在 App 容器的文件里，插件才能读到。\n「保存」只做本地校验并写 Documents/MiniSight/ai.json，不发任何网络请求；「测试」单独发一次请求，不改动已保存的配置，失败（含 429 限流）既不清空输入也不影响保存状态。冷却只作用于「测试」，「保存」随时可用。")
            }

            Section {
                Button("测试显示 3 秒") {
                    post("com.openminis.agent.started")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        post("com.openminis.agent.stopped")
                    }
                }
            } footer: {
                Text("用来确认指示器正常，不需要 AI 操作。")
            }

            Section {
                Toggle("操作时录屏", isOn: $record)
                Toggle("长按指示器切换录屏", isOn: $longPressToRecord)
            } header: {
                Text("录屏")
            } footer: {
                Text("录屏默认关闭。开启后，AI 开始操作就录，结束保存；长按可以随时手动开/关。")
            }
        }
        .navigationTitle("操作指示器")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            petImage = MiniSightPetFile.load()
            shown = MiniSightPetFile.loadShown()
            let ai = MiniSightPetFile.loadAI()
            aiURL = ai.0; aiKey = ai.1; aiModel = ai.2
            // 「已保存」状态从磁盘来（文件时间），与上次测试结果完全无关。
            aiSavedSnapshot = [ai.0, ai.1, ai.2]
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt
        }
        .onChange(of: style) { _ in flushAndPost("com.openminis.minisight.settings") }
        .onChange(of: mode) { _ in flushAndPost("com.openminis.minisight.settings") }
        .onChange(of: shown) { value in
            MiniSightPetFile.saveShown(value)
            flushAndPost(value ? "com.openminis.minisight.show" : "com.openminis.minisight.settings")
        }
        .onChange(of: petSize) { _ in flushAndPost("com.openminis.minisight.settings") }
        .onChange(of: gravity) { _ in flushAndPost("com.openminis.minisight.settings") }
        .sheet(isPresented: $showPhotoPicker) {
            MiniSightPhotoPicker { image in importImage(image) }
        }
        .sheet(isPresented: $showFilePicker) {
            MiniSightDocumentPicker { url in importFile(url) }
        }
        .alert("导入失败", isPresented: Binding(
            get: { importError != nil },
            set: { if !$0 { importError = nil } }
        )) {
            Button("好") { importError = nil }
        } message: {
            Text(importError ?? "")
        }
    }

    private func importImage(_ image: UIImage) {
        if MiniSightPetFile.save(image) {
            petImage = MiniSightPetFile.load()
            style = 1
        } else {
            importError = "保存失败，存储空间可能不足。"
        }
    }

    /// 保留合法查询参数；只改路径，不在诊断中回显 URL 或凭据。
    static func endpoint(for base: String) -> String? {
        MiniSightAITest.endpoint(for: base)
    }

    private static func cooldownSeconds(until: Date?, now: Date) -> Int {
        guard let until = until else { return 0 }
        return Int(min(300, max(0, ceil(until.timeIntervalSince(now)))))
    }

    /// 「已保存」状态行的文案：只看本机文件，与网络无关。
    private static let savedAtFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM-dd HH:mm:ss"
        return formatter
    }()

    private var saveStateText: String {
        guard let aiSavedAt = aiSavedAt else { return "还没保存过。" }
        let stamp = "已保存 · " + Self.savedAtFormatter.string(from: aiSavedAt)
        return aiDirty ? stamp + "，当前输入还没保存。" : stamp
    }

    /// 界面输入是否与最近一次成功保存的内容不同。地址按补全后的端点比较，
    /// 免得只差一个 /v1/chat/completions 就误报「未保存」。
    private var aiDirty: Bool {
        let endpoint = Self.endpoint(for: aiURL) ?? aiURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let current = [endpoint,
                       aiKey.trimmingCharacters(in: .whitespacesAndNewlines),
                       aiModel.trimmingCharacters(in: .whitespacesAndNewlines)]
        return current != aiSavedSnapshot
    }

    private func statusLine(title: String, text: String, tint: Color) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 60, alignment: .leading)
            Text(text)
                .font(.footnote)
                .foregroundStyle(tint)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// 保存与测试共用的本地校验结果（地址合法、Key/模型非空）。
    private struct AIConfigInput {
        let endpoint: String
        let key: String
        let model: String
    }

    /// 只做本地校验，不发网络请求。
    private func validatedAIInput() -> (config: AIConfigInput?, problem: String?) {
        let key = aiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = aiModel.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return (nil, "API Key 还没有填。") }
        guard key.rangeOfCharacter(from: .whitespacesAndNewlines.union(.controlCharacters)) == nil else {
            return (nil, "API Key 里有空格或换行。")
        }
        guard !model.isEmpty else { return (nil, "模型名还没有填。") }
        guard let endpoint = Self.endpoint(for: aiURL) else {
            return (nil, "接口地址不合法：须为 http(s)，且不能含用户名、密码或片段。")
        }
        return (AIConfigInput(endpoint: endpoint, key: key, model: model), nil)
    }

    /// 「保存」：本地校验 + 写 Documents/MiniSight/ai.json，完全不发网络请求，
    /// 因此保存成功与否只取决于磁盘，不受限流、断网、429 影响。
    @MainActor
    private func saveAIConfig() {
        let (config, problem) = validatedAIInput()
        guard let config = config else {
            aiSaveOK = false
            aiSaveNotice = "未保存：" + (problem ?? "输入不完整。") + "（这一步只看输入，不联网）"
            return
        }
        do {
            try MiniSightPetFile.saveAI(url: config.endpoint, key: config.key, model: config.model)
            aiSavedSnapshot = [config.endpoint, config.key, config.model]
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt ?? Date()
            aiSaveOK = true
            aiSaveNotice = "已保存：只写入本机 ai.json，没有发送任何网络请求。"
        } catch {
            // localizedDescription 可能带文件 URL，不向界面回显。
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt
            aiSaveOK = false
            aiSaveNotice = "保存失败：配置没能写入本机文件（可能是存储空间或权限问题）。这是写盘失败，与接口能不能连通无关。"
        }
    }

    /// 「测试」：只发一次连通性请求（输入取本次快照），不写 ai.json、不碰保存状态。
    @MainActor
    private func testAI() async {
        // UI 禁用以外再设入口闸门；不重试，输入也只取本次快照。
        guard !aiTesting, Self.cooldownSeconds(until: aiCooldownUntil, now: Date()) == 0 else { return }
        let (config, problem) = validatedAIInput()
        guard let config = config, let url = URL(string: config.endpoint) else {
            aiTestOK = false
            aiTestStatus = "未测试：" + (problem ?? "接口地址不合法。") + "（不影响已保存的配置）"
            return
        }
        let key = config.key
        let model = config.model

        aiTesting = true
        aiTestOK = false
        aiTestStatus = "正在测试连通性…（不会改动已保存的配置）"
        defer { aiTesting = false }

        let queryValues = (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [])
            .compactMap { $0.value }.filter { !$0.isEmpty }
        let secrets = [key] + queryValues
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 8
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "model": model,
            "max_tokens": 40,
            "messages": [
                ["role": "system", "content": "你是可爱的桌宠，说一句不超过20字的中文撒娇话，不要引号。"],
                ["role": "user", "content": "说一句"],
            ],
        ]
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 8
        configuration.timeoutIntervalForResource = 15
        // 不跟随重定向，避免向另一地址转发 Authorization/查询凭据。
        let session = URLSession(configuration: configuration,
                                 delegate: MiniSightAITestRedirectGuard(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var receivedStatus: Int?
        do {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            let (bytes, response) = try await session.bytes(for: req)
            guard let http = response as? HTTPURLResponse else {
                aiTestOK = false
                aiTestStatus = "测试失败：未收到 HTTP 响应（不影响已保存的配置）。"
                return
            }
            receivedStatus = http.statusCode
            // 先应用响应头，即使错误体过大、无效或读取失败，也要冷却。
            if http.statusCode == 429 {
                let now = Date()
                let delay = MiniSightAITest.retryDelay(http.value(forHTTPHeaderField: "Retry-After"), now: now)
                aiCooldownUntil = now.addingTimeInterval(delay)
            }
            var data = Data()
            var tooLarge = false
            for try await byte in bytes {
                if data.count >= MiniSightAITest.maxBodyBytes { tooLarge = true; break }
                data.append(byte)
            }
            aiTestOK = http.statusCode == 200
            aiTestStatus = aiTestOK
                ? MiniSightAITest.reply(data, tooLarge: tooLarge, secrets: secrets)
                : MiniSightAITest.failure(http.statusCode, data: data, tooLarge: tooLarge, secrets: secrets)
        } catch {
            aiTestOK = false
            if let status = receivedStatus, status != 200 {
                aiTestStatus = MiniSightAITest.failure(status, data: Data(), tooLarge: false, secrets: secrets)
                    + "（错误详情读取未完成）"
            } else if receivedStatus == 200 {
                aiTestStatus = "HTTP 200，但响应读取未完成（非 HTTP 错误；不影响已保存的配置）。"
            } else {
                aiTestStatus = "测试失败：请求未完成，请检查网络或超时情况（不影响已保存的配置）。"
            }
        }
    }

    /// AppStorage 写的是内存里的 defaults，异步落盘；插件收到通知会立刻读
    /// plist，没落盘就读到旧值（表现为要拨两次才生效）。先强写盘再发。
    private func flushAndPost(_ name: String) {
        UserDefaults.standard.synchronize()
        post(name)
    }

    private func post(_ name: String) {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }

    private func importFile(_ url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url), let image = UIImage(data: data) else {
            importError = "这个文件不是可识别的图片。"
            return
        }
        importImage(image)
    }
}

// MARK: - Pickers

private struct MiniSightPhotoPicker: UIViewControllerRepresentable {
    let onPick: (UIImage) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .images
        config.selectionLimit = 1
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPick: (UIImage) -> Void
        init(onPick: @escaping (UIImage) -> Void) { self.onPick = onPick }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            guard let provider = results.first?.itemProvider,
                  provider.canLoadObject(ofClass: UIImage.self) else { return }
            provider.loadObject(ofClass: UIImage.self) { object, _ in
                guard let image = object as? UIImage else { return }
                DispatchQueue.main.async { self.onPick(image) }
            }
        }
    }
}

private struct MiniSightDocumentPicker: UIViewControllerRepresentable {
    let onPick: (URL) -> Void

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.image], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(onPick: @escaping (URL) -> Void) { self.onPick = onPick }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            onPick(url)
        }
    }
}
