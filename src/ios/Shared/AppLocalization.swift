//
//  AppLocalization.swift
//  MinisApp
//
//  [T-ios-inapp-language-string-localized] Makes the in-app language picker
//  actually apply to every localized string, not just some of them.
//
//  The problem
//  -----------
//  `Bundle.enableLanguageOverride()` (MinisApp.swift) swizzles
//  `Bundle.localizedString(forKey:value:table:)` so the in-app language choice
//  is honoured without an app restart. That works for `Text("…")` and UIKit,
//  which route through that ObjC method — but `String(localized:)` does NOT.
//
//  Measured, not assumed. With the swizzle installed:
//
//      NSLocalizedString("k")   -> Bundle.localizedString hits: 1
//      "k"   -> Bundle.localizedString hits: 0
//
//  Three interception strategies were tried against a real bundle and all
//  three failed to redirect `String(localized:)`:
//    1. method swizzling `localizedString(forKey:value:table:)`   — bypassed
//    2. `object_setClass` onto a Bundle subclass overriding it    — bypassed
//    3. overriding `preferredLocalizations` / `localizations`     — bypassed
//  `String(localized:)` resolves the table natively inside Foundation and
//  never calls back into the ObjC entry point, so nothing installed on
//  `Bundle.main` can steer it. Setting `AppleLanguages` does work, but only
//  from the NEXT process launch — verified: `preferredLocalizations` does not
//  change within the running process.
//
//  What DOES work is the one documented seam: `String(localized:bundle:)`
//  honours an explicit bundle. Verified against `es.lproj` / `de.lproj` /
//  `en.lproj` — each returns that language's value.
//
//  The fix
//  -------
//  Route every call through `AppBundle.current`, which is the overridden
//  `.lproj` bundle when the user has picked a language in-app, and
//  `Bundle.main` otherwise. This is deliberately generic: it is keyed off
//  whatever language is selected, so de / fr / ja / ko / ru / zh-Hans /
//  zh-Hant / es all behave the same. Nothing here is Spanish-specific.
//

import Foundation

/// The bundle localized lookups should read from.
///
/// Mirrors `Bundle.main.languageBundle` (set by `Bundle.setLanguage(_:)`), so
/// the in-app picker and this helper can never disagree about which language is
/// active. Falls back to `Bundle.main` when no in-app override is set, which is
/// the normal case — the system language then applies exactly as before.
enum AppBundle {
    static var current: Bundle {
        Bundle.main.languageBundle ?? Bundle.main
    }
}

/// Localized string that follows the in-app language override.
///
/// Drop-in replacement for `String(localized:)`. Prefer this over
/// `String(localized:)` anywhere the result is shown to the user: the bare
/// form silently ignores the in-app language setting (see the file comment),
/// which is what produced mixed-language UI for users whose system language
/// differs from their in-app choice.
///
/// `Text("…")` does not need this — SwiftUI's `Text` routes through
/// `NSLocalizedString`, which the existing swizzle already covers.
///
/// - Parameters:
///   - key: the localization key, i.e. the English source string.
///   - comment: translator context, kept so `genstrings`-style extraction and
///     the String Catalog continue to see it.
func AppLocalized(_ key: String, comment: StaticString? = nil) -> String {
    NSLocalizedString(key, bundle: AppBundle.current,
                      comment: comment.map { String(describing: $0) } ?? "")
}

/// [T-l10n-interpolation] Localized string WITH format arguments.
///
/// `AppLocalized("Message \(name) (@ to mention files)")` looks harmless and is
/// NOT: Swift resolves the interpolation before the call, so the lookup key
/// becomes the fully-written English sentence ("Message Minis (@ to mention
/// files)") — a key that exists in no catalog. The result is English in a
/// Chinese UI, and it fails silently, which is why it survived in 130+ places.
///
/// The catalog stores ONE parameterized entry per string ("Message %@ (@ to
/// mention files)"), so the arguments have to be applied AFTER the lookup,
/// which is all this does.
///
/// - Parameters:
///   - key: the catalog key, containing `%@` / `%lld` placeholders.
///   - args: the values for those placeholders, in order.
func AppLocalizedFormat(_ key: String, _ args: CVarArg...) -> String {
    String(format: NSLocalizedString(key, bundle: AppBundle.current, comment: ""),
           arguments: args)
}


// MARK: - [T-friendly-error-text] Human-readable error copy

