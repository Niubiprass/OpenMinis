// Sole extra dependency: thread-safe synthetic threshold, never app Defaults.
final class FixtureThreshold: @unchecked Sendable {
    static let shared = FixtureThreshold()
    private let mutex = NSLock()
    private var threshold: Double = 3
    func read() -> Double { mutex.lock(); defer { mutex.unlock() }; return threshold }
    func set(_ value: Double) { mutex.lock(); threshold = value; mutex.unlock() }
}
