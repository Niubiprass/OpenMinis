import Foundation
import WebKit

// MARK: - [T-115-quota] 额度与余额一目了然 (App Store 1.15)

/// Provider quota / balance display support.
///
/// Data source — the same one the official Android 1.15 port uses:
///   * OpenAI-compatible instances (API-key creds): the OpenAI billing pair
///     `GET {base}/v1/dashboard/billing/subscription` (hard/soft limit USD)
///     + `GET {base}/v1/dashboard/billing/usage?start_date&end_date`
///     (month-to-date usage in cents). Works for official OpenAI keys and for
///     relays that implement these endpoints; relays that 404/401/403 simply
///     show nothing.
///   * Anthropic instances: month-to-date spend via
///     `GET {base}/v1/organizations/usage/costs` (no public limit endpoint →
///     spend only, never highlighted).
///
/// Everything else (OAuth-only hosts, non-OpenAI/Anthropic providers, missing
/// credentials) displays nothing. Results are cached per instance for 5
/// minutes; a failed fetch caches as "unsupported" so the UI doesn't retry on
/// every body pass.
final class ProviderQuotaService: ObservableObject {
    static let shared = ProviderQuotaService()

    /// Bumped after every background refresh lands so SwiftUI views observing
    /// the service re-read `cachedQuota`.
    @Published private(set) var revision = 0

    struct QuotaInfo {
        let displayText: String
        /// True when remaining credit is low (official rule: below ~15 % of
        /// the limit, or under $3) — the model dot turns yellow.
        let highlighted: Bool
        /// [T-quota-newapi-balance] How this figure was obtained. Drives the
        /// badge tint and whether Settings offers the access-token hint.
        var kind: Kind = .used
        /// Real remaining balance in USD when known (`kind == .balance`).
        var balanceUSD: Double? = nil

        enum Kind {
            /// Provider-reported month-to-date spend (no trustworthy limit).
            case used
            /// Trustworthy remaining balance from New API `/api/user/self`.
            case balance
        }
    }

    /// [T-quota-newapi-balance] Per-site `quota_per_unit`, read from the
    /// public `/api/status` endpoint and cached for the process lifetime.
    /// 500,000 is the New API default and the value every relay we probed
    /// reports; a site that omits the field keeps that default.
    private static var quotaPerUnitCache: [String: Double] = [:]
    private static let quotaPerUnitLock = NSLock()
    private static let defaultQuotaPerUnit: Double = 500_000

    /// [T-quota-threshold] USD amount under which a real balance is flagged.
    /// User-adjustable in Settings (default $3). Only ever applied to
    /// `kind == .balance` — a usage-only figure has no scale to compare with,
    /// so flagging it low would be a guess.
    static let lowThresholdDefaultsKey = "quota.lowThresholdUSD"

    static var lowThresholdUSD: Double {
        let stored = UserDefaults.standard.object(forKey: lowThresholdDefaultsKey) as? Double
        guard let stored, stored >= 0 else { return 3.0 }
        return stored
    }

    private struct CacheEntry {
        let info: QuotaInfo?
        let fetchedAt: Date
    }

    private var cache: [String: CacheEntry] = [:]
    private let lock = NSLock()
    private let ttl: TimeInterval = 300

    // MARK: Sync read for UI

    /// [T-quota-stale-ok] Returns the last known figure even after `ttl`
    /// expires.
    ///
    /// Dropping it on expiry made the balance blink out of the title bar every
    /// five minutes and reappear a second later once the background refresh
    /// landed — indistinguishable from "the setting broke". A stale number is
    /// far less confusing than no number; `isMissing` is what decides whether a
    /// request should go out.
    func cachedQuota(instanceId: String) -> QuotaInfo? {
        lock.lock(); defer { lock.unlock() }
        return cache[instanceId]?.info
    }

    func isMissing(instanceId: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard let e = cache[instanceId] else { return true }
        return Date().timeIntervalSince(e.fetchedAt) >= ttl
    }

