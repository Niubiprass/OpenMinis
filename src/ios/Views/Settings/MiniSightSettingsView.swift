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
import Foundation
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import UIKit

// MARK: - MiniSight AI file store (Foundation-only; exercised by standalone tests)

/// One authoritative file. Persona-only writes never capture unsaved connection fields.
/// Corrupt/unreadable files are NOT treated as empty dictionaries and silently replaced.
enum MiniSightAIConfigFile {
    static let maxBytes = 64 * 1024
    enum Failure: Error { case invalidFile, tooLarge, verificationFailed }

    static func normalizedPersona(_ text: String) -> String {
        String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(2000))
    }

    static func read(_ url: URL) throws -> [String: Any] {
        guard FileManager.default.fileExists(atPath: url.path) else { return [:] }
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard ((attributes[.size] as? NSNumber)?.intValue ?? 0) <= maxBytes else {
            throw Failure.tooLarge
        }
        let data = try Data(contentsOf: url)
        guard data.count <= maxBytes else { throw Failure.tooLarge }
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw Failure.invalidFile
        }
        return object
    }

    @discardableResult
    static func writeAndVerify(_ object: [String: Any], to url: URL,
                               onWrite: (() -> Void)? = nil) throws -> [String: Any] {
        let data = try JSONSerialization.data(withJSONObject: object)
        guard data.count <= maxBytes else { throw Failure.tooLarge }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
        onWrite?()
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        let verified = try read(url)
        guard NSDictionary(dictionary: verified).isEqual(NSDictionary(dictionary: object)) else {
            throw Failure.verificationFailed
        }
        return verified
    }

    static func replacingPersona(_ text: String, in object: [String: Any]) -> [String: Any] {
        var updated = object
        let prompt = normalizedPersona(text)
        if prompt.isEmpty { updated.removeValue(forKey: "system_prompt") }
        else { updated["system_prompt"] = prompt }
        return updated
    }

    @discardableResult
    static func savePersona(_ text: String, to url: URL, onWrite: (() -> Void)? = nil) throws -> String {
        let current = try read(url)
        let updated = replacingPersona(text, in: current)
        // Avoid rewriting the same file on every onAppear and invalidating a valid test.
        if !NSDictionary(dictionary: current).isEqual(NSDictionary(dictionary: updated)) ||
            !FileManager.default.fileExists(atPath: url.path) {
            _ = try writeAndVerify(updated, to: url, onWrite: onWrite)
        } else { onWrite?() }
        let verified = try read(url)
        let expected = normalizedPersona(text)
        guard (verified["system_prompt"] as? String ?? "") == expected else {
            throw Failure.verificationFailed
        }
        return expected
    }

    static func saveConnection(url: String, key: String, model: String,
                               persona: String, to file: URL, onWrite: (() -> Void)? = nil) throws {
        var updated = replacingPersona(persona, in: try read(file))
        updated["url"] = url
        updated["key"] = key
        updated["model"] = model
        _ = try writeAndVerify(updated, to: file, onWrite: onWrite)
    }
}

