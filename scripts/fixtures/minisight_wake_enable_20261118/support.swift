import Foundation

// Synthetic dependencies only. Never use runner/device defaults, permission UI,
// AVFoundation, an audio engine, a panel, files, network or a real user's name.
@MainActor final class UserDefaults {
    static let standard = UserDefaults()
    var values = [String: Any]()
    func set(_ value: Any, forKey key: String) { values[key] = value }
    func string(forKey key: String) -> String? { values[key] as? String }
    func bool(forKey key: String) -> Bool { values[key] as? Bool ?? false }
    func integer(forKey key: String) -> Int { values[key] as? Int ?? 0 }
}
enum MiniSightSettingKey {
    static let style = "synthetic.style", wakeEnabled = "synthetic.enabled"
    static let wakeName = "synthetic.name", wakePronunciation = "synthetic.reading"
}
@MainActor final class UIApplication {
    enum State { case active, inactive, background }
    static let shared = UIApplication()
    var applicationState = State.active
    var isProtectedDataAvailable = true
}
@MainActor final class SessionLockStore {
    static let shared = SessionLockStore()
    var appIsLocked = false
}
enum MiniSightWakeName {
    struct Prepared { let name: String; let pronunciation: String }
}
@MainActor final class MiniSightConfigStore {
    static let shared = MiniSightConfigStore()
    var wakeEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled) }
        set { UserDefaults.standard.set(newValue, forKey: MiniSightSettingKey.wakeEnabled) }
    }
    var wakeName: String { UserDefaults.standard.string(forKey: MiniSightSettingKey.wakeName) ?? "" }
    var wakePronunciation: String { UserDefaults.standard.string(forKey: MiniSightSettingKey.wakePronunciation) ?? "" }
    func saveWakeIdentity(_ value: MiniSightWakeName.Prepared) {
        UserDefaults.standard.set(value.name, forKey: MiniSightSettingKey.wakeName)
        UserDefaults.standard.set(value.pronunciation, forKey: MiniSightSettingKey.wakePronunciation)
    }
}
final class SyntheticInput { var isRunning = false }
final class SyntheticDetector { var stops = 0; func stop() { stops += 1 } }
final class SyntheticTimer { func invalidate() {} }

@MainActor final class EnableController {
    enum Phase { case stopped, failed, holding, acknowledging, listening }
    let input = SyntheticInput(), detector = SyntheticDetector()
    let pulse = MiniSightWakeAudioPulse()
    var remoteCycle: Int?, namedGeneration: Int?
    var companionTransitionUntil: Double = 0
    var installed = true, endingCycle = false
    var refreshes = 0
    var phase = Phase.stopped
    var status = "", resolvedPronunciation = ""
    var settingsIdentity = "", savingIdentity = false
    var enableGeneration = 0, permissionPending = false
    var permissionTask: Task<Void, Never>?
    var timer: SyntheticTimer?
    var foreground = true, appLocked = false, protectedDataUnavailable = false
    var shown = true, hasAsset = true, armed = false, failureLatched = false
    var pauses = 0
    var validations = [(Result<MiniSightWakeName.Prepared, Error>) -> Void]()
    func install() {}
    func pause(reason: String) { pauses += 1; status = reason; phase = .stopped }
    func updateTimer() {}
    func pollRemoteState() {}
    func refresh() {
        // PRODUCTION_REFRESH_PREFIX
        refreshes += 1 // observation only; does not model policy or start audio
    }
    func backgroundNotification() { applicationDidEnterBackground() }
    func activeNotification() { applicationChanged(active: true) }
    func protectedDataNotification() {
        protectedDataUnavailable = true
        invalidatePendingEnableIfUnsafe()
        pause(reason: "synthetic protection event")
    }
    func lockNotification(_ locked: Bool) { appLocked = locked; refresh() }
    func validate(name: String, pronunciation: String,
                  completion: @escaping (Result<MiniSightWakeName.Prepared, Error>) -> Void) {
        validations.append(completion)
    }
    func validated() {
        let pending = validations; validations.removeAll()
        for callback in pending {
            callback(.success(.init(name: "合成", pronunciation: "he cheng")))
        }
    }
    func defaultsChanged() { settingsChanged() }
    // PRODUCTION_METHODS: byte-for-byte requestEnabled, saveName, settingsChanged.
}
