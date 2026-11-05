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

enum MiniSightPetFile {
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
        let stamp = MiniSightSettingsDiagnostics.savedAtFormatter.string(from: date)
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
enum MiniSightAITest {

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
    @StateObject private var config = MiniSightConfigStore.shared

    var body: some View {
        MiniSightHomeView().environmentObject(config)
    }
}

// MARK: - Safe local diagnostics (no network or automatic upload)

enum MiniSightSettingsDiagnostics {
    static let savedAtFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "MM-dd HH:mm:ss"
        return f
    }()

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
        let modified = (attrs[.modificationDate] as? Date).map { MiniSightSettingsDiagnostics.savedAtFormatter.string(from: $0) } ?? "未知"
        let header = "来源：Documents/MiniSight/\(filename)\n文件修改：\(modified) · 刷新：\(MiniSightSettingsDiagnostics.savedAtFormatter.string(from: Date()))\n"
        guard !filename.hasPrefix("diagnostic.log") else {
            return header + "\n旧日志可能含未脱敏正文，本页不显示 raw 内容。请使用本地脚本生成脱敏摘要。"
        }
        let lines = try tail(file).split(separator: "\n").compactMap { sanitizedEvent(String($0)) }
        return header + "\n" + (lines.isEmpty ? "最后 60KB 内没有可显示的基础事件；无法解析的旧文本已隐藏。" : lines.joined(separator: "\n"))
    }
}

struct MiniSightRuntimeLogView: View {
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

struct MiniSightPhotoPicker: UIViewControllerRepresentable {
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

struct MiniSightDocumentPicker: UIViewControllerRepresentable {
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
