// Compiles production coordinator, ASR, voice bridge and BKA readback/stop bodies.
// MAIN/AV/Speech dependencies are explicitly synthetic; no hardware validation.
import Foundation

@main enum NameBackgroundAudioHarness {
    @MainActor static var assertions = 0
    @MainActor static func check(_ condition: @autoclosure () -> Bool, _ message: String) {
        assertions += 1
        precondition(condition(), message)
    }
    @MainActor static func wait(_ message: String, _ predicate: () -> Bool) async {
        for _ in 0..<1000 {
            if predicate() { return }
            try? await Task.sleep(nanoseconds: 2_000_000)
        }
        preconditionFailure("timed out: \(message)")
    }
    @MainActor static func wake(_ coordinator: AudioSessionCoordinator) async -> Bool {
        await withCheckedContinuation { c in coordinator.beginWakeWordListening { c.resume(returning: $0) } }
    }
    @MainActor static func idle(_ coordinator: AudioSessionCoordinator, _ speech: SpeechRecognitionManager) async {
        speech.stopRecording()
        for intent in [AudioSessionCoordinator.Intent.capture, .mediaAttachment, .replyTTS,
                       .nameWakeDictation, .wakeWord, .backgroundKeepAlive] { coordinator.end(intent) }
        await wait("idle") { !AVAudioSession.sharedInstance().isActive }
    }
    @MainActor static func permissions() -> Int {
        SFSpeechRecognizer.permissionRequests + AVAudioSession.sharedInstance().permissionRequests
            + AVAudioApplication.shared.permissionRequests
    }
    @MainActor static func request(_ bridge: MiniSightVoiceBridge, _ generation: Int, _ action: String = "start",
                                   source: String? = "nameWake", token: String? = "01234567-89AB-4CDE-8FAB-0123456789AB") throws {
        var payload: [String: Any] = ["generation": generation, "action": action]
        if let source { payload["source"] = source }
        if let token { payload["nameWakeToken"] = token }
        try JSONSerialization.data(withJSONObject: payload).write(to: bridge.files.appendingPathComponent("voice.json"))
        bridge.handleRequest()
    }
    @MainActor static func result(_ bridge: MiniSightVoiceBridge) -> [String: Any] {
        bridge.writeQueue.sync {}
        let data = try! Data(contentsOf: bridge.files.appendingPathComponent("voice-result.json"))
        return try! JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
    @MainActor static func expectNameFailure(_ speech: SpeechRecognitionManager) {
        do { try speech.startRecording(nameWake: true); preconditionFailure("expected name start failure") }
        catch {
            check(speech.state == .idle, "name failure idle")
            check(!speech.backgroundRecognitionHasLiveAudio, "name failure has no physical backing")
            check(!AudioSessionCoordinator.shared.hasIntent(.nameWakeDictation), "name failure releases own intent")
            check(speech.recognizedText == "kept draft", "name failure retains draft")
        }
    }
    @MainActor static func main() async throws {
        let coordinator = AudioSessionCoordinator.shared
        let speech = SpeechRecognitionManager.shared
        let input = AVAudioEngine.latest!
        let session = AVAudioSession.sharedInstance()
        let bka = BackgroundKeepAliveManager.shared
        let main = MiniSightWakeController.shared
        let permissionCount = permissions()
        check(coordinator.beginAndWait(.backgroundKeepAlive), "silent profile")
        let silent = AVAudioEngine()
        try silent.start()
        bka.audioEngine = silent; bka.silentAudioActive = true
        let wakeGranted = await wake(coordinator)
        check(wakeGranted, "wake outranks silent owner")
        check(!silent.isRunning && coordinator.hasIntent(.backgroundKeepAlive), "silent engine stopped, owner retained")
        check(session.category == .playAndRecord && session.mode == .measurement
              && session.categoryOptions == [.mixWithOthers], "mixable passive profile")
        check(!bka.silentAudioWanted && !bka.backgroundExecutionIsBacked, "intent alone is not backing")
        main.physicalPassiveInput = true
        check(bka.backgroundExecutionIsBacked, "physical passive input backs the matching profile")
        main.physicalPassiveInput = false
        var wakePreemptions = 0
        coordinator.onWakeWordPreempted = { wakePreemptions += 1; EventLog.shared.append("stop-wake") }
        coordinator.begin(.backgroundKeepAlive)
        check(coordinator.appliedIntent == .wakeWord && wakePreemptions == 0, "silent cannot steal live profile")
        EventLog.shared.clear()
        try speech.startRecording(nameWake: true)
        check(speech.backgroundRecognitionHasLiveAudio && input.isRunning, "named dictation physically running")
        check(coordinator.appliedIntent == .nameWakeDictation && !coordinator.hasIntent(.wakeWord), "atomic wake to name")
        check(wakePreemptions == 0 && !EventLog.shared.events.contains("active:false"), "handoff keeps claim and active session")
        let obsoleteTask = SFSpeechRecognizer.tasks.last!
        EventLog.shared.clear()
        let reverseGranted = await wake(coordinator)
        check(reverseGranted && speech.state == .idle && !input.isRunning, "reverse handoff physically stops ASR")
        check(!EventLog.shared.events.contains("active:false"), "reverse handoff never deactivates")
        obsoleteTask.deliver("obsolete", final: true)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(speech.recognizedText != "obsolete" && coordinator.hasIntent(.wakeWord), "stale final cannot damage next owner")
        coordinator.onWakeWordPreempted = nil
        await idle(coordinator, speech)
        for source in [AudioSessionCoordinator.Intent.replyTTS, .mediaAttachment, .capture] {
            try speech.startRecording(nameWake: true)
            EventLog.shared.clear()
            coordinator.begin(source)
            check(!input.isRunning && speech.state == .idle, "higher source synchronously stops name mic")
            await wait("higher profile") { coordinator.appliedIntent == source }
            let events = EventLog.shared.events
            check(events.first == "stop-engine", "physical stop precedes category mutation")
            speech.stopNameWakeRecording()
            check(coordinator.hasIntent(source), "name teardown cannot end advanced owner")
            await idle(coordinator, speech)
        }
        speech.recognizedText = "kept draft"
        session.failNextActivation(); expectNameFailure(speech)
        await idle(coordinator, speech)
        MockFault.installException = true; expectNameFailure(speech)
        await idle(coordinator, speech)
        MockFault.engineStartError = true; expectNameFailure(speech)
        await idle(coordinator, speech)
        MockFault.recognitionException = true; expectNameFailure(speech)
        await idle(coordinator, speech)
        input.inputNode.format.sampleRate = .infinity; expectNameFailure(speech)
        input.inputNode.format.sampleRate = 16000
        await idle(coordinator, speech)
        check(coordinator.beginAndWait(.capture), "synthetic VAD capture")
        expectNameFailure(speech)
        check(coordinator.hasIntent(.capture), "refused name never releases VAD")
        speech.stopNameWakeRecording()
        check(coordinator.hasIntent(.capture), "name stop cannot release VAD")
        await idle(coordinator, speech)
        check(permissions() == permissionCount, "named ASR never prompts permissions")

        let bridge = MiniSightVoiceBridge.shared
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        bridge.files = directory
        let claimsBefore = main.claimCalls.count
        try request(bridge, 100, token: "01234567-89ab-4cde-8fab-0123456789ab")
        try request(bridge, 100, token: nil)
        check(main.claimCalls.count == claimsBefore && permissions() == permissionCount,
              "malformed/missing named token never reaches manual or claim")
        main.allowClaim = false
        try request(bridge, 101)
        check(result(bridge)["reason"] as? String == "name_wake_claim", "unclaimed start rejected")
        check(!input.isRunning && main.startedCalls.isEmpty && main.endedCalls.isEmpty, "unclaimed request has no lifecycle")
        main.allowClaim = true
        let pendingWake = await wake(coordinator)
        check(pendingWake, "passive lease before queued named start")
        try request(bridge, 102)
        bridge.cancelNameWake(generation: 999)
        check(!main.endedCalls.contains(102), "wrong generation cannot cancel waiting name")
        bridge.cancelNameWake(generation: 102)
        bridge.cancelNameWake(generation: 102)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(main.endedCalls.filter { $0 == 102 }.count == 1 && !input.isRunning,
              "waiting cancel invalidates queued mic and ends once")
        check(permissions() == permissionCount, "waiting name never displays permissions")
        await idle(coordinator, speech)

        EventLog.shared.clear()
        try request(bridge, 103)
        await wait("named bridge recording") { main.startedCalls.contains(103) }
        check(speech.backgroundRecognitionHasLiveAudio && bka.backgroundExecutionIsBacked,
              "successful claimed ASR is actual background backing")
        check(EventLog.shared.events.first == "claim-name", "claim precedes starting/files/profile/mic")
        bridge.cancelNameWake(generation: 102)
        check(input.isRunning, "stale cancellation cannot stop new name")
        main.rearmWakeOnEnd = true
        EventLog.shared.clear()
        SFSpeechRecognizer.tasks.last!.deliver("named draft", final: true)
        await wait("named final") { speech.state == .idle }
        await wait("atomic final rearm") { coordinator.appliedIntent == .wakeWord }
        check(!EventLog.shared.events.contains("active:false"), "normal final can rearm synchronously without inactive gap")
        main.rearmWakeOnEnd = false
        bridge.recordingBecameIdle(speech)
        bridge.recordingBecameIdle(speech)
        let final = result(bridge)
        check(final["text"] as? String == "named draft" && final["final"] as? Bool == true,
              "name final remains draft, no send")
        check(final["source"] as? String == "nameWake" && final["nameWakeToken"] != nil,
              "named result correlates token without changing manual wire")
        check(main.endedCalls.filter { $0 == 103 }.count == 1, "final and duplicate idle end once")
        await idle(coordinator, speech)

        try request(bridge, 104)
        await wait("name cancel recording") { main.startedCalls.contains(104) }
        bridge.cancelNameWake(generation: 104)
        bridge.recordingBecameIdle(speech)
        check(!input.isRunning && !coordinator.hasIntent(.nameWakeDictation), "cancel stops physical name and releases own lease")
        check(main.endedCalls.filter { $0 == 104 }.count == 1, "active cancellation ends once")
        await idle(coordinator, speech)
        try request(bridge, 105, source: nil, token: nil)
        await wait("manual bridge recording") { speech.state == .recording }
        check(coordinator.appliedIntent == .capture && permissions() > permissionCount, "manual retains original permission/profile path")
        bridge.cancelNameWake(generation: 105)
        bridge.cancelNameWake(generation: 104)
        check(input.isRunning && coordinator.hasIntent(.capture), "name cancel never stops manual mic")
        check(result(bridge)["source"] == nil, "manual payload remains unchanged")
        bridge.stop()
        bridge.recordingBecameIdle(speech)
        await idle(coordinator, speech)

        let explicitPermissions = permissions()
        SFSpeechRecognizer.authorization = .denied
        try request(bridge, 106)
        await wait("named permission failure") { main.endedCalls.contains(106) }
        check(permissions() == explicitPermissions && !input.isRunning, "named permission denial never prompts")
        check(main.endedCalls.filter { $0 == 106 }.count == 1, "permission failure releases controller claim once")
        SFSpeechRecognizer.authorization = .authorized
        await idle(coordinator, speech)
        try speech.startRecording(nameWake: true)
        coordinator.handleInterruption(Notification(name: AVAudioSession.interruptionNotification,
            userInfo: [AVAudioSessionInterruptionTypeKey: UInt(1)]))
        check(!input.isRunning && !coordinator.hasIntent(.nameWakeDictation), "interruption physically stops name immediately")
        coordinator.handleInterruption(Notification(name: AVAudioSession.interruptionNotification,
            userInfo: [AVAudioSessionInterruptionTypeKey: UInt(0)]))
        check(speech.state == .idle && !input.isRunning, "interruption has no automatic name dictation restart")
        await idle(coordinator, speech)
        print("PASS production Swift/mock: \(assertions) assertions; synthetic MAIN/audio only, no device/network/mic")
    }
}
