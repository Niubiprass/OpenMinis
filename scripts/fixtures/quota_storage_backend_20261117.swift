// Dependency injection only. Production Defaults/codec/writer methods are
// extracted unchanged. Private Foundation suite; no app preferences/accounts.
final class StorageGate: @unchecked Sendable {
    private let mutex = NSLock()
    private let releaseSemaphore = DispatchSemaphore(value: 0)
    private var arrived = false
    func pause() {
        mutex.lock(); arrived = true; mutex.unlock()
        if releaseSemaphore.wait(timeout: .now() + 10) != .success { fatalError("storage gate timed out") }
    }
    func waitForArrival() async {
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            mutex.lock(); let value = arrived; mutex.unlock()
            if value { return }
            await Task.yield()
        }
        fatalError("real storage entry was not reached")
    }
    func release() { releaseSemaphore.signal() }
}
final class FixtureDefaults: @unchecked Sendable {
    let suite = Foundation.UserDefaults(suiteName: "com.openminis.quota-storage." + UUID().uuidString)!
    private let mutex = NSLock()
    private var gates: [String: StorageGate] = [:]
    func arm(_ operation: String, key: String, gate: StorageGate) {
        mutex.lock(); gates[operation + key] = gate; mutex.unlock()
    }
    private func enter(_ operation: String, key: String) {
        mutex.lock(); let gate = gates.removeValue(forKey: operation + key); mutex.unlock()
        gate?.pause()
    }
    func set(_ value: Any?, forKey key: String) {
        enter("set", key: key); suite.set(value, forKey: key)
        // Deterministic equivalent of synchronous Defaults notification delivery
        // to a .main observer (not a claim about any iOS private system stack).
        NotificationCenter.default.post(name: Foundation.UserDefaults.didChangeNotification, object: suite)
    }
    func removeObject(forKey key: String) {
        enter("remove", key: key); suite.removeObject(forKey: key)
        NotificationCenter.default.post(name: Foundation.UserDefaults.didChangeNotification, object: suite)
    }
    func data(forKey key: String) -> Data? { enter("read", key: key); return suite.data(forKey: key) }
    func dictionaryRepresentation() -> [String: Any] { suite.dictionaryRepresentation() }
}
enum UserDefaults { static let standard = FixtureDefaults() }
