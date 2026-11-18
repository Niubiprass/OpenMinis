import Foundation

// Only platform API boundaries are synthetic. The whole two-stage production
// requestPermissions body is inserted verbatim. No Speech/AVFoundation import,
// system permission UI, real recorder, defaults, device or user data is accessed.
enum SyntheticSpeechStatus { case authorized, denied, restricted }
@MainActor enum PermissionProbe {
    static var speechRequests = 0, modernMicRequests = 0, legacyMicRequests = 0
    static var speechReplies = [(SyntheticSpeechStatus) -> Void]()
    static var micReplies = [(Bool) -> Void]()
    static var modernAPI = true
    static var micRequests: Int { modernMicRequests + legacyMicRequests }
    static func speech(_ status: SyntheticSpeechStatus) {
        let pending = speechReplies; speechReplies.removeAll()
        for reply in pending { reply(status) }
    }
    static func microphone(_ granted: Bool) {
        let pending = micReplies; micReplies.removeAll()
        for reply in pending { reply(granted) }
    }
}
@MainActor enum SFSpeechRecognizer {
    static func requestAuthorization(_ callback: @escaping (SyntheticSpeechStatus) -> Void) {
        PermissionProbe.speechRequests += 1
        PermissionProbe.speechReplies.append(callback)
    }
}
@MainActor enum AVAudioApplication {
    static func requestRecordPermission() async -> Bool {
        PermissionProbe.modernMicRequests += 1
        return await withCheckedContinuation { continuation in
            PermissionProbe.micReplies.append { continuation.resume(returning: $0) }
        }
    }
}
@MainActor final class AVAudioSession {
    enum Permission { case granted, denied }
    static let shared = AVAudioSession()
    static func sharedInstance() -> AVAudioSession { shared }
    var recordPermission = Permission.granted
    func requestRecordPermission(_ callback: @escaping (Bool) -> Void) {
        PermissionProbe.legacyMicRequests += 1
        PermissionProbe.micReplies.append(callback)
    }
}
struct SyntheticLogger { func warning(_ text: String) {} }
@MainActor final class SpeechRecognitionManager {
    static let shared = SpeechRecognitionManager()
    let logger = SyntheticLogger()
    var permissionsAlreadyGranted = false, isAvailable = true
    var recognizedText = "synthetic draft", recordingStarts = 0
    var requests: Int { PermissionProbe.speechRequests }
    func startRecording() throws { recordingStarts += 1 } // observation only; NO engine
    // PRODUCTION_PERMISSION_METHOD
}
@MainActor func resetPermissions() {
    check(PermissionProbe.speechReplies.isEmpty && PermissionProbe.micReplies.isEmpty,
          "all already-presented synthetic permissions must be completed")
    PermissionProbe.speechRequests = 0; PermissionProbe.modernMicRequests = 0
    PermissionProbe.legacyMicRequests = 0
    let m = SpeechRecognitionManager.shared
    m.permissionsAlreadyGranted = false; m.recordingStarts = 0; m.recognizedText = "synthetic draft"
}
@MainActor func grantPermissions() async {
    PermissionProbe.speech(.authorized); await drain()
    PermissionProbe.microphone(true); await drain()
}
@MainActor func denySpeech() async { PermissionProbe.speech(.denied); await drain() }
