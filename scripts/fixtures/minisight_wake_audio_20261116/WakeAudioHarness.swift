// Runs actual production coordinator/recognition + manual voice bridge bodies.
// Uses the unchanged current background runner's production extraction, BKA
// readback/stop members and shared MockAudio adaptation; no policy translation.
// MAIN/AV/Speech effects are synthetic; this is NOT hardware or ObjC-EH proof.
import Foundation

@main enum WakeAudioHarness {
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
        await withCheckedContinuation { continuation in
            coordinator.beginWakeWordListening { continuation.resume(returning: $0) }
        }
    }
    @MainActor static func idle(_ coordinator: AudioSessionCoordinator) async {
        for intent in [AudioSessionCoordinator.Intent.wakeWord, .nameWakeDictation, .capture,
                       .mediaAttachment, .replyTTS, .backgroundKeepAlive] { coordinator.end(intent) }
        await wait("idle session") { !AVAudioSession.sharedInstance().isActive }
    }
    @MainActor static func expectFailure(_ speech: SpeechRecognitionManager, _ engine: AVAudioEngine,
                                        _ message: String) {
        do { try speech.startRecording(); preconditionFailure("expected failure: \(message)") }
        catch {
            check(speech.state == .idle, "failure returns idle: \(message)")
            check(!AudioSessionCoordinator.shared.isCapturing, "failure releases capture: \(message)")
            check(speech.recognizedText == "kept draft", "failure preserves draft: \(message)")
            check(!engine.isRunning, "failure stops engine: \(message)")
            check(!engine.inputNode.hasTap, "failure removes tap: \(message)")
            check(AudioSessionCoordinator.shared.hasIntent(.backgroundKeepAlive),
                  "failed speech cannot release background owner: \(message)")
        }
    }
    @MainActor static func permissions() -> Int {
        SFSpeechRecognizer.permissionRequests + AVAudioSession.sharedInstance().permissionRequests
            + AVAudioApplication.shared.permissionRequests
    }
    @MainActor static func request(_ bridge: MiniSightVoiceBridge, _ generation: Int,
                                   _ action: String = "start") throws {
        let payload: [String: Any] = ["generation": generation, "action": action]
        try JSONSerialization.data(withJSONObject: payload).write(to: bridge.files.appendingPathComponent("voice.json"))
        bridge.handleRequest()
    }
    @MainActor static func result(_ bridge: MiniSightVoiceBridge) -> [String: Any] {
        bridge.writeQueue.sync {}
        let data = try! Data(contentsOf: bridge.files.appendingPathComponent("voice-result.json"))
        return try! JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
    @MainActor static func rejectNamedPermission(_ speech: SpeechRecognitionManager, _ engine: AVAudioEngine) {
        let before = permissions()
        do {
            try speech.startRecording(nameWake: true)
            preconditionFailure("named permission denial must throw")
        } catch {
            check(speech.state == .idle && !engine.isRunning && !engine.inputNode.hasTap,
                  "named denial has no physical capture")
            check(!AudioSessionCoordinator.shared.hasIntent(.nameWakeDictation), "named denial has no lease")
            check(permissions() == before, "named permission denial never prompts")
        }
    }
    @MainActor static func main() async throws {
        let coordinator = AudioSessionCoordinator.shared
        let session = AVAudioSession.sharedInstance()
        let speech = SpeechRecognitionManager.shared
        let engine = AVAudioEngine.latest! // Cache ASR engine before synthetic BKA creation.
        let bka = BackgroundKeepAliveManager.shared
        bka.appIsInBackground = false // This harness covers foreground recording.
        check(AudioSessionCoordinator.Intent.nameWakeDictation.rawValue == -2, "new named raw value")
        check(AudioSessionCoordinator.Intent.wakeWord.rawValue == -1, "wake rank")
        let old: [AudioSessionCoordinator.Intent] = [.backgroundKeepAlive, .replyTTS, .mediaAttachment, .capture]
        for (raw, intent) in old.enumerated() { check(intent.rawValue == raw, "stable old rank") }
        let categories: [AVAudioSession.Category] = [.playback, .playback, .playback, .record]
        let modes: [AVAudioSession.Mode] = [.default, .spokenAudio, .default, .measurement]
        let options: [AVAudioSession.CategoryOptions] = [[.mixWithOthers], [.duckOthers], [.duckOthers], []]
        // BKA is now a lower, coexisting owner. The other three historical
        // profiles still synchronously preempt and refuse passive input.
        for (index, intent) in old.enumerated() where intent != .backgroundKeepAlive {
            let granted = await wake(coordinator)
            check(granted, "wake granted while idle")
            check(session.category == .playAndRecord && session.mode == .measurement
                    && session.categoryOptions == [.mixWithOthers], "wake exact profile")
            EventLog.shared.clear()
            var preemptions = 0
            coordinator.onWakeWordPreempted = {
                preemptions += 1
                EventLog.shared.append("stop-wake")
                coordinator.end(.wakeWord) // Must be reentrant-safe.
                coordinator.begin(.wakeWord) // Must be refused during preemption.
                check(!coordinator.canBeginWakeWordListening, "preemption gate")
            }
            coordinator.begin(intent)
            await wait("higher profile") { coordinator.appliedIntent == intent }
            check(preemptions == 1, "exactly once preemption")
            check(EventLog.shared.events.first == "stop-wake", "physical stop before category mutation")
            check(!coordinator.hasIntent(.wakeWord), "preemption removes only wake")
            coordinator.end(.wakeWord)
            check(coordinator.hasIntent(intent), "wake end cannot erase old owner")
            check(session.category == categories[index] && session.mode == modes[index]
                    && session.categoryOptions == options[index], "old profile unchanged")
            let refused = await wake(coordinator)
            check(!refused, "every higher legacy intent blocks wake")
            coordinator.onWakeWordPreempted = nil
            await idle(coordinator)
        }
        let ttsStops = VoiceOutputPlayer.shared.stopCount
        EventLog.shared.clear()
        let mediaNote = NotificationCenter.default.addObserver(
            forName: AudioSessionCoordinator.replyTTSPreemptedNotification, object: nil, queue: nil
        ) { _ in EventLog.shared.append("tts-preempted") }
        coordinator.begin(.replyTTS)
        coordinator.begin(.mediaAttachment)
        await wait("media wins") { coordinator.appliedIntent == .mediaAttachment }
        check(VoiceOutputPlayer.shared.stopCount == ttsStops + 1, "old TTS preemption retained")
        check(EventLog.shared.events.contains("tts-preempted"), "media also notifies System TTS owner")
        NotificationCenter.default.removeObserver(mediaNote)
        await idle(coordinator)
        let backgroundGranted: Bool = await withCheckedContinuation { continuation in
            coordinator.beginBackgroundKeepAlive { continuation.resume(returning: $0) }
        }
        check(backgroundGranted && coordinator.keepAlivePlaybackApplied, "old background ACK")
        check(session.category == categories[0] && session.mode == modes[0]
              && session.categoryOptions == options[0], "fourth old profile unchanged: BKA")
        let silent = AVAudioEngine()
        try silent.start()
        bka.audioEngine = silent; bka.silentAudioActive = true
        EventLog.shared.clear()
        let coexistingWake = await wake(coordinator)
        check(coexistingWake && coordinator.hasIntent(.backgroundKeepAlive), "wake coexists with BKA lease")
        check(!silent.isRunning && !bka.silentAudioIsPlaying, "silent input yielded physically")
        check(bka.enhancedBackgroundEnabled && bka.backgroundSpeakEnabled, "handoff preserves background switches")
        check(!coordinator.keepAlivePlaybackApplied && coordinator.keepAlivePlaybackBlocked,
              "BKA intent does not overwrite or fake live input")
        var silentPreemptions = 0
        coordinator.onWakeWordPreempted = { silentPreemptions += 1 }
        coordinator.begin(.backgroundKeepAlive)
        coordinator.reassertForForeground()
        check(coordinator.appliedIntent == .wakeWord && silentPreemptions == 0,
              "silent owner and foreground reassert cannot preempt wake")
        let blockedBKA: Bool = await withCheckedContinuation { continuation in
            coordinator.beginBackgroundKeepAlive { continuation.resume(returning: $0) }
        }
        check(!blockedBKA && coordinator.hasIntent(.backgroundKeepAlive), "BKA ACK refuses input but keeps own lease")
        check(!EventLog.shared.events.contains("active:false"), "BKA to wake has no inactive gap")
        coordinator.end(.wakeWord)
        await wait("BKA after own wake end") { coordinator.keepAlivePlaybackApplied }
        check(coordinator.hasIntent(.backgroundKeepAlive), "wake end leaves BKA owner intact")
        coordinator.onWakeWordPreempted = nil
        await idle(coordinator)

        session.failNextActivation()
        let failed = await wake(coordinator)
        check(!failed && !coordinator.hasIntent(.wakeWord), "failed wake activation releases lease")
        await idle(coordinator)
        let gate = DispatchSemaphore(value: 0)
        session.blockNextActivation(gate)
        var oldAck: Bool?
        var newAck: Bool?
        let start = Date()
        coordinator.beginWakeWordListening { oldAck = $0 }
        check(Date().timeIntervalSince(start) < 0.25, "wake begin never waits on main")
        await wait("blocked synthetic activation") { session.gateEntered }
        check(oldAck == nil, "no premature success ACK")
        coordinator.end(.wakeWord)
        coordinator.beginWakeWordListening { newAck = $0 }
        gate.signal()
        await wait("both generation ACKs") { oldAck != nil && newAck != nil }
        check(oldAck == false && newAck == true, "stale ACK cannot grant/end a newer lease")
        await idle(coordinator)

        var interruptionStops = 0
        coordinator.onWakeWordPreempted = { interruptionStops += 1; coordinator.end(.wakeWord) }
        let beforeInterruption = await wake(coordinator)
        check(beforeInterruption, "wake before interruption")
        coordinator.handleInterruption(Notification(name: AVAudioSession.interruptionNotification,
            userInfo: [AVAudioSessionInterruptionTypeKey: UInt(1)]))
        check(interruptionStops == 1 && !coordinator.canBeginWakeWordListening, "system preemption is synchronous")
        let interruptedAck = await wake(coordinator)
        check(!interruptedAck, "interruption refuses wake")
        coordinator.handleInterruption(Notification(name: AVAudioSession.interruptionNotification,
            userInfo: [AVAudioSessionInterruptionTypeKey: UInt(0)]))
        check(!coordinator.hasIntent(.wakeWord), "no passive auto resume")
        await idle(coordinator)
        let beforeHint = await wake(coordinator)
        check(beforeHint, "wake before external recorder hint")
        coordinator.handleSilenceSecondaryAudioHint(Notification(name: AVAudioSession.silenceSecondaryAudioHintNotification,
            userInfo: [AVAudioSessionSilenceSecondaryAudioHintTypeKey: UInt(1)]))
        check(interruptionStops == 2 && !coordinator.canBeginWakeWordListening, "secondary audio preempts wake")
        coordinator.handleSilenceSecondaryAudioHint(Notification(name: AVAudioSession.silenceSecondaryAudioHintNotification,
            userInfo: [AVAudioSessionSilenceSecondaryAudioHintTypeKey: UInt(0)]))
        coordinator.onWakeWordPreempted = nil
        await idle(coordinator)

        let permissionCount = permissions()
        check(coordinator.beginAndWait(.backgroundKeepAlive), "background lease before foreground capture")
        let permissionFreeWake = await wake(coordinator)
        check(permissionFreeWake, "wake has its own controller permission contract")
        check(permissionCount == SFSpeechRecognizer.permissionRequests + session.permissionRequests
              + AVAudioApplication.shared.permissionRequests, "wake never prompts speech/mic permission")
        try speech.startRecording()
        check(speech.state == .recording && coordinator.appliedIntent == .capture, "speech preempts passive profile")
        check(!coordinator.hasIntent(.wakeWord) && engine.isRunning, "synthetic short speech owns capture")
        let firstTask = SFSpeechRecognizer.tasks.last!
        firstTask.deliver("draft")
        await wait("partial text") { speech.recognizedText == "draft" }
        speech.stopRecording()
        check(speech.state == .idle && speech.recognizedText == "draft", "stop preserves text")
        check(!coordinator.isCapturing && !engine.inputNode.hasTap, "stop releases own capture")
        check(coordinator.hasIntent(.backgroundKeepAlive), "speech stop cannot release background owner")
        firstTask.deliver("obsolete", final: true)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(speech.recognizedText == "draft", "cancelled task cannot change draft")
        try speech.startRecording()
        firstTask.deliver("obsolete same-intent final", final: true)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(speech.state == .recording && speech.recognizedText == "" && engine.isRunning
              && coordinator.hasIntent(.capture), "cancelled callback cannot end newer capture")
        speech.stopNameWakeRecording()
        check(speech.state == .recording && engine.isRunning && coordinator.hasIntent(.capture),
              "name-only stop cannot end ordinary capture")
        speech.stopRecording()
        await idle(coordinator)

        _ = coordinator.beginAndWait(.capture) // Synthetic VAD owner.
        do { try speech.startRecording(); preconditionFailure("expected VAD busy") }
        catch { check(coordinator.hasIntent(.capture), "busy never ends VAD capture") }
        speech.stopRecording()
        check(coordinator.hasIntent(.capture), "idle speech stop never ends VAD")
        await idle(coordinator)
        speech.recognizedText = "kept draft"
        check(coordinator.beginAndWait(.backgroundKeepAlive), "other owner before rollback failures")
        session.failNextActivation()
        expectFailure(speech, engine, "session activation")
        await wait("activation rollback") { coordinator.keepAlivePlaybackApplied }
        engine.inputNode.format.channelCount = 0
        expectFailure(speech, engine, "zero channels")
        engine.inputNode.format.channelCount = 1
        await wait("channels rollback") { coordinator.keepAlivePlaybackApplied }
        engine.inputNode.format.sampleRate = 0
        expectFailure(speech, engine, "zero sample rate")
        engine.inputNode.format.sampleRate = 16000
        await wait("rate rollback") { coordinator.keepAlivePlaybackApplied }
        for invalidRate in [Double.infinity, Double.nan] {
            engine.inputNode.format.sampleRate = invalidRate
            expectFailure(speech, engine, "non-finite sample rate")
            engine.inputNode.format.sampleRate = 16000
            await wait("non-finite rollback") { coordinator.keepAlivePlaybackApplied }
        }
        MockFault.bridgeFailed = true
        expectFailure(speech, engine, "bridge rejects input format resolution")
        await wait("input node rollback") { coordinator.keepAlivePlaybackApplied }
        MockFault.installException = true
        expectFailure(speech, engine, "bridge rejects installTap")
        await wait("install rollback") { coordinator.keepAlivePlaybackApplied }
        MockFault.engineStartError = true
        expectFailure(speech, engine, "engine Swift error")
        await wait("engine rollback") { coordinator.keepAlivePlaybackApplied }
        MockFault.recognitionException = true
        expectFailure(speech, engine, "recognition task initialization")
        await wait("recognition rollback") { coordinator.keepAlivePlaybackApplied }
        SFSpeechRecognizer.available = false
        expectFailure(speech, engine, "unavailable recognizer")
        SFSpeechRecognizer.available = true
        speech.setLanguage(Locale(identifier: "zz-invalid"))
        expectFailure(speech, engine, "nil recognizer")
        speech.setLanguage(Locale(identifier: "en-US"))
        await idle(coordinator)

        try speech.startRecording()
        let oldLanguageTask = SFSpeechRecognizer.tasks.last!
        oldLanguageTask.deliver("language draft")
        await wait("language draft") { speech.recognizedText == "language draft" }
        speech.setLanguage(speech.locale)
        speech.setProvider(.system)
        check(speech.state == .recording && SFSpeechRecognizer.tasks.last === oldLanguageTask
              && !speech.pendingRecordingRestart, "unchanged language/provider cannot restart capture")
        speech.setLanguage(Locale(identifier: "zh-CN"))
        check(speech.pendingRecordingRestart && speech.state == .idle, "language switch defers restart")
        check(speech.recognizedText == "language draft" && !coordinator.isCapturing, "language switch keeps text and releases")
        speech.restartRecordingIfPending()
        check(speech.state == .recording && !speech.pendingRecordingRestart, "explicit language restart")
        oldLanguageTask.deliver("stale language final", final: true)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(speech.state == .recording && speech.recognizedText == "", "old language callback cannot end newer recording")
        let currentTask = SFSpeechRecognizer.tasks.last!
        currentTask.deliver("current draft")
        await wait("current language draft") { speech.recognizedText == "current draft" }
        let began = Notification(name: AVAudioSession.interruptionNotification,
                                 userInfo: [AVAudioSessionInterruptionTypeKey: UInt(1)])
        coordinator.handleInterruption(began)
        NotificationCenter.default.post(began)
        await wait("speech interruption teardown") { speech.state == .idle }
        check(speech.recognizedText == "current draft" && !coordinator.isCapturing, "interruption keeps draft/releases speech")
        coordinator.handleInterruption(Notification(name: AVAudioSession.interruptionNotification,
            userInfo: [AVAudioSessionInterruptionTypeKey: UInt(0)]))
        check(speech.state == .idle && !coordinator.isCapturing, "speech never auto resumes after interruption")
        SFSpeechRecognizer.authorization = .denied
        check(!speech.permissionsAlreadyGranted, "speech authorization remains independent")
        SFSpeechRecognizer.authorization = .authorized
        check(speech.permissionsAlreadyGranted, "existing permission probe unchanged")
        let speechRequestsBefore = SFSpeechRecognizer.permissionRequests
        let permissionResult = await speech.requestPermissions()
        check(permissionResult && SFSpeechRecognizer.permissionRequests == speechRequestsBefore + 1,
              "explicit speech permission path retained")
        await idle(coordinator)

        // Permission-negative cases execute the production named guard AND the
        // real ordinary bridge's asynchronous permission/start/lease path.
        let bridge = MiniSightVoiceBridge.shared
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        bridge.files = directory
        SFSpeechRecognizer.authorization = .denied
        check(!speech.permissionsAlreadyGranted, "non-prompting speech denial probe")
        rejectNamedPermission(speech, engine)
        let beforeSpeechDenied = permissions()
        try request(bridge, 901)
        await wait("manual speech denial") {
            speech.state == .recording || (result(bridge)["state"] as? String) == "failed"
        }
        check(speech.state == .idle && !engine.isRunning && !coordinator.isCapturing,
              "manual speech denial never starts engine")
        check((result(bridge)["reason"] as? String) == "permission"
              && permissions() == beforeSpeechDenied + 1, "manual speech denial fails before microphone request")
        SFSpeechRecognizer.authorization = .authorized
        session.recordPermission = .denied
        AVAudioApplication.shared.recordPermission = .denied
        check(!speech.permissionsAlreadyGranted, "both authorization paths require microphone")
        rejectNamedPermission(speech, engine)
        let beforeMicDenied = permissions()
        try request(bridge, 902)
        await wait("manual mic denial") {
            speech.state == .recording || (result(bridge)["state"] as? String) == "failed"
        }
        check(speech.state == .idle && !engine.isRunning && !engine.inputNode.hasTap && !coordinator.isCapturing,
              "manual microphone denial never starts engine")
        check((result(bridge)["reason"] as? String) == "permission"
              && permissions() == beforeMicDenied + 2, "manual microphone denial retains explicit prompt path")
        session.recordPermission = .granted
        AVAudioApplication.shared.recordPermission = .granted
        let beforeManual = permissions()
        try request(bridge, 903)
        await wait("manual bridge recording") { speech.state == .recording }
        check(coordinator.appliedIntent == .capture && permissions() == beforeManual + 2,
              "ordinary bridge requests permissions and keeps capture profile")
        bridge.cancelNameWake(generation: 903)
        speech.stopNameWakeRecording()
        check(engine.isRunning && coordinator.hasIntent(.capture), "named cancellation cannot release manual owner")
        bridge.stop()
        bridge.recordingBecameIdle(speech)
        await idle(coordinator)
        try request(bridge, 904)
        try request(bridge, 904, "cancel") // Invalidate a queued ordinary start before its Task runs.
        try? await Task.sleep(nanoseconds: 20_000_000)
        check(speech.state == .idle && !engine.isRunning && !coordinator.hasIntent(.capture),
              "cancelled queued manual lease cannot open a recorder")
        await idle(coordinator)
        print("PASS native production Swift mock harness: \(assertions) assertions; no microphone/device/network")
    }
}
