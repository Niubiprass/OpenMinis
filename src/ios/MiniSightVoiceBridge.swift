import Combine
import CoreFoundation
import Foundation

/// Cross-process voice bridge. The SpringBoard panel asks the App to listen;
/// recognition uses the App's existing real-time Speech manager, so the bar
/// never has to raise the keyboard. Results stream back as files + Darwin
/// notes. A missing App is reported, never faked.
@MainActor
final class MiniSightVoiceBridge {
    static let shared = MiniSightVoiceBridge()
    static let requestNote = "com.openminis.minisight.voice"
    static let resultNote = "com.openminis.minisight.voice.result"

    private var observer: UnsafeMutablePointer<UInt8>?
    private var bag = Set<AnyCancellable>()
    private var listening = false
    private var files = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("MiniSight")

    func install() {
        guard observer == nil else { return }
        let pointer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1)
        observer = pointer
        CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
            pointer, { _, _, _, _, _ in
                Task { @MainActor in MiniSightVoiceBridge.shared.handleRequest() }
            }, Self.requestNote as CFString, nil, .deliverImmediately)
        let manager = SpeechRecognitionManager.shared
        manager.$recognizedText
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] text in self?.emit(text, final: false) }
            .store(in: &bag)
        manager.$state
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                guard state == .idle, let self, self.listening else { return }
                self.listening = false
                self.emit(manager.recognizedText, final: true)
            }
            .store(in: &bag)
    }

    private func handleRequest() {
        let data = try? Data(contentsOf: files.appendingPathComponent("voice.json"))
        let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        guard (object?["action"] as? String) == "start" else { return }
        Task { await startListening() }
    }

    private func startListening() async {
        let manager = SpeechRecognitionManager.shared
        if manager.state == .recording {
            manager.stopRecording()
            MSDiagEvent("voice", "stop", "ok", ["source": "app", "reason": "second_request"])
            return
        }
        guard await manager.requestPermissions() else {
            write(result: "", final: true, reason: "permission")
            MSDiagEvent("voice", "start", "failed", ["source": "app", "reason": "permission"])
            return
        }
        manager.recognizedText = ""
        do {
            try manager.startRecording()
            listening = true
            MSDiagEvent("voice", "start", "ok", ["source": "app", "reason": "app_listening"])
        } catch {
            write(result: "", final: true, reason: "engine")
            MSDiagEvent("voice", "start", "failed", ["source": "app", "reason": "engine", "code": (error as NSError).code])
        }
    }

    /// Called by the UI when the user stops holding the mic.
    func stop() {
        guard listening else { return }
        SpeechRecognitionManager.shared.stopRecording()
    }

    private func emit(_ text: String, final: Bool) {
        guard listening else { return }
        write(result: text, final: final, reason: nil)
    }

    private func write(result: String, final: Bool, reason: String?) {
        try? FileManager.default.createDirectory(at: files, withIntermediateDirectories: true)
        var payload: [String: Any] = ["text": String(result.prefix(2000)), "final": final]
        if let reason { payload["reason"] = reason }
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        try? data.write(to: files.appendingPathComponent("voice-result.json"), options: .atomic)
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(Self.resultNote as CFString), nil, nil, true)
    }
}
