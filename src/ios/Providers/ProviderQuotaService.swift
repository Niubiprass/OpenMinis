import Foundation

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
    }

    private struct CacheEntry {
        let info: QuotaInfo?
        let fetchedAt: Date
    }

    private var cache: [String: CacheEntry] = [:]
    private let lock = NSLock()
    private let ttl: TimeInterval = 300

    // MARK: Sync read for UI

    func cachedQuota(instanceId: String) -> QuotaInfo? {
        lock.lock(); defer { lock.unlock() }
        guard let e = cache[instanceId] else { return nil }
        guard Date().timeIntervalSince(e.fetchedAt) < ttl else { return nil }
        return e.info
    }

    func isMissing(instanceId: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard let e = cache[instanceId] else { return true }
        return Date().timeIntervalSince(e.fetchedAt) >= ttl
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
            return await fetchOpenAIQuota(key: key, baseURL: base)
        case .anthropic:
            return await fetchAnthropicSpend(key: key, baseURL: base)
        default:
            return nil
        }
    }

    private static func fetchOpenAIQuota(key: String, baseURL: String) async -> QuotaInfo? {
        let session = URLSession.shared

        // 1) Subscription -> hard/soft limit.
        guard let subURL = URL(string: baseURL + "/dashboard/billing/subscription") else { return nil }
        var subReq = URLRequest(url: subURL)
        subReq.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        subReq.timeoutInterval = 12
        var hardLimit: Double?
        var softLimit: Double?
        do {
            let (data, resp) = try await session.data(for: subReq)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return nil // relay without the billing endpoint
            }
            hardLimit = (obj["hard_limit_usd"] as? NSNumber)?.doubleValue
                ?? (obj["soft_limit_usd"] as? NSNumber)?.doubleValue
            softLimit = (obj["soft_limit_usd"] as? NSNumber)?.doubleValue
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
            let limit = softLimit ?? hardLimit
            let low = remaining < 3.0 || remaining < limit * 0.15
            return QuotaInfo(displayText: String(format: "剩 $%.2f", max(remaining, 0)), highlighted: low)
        }
        if totalUsed > 0.001 {
            return QuotaInfo(displayText: String(format: "已用 $%.2f", totalUsed), highlighted: false)
        }
        return nil
    }

    /// Above this `hard_limit_usd` the value cannot be a real OpenAI spending
    /// cap, so it is treated as a relay's "unlimited" placeholder. $1,000,000
    /// sits far above any genuine per-account cap and far below the 1e8 values
    /// relays actually send.
    static let relayPlaceholderLimitUSD: Double = 1_000_000

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