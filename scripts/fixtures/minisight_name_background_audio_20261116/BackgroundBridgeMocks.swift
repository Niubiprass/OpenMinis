// Synthetic dependencies; runner injects unchanged production BKA members.
// No AVFoundation/Speech, live microphone, App launch, device or network.
import Foundation

final class AnyCancellable: Hashable {
    static func == (lhs: AnyCancellable, rhs: AnyCancellable) -> Bool { lhs === rhs }
    func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}
func MSDiagEvent(_ domain: String, _ action: String, _ result: String, _ fields: [String: Any]) {}
final class VoiceModePreference {
    static let shared = VoiceModePreference()
    var isCapturing = false
}
final class GlobalAudioPlayer {
    static let shared = GlobalAudioPlayer()
    var isPlaying = false
}
final class VoiceOutputState {
    static let shared = VoiceOutputState()
    var isReadingAloud = false
    var speechPaused = false
}
final class SessionActivityTracker {
    static let shared = SessionActivityTracker()
    var activeSessions: [Int] = []
}
final class AVAudioPlayerNode {
    var isPlaying = false
    func stop() { isPlaying = false }
}

@MainActor final class BackgroundKeepAliveManager {
    static let shared = BackgroundKeepAliveManager()
    var isActive = true
    var enhancedBackgroundEnabled = true
    var backgroundSpeakEnabled = true
    var appIsInBackground = true
    var silentAudioSuspendCount = 0
    var audioEngine: AVAudioEngine?
    var silentPlayerNode: AVAudioPlayerNode?
    var silentAudioActive = false
    var silentAudioStartToken: UUID?
    var silentAudioRetry: DispatchWorkItem?
    var silentAudioActivationRetries = 0
    private let logger = AppLogger(category: "BKA mock")
    func cancelPendingSilentAudioStop(reason: String) {}
    func cancelIdleGrace(reason: String) {}
    func stopAudioUpdateTimer() {}
    func recordBKAEvent(_ event: String) { EventLog.shared.append(event) }
    // PRODUCTION_BKA_MEMBERS
}

// MAIN API contract only, deliberately not a simulation of its privacy policy.
@MainActor final class MiniSightWakeController {
    static let shared = MiniSightWakeController()
    var allowClaim = true
    var physicalPassiveInput = false
    var physicalResponseTTS = false
    var claimCalls: [Int] = []
    var startedCalls: [Int] = []
    var endedCalls: [Int] = []
    var namedGeneration: Int?
    var rearmWakeOnEnd = false // Injected effect only; no privacy-policy simulation.
    var backgroundAudioIsLive: Bool {
        physicalPassiveInput || physicalResponseTTS
            || (namedGeneration != nil && SpeechRecognitionManager.shared.backgroundRecognitionHasLiveAudio)
    }
    func claimNameWakeVoice(token: String, generation: Int) -> Bool {
        claimCalls.append(generation)
        EventLog.shared.append("claim-name")
        guard allowClaim else { return false }
        physicalPassiveInput = false
        namedGeneration = generation
        return true
    }
    func awaitsNameWakeReply(token: String) -> Bool { false }
    func nameWakeVoiceStarted(generation: Int) { startedCalls.append(generation) }
    func nameWakeVoiceEnded(generation: Int) {
        endedCalls.append(generation)
        if namedGeneration == generation {
            namedGeneration = nil
            if rearmWakeOnEnd { AudioSessionCoordinator.shared.begin(.wakeWord) }
        }
    }
}
