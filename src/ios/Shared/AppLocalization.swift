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

    /// Nil means "do not show this at all" — cancellations.
    static func sanitize(_ raw: String) -> String? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return nil }

        if isCancellation(text) { return nil }

        if let cleaned = rewriteRawNSError(text) { return cleaned }

        return collapseHTMLDump(text)
    }

    /// `-999` / "已取消" / "cancelled" arriving as prose rather than a type.
    private static func isCancellation(_ text: String) -> Bool {
        if text.contains("Code=-999") { return true }
        let lowered = text.lowercased()
        if lowered == "cancelled" || lowered == "canceled" { return true }
        if lowered.hasSuffix("已取消") && lowered.count <= 40 { return true }
        return false
    }

    /// `Error Domain=NSURLErrorDomain Code=-1001 "请求超时。" UserInfo=…`
    /// → `网络错误：请求超时。`
    private static func rewriteRawNSError(_ text: String) -> String? {
        guard text.hasPrefix("Error Domain=") else { return nil }
        // The quoted segment is the system's own localized reason — keep it.
        var reason: String?
        if let firstQuote = text.firstIndex(of: "\""),
           let secondQuote = text[text.index(after: firstQuote)...].firstIndex(of: "\"") {
            reason = String(text[text.index(after: firstQuote)..<secondQuote])
        }
        let domain = text.contains("NSURLErrorDomain") ? "network"
                   : (text.contains("NSCocoaErrorDomain") ? "file" : "other")
        let fallback = reason ?? AppLocalized("未知错误")
        switch domain {
        case "network": return String(format: AppLocalized("网络错误：%@"), fallback)
        case "file":    return String(format: AppLocalized("文件错误：%@"), fallback)
        default:        return fallback
        }
    }

    /// `HTTP 524: <!DOCTYPE html>…` → `HTTP 524：对方服务器没有及时响应`
    private static func collapseHTMLDump(_ text: String) -> String {
        let lowered = text.lowercased()
        let looksLikeMarkup = lowered.contains("<!doctype") || lowered.contains("<html")
            || lowered.contains("<head") || lowered.contains("<body")
        guard looksLikeMarkup else {
            return text.count > 300 ? String(text.prefix(300)) + "…" : text
        }

        // Keep whatever readable prefix precedes the markup — usually
        // "HTTP 524: " or the provider's own one-line reason.
        let markerIndex = lowered.range(of: "<!doctype").map { $0.lowerBound }
            ?? lowered.range(of: "<html").map { $0.lowerBound }
        let prefix = markerIndex.map { String(text[..<$0]) } ?? ""
        let head = prefix.trimmingCharacters(in: CharacterSet(charactersIn: " :：,，;；"))

        if head.isEmpty { return AppLocalized("服务商返回了一个错误页面（不是接口响应）") }
        // "HTTP 524" → add the human meaning when the code is known.
        if let code = httpStatusCode(head), let meaning = httpMeaning(code) {
            return String(format: AppLocalized("%@：%@"), head, meaning)
        }
        return head
    }

    private static func httpStatusCode(_ text: String) -> Int? {
        guard let range = text.range(of: "HTTP ") else { return nil }
        let digits = text[range.upperBound...].prefix(3)
        return Int(digits)
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
