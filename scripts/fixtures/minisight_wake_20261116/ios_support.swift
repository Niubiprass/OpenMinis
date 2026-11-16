import Foundation
import Combine
import AVFoundation

// Typecheck-only dependencies outside this feature. No fake KWS/audio runtime
// is executed: production wake sources are checked against the real Apple SDK,
// real MiniSightChatPanel header and real SherpaOnnxC module below.
@MainActor final class MiniSightConfigStore: ObservableObject {
    static let shared = MiniSightConfigStore()
    @Published var style = 1
    @Published var renderer = 1
    @Published var wakeEnabled = false
    @Published var wakeName = ""
    @Published var wakePronunciation = ""
    var appearancePreferencesForWake: [String: Any] { [:] }
    func saveWakeIdentity(_ value: MiniSightWakeName.Prepared) {}
}
enum MiniSightSettingKey {
    static let style = "minisight.style"
    static let renderer = "minisight.renderer"
    static let shown = "minisight.shown"
    static let shownRevision = "minisight.settings.revision"
    static let wakeEnabled = "minisight.wake.enabled"
    static let wakeName = "minisight.wake.name"
    static let wakePronunciation = "minisight.wake.pronunciation"
}
@MainActor final class SessionLockStore: ObservableObject {
    static let shared = SessionLockStore()
    @Published private(set) var appIsLocked = false
}
@MainActor final class MiniSightVoiceBridge {
    static let shared = MiniSightVoiceBridge()
    func cancelNameWake(generation: Int) {}
    func resumeRequestedVoice() {}
}
@MainActor final class SpeechRecognitionManager: ObservableObject {
    enum State: Equatable { case idle, recording }
    static let shared = SpeechRecognitionManager()
    @Published private(set) var state = State.idle
    var backgroundRecognitionHasLiveAudio: Bool { false }
    var permissionsAlreadyGranted: Bool { false }
    func requestPermissions() async -> Bool { false }
}
@MainActor final class AudioSessionCoordinator {
    enum Intent { case wakeWord, nameWakeDictation }
    static let shared = AudioSessionCoordinator()
    static let stateChangedNotification = Notification.Name("AudioSession.fixture")
    var onWakeWordPreempted: (@MainActor () -> Void)?
    var canBeginWakeWordListening: Bool { false }
    var appliedIntent: Intent? { nil }
    func begin(_ intent: Intent) {}
    func beginWakeWordListening(completion: @escaping (Bool)->Void) {}
    func end(_ intent: Intent) {}
}
func noff_try_objc(_ body: () -> Void) -> Bool { true }