// MARK: - Pet files and AI UI metadata

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
    static func save(_ image: UIImage, onWrite: () -> Void) throws {
        let maxWidth: CGFloat = 768
        let scale = min(1, maxWidth / max(image.size.width, 1))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: size)
        let scaled = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        guard let data = scaled.pngData() else { throw MiniSightAIConfigFile.Failure.invalidFile }
        try data.write(to: url, options: .atomic)
        onWrite()
        let verified = try Data(contentsOf: url)
        guard verified == data, UIImage(data: verified) != nil else {
            throw MiniSightAIConfigFile.Failure.verificationFailed
        }
    }

    static func delete() throws {
        try FileManager.default.removeItem(at: url)
        guard !FileManager.default.fileExists(atPath: url.path) else {
            throw MiniSightAIConfigFile.Failure.verificationFailed
        }
    }

    static var aiConfigURL: URL { directory.appendingPathComponent("ai.json") }
    static var containerPath: String { directory.deletingLastPathComponent().deletingLastPathComponent().path }
    static var shownURL: URL { directory.appendingPathComponent("shown") }

    static func loadShown() -> Bool {
        guard let data = try? Data(contentsOf: shownURL) else { return true }
        return String(data: data, encoding: .utf8) != "0"
    }

    static func saveShown(_ on: Bool, onWrite: () -> Void) throws {
        let expected = Data((on ? "1" : "0").utf8)
        try expected.write(to: shownURL, options: .atomic)
        onWrite()
        guard try Data(contentsOf: shownURL) == expected else {
            throw MiniSightAIConfigFile.Failure.verificationFailed
        }
    }

    static func loadAI() -> (String, String, String, String) {
        guard let obj = try? MiniSightAIConfigFile.read(aiConfigURL) else { return ("", "", "", "") }
        return (obj["url"] as? String ?? "", obj["key"] as? String ?? "",
                obj["model"] as? String ?? "", obj["system_prompt"] as? String ?? "")
    }

    static func saveAI(url: String, key: String, model: String, systemPrompt: String,
                       onWrite: (() -> Void)? = nil) throws {
        try MiniSightAIConfigFile.saveConnection(url: url, key: key, model: model,
                                                persona: systemPrompt, to: aiConfigURL, onWrite: onWrite)
    }

    static func savePersona(_ text: String, onWrite: (() -> Void)? = nil) throws -> String {
        try MiniSightAIConfigFile.savePersona(text, to: aiConfigURL, onWrite: onWrite)
    }

    /// Revision is metadata only, never a key/URL/prompt. Changed settings invalidate old green results.
    static var aiConfigRevision: String {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: aiConfigURL.path),
              let date = attributes[.modificationDate] as? Date else { return "missing" }
        return "\(date.timeIntervalSince1970)|\(attributes[.size] as? NSNumber ?? 0)"
    }

    static var aiTestRecordURL: URL { directory.appendingPathComponent("ai-test-status.json") }

    /// Persist only result metadata, not the response, credentials or persona.
    static func saveTestRecord(ok: Bool, status: String, cooldownUntil: Date?, revision: String) throws {
        var object: [String: Any] = ["ok": ok, "status": status, "revision": revision,
                                     "time": Date().timeIntervalSince1970]
        if let cooldownUntil { object["cooldownUntil"] = cooldownUntil.timeIntervalSince1970 }
        _ = try MiniSightAIConfigFile.writeAndVerify(object, to: aiTestRecordURL)
    }

    static func loadTestRecord() -> (status: String, ok: Bool, cooldown: Date?)? {
        guard let object = try? MiniSightAIConfigFile.read(aiTestRecordURL),
              let status = object["status"] as? String, status.count <= 1000 else { return nil }
        let date = Date(timeIntervalSince1970: object["time"] as? TimeInterval ?? 0)
        let stamp = MiniSightSettingsView.savedAtFormatter.string(from: date)
        let sameRevision = (object["revision"] as? String) == aiConfigRevision
        let text = "\(stamp) · \(status)" + (sameRevision ? "" : " 配置已变，需要重新测试。")
        let until = (object["cooldownUntil"] as? TimeInterval).map(Date.init(timeIntervalSince1970:))
        return (text, sameRevision && (object["ok"] as? Bool ?? false), until)
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

/// Endpoint validation and UI-only redaction; no second network client/parser.
private enum MiniSightAITest {

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
    static func safeText(_ text: String, secrets: [String], limit: Int) -> String {
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

}

struct MiniSightSettingsView: View {
    /// 0 = capsule, 1 = pet.
    @AppStorage("minisight.style") private var style = 0
    @AppStorage("minisight.renderer") private var renderer = 0 // 0: plugin, 1: App
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("minisight.record") private var record = false
    @AppStorage("minisight.longPress") private var longPressToRecord = true
    @AppStorage("minisight.mode") private var mode = 0   // 0 = 仅调用时，1 = 常驻
    @State private var shown = true
    @AppStorage("minisight.petSize") private var petSize = 96.0
    @AppStorage("minisight.gravity") private var gravity = false
    @AppStorage("minisight.diagnostics") private var diagnostics = false
    @AppStorage("minisight.chat.height") private var chatHeight = 160.0
    @AppStorage("minisight.chat.theme") private var chatTheme = 0
    @AppStorage("minisight.chat.tintHex") private var chatTintHex = "8B5CF6"
    @AppStorage("minisight.chat.tintAlpha") private var chatTintAlpha = 0.22
    @State private var aiPersona = ""
    @State private var savedPersona = ""
    @State private var personaLoaded = false
    @State private var personaSaveGeneration = 0
    @State private var personaSaveWork: DispatchWorkItem?
    @State private var personaSaveFailed = false
    @State private var personaSaveStatus = "人设尚未读取。"

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
    @State private var aiTestClient: MiniSightAI?
    @State private var aiTestGeneration = 0
    @State private var aiCooldownUntil: Date?
    @State private var petImage: UIImage?
    @State private var showPhotoPicker = false
    @State private var showFilePicker = false
    @State private var importError: String?
    @State private var settingsError: String?
    @State private var settingsLoaded = false
    @State private var showRuntimeLogs = false
    @State private var aiTestRequest = ""

    var body: some View {
        List {
            Section {
                Picker("样式", selection: $style) {
                    Text("胶囊").tag(0)
                    Text("桌宠").tag(1)
                }
                .pickerStyle(.segmented)
                if style == 1 {
                    Picker("桌宠显示端", selection: $renderer) {
                        Text("越狱插件").tag(0)
                        Text("App 内").tag(1)
                    }
                    .pickerStyle(.segmented)
                }
            } footer: {
                Text("切换后立即生效。越狱插件可跨 App 显示；App 内只在 Minis 中显示。只启用选中的一端，不重复画两只。")
            }

            Section {
                Toggle("显示桌宠", isOn: $shown)
            } footer: {
                Text("双击打开对话；对话菜单里可以隐藏桌宠。隐藏后 MCP 调用也不再出现，可在这里恢复。")
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
                        do {
                            try MiniSightPetFile.delete()
                            MSDiagEvent("assets", "readback", "ok", ["setting": "pet", "source": "delete", "readback": true])
                            petImage = nil
                            style = 0
                            flushAndPost("com.openminis.minisight.settings", setting: "pet")
                        } catch {
                            MSDiagEvent("assets", "readback", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "pet"))
                            importError = "删除失败或删除后核对失败，请刷新后重试。"
                        }
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
                    if aiTesting {
                        Button("取消测试") { cancelAITest() }
                            .buttonStyle(.bordered)
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
                Text("地址、Key、模型点保存后生效；人设独立自动保存。两端聊天和测试都读同一份 Documents/MiniSight/ai.json；测试只验证已保存配置，不替你保存未完成的连接编辑。收到真实回答才判成功。")
            }

            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text("AI 人设 / 系统提示词").font(.subheadline.weight(.medium))
                    TextEditor(text: $aiPersona)
                        .frame(minHeight: 90, maxHeight: 150)
                        .padding(6)
                        .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                    Text("人设独立自动保存，停止输入片刻或离开页面时落盘；最多 2000 字。留空使用默认人设，不会写入诊断日志。")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(personaSaveStatus)
                        .font(.caption)
                        .foregroundStyle(personaSaveFailed ? Color.red : Color.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if personaSaveFailed {
                        Button("重试保存人设") { savePersonaNow() }
                            .font(.footnote)
                    }
                    Button("恢复默认人设") {
                        aiPersona = ""
                        savePersonaNow()
                    }
                    .font(.footnote)
                }
                HStack(spacing: 12) {
                    Text("气泡记录最大高度")
                    Slider(value: $chatHeight, in: 80...200, step: 10)
                    Text("\(Int(chatHeight))")
                        .font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                        .frame(width: 42, alignment: .trailing)
                }
                Picker("磨砂样式", selection: $chatTheme) {
                    Text("柔和磨砂").tag(0)
                    Text("深色磨砂").tag(1)
                    Text("清透玻璃").tag(2)
                }
                .pickerStyle(.segmented)
                ColorPicker("主题色", selection: chatTintBinding, supportsOpacity: false)
                TextField("HEX 微调（6 位）", text: $chatTintHex)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                HStack(spacing: 12) {
                    Text("色彩浓度")
                    Slider(value: $chatTintAlpha, in: 0.05...0.55, step: 0.025)
                    Text("\(Int(chatTintAlpha * 100))%")
                        .font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                        .frame(width: 40, alignment: .trailing)
                }
            } header: {
                Text("聊天外观与人设")
            } footer: {
                Text("这些设置同时供 Minis 内桌宠和越狱桌宠的聊天面板使用；实际磨砂强度受系统材质控制。")
            }

            Section {
                Button("测试显示 3 秒") {
                    MSDiagEvent("settings", "publish", "pending", ["setting": "display_test", "reason": "awaiting_runtime"])
                    post("com.openminis.agent.started")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        MSDiagEvent("settings", "publish", "pending", ["setting": "display_test", "reason": "stop_requested"])
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

            Section {
                Toggle("记录详细诊断", isOn: $diagnostics)
                Button { showRuntimeLogs = true } label: {
                    Label("查看运行日志", systemImage: "doc.text.magnifyingglass")
                }
                if let settingsError {
                    Text(settingsError).font(.caption).foregroundStyle(Color.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("重试保存设置") {
                        persistShown(shown)
                    }
                }
            } header: {
                Text("诊断")
            } footer: {
                Text("基础状态事件始终在本机记录；开关只控制详细诊断。Documents/MiniSight/ 下 App 与插件各写 diagnostic-app.log / diagnostic-plugin.log，每文件上限 200KB，另保留一份 .1 轮转，旧记录会被覆盖。只记录脱敏状态、错误码和计数，不记 Key、地址、提示词或正文，不自动上传。")
            }
        }
        .navigationTitle("操作指示器")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            settingsLoaded = false
            MSDiagConfigure(diagnostics, MiniSightPetFile.containerPath)
            petImage = MiniSightPetFile.load()
            shown = MiniSightPetFile.loadShown()
            // Migrate the old half-screen card height to the compact bubbles' range.
            if !chatHeight.isFinite || chatHeight < 80 || chatHeight > 200 {
                chatHeight = chatHeight.isFinite ? min(200, max(80, chatHeight)) : 160
            }
            loadAISettings()
            settingsLoaded = true
            for item in settingsSnapshot {
                settingEvent(item.key, stage: "load", result: "pending", reason: "settings_page")
            }
            settingEvent("shown", stage: "load", result: "pending", reason: "settings_page")
        }
        .onDisappear {
            savePersonaNow()
            cancelAITest()
        }
        .onChange(of: scenePhase) { phase in
            if phase != .active { savePersonaNow() }
            if phase == .background { cancelAITest() }
        }
        .onChange(of: aiPersona) { value in schedulePersonaSave(value) }
        .onChange(of: renderer) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.renderer") }
        .onChange(of: style) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.style") }
        .onChange(of: mode) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.mode") }
        .onChange(of: shown) { value in if settingsLoaded && MiniSightPetFile.loadShown() != value { persistShown(value) } }
        .onChange(of: petSize) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.petSize") }
        .onChange(of: gravity) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.gravity") }
        .onChange(of: diagnostics) { _ in
            MSDiagConfigure(diagnostics, MiniSightPetFile.containerPath)
            flushAndPost("com.openminis.minisight.settings", setting: "minisight.diagnostics")
        }
        .onChange(of: record) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.record") }
        .onChange(of: longPressToRecord) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.longPress") }
        .onChange(of: chatHeight) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.chat.height") }
        .onChange(of: chatTheme) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.chat.theme") }
        .onChange(of: chatTintHex) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.chat.tintHex") }
        .onChange(of: chatTintAlpha) { _ in flushAndPost("com.openminis.minisight.settings", setting: "minisight.chat.tintAlpha") }
        .sheet(isPresented: $showRuntimeLogs) { MiniSightRuntimeLogView() }
        .sheet(isPresented: $showPhotoPicker) {
            MiniSightPhotoPicker(onPick: { image in importImage(image, source: "photos") }, onFailure: {
                MSDiagEvent("assets", "receive", "failed", ["setting": "pet", "source": "photos", "reason": "decode_failed"])
                importError = "照片无法读取，请换一张图片重试。"
            })
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

    private func importImage(_ image: UIImage, source: String) {
        MSDiagEvent("assets", "receive", "pending", ["setting": "pet", "source": source])
        var didWrite = false
        do {
            try MiniSightPetFile.save(image, onWrite: {
                didWrite = true
                MSDiagEvent("assets", "save", "ok", ["setting": "pet", "source": source, "saved": true])
            })
            petImage = MiniSightPetFile.load()
            guard petImage != nil else { throw MiniSightAIConfigFile.Failure.verificationFailed }
            MSDiagEvent("assets", "readback", "ok", ["setting": "pet", "source": source, "readback": true])
            style = 1
            flushAndPost("com.openminis.minisight.settings", setting: "pet")
        } catch {
            MSDiagEvent("assets", didWrite ? "readback" : "save", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "pet"))
            importError = "素材写入或读回核对失败，请重试。"
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
    fileprivate static let savedAtFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM-dd HH:mm:ss"
        return formatter
    }()

    private var chatTintBinding: Binding<Color> {
        Binding(get: {
            let hex = chatTintHex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
            let value = UInt64(hex, radix: 16) ?? 0x8B5CF6
            return Color(.sRGB, red: Double((value >> 16) & 0xff) / 255,
                         green: Double((value >> 8) & 0xff) / 255,
                         blue: Double(value & 0xff) / 255, opacity: 1)
        }, set: { color in
            let ui = UIColor(color)
            var red: CGFloat = 0, green: CGFloat = 0, blue: CGFloat = 0, alpha: CGFloat = 1
            guard ui.getRed(&red, green: &green, blue: &blue, alpha: &alpha) else { return }
            chatTintHex = String(format: "%02X%02X%02X", Int((red * 255).rounded()),
                                 Int((green * 255).rounded()), Int((blue * 255).rounded()))
        })
    }

    private func loadAISettings() {
        personaLoaded = false
        do {
            let object = try MiniSightAIConfigFile.read(MiniSightPetFile.aiConfigURL)
            let legacy = UserDefaults.standard.string(forKey: "minisight.ai.persona") ?? ""
            // Recover an old defaults-only persona once, without overwriting a file persona.
            if object["system_prompt"] == nil && !MiniSightAIConfigFile.normalizedPersona(legacy).isEmpty {
                _ = try MiniSightPetFile.savePersona(legacy)
                UserDefaults.standard.removeObject(forKey: "minisight.ai.persona")
            }
            let verified = try MiniSightAIConfigFile.read(MiniSightPetFile.aiConfigURL)
            let ai = (verified["url"] as? String ?? "", verified["key"] as? String ?? "",
                      verified["model"] as? String ?? "", verified["system_prompt"] as? String ?? "")
            aiURL = ai.0; aiKey = ai.1; aiModel = ai.2; aiPersona = ai.3
            savedPersona = MiniSightAIConfigFile.normalizedPersona(ai.3)
            aiSavedSnapshot = [Self.endpoint(for: ai.0) ?? ai.0.trimmingCharacters(in: .whitespacesAndNewlines),
                               ai.1.trimmingCharacters(in: .whitespacesAndNewlines),
                               ai.2.trimmingCharacters(in: .whitespacesAndNewlines)]
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt
            personaSaveFailed = false
            personaSaveStatus = savedPersona.isEmpty ? "默认人设；修改后会自动保存。" : "人设已从本机文件读取。"
            MSDiagEvent("settings", "load", "ok", ["setting": "ai_persona", "readback": true, "chars": savedPersona.count])
            MSDiagEvent("settings", "load", "ok", ["setting": "ai_connection", "readback": true])
        } catch {
            // Keep corrupt/unreadable ai.json intact. Never dump its contents or error URL.
            personaSaveFailed = true
            personaSaveStatus = "人设读取失败：原配置文件已保留。修改后可重试保存。"
            aiSavedSnapshot = []
            aiSavedAt = nil
            MSDiagEvent("settings", "load", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_persona"))
            MSDiagEvent("settings", "load", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_connection"))
            aiSaveOK = false
            aiSaveNotice = "读取失败：原配置文件已保留，没有覆盖。"
        }
        personaLoaded = true
        restoreLastTestStatus()
    }

    private func schedulePersonaSave(_ value: String) {
        guard personaLoaded else { return }
        if value.count > 2000 {
            aiPersona = String(value.prefix(2000))
            return
        }
        personaSaveWork?.cancel()
        personaSaveGeneration += 1
        let generation = personaSaveGeneration
        guard MiniSightAIConfigFile.normalizedPersona(value) != savedPersona || personaSaveFailed else { return }
        personaSaveStatus = "等待自动保存…"
        let work = DispatchWorkItem {
            guard generation == personaSaveGeneration, personaLoaded else { return }
            savePersonaNow()
        }
        personaSaveWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45, execute: work)
    }

    /// Runs on the UI queue on debounce, explicit retry, navigation or backgrounding.
    /// Only system_prompt is merged; URL/Key/model drafts never enter this write.
    private func savePersonaNow() {
        personaSaveWork?.cancel()
        personaSaveWork = nil
        personaSaveGeneration += 1
        guard personaLoaded else { return }
        let prompt = MiniSightAIConfigFile.normalizedPersona(aiPersona)
        guard prompt != savedPersona || personaSaveFailed else { return }
        var didWrite = false
        MSDiagEvent("settings", "save", "pending", ["setting": "ai_persona", "generation": personaSaveGeneration])
        do {
            savedPersona = try MiniSightPetFile.savePersona(prompt, onWrite: {
                didWrite = true
                MSDiagEvent("settings", "save", "ok", ["setting": "ai_persona", "saved": true])
            })
            MSDiagEvent("settings", "readback", "ok", ["setting": "ai_persona", "readback": true, "chars": savedPersona.count])
            UserDefaults.standard.removeObject(forKey: "minisight.ai.persona")
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt
            personaSaveFailed = false
            personaSaveStatus = "人设已保存并核对 · " + Self.savedAtFormatter.string(from: aiSavedAt ?? Date())
            flushAndPost("com.openminis.minisight.settings", setting: "ai_persona")
            if !aiTesting { restoreLastTestStatus() }
        } catch {
            personaSaveFailed = true
            personaSaveStatus = "人设保存失败，输入还在这里。请重试；没有改动接口、Key 或模型。"
            MSDiagEvent("settings", didWrite ? "readback" : "save", "failed",
                        MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_persona"))
        }
    }

    private func restoreLastTestStatus() {
        guard !aiTesting else { return }
        if let record = MiniSightPetFile.loadTestRecord() {
            aiTestStatus = record.status
            aiTestOK = record.ok
            aiCooldownUntil = record.cooldown
        } else {
            aiTestStatus = nil
            aiTestOK = false
        }
    }

    private var saveStateText: String {
        guard aiSavedSnapshot.count == 3, aiSavedSnapshot.allSatisfy({ !$0.isEmpty }),
              let aiSavedAt = aiSavedAt else { return "接口、Key 和模型还没有完整保存。" }
        let stamp = "已保存 · " + Self.savedAtFormatter.string(from: aiSavedAt)
        return aiDirty ? stamp + "，接口/Key/模型有未保存改动；测试只用已保存配置。" : stamp
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
        cancelAITest()
        savePersonaNow()
        let (config, problem) = validatedAIInput()
        guard let config = config else {
            aiSaveOK = false
            aiSaveNotice = "未保存：" + (problem ?? "输入不完整。") + "（这一步只看输入，不联网）"
            MSDiagEvent("settings", "save", "skipped", ["setting": "ai_connection", "reason": "invalid_input"])
            return
        }
        var didWrite = false
        MSDiagEvent("settings", "save", "pending", ["setting": "ai_connection"])
        do {
            try MiniSightPetFile.saveAI(url: config.endpoint, key: config.key, model: config.model, systemPrompt: aiPersona, onWrite: {
                didWrite = true
                MSDiagEvent("settings", "save", "ok", ["setting": "ai_connection", "saved": true])
            })
            MSDiagEvent("settings", "readback", "ok", ["setting": "ai_connection", "readback": true])
            aiSavedSnapshot = [config.endpoint, config.key, config.model]
            aiSavedAt = MiniSightPetFile.aiConfigSavedAt ?? Date()
            savedPersona = MiniSightAIConfigFile.normalizedPersona(aiPersona)
            personaSaveFailed = false
            personaSaveStatus = "人设已保存并核对 · " + Self.savedAtFormatter.string(from: aiSavedAt ?? Date())
            aiSaveOK = true
            aiSaveNotice = "已保存并核对：只写本机文件，没有发送网络请求。"
            flushAndPost("com.openminis.minisight.settings", setting: "ai_connection")
            restoreLastTestStatus()
        } catch {
            // NSError descriptions can contain paths; expose only a fixed message and code/domain metadata.
            MSDiagEvent("settings", didWrite ? "readback" : "save", "failed",
                        MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_connection"))
            aiSavedAt = nil
            aiSavedSnapshot = []
            aiSaveOK = false
            aiSaveNotice = "保存失败：配置没能写入本机文件（可能是存储空间或权限问题）。这是写盘失败，与接口能不能连通无关。"
        }
    }

    /// The test reads the same saved file and uses the same MiniSightAI client as chat.
    /// It never implicitly saves connection drafts and never treats HTTP alone as success.
    @MainActor
    private func testAI() async {
        let request = UUID().uuidString
        MSDiagEvent("ai_test", "click", "pending", ["request": request, "source": "settings"])
        guard !aiTesting else {
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "busy"])
            return
        }
        guard Self.cooldownSeconds(until: aiCooldownUntil, now: Date()) == 0 else {
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "cooldown"])
            return
        }
        savePersonaNow()
        guard !personaSaveFailed else {
            aiTestOK = false
            aiTestStatus = "未测试：人设尚未成功保存，请先重试保存人设。"
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "persona_unsaved"])
            MSDiagEvent("ai_test", "display", "failed", ["request": request, "reason": "persona_unsaved"])
            return
        }
        guard !aiDirty else {
            aiTestOK = false
            aiTestStatus = "未测试：接口、Key 或模型有未保存改动，请先点上方保存。"
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "connection_unsaved"])
            MSDiagEvent("ai_test", "display", "failed", ["request": request, "reason": "connection_unsaved"])
            return
        }
        let (config, problem) = validatedAIInput()
        guard let config = config, let url = URL(string: config.endpoint) else {
            aiTestOK = false
            aiTestStatus = "未测试：" + (problem ?? "接口地址不合法。")
            MSDiagEvent("ai_test", "skip", "skipped", ["request": request, "reason": "invalid_input"])
            MSDiagEvent("ai_test", "display", "failed", ["request": request, "reason": "invalid_input"])
            return
        }
        aiTestGeneration += 1
        let generation = aiTestGeneration
        let revision = MiniSightPetFile.aiConfigRevision
        let key = config.key
        let startedAt = Date()
        aiTestRequest = request
        aiTesting = true
        aiTestOK = false
        aiTestStatus = "正在用已保存配置请求真实回答…（与聊天共用接入；可取消）"
        MSDiagConfigure(diagnostics, MiniSightPetFile.containerPath)
        MSDiagEvent("ai_test", "start", "pending", ["request": request, "generation": generation, "source": "settings"])
        let client = MiniSightAI(container: MiniSightPetFile.containerPath)
        aiTestClient = client
        defer {
            if generation == aiTestGeneration {
                aiTesting = false
                aiTestClient = nil
            }
        }

        let queryValues = (URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? [])
            .compactMap { $0.value }.filter { !$0.isEmpty }
        let secrets = [key] + queryValues
        let reply: MiniSightAIReply = await withCheckedContinuation { continuation in
            client.send("你好，请只回答一句简短的中文。", completion: { reply in
                continuation.resume(returning: reply)
            })
        }
        MSDiagEvent("ai_test", "response", reply.isSuccess ? "ok" : "failed",
                    ["request": request, "generation": generation, "code": reply.status,
                     "chars": reply.text.count, "duration_ms": Int(Date().timeIntervalSince(startedAt) * 1000)])
        guard generation == aiTestGeneration else {
            MSDiagEvent("ai_test", "display", "skipped", ["request": request, "reason": "stale_generation"])
            return
        }
        if reply.status == 429 {
            aiCooldownUntil = Date().addingTimeInterval(min(300, max(1, reply.retryAfterSeconds)))
        }
        let sameRevision = revision == MiniSightPetFile.aiConfigRevision
        aiTestOK = reply.isSuccess && sameRevision
        let summary: String
        if reply.isSuccess {
            summary = "收到真实回答（\(reply.text.count) 字；回答正文未保存）。"
            let preview = MiniSightAITest.safeText(reply.text, secrets: secrets, limit: 240)
            aiTestStatus = sameRevision ? "测试成功：" + preview
                : "请求收到回答，但测试过程中配置已变，请重新测试。"
        } else {
            summary = "请求失败（状态码 \(reply.status)；未保存响应正文）。"
            aiTestStatus = "测试失败：请查看运行日志中的状态码及请求阶段。"
        }
        MSDiagEvent("ai_test", "display", aiTestOK ? "ok" : "failed",
                    ["request": request, "generation": generation, "visible": true,
                     "reason": sameRevision ? "response_received" : "config_changed"])
        do {
            try MiniSightPetFile.saveTestRecord(ok: aiTestOK, status: summary,
                                               cooldownUntil: aiCooldownUntil, revision: revision)
            MSDiagEvent("ai_test", "readback", "ok", ["request": request, "setting": "ai_test_status", "readback": true])
        } catch {
            var fields = MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_test_status")
            fields["request"] = request
            MSDiagEvent("ai_test", "save", "failed", fields)
            aiTestStatus = (aiTestStatus ?? "") + "（结果未能保存，离开页面后可能丢失。）"
        }
    }

    private func cancelAITest() {
        guard aiTesting else { return }
        MSDiagEvent("ai_test", "cancel", "pending", ["request": aiTestRequest, "generation": aiTestGeneration])
        aiTestGeneration += 1
        aiTesting = false
        let client = aiTestClient
        aiTestClient = nil
        client?.cancel()
        aiTestOK = false
        aiTestStatus = "测试已取消；未修改连接配置。"
        MSDiagEvent("ai_test", "display", "cancelled", ["request": aiTestRequest, "visible": true])
        do {
            try MiniSightPetFile.saveTestRecord(ok: false, status: "测试已取消。",
                                               cooldownUntil: aiCooldownUntil,
                                               revision: MiniSightPetFile.aiConfigRevision)
            MSDiagEvent("ai_test", "readback", "ok", ["request": aiTestRequest, "setting": "ai_test_status", "readback": true])
        } catch {
            MSDiagEvent("ai_test", "save", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "ai_test_status"))
            aiTestStatus = "测试已取消；结果保存失败。"
        }
    }

    /// AppStorage's cached read is insufficient: compare every value with the on-disk
    /// application domain after synchronization. A Darwin post is not an apply ACK.
    private var settingsSnapshot: [(key: String, value: Any)] {
        [("minisight.style", style), ("minisight.renderer", renderer),
         ("minisight.record", record), ("minisight.longPress", longPressToRecord),
         ("minisight.mode", mode), ("minisight.petSize", petSize),
         ("minisight.gravity", gravity), ("minisight.diagnostics", diagnostics),
         ("minisight.chat.height", chatHeight), ("minisight.chat.theme", chatTheme),
         ("minisight.chat.tintHex", chatTintHex), ("minisight.chat.tintAlpha", chatTintAlpha)]
    }

    private func settingEvent(_ key: String, stage: String, result: String,
                              revision: String? = nil, reason: String? = nil) {
        var fields: [String: Any] = ["setting": key, "source": "settings"]
        if let revision { fields["revision"] = revision }
        if let reason { fields["reason"] = reason }
        switch key {
        case "minisight.record": fields["enabled"] = record
        case "minisight.longPress": fields["enabled"] = longPressToRecord
        case "minisight.gravity": fields["enabled"] = gravity
        case "minisight.diagnostics": fields["enabled"] = diagnostics
        case "shown": fields["enabled"] = shown
        case "minisight.mode": fields["mode"] = mode
        case "minisight.style": fields["style"] = style
        case "minisight.renderer": fields["renderer"] = renderer
        case "minisight.petSize": fields["value"] = petSize
        case "minisight.chat.height": fields["value"] = chatHeight
        case "minisight.chat.theme": fields["value"] = chatTheme
        case "minisight.chat.tintAlpha": fields["value"] = chatTintAlpha
        case "minisight.chat.tintHex":
            if chatTintHex.count == 6, let rgb = UInt32(chatTintHex, radix: 16) { fields["value"] = rgb }
        default: break // Never log persona or connection strings.
        }
        MSDiagEvent(key == "minisight.record" || key == "minisight.longPress" ? "recording" : "settings",
                    stage, result, fields)
    }

    private func persistShown(_ value: Bool) {
        var didWrite = false
        do {
            try MiniSightPetFile.saveShown(value, onWrite: {
                didWrite = true
                settingEvent("shown", stage: "save", result: "ok")
            })
            settingEvent("shown", stage: "readback", result: "ok")
            flushAndPost(value ? "com.openminis.minisight.show" : "com.openminis.minisight.settings", setting: "shown")
        } catch {
            MSDiagEvent("settings", didWrite ? "readback" : "save", "failed",
                        MiniSightSettingsDiagnostics.errorFields(error, setting: "shown"))
            settingsError = "显示状态写入或读回失败；未通知运行端，请重试保存。"
        }
    }

    private func flushAndPost(_ name: String, setting: String = "ai_connection") {
        guard settingsLoaded else { return }
        MSDiagConfigure(diagnostics, MiniSightPetFile.containerPath)
        let revision = UUID().uuidString
        let snapshot = settingsSnapshot
        let defaults = UserDefaults.standard
        for item in snapshot { defaults.set(item.value, forKey: item.key) }
        defaults.set(revision, forKey: "minisight.settings.revision")
        for item in snapshot { settingEvent(item.key, stage: "save", result: "pending", revision: revision) }
        _ = defaults.synchronize() // Its Bool is not evidence of a successful write.
        do {
            let persisted = try MiniSightSettingsDiagnostics.readDefaultsDomain()
            var mismatches = 0
            for item in snapshot {
                let matches = (persisted[item.key] as? NSObject)?.isEqual(item.value) == true
                if !matches { mismatches += 1 }
                settingEvent(item.key, stage: "readback", result: matches ? "ok" : "failed", revision: revision)
                settingEvent(item.key, stage: "save", result: matches ? "ok" : "failed", revision: revision)
            }
            let revisionMatches = persisted["minisight.settings.revision"] as? String == revision
            MSDiagEvent("settings", "readback", revisionMatches ? "ok" : "failed",
                        ["setting": "minisight.settings.revision", "revision": revision, "readback": revisionMatches])
            let shownMatches: Bool
            if FileManager.default.fileExists(atPath: MiniSightPetFile.shownURL.path) {
                shownMatches = (try Data(contentsOf: MiniSightPetFile.shownURL)) == Data((shown ? "1" : "0").utf8)
            } else { shownMatches = shown } // Missing file is the runtime's default-on state.
            settingEvent("shown", stage: "readback", result: shownMatches ? "ok" : "failed", revision: revision)
            if !shownMatches { mismatches += 1 }
            guard mismatches == 0, revisionMatches else {
                settingsError = "设置磁盘读回不一致；未通知运行端。请点重试保存，日志可定位具体设置。"
                MSDiagEvent("settings", "publish", "skipped", ["setting": setting, "revision": revision, "reason": "readback_mismatch", "count": mismatches])
                return
            }
            settingsError = nil
            post(name)
            settingEvent(setting, stage: "publish", result: "pending", revision: revision, reason: "awaiting_runtime")
            for item in snapshot {
                settingEvent(item.key, stage: "publish", result: "pending", revision: revision, reason: "awaiting_runtime")
            }
        } catch {
            var fields = MiniSightSettingsDiagnostics.errorFields(error, setting: setting)
            fields["revision"] = revision
            MSDiagEvent("settings", "readback", "failed", fields)
            MSDiagEvent("settings", "publish", "skipped", ["setting": setting, "revision": revision, "reason": "readback_failed"])
            settingsError = "设置落盘核对失败；未通知运行端，请重试保存。"
        }
    }

    private func post(_ name: String) {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }

    private func importFile(_ url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            guard let image = UIImage(data: data) else { throw MiniSightAIConfigFile.Failure.invalidFile }
            importImage(image, source: "files")
        } catch {
            MSDiagEvent("assets", "receive", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "pet"))
            importError = "这个文件无法读取或不是可识别的图片。"
        }
    }
}

