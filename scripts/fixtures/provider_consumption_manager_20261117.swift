final class ProviderMultiKeyManager: @unchecked Sendable {
    static let shared = ProviderMultiKeyManager()
    static let recoveryInterval: TimeInterval = 300
    static let didSucceed = Notification.Name("ProviderMultiKeyManager.didSucceed")
    let lock = NSLock()
    var keySnapshots: [String: [ProviderAPIKey]] = [:]
    var mainSnapshots: [String: MainState] = [:]
    var cursorSnapshots: [String: Int] = [:]
    var enabledSnapshots: [String: Bool] = [:]
    var strategySnapshots: [String: MultiKeyStrategy] = [:]
    var leases = 0
    var failures = 0
    let cursorPrefix = "consumption.synthetic.cursor."
    enum Dirty { case main, ring, cursor }
    func put(_ keys: [ProviderAPIKey], id: String, enabled: Bool = true, strategy: MultiKeyStrategy = .roundRobin) {
        lock.lock(); keySnapshots[id] = keys; enabledSnapshots[id] = enabled; strategySnapshots[id] = strategy; lock.unlock()
    }
    func keys(for id: String) -> [ProviderAPIKey] { lock.lock(); defer { lock.unlock() }; return keySnapshots[id] ?? [] }
    func isEnabled(for id: String) -> Bool { storedEnabled(for: id) }
    func storedEnabled(for id: String) -> Bool { lock.lock(); defer { lock.unlock() }; return enabledSnapshots[id] ?? false }
    func strategy(for id: String) -> MultiKeyStrategy { lock.lock(); defer { lock.unlock() }; return strategySnapshots[id] ?? .roundRobin }
    func bump(_ id: String, _ domain: Dirty) {}
    func schedulePersistence(for id: String) {}
    func mutateKeys(for id: String, quotaCredentialsUnchanged: Bool = false, _ mutate: (inout [ProviderAPIKey]) -> Void) {
        lock.lock(); var keys = keySnapshots[id] ?? []; mutate(&keys); keySnapshots[id] = keys; lock.unlock()
    }
    func warm(_ id: String) {}
    func isActiveAsync(for id: String) async -> Bool {
        if let gate = await ConsumptionPlan.shared.takeActive() { await gate.wait() }
        return storedEnabled(for: id) && !keys(for: id).isEmpty
    }
    func keysAsync(for id: String) async -> [ProviderAPIKey] { keys(for: id) }
    func primaryKeyAsync(for id: String) async -> String? {
        ProviderKeychainHelper.loadAPIKey(instanceId: id)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    func leaseAsync(for id: String, excluding: Set<String> = []) async -> ProviderKeyLease? {
        await Task.detached {
            self.lock.lock(); self.leases += 1; self.lock.unlock()
            return self.lease(for: id, excluding: excluding)
        }.value
    }
    func validatedRetryLeaseAsync(_ lease: ProviderKeyLease, for id: String) async -> ProviderKeyLease? { lease }
    func recordFailure(lease: ProviderKeyLease, kind: MultiKeyFailureKind, for id: String) {
        lock.lock(); failures += 1; lock.unlock()
    }
    func counts() -> (Int, Int) { lock.lock(); defer { lock.unlock() }; return (leases, failures) }
    // PRODUCTION MEMBERS
}