    /// Drops one instance's cached quota so the next read refetches. Called
    /// after the balance access token or the site login changes.
    func invalidate(instanceId: String) {
        lock.lock()
        cache.removeValue(forKey: instanceId)
        lock.unlock()
        Task { @MainActor in self.revision += 1 }
    }

    // MARK: Async fetch + cache

    func refreshQuota(for instance: ProviderInstance) async {
        let info = await Self.fetchQuota(for: instance)
        lock.lock()
        cache[instance.id] = CacheEntry(info: info, fetchedAt: Date())
        lock.unlock()
    }

    func refreshAllIfNeeded(instances: [ProviderInstance]) {
        let missing = instances.filter { isMissing(instanceId: $0.id) }
        guard !missing.isEmpty else { return }
        Task {
            for instance in missing {
                await refreshQuota(for: instance)
            }
            await MainActor.run { self.revision += 1 }
        }
    }

    // MARK: Fetch

    static func fetchQuota(for instance: ProviderInstance) async -> QuotaInfo? {
        guard instance.isEnabled else { return nil }
        // Only API-key instances: the billing endpoints are key-authenticated
        // (OAuth/manual-token flows have no stable way to reach them).
        let key: String?
        switch instance.credentialType {
        case .apiKey:
            key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)
        default:
            key = nil
        }
        guard let key, !key.isEmpty else { return nil }

        var base = instance.effectiveCustomBaseURL
        if base == nil {
            switch instance.providerType {
            case .openAI, .openAIResponses: base = "https://api.openai.com"
            case .anthropic: base = "https://api.anthropic.com"
            default: return nil
            }
        }
        guard var base else { return nil }
        base = base.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if instance.appendV1Suffix && !base.hasSuffix("/v1") { base += "/v1" }

