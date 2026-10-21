import Foundation
import Security
import CryptoKit

/// Request-local identity. Do not print a lease: it contains a credential.
struct ProviderKeyLease {
    let id: String
    let key: String
    // A late success must not reactivate a key parked by a newer request.
    var startedAt: Date = Date()
}

enum MultiKeyFailureKind {
    case credential, quota, rateLimit, transient, other

    var mayTryAnotherKey: Bool {
        switch self {
        case .other: return false
        default: return true
        }
    }

    /// Only these category summaries, never provider bodies, reach storage.
    fileprivate var summary: String {
        switch self {
        case .credential: return AppLocalized("Invalid API key")
        case .quota: return AppLocalized("Insufficient balance or quota")
        case .rateLimit: return AppLocalized("Rate limited")
        case .transient: return AppLocalized("Service temporarily unavailable")
        case .other: return AppLocalized("Request failed")
        }
    }

    static func classify(_ error: Error) -> MultiKeyFailureKind {
        guard !isCancellation(error) else { return .other }
        return classifyUncancelled(error, depth: 0)
    }

    private static func isCancellation(_ error: Error, depth: Int = 0) -> Bool {
        guard depth < 16 else { return false }
        if error is CancellationError { return true }
        if let llm = error as? LLMError {
            switch llm {
            case .cancelled: return true
            case .networkError(let e), .decodingError(let e):
                return isCancellation(e, depth: depth + 1)
            case .unknown(let e):
                if let e { return isCancellation(e, depth: depth + 1) }
            default: break
            }
        }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return true }
        if let e = ns.userInfo[NSUnderlyingErrorKey] as? Error {
            return isCancellation(e, depth: depth + 1)
        }
        return false
    }

    private static func classifyUncancelled(_ error: Error, depth: Int) -> MultiKeyFailureKind {
        guard depth < 16 else { return .other }
        if let llm = error as? LLMError {
            switch llm {
            case .invalidAPIKey: return .credential
            case .rateLimited: return .rateLimit
            case .networkError, .transientError: return .transient
            case .providerError(let message): return classifyProviderMessage(message)
            case .unknown(let e):
                if let e { return classifyUncancelled(e, depth: depth + 1) }
                return .other
            case .cancelled, .decodingError: return .other
            }
        }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain { return .transient }
        if let e = ns.userInfo[NSUnderlyingErrorKey] as? Error {
            return classifyUncancelled(e, depth: depth + 1)
        }
        return .other
    }

    private static func classifyProviderMessage(_ text: String) -> MultiKeyFailureKind {
        let message = text.lowercased()
        // Only a leading HTTP status / [status] is evidence, not numbers in a body.
        let pattern = #"(?i)^\s*(?:HTTP\s*(?:\[\s*(\d{3})\s*\]|(\d{3}))|\[\s*(\d{3})\s*\])(?=$|[\s:;,\.\-])"#
        if let regex = try? NSRegularExpression(pattern: pattern),
           let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let code = (1..<match.numberOfRanges).compactMap({ index -> Int? in
               guard let range = Range(match.range(at: index), in: text) else { return nil }
               return Int(text[range])
           }).first {
            switch code {
            case 401, 403: return .credential
            case 402: return .quota
            case 429: return .rateLimit
            case 408, 500...599: return .transient
            case 400: break // Some relays report exhausted credit with HTTP 400; inspect its explicit reason.
            default: break
            }
        }
        if ["context length", "context_length", "maximum context", "invalid schema",
            "invalid_schema", "content policy", "content_policy", "content_filter",
            "model not found", "model_not_found"].contains(where: { message.contains($0) }) { return .other }
        if ["insufficient balance", "insufficient_balance", "insufficient quota", "insufficient_quota",
            "quota exhausted", "quota_exhausted", "quota exceeded", "quota_exceeded",
            "balance exhausted", "insufficient credits", "credit balance too low", "credits exhausted",
            "余额不足", "额度耗尽", "额度不足"].contains(where: { message.contains($0) }) { return .quota }
        if ["invalid api key", "invalid_api_key", "incorrect api key", "authentication",
            "unauthorized", "permission denied", "permission_denied", "insufficient permissions",
            "does not have permission", "access denied"].contains(where: { message.contains($0) }) { return .credential }
        if ["rate limit", "rate_limit", "too many requests", "限流", "请求过于频繁"]
            .contains(where: { message.contains($0) }) { return .rateLimit }
        return .other
    }
}

/// [T-multikey] One API key under a provider, plus the bookkeeping needed to
/// route around it when it starts failing.
///
/// Modelled on Kelivo's `ApiKeyConfig` (Chevey339/kelivo, AGPL-3.0): the same
/// four-state lifecycle, the same consecutive-failure rule. Reimplemented in
/// Swift — their Dart is read for design only, nothing is copied.
struct ProviderAPIKey: Codable, Identifiable, Hashable {

    enum Status: String, Codable {
        /// Usable.
        case active
        /// Turned off by the user; never selected.
        case disabled
        /// Failed `maxConsecutiveFailures` times in a row. Skipped until the
        /// cooldown expires, then it gets another chance on its own.
        case error
    }

    let id: String
    var key: String
    /// Optional label so two keys from the same site are distinguishable.
    var name: String?
    var isEnabled: Bool
    var status: Status
    var successCount: Int
    var failureCount: Int
    var consecutiveFailures: Int
    var lastUsed: Date?
    var lastError: String?
    var updatedAt: Date
    /// Optional for old Keychain blobs; rate limits can recover sooner than 5 min.
    var unavailableUntil: Date? = nil

    init(key: String, name: String? = nil) {
        self.id = UUID().uuidString
        self.key = key
        self.name = name
        self.isEnabled = true
        self.status = .active
        self.successCount = 0
        self.failureCount = 0
        self.consecutiveFailures = 0
        self.lastUsed = nil
        self.lastError = nil
        self.updatedAt = Date()
    }

    /// Never show a full key in the UI — only the head and tail.
    var masked: String {
        guard key.count > 14 else { return String(repeating: "•", count: 10) }
        return key.prefix(6) + "…" + key.suffix(4)
    }

    /// True when the key is currently selectable. `error` keys come back once
    /// `recoveryInterval` has passed since they were marked.
    func isSelectable(recoveryInterval: TimeInterval, now: Date = Date()) -> Bool {
        guard isEnabled, !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        if let until = unavailableUntil, now < until { return false }
        switch status {
        case .active:
            return true
        case .disabled:
            return false
        case .error:
            return now >= (unavailableUntil ?? updatedAt.addingTimeInterval(recoveryInterval))
        }
    }
}

/// [T-multikey] How to pick the next key.
enum MultiKeyStrategy: String, Codable, CaseIterable {
    case roundRobin
    case priority
    case random
    case leastUsed

    var displayName: String {
        switch self {
        case .roundRobin: return "轮询"
        case .priority:   return "顺序优先"
        case .random:     return "随机"
        case .leastUsed:  return "最少使用"
        }
    }

    var explanation: String {
        switch self {
        case .roundRobin: return "依次使用每个 Key，用完最后一个再回到第一个。最均衡，推荐。"
        case .priority:   return "只用第一个，它报错了才换下一个。适合有主备之分的情况。"
        case .random:     return "每次随机挑一个。分散得最开，但不好预期。"
        case .leastUsed:  return "优先选累计用得最少的那个。长期最省。"
        }
    }
}

/// [T-multikey] Per-provider key ring.
///
/// Storage split:
///   - the keys themselves → Keychain, one JSON blob per provider, **not**
///     iCloud-synchronised (same reasoning as the dashboard access token:
///     credentials stay on this device)
///   - the switch, strategy and round-robin cursor → UserDefaults, since they
///     are preferences rather than secrets
final class ProviderMultiKeyManager {

    static let shared = ProviderMultiKeyManager()
    private init() {}

    /// After this long, an `error` key is retried once on its own.
    static let recoveryInterval: TimeInterval = 5 * 60
    /// Consecutive failures before a key is parked.
    static let maxConsecutiveFailures = 3

    private let servicePrefix = "com.openminis.app.provider.multikeys"
    private let enabledPrefix = "provider.multikey.enabled."
    private let strategyPrefix = "provider.multikey.strategy."
    private let cursorPrefix = "provider.multikey.cursor."
    private let lock = NSLock()

    // MARK: - Keychain

    private func service(for instanceId: String) -> String {
        "\(servicePrefix).\(instanceId)"
    }

    private func readBlob(for instanceId: String) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: instanceId),
            kSecAttrAccount as String: "keys",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    private func writeBlob(_ data: Data, for instanceId: String) {
        let svc = service(for: instanceId)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: svc,
            kSecAttrAccount as String: "keys",
        ]
        let attrs: [String: Any] = [
            kSecValueData as String: data,
            // Local only — a key ring is a credential, and the user asked for
            // credentials to stay on this device.
            kSecAttrSynchronizable as String: false,
        ]
        if SecItemUpdate(query as CFDictionary, attrs as CFDictionary) == errSecSuccess { return }
        var add = query
        add.merge(attrs) { _, new in new }
        SecItemAdd(add as CFDictionary, nil)
    }

    // MARK: - Read

    func keys(for instanceId: String) -> [ProviderAPIKey] {
        lock.lock(); defer { lock.unlock() }
        guard let data = readBlob(for: instanceId),
              let list = try? JSONDecoder().decode([ProviderAPIKey].self, from: data) else {
            return []
        }
        return list
    }

    func isEnabled(for instanceId: String) -> Bool {
        UserDefaults.standard.bool(forKey: enabledPrefix + instanceId)
    }

    func strategy(for instanceId: String) -> MultiKeyStrategy {
        guard let raw = UserDefaults.standard.string(forKey: strategyPrefix + instanceId),
              let s = MultiKeyStrategy(rawValue: raw) else { return .roundRobin }
        return s
    }

    /// Counts shown on the management screen.
    func summary(for instanceId: String) -> (total: Int, ok: Int, bad: Int) {
        let list = keys(for: instanceId)
        let ok = list.filter { $0.isSelectable(recoveryInterval: Self.recoveryInterval) }.count
        return (list.count, ok, list.count - ok)
    }

    // MARK: - Write

    func save(_ keys: [ProviderAPIKey], for instanceId: String) {
        lock.lock(); defer { lock.unlock() }
        guard let data = try? JSONEncoder().encode(keys) else { return }
        writeBlob(data, for: instanceId)
    }

    func setEnabled(_ on: Bool, for instanceId: String) {
        UserDefaults.standard.set(on, forKey: enabledPrefix + instanceId)
    }

    func setStrategy(_ s: MultiKeyStrategy, for instanceId: String) {
        UserDefaults.standard.set(s.rawValue, forKey: strategyPrefix + instanceId)
    }

    func add(_ key: String, name: String? = nil, for instanceId: String) -> ProviderAPIKey {
        var list = keys(for: instanceId)
        let fresh = ProviderAPIKey(key: key.trimmingCharacters(in: .whitespacesAndNewlines), name: name)
        list.append(fresh)
        save(list, for: instanceId)
        return fresh
    }

    func remove(keyId: String, for instanceId: String) {
        var list = keys(for: instanceId)
        list.removeAll { $0.id == keyId }
        save(list, for: instanceId)
    }

    func update(keyId: String, for instanceId: String, _ mutate: (inout ProviderAPIKey) -> Void) {
        var list = keys(for: instanceId)
        guard let idx = list.firstIndex(where: { $0.id == keyId }) else { return }
        mutate(&list[idx])
        list[idx].updatedAt = Date()
        save(list, for: instanceId)
    }

    /// Manual retry: clear the parked state without touching the counters.
    func reactivate(keyId: String, for instanceId: String) {
        update(keyId: keyId, for: instanceId) { k in
            k.status = .active
            k.consecutiveFailures = 0
            k.lastError = nil
        }
    }

    // MARK: - Request-scoped leases

    private struct MainState: Codable {
        let fingerprint: String
        var successCount = 0
        var failureCount = 0
        var consecutiveFailures = 0
        var unavailableUntil: Date?
        var lastFailureAt: Date?
    }

    private func fingerprint(_ key: String) -> String {
        SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func mainState(_ key: String, instanceId: String) -> MainState {
        let fp = fingerprint(key)
        if let data = UserDefaults.standard.data(forKey: "provider.multikey.mainState." + instanceId),
           let state = try? JSONDecoder().decode(MainState.self, from: data), state.fingerprint == fp {
            return state
        }
        return MainState(fingerprint: fp)
    }

    private func saveMainState(_ state: MainState, instanceId: String) {
        // Only a one-way fingerprint and counters. Credentials stay in Keychain.
        guard let data = try? JSONEncoder().encode(state) else { return }
        UserDefaults.standard.set(data, forKey: "provider.multikey.mainState." + instanceId)
    }

    private func unlockedKeys(_ instanceId: String) -> [ProviderAPIKey] {
        guard let data = readBlob(for: instanceId),
              let list = try? JSONDecoder().decode([ProviderAPIKey].self, from: data) else { return [] }
        return list
    }

    private func unlockedSave(_ list: [ProviderAPIKey], instanceId: String) {
        guard let data = try? JSONEncoder().encode(list) else { return }
        writeBlob(data, for: instanceId)
    }

    /// One atomic pick including the main credential; no dead-main fallback.
    func lease(for instanceId: String, excluding: Set<String> = []) -> ProviderKeyLease? {
        lock.lock(); defer { lock.unlock() }
        let main = ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard isEnabled(for: instanceId) else {
            return main.isEmpty || excluding.contains("main") ? nil : ProviderKeyLease(id: "main", key: main)
        }
        let now = Date()
        var pool: [(lease: ProviderKeyLease, uses: Int)] = []
        var seen = Set<String>()
        if !main.isEmpty {
            seen.insert(main)
            let state = mainState(main, instanceId: instanceId)
            if !excluding.contains("main"), state.unavailableUntil.map({ $0 <= now }) ?? true {
                pool.append((ProviderKeyLease(id: "main", key: main), state.successCount + state.failureCount))
            }
        }
        for entry in unlockedKeys(instanceId) {
            let key = entry.key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, seen.insert(key).inserted else { continue }
            guard !excluding.contains(entry.id), entry.isSelectable(recoveryInterval: Self.recoveryInterval, now: now) else { continue }
            pool.append((ProviderKeyLease(id: entry.id, key: key), entry.successCount + entry.failureCount))
        }
        guard !pool.isEmpty else { return nil }
        switch strategy(for: instanceId) {
        case .priority: return pool[0].lease
        case .random: return pool.randomElement()?.lease
        case .leastUsed: return pool.min { $0.uses < $1.uses }?.lease
        case .roundRobin:
            let cursor = max(0, UserDefaults.standard.integer(forKey: cursorPrefix + instanceId))
            let index = cursor % pool.count
            UserDefaults.standard.set(cursor == Int.max ? 0 : cursor + 1, forKey: cursorPrefix + instanceId)
            return pool[index].lease
        }
    }

    func recordSuccess(lease: ProviderKeyLease, for instanceId: String) {
        lock.lock(); defer { lock.unlock() }
        if lease.id == "main" {
            guard ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key else { return }
            var state = mainState(lease.key, instanceId: instanceId)
            state.successCount += 1
            if state.lastFailureAt.map({ $0 <= lease.startedAt }) ?? true {
                state.consecutiveFailures = 0; state.unavailableUntil = nil
            }
            saveMainState(state, instanceId: instanceId)
        } else {
            var list = unlockedKeys(instanceId)
            guard let index = list.firstIndex(where: { $0.id == lease.id && $0.key.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key }) else { return }
            list[index].successCount += 1
            list[index].lastUsed = Date()
            if list[index].updatedAt <= lease.startedAt {
                list[index].consecutiveFailures = 0; list[index].lastError = nil
                list[index].unavailableUntil = nil
                if list[index].isEnabled && list[index].status != .disabled { list[index].status = .active }
            }
            unlockedSave(list, instanceId: instanceId)
        }
    }

    func recordFailure(lease: ProviderKeyLease, kind: MultiKeyFailureKind, for instanceId: String) {
        guard kind.mayTryAnotherKey else { return }
        lock.lock(); defer { lock.unlock() }
        let now = Date()
        func cooldown(_ failures: Int) -> TimeInterval? {
            switch kind {
            case .credential, .quota: return Self.recoveryInterval
            case .rateLimit: return 60
            case .transient: return failures >= Self.maxConsecutiveFailures ? 30 : nil
            case .other: return nil
            }
        }
        if lease.id == "main" {
            guard ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key else { return }
            var state = mainState(lease.key, instanceId: instanceId)
            state.failureCount += 1; state.consecutiveFailures += 1; state.lastFailureAt = now
            if let seconds = cooldown(state.consecutiveFailures) { state.unavailableUntil = now.addingTimeInterval(seconds) }
            saveMainState(state, instanceId: instanceId)
        } else {
            var list = unlockedKeys(instanceId)
            guard let index = list.firstIndex(where: { $0.id == lease.id && $0.key.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key }) else { return }
            list[index].failureCount += 1; list[index].consecutiveFailures += 1
            list[index].lastUsed = now; list[index].updatedAt = now; list[index].lastError = kind.summary
            if let seconds = cooldown(list[index].consecutiveFailures) {
                list[index].unavailableUntil = now.addingTimeInterval(seconds)
                if list[index].isEnabled && list[index].status != .disabled { list[index].status = .error }
            }
            unlockedSave(list, instanceId: instanceId)
        }
    }

    // MARK: - Selection

    /// [T-multikey] The key this request should actually use.
    ///
    /// Multi-key ON and a key is selectable → that key.
    /// Multi-key ON but every key is parked/disabled → fall back to the single
    ///   saved key (it may still work; failing silently with no key at all
    ///   would be worse than trying).
    /// Multi-key OFF → the single saved key, exactly as before.
    func effectiveKey(for instanceId: String) -> String? {
        lease(for: instanceId)?.key
    }


    /// Returns the key this request should use, or nil when the multi-key ring
    /// is off / empty — callers then fall back to the single saved key.
    ///
    /// Selection never mutates counters; `recordSuccess` / `recordFailure` do
    /// that once the request resolves. A nil return with a non-empty ring means
    /// every key is parked or disabled, and the caller should surface that
    /// rather than silently using a dead key.
    func nextKey(for instanceId: String) -> ProviderAPIKey? {
        guard isEnabled(for: instanceId) else { return nil }
        let list = keys(for: instanceId)
        guard !list.isEmpty else { return nil }

        let usable = list.filter { $0.isSelectable(recoveryInterval: Self.recoveryInterval) }
        guard !usable.isEmpty else { return nil }

        let chosen: ProviderAPIKey
        switch strategy(for: instanceId) {
        case .roundRobin:
            let cursor = UserDefaults.standard.integer(forKey: cursorPrefix + instanceId)
            let idx = cursor % usable.count
            chosen = usable[idx]
            UserDefaults.standard.set((idx + 1) % usable.count, forKey: cursorPrefix + instanceId)
        case .priority:
            chosen = usable.first!
        case .random:
            chosen = usable.randomElement()!
        case .leastUsed:
            chosen = usable.min { a, b in
                (a.successCount + a.failureCount) < (b.successCount + b.failureCount)
            }!
        }
        return chosen
    }

    // MARK: - Outcome

    func recordSuccess(keyId: String, for instanceId: String) {
        update(keyId: keyId, for: instanceId) { k in
            k.successCount += 1
            k.consecutiveFailures = 0
            k.status = .active
            k.lastError = nil
            k.lastUsed = Date()
        }
    }

    /// Marks a failure. After `maxConsecutiveFailures` in a row the key is
    /// parked (`.error`) and skipped until the cooldown expires.
    func recordFailure(keyId: String, error: String, for instanceId: String) {
        update(keyId: keyId, for: instanceId) { k in
            k.failureCount += 1
            k.consecutiveFailures += 1
            k.lastError = error
            k.lastUsed = Date()
            if k.consecutiveFailures >= Self.maxConsecutiveFailures {
                k.status = .error
            }
        }
    }
}
