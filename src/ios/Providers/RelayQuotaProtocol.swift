import Foundation
import CoreFoundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Adapted from the pinned official RelayQuotaAdapter (1291–1520), QuotaModels
/// and QuotaRules. Foundation only: no Keychain, UI, storage or live probing.
enum RelayQuotaProtocol {
    enum Source: String, CaseIterable {
        case sub2api, newAPIKey, openAIBilling, newAPIAccount, anthropic
        var path: String {
            switch self {
            case .sub2api: return "/v1/usage"
            case .newAPIKey: return "/api/usage/token/"
            case .openAIBilling: return "/v1/dashboard/billing/subscription"
            case .newAPIAccount: return "/api/user/self"
            case .anthropic: return "/v1/organizations/usage/costs"
            }
        }
        static let probeOrder: [Source] = [.sub2api, .newAPIKey, .openAIBilling]
    }
    enum Scope: String { case accountBalance, keyQuota, subscription, spendingLimit, usage }
    enum Unit: Equatable {
        case currency(String), quota
        var label: String {
            switch self { case .currency(let code): return code; case .quota: return "quota" }
        }
        var isUSD: Bool { self == .currency("USD") }
    }
    struct Scale {
        let quotaPerUnit: Double
        let observedAt: Date
        let endpoint: String
    }
    struct Reading: Identifiable {
        var id: String { source.rawValue + ":" + scope.rawValue }
        let source: Source
        let scope: Scope
        let endpoint: String
        let relayHost: String
        let unit: Unit
        let unitEvidence: String
        let quotaPerUnit: Double?
        let scaleObservedAt: Date?
        var remaining: Double?
        var used: Double?
        var total: Double?
        var unlimited = false
        var rejected = false
        /// Free-form documented scope, not an inferred billing period.
        var usedLabel: String? = nil
        var usedEndpoint: String? = nil
        var usedObservedAt: Date? = nil
        /// Receipt time, never the time of a subsequent failed attempt.
        let observedAt: Date
        var refreshFailed = false
        func isStale(at now: Date = Date()) -> Bool {
            refreshFailed || now.timeIntervalSince(observedAt) >= 300
        }
        var hasAmounts: Bool { remaining != nil || used != nil || total != nil || unlimited || rejected }
        var label: String {
            switch scope {
            case .accountBalance: return "账户余额"
            case .keyQuota: return "Key 额度"
            case .subscription: return "套餐余量"
            case .spendingLimit: return "预算余量"
            case .usage: return "已用"
            }
        }
    }
    struct Attempt {
        let source: Source
        let endpoint: String
        let attemptedAt: Date
        let succeeded: Bool
        let failureNote: String?
        var probeMiss = false
    }

    /// One short line per non-primary pool, labelled by what it actually is.
    /// Amounts from different scopes are never added together: a wallet
    /// balance, a Key limit and a plan remainder are three different things.
    static func secondaryLine(_ readings: [Reading], primary: Reading?) -> String? {
        let others = readings.filter { reading in
            guard let primary else { return true }
            return reading.id != primary.id && !reading.rejected && reading.remaining != nil
        }
        guard !others.isEmpty else { return nil }
        return others.map { reading in
            let amount = self.amount(reading.remaining, unit: reading.unit)
            return "\(reading.label) \(amount)"
        }.joined(separator: " · ")
    }

    static func amount(_ value: Double?, unit: Unit) -> String {
        guard let value, value.isFinite, value >= 0 else { return "—" }
        if unit.isUSD { return String(format: "$%.2f", value) }
        let text = String(format: "%.2f", value)
        return unit.label == "quota" ? "\(text) quota" : "\(text) \(unit.label)"
    }

