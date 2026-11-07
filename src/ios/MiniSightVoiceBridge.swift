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
    private var activeGeneration = 0
    private var nextGeneration = 0
    private var writeQueue = DispatchQueue(label: "com.openminis.minisight.voice.files")
    private var speechDeadline: Task<Void, Never>?
    private var files = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("MiniSight")

    func resumeRequestedVoice() {
        install()
        handleRequest()
    }

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
                // Emit before clearing `listening`; emit intentionally rejects
                // callbacks from an old/non-active recognition generation.
                self.emit(manager.recognizedText, final: true, generation: self.activeGeneration)
                self.listening = false
                self.speechDeadline?.cancel()
            }
            .store(in: &bag)
    }

    private func handleRequest() {
        guard let data = try? Data(contentsOf: files.appendingPathComponent("voice.json")),
              data.count <= 4096,
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let generation = object["generation"] as? Int, generation > 0,
              let action = object["action"] as? String else { return }
        if action == "stop" || action == "cancel" {
            guard generation == activeGeneration else { return }
            nextGeneration &+= 1
            if action == "cancel" {
                let wasListening = listening
                listening = false
                speechDeadline?.cancel()
                if wasListening { SpeechRecognitionManager.shared.stopRecording() }
                write(result: "", final: true, reason: "cancelled", generation: generation, state: "cancelled")
            } else { stop() }
            return
        }
        guard action == "start", generation != activeGeneration else { return }
        if listening && SpeechRecognitionManager.shared.state == .recording {
            activeGeneration = generation
            SpeechRecognitionManager.shared.stopRecording()
            return
        }
        guard !listening && SpeechRecognitionManager.shared.state != .recording else {
            write(result: "", final: true, reason: "microphone_busy", generation: generation, state: "failed")
            return
        }
        activeGeneration = generation
        nextGeneration &+= 1
        let lease = nextGeneration
        // Acknowledge immediately, including while the system permission sheet
        // is open. The plugin must not assume silence means no App is running.
        write(result: "", final: false, reason: nil, generation: generation, state: "starting")
        Task { await startListening(generation: generation, lease: lease) }
    }

    private func startListening(generation: Int, lease: Int) async {
        let manager = SpeechRecognitionManager.shared
        guard await manager.requestPermissions() else {
            write(result: "", final: true, reason: "permission", generation: generation, state: "failed")
            MSDiagEvent("voice", "start", "failed", ["source": "app", "generation": generation, "reason": "permission"])
            return
        }
        guard generation == activeGeneration, lease == nextGeneration, !Task.isCancelled else {
            if generation == activeGeneration && !listening {
                write(result: "", final: true, reason: "stopped", generation: generation, state: "finished")
            }
            return
        }
        guard manager.isAvailable else {
            write(result: "", final: true, reason: "recognizer_unavailable", generation: generation, state: "failed")
            return
        }
        manager.recognizedText = ""
        do {
            listening = true
            try manager.startRecording()
            write(result: "", final: false, reason: nil, generation: generation, state: "listening")
            speechDeadline?.cancel()
            speechDeadline = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 45_000_000_000) } catch { return }
                guard let self, self.activeGeneration == generation, self.listening else { return }
                self.stop()
            }
            MSDiagEvent("voice", "start", "ok", ["source": "app", "generation": generation, "reason": "app_listening"])
        } catch {
            listening = false
            write(result: "", final: true, reason: "engine", generation: generation, state: "failed")
            MSDiagEvent("voice", "start", "failed", ["source": "app", "generation": generation, "reason": "engine", "code": (error as NSError).code])
        }
    }

    /// Called by the UI when the user stops holding the mic.
    func stop() {
        guard listening else { return }
        speechDeadline?.cancel()
        SpeechRecognitionManager.shared.stopRecording()
    }

    private func emit(_ text: String, final: Bool, generation: Int? = nil) {
        guard listening, generation == nil || generation == activeGeneration else { return }
        write(result: text, final: final, reason: final && text.isEmpty ? "empty_transcript" : nil,
              generation: activeGeneration, state: final ? "finished" : "partial")
    }

    private func write(result: String, final: Bool, reason: String?, generation: Int, state: String) {
        var payload: [String: Any] = ["text": String(result.prefix(2000)), "final": final,
                                     "generation": generation, "state": state]
        if let reason { payload["reason"] = reason }
        let dir = files
        let snapshot = payload
        let resultNote = Self.resultNote
        writeQueue.async {
            do {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let data = try JSONSerialization.data(withJSONObject: snapshot)
                try data.write(to: dir.appendingPathComponent("voice-result.json"), options: .atomic)
                CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                    CFNotificationName(resultNote as CFString), nil, nil, true)
            } catch {
                MSDiagEvent("voice", "deliver", "failed", ["source": "app", "generation": generation,
                                                           "code": (error as NSError).code])
            }
        }
    }
}
