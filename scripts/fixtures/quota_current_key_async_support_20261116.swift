// Synthetic dependencies only; no URLSession, UIKit, Keychain or real account.
// The asynchronous methods themselves are extracted from production unchanged.
struct ProviderInstance: Sendable { let id: String; var isEnabled = true; var root = "https://quota.invalid" }
@MainActor final class ProviderConfigStore {
    static let shared = ProviderConfigStore()
    var values: [String: ProviderInstance] = [:]
    func instance(for id: String) -> ProviderInstance? { values[id] }
}
@MainActor final class UIApplication {
    enum State { case active, background }
    static let shared = UIApplication()
    var applicationState = State.active
}
enum SyntheticKeyStatus { case active, disabled }
struct ProviderAPIKey { let id: String; var key: String; var isEnabled = true; var status = SyntheticKeyStatus.active }
final class ProviderKeychainHelper {
    private static let lock = NSLock()
    private static var values: [String: String] = [:]
    static func loadAPIKey(instanceId: String) -> String? { lock.lock(); defer { lock.unlock() }; return values[instanceId] }
    static func put(_ key: String, id: String) { lock.lock(); values[id] = key; lock.unlock() }
}
final class ProviderMultiKeyManager {
    static let shared = ProviderMultiKeyManager()
    private let lock = NSLock()
    private var values: [String: [ProviderAPIKey]] = [:]
    func isEnabled(for id: String) -> Bool { true }
    func keys(for id: String) -> [ProviderAPIKey] { lock.lock(); defer { lock.unlock() }; return values[id] ?? [] }
    func put(_ keys: [ProviderAPIKey], id: String) { lock.lock(); values[id] = keys; lock.unlock() }
}
func AppLocalized(_ value: String) -> String { value }
struct SyntheticLogger { func info(_ value: String) {} }
actor FixtureGate {
    private var reached = false
    private var released = false
    private var arrival: [CheckedContinuation<Void, Never>] = []
    private var held: CheckedContinuation<Void, Never>?
    func wait() async {
        reached = true
        for item in arrival { item.resume() }; arrival.removeAll()
        if released { return }
        await withCheckedContinuation { held = $0 }
    }
    func waitForArrival() async {
        if reached { return }
        await withCheckedContinuation { arrival.append($0) }
    }
    func release() { released = true; held?.resume(); held = nil }
}
actor FixturePlan {
    static let shared = FixturePlan()
    private var contextGates: [String: FixtureGate] = [:]
    private var collectGates: [String: FixtureGate] = [:]
    func pauseContext(_ row: String, at gate: FixtureGate) { contextGates[row] = gate }
    func pauseCollect(_ row: String, at gate: FixtureGate) { collectGates[row] = gate }
    func takeContext(_ row: String) -> FixtureGate? { contextGates.removeValue(forKey: row) }
    func takeCollect(_ row: String) -> FixtureGate? { collectGates.removeValue(forKey: row) }
}
func checkAsync(_ value: @autoclosure () -> Bool, _ label: String) {
    if !value() { fatalError(label) }
}
func fixtureOwner(_ instance: ProviderInstance, row: String, key: String) -> String {
    let value = "synthetic:\(instance.id):\(row):\(key):\(instance.root)"
    return SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
}
extension CacheAsyncHarness {
    // Only the account-context dependencies are mocked; captured rows, epochs,
    // selection commits, ticket cleanup, deferred work and cache writes are real.
    static func context(for instance: ProviderInstance, key: String, rowId: String) async -> Context? {
        guard instance.isEnabled, !key.isEmpty else { return nil }
        let owner = fixtureOwner(instance, row: rowId, key: key)
        if let gate = await FixturePlan.shared.takeContext(rowId) { await gate.wait() }
        return Context(durableOwner: owner, rowId: rowId, root: instance.root, accountRoot: instance.root,
                       key: key, token: nil, uid: nil, cookie: nil, owner: owner, isRelay: true, anthropic: false)
    }
    static func collect(_ context: Context) async -> RelayQuotaProtocol.Snapshot {
        if let gate = await FixturePlan.shared.takeCollect(context.rowId) { await gate.wait() }
        let now = Date()
        let amount = context.rowId == "main" ? 1.10 : 2.31
        let reading = RelayQuotaProtocol.Reading(source: .sub2api, scope: .keyQuota,
            endpoint: "https://quota.invalid/v1/usage", relayHost: "quota.invalid", unit: .currency("USD"),
            unitEvidence: "synthetic fixture", quotaPerUnit: nil, scaleObservedAt: nil,
            remaining: amount, used: nil, total: nil, observedAt: now)
        let attempt = RelayQuotaProtocol.Attempt(source: .sub2api, endpoint: reading.endpoint,
                                               attemptedAt: now, succeeded: true, failureNote: nil)
        return .init(owner: context.owner, readings: [reading], attempts: [attempt])
    }
    func scheduleAutomatic(_ id: String) async {
        lock.lock(); scheduledCount[id, default: 0] += 1; lock.unlock()
    }
    static func logRefresh(instanceId: String, rowId: String, info: QuotaInfo?, note: String?) {}
    func inspect<T>(_ read: (CacheAsyncHarness) -> T) -> T {
        lock.lock(); defer { lock.unlock() }; return read(self)
    }
    func setup(_ modify: (CacheAsyncHarness) -> Void) {
        lock.lock(); modify(self); lock.unlock()
    }
}
