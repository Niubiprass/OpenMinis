import Foundation
import Security
import CryptoKit

/// Request-local identity. Do not print a lease: it contains a credential.
struct ProviderKeyLease: Sendable {
    let id: String
    let key: String
    // A late success must not reactivate a key parked by a newer request.
    var startedAt: Date = Date()
}

enum MultiKeyFailureKind: Sendable {
    case credential, forbidden, quota, rateLimit, transient, gatewayTimeout, requestTooLarge, network, other

    var mayTryAnotherKey: Bool {
        switch self {
        // A transport failure says nothing about the credential. Retrying the
        // same key after the path recovers avoids shuffling keys pointlessly.
        case .network, .other, .requestTooLarge: return false
        default: return true
        }
    }

    /// Only these category summaries, never provider bodies, reach storage.
    fileprivate var summary: String {
        switch self {
        case .credential: return AppLocalized("Invalid API key")
        case .forbidden: return AppLocalized("Access denied")
        case .quota: return AppLocalized("Insufficient balance or quota")
        case .rateLimit: return AppLocalized("Rate limited")
        case .transient: return AppLocalized("Service temporarily unavailable")
        case .gatewayTimeout: return AppLocalized("Gateway timed out")
        case .requestTooLarge: return AppLocalized("Request too large")
        case .network: return AppLocalized("Network line failed")
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
            case .networkError: return .network
            case .transientError(_, let statusCode):
                // Connection-level 408 is a line timeout; a 5xx came from the
                // origin. Cloudflare 520–523 mean the origin is unreachable,
                // so changing key does not help; 524 is a slow gateway.
                if statusCode == 408 { return .network }
                guard statusCode != nil else { return .other }
                if let code = statusCode, (520...523).contains(code) { return .other }
                if statusCode == 524 { return .gatewayTimeout }
                return .transient
            case .providerError(let message): return classifyProviderMessage(message)
            case .unknown(let e):
                if let e { return classifyUncancelled(e, depth: depth + 1) }
                return .other
            case .cancelled, .decodingError: return .other
            }
        }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain { return .network }
        if let e = ns.userInfo[NSUnderlyingErrorKey] as? Error {
            return classifyUncancelled(e, depth: depth + 1)
        }
        return .other
    }

    private static func classifyProviderMessage(_ text: String) -> MultiKeyFailureKind {
        let message = text.lowercased()
        // A 5xx can still mean "this deployment has no channel". That is a
        // routing/config fact, not capacity: retrying or changing key is useless.
        if message.contains("model_not_found") || message.contains("no available channel")
            || message.contains("无可用渠道") {
            return .other
        }
        // Only a leading HTTP status / [status] is evidence, not numbers in a body.
        let pattern = #"(?i)^\s*(?:HTTP\s*(?:\[\s*(\d{3})\s*\]|(\d{3}))|\[\s*(\d{3})\s*\])(?=$|[\s:;,\.\-])"#
        if let regex = try? NSRegularExpression(pattern: pattern),
           let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let code = (1..<match.numberOfRanges).compactMap({ index -> Int? in
               guard let range = Range(match.range(at: index), in: text) else { return nil }
               return Int(text[range])
           }).first {
            switch code {
            case 401: return .credential
            case 403: return .forbidden
            case 402: return .quota
            case 429: return .rateLimit
            case 413: return .requestTooLarge
            case 520...523: return .other
            case 524: return .gatewayTimeout
            case 408: return .network
            case 500...599: return .transient
            case 400: break // Some relays report exhausted credit with HTTP 400; inspect its explicit reason.
            default: break
            }
        }
        if ["context length", "context_length", "maximum context", "invalid schema",
            "invalid_schema", "content policy", "content_policy", "content_filter",
            "model not found", "model_not_found", "no available channel", "无可用渠道"].contains(where: { message.contains($0) }) { return .other }
        if ["insufficient balance", "insufficient_balance", "insufficient quota", "insufficient_quota",
            "quota exhausted", "quota_exhausted", "quota exceeded", "quota_exceeded",
            "balance exhausted", "insufficient credits", "credit balance too low", "credits exhausted",
            "余额不足", "额度耗尽", "额度不足"].contains(where: { message.contains($0) }) { return .quota }
        if ["invalid api key", "invalid_api_key", "incorrect api key", "authentication",
            "unauthorized", "permission denied", "permission_denied", "insufficient permissions",
            "does not have permission", "access denied"].contains(where: { message.contains($0) }) { return .credential }
        if ["rate limit", "rate_limit", "too many requests", "concurrency limit",
            "concurrent request", "requests-per-minute", "requests per minute",
            "request per minute", "限流", "请求过于频繁", "并发超限"]
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
struct ProviderAPIKey: Codable, Identifiable, Hashable, Sendable {

    enum Status: String, Codable, Sendable {
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
enum MultiKeyStrategy: String, Codable, CaseIterable, Sendable {
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
        case .priority:   return "固定用主 Key；主 Key 报错或被停用后，才按列表顺序用轮询 1、2、3。"
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
final class ProviderMultiKeyManager: @unchecked Sendable {

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
    // [T-multikey-freeze-20261101] This mutex protects MEMORY ONLY. No
    // Security/UserDefaults call, JSON codec, queue wait or callback may run
    // while it is held. A blocked storage daemon must never block UI readers.
    // This lock protects memory snapshots only. Storage has a different lock;
    // readers/lease reservations NEVER wait for a Keychain/defaults operation.
    private let lock = NSLock()
    private let storageLock = NSLock()
    private var keySnapshots: [String: [ProviderAPIKey]] = [:]
    private var mainSnapshots: [String: MainState] = [:]
    private var cursorSnapshots: [String: Int] = [:]
    private var enabledSnapshots: [String: Bool] = [:]
    private var strategySnapshots: [String: MultiKeyStrategy] = [:]
    private var loaded: Set<String> = []
    private enum Dirty: Hashable { case ring, main, cursor, enabled, strategy }
    private var dirty: [String: Set<Dirty>] = [:]
    private var dirtyVersions: [String: [Dirty: UInt64]] = [:]
    private var persistenceErrors: Set<String> = []
    private var writers: [String: DispatchQueue] = [:]
    private var scheduledWriters: Set<String> = []
    private var loading: Set<String> = []

    static let didChange = Notification.Name("ProviderMultiKeyManager.didChange")

    private func notifyChange(_ instanceId: String) {
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: Self.didChange, object: instanceId)
        }
    }

    /// Enqueue one writer per provider. The writer always snapshots the latest
    /// dirty domains and persists OUTSIDE the mutex. Concurrent edits cannot
    /// lose increments or enqueue a stale snapshot after a newer one.
    private func schedulePersistence(for instanceId: String) {
        lock.lock()
        guard !scheduledWriters.contains(instanceId) else { lock.unlock(); return }
        let queue = writers[instanceId] ?? DispatchQueue(label: "com.openminis.multikey.persist.\(instanceId)", qos: .utility)
        writers[instanceId] = queue
        scheduledWriters.insert(instanceId)
        lock.unlock()
        queue.async { [self] in persistLatest(for: instanceId) }
    }

    private func persistLatest(for instanceId: String) {
        storageLock.lock()
        defer { storageLock.unlock() }
        while true {
            lock.lock()
            let domains = dirty[instanceId] ?? []
            let versions = dirtyVersions[instanceId] ?? [:]
            let ring = keySnapshots[instanceId]
            let main = mainSnapshots[instanceId]
            let cursor = cursorSnapshots[instanceId]
            let enabled = enabledSnapshots[instanceId]
            let strategy = strategySnapshots[instanceId]
            if domains.isEmpty {
                scheduledWriters.remove(instanceId)
                persistenceErrors.remove(instanceId)
                lock.unlock()
                return
            }
            lock.unlock()

            var persisted = Set<Dirty>()
            if domains.contains(.ring), let ring, persistRing(ring, instanceId: instanceId) { persisted.insert(.ring) }
            if domains.contains(.main), let main, persistMain(main, instanceId: instanceId) { persisted.insert(.main) }
            if domains.contains(.cursor), let cursor, setDefault(cursor, key: cursorPrefix + instanceId) { persisted.insert(.cursor) }
            if domains.contains(.enabled), let enabled, setDefault(enabled, key: enabledPrefix + instanceId) { persisted.insert(.enabled) }
            if domains.contains(.strategy), let strategy, setDefault(strategy.rawValue, key: strategyPrefix + instanceId) { persisted.insert(.strategy) }

            lock.lock()
            for domain in persisted where dirtyVersions[instanceId]?[domain] == versions[domain] {
                dirty[instanceId]?.remove(domain)
                dirtyVersions[instanceId]?.removeValue(forKey: domain)
            }
            let failed = !(dirty[instanceId] ?? []).subtracting(persisted).isEmpty
            if failed {
                persistenceErrors.insert(instanceId)
                scheduledWriters.remove(instanceId)
                lock.unlock()
                notifyChange(instanceId)
                let queue = writers[instanceId]
                queue?.asyncAfter(deadline: .now() + 2.0) { [weak self] in
                    self?.schedulePersistence(for: instanceId)
                }
                return
            }
            lock.unlock()
            // A newer mutation bumps its version while storage was writing;
            // its dirty bit remains and the loop takes a fresh snapshot.
        }
    }

    private func setDefault(_ value: Any, key: String) -> Bool {
        UserDefaults.standard.set(value, forKey: key)
        return UserDefaults.standard.synchronize()
    }

    // MARK: - Keychain

    private func service(for instanceId: String) -> String {
        "\(servicePrefix).\(instanceId)"
    }

    private func readBlob(for instanceId: String) -> (data: Data?, readable: Bool) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: instanceId),
            kSecAttrAccount as String: "keys",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &out)
        if status == errSecItemNotFound { return (nil, true) }
        guard status == errSecSuccess, let data = out as? Data else { return (nil, false) }
        return (data, true)
    }

    private func writeBlob(_ data: Data, for instanceId: String) -> Bool {
        let svc = service(for: instanceId)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: svc,
            kSecAttrAccount as String: "keys",
        ]
        let attrs: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrSynchronizable as String: false,
        ]
        let update = SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
        if update == errSecSuccess { return true }
        guard update == errSecItemNotFound else { return false }
        var add = query
        add.merge(attrs) { _, new in new }
        let status = SecItemAdd(add as CFDictionary, nil)
        if status == errSecSuccess { return true }
        // Another writer/process may have inserted it after the first lookup.
        if status == errSecDuplicateItem {
            return SecItemUpdate(query as CFDictionary, attrs as CFDictionary) == errSecSuccess
        }
        return false
    }

    // MARK: - Read

    private func bump(_ instanceId: String, _ domain: Dirty) {
        var versions = dirtyVersions[instanceId] ?? [:]
        versions[domain, default: 0] &+= 1
        dirtyVersions[instanceId] = versions
        dirty[instanceId, default: []].insert(domain)
    }

    private func markLoaded(_ instanceId: String) {
        lock.lock(); loaded.insert(instanceId); lock.unlock()
    }

    func persistenceFailed(for instanceId: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return persistenceErrors.contains(instanceId)
    }

    private func persistRing(_ keys: [ProviderAPIKey], instanceId: String) -> Bool {
        guard let data = try? JSONEncoder().encode(keys) else { return false }
        return writeBlob(data, for: instanceId)
    }

    private func persistMain(_ state: MainState, instanceId: String) -> Bool {
        guard let data = try? JSONEncoder().encode(state) else { return false }
        UserDefaults.standard.set(data, forKey: "provider.multikey.mainState." + instanceId)
        return UserDefaults.standard.synchronize()
    }

    func keys(for instanceId: String) -> [ProviderAPIKey] {
        lock.lock()
        let cached = keySnapshots[instanceId]
        lock.unlock()
        if let cached { return cached }
        // Never touch Keychain from SwiftUI. An unloaded UI snapshot is unknown,
        // not an empty key ring; the management screen waits for keysReady.
        if Thread.isMainThread { warm(instanceId); return [] }
        // A cold load reads Keychain without waiting for the persistence writer.
        // Any concurrent edit publishes its new snapshot first; the publish check
        // below therefore wins over this potentially stale read.
        let blob = readBlob(for: instanceId)
        guard blob.readable else { return [] }
        let list: [ProviderAPIKey]
        if let data = blob.data {
            guard let decoded = try? JSONDecoder().decode([ProviderAPIKey].self, from: data) else { return [] }
            list = decoded
        } else { list = [] }
        lock.lock()
        // The loader must not publish a stale storage read over a mutation that
        // arrived during Keychain XPC. Treat a transient read failure separately
        // from the legitimate (successfully read) empty ring.
        let result = keySnapshots[instanceId] ?? list
        if keySnapshots[instanceId] == nil {
            keySnapshots[instanceId] = result
            loaded.insert(instanceId)
        }
        lock.unlock()
        notifyChange(instanceId)
        return result
    }

    func keysReady(for instanceId: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return keySnapshots[instanceId] != nil
    }

    private func warm(_ instanceId: String) {
        lock.lock()
        guard loading.insert(instanceId).inserted else { lock.unlock(); return }
        lock.unlock()
        DispatchQueue.global(qos: .utility).async { [self] in
            _ = keys(for: instanceId)
            _ = storedEnabled(for: instanceId)
            _ = strategy(for: instanceId)
            lock.lock(); loading.remove(instanceId); lock.unlock()
            notifyChange(instanceId)
        }
    }

    func keysAsync(for instanceId: String) async -> [ProviderAPIKey] {
        await Task.detached(priority: .userInitiated) {
            _ = self.storedEnabled(for: instanceId)
            _ = self.strategy(for: instanceId)
            return self.keys(for: instanceId)
        }.value
    }
    func isActiveAsync(for instanceId: String) async -> Bool {
        await Task.detached(priority: .userInitiated) { self.isActive(for: instanceId) }.value
    }
    func primaryKeyAsync(for instanceId: String) async -> String? {
        await Task.detached(priority: .userInitiated) {
            ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)
        }.value
    }
    func effectiveKeyAsync(for instanceId: String) async -> String? {
        await Task.detached(priority: .userInitiated) { self.effectiveKey(for: instanceId) }.value
    }
    func leaseAsync(for instanceId: String, excluding: Set<String> = []) async -> ProviderKeyLease? {
        await Task.detached(priority: .userInitiated) { self.lease(for: instanceId, excluding: excluding) }.value
    }

    /// Reuse a transport-failed credential without advancing the cursor.
    /// Revalidate current selection off-main: deleted/replaced/disabled keys
    /// never survive into another attempt just because a wrapper retained it.
    func validatedRetryLeaseAsync(_ lease: ProviderKeyLease, for instanceId: String) async -> ProviderKeyLease? {
        await Task.detached(priority: .utility) { [self] in
            let main = ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if lease.id == "main" {
                guard !main.isEmpty, main == lease.key else { return nil }
                if storedEnabled(for: instanceId),
                   mainState(main, instanceId: instanceId).unavailableUntil.map({ $0 > Date() }) == true { return nil }
                return ProviderKeyLease(id: lease.id, key: main, startedAt: Date())
            }
            guard storedEnabled(for: instanceId),
                  let entry = keys(for: instanceId).first(where: { $0.id == lease.id }),
                  entry.key.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key,
                  entry.isSelectable(recoveryInterval: Self.recoveryInterval) else { return nil }
            return ProviderKeyLease(id: lease.id, key: lease.key, startedAt: Date())
        }.value
    }

    private func storedEnabled(for instanceId: String) -> Bool {
        lock.lock(); let cached = enabledSnapshots[instanceId]; lock.unlock()
        if let cached { return cached }
        if Thread.isMainThread { warm(instanceId); return false }
        let stored = UserDefaults.standard.bool(forKey: enabledPrefix + instanceId)
        lock.lock()
        let result = enabledSnapshots[instanceId] ?? stored
        enabledSnapshots[instanceId] = result
        lock.unlock()
        return result
    }

    /// The persisted switch, and only that. Cheap enough for a view body; it
    /// must never read the Keychain there.
    func isEnabled(for instanceId: String) -> Bool {
        storedEnabled(for: instanceId)
    }

    /// Rotation really takes over only when the switch is on AND the ring has
    /// a key. [T-multikey-empty-ring] A latched-on switch with an empty ring
    /// used to keep wrapping requests: one failure parked the single saved
    /// credential, and every message until the cooldown then reported "no
    /// usable Key" although the user had merely deleted their extra keys.
    /// Request paths call this; view bodies use `isEnabled` or cached state.
    func isActive(for instanceId: String) -> Bool {
        guard storedEnabled(for: instanceId) else { return false }
        return !keys(for: instanceId).isEmpty
    }

    func strategy(for instanceId: String) -> MultiKeyStrategy {
        lock.lock(); let cached = strategySnapshots[instanceId]; lock.unlock()
        if let cached { return cached }
        if Thread.isMainThread { warm(instanceId); return .roundRobin }
        let stored = UserDefaults.standard.string(forKey: strategyPrefix + instanceId)
            .flatMap(MultiKeyStrategy.init(rawValue:)) ?? .roundRobin
        lock.lock()
        let result = strategySnapshots[instanceId] ?? stored
        strategySnapshots[instanceId] = result
        lock.unlock()
        return result
    }

    /// Counts shown on the management screen.
    func summary(for instanceId: String) -> (total: Int, ok: Int, bad: Int) {
        let list = keys(for: instanceId)
        let ok = list.filter { $0.isSelectable(recoveryInterval: Self.recoveryInterval) }.count
        return (list.count, ok, list.count - ok)
    }

    // MARK: - Write

    func save(_ keys: [ProviderAPIKey], for instanceId: String) {
        lock.lock()
        keySnapshots[instanceId] = keys
        bump(instanceId, .ring)
        lock.unlock()
        schedulePersistence(for: instanceId)
        notifyChange(instanceId)
    }

    func setEnabled(_ on: Bool, for instanceId: String) {
        lock.lock()
        enabledSnapshots[instanceId] = on
        bump(instanceId, .enabled)
        lock.unlock()
        schedulePersistence(for: instanceId)
        notifyChange(instanceId)
    }

    func setStrategy(_ s: MultiKeyStrategy, for instanceId: String) {
        lock.lock()
        strategySnapshots[instanceId] = s
        bump(instanceId, .strategy)
        lock.unlock()
        schedulePersistence(for: instanceId)
        notifyChange(instanceId)
    }

    // In-memory read/modify/write is atomic across CRUD and request outcomes.
    // Callers must have loaded the ring (management UI disables edits until it
    // is ready); an unavailable Keychain is NOT an empty ring to overwrite.
    private func mutateKeys(for instanceId: String, _ change: (inout [ProviderAPIKey]) -> Void) {
        if !keysReady(for: instanceId) { _ = keys(for: instanceId) }
        lock.lock()
        guard var list = keySnapshots[instanceId] else { lock.unlock(); return }
        change(&list) // pure field edits only; never I/O or a manager callback
        keySnapshots[instanceId] = list
        bump(instanceId, .ring)
        lock.unlock()
        schedulePersistence(for: instanceId)
        notifyChange(instanceId)
    }

    func add(_ key: String, name: String? = nil, for instanceId: String) -> ProviderAPIKey {
        let fresh = ProviderAPIKey(key: key.trimmingCharacters(in: .whitespacesAndNewlines), name: name)
        mutateKeys(for: instanceId) { list in
            guard !list.contains(where: { $0.key.trimmingCharacters(in: .whitespacesAndNewlines) == fresh.key }) else { return }
            list.append(fresh)
        }
        return fresh
    }

    func remove(keyId: String, for instanceId: String) {
        mutateKeys(for: instanceId) { $0.removeAll { $0.id == keyId } }
    }

    func update(keyId: String, for instanceId: String, _ mutate: (inout ProviderAPIKey) -> Void) {
        mutateKeys(for: instanceId) { list in
            guard let idx = list.firstIndex(where: { $0.id == keyId }) else { return }
            mutate(&list[idx])
            list[idx].updatedAt = Date()
        }
    }

    /// Manual retry: clear the parked state without touching the counters.
    func reactivate(keyId: String, for instanceId: String) {
        update(keyId: keyId, for: instanceId) { k in
            k.status = .active
            k.consecutiveFailures = 0
            k.lastError = nil
            k.unavailableUntil = nil
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
        lock.lock(); let cached = mainSnapshots[instanceId]; lock.unlock()
        if let cached, cached.fingerprint == fp { return cached }
        var stored = MainState(fingerprint: fp)
        if let data = UserDefaults.standard.data(forKey: "provider.multikey.mainState." + instanceId),
           let state = try? JSONDecoder().decode(MainState.self, from: data), state.fingerprint == fp {
            stored = state
        }
        lock.lock()
        let result = mainSnapshots[instanceId].flatMap { $0.fingerprint == fp ? $0 : nil } ?? stored
        mainSnapshots[instanceId] = result
        lock.unlock()
        return result
    }

    private func saveMainState(_ state: MainState, instanceId: String) {
        // Only a one-way fingerprint and counters. Credentials stay in Keychain.
        guard let data = try? JSONEncoder().encode(state) else { return }
        UserDefaults.standard.set(data, forKey: "provider.multikey.mainState." + instanceId)
    }

    private func unlockedKeys(_ instanceId: String) -> [ProviderAPIKey] {
        keys(for: instanceId)
    }

    /// The only round-robin reservation. Cursor read/advance is atomic in
    /// memory; the coalescing writer persists later without holding this mutex.
    private func reserveCursor(for instanceId: String, count: Int) -> Int {
        lock.lock(); let cached = cursorSnapshots[instanceId]; lock.unlock()
        let initial = cached ?? max(0, UserDefaults.standard.integer(forKey: cursorPrefix + instanceId))
        lock.lock()
        let cursor = cursorSnapshots[instanceId] ?? initial
        cursorSnapshots[instanceId] = cursor == Int.max ? 0 : cursor + 1
        bump(instanceId, .cursor)
        lock.unlock()
        schedulePersistence(for: instanceId)
        return cursor % max(1, count)
    }

    private func unlockedSave(_ list: [ProviderAPIKey], instanceId: String) {
        guard let data = try? JSONEncoder().encode(list) else { return }
        writeBlob(data, for: instanceId)
    }

    /// One atomic pick. The switch is the gate: OFF (or an empty ring) means the
    /// normal single main key; ON means main + added rotation keys all go
    /// through the selected strategy. The main key is also the last-resort
    /// fallback when every pooled key is parked.
    func lease(for instanceId: String, excluding: Set<String> = []) -> ProviderKeyLease? {
        // Synchronous compatibility entry is for utility/request workers only.
        // An accidental UI caller must not perform Keychain XPC on main.
        guard !Thread.isMainThread else { warm(instanceId); return nil }
        let main = ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        // Immutable ring snapshot. No reader/selection mutex spans storage I/O.
        let ring = unlockedKeys(instanceId)
        guard storedEnabled(for: instanceId), !ring.isEmpty else {
            return main.isEmpty || excluding.contains("main") ? nil : ProviderKeyLease(id: "main", key: main)
        }
        let now = Date()
        var pool: [(lease: ProviderKeyLease, uses: Int)] = []
        var seen = Set<String>()
        // [T-multikey-all-keys] When the switch is ON, every key in the pool
        // follows the selected strategy — the saved credential (主 Key) and
        // the added rotation keys alike. Switch OFF (or an empty ring) is the
        // normal single-key path and never reaches this block. The main key is
        // also the last-resort fallback when every pooled key is parked.
        if !main.isEmpty {
            seen.insert(main)
            let state = mainState(main, instanceId: instanceId)
            if !excluding.contains("main"), state.unavailableUntil.map({ $0 <= now }) ?? true {
                pool.append((ProviderKeyLease(id: "main", key: main), state.successCount + state.failureCount))
            }
        }
        for entry in ring {
            let key = entry.key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, seen.insert(key).inserted else { continue }
            guard !excluding.contains(entry.id), entry.isSelectable(recoveryInterval: Self.recoveryInterval, now: now) else { continue }
            pool.append((ProviderKeyLease(id: entry.id, key: key), entry.successCount + entry.failureCount))
        }
        guard !pool.isEmpty else {
            // [T-multikey-last-resort] Every ring key is parked or disabled.
            // The saved credential may still be the only funded key (the
            // reported 晨光 case: two empty ring keys plus one working main).
            // Reporting "no usable Key" without trying it made a good key look
            // broken for the whole cooldown. Try main once; a real provider
            // error is more useful than the synthetic one, and `excluding`
            // still prevents a same-request retry loop.
            guard !main.isEmpty, !excluding.contains("main") else { return nil }
            return ProviderKeyLease(id: "main", key: main)
        }
        switch strategy(for: instanceId) {
        case .priority:
            // The user's "first key" is the main credential, then the ring
            // keys in list order. Do not rotate on success; only a parked,
            // disabled or failed key is skipped.
            return pool[0].lease
        case .random: return pool.randomElement()?.lease
        case .leastUsed: return pool.min { $0.uses < $1.uses }?.lease
        case .roundRobin:
            let index = reserveCursor(for: instanceId, count: pool.count)
            return pool[index].lease
        }
    }

    private func increment(_ count: Int) -> Int { count < Int.max ? max(0, count) + 1 : Int.max }

    func recordSuccess(lease: ProviderKeyLease, for instanceId: String) {
        if Thread.isMainThread {
            DispatchQueue.global(qos: .utility).async { self.recordSuccess(lease: lease, for: instanceId) }
            return
        }
        if lease.id == "main" {
            guard ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key else { return }
            let seeded = mainState(lease.key, instanceId: instanceId) // storage outside lock
            lock.lock()
            guard var state = mainSnapshots[instanceId], state.fingerprint == seeded.fingerprint else { lock.unlock(); return }
            state.successCount = increment(state.successCount)
            if state.lastFailureAt.map({ $0 <= lease.startedAt }) ?? true {
                state.consecutiveFailures = 0; state.unavailableUntil = nil
            }
            mainSnapshots[instanceId] = state
            bump(instanceId, .main)
            lock.unlock()
            schedulePersistence(for: instanceId)
        } else {
            let now = Date()
            mutateKeys(for: instanceId) { list in
                guard let index = list.firstIndex(where: { $0.id == lease.id && $0.key.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key }) else { return }
                list[index].successCount = increment(list[index].successCount)
                list[index].lastUsed = now
                // A success older than a newer failure/manual edit cannot
                // reactivate or overwrite a parked/replaced key.
                if list[index].updatedAt <= lease.startedAt {
                    list[index].consecutiveFailures = 0; list[index].lastError = nil
                    list[index].unavailableUntil = nil
                    if list[index].isEnabled && list[index].status != .disabled { list[index].status = .active }
                }
            }
        }
    }

    func recordFailure(lease: ProviderKeyLease, kind: MultiKeyFailureKind, for instanceId: String) {
        // Network failures do not rotate/park, but still need lastError and
        // counters in the Key UI. A 413 is about the request, not the key, and
        // is deliberately not recorded.
        // Network failure is diagnostic-only: do not increment a credential's
        // failure/cooldown counters or rotate it. The retry wrapper owns the
        // same-lease retry after a path change.
        guard kind != .network, kind.mayTryAnotherKey else { return }
        if Thread.isMainThread {
            DispatchQueue.global(qos: .utility).async { self.recordFailure(lease: lease, kind: kind, for: instanceId) }
            return
        }
        let now = Date()
        let summary = kind.summary // localization may read preferences; outside lock
        func cooldown(_ failures: Int) -> TimeInterval? {
            switch kind {
            case .credential, .quota: return Self.recoveryInterval
            case .forbidden: return nil
            case .rateLimit: return 60
            case .transient: return failures >= Self.maxConsecutiveFailures ? 30 : nil
            case .gatewayTimeout: return failures >= Self.maxConsecutiveFailures ? 30 : nil
            case .network, .requestTooLarge, .other: return nil
            }
        }
        if lease.id == "main" {
            guard ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)?.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key else { return }
            let seeded = mainState(lease.key, instanceId: instanceId)
            lock.lock()
            guard var state = mainSnapshots[instanceId], state.fingerprint == seeded.fingerprint else { lock.unlock(); return }
            state.failureCount = increment(state.failureCount)
            state.consecutiveFailures = increment(state.consecutiveFailures)
            state.lastFailureAt = now
            if let seconds = cooldown(state.consecutiveFailures) { state.unavailableUntil = now.addingTimeInterval(seconds) }
            mainSnapshots[instanceId] = state
            bump(instanceId, .main)
            lock.unlock()
            schedulePersistence(for: instanceId)
        } else {
            mutateKeys(for: instanceId) { list in
                guard let index = list.firstIndex(where: { $0.id == lease.id && $0.key.trimmingCharacters(in: .whitespacesAndNewlines) == lease.key }) else { return }
                list[index].failureCount = increment(list[index].failureCount)
                list[index].consecutiveFailures = increment(list[index].consecutiveFailures)
                list[index].lastUsed = now; list[index].updatedAt = now; list[index].lastError = summary
                if let seconds = cooldown(list[index].consecutiveFailures) {
                    list[index].unavailableUntil = now.addingTimeInterval(seconds)
                    if list[index].isEnabled && list[index].status != .disabled { list[index].status = .error }
                }
            }
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
            let idx = reserveCursor(for: instanceId, count: usable.count)
            chosen = usable[idx]
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