// MARK: - Safe local diagnostics (no network or automatic upload)

private enum MiniSightSettingsDiagnostics {
    static let tailBytes = 60 * 1024
    static let safeDomains: Set<String> = ["NSCocoaErrorDomain", "NSPOSIXErrorDomain", "NSURLErrorDomain",
                                          "MiniSightAIConfigFile", "MiniSightSettings"]
    static func errorFields(_ error: Error, setting: String) -> [String: Any] {
        let ns = error as NSError
        return ["setting": setting, "code": ns.code,
                "domain": safeDomains.contains(ns.domain) ? ns.domain : "MiniSightSettings"]
    }

    static func readDefaultsDomain() throws -> [String: Any] {
        guard let identifier = Bundle.main.bundleIdentifier else { throw MiniSightAIConfigFile.Failure.invalidFile }
        let file = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Preferences")
            .appendingPathComponent(identifier + ".plist")
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: 4 * 1024 * 1024 + 1) ?? Data()
        guard data.count <= 4 * 1024 * 1024,
              let object = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any] else {
            throw MiniSightAIConfigFile.Failure.invalidFile
        }
        return object
    }

    /// Bounded at the handle, not after Data(contentsOf:) has loaded the whole log.
    static func tail(_ file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        let end = try handle.seekToEnd()
        let offset = end > UInt64(tailBytes) ? end - UInt64(tailBytes) : 0
        try handle.seek(toOffset: offset)
        var data = try handle.read(upToCount: tailBytes) ?? Data()
        if offset > 0 { // Never render a partial event from the head of the tail.
            if let newline = data.firstIndex(of: 10) { data = Data(data.suffix(from: data.index(after: newline))) }
            else { data = Data() }
        }
        return String(decoding: data, as: UTF8.self)
    }

    static let features: Set<String> = ["activity", "ai", "ai_test", "approval", "assets", "bubble", "chat", "drag", "gesture", "gravity", "ownership", "recording", "runtime", "screen", "settings", "voice"]
    static let stages: Set<String> = ["apply", "begin", "build", "callback", "cancel", "change", "click", "close", "composer", "config", "configure", "deliver", "display", "editor", "end", "entry", "error", "finish", "hide", "identity", "interruption", "keyboard", "layout", "load", "network", "parse", "publish", "readback", "ready", "receive", "reload", "reply", "request", "response", "rotate", "sample", "save", "send", "show", "skip", "start", "state", "stop", "visibility"]
    static let allowed: Set<String> = ["active", "below", "bytes", "chars", "code", "count", "domain", "duration_ms", "enabled", "executing", "field", "finish", "generation", "h", "http", "issue", "keyboard", "mode", "present", "readback", "reason", "reasoning", "renderer", "request", "revision", "roll", "samples", "saved", "sending", "sequence", "setting", "source", "style", "valid", "value", "version", "visible", "w", "x", "y"]

    static func asciiToken(_ value: String, limit: Int = 80) -> Bool {
        guard !value.isEmpty, value.utf8.count <= limit, value.utf8.allSatisfy({
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 95 || $0 == 45 || $0 == 46
        }) else { return false }
        let lower = value.lowercased()
        return !lower.hasPrefix("sk-") && !lower.hasPrefix("sk_") && !lower.hasPrefix("bearer") &&
            !lower.contains("apikey") && !lower.contains("api_key") && !lower.contains("token")
    }

    static func requestID(_ text: String) -> String? {
        let parts = text.replacingOccurrences(of: "/", with: ".").split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 1 || parts.count == 2, let first = parts.first,
              let uuid = UUID(uuidString: String(first)) else { return nil }
        guard parts.count == 2 else { return uuid.uuidString }
        guard (1...15).contains(parts[1].utf8.count), parts[1].utf8.allSatisfy({ (48...57).contains($0) }) else { return nil }
        return uuid.uuidString + "." + parts[1]
    }

    static func safeValue(_ value: Any, field: String) -> Any? {
        if let number = value as? NSNumber {
            return number.doubleValue.isFinite && abs(number.doubleValue) <= 9_007_199_254_740_991 ? number : nil
        }
        guard let text = value as? String else { return nil }
        if field == "request" { return requestID(text) }
        if field == "revision" { return UUID(uuidString: text) == nil ? nil : text }
        if field == "domain" { return safeDomains.contains(text) ? text : nil }
        let strings: Set<String> = ["setting", "source", "reason", "renderer", "mode", "style", "field", "code", "issue", "finish", "version"]
        return strings.contains(field) && asciiToken(text) ? text : nil
    }

    /// Real writer contract: UTC time pid=… process=… runId=… seq=… event=<JSON>.
    /// Only rebuild validated metadata; no raw line or free-form legacy text survives.
    static func eventObject(_ line: String) -> [String: Any]? {
        guard line.utf8.count <= 8192, let marker = line.range(of: " event="),
              let data = String(line[marker.upperBound...]).data(using: .utf8),
              var object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              (object["v"] as? Int) == 1 else { return nil }
        let prefix = line[..<marker.lowerBound].split(whereSeparator: { $0.isWhitespace })
        guard prefix.count == 5, prefix[0].utf8.count <= 40 else { return nil }
        let stamp = String(prefix[0])
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard formatter.date(from: stamp) != nil else { return nil }
        var metadata: [String: String] = [:]
        for token in prefix.dropFirst() {
            let pair = token.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { return nil }
            metadata[String(pair[0])] = String(pair[1])
        }
        guard let pidText = metadata["pid"], let pid = Int(pidText), pid > 0,
              let process = metadata["process"], asciiToken(process),
              let run = metadata["runId"], UUID(uuidString: run) != nil,
              let seqText = metadata["seq"], let seq = UInt64(seqText), seq > 0, seq <= 9_007_199_254_740_991 else { return nil }
        object["time"] = stamp; object["pid"] = pid; object["process"] = process
        object["runId"] = run; object["seq"] = seq
        return object
    }

    static func sanitizedEvent(_ line: String) -> String? {
        guard let object = eventObject(line),
              let feature = object["feature"] as? String, features.contains(feature),
              let stage = object["stage"] as? String, stages.contains(stage),
              let result = object["result"] as? String,
              ["ok", "failed", "skipped", "cancelled", "pending", "unsupported"].contains(result) else { return nil }
        var clean: [String: Any] = ["feature": feature, "stage": stage, "result": result]
        var fields: [String: Any] = [:]
        let input = object["fields"] as? [String: Any] ?? [:]
        for (key, value) in input where allowed.contains(key) {
            if let safe = safeValue(value, field: key) { fields[key] = safe }
        }
        clean["fields"] = fields
        for key in ["time", "pid", "process", "runId", "seq"] { clean[key] = object[key] }
        guard let output = try? JSONSerialization.data(withJSONObject: clean, options: [.sortedKeys]),
              let text = String(data: output, encoding: .utf8) else { return nil }
        return text
    }

    static let logFiles = ["diagnostic-app.log", "diagnostic-app.log.1", "diagnostic-plugin.log",
                           "diagnostic-plugin.log.1", "diagnostic.log", "diagnostic.log.1"]
    static func logText(_ selection: Int) throws -> String {
        let index = min(max(0, selection), logFiles.count - 1)
        let filename = logFiles[index]
        let file = MiniSightPetFile.directory.appendingPathComponent(filename)
        let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
        let modified = (attrs[.modificationDate] as? Date).map { MiniSightSettingsView.savedAtFormatter.string(from: $0) } ?? "未知"
        let header = "来源：Documents/MiniSight/\(filename)\n文件修改：\(modified) · 刷新：\(MiniSightSettingsView.savedAtFormatter.string(from: Date()))\n"
        guard !filename.hasPrefix("diagnostic.log") else {
            return header + "\n旧日志可能含未脱敏正文，本页不显示 raw 内容。请使用本地脚本生成脱敏摘要。"
        }
        let lines = try tail(file).split(separator: "\n").compactMap { sanitizedEvent(String($0)) }
        return header + "\n" + (lines.isEmpty ? "最后 60KB 内没有可显示的基础事件；无法解析的旧文本已隐藏。" : lines.joined(separator: "\n"))
    }
}