    /// Failure text for the pools that did not answer, without leaking bodies.
    static func failureLine(_ attempts: [Attempt]) -> String? {
        let failed = attempts.filter { !$0.succeeded && !$0.probeMiss }
        guard !failed.isEmpty else { return nil }
        var seen = Set<String>()
        let notes = failed.compactMap { attempt -> String? in
            guard let note = attempt.failureNote, seen.insert(note).inserted else { return nil }
            return note
        }
        return notes.isEmpty ? "\(failed.count) 个来源没有返回结果" : notes.joined(separator: "；")
    }
    struct Snapshot {
        /// Process-local digest of credential + roots + user ID; never a key.
        let owner: String
        var readings: [Reading]
        var attempts: [Attempt]
        var lastAttemptAt: Date? { attempts.map(\.attemptedAt).max() }
        var primary: Reading? { Self.primary(in: readings) }
        static func primary(in values: [Reading]) -> Reading? {
            func rank(_ r: Reading) -> Int {
                if r.rejected { return 90 }
                if r.remaining != nil {
                    switch r.scope {
                    case .accountBalance: return 0
                    case .keyQuota: return 1
                    case .subscription: return 2
                    case .spendingLimit: return 3
                    case .usage: break
                    }
                }
                if r.used != nil { return 10 }
                if r.unlimited { return 20 }
                return 30
            }
            return values.enumerated().min {
                let a = rank($0.element), b = rank($1.element)
                return a == b ? $0.offset < $1.offset : a < b
            }?.element
        }
        /// A failed source keeps its previous timestamp and amounts. A complete
        /// source replaces only its own pools (wallet -> subscription retires wallet).
        func merging(previous: Snapshot?) -> Snapshot {
            guard let previous, previous.owner == owner else { return self }
            let successful = Set(attempts.filter(\.succeeded).map(\.source))
            var result = self
            // An incomplete billing pair may identify its protocol but cannot
            // overwrite a previous complete reading with missing usage.
            let previousIDs = Set(previous.readings.map(\.id))
            result.readings.removeAll { $0.refreshFailed && previousIDs.contains($0.id) }
            let answeredRelay = successful.contains { Source.probeOrder.contains($0) }
            result.readings += previous.readings.filter {
                !successful.contains($0.source) && !(answeredRelay && Source.probeOrder.contains($0.source))
            }.map {
                var old = $0
                old.refreshFailed = true
                return old
            }
            return result
        }
        func isLow(thresholdUSD: Double, now: Date = Date()) -> Bool {
            readings.contains {
                !$0.rejected && !$0.unlimited && !$0.isStale(at: now) && $0.unit.isUSD
                    && ($0.remaining.map { $0 < thresholdUSD } ?? false)
            }
        }
    }
    enum Failure: Error {
        case invalidURL, unsupported, rejected, http(Int), transport, missingCredential, missingUserID
        var note: String {
            switch self {
            case .invalidURL: return "站点地址无效"
            case .unsupported: return "返回里没有可识别的额度字段"
            case .rejected: return "余额接口拒绝：访问令牌无效或权限不足"
            case .http(404): return "站点没有余额查询接口（不影响对话）"
            case .http(let code): return "额度接口返回 HTTP \(code)"
            case .transport: return "连不上这个站点（网络或证书问题，也可能被代理拦了）"
            case .missingCredential: return "没有凭据：没填访问令牌，也没在这个站点登录过"
            case .missingUserID: return "这个站还要求填「用户 ID」；点这把 Key 填上（在站点后台个人设置里）"
            }
        }
    }

