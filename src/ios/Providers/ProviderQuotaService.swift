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
        /// [T-quota-multikey-perkey] The figure itself in USD, for whichever
        /// kind this is — remaining for `.balance`, month-to-date spend for
        /// `.used`. Added so the per-key rows can print a right-aligned number
        /// (`$0.86`) instead of re-parsing `displayText`, which carries the
        /// localized prefix and cannot be turned back into a value reliably.
        var amountUSD: Double? = nil

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

    /// [T-quota-panel-host] Where the BALANCE lives, when that is not the API
    /// host.
    ///
    /// Relays routinely split them: one user's site answers chat completions at
    /// `wapi.wintoken.ai` and its panel at `cun.ai` — `/api/user/self` on the
    /// API host is 403 while the same path on the panel host is the real
    /// endpoint. Without this field the query can only ever fall back to the
    /// OpenAI billing pair, which reports month-to-date SPEND (「已用 $7.42」)
    /// even though the dashboard shows a remaining balance (「$0.8808」).
    ///
    /// Stored per instance in UserDefaults: it is a URL, not a secret.
    static func panelBaseURL(instanceId: String) -> String? {
        let raw = UserDefaults.standard.string(forKey: "quota.panelBaseURL.\(instanceId)") ?? ""
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func setPanelBaseURL(_ url: String, instanceId: String) {
        let normalized = normalizePanelURL(url) ?? ""
        UserDefaults.standard.set(normalized, forKey: "quota.panelBaseURL.\(instanceId)")
        shared.invalidate(instanceId: instanceId)
    }

    /// Reduce whatever the user pasted to scheme + host + port.
    ///
    /// Reported 2026-10-21: the field held
    /// `https://www.cun.ai/profile` — a full page URL copied from the browser —
    /// so the balance request became `…/profile/api/user/self` and 404'd. A
    /// panel address is a HOST, not a page; anything after the host is dropped,
    /// and a bare `cun.ai` gets an https scheme so it is a usable URL.
    static func normalizePanelURL(_ raw: String) -> String? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.lowercased().hasPrefix("http://"), !text.lowercased().hasPrefix("https://") {
            text = "https://" + text
        }
        guard let parsed = URL(string: text), let host = parsed.host, !host.isEmpty else { return nil }
        var comps = URLComponents()
        comps.scheme = parsed.scheme ?? "https"
        comps.host = host
        comps.port = parsed.port
        return comps.url?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    /// [T-quota-newapi-user] `New-Api-User` header value.
    ///
    /// New API's `/api/user/self` rejects an otherwise valid access token with
    /// 「Unauthorized, New-Api-User header not provided」 unless the numeric user
    /// id rides along in a header of that name. The id is printed on the site's
    /// own dashboard ("用户 ID"), so it is one number the user copies once.
    static func userID(instanceId: String) -> String? {
        let raw = UserDefaults.standard.string(forKey: "quota.newAPIUserID.\(instanceId)") ?? ""
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func setUserID(_ value: String, instanceId: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(trimmed, forKey: "quota.newAPIUserID.\(instanceId)")
        shared.invalidate(instanceId: instanceId)
    }

    /// Root for the balance endpoints: the configured panel host when present,
    /// else the API host with `/v1` stripped.
    static func balanceRoot(instanceId: String, apiBase: String) -> String {
        if let stored = panelBaseURL(instanceId: instanceId),
           let panel = normalizePanelURL(stored) {
            return panel
        }
        return apiRoot(apiBase)
    }

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

    // MARK: - [T-quota-multikey-perkey] One row per key

    /// One line in the detail page's 余额 section: the credential key, or one
    /// key out of the rotation ring.
    ///
    /// The app has TWO key stores and they are not the same thing: `凭证`'s
    /// single Keychain key (the "主 Key", the fallback when every ring key is
    /// parked) and the multi-key ring. Balance used to be fetched for the
    /// credential only, so with 多 Key 模式 on, the number on screen belonged to
    /// a key that was not serving the requests. These rows make the ownership
    /// explicit instead of picking a winner.
    struct KeyQuota: Identifiable {
        /// `main`, or the ring key's own UUID. Stable across refreshes.
        let id: String
        /// "主 Key" / "轮询 1".
        let title: String
        /// Short glyph inside the leading badge: "主" for the credential key,
        /// the rotation index for a ring key.
        let badge: String
        /// Head…tail only — a key never reaches the UI whole.
        let masked: String
        let isMain: Bool
        /// `nil` means "not answered": never queried, or queried and the site
        /// has no balance endpoint.
        var info: QuotaInfo? = nil
        /// When this row was last queried. nil = never (the row then reads
        /// 未查询 rather than pretending the key has no balance).
        var queriedAt: Date? = nil

        var isUnavailable: Bool { info == nil && queriedAt != nil }
    }

    /// Per-instance per-row results, keyed by `KeyQuota.id`.
    private var keyCache: [String: [String: CacheEntry]] = [:]

    /// [T-quota-failure-reason] WHY the last attempt produced nothing.
    ///
    /// "未获取" was the whole answer the UI could give, which is useless for
    /// deciding whether the site does not support balances, the credential is
    /// missing, or the endpoint answered 404 — the three cases look identical
    /// on screen and need completely different actions from the user.
    private var failureNotes: [String: String] = [:]

    private func failureKey(_ instanceId: String, _ rowId: String) -> String {
        "\(instanceId)|\(rowId)"
    }

    /// Recorded explanation for the last failed attempt of one key, if any.
    func failureNote(instanceId: String, rowId: String = "main") -> String? {
        lock.lock(); defer { lock.unlock() }
        return failureNotes[failureKey(instanceId, rowId)]
    }

    func noteFailure(_ text: String, instanceId: String, rowId: String = "main") {
        lock.lock()
        failureNotes[failureKey(instanceId, rowId)] = text
        lock.unlock()
    }

    func clearFailure(instanceId: String, rowId: String = "main") {
        lock.lock()
        failureNotes.removeValue(forKey: failureKey(instanceId, rowId))
        lock.unlock()
    }

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
        // [T-quota-multikey-perkey] A provider in 多 Key 模式 is left ALONE
        // here. Its request-serving key is whichever ring key the rotation
        // picks, so an automatic single-key fetch would paint the credential
        // key's number next to a provider that is being billed elsewhere — a
        // wrong answer is worse than a blank one. Those providers are refreshed
        // only when the user asks, from the detail page.
        let missing = instances
            .filter { !ProviderMultiKeyManager.shared.isEnabled(for: $0.id) }
            .filter { isMissing(instanceId: $0.id) }
        guard !missing.isEmpty else { return }
        Task {
            for instance in missing {
                await refreshQuota(for: instance)
            }
            await MainActor.run { self.revision += 1 }
        }
    }

    // MARK: - [T-quota-multikey-perkey] Per-key rows

    /// The rows to draw for `instance`, in display order: the credential key
    /// first, then the ring (numbered by ring order). Values come from the last
    /// query; nothing is fetched here — a list body must never start network
    /// work, and the user explicitly asked for manual refresh only.
    func quotaRows(for instance: ProviderInstance) -> [KeyQuota] {
        var rows: [KeyQuota] = []

        if let main = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id),
           !main.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            var row = KeyQuota(id: "main", title: AppLocalized("主 Key"),
                               badge: AppLocalized("主"),
                               masked: Self.mask(main), isMain: true)
            attach(&row, instanceId: instance.id)
            rows.append(row)
        }

        guard ProviderMultiKeyManager.shared.isEnabled(for: instance.id) else { return rows }
        let ring = ProviderMultiKeyManager.shared.keys(for: instance.id)
        for (index, key) in ring.enumerated() {
            var row = KeyQuota(id: key.id,
                               title: String(format: AppLocalized("轮询 %lld"), Int64(index + 1)),
                               badge: "\(index + 1)",
                               masked: key.masked,
                               isMain: false)
            attach(&row, instanceId: instance.id)
            rows.append(row)
        }
        return rows
    }

    private func attach(_ row: inout KeyQuota, instanceId: String) {
        lock.lock()
        let entry = keyCache[instanceId]?[row.id]
        lock.unlock()
        row.info = entry?.info
        row.queriedAt = entry?.fetchedAt
    }

    /// `sk-abc…7f2a` — same head/tail rule the ring uses, so the two kinds of
    /// key read identically in the list.
    static func mask(_ key: String) -> String {
        guard key.count > 14 else { return String(repeating: "•", count: 10) }
        return key.prefix(6) + "…" + key.suffix(4)
    }

    /// Query EVERY key of this provider — credential key and every ring key —
    /// concurrently, publishing each result as it lands.
    ///
    /// Manual on purpose: this is the only place N requests are spent, and it
    /// runs because the user tapped 测试并刷新余额. Concurrency matters here:
    /// serially, four slow relays would stall the button for a minute.
    func refreshAllKeys(for instance: ProviderInstance) async {
        let rows = quotaRows(for: instance)
        guard !rows.isEmpty else { return }

        // Resolve each row id to the secret it stands for. The ring is read
        // again (not carried from `rows`) because `KeyQuota` deliberately holds
        // the masked form only.
        var secrets: [String: String] = [:]
        if let main = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) {
            secrets["main"] = main
        }
        for key in ProviderMultiKeyManager.shared.keys(for: instance.id) {
            secrets[key.id] = key.key
        }

        await withTaskGroup(of: (String, QuotaInfo?).self) { group in
            for row in rows {
                guard let secret = secrets[row.id] else { continue }
                group.addTask {
                    let info = await Self.fetchQuota(for: instance, key: secret, rowId: row.id)
                    return (row.id, info)
                }
            }
            for await (rowId, info) in group {
                let entry = CacheEntry(info: info, fetchedAt: Date())
                lock.lock()
                keyCache[instance.id, default: [:]][rowId] = entry
                lock.unlock()
                if let info {
                    AppLogger(category: "Quota").info(
                        "[Quota][perKey] instance=\(instance.id.prefix(8)) row=\(rowId.prefix(8)) "
                        + "kind=\(info.kind) text=\(info.displayText)")
                } else {
                    AppLogger(category: "Quota").info(
                        "[Quota][perKey] instance=\(instance.id.prefix(8)) row=\(rowId.prefix(8)) unavailable")
                }
                await MainActor.run { self.revision += 1 }
            }
        }

        publishAggregate(for: instance.id)
        await MainActor.run { self.revision += 1 }
    }

    /// Roll the per-key answers into the ONE figure the rest of the app reads
    /// (list row, picker, composer capsule): the LOWEST real balance, so a
    /// nearly-spent key cannot hide behind a healthy sibling. Falls back to the
    /// credential key's usage-only figure when no site gives a real balance.
    private func publishAggregate(for instanceId: String) {
        lock.lock()
        let entries = keyCache[instanceId] ?? [:]
        lock.unlock()
        guard !entries.isEmpty else { return }

        let balances: [Double] = entries.values.compactMap { entry in
            guard let info = entry.info, info.kind == .balance else { return nil }
            return info.balanceUSD
        }
        let aggregate: QuotaInfo?
        if let lowest = balances.min() {
            aggregate = QuotaInfo(
                displayText: String(format: "余额 $%.2f", lowest),
                highlighted: lowest < Self.lowThresholdUSD,
                kind: .balance,
                balanceUSD: lowest,
                amountUSD: lowest)
        } else {
            aggregate = entries["main"]?.info
        }
        guard let aggregate else { return }
        lock.lock()
        cache[instanceId] = CacheEntry(info: aggregate, fetchedAt: Date())
        lock.unlock()
    }

    // MARK: Fetch

    static func fetchQuota(for instance: ProviderInstance) async -> QuotaInfo? {
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
        return await fetchQuota(for: instance, key: key)
    }

    /// [T-quota-multikey-perkey] Same query, but for ONE explicit key.
    ///
    /// The per-key rows are the reason this exists: each line in the detail
    /// page asks about its own key, so the answer can no longer be implied by
    /// the instance id. Everything below — endpoint choice, placeholder
    /// handling, threshold — is shared with the single-key path on purpose;
    /// two implementations would drift.
    /// - Parameter rowId: which key of the provider this query is for —
    ///   `main`, or a ring key's UUID. Selects that key's own access token
    ///   ([T-quota-perkey-token]) and falls back to the instance-wide one.
    static func fetchQuota(for instance: ProviderInstance, key: String,
                           rowId: String = "main") async -> QuotaInfo? {
        guard instance.isEnabled else { return nil }
        guard !key.isEmpty else { return nil }

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
                baseURL: base,
                rowId: rowId
            )
        case .anthropic:
            return await fetchAnthropicSpend(key: key, baseURL: base)
        default:
            return nil
        }
    }

    private static func fetchOpenAIQuota(instanceId: String, key: String, baseURL: String,
                                        rowId: String) async -> QuotaInfo? {
        // [T-quota-balance-priority] Restore the saved access-token path FIRST.
        // /api/usage/token/ can succeed with usage only (an unlimited API key).
        // Returning that early skipped the user's configured balance token.
        // Keep rowId: each ring key may belong to a different account.
        if let balance = await fetchNewAPIBalance(instanceId: instanceId, baseURL: baseURL,
                                                 rowId: rowId) {
            return balance
        }

        // A real key balance is useful when the account query is unavailable.
        // Usage is only a fallback: it must not hide a real billing balance.
        let keyQuota = await fetchKeyUsage(key: key, baseURL: baseURL)
        if let keyQuota, keyQuota.kind == .balance {
            return keyQuota
        }

        let billingQuota = await fetchOpenAIBillingQuota(key: key, baseURL: baseURL)
        if let billingQuota, billingQuota.kind == .balance {
            return billingQuota
        }

        // Every supported balance path was tried. Preserve successful key
        // usage even if billing is unsupported or fails, then month-to-date
        // billing usage as the last resort. Both nil means unavailable.
        return keyQuota ?? billingQuota
    }

    /// Existing OpenAI billing pair, isolated so its failure cannot discard
    /// usage already obtained by the caller. Parsing and thresholds unchanged.
    private static func fetchOpenAIBillingQuota(key: String, baseURL: String) async -> QuotaInfo? {
        let session = URLSession.shared

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
                             balanceUSD: max(remaining, 0),
                             amountUSD: max(remaining, 0))
        }
        if totalUsed > 0.001 {
            return QuotaInfo(
                displayText: String(format: "已用 $%.2f", totalUsed),
                highlighted: false,
                kind: .used,
                amountUSD: totalUsed
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
    private static func fetchNewAPIBalance(instanceId: String, baseURL: String,
                                           rowId: String) async -> QuotaInfo? {
        // [T-quota-panel-host] Panel host wins when the user set one — see
        // `panelBaseURL` for the split-host case this exists for.
        let root = balanceRoot(instanceId: instanceId, apiBase: baseURL)
        guard let url = URL(string: root + "/api/user/self") else { return nil }

        var req = URLRequest(url: url)
        req.timeoutInterval = 12

        // [T-quota-perkey-token] This key's own token first; the instance-wide
        // token is the fallback for a single-account setup.
        if let token = ProviderKeychainHelper.resolvedQuotaAccessToken(instanceId: instanceId, keyId: rowId),
           !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            // [T-quota-newapi-user] Required by New API alongside the token.
            if let uid = userID(instanceId: instanceId) {
                req.setValue(uid, forHTTPHeaderField: "New-Api-User")
            }
        } else if let cookie = await sessionCookieHeader(for: root) {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        } else {
            ProviderQuotaService.shared.noteFailure(
                AppLocalized("没有凭据：没填访问令牌，也没在这个站点登录过"), instanceId: instanceId, rowId: rowId)
            return nil
        }

        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse else {
            ProviderQuotaService.shared.noteFailure(
                AppLocalized("连不上这个站点（网络或证书问题，也可能被代理拦了）"), instanceId: instanceId, rowId: rowId)
            return nil
        }
        guard http.statusCode == 200 else {
            // [T-quota-diag] Log the status AND the body prefix: New API forks
            // answer 401 with a message that names the missing piece (e.g.
            // 「New-Api-User header not provided」), which is the only way to
            // tell a wrong token from a missing header without a debugger.
            AppLogger(category: "Quota").error(
                "[Quota][newapi] \(root)/api/user/self → HTTP \(http.statusCode) body=\(String(data: data.prefix(240), encoding: .utf8) ?? "<binary>")")
            let bodyText = String(data: data.prefix(240), encoding: .utf8) ?? ""
            if bodyText.lowercased().contains("new-api-user") {
                ProviderQuotaService.shared.noteFailure(
                    AppLocalized("这个站还要求填「用户 ID」（在它后台的个人设置里）"),
                    instanceId: instanceId, rowId: rowId)
            } else {
                ProviderQuotaService.shared.noteFailure(
                    String(format: AppLocalized("站点返回 HTTP %lld（这个路径可能不存在）"), Int64(http.statusCode)),
                    instanceId: instanceId, rowId: rowId)
            }
            return nil
        }
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            ProviderQuotaService.shared.noteFailure(
                AppLocalized("返回的不是 JSON（可能不是一个 API 站）"), instanceId: instanceId, rowId: rowId)
            return nil
        }
        // New API wraps payloads in "data"; some forks answer flat.
        let body = (obj["data"] as? [String: Any]) ?? obj
        guard let quota = body["quota"] as? NSNumber else {
            AppLogger(category: "Quota").error(
                "[Quota][newapi] \(root)/api/user/self → 200 but no quota field; keys=\(body.keys.sorted().prefix(12)) body=\(String(data: data.prefix(240), encoding: .utf8) ?? "")")
            ProviderQuotaService.shared.noteFailure(
                AppLocalized("返回里没有 quota 字段（这站可能不是 New API 面板）"), instanceId: instanceId, rowId: rowId)
            return nil
        }
        ProviderQuotaService.shared.clearFailure(instanceId: instanceId, rowId: rowId)

        let perUnit = await quotaPerUnit(root: root)
        let balance = quota.doubleValue / perUnit
        AppLogger(category: "Quota").info(
            "[Quota][newapi] \(root)/api/user/self OK quota=\(quota.doubleValue) perUnit=\(perUnit) balance=\(balance)")
        return QuotaInfo(
            displayText: String(format: "余额 $%.2f", balance),
            highlighted: balance < lowThresholdUSD,
            kind: .balance,
            balanceUSD: balance,
            amountUSD: balance
        )
    }

    /// `GET {root}/api/usage/token/` — the balance of ONE API key.
    ///
    /// Response shape (New API / One API): `{ "data": { "total_granted": …,
    /// "total_used": …, "total_available": … } }` in quota points. Anything
    /// else — 401, HTML, a different panel — returns nil so the caller can try
    /// the next strategy, and the UI simply shows no balance.
    private static func fetchKeyUsage(key: String, baseURL: String) async -> QuotaInfo? {
        let root = apiRoot(baseURL)
        guard let url = URL(string: root + "/api/usage/token/") else { return nil }
        var req = URLRequest(url: url)
        req.timeoutInterval = 12
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")

        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let body = obj["data"] as? [String: Any] else {
            return nil
        }

        let available = (body["total_available"] as? NSNumber)?.doubleValue
        let granted = (body["total_granted"] as? NSNumber)?.doubleValue
        let used = (body["total_used"] as? NSNumber)?.doubleValue
        let unlimited = (body["unlimited_quota"] as? Bool) ?? false
        let perUnit = await quotaPerUnit(root: root)

        // [T-quota-key-usage] An UNLIMITED key has no remaining balance to
        // report — `total_available` is negative by design. The honest figure
        // is the usage, and saying so is better than drawing "余额 -$7.42" or
        // showing nothing at all: this path needs the key the user already
        // pasted, which is the whole point.
        if unlimited {
            let spent = (used ?? 0) / perUnit
            AppLogger(category: "Quota").info(
                "[Quota][keyusage] \(root) unlimited quota used=\(used ?? 0) spent=\(spent)")
            // [T-quota-key-usage] No 「不限量」 wording: the user asked for it
            // gone. An unlimited key simply reports what it has spent — the
            // same 「已用 $X」 the billing fallback produces, so both paths read
            // identically and the per-key rows inherit it for free.
            return QuotaInfo(
                displayText: String(format: "已用 $%.2f", spent),
                highlighted: false,
                kind: .used,
                amountUSD: spent)
        }

        let quotaPoints: Double? = available ?? {
            guard let granted, let used else { return nil }
            return max(0, granted - used)
        }()
        guard let quotaPoints else { return nil }

        let balance = quotaPoints / perUnit
        AppLogger(category: "Quota").info(
            "[Quota][keyusage] \(root)/api/usage/token/ OK available=\(quotaPoints) perUnit=\(perUnit) balance=\(balance)")
        return QuotaInfo(
            displayText: String(format: "余额 $%.2f", balance),
            highlighted: balance < lowThresholdUSD,
            kind: .balance,
            balanceUSD: balance,
            amountUSD: balance)
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
            return QuotaInfo(displayText: String(format: "本月 $%.2f", usd),
                             highlighted: false,
                             amountUSD: usd)
        }
        return nil
    }
}