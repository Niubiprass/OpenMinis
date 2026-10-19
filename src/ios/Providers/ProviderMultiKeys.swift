import Foundation
import Security

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
        guard isEnabled else { return false }
        switch status {
        case .active:
            return true
        case .disabled:
            return false
        case .error:
            return now.timeIntervalSince(updatedAt) >= recoveryInterval
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

    // MARK: - Selection

    /// [T-multikey] The key this request should actually use.
    ///
    /// Multi-key ON and a key is selectable → that key.
    /// Multi-key ON but every key is parked/disabled → fall back to the single
    ///   saved key (it may still work; failing silently with no key at all
    ///   would be worse than trying).
    /// Multi-key OFF → the single saved key, exactly as before.
    func effectiveKey(for instanceId: String) -> String? {
        if isEnabled(for: instanceId), let picked = nextKey(for: instanceId) {
            return picked.key
        }
        return ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)
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