        switch instance.providerType {
        case .openAI, .openAIResponses:
            return await fetchOpenAIQuota(
                instanceId: instance.id,
                key: key,
                baseURL: base
            )
        case .anthropic:
            return await fetchAnthropicSpend(key: key, baseURL: base)
        default:
            return nil
        }
    }

    private static func fetchOpenAIQuota(instanceId: String, key: String, baseURL: String) async -> QuotaInfo? {
        let session = URLSession.shared

        // 0) [T-quota-newapi-balance] New API / One API relays expose the REAL
        // remaining balance at `GET {root}/api/user/self`, authenticated either
        // by a user access token (preferred — it never expires) or by the
        // logged-in web session cookies (fallback). Their OpenAI-compatible
        // billing endpoints are implemented with a placeholder limit (1e8), so
        // this is the only way to report a truthful "余额".
        if let balance = await fetchNewAPIBalance(instanceId: instanceId, baseURL: baseURL) {
            return balance
        }

        // 1) Subscription -> hard/soft limit.
        guard let subURL = URL(string: baseURL + "/dashboard/billing/subscription") else { return nil }
        var subReq = URLRequest(url: subURL)
        subReq.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        subReq.timeoutInterval = 12
        var hardLimit: Double?
        do {
            let (data, resp) = try await session.data(for: subReq)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return nil // relay without the billing endpoint
            }
            hardLimit = (obj["hard_limit_usd"] as? NSNumber)?.doubleValue
                ?? (obj["soft_limit_usd"] as? NSNumber)?.doubleValue
        } catch {
            return nil
        }

        // 2) Usage since the 1st of the month (cents).
        let now = Date()
        let cal = Calendar.current
        var comps = cal.dateComponents([.year, .month], from: now)
        comps.day = 1
        let start = cal.date(from: comps) ?? now.addingTimeInterval(-30 * 86400)
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd"
        guard var usageComps = URLComponents(string: baseURL + "/dashboard/billing/usage") else { return nil }
        usageComps.queryItems = [
            URLQueryItem(name: "start_date", value: df.string(from: start)),
            URLQueryItem(name: "end_date", value: df.string(from: now)),
        ]
        guard let usageURL = usageComps.url else { return nil }
        var useReq = URLRequest(url: usageURL)
        useReq.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        useReq.timeoutInterval = 12
        var totalUsed: Double?
        if let (data, resp) = try? await session.data(for: useReq),
           let http = resp as? HTTPURLResponse, http.statusCode == 200,
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let cents = obj["total_usage"] as? NSNumber {
            totalUsed = cents.doubleValue / 100.0
        }

        // A successful subscription response alone is not enough to claim a
        // full balance: a missing/failed usage endpoint means the balance is
        // unknown, especially for relays that only implement one endpoint.
        guard let totalUsed else { return nil }
        // [T-quota-relay-placeholder] Relays fake the OpenAI billing endpoint by
        // returning a huge `hard_limit_usd` (commonly 100000000) meaning
        // "unlimited". Subtracting real usage from that placeholder produced
        // "剩 $99999977.88" on every relay — a number with no meaning, since a
        // real OpenAI cap is tens/hundreds/thousands, never millions. Above the
        // ceiling we report the only truthful figure the endpoint gives us
        // (month-to-date usage) instead of a fabricated remainder, and never
        // flag it low (we cannot know).
        if let hardLimit, hardLimit > 0, hardLimit < Self.relayPlaceholderLimitUSD {
            let remaining = hardLimit - totalUsed
            // [T-quota-threshold-only] The user sets the cut-off; a second
            // automatic "below 15 % of the limit" rule fought it. If you set
            // $1, you mean $1 — a $200 cap quietly turning $30 yellow is the
            // app second-guessing a number the user already chose.
            let low = remaining < Self.lowThresholdUSD
            // [T-quota-remaining-is-balance] This is a real remainder (a real
            // cap minus real usage), so treat it like one: say 余额 like the
            // New API path and carry `.balance` so it gets the green/yellow
            // treatment. Leaving `kind` at its `.used` default made it the odd
            // one out in the UI — grey text saying 剩 while every other
            // readable site said 余额 in green.
            return QuotaInfo(displayText: String(format: "余额 $%.2f", max(remaining, 0)),
                             highlighted: low,
                             kind: .balance,
                             balanceUSD: max(remaining, 0))
        }
        if totalUsed > 0.001 {
            return QuotaInfo(
                displayText: String(format: "已用 $%.2f", totalUsed),
                highlighted: false,
                kind: .used
            )
        }
        return nil
    }

    /// Above this `hard_limit_usd` the value cannot be a real OpenAI spending
    /// cap, so it is treated as a relay's "unlimited" placeholder. $1,000,000
    /// sits far above any genuine per-account cap and far below the 1e8 values
    /// relays actually send.
    static let relayPlaceholderLimitUSD: Double = 1_000_000

    // MARK: - [T-quota-newapi-balance] New API real balance

    /// Strips the OpenAI-compatible `/v1` suffix so the New API management
    /// endpoints (`/api/status`, `/api/user/self`) sit on the site root.
    static func apiRoot(_ baseURL: String) -> String {
        var root = baseURL
        if root.hasSuffix("/v1") { root = String(root.dropLast(3)) }
        while root.hasSuffix("/") { root = String(root.dropLast()) }
        return root
    }

    /// `GET {root}/api/user/self` — the only source of a trustworthy remaining
    /// balance on New API / One API relays. Authenticated by the user's access
    /// token when one is saved; otherwise by the site's login cookies if the
    /// user signed in through the in-app browser. Returns nil for non-New-API
    /// sites or when neither credential exists, and the caller falls back to
    /// the usage-only display.
    private static func fetchNewAPIBalance(instanceId: String, baseURL: String) async -> QuotaInfo? {
        let root = apiRoot(baseURL)
        guard let url = URL(string: root + "/api/user/self") else { return nil }

        var req = URLRequest(url: url)
        req.timeoutInterval = 12

        if let token = ProviderKeychainHelper.loadQuotaAccessToken(instanceId: instanceId),
           !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        } else if let cookie = await sessionCookieHeader(for: root) {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        } else {
            return nil
        }

        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        // New API wraps payloads in "data"; some forks answer flat.
        let body = (obj["data"] as? [String: Any]) ?? obj
        guard let quota = body["quota"] as? NSNumber else { return nil }

        let perUnit = await quotaPerUnit(root: root)
        let balance = quota.doubleValue / perUnit
        return QuotaInfo(
            displayText: String(format: "余额 $%.2f", balance),
            highlighted: balance < lowThresholdUSD,
            kind: .balance,
            balanceUSD: balance
        )
    }

    /// `1 USD = quota_per_unit` points, published by every New API site at
    /// `/api/status`. Cached per root; 500,000 is the upstream default.
    static func quotaPerUnit(root: String) async -> Double {
        quotaPerUnitLock.lock()
        if let cached = quotaPerUnitCache[root] {
            quotaPerUnitLock.unlock()
            return cached
        }
        quotaPerUnitLock.unlock()

        var unit = defaultQuotaPerUnit
        if let url = URL(string: root + "/api/status"),
           let (data, resp) = try? await URLSession.shared.data(from: url),
           let http = resp as? HTTPURLResponse, http.statusCode == 200,
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let payload = obj["data"] as? [String: Any],
           let qpu = payload["quota_per_unit"] as? NSNumber,
           qpu.doubleValue > 0 {
            unit = qpu.doubleValue
        }

        quotaPerUnitLock.lock()
        quotaPerUnitCache[root] = unit
        quotaPerUnitLock.unlock()
        return unit
    }

    /// Cookies for `root`'s host from the app's own WKWebView store. This is
    /// the SAME store the in-app browser uses, so signing in through
    /// `ProviderQuotaLoginView` makes the balances readable without the user
    /// ever copying a token. Safari's cookies are unreachable by design.
    static func sessionCookieHeader(for root: String) async -> String? {
        guard let host = URL(string: root)?.host else { return nil }
        // WKWebsiteDataStore is main-thread-bound; hop explicitly.
        let cookies: [HTTPCookie] = await withCheckedContinuation { continuation in
            DispatchQueue.main.async {
                WKWebsiteDataStore.default().httpCookieStore.getAllCookies { all in
                    continuation.resume(returning: all)
                }
            }
        }
        let relevant = cookies.filter { cookie in
            var domain = cookie.domain
            if domain.hasPrefix(".") { domain = String(domain.dropFirst()) }
            return host == domain || host.hasSuffix("." + domain)
        }
        guard !relevant.isEmpty else { return nil }
        return relevant.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
    }

    /// Whether this site currently has a usable balance credential (token or
    /// login cookies). Drives the "未登录/未填写" state in Settings.
    static func hasBalanceCredential(instanceId: String) async -> Bool {
        if let token = ProviderKeychainHelper.loadQuotaAccessToken(instanceId: instanceId),
           !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return true
        }
        return false
    }

    private static func fetchAnthropicSpend(key: String, baseURL: String) async -> QuotaInfo? {
        // Anthropic has no public billing-limit endpoint; report month-to-date
        // spend from the org usage/costs API when available.
        let calendar = Calendar.current
        let now = Date()
        var monthComponents = calendar.dateComponents([.year, .month], from: now)
        monthComponents.day = 1
        guard let start = calendar.date(from: monthComponents),
              var comps = URLComponents(string: baseURL + "/organizations/usage/costs") else { return nil }
        comps.queryItems = [
            URLQueryItem(name: "starting_at", value: ISO8601DateFormatter().string(from: start)),
            URLQueryItem(name: "ending_at", value: ISO8601DateFormatter().string(from: now)),
            URLQueryItem(name: "limit", value: "1"),
        ]
        guard let url = comps.url else { return nil }
        var req = URLRequest(url: url)
        req.setValue(key, forHTTPHeaderField: "x-api-key")
        req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        req.timeoutInterval = 12
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let breakdown = obj["cost_breakdown"] as? [String: Any],
              let samples = breakdown["samples"] as? [[String: Any]],
              let first = samples.first,
              let cost = first["cost"] as? [String: Any] else {
            return nil
        }
        let usd = cost["usd"] as? Double ?? 0
        if usd > 0.001 {
            return QuotaInfo(displayText: String(format: "本月 $%.2f", usd), highlighted: false)
        }
        return nil
    }
}