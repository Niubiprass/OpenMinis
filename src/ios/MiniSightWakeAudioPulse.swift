import Foundation

/// Real tap heartbeat only; never stores waveforms or user speech. Lock guards
/// callback/MAIN access. Deliberately independent of any enabled/intent flag.
final class MiniSightWakeAudioPulse: @unchecked Sendable {
    private let lock = NSLock()
    private var token: UUID?
    private var detectionToken: UUID?
    private var lastFrame: Double?
    func begin(inputToken: UUID) {
        lock.lock(); defer { lock.unlock() }
        token = inputToken; detectionToken = nil; lastFrame = nil
    }
    func setDetectionToken(_ token: UUID?) {
        lock.lock(); defer { lock.unlock() }
        detectionToken = token
    }
    func markFrame(inputToken: UUID, now: Double) -> UUID? {
        lock.lock(); defer { lock.unlock() }
        guard token == inputToken, now.isFinite else { return nil }
        lastFrame = now
        return detectionToken
    }
    func isFresh(now: Double) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard token != nil, let lastFrame, now.isFinite, now >= lastFrame else { return false }
        return now - lastFrame <= 2
    }
    func stop() {
        lock.lock(); defer { lock.unlock() }
        token = nil; detectionToken = nil; lastFrame = nil
    }
}