    static func root(_ raw: String) -> String? {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") { value.removeLast() }
        if value.lowercased().hasSuffix("/v1") { value.removeLast(3) }
        while value.hasSuffix("/") { value.removeLast() }
        guard let c = URLComponents(string: value),
              c.scheme == "https" || c.scheme == "http", c.host?.isEmpty == false,
              c.user == nil, c.password == nil, c.query == nil, c.fragment == nil else { return nil }
        return value
    }
    static func endpoint(root: String, path: String) -> URL? {
        guard let base = Self.root(root), path.hasPrefix("/"), !path.hasPrefix("//") else { return nil }
        return URL(string: base + path)
    }
    /// Strict full-string validation; JSON booleans, NaN, infinity and numeric
    /// prefixes such as "12USD" must never become amounts.
    static func number(_ value: Any?) -> Double? {
        let text: String
        if let s = value as? String { text = s.trimmingCharacters(in: .whitespacesAndNewlines) }
        else if let n = value as? NSNumber {
            guard CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
            text = n.stringValue
        } else { return nil }
        guard text.range(of: #"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"#,
                         options: .regularExpression) != nil,
              let n = Double(text), n.isFinite else { return nil }
        return n
    }
    static func boolean(_ value: Any?) -> Bool? {
        guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }
        return n.boolValue
    }
    private static func object(_ data: Data) throws -> [String: Any] {
        guard let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw Failure.unsupported
        }
        if boolean(obj["success"]) == false { throw Failure.rejected }
        return obj
    }
    static func scale(_ data: Data, root: String, now: Date) -> Scale? {
        guard let obj = try? object(data), let body = obj["data"] as? [String: Any],
              let qpu = number(body["quota_per_unit"]), qpu > 0 else { return nil }
        // New API defines quota_per_unit as quota points per ledger USD.
        // usd_exchange_rate/display currency is separate display metadata.
        return Scale(quotaPerUnit: qpu, observedAt: now, endpoint: root + "/api/status")
    }
    private static func reading(_ source: Source, _ scope: Scope, root: String, now: Date,
                                scale: Scale? = nil, usd: Bool = false) -> Reading {
        Reading(source: source, scope: scope, endpoint: root + source.path,
                relayHost: URL(string: root)?.host ?? "",
                unit: usd || scale != nil ? .currency("USD") : .quota,
                unitEvidence: usd ? "documented \(source.rawValue) USD fields"
                    : (scale.map { $0.endpoint + "#quota_per_unit" } ?? "unconverted quota; rate unknown"),
                quotaPerUnit: scale?.quotaPerUnit, scaleObservedAt: scale?.observedAt,
                observedAt: now)
    }
    private static func converted(_ value: Any?, scale: Scale?) -> Double? {
        guard let value = number(value) else { return nil }
        let result = value / (scale?.quotaPerUnit ?? 1)
        return result.isFinite ? result : nil
    }

    static func parseSub2API(_ data: Data, root: String, now: Date) throws -> [Reading] {
        let obj = try object(data)
        guard let valid = boolean(obj["isValid"]) else { throw Failure.unsupported }
        let keyUsed = ((obj["usage"] as? [String: Any])?["total"] as? [String: Any])
            .flatMap { number($0["actual_cost"]) }
        var r: Reading
        if obj["mode"] as? String == "quota_limited" {
            r = reading(.sub2api, .keyQuota, root: root, now: now, usd: true)
            let q = obj["quota"] as? [String: Any] ?? [:]
            r.total = number(q["limit"])
            r.remaining = number(q["remaining"]).map { max(0, $0) }
            r.used = obj["quota"] != nil ? number(q["used"]) : keyUsed
            r.usedLabel = "Key 限额内已用"
        } else if obj.keys.contains("balance") {
            r = reading(.sub2api, .accountBalance, root: root, now: now, usd: true)
            r.remaining = number(obj["balance"])
        } else {
            r = reading(.sub2api, .subscription, root: root, now: now, usd: true)
            let remaining = number(obj["remaining"])
            r.unlimited = remaining == -1
            r.remaining = remaining.flatMap { $0 >= 0 ? $0 : nil }
            r.used = keyUsed
            r.usedLabel = "Key 累计实际费用（非套餐周期用量）"
        }
        r.rejected = !valid
        guard r.hasAmounts else { throw Failure.unsupported }
        var result = [r]
        // actual_cost is key usage, not lifetime account spend or plan usage.
        if r.scope == .accountBalance, let keyUsed {
            var usage = reading(.sub2api, .usage, root: root, now: now, usd: true)
            usage.used = keyUsed
            usage.usedLabel = "Key 累计实际费用"
            usage.rejected = !valid
            result.append(usage)
        }
        return result
    }

    static func parseNewAPI(_ data: Data, root: String, now: Date, scale: Scale?) throws -> [Reading] {
        let obj = try object(data)
        guard let d = obj["data"] as? [String: Any],
              d["total_granted"] != nil || d["total_available"] != nil || boolean(d["unlimited_quota"]) == true else {
            throw Failure.unsupported
        }
        var r = reading(.newAPIKey, .keyQuota, root: root, now: now, scale: scale)
        let granted = converted(d["total_granted"], scale: scale)
        r.used = converted(d["total_used"], scale: scale)
        r.usedLabel = "Key 累计已用"
        r.unlimited = boolean(d["unlimited_quota"]) == true || (granted.map { $0 < 0 } ?? false)
        if !r.unlimited {
            r.total = granted
            r.remaining = converted(d["total_available"], scale: scale)
            if r.remaining == nil, let total = r.total, let used = r.used, (total - used).isFinite {
                r.remaining = max(0, total - used)
            }
        }
        guard r.hasAmounts else { throw Failure.unsupported }
        return [r]
    }
    static func parseAccount(_ data: Data, root: String, now: Date, scale: Scale?) throws -> [Reading] {
        let obj = try object(data), d = (obj["data"] as? [String: Any]) ?? obj
        var r = reading(.newAPIAccount, .accountBalance, root: root, now: now, scale: scale)
        r.remaining = converted(d["quota"], scale: scale)
        r.used = converted(d["used_quota"], scale: scale)
        r.usedLabel = "账户累计已用"
        guard r.remaining != nil else { throw Failure.unsupported }
        return [r]
    }

    /// Keep the established conservative ceiling for legacy relay placeholders.
    static let placeholderLimitUSD: Double = 1_000_000
    static func parseBilling(_ subscription: Data, usage: Data?, root: String, now: Date) throws -> [Reading] {
        let obj = try object(subscription), sub = (obj["data"] as? [String: Any]) ?? obj
        let useObj = usage.flatMap { try? object($0) } ?? [:]
        let use = (useObj["data"] as? [String: Any]) ?? useObj
        var r = reading(.openAIBilling, .spendingLimit, root: root, now: now, usd: true)
        r.used = number(use["total_usage"]).map { $0 / 100.0 } ?? number(use["used_usd"])
        // Generic 'balance' carries no USD evidence. Only an explicit USD field
        // or currency tag may promote it to account money.
        let balance = number(sub["balance_usd"])
            ?? ((sub["currency"] as? String)?.uppercased() == "USD" ? number(sub["balance"]) : nil)
        if let balance {
            r = reading(.openAIBilling, .accountBalance, root: root, now: now, usd: true)
            r.remaining = balance
            r.used = number(use["total_usage"]).map { $0 / 100.0 } ?? number(use["used_usd"])
        } else if let hard = number(sub["hard_limit_usd"]) ?? number(sub["soft_limit_usd"]), hard >= 0 {
            r.unlimited = hard >= placeholderLimitUSD
            if !r.unlimited {
                r.total = hard
                r.remaining = r.used.flatMap { (hard - $0).isFinite ? max(0, hard - $0) : nil }
            }
        } else { throw Failure.unsupported }
        r.usedLabel = "本月已用"
        r.usedEndpoint = root + "/v1/dashboard/billing/usage"
        r.usedObservedAt = r.used != nil ? now : nil
        return [r]
    }
    static func parseAnthropic(_ data: Data, root: String, now: Date) throws -> [Reading] {
        let obj = try object(data)
        guard let breakdown = obj["cost_breakdown"] as? [String: Any],
              let samples = breakdown["samples"] as? [[String: Any]], let first = samples.first,
              let cost = first["cost"] as? [String: Any], let usd = number(cost["usd"]) else {
            throw Failure.unsupported
        }
        var r = reading(.anthropic, .usage, root: root, now: now, usd: true)
        r.used = usd
        return [r]
    }

    /// Credentials are supplied only by the caller that owns this endpoint.
    static func request(root: String, source: Source, chatKey: String?, accountToken: String?,
                        userID: String?, cookie: String? = nil) throws -> URLRequest {
        guard let url = endpoint(root: root, path: source.path) else { throw Failure.invalidURL }
        var req = URLRequest(url: url)
        req.timeoutInterval = 12
        req.cachePolicy = .reloadIgnoringLocalCacheData
        req.httpShouldHandleCookies = false
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if source == .newAPIAccount {
            if let token = accountToken, !token.isEmpty {
                guard let uid = userID, !uid.isEmpty else { throw Failure.missingUserID }
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                req.setValue(uid, forHTTPHeaderField: "New-Api-User")
            } else if let cookie, !cookie.isEmpty {
                req.setValue(cookie, forHTTPHeaderField: "Cookie")
            } else { throw Failure.missingCredential }
        } else {
            guard let key = chatKey, !key.isEmpty else { throw Failure.missingCredential }
            if source == .anthropic {
                req.setValue(key, forHTTPHeaderField: "x-api-key")
                req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
            } else { req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") }
        }
        return req
    }
}

/// Deliberately refuse ALL redirects, including same-origin path rewrites:
/// neither chat credentials nor management credentials can migrate endpoints.
final class RelayQuotaRedirectGuard: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
