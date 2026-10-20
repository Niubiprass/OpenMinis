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
        case .invalidAPIKey, .providerError, .decodingError, .rateLimited, .cancelled, .unknown:
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
        case .providerError(let msg):
            return String(format: AppLocalized("Provider error: %@"), String(msg.prefix(60)))
        default: return AppLocalized("Error")
        }
    }

    var isFallbackable: Bool {
        switch self {
        case .rateLimited, .invalidAPIKey, .providerError:
            return true
        case .transientError, .networkError, .decodingError, .cancelled, .unknown:
            return false
        }
    }

    /// [T-fallback-503-budget] The HTTP status this error was mapped from, when
    /// the mapping site had one. nil for every non-HTTP condition.
    var httpStatusCode: Int? {
        if case .transientError(_, let code) = self { return code }
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