/// Turns whatever an error object says into something a person can read.
///
/// Two shapes kept reaching the red banner verbatim:
///
///  * `Error Domain=NSURLErrorDomain Code=-999 "已取消" UserInfo={…}` — the raw
///    `NSError` description, English scaffolding wrapped around a Chinese word.
///    -999 is `NSURLErrorCancelled`, which is NOT a failure: a superseded
///    request, a stopped turn or a replaced stream all produce it, and showing
///    it as an error trains the user to ignore the banner.
///  * `服务商报错：HTTP 524: <!DOCTYPE html>…` — a relay answering with an HTML
///    error page, dumped into the banner up to its 500-character cap.
///
/// Both are presentation problems, so they are fixed at presentation: the
/// underlying error is untouched for logs and fallback decisions.
enum FriendlyErrorText {

    /// The only display boundary for transport/provider failures.  The error
    /// object and the diagnostic copy are never changed; this returns a safe,
    /// short Chinese sentence for the UI only.  A nil result means a real
    /// cancellation and keeps the existing "don't show a banner" contract.
    static func sanitize(_ raw: String) -> String? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        guard !isCancellation(text) else { return nil }

        if let cleaned = rewriteRawNSError(text) { return cleaned }
        if containsMarkup(text) { return collapseHTMLDump(text) }

