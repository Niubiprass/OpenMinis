import Foundation

enum LLMError: LocalizedError {
    case invalidAPIKey(detail: String = "")
    case networkError(underlying: Error)
    case providerError(message: String)
    /// Transient server-side errors (HTTP 500/502/503/504/529) that should be
    /// retried on the same model rather than triggering a group fallback.
    ///
    /// [T-fallback-503-budget] `statusCode` is the HTTP status the mapping site
    /// actually saw, and is nil for transient conditions with no HTTP response
    /// of their own (stall/TTFB timeouts, empty responses, compaction breaches).
    /// It exists so the fallback planner can tell "the upstream answered 503,
    /// this model has no capacity" from "our link/stream misbehaved" WITHOUT
    /// substring-matching a body that may legitimately contain "503".
    case transientError(message: String, statusCode: Int? = nil)
    case decodingError(underlying: Error)
    case rateLimited
    /// The request body exceeded either the provider's/gateway's byte limit or
    /// our pre-serialization memory ceiling. Distinct from a context-window
    /// overflow: the token count can be far below the window while nginx still
    /// rejects at ~1 MB. The provider trims old payload on the next attempt.
    case requestTooLarge(estimatedBytes: Int?, limitBytes: Int?, detail: String = "")
    case cancelled
    case unknown(underlying: Error?)

    var errorDescription: String? {
        // [T-error-copy-l10n] Every string here is user-facing: it is what the
        // red banner in the transcript prints verbatim (and what the group
        // trail repeats per model). They used to be English literals, so a
        // Chinese UI still said "Rate limited — please try again later" — the
        // report that started this. `AppLocalized` + a format string keeps the
        // numbers/ids the provider sent while translating the sentence.
        switch self {
        case .invalidAPIKey(let detail):
            return detail.isEmpty
                ? AppLocalized("Invalid API key")
                : String(format: AppLocalized("Invalid API key: %@"), detail)
        case .networkError(let error):
            return String(format: AppLocalized("Network error: %@"), error.localizedDescription)
        case .providerError(let message):
            return String(format: AppLocalized("Provider error: %@"), message)
        case .transientError(let message, _):
            return String(format: AppLocalized("Service temporarily unavailable: %@"), message)
        case .decodingError(let error):
            return String(format: AppLocalized("Decoding error: %@"), error.localizedDescription)
        case .rateLimited:
            return AppLocalized("Rate limited — please try again later")
        case .requestTooLarge(let estimated, let limit, let detail):
            let size = estimated.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? AppLocalized("unknown size")
            let cap = limit.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? AppLocalized("provider limit")
            let base = String(format: AppLocalized("[413] Request body is too large (%@, site limit %@). Old tool output is trimmed and retried automatically; if it keeps happening, start a new conversation."), size, cap)
            return detail.isEmpty ? base : base + "\n" + detail
        case .cancelled:
            return AppLocalized("Request was cancelled")
        case .unknown(let error):
            return String(format: AppLocalized("Unknown error: %@"),
                          error?.localizedDescription ?? AppLocalized("no details"))
        }
    }

    var isNetworkError: Bool {
        if case .networkError = self { return true }
        return false
    }

    /// Errors that should be retried with countdown on the same provider.
    /// Includes both network errors and transient server-side errors (5xx).
    var isRetryable: Bool {
        switch self {
        case .networkError, .transientError:
            return true
        case .invalidAPIKey, .providerError, .decodingError, .rateLimited,
             .requestTooLarge, .cancelled, .unknown:
            return false
        }
    }

    /// Errors that indicate the provider itself cannot serve this request
    /// (rate limit, invalid key, permanent provider-side rejection). These trigger
    /// an immediate fallback to the next model in a group, without retry countdown.
    ///
    /// Note: transientError and networkError are also fallbackable — after
    /// auto-retry is exhausted on the current model, group fallback kicks in.
    var fallbackReason: String {
        // Same treatment as `errorDescription`: this reaches the user too, as
        // one "⚠️ model (site): reason" line per attempted entry in the
        // group-exhausted banner.
        switch self {
        case .rateLimited: return AppLocalized("Rate limited")
        case .invalidAPIKey: return AppLocalized("Invalid API key")
        case .requestTooLarge: return AppLocalized("Request too large")
        case .providerError(let msg):
            return String(format: AppLocalized("Provider error: %@"), String(msg.prefix(60)))
        default: return AppLocalized("Error")
        }
    }

