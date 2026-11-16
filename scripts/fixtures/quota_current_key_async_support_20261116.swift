// Synthetic dependencies only; no URLSession, UIKit, Keychain or real account.
// The asynchronous methods themselves are extracted from production unchanged.
struct ProviderInstance: Sendable {
    enum CredentialType: Sendable { case apiKey }
    let id: String; var isEnabled = true; var root = "https://quota.invalid"; var label = "synthetic"
    var credentialType = CredentialType.apiKey
}
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
struct ProviderAPIKey {
    let id: String; var key: String; var isEnabled = true; var status = SyntheticKeyStatus.active
    var successCount = 0; var lastUsed: Date?; var masked: String { "synthetic-mask" }
}
// Synthetic dependency gate: delays the usage read AFTER real quotaRows has
// captured its rows. No gate/code is spliced into a production method.
final class FixtureReadGate: @unchecked Sendable {
    private let mutex = NSLock(), semaphore = DispatchSemaphore(value: 0)
    private var arrived = false
    func pause() {
        mutex.lock(); arrived = true; mutex.unlock()
        if semaphore.wait(timeout: .now() + 10) != .success { fatalError("usage gate timeout") }
    }
    func waitForArrival() async {
        let limit = Date().addingTimeInterval(10)
        while Date() < limit {
            mutex.lock(); let value = arrived; mutex.unlock()
            if value { return }; await Task.yield()
        }
        fatalError("usage read never arrived")
    }
    func release() { semaphore.signal() }
}
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
    private var usageGates: [String: (Int, FixtureReadGate)] = [:]
    func isEnabled(for id: String) -> Bool { true }
    func isActiveAsync(for id: String) async -> Bool { !keys(for: id).isEmpty }
    func keys(for id: String) -> [ProviderAPIKey] {
        lock.lock()
        let result = values[id] ?? []
        var gate: FixtureReadGate?
        if let (remaining, value) = usageGates[id] {
            if remaining == 1 { gate = value; usageGates.removeValue(forKey: id) }
            else { usageGates[id] = (remaining - 1, value) }
        }
        lock.unlock(); gate?.pause(); return result
    }
    func pauseProjectionUsage(id: String, at gate: FixtureReadGate) {
        lock.lock(); usageGates[id] = (2, gate); lock.unlock()
    }
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
    private var emptyRows = Set<String>()
    private var collects: [String: Int] = [:]
    func didCollect(_ contextID: String) { collects[contextID, default: 0] += 1 }
    func count(_ contextID: String) -> Int { collects[contextID] ?? 0 }
    func emptyNextCollect(_ row: String) { emptyRows.insert(row) }
    func takeEmpty(_ row: String) -> Bool { emptyRows.remove(row) != nil }
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
        await FixturePlan.shared.didCollect(context.owner)
        if let gate = await FixturePlan.shared.takeCollect(context.rowId) { await gate.wait() }
        if await FixturePlan.shared.takeEmpty(context.rowId) { return .init(owner: context.owner, readings: [], attempts: []) }
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
    func scheduleAutomatic(_ id: String, expectedEpoch: UUID? = nil,
                           validatedOrigin: ProviderQuotaCurrentKeyPolicy.Origin? = nil,
                           replacing: Bool = true) async {
        lock.lock(); scheduledCount[id, default: 0] += 1; lock.unlock()
    }
    static func logRefresh(instanceId: String, rowId: String, info: QuotaInfo?, note: String?) {}
    func inspect<T>(_ read: (CacheAsyncHarness) -> T) -> T {
        lock.lock(); defer { lock.unlock() }; return read(self)
    }
    // Fixture-only asynchronous fence. Production/UI never waits for storage.
    func flushWriter() async {
        schedulePersistence()
        await withCheckedContinuation { continuation in
            writer.async { continuation.resume() }
        }
    }
    func setup(_ modify: (CacheAsyncHarness) -> Void) {
        lock.lock(); modify(self); lock.unlock()
    }
}