        let normalized = stripKnownWrapper(text)
        let payload = jsonPayload(in: normalized)
        let candidate = [payload.message, payload.type, payload.code]
            .compactMap { $0 }.joined(separator: " ")
        let status = httpStatusCode(in: normalized) ?? (payload.status.flatMap(Int.init))
        return classify(candidate.isEmpty ? normalized : candidate, status: status,
                        code: payload.code, domain: nil)
    }

    /// Use this overload at future Error-to-UI boundaries.  It inspects the
    /// NSError domain/code before localizedDescription, so a raw NSError's
    /// English wrapper never reaches the user.  LLMError's description and
    /// fallback decisions are intentionally not modified here.
    static func sanitize(_ error: Error) -> String? {
        if error is CancellationError { return nil }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return nil }
        let description = (error as? LocalizedError)?.errorDescription ?? ns.localizedDescription
        return classify(description, status: httpStatusCode(in: description), code: nil,
                        domain: ns.domain, systemCode: ns.code)
    }

    /// Match only an actual cancellation shape.  In particular, a random
    /// provider payload containing Code=-9999 is not silently discarded.
    private static func isCancellation(_ text: String) -> Bool {
        let lowered = text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if lowered == "cancelled" || lowered == "canceled"
            || lowered == "request was cancelled" || lowered == "request was canceled"
            || lowered == "请求已取消" { return true }
        guard text.hasPrefix("Error Domain=NSURLErrorDomain") else { return false }
        return capture(#"\bCode=(-999)(?:\D|$)"#, in: text) != nil
    }

    /// `Error Domain=NSURLErrorDomain Code=-1001 "The request timed out." …`
    /// becomes a category sentence, not Foundation's English scaffolding.
    private static func rewriteRawNSError(_ text: String) -> String? {
        guard text.hasPrefix("Error Domain=") else { return nil }
        let domain = capture(#"Error Domain=([^ ]+)"#, in: text)
        let code = capture(#"Code=(-?\d+)"#, in: text).flatMap(Int.init)
        if domain == NSURLErrorDomain && code == NSURLErrorCancelled { return nil }
        let reason: String
        if let first = text.firstIndex(of: "\""),
           let second = text[text.index(after: first)...].firstIndex(of: "\"") {
            reason = String(text[text.index(after: first)..<second])
        } else {
            reason = ""
        }
        return classify(reason, status: nil, code: nil, domain: domain, systemCode: code)
    }

    /// HTML/Cloudflare bodies are never displayed.  Keep only a status and a
    /// Chinese meaning; no HTML, stack trace, URL or provider body leaks out.
    private static func collapseHTMLDump(_ text: String) -> String {
        let status = httpStatusCode(in: text)
        let code = providerCode(in: text)
        return classify("", status: status, code: code, domain: nil)
    }

    private static func containsMarkup(_ text: String) -> Bool {
        let lower = text.lowercased()
        return lower.contains("<!doctype") || lower.contains("<html")
            || lower.contains("<head") || lower.contains("<body")
            || lower.contains("<script")
    }

    /// Remove only the presentation wrappers emitted by the app/provider
    /// layer.  Keep the inner protocol text for classification, never for UI.
    private static func stripKnownWrapper(_ text: String) -> String {
        var value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for prefix in ["Provider error:", "服务商报错：", "服务商报错:", "SSE Stream error:", "Stream error:"] {
            if value.lowercased().hasPrefix(prefix.lowercased()) {
                value = String(value.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        return value
    }

    private struct JSONPayload {
        var message: String?
        var type: String?
        var code: String?
        var status: String?
        var isJSON: Bool

        init(isJSON: Bool = false) {
            self.message = nil
            self.type = nil
            self.code = nil
            self.status = nil
            self.isJSON = isJSON
        }
    }

    /// Extract only known error fields. Supports an HTTP prefix before JSON,
    /// but never walks arbitrary response values as though they were errors.
    private static func jsonPayload(in text: String) -> JSONPayload {
        let candidates = [text] + text.split(separator: "\n").map(String.init)
        for line in candidates {
            var body = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if body.lowercased().hasPrefix("data:") { body = String(body.dropFirst(5)).trimmingCharacters(in: .whitespacesAndNewlines) }
            var object = decodeJSON(body)
            if object == nil, let open = body.firstIndex(of: "{"), let close = body.lastIndex(of: "}"), open < close {
                object = decodeJSON(String(body[open...close]))
            }
            guard let dictionary = object as? [String: Any] else { continue }
            let typeHint = (dictionary["type"] as? String ?? "").lowercased()
            let codeHint = (dictionary["code"] as? String ?? "").lowercased()
            let explicitError = dictionary["error"] != nil || dictionary["errors"] != nil
                || dictionary["error_code"] != nil || httpStatusCode(in: text) != nil
                || [typeHint, codeHint].contains(where: { hint in
                    ["error", "invalid", "rate", "quota", "model", "forbidden", "auth", "timeout", "limit", "denied"]
                        .contains(where: hint.contains)
                })
            guard explicitError else { continue }
            var result = JSONPayload(isJSON: true)
            collectJSON(dictionary, into: &result, depth: 0, errorContext: true)
            if result.message != nil || result.type != nil || result.code != nil || result.status != nil { return result }
        }
        return JSONPayload()
    }

    private static func decodeJSON(_ text: String) -> Any? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    private static func collectJSON(_ object: Any, into result: inout JSONPayload,
                                    depth: Int, errorContext: Bool) {
        guard depth <= 4, let dictionary = object as? [String: Any] else { return }
        if errorContext {
            for key in ["message", "detail", "reason", "error_description"] {
                if result.message == nil, let value = dictionary[key] as? String,
                   !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { result.message = value }
            }
            if result.type == nil, let value = dictionary["type"] as? String { result.type = value }
            for key in ["code", "error_code"] {
                if result.code == nil, let value = dictionary[key] as? String { result.code = safeCode(value) }
                if result.code == nil, let value = dictionary[key] as? NSNumber { result.code = value.stringValue }
            }
            if let value = dictionary["error"] as? String,
               result.message == nil, !value.isEmpty { result.message = value }
        }
        for key in ["status", "statusCode", "status_code"] {
            if result.status == nil, let value = dictionary[key] as? String { result.status = value }
            if result.status == nil, let value = dictionary[key] as? NSNumber { result.status = value.stringValue }
        }
        for key in ["error", "errors"] {
            if let nested = dictionary[key] { collectJSON(nested, into: &result, depth: depth + 1, errorContext: true) }
        }
    }

    private static func classify(_ raw: String, status: Int?, code: String?,
                                 domain: String?, systemCode: Int? = nil) -> String {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let lower = text.lowercased()
        // Provider symbolic codes can contain credentials or opaque internals;
        // classification may use them, but presentation never appends them.
        let numericCodeSuffix = code.flatMap(Int.init).map {
            "（" + AppLocalized("错误码") + " \($0)）"
        } ?? ""
        let systemSuffix = systemCode.map { "（" + AppLocalized("错误码") + " \($0)）" } ?? ""
        func withHTTP(_ message: String) -> String {
            if let status { return "HTTP \(status)：" + message + numericCodeSuffix + systemSuffix }
            return message + numericCodeSuffix + systemSuffix
        }
        let hints = (lower + " " + (code?.lowercased() ?? ""))
        let isQuota = hints.contains("insufficient_quota")
            || ((hints.contains("insufficient") || hints.contains("exhausted"))
                && (hints.contains("quota") || hints.contains("balance")))
            || hints.contains("billing_hard_limit") || hints.contains("余额不足")
            || hints.contains("额度耗尽") || hints.contains("欠费") || status == 402

        if hints.contains("context length") || hints.contains("context_length_exceeded")
            || hints.contains("too many tokens") || hints.contains("maximum context")
            || hints.contains("上下文") || hints.contains("token limit") {
            return withHTTP(AppLocalized("上下文超出供应商限制"))
        }
        if hints.contains("content filter") || hints.contains("content_policy")
            || hints.contains("moderation") || hints.contains("safety system")
            || hints.contains("内容审核") || hints.contains("安全策略") {
            return withHTTP(AppLocalized("内容被供应商审核拦截"))
        }
        if isQuota { return withHTTP(AppLocalized("供应商账户余额或额度不足")) }
        if hints.contains("file permission") || hints.contains("permission denied for file")
            || hints.contains("cannot write file") || hints.contains("cannot read file")
            || hints.contains("文件权限") || hints.contains("文件访问被拒绝") {
            return withHTTP(AppLocalized("文件读写失败"))
        }
        if hints.contains("permission denied") || hints.contains("forbidden")
            || hints.contains("not authorized") || hints.contains("无权限") || status == 403 {
            return withHTTP(AppLocalized("没有权限访问供应商"))
        }
        if hints.contains("invalid api key") || hints.contains("incorrect api key")
            || hints.contains("invalid_api_key") || hints.contains("unauthorized")
            || hints.contains("api key 无效") || hints.contains("key 无效") || status == 401 {
            return withHTTP(AppLocalized("API Key 无效或已失效"))
        }
        if hints.contains("model_not_found") || hints.contains("model not found")
            || hints.contains("model does not exist") || hints.contains("unknown model")
            || hints.contains("no such model") || hints.contains("模型不存在")
            || hints.contains("模型或路由") {
            return withHTTP(AppLocalized("模型或路由不存在"))
        }
        if status == 404 {
            return withHTTP(AppLocalized("接口地址或路由不存在"))
        }
        if status == 429 || hints.contains("rate limit") || hints.contains("rate_limit")
            || hints.contains("too many requests") || hints.contains("ratelimit") || hints.contains("限流") {
            return withHTTP(AppLocalized("短时请求过多，供应商正在限流"))
        }
        if lower.contains("certificate") || lower.contains("ssl") || lower.contains("tls")
            || lower.contains("证书") || (domain == NSURLErrorDomain && (systemCode == -1200 || systemCode == -1201)) {
            return withHTTP(AppLocalized("安全证书或 TLS 连接失败"))
        }
        if domain == NSURLErrorDomain && systemCode == NSURLErrorTimedOut {
            return withHTTP(AppLocalized("网络请求超时，连接没有及时响应"))
        }
        if domain == NSURLErrorDomain && (lower.contains("timed out") || lower.contains("timeout")) {
            return withHTTP(AppLocalized("网络请求超时，连接没有及时响应"))
        }
        if status == 524 {
            return withHTTP(AppLocalized("供应商网关等待上游超时"))
        }
        if status == 408 || status == 504 || status == 522 || status == 524 || lower.contains("timeout") || lower.contains("timed out")
            || lower.contains("请求超时") {
            return withHTTP(AppLocalized("请求超时，供应商没有及时响应"))
        }
        if domain == NSCocoaErrorDomain || lower.contains("file read") || lower.contains("file write")
            || lower.contains("file access") || lower.contains("no such file")
            || lower.contains("permission denied for file") || lower.contains("文件") || lower.contains("读写") {
            return withHTTP(AppLocalized("文件读写失败"))
        }
        if domain == NSURLErrorDomain || lower.contains("network") || lower.contains("not connected")
            || lower.contains("offline") || lower.contains("网络") || lower.contains("connection failed") {
            return withHTTP(AppLocalized("网络连接失败"))
        }
        if lower.contains("overloaded") || lower.contains("overload") || lower.contains("service unavailable")
            || status == 500 || status == 502 || status == 503 {
            return withHTTP(AppLocalized("供应商服务暂时过载或不可用"))
        }
        if let chinese = safeChineseReason(text) {
            if let status { return "HTTP \(status)：" + chinese + systemSuffix }
            return chinese + systemSuffix
        }
        if let status {
            return withHTTP(httpMeaning(status) ?? AppLocalized("供应商返回了无法识别的错误"))
        }
        // Unknown Errors are not implicitly attributed to a provider.
        return AppLocalized("无法识别的错误") + systemSuffix
    }

    private static func safeChineseReason(_ text: String) -> String? {
        guard text.count <= 160, text.range(of: #"[\u4e00-\u9fff]"#, options: .regularExpression) != nil else { return nil }
        let lower = text.lowercased()
        if lower.contains("api key") || lower.contains("authorization") || lower.contains("bearer")
            || lower.contains("sk-") || lower.contains("token=") || text.contains("http://") || text.contains("https://") {
            return nil
        }
        let stripped = text.replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "\r", with: " ")
        return stripped.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func capture(_ pattern: String, in text: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]),
              let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              let range = Range(match.range(at: 1), in: text) else { return nil }
        return String(text[range])
    }

    private static func httpStatusCode(in text: String) -> Int? {
        let patterns = [#"(?i)\bhttp\s*:?[ "]*([45]\d{2})\b"#,
                        #"(?i)\bstatus(?:code)?[ "]*[:=][ "]*([45]\d{2})\b"#,
                        #"\[[ "]*([45]\d{2})[ "]*\]"#]
        for pattern in patterns {
            if let value = capture(pattern, in: text), let code = Int(value) { return code }
        }
        return nil
    }

    private static func providerCode(in text: String) -> String? {
        let value = capture(#"(?i)[\"'](?:code|error_code)[\"']\s*:\s*[\"']?([A-Za-z0-9._-]{2,64})"#, in: text)
            ?? capture(#"(?i)\bcode\s*[=:]\s*([A-Za-z0-9._-]{2,64})"#, in: text)
        return value.flatMap(safeCode)
    }

    private static func safeCode(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 64,
              trimmed.range(of: #"^[A-Za-z0-9._-]+$"#, options: .regularExpression) != nil else { return nil }
        return trimmed
    }

    private static func httpMeaning(_ code: Int) -> String? {
        switch code {
        case 400: return AppLocalized("请求格式不对")
        case 401: return AppLocalized("Key 无效或没有权限")
        case 403: return AppLocalized("被拒绝访问")
        case 404: return AppLocalized("接口地址不存在")
        case 408: return AppLocalized("请求超时")
        case 429: return AppLocalized("请求太频繁")
        case 500: return AppLocalized("对方服务器内部错误")
        case 502: return AppLocalized("网关错误")
        case 503: return AppLocalized("对方服务暂时不可用")
        case 504: return AppLocalized("网关超时")
        case 520, 521, 522, 523, 524: return AppLocalized("对方服务器没有及时响应")
        default: return nil
        }
    }
}

// MARK: - [T-compaction-l10n] Compaction rows, in the reader's language

/// The compaction separator and status rows carry their English sentence in
/// `ChatMessage.content` — it is written once, when the compaction happens, and
/// then lives in the transcript forever. Localizing at write time would freeze
/// that row in whatever language was active back then, and would leave every
/// historical row English anyway.
///
/// So the translation happens at DISPLAY: the stored string stays a stable,
/// language-neutral marker, and this maps the known shapes to the current
/// language. Unknown text passes through untouched — a future row type shows its
/// own wording rather than a mistranslation.
enum CompactionCopy {
    static func localize(_ raw: String) -> String {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return raw }

        // "41 messages compacted" / "1 messages compacted"
        if let n = intBefore(text, suffix: " messages compacted") {
            return String(format: AppLocalized("%@ 条消息已压缩"), String(n))
        }
        // "Compacting conversation... (211 chars)"
        if text.hasPrefix("Compacting conversation...") {
            if let open = text.lastIndex(of: "("), let close = text.lastIndex(of: ")"),
               open < close {
                let inner = String(text[text.index(after: open)..<close])
                let chars = inner.replacingOccurrences(of: " chars", with: "")
                return String(format: AppLocalized("正在压缩对话…（%@ 字符）"), chars)
            }
            return AppLocalized("正在压缩对话…")
        }
        // "Compacting with DeepSeek V4 Flash..."
        if text.hasPrefix("Compacting with "), text.hasSuffix("...") {
            let name = text
                .replacingOccurrences(of: "Compacting with ", with: "")
                .replacingOccurrences(of: "...", with: "")
            return String(format: AppLocalized("正在用 %@ 压缩…"), name)
        }
        // "Compaction failed: …" — keep the reason, translate the frame.
        if text.hasPrefix("Compaction failed") {
            let reason = text
                .replacingOccurrences(of: "Compaction failed:", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return reason.isEmpty
                ? AppLocalized("压缩失败")
                : String(format: AppLocalized("压缩失败：%@"), reason)
        }
        return raw
    }

    private static func intBefore(_ text: String, suffix: String) -> Int? {
        guard text.hasSuffix(suffix) else { return nil }
        let head = String(text.dropLast(suffix.count))
        return Int(head)
    }
}

// MARK: - [T-provider-error-digest] A Chinese sentence in front of the raw reply

/// Maps the provider messages users actually hit onto one plain Chinese
/// sentence, leaving the original text underneath for diagnosis.
///
/// Deliberately a fixed table, not a translator: these strings are protocol
/// text ("thinking", "content[].thinking", "max_tokens") where a loose
/// translation would invent meaning. A message that matches nothing returns
/// nil and the banner keeps showing the raw text alone — a wrong summary is
/// worse than none.
enum ProviderErrorDigest {

    /// Chinese-only text for one provider error. `code` is the provider's own
    /// code (for support), never the whole JSON body.
    struct Display {
        let title: String
        let detail: String?
        let code: String?

        /// The banner's original second line: the reason, plus the provider
        /// code when there is one. Kept separate so the existing two-line
        /// banner layout (main sentence + smaller detail) is untouched.
        var secondaryLine: String? {
            var parts: [String] = []
            if let detail, !detail.isEmpty { parts.append(detail) }
            if let code, !code.isEmpty { parts.append(AppLocalized("代码") + " " + code) }
            return parts.isEmpty ? nil : parts.joined(separator: " ")
        }
    }

    /// Full display mapping. `summary` is kept as the title-only entry point
    /// for existing call sites and tests.
    static func display(for raw: String) -> Display? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        let lower = text.lowercased()
        let status = httpStatus(in: text)
        let code = providerCode(in: text)

        // Protocol-level messages first: a 400 carrying one of these is not an
        // auth failure, even though providers sometimes label it that way.
        if lower.contains("thinking") && (lower.contains("not supported") || lower.contains("unsupported")) {
            return Display(title: AppLocalized("这个模型不支持「思考」参数"),
                           detail: AppLocalized("把「思考」关掉再试。"), code: code)
        }
        if lower.contains("content[].thinking") || lower.contains("must be passed back") {
            return Display(title: AppLocalized("这条会话的思考内容没收全"),
                           detail: AppLocalized("重试一次；还不行就换模型。"), code: code)
        }
        if lower.contains("context length") || lower.contains("context_length_exceeded")
            || lower.contains("too many tokens") || lower.contains("maximum context") {
            return Display(title: AppLocalized("上下文超出供应商限制"),
                           detail: AppLocalized("压缩对话，或换一个上下文更大的模型。"), code: code)
        }
        if lower.contains("content filter") || lower.contains("content_policy")
            || lower.contains("safety") || lower.contains("moderation") {
            return Display(title: AppLocalized("被供应商的内容审核拦截"),
                           detail: AppLocalized("换个说法再试。"), code: code)
        }

        // 401 is not proof the key string is wrong: relays also use it for
        // account restrictions and short bursts. Say that, instead of
        // "API Key 无效" over a raw JSON body.
        if status == 401 || lower.contains("invalid api key") || lower.contains("incorrect api key")
            || lower.contains("invalid_api_key") || lower.contains("unauthorized")
            || lower.contains("api key 无效") || (code?.hasPrefix("AUTH") == true) {
            return Display(title: AppLocalized("供应商鉴权失败（HTTP 401）"),
                           detail: AppLocalized("可能是 Key 没权限、账号被限制，或短时请求过多。"),
                           code: code)
        }
        if status == 402
            || (lower.contains("insufficient") && (lower.contains("quota") || lower.contains("balance")))
            || lower.contains("余额不足") || lower.contains("额度耗尽") {
            return Display(title: AppLocalized("供应商账户余额不足"),
                           detail: AppLocalized("充值，或换一个有余额的 Key 再试。"), code: code)
        }
        if status == 403 || lower.contains("permission denied") || lower.contains("forbidden") {
            return Display(title: AppLocalized("供应商拒绝访问（HTTP 403）"),
                           detail: AppLocalized("可能是 Key 没有权限，也可能是网络出口 IP 被拦截；换网或检查权限后再试。"), code: code)
        }
        if lower.contains("no available channel") || lower.contains("无可用渠道")
            || lower.contains("model_not_found") {
            return Display(title: AppLocalized("这个分组暂时没有可用渠道"),
                           detail: AppLocalized("不是 Key 坏了；换一个模型，或让供应商补渠道。"), code: code)
        }
        if status == 413 {
            return Display(title: AppLocalized("请求体超过站点限制"),
                           detail: AppLocalized("不是 Key 坏了；减少附件或手动压缩上下文后重试。"), code: code)
        }
        if status == 404 || (lower.contains("model") && (lower.contains("not found")
            || lower.contains("does not exist") || lower.contains("unknown model")
            || lower.contains("no such model"))) {
            return Display(title: AppLocalized("供应商没有这个模型"),
                           detail: AppLocalized("检查模型名或接口地址。"), code: code)
        }
        if status == 429 || lower.contains("rate limit") || lower.contains("too many requests")
            || lower.contains("429") {
            return Display(title: AppLocalized("请求太频繁，被供应商限流"),
                           detail: AppLocalized("等几十秒再试。"), code: code)
        }
        if (status.map { (500...599).contains($0) } ?? false)
            || lower.contains("overloaded") || lower.contains("service unavailable") {
            let codeText = status.map { String($0) } ?? "5xx"
            return Display(title: String(format: AppLocalized("供应商服务暂时不可用（HTTP %@）"), codeText),
                           detail: AppLocalized("稍后再试。"), code: code)
        }
        if status == 408 || lower.contains("timeout") || lower.contains("timed out")
            || lower.contains("network error") || lower.contains("网络错误") {
            return Display(title: AppLocalized("当前网络线路失败"),
                           detail: AppLocalized("可切换 Wi-Fi 或 4G 重试；这不一定是 Key 或模型的问题。"), code: code)
        }
        if let limit = imageLimit(in: lower) {
            return Display(title: String(format: AppLocalized("这条会话里的图片超过 %lld 张"), Int64(limit)),
                           detail: String(format: AppLocalized("不是 Key 失效；这个站点一次只接收 %lld 张图片。旧图会自动裁掉，或新建会话再试。"), Int64(limit)),
                           code: code)
        }
        if status == 400 {
            return Display(title: AppLocalized("供应商拒绝了请求（HTTP 400）"),
                           detail: AppLocalized("请求格式或参数不对。"), code: code)
        }
        // Last resort: never hand the raw upstream English/JSON to the user.
        // Keep the useful category, but always give one short Chinese sentence
        // and a next step. The raw text is still available by long-press copy
        // because the bubble's context menu stores `message.error` unchanged.
        let detail: String
        if lower.contains("image") {
            detail = AppLocalized("图片数量或格式不被接受；先删到 4 张以内，或换一张图再试。")
        } else if lower.contains("tool") || lower.contains("function call") {
            detail = AppLocalized("工具调用参数不被接受；重试一次，还不行就换个模型。")
        } else if lower.contains("parameter") || lower.contains("invalid request") {
            detail = AppLocalized("请求参数不被接受；检查模型名、思考开关和附件后重试。")
        } else if let status {
            detail = String(format: AppLocalized("供应商拒绝了这次请求（HTTP %lld）；稍后重试。"), Int64(status))
        } else {
            detail = AppLocalized("上游返回了一个无法识别的错误；重试一次，反复出现再联系供应商。")
        }
        return Display(title: AppLocalized("供应商返回错误"),
                       detail: detail,
                       code: code)
    }

    /// Pull a per-request image cap out of any common provider phrasing.
    /// Used by both the Chinese display and the per-site learned limit.
    static func imageLimit(in text: String) -> Int? {
        let lower = text.lowercased()
        guard lower.contains("image") else { return nil }
        let patterns = [
            #"at most\s+(\d{1,2})\s+images?"#,
            #"max(?:imum)?(?:\s+of)?\s+(\d{1,2})\s+images?"#,
            #"up to\s+(\d{1,2})\s+images?"#,
            #"only\s+(\d{1,2})\s+images?"#
        ]
        for pattern in patterns {
            if let re = try? NSRegularExpression(pattern: pattern),
               let match = re.firstMatch(in: lower, range: NSRange(lower.startIndex..., in: lower)),
               let range = Range(match.range(at: 1), in: lower),
               let value = Int(lower[range]), value > 0 {
                return value
            }
        }
        // The site stated an image-count limit but not a parseable number:
        // four is the common OpenAI-relay cap and is always safe to try.
        if lower.contains("at most") || lower.contains("maximum") || lower.contains("limit") {
            return 4
        }
        return nil
    }

    /// Title only, for the existing banner/test contract.
    static func summary(for raw: String) -> String? {
        display(for: raw)?.title
    }

    /// One paragraph, exactly the shape the old bubble rendered: title,
    /// reason and the provider's code in a single Text. The bubble keeps its
    /// original font, padding and self-sizing; only the words change.
    static func composed(for raw: String) -> String? {
        guard let display = display(for: raw) else { return nil }
        var text = display.title
        if let detail = display.detail, !detail.isEmpty {
            text += "：" + detail
        }
        if let code = display.code, !code.isEmpty {
            text += "（" + AppLocalized("代码") + " " + code + "）"
        }
        return text
    }

    private static func httpStatus(in text: String) -> Int? {
        let patterns = [
            #"(?i)\bhttp\s*:?\s*([45]\d{2})\b"#,
            #"(?i)\bstatus(?:code)?\s*[=:]\s*([45]\d{2})\b"#,
            #"\[\s*([45]\d{2})\s*\]"#
        ]
        for pattern in patterns {
            if let re = try? NSRegularExpression(pattern: pattern),
               let match = re.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
               let range = Range(match.range(at: 1), in: text) {
                return Int(text[range])
            }
        }
        return nil
    }

    private static func providerCode(in text: String) -> String? {
        let patterns = [
            #""code"\s*:\s*"([^"]+)""#,
            #"(?i)\bcode\s*[=:]\s*([A-Za-z0-9._-]+)"#
        ]
        for pattern in patterns {
            if let re = try? NSRegularExpression(pattern: pattern),
               let match = re.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
               let range = Range(match.range(at: 1), in: text) {
                let value = String(text[range]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !value.isEmpty { return value }
            }
        }
        // Provider-style codes such as AUTH-ERR-5.
        if let re = try? NSRegularExpression(pattern: #"\b[A-Z][A-Z0-9]{2,}-[A-Z0-9-]{2,}\b"#),
           let match = re.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let range = Range(match.range, in: text) {
            return String(text[range])
        }
        return nil
    }
}

// MARK: - [T-turn-cost] What this turn cost, appended to the context line

/// Formats an estimated price for one API call from its token usage.
///
/// Numbers only, no labels: the context line already says what it is, and the
/// user asked for 「字体都对齐，统一一下」 — so the suffix is the same size and
/// colour as the rest of the line, with tabular digits so it does not jitter.
///
/// The figure is an ESTIMATE by construction: prices come from the bundled
/// models.dev catalog (official list prices), while relays bill at their own
/// multiplier, which no API exposes. Hence the leading ≈.
enum TurnCost {
    /// `currency`: "CNY" or "USD". `rate`: CNY per USD (only used for CNY).
    static let currencyKey = "cost.displayCurrency"
    static let rateKey = "cost.usdToCnyRate"

    static var currency: String {
        UserDefaults.standard.string(forKey: currencyKey) ?? "CNY"
    }

    static var usdToCny: Double {
        let stored = UserDefaults.standard.object(forKey: rateKey) as? Double
        guard let stored, stored > 0 else { return 7.3 }
        return stored
    }

    /// "≈¥0.0075" / "≈$0.0010", or nil when the model has no known price.
    static func suffix(usage: TokenUsage, modelId: String?) -> String? {
        guard let modelId,
              let price = ModelsDevAPI.pricingPerMillion(for: modelId) else { return nil }
        let usd = usd(usage: usage, inputPrice: price.input, outputPrice: price.output)
        guard usd > 0 else { return nil }
        return formatted(usd)
    }

    /// Cost from explicit USD prices per 1M tokens. The site-pricing path uses
    /// this; the catalog path above remains the fallback for sites without a
    /// pricing endpoint.
    static func usd(usage: TokenUsage, inputPrice: Double, outputPrice: Double) -> Double {
        let inputTokens = Double(usage.inputTokens + usage.cacheReadTokens + usage.cacheCreationTokens)
        let outputTokens = Double(usage.outputTokens)
        return (inputTokens * inputPrice + outputTokens * outputPrice) / 1_000_000
    }

    static func formatted(_ usd: Double, rate: Double? = nil, currency: String? = nil) -> String {
        let code = (currency ?? Self.currency).uppercased()
        if code == "USD" {
            return String(format: "≈$%.4f", usd)
        }
        if code == "CNY" {
            return String(format: "≈¥%.4f", usd * (rate ?? usdToCny))
        }
        // Arbitrary user code (EUR/JPY/...): use the code as the prefix so
        // no symbol table or network lookup is required.
        return String(format: "≈%@ %.4f", code, usd * (rate ?? 1))
    }

    /// Compact composer suffix: two decimals, because the line also carries
    /// context percentage and token counts. The full four-decimal figure stays
    /// available in the detail sheet.
    static func compact(_ usd: Double, rate: Double? = nil, currency: String? = nil) -> String {
        // No currency symbol in the composer: the shorter run keeps the
        // context figures readable. The detail sheet keeps the full symbol.
        let code = (currency ?? Self.currency).uppercased()
        let value = code == "USD" ? usd : usd * (rate ?? usdToCny)
        return String(format: "≈%.2f", value)
    }
}