    var isFallbackable: Bool {
        switch self {
        case .rateLimited, .invalidAPIKey, .providerError, .requestTooLarge:
            return true
        case .transientError, .networkError, .decodingError, .cancelled, .unknown:
            return false
        }
    }

    /// [T-fallback-503-budget] The HTTP status this error was mapped from, when
    /// the mapping site had one. nil for every non-HTTP condition.
    var httpStatusCode: Int? {
        if case .transientError(_, let code) = self { return code }
        if case .requestTooLarge = self { return 413 }
        return nil
    }

    var isRequestTooLarge: Bool {
        if case .requestTooLarge = self { return true }
        return false
    }

    /// Non-empty only when the PROVIDER answered 413 (the guard's local
    /// rejection has no body). Only that case earns a lower learned cap and a
    /// retry; a body that still cannot fit after trimming goes straight out.
    var requestTooLargeServerDetail: String? {
        if case .requestTooLarge(_, _, let detail) = self, !detail.isEmpty { return detail }
        return nil
    }

    /// A transient error the SERVER produced with a 5xx status — i.e. this
    /// model/deployment has no capacity right now, which another group member
    /// may well have. Distinct from a local/link transient (nil status), where
    /// switching models fixes nothing.
    var isServerCapacityTransient: Bool {
        guard let code = httpStatusCode else { return false }
        return (500...599).contains(code)
    }
}


/// Per-endpoint learned request-body ceiling.
///
/// A context window says how many tokens a model accepts; it says nothing
/// about an nginx/Cloudflare front door. A 1,050,000-token model behind a
/// 1 MB `client_max_body_size` still answers 413 at ~250k tokens. The cap is
/// therefore remembered per HOST (never per model) after a real rejection and
/// only ever moves DOWN, with a floor so one pathological probe cannot pin it
/// at a few kilobytes.
enum RequestBodyByteBudget {
    static let officialDefault = 8 * 1024 * 1024
    static let relayDefault = 768 * 1024
    static let floor = 128 * 1024
    private static let prefix = "provider.bodyCap."
    private static let datePrefix = "provider.bodyCapAt."
    private static let maxAge: TimeInterval = 7 * 24 * 60 * 60

    static func key(for baseURL: String?) -> String {
        guard let baseURL, let host = URL(string: baseURL)?.host?.lowercased(), !host.isEmpty else {
            return "__official__"
        }
        return host
    }

    /// Hosts known to accept multi-megabyte bodies even when entered as a
    /// "custom" base URL. Prefix match covers Azure resource subdomains.
    private static let officialHosts = [
        "api.openai.com", "chatgpt.com", "api.anthropic.com",
        "generativelanguage.googleapis.com",
    ]

    static func cap(for key: String, customBase: Bool) -> Int {
        let host = key.split(separator: "|", maxSplits: 1).first.map(String.init) ?? ""
        let official = officialHosts.contains(host) || host.hasSuffix(".openai.azure.com")
        let fallback = (official || !customBase) ? officialDefault : relayDefault
        let learned = UserDefaults.standard.integer(forKey: prefix + key)
        guard learned > 0 else { return fallback }
        let at = UserDefaults.standard.object(forKey: datePrefix + key) as? Date
        if let at, Date().timeIntervalSince(at) > maxAge {
            UserDefaults.standard.removeObject(forKey: prefix + key)
            UserDefaults.standard.removeObject(forKey: datePrefix + key)
            return fallback
        }
        return min(fallback, max(floor, learned))
    }

    /// Learn from a real 413. Halve what was just rejected so a low gateway
    /// limit converges in the two retries the agent loop allows.
    @discardableResult
    static func noteRejected(key: String, attemptedBytes: Int?) -> Int {
        let current = cap(for: key, customBase: !key.hasPrefix("__official__"))
        let proposed = attemptedBytes.map { max(floor, $0 / 2) } ?? min(current, relayDefault)
        let next = max(floor, min(current, proposed))
        UserDefaults.standard.set(next, forKey: prefix + key)
        UserDefaults.standard.set(Date(), forKey: datePrefix + key)
        return next
    }
}
