// Runs production coordinator/recognition bodies with synthetic dependencies.
// The Python runner only removes imports/ObjC selector registration and opens
// three handler access levels; it never translates or reimplements policy.
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
        for intent in [AudioSessionCoordinator.Intent.wakeWord, .capture, .mediaAttachment,
                       .replyTTS, .backgroundKeepAlive] { coordinator.end(intent) }
        await wait("idle session") { !AVAudioSession.sharedInstance().isActive }
    }
    @MainActor static func expectFailure(_ speech: SpeechRecognitionManager, _ message: String) {
        do { try speech.startRecording(); preconditionFailure("expected failure: \(message)") }
        catch {
            check(speech.state == .idle, "failure returns idle: \(message)")
            check(!AudioSessionCoordinator.shared.isCapturing, "failure releases capture: \(message)")
            check(speech.recognizedText == "kept draft", "failure preserves draft: \(message)")
            check(!(AVAudioEngine.latest?.isRunning ?? true), "failure stops engine: \(message)")
            check(!(AVAudioEngine.latest?.inputNode.hasTap ?? true), "failure removes tap: \(message)")
        }
    }
    @MainActor static func main() async throws {
        let coordinator = AudioSessionCoordinator.shared
        let session = AVAudioSession.sharedInstance()
        check(AudioSessionCoordinator.Intent.wakeWord.rawValue == -1, "wake rank")
        let old: [AudioSessionCoordinator.Intent] = [.backgroundKeepAlive, .replyTTS, .mediaAttachment, .capture]
        for (raw, intent) in old.enumerated() { check(intent.rawValue == raw, "stable old rank") }
        let categories: [AVAudioSession.Category] = [.playback, .playback, .playback, .record]
        let modes: [AVAudioSession.Mode] = [.default, .spokenAudio, .default, .measurement]
        let options: [AVAudioSession.CategoryOptions] = [[.mixWithOthers], [.duckOthers], [.duckOthers], []]
        for (index, intent) in old.enumerated() {
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
            check(!refused, "every old intent blocks wake")
            coordinator.onWakeWordPreempted = nil
            await idle(coordinator)
        }
        let ttsStops = VoiceOutputPlayer.shared.stopCount
        coordinator.begin(.replyTTS)
        coordinator.begin(.mediaAttachment)
        await wait("media wins") { coordinator.appliedIntent == .mediaAttachment }
        check(VoiceOutputPlayer.shared.stopCount == ttsStops + 1, "old TTS preemption retained")
        await idle(coordinator)
        let backgroundGranted: Bool = await withCheckedContinuation { continuation in
            coordinator.beginBackgroundKeepAlive { continuation.resume(returning: $0) }
        }
        check(backgroundGranted && coordinator.keepAlivePlaybackApplied, "old background ACK")
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

        let speech = SpeechRecognitionManager.shared
        let engine = AVAudioEngine.latest!
        let permissionCount = SFSpeechRecognizer.permissionRequests + session.permissionRequests
            + AVAudioApplication.shared.permissionRequests
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
        firstTask.deliver("obsolete", final: true)
        try? await Task.sleep(nanoseconds: 10_000_000)
        check(speech.recognizedText == "draft", "cancelled task cannot change draft")
        await idle(coordinator)

        _ = coordinator.beginAndWait(.capture) // Synthetic VAD owner.
        do { try speech.startRecording(); preconditionFailure("expected VAD busy") }
        catch { check(coordinator.hasIntent(.capture), "busy never ends VAD capture") }
        speech.stopRecording()
        check(coordinator.hasIntent(.capture), "idle speech stop never ends VAD")
        await idle(coordinator)
        speech.recognizedText = "kept draft"
        session.failNextActivation()
        expectFailure(speech, "session activation")
        await idle(coordinator)
        engine.inputNode.format.channelCount = 0
        expectFailure(speech, "zero channels")
        engine.inputNode.format.channelCount = 1
        await idle(coordinator)
        engine.inputNode.format.sampleRate = 0
        expectFailure(speech, "zero sample rate")
        engine.inputNode.format.sampleRate = 16000
        await idle(coordinator)
        MockFault.installException = true
        expectFailure(speech, "bridge rejects installTap")
        await idle(coordinator)
        MockFault.engineStartError = true
        expectFailure(speech, "engine Swift error")
        await idle(coordinator)
        MockFault.recognitionException = true
        expectFailure(speech, "recognition task initialization")
        await idle(coordinator)
        speech.setLanguage(Locale(identifier: "zz-invalid"))
        expectFailure(speech, "nil recognizer")
        speech.setLanguage(Locale(identifier: "en-US"))
        await idle(coordinator)

        try speech.startRecording()
        let oldLanguageTask = SFSpeechRecognizer.tasks.last!
        oldLanguageTask.deliver("language draft")
        await wait("language draft") { speech.recognizedText == "language draft" }
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
        let permissionResult = await speech.requestPermissions()
        check(permissionResult && SFSpeechRecognizer.permissionRequests == 1, "explicit speech permission path retained")
        await idle(coordinator)
        print("PASS native production Swift mock harness: \(assertions) assertions; no microphone/device/network")
    }
}
