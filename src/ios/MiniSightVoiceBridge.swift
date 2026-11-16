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
    private var manualStartPending = false
    private struct NamedSession {
        let token: String
        let generation: Int
        let lease: Int
        var started = false
    }
    private var namedSession: NamedSession?
    private var namedStartTask: Task<Void, Never>?
    private var lastNamedRequest: (token: String, generation: Int)?
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
                guard state == .idle else { return }
                self?.recordingBecameIdle(manager)
            }
            .store(in: &bag)
    }

    private func recordingBecameIdle(_ manager: SpeechRecognitionManager) {
        // receive(on:) can deliver an obsolete idle after a newer engine starts.
        guard manager.state == .idle, listening else { return }
        if let session = namedSession, session.generation == activeGeneration {
            finishNameWake(generation: session.generation, lease: session.lease,
                           result: manager.recognizedText,
                           reason: manager.recognizedText.isEmpty ? "empty_transcript" : nil,
                           state: "finished")
        } else {
            emit(manager.recognizedText, final: true, generation: activeGeneration)
            listening = false
            speechDeadline?.cancel()
        }
    }

    private func handleRequest() {
        let requestURL = files.appendingPathComponent("voice.json")
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: requestURL.path),
              attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber, size.intValue <= 4096,
              let data = try? Data(contentsOf: requestURL), data.count <= 4096,
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let generation = object["generation"] as? Int, generation > 0,
              let action = object["action"] as? String else { return }
        if object["source"] as? String == "nameWake" {
            // Missing/malformed tokens NEVER fall through to manual permission.
            guard let token = object["nameWakeToken"] as? String,
                  token.count == 36, UUID(uuidString: token)?.uuidString == token else { return }
            handleNameWakeRequest(action: action, token: token, generation: generation)
            return
        }
        // An explicit manual start may take over, but manual stop/cancel must
        // never terminate a named lease just because integer generations collide.
        if let session = namedSession {
            guard action == "start" else { return }
            cancelNameWake(generation: session.generation)
        }
        if action == "stop" || action == "cancel" {
            guard generation == activeGeneration else { return }
            nextGeneration &+= 1
            manualStartPending = false
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
        manualStartPending = true
        // Acknowledge immediately, including while the system permission sheet
        // is open. The plugin must not assume silence means no App is running.
        write(result: "", final: false, reason: nil, generation: generation, state: "starting")
        Task { await startListening(generation: generation, lease: lease) }
    }

    private func handleNameWakeRequest(action: String, token: String, generation: Int) {
        if action == "stop" || action == "cancel" {
            guard let session = namedSession, session.token == token,
                  session.generation == generation else { return }
            if action == "cancel" { cancelNameWake(generation: generation) }
            else if session.started && listening { SpeechRecognitionManager.shared.stopNameWakeRecording() }
            else {
                finishNameWake(generation: generation, lease: session.lease, result: "",
                               reason: "stopped", state: "finished")
            }
            return
        }
        guard action == "start" else { return }
        if lastNamedRequest?.token == token && lastNamedRequest?.generation == generation { return }
        let manager = SpeechRecognitionManager.shared
        guard namedSession == nil, !listening, !manualStartPending,
              manager.state != .recording else {
            write(result: "", final: true, reason: "microphone_busy", generation: generation,
                  state: "failed", nameWakeToken: token)
            return
        }
        // Token/fresh response validation and physical detector stop belong to
        // MAIN. No starting acknowledgement, permission probe or mic precedes it.
        guard MiniSightWakeController.shared.claimNameWakeVoice(token: token, generation: generation) else {
            if MiniSightWakeController.shared.awaitsNameWakeReply(token: token) { return }
            write(result: "", final: true, reason: "name_wake_claim", generation: generation,
                  state: "failed", nameWakeToken: token)
            return
        }
        activeGeneration = generation
        nextGeneration &+= 1
        let lease = nextGeneration
        namedSession = NamedSession(token: token, generation: generation, lease: lease)
        manager.onNameWakeRecordingEnded = { [weak self, weak manager] in
            guard let manager else { return }
            self?.recordingBecameIdle(manager)
        }
        lastNamedRequest = (token, generation)
        write(result: "", final: false, reason: nil, generation: generation,
              state: "starting", nameWakeToken: token)
        namedStartTask = Task { [weak self] in
            guard let self else { return }
            await self.startNameWakeListening(generation: generation, lease: lease)
        }
    }

    private func startNameWakeListening(generation: Int, lease: Int) async {
        guard let session = namedSession, session.generation == generation, session.lease == lease,
              generation == activeGeneration, lease == nextGeneration, !Task.isCancelled else { return }
        let manager = SpeechRecognitionManager.shared
        // Never show authorization UI from a cross-App name request.
        guard manager.permissionsAlreadyGranted else {
            finishNameWake(generation: generation, lease: lease, result: "", reason: "permission", state: "failed")
            return
        }
        guard manager.isAvailable else {
            finishNameWake(generation: generation, lease: lease, result: "", reason: "recognizer_unavailable", state: "failed")
            return
        }
        manager.recognizedText = ""
        do {
            listening = true
            try manager.startRecording(nameWake: true)
            namedSession?.started = true
            guard manager.backgroundRecognitionHasLiveAudio else {
                throw NSError(domain: "MiniSightVoice", code: -1)
            }
            MiniSightWakeController.shared.nameWakeVoiceStarted(generation: generation)
            // MAIN can synchronously cancel on a privacy/settings race.
            guard namedSession?.lease == lease, listening else { return }
            write(result: "", final: false, reason: nil, generation: generation,
                  state: "listening", nameWakeToken: session.token)
            speechDeadline?.cancel()
            speechDeadline = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 45_000_000_000) } catch { return }
                guard let self, self.namedSession?.generation == generation,
                      self.namedSession?.lease == lease, self.listening else { return }
                SpeechRecognitionManager.shared.stopNameWakeRecording()
            }
        } catch {
            finishNameWake(generation: generation, lease: lease, result: "", reason: "engine", state: "failed")
        }
    }

    /// OFF/lock cancels ONLY the matched name-derived lease, including a queued
    /// async start. It never invalidates or stops a manual session.
    func cancelNameWake(generation: Int) {
        guard let session = namedSession, session.generation == generation else { return }
        finishNameWake(generation: generation, lease: session.lease, result: "",
                       reason: "cancelled", state: "cancelled")
    }

    private func finishNameWake(generation: Int, lease: Int, result: String, reason: String?, state: String) {
        guard let session = namedSession, session.generation == generation, session.lease == lease else { return }
        // Clear FIRST: state notifications, reentrant cancellation and late
        // continuations can never end the controller's named generation twice.
        namedSession = nil
        namedStartTask?.cancel(); namedStartTask = nil
        if activeGeneration == generation && nextGeneration == lease {
            nextGeneration &+= 1
            listening = false
            speechDeadline?.cancel(); speechDeadline = nil
        }
        // MAIN may insert the next passive owner while the old named lease is
        // still held. OFF/privacy clears MAIN's generation first and cannot resume.
        MiniSightWakeController.shared.nameWakeVoiceEnded(generation: generation)
        if session.started { SpeechRecognitionManager.shared.stopNameWakeRecording() }
        write(result: result, final: true, reason: reason, generation: generation,
              state: state, nameWakeToken: session.token)
    }

    private func startListening(generation: Int, lease: Int) async {
        defer {
            if generation == activeGeneration && lease == nextGeneration { manualStartPending = false }
        }
        let manager = SpeechRecognitionManager.shared
        guard await manager.requestPermissions() else {
            guard generation == activeGeneration, lease == nextGeneration else { return }
            write(result: "", final: true, reason: "permission", generation: generation, state: "failed")
            MSDiagEvent("voice", "start", "failed", ["source": "app", "generation": generation, "reason": "permission"])
            return
        }
        guard generation == activeGeneration, lease == nextGeneration, !Task.isCancelled else {
            if generation == activeGeneration && !listening && namedSession == nil {
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
        if namedSession != nil { SpeechRecognitionManager.shared.stopNameWakeRecording() }
        else { SpeechRecognitionManager.shared.stopRecording() }
    }

    private func emit(_ text: String, final: Bool, generation: Int? = nil) {
        guard listening, generation == nil || generation == activeGeneration else { return }
        if namedSession != nil && text != SpeechRecognitionManager.shared.recognizedText { return }
        write(result: text, final: final, reason: final && text.isEmpty ? "empty_transcript" : nil,
              generation: activeGeneration, state: final ? "finished" : "partial",
              nameWakeToken: namedSession?.token)
    }

    private func write(result: String, final: Bool, reason: String?, generation: Int, state: String,
                       nameWakeToken: String? = nil) {
        var payload: [String: Any] = ["text": String(result.prefix(2000)), "final": final,
                                     "generation": generation, "state": state]
        if let reason { payload["reason"] = reason }
        if let token = nameWakeToken {
            payload["source"] = "nameWake"
            payload["nameWakeToken"] = token
        }
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