private struct MiniSightRuntimeLogView: View {
    @Environment(\.presentationMode) private var presentationMode
    @State private var source = 0 // Current process's latest log, never the legacy log.
    @State private var text = ""
    @State private var failure: String?
    @State private var copied = false
    @State private var refreshGeneration = 0

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 12) {
                Picker("日志来源", selection: $source) {
                    Text("App · 最新（本进程）").tag(0)
                    Text("App · 上一份").tag(1)
                    Text("插件 · 最新").tag(2)
                    Text("插件 · 上一份").tag(3)
                    Text("旧诊断 · 最新（摘要提示）").tag(4)
                    Text("旧诊断 · 上一份（摘要提示）").tag(5)
                }
                .pickerStyle(.menu)
                Text("只显示最后约 60KB 中的脱敏基础事件；基础日志始终开启，轮转后旧记录会被覆盖。复制仅进入本机剪贴板，不自动上传。")
                    .font(.caption).foregroundStyle(.secondary)
                if let failure { Text(failure).font(.caption).foregroundStyle(Color.red) }
                ScrollView {
                    Text(text.isEmpty ? "暂无日志。" : text)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack {
                    Button("刷新") { refresh() }.buttonStyle(.bordered)
                    Button(copied ? "已复制脱敏文本" : "复制脱敏文本") {
                        UIPasteboard.general.string = text
                        copied = true
                    }.buttonStyle(.bordered).disabled(text.isEmpty || failure != nil)
                }
            }
            .padding()
            .navigationTitle("运行日志")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Button("完成") { presentationMode.wrappedValue.dismiss() } } }
            .onAppear { refresh() }
            .onChange(of: source) { _ in refresh() }
        }
        .navigationViewStyle(.stack)
    }

    private func refresh() {
        copied = false
        refreshGeneration += 1
        let generation = refreshGeneration
        let selection = source
        DispatchQueue.global(qos: .utility).async {
            let result = Result { try MiniSightSettingsDiagnostics.logText(selection) }
            DispatchQueue.main.async {
                guard generation == refreshGeneration, selection == source else { return }
                switch result {
                case .success(let value): text = value; failure = nil
                case .failure(let error):
                    text = ""
                    failure = "日志暂不可读或尚未生成，请稍后刷新。来源：Documents/MiniSight/" + MiniSightSettingsDiagnostics.logFiles[selection]
                    MSDiagEvent("settings", "load", "failed", MiniSightSettingsDiagnostics.errorFields(error, setting: "runtime_logs"))
                }
            }
        }
    }

}

// MARK: - Pickers

private struct MiniSightPhotoPicker: UIViewControllerRepresentable {
    let onPick: (UIImage) -> Void
    let onFailure: () -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .images
        config.selectionLimit = 1
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick, onFailure: onFailure) }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPick: (UIImage) -> Void
        let onFailure: () -> Void
        init(onPick: @escaping (UIImage) -> Void, onFailure: @escaping () -> Void) {
            self.onPick = onPick; self.onFailure = onFailure
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            guard let provider = results.first?.itemProvider else {
                MSDiagEvent("assets", "receive", "cancelled", ["setting": "pet", "source": "photos"])
                return
            }
            guard provider.canLoadObject(ofClass: UIImage.self) else { onFailure(); return }
            provider.loadObject(ofClass: UIImage.self) { object, _ in
                DispatchQueue.main.async {
                    guard let image = object as? UIImage else { self.onFailure(); return }
                    self.onPick(image)
                }
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
