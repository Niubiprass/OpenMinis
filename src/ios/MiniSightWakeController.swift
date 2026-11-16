import AVFoundation
import CallKit
import Combine
import Foundation
import ReplayKit
import UIKit

/// User-enabled foreground/background name detection. The authorised App owns
/// real audio; the SpringBoard companion owns cross-App presentation. Installing
/// observers alone never opens a mic; no recording code is injected into SpringBoard.
@MainActor
final class MiniSightWakeController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate, CXCallObserverDelegate {
    static let shared = MiniSightWakeController()
    static let responseNotification = Notification.Name("MiniSightNameWakeResponse")
    enum Phase: Equatable { case stopped, loading, activating, listening, holding, awaitingCompanion, acknowledging, input, failed }
    private enum RemoteStage: Equatable { case waitingAccepted, accepted, waitingVoice, voiceRequested }
    private struct RemoteCycle {
        let token: UUID
        let state: MiniSightWakeRemote.State
        var stage: RemoteStage = .waitingAccepted
        var responseGeneration: UInt = 0
        var voiceGeneration: Int = 0
    }
    @Published private(set) var phase = Phase.stopped
    @Published private(set) var status = "名字唤醒已关闭"
    @Published private(set) var resolvedPronunciation = ""
    @Published private(set) var responseSequence = 0
    @Published private(set) var responseActive = false
    @Published private(set) var permissionPending = false

    private let detector = MiniSightWakeEngine()
    private let remote = MiniSightWakeRemote()
    private let pulse = MiniSightWakeAudioPulse()
    private let input = AVAudioEngine()
    private let speaker = AVSpeechSynthesizer()
    private let calls = CXCallObserver()
    private let io = DispatchQueue(label: "com.openminis.minisight.wake.settings", qos: .utility)
    private var bag = Set<AnyCancellable>()
    private var timer: Timer?
    private var permissionTask: Task<Void, Never>?
    private var replyDeadline: Task<Void, Never>?
    private var installed = false
    private var foreground = false
    private var armed = false
    private var companion: MiniSightWakeRemote.State?
    private var remoteCycle: RemoteCycle?
    private var namedGeneration: Int?
    private var voiceClaimPending = false
    private var voiceRequestAt: Double = 0
    private var endingCycle = false
    private var finishingNamedInput = false
    private var startingPassiveHold = false
    private var companionTransitionUntil: Double = 0
    private var shown = false
    private var hasAsset = false
    private var appLocked = true
    private var petInteractionBusy = false
    private var active: UUID?
    private weak var petAnchor: UIView?
    private weak var responsePanel: MiniSightChatPanel?
    private var responseGeneration: UInt = 0
    private var waitingForAnchor = false
    private var anchorDeliveryScheduled = false
    private var handoffScheduled = false
    private var tapInstalled = false
    private var ownsWakeAudio = false
    private var pendingUtterance: AVSpeechUtterance?
    private var settingsIdentity = ""
    private var failureLatched = false
    private var cooldownUntil: TimeInterval = 0
    private var enableGeneration = 0
    private var savingIdentity = false

    private override init() { super.init() }
    func install() {
        guard !installed else { return }
        installed = true
        speaker.delegate = self
        speaker.usesApplicationAudioSession = true
        calls.setDelegate(self, queue: .main)
        foreground = UIApplication.shared.applicationState == .active
        appLocked = SessionLockStore.shared.appIsLocked
        remote.onState = { [weak self] state in self?.receivedCompanion(state) }
        remote.onReply = { [weak self] reply in self?.receivedReply(reply) }
        remote.install()
        NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.applicationChanged(active: false) }.store(in: &bag)
        NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.applicationChanged(active: true) }.store(in: &bag)
        NotificationCenter.default.publisher(for: UIApplication.protectedDataWillBecomeUnavailableNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.pause(reason: "系统已锁定，名字监听停止") }.store(in: &bag)
        NotificationCenter.default.publisher(for: UIApplication.willTerminateNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.pause(reason: "App 即将退出，名字监听停止") }.store(in: &bag)
        SessionLockStore.shared.$appIsLocked.removeDuplicates().receive(on: DispatchQueue.main)
            .sink { [weak self] locked in self?.appLocked = locked; self?.refresh() }.store(in: &bag)
        AudioSessionCoordinator.shared.onWakeWordPreempted = { [weak self] in
            // MAIN synchronous: physical recording stops BEFORE the other profile.
            self?.pause(reason: MiniSightWakePolicy.Decision.busy.message)
        }
        NotificationCenter.default.publisher(for: UserDefaults.didChangeNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.settingsChanged() }.store(in: &bag)
        NotificationCenter.default.publisher(for: AudioSessionCoordinator.stateChangedNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in self?.refresh() }.store(in: &bag)
        NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] note in self?.routeChanged(note) }.store(in: &bag)
        NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] note in
                guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                      AVAudioSession.InterruptionType(rawValue: raw) == .began else { return }
                self?.pause(reason: "系统音频中断，名字监听已暂停")
            }.store(in: &bag)
        SpeechRecognitionManager.shared.$state.removeDuplicates().receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refresh() }.store(in: &bag)
        settingsChanged()
    }
    func registerPetAnchor(_ view: UIView) {
        petAnchor = view
        guard waitingForAnchor, let token = active, !anchorDeliveryScheduled else { return }
        anchorDeliveryScheduled = true
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.anchorDeliveryScheduled = false
            self.presentResponse(token)
        }
    }
    func unregisterPetAnchor(_ view: UIView?) {
        guard petAnchor === view else { return }
        petAnchor = nil
        if phase == .acknowledging && remoteCycle == nil { pause(reason: "角色宿主已移除，回应已取消") }
    }
    func setPetInteractionBusy(_ busy: Bool) {
        guard petInteractionBusy != busy else { return }
        petInteractionBusy = busy
        refresh()
    }
    func updatePresentation(foreground: Bool, shown: Bool, hasAsset: Bool, appLocked: Bool) {
        install()
        if !foreground && self.foreground { applicationChanged(active: false) }
        self.foreground = foreground
        // These are App view inputs only. Companion state supplies the actual
        // cross-App show/asset/lock proof; view teardown must not erase it.
        self.shown = shown; self.hasAsset = hasAsset; self.appLocked = appLocked
        if foreground && UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled) &&
            AVAudioSession.sharedInstance().recordPermission == .granted { armed = true }
        updateTimer(); pollRemoteState(); refresh()
    }
    func presentationDetached() {
        petAnchor = nil
        if !isUsingCompanion && (phase == .acknowledging || phase == .input) {
            pause(reason: "App 内对话宿主已移除")
        }
        // Do not pretend the user disabled the pet or locked the phone merely
        // because SwiftUI dismantled a foreground view.
    }
    private func applicationChanged(active: Bool) {
        let wasActive = foreground
        foreground = active
        if wasActive && !active && input.isRunning && remoteCycle == nil {
            pulse.setDetectionToken(nil); detector.stop()
            phase = .holding
            companionTransitionUntil = ProcessInfo.processInfo.systemUptime + 3
        }
        if active { appLocked = SessionLockStore.shared.appIsLocked }
        if active && UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled) &&
            AVAudioSession.sharedInstance().recordPermission == .granted { armed = true }
        if !active && remoteCycle == nil && (phase == .acknowledging || namedGeneration != nil) {
            pause(reason: "切换显示端，当前 App 内语音已取消")
        }
        updateTimer(); pollRemoteState(); refresh()
    }
    private func updateTimer() {
        let enabled = UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled)
        if !enabled || !armed { timer?.invalidate(); timer = nil; return }
        guard timer == nil else { return }
        let t = Timer(timeInterval: .5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.pollRemoteState(); self?.refresh() }
        }
        timer = t; RunLoop.main.add(t, forMode: .common)
    }
    var backgroundAudioIsLive: Bool {
        let coordinator = AudioSessionCoordinator.shared
        guard UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled) else { return false }
        if namedGeneration != nil && coordinator.appliedIntent == .nameWakeDictation {
            return SpeechRecognitionManager.shared.backgroundRecognitionHasLiveAudio
        }
        return ownsWakeAudio && coordinator.appliedIntent == .wakeWord && input.isRunning &&
            pulse.isFresh(now: ProcessInfo.processInfo.systemUptime)
    }
    private var isUsingCompanion: Bool {
        !foreground || UserDefaults.standard.integer(forKey: MiniSightSettingKey.renderer) != 1
    }
    func pollRemoteState() {
        guard installed, UserDefaults.standard.bool(forKey: MiniSightSettingKey.wakeEnabled) || remoteCycle != nil else { return }
        remote.poll()
    }
    private func context() -> MiniSightWakePolicy.Context {
        let session = AudioSessionCoordinator.shared, d = UserDefaults.standard
        let now = ProcessInfo.processInfo.systemUptime
        let revision = d.string(forKey: MiniSightSettingKey.shownRevision) ?? ""
        let ready = companion?.isFresh(now: now, revision: revision) == true && companion?.allowed == true
        let usePlugin = isUsingCompanion
        let hasOtherRecording = SpeechRecognitionManager.shared.state == .recording && namedGeneration == nil && !finishingNamedInput
        let blockedCapture = hasOtherRecording || RPScreenRecorder.shared().isRecording ||
            UIScreen.main.isCaptured || petInteractionBusy || calls.calls.contains { !$0.hasEnded }
        let unlocked = !appLocked && UIApplication.shared.isProtectedDataAvailable &&
            (!usePlugin || (companion?.isFresh(now: now, revision: revision) == true && companion?.unlocked == true))
        var c = MiniSightWakePolicy.Context(enabled: d.bool(forKey: MiniSightSettingKey.wakeEnabled),
            foreground: foreground, unlocked: unlocked,
            shown: usePlugin ? d.bool(forKey: MiniSightSettingKey.shown) : shown,
            petStyle: d.integer(forKey: MiniSightSettingKey.style) == 1,
            appRenderer: d.integer(forKey: MiniSightSettingKey.renderer) == 1,
            hasAsset: usePlugin ? ready : hasAsset,
            permissionGranted: AVAudioSession.sharedInstance().recordPermission == .granted,
            audioAvailable: session.canBeginWakeWordListening, recordingOrCall: blockedCapture,
            chatVisible: usePlugin ? companion?.busy != false : MiniSightChatPanel.existing()?.isVisible == true,
            now: now, cooldownUntil: cooldownUntil)
        c.armed = armed; c.companionRequired = usePlugin; c.companionReady = ready
        return c
    }
    private func settingsChanged() {
        guard !savingIdentity else { return }
        let defaults = UserDefaults.standard
        let name = defaults.string(forKey: MiniSightSettingKey.wakeName) ?? ""
        let reading = defaults.string(forKey: MiniSightSettingKey.wakePronunciation) ?? ""
        let key = "\(defaults.bool(forKey: MiniSightSettingKey.wakeEnabled))|\(name.utf8.count):\(name)|\(reading.utf8.count):\(reading)"
        if key != settingsIdentity {
            if permissionPending {
                enableGeneration &+= 1
                permissionTask?.cancel(); permissionTask = nil; permissionPending = false
            }
            settingsIdentity = key; failureLatched = false
            pause(reason: "名字设置已更新")
            resolvedPronunciation = ""
        }
        if !defaults.bool(forKey: MiniSightSettingKey.wakeEnabled) { armed = false }
        else if foreground && AVAudioSession.sharedInstance().recordPermission == .granted { armed = true }
        updateTimer(); pollRemoteState(); refresh()
    }
    private func refresh() {
        guard installed, !savingIdentity, !endingCycle else { return }
        let c = context(), decision = MiniSightWakePolicy.decision(c)
        if isUsingCompanion && input.isRunning && c.now < companionTransitionUntil &&
            c.enabled && c.armed && !appLocked && UIApplication.shared.isProtectedDataAvailable && !c.recordingOrCall {
            let latest = companion?.isFresh(now: c.now,
                revision: UserDefaults.standard.string(forKey: MiniSightSettingKey.shownRevision) ?? "") == true &&
                (companion?.clock ?? 0) >= companionTransitionUntil - 3
            if !latest {
                pulse.setDetectionToken(nil); detector.stop(); phase = .holding
                status = "正在交接后台桌宠，等待屏幕安全确认"; return
            }
        }
        companionTransitionUntil = 0
        if remoteCycle != nil {
            if MiniSightWakePolicy.safetyDecision(c) != nil {
                pause(reason: "当前屏幕或音频不再允许名字对话")
            }
            return // Companion busy includes THIS response; it is not a new hit.
        }
        if namedGeneration != nil {
            if MiniSightWakePolicy.safetyDecision(c) != nil { pause(reason: "名字语音已被停止") }
            return
        }
        if startingPassiveHold {
            if MiniSightWakePolicy.safetyDecision(c) != nil { pause(reason: "当前不允许恢复名字输入") }
            return
        }
        if voiceClaimPending {
            if MiniSightWakePolicy.safetyDecision(c) != nil { pause(reason: "等待短语音时安全状态已改变") }
            return
        }
        if phase == .acknowledging {
            let cancelled = waitingForAnchor ? c.chatVisible
                : responsePanel?.isNameWakeResponseCurrent(generation: responseGeneration) != true
            if MiniSightWakePolicy.safetyDecision(c) != nil || cancelled || !c.foreground {
                finishCycle(reason: "你已关闭或接管对话，回应已退让")
            }
            return
        }
        if responseActive && (MiniSightChatPanel.existing()?.isVisible != true || !c.foreground) { responseActive = false }
        if decision != .listen {
            if phase == .holding && input.isRunning && MiniSightWakePolicy.safetyDecision(c) == nil {
                status = c.chatVisible ? "对话仍在使用，名字监听暂不重复回应" : decision.message
                return // Keep authorised REAL input, not a finite/silent bgTask.
            }
            if active != nil || tapInstalled || ownsWakeAudio { pause(reason: decision.message) }
            else if !failureLatched && !permissionPending { phase = .stopped; status = decision.message }
            return
        }
        if failureLatched { return }
        if phase == .listening {
            if !input.isRunning || AudioSessionCoordinator.shared.appliedIntent != .wakeWord {
                pause(reason: "音频监听已中断，请重试"); cooldownUntil = c.now + 1
            }
            return
        }
        if phase == .loading || phase == .activating { return }
        prepareDetector()
    }
    private func prepareDetector() {
        let token = UUID(); active = token; phase = .loading; status = "正在准备本地名字检测"
        pulse.setDetectionToken(nil)
        let defaults = UserDefaults.standard
        detector.prepare(name: defaults.string(forKey: MiniSightSettingKey.wakeName) ?? "",
            pronunciation: defaults.string(forKey: MiniSightSettingKey.wakePronunciation) ?? "", token: token,
            onHit: { [weak self] token in self?.detected(token) },
            onFailure: { [weak self] token, error in self?.failed(error, token: token) }) { [weak self] result in
                guard let self, self.active == token else { return }
                switch result {
                case .failure(let error): self.failed(error, token: token)
                case .success(let name):
                    guard MiniSightWakePolicy.decision(self.context()) == .listen else {
                        self.finishCycle(reason: MiniSightWakePolicy.decision(self.context()).message); return
                    }
                    self.resolvedPronunciation = name.pronunciation
                    self.acquireAudio(token)
                }
            }
    }
    private func acquireAudio(_ token: UUID) {
        guard active == token, MiniSightWakePolicy.decision(context()) == .listen else { return }
        phase = .activating; status = "正在取得低优先级音频监听"
        ownsWakeAudio = true
        AudioSessionCoordinator.shared.beginWakeWordListening { [weak self] success in
            guard let self, self.active == token else { return }
            guard success, MiniSightWakePolicy.decision(self.context()) == .listen else {
                self.pause(reason: "音频正在被占用，名字监听未启动")
                self.cooldownUntil = ProcessInfo.processInfo.systemUptime + 2
                return
            }
            self.startInput(token)
        }
    }
    private func startInput(_ token: UUID, detecting: Bool = true) {
        guard active == token, MiniSightWakePolicy.safetyDecision(context()) == nil,
              AudioSessionCoordinator.shared.appliedIntent == .wakeWord else { return }
        if input.isRunning && tapInstalled {
            pulse.setDetectionToken(detecting ? token : nil)
            phase = detecting ? .listening : .holding
            status = detecting ? "正在本机等你喊名字，离开 App 后继续" : "对话使用中，保持名字监听的后台输入"
            return
        }
        var swiftError: Error?
        let detector = self.detector, pulse = self.pulse, inputToken = UUID()
        pulse.begin(inputToken: inputToken)
        pulse.setDetectionToken(detecting ? token : nil)
        let started = noff_try_objc {
            let node = self.input.inputNode
            node.removeTap(onBus: 0)
            let format = node.outputFormat(forBus: 0)
            guard format.commonFormat == .pcmFormatFloat32, !format.isInterleaved,
                  format.channelCount > 0, format.sampleRate.isFinite,
                  (8000...192000).contains(format.sampleRate) else {
                swiftError = MiniSightWakeEngine.Failure.audioFormat; return
            }
            node.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                guard buffer.frameLength > 0, buffer.frameLength <= 8192,
                      let channel = buffer.floatChannelData?[0] else { return }
                guard let detectionToken = pulse.markFrame(inputToken: inputToken,
                    now: ProcessInfo.processInfo.systemUptime) else { return }
                let samples = Array(UnsafeBufferPointer(start: channel, count: Int(buffer.frameLength)))
                detector.offer(samples, sampleRate: buffer.format.sampleRate, token: detectionToken)
            }
            self.tapInstalled = true
            self.input.prepare()
            do { try self.input.start() } catch { swiftError = error }
        }
        guard started, swiftError == nil, input.isRunning else {
            failed(swiftError ?? MiniSightWakeEngine.Failure.audioFormat, token: token)
            return
        }
        armed = true
        phase = detecting ? .listening : .holding
        status = detecting ? "正在本机等你喊名字，离开 App 后继续" : "对话使用中，保持名字监听的后台输入"
    }
    private func stopInputKeepingAudio() {
        pulse.stop()
        _ = noff_try_objc { self.input.stop() }
        if tapInstalled {
            tapInstalled = false
            _ = noff_try_objc { self.input.inputNode.removeTap(onBus: 0) }
        }
        detector.stop()
    }
    private func pause(reason: String) {
        let cycle = remoteCycle, generation = namedGeneration
        remoteCycle = nil; namedGeneration = nil; voiceClaimPending = false; startingPassiveHold = false
        active = nil; companionTransitionUntil = 0
        waitingForAnchor = false; handoffScheduled = false
        responsePanel?.nameWakeCancellationHandler = nil
        if let token = cycle?.token { remote.post(action: "cancel", token: token, state: cycle!.state) }
        if let generation { MiniSightVoiceBridge.shared.cancelNameWake(generation: generation) }
        responsePanel = nil; responseGeneration = 0
        // A user who takes over the existing composer keeps its visible draft.
        // A failed pending mount has no panel and cannot leave a ghost pet.
        responseActive = responseActive && MiniSightChatPanel.existing()?.isVisible == true
        replyDeadline?.cancel(); replyDeadline = nil
        pendingUtterance = nil
        if speaker.isSpeaking { speaker.stopSpeaking(at: .immediate) }
        stopInputKeepingAudio()
        if ownsWakeAudio {
            ownsWakeAudio = false
            AudioSessionCoordinator.shared.end(.wakeWord)
        }
        phase = .stopped; status = reason
    }
    /// End one name interaction without mistaking a user closing the panel for
    /// turning OFF the global name switch. Keep/reacquire the real audio source.
    private func finishCycle(reason: String) {
        guard !endingCycle else { return }
        if let generation = namedGeneration {
            let cycle = remoteCycle
            remoteCycle = nil; voiceClaimPending = false
            if let cycle { remote.post(action: "cancel", token: cycle.token, state: cycle.state) }
            status = reason
            // Keep generation until the bridge's synchronous terminal callback;
            // it must establish the next owner before the old input is released.
            MiniSightVoiceBridge.shared.cancelNameWake(generation: generation)
            if namedGeneration == generation { nameWakeVoiceEnded(generation: generation) }
            return
        }
        endingCycle = true
        let cycle = remoteCycle
        remoteCycle = nil; voiceClaimPending = false
        responsePanel?.nameWakeCancellationHandler = nil
        responsePanel = nil; responseGeneration = 0
        waitingForAnchor = false; handoffScheduled = false
        replyDeadline?.cancel(); replyDeadline = nil; pendingUtterance = nil
        if speaker.isSpeaking { speaker.stopSpeaking(at: .immediate) }
        detector.stop(); pulse.setDetectionToken(nil)
        if let cycle { remote.post(action: "cancel", token: cycle.token, state: cycle.state) }
        cooldownUntil = ProcessInfo.processInfo.systemUptime + 2
        status = reason
        endingCycle = false
        resumePassiveInput()
    }
    private func resumePassiveInput() {
        guard !failureLatched, MiniSightWakePolicy.safetyDecision(context()) == nil else {
            pause(reason: MiniSightWakePolicy.decision(context()).message); return
        }
        let token = UUID(); active = token
        if input.isRunning && ownsWakeAudio && AudioSessionCoordinator.shared.appliedIntent == .wakeWord {
            pulse.setDetectionToken(nil); phase = .holding; return
        }
        phase = .activating; startingPassiveHold = true
        ownsWakeAudio = true
        // Called synchronously from named final BEFORE its old lease is released:
        // insert the next owner first, so the queue cannot deactivate in between.
        AudioSessionCoordinator.shared.begin(.wakeWord)
        AudioSessionCoordinator.shared.beginWakeWordListening { [weak self] applied in
            guard let self, self.active == token else { return }
            guard applied, MiniSightWakePolicy.safetyDecision(self.context()) == nil else {
                self.pause(reason: "名字监听暂时无法恢复"); return
            }
            self.startInput(token, detecting: false)
            self.startingPassiveHold = false
            self.refresh()
        }
    }
    private func failed(_ error: Error, token: UUID) {
        guard active == token else { return }
        pause(reason: error.localizedDescription)
        failureLatched = true; phase = .failed
    }
    private func receivedCompanion(_ state: MiniSightWakeRemote.State?) {
        if let state, let old = companion, state.host == old.host && state.clock < old.clock { return }
        companion = state
        if let cycle = remoteCycle,
           state?.host != cycle.state.host || state?.revision != cycle.state.revision || state?.allowed != true {
            pause(reason: "插件屏幕状态或设置已变化，名字对话已停止")
        }
        refresh()
    }
    private func receivedReply(_ reply: MiniSightWakeRemote.Reply) {
        guard var cycle = remoteCycle, active == cycle.token,
              MiniSightWakePolicy.remoteReplyCurrent(now: ProcessInfo.processInfo.systemUptime, clock: reply.clock,
                token: reply.token, expectedToken: cycle.token.uuidString, host: reply.host,
                expectedHost: cycle.state.host, revision: reply.revision, expectedRevision: cycle.state.revision) else { return }
        switch reply.state {
        case "accepted":
            guard cycle.stage == .waitingAccepted, reply.responseGeneration > 0 else { return }
            cycle.stage = .accepted; cycle.responseGeneration = reply.responseGeneration
            remoteCycle = cycle; phase = .acknowledging
            speakResponse(cycle.token)
        case "voice_requested":
            guard cycle.stage == .waitingVoice, reply.responseGeneration == cycle.responseGeneration,
                  reply.voiceGeneration > 0, reply.voiceGeneration <= UInt(Int.max) else { return }
            cycle.stage = .voiceRequested; cycle.voiceGeneration = Int(reply.voiceGeneration)
            remoteCycle = cycle; voiceClaimPending = true; voiceRequestAt = ProcessInfo.processInfo.systemUptime
            // Response mailbox was read/validated BEFORE the named voice entry.
            MiniSightVoiceBridge.shared.resumeRequestedVoice()
        case "cancelled", "declined":
            if MiniSightWakePolicy.safetyDecision(context()) != nil { pause(reason: "当前名字语音已停止") }
            else { finishCycle(reason: "桌宠暂时忙碌或你已取消，本轮回应已结束") }
        default: break
        }
    }
    /// A voice note can arrive before the separately-verified response note.
    /// Ignore that early note (no fake failure); receivedReply replays it once
    /// the same host/token/generation has actually been confirmed.
    func awaitsNameWakeReply(token: String) -> Bool {
        remoteCycle?.token.uuidString == token && remoteCycle?.stage == .waitingVoice
    }
    func claimNameWakeVoice(token: String, generation: Int) -> Bool {
        guard generation > 0, let identity = UUID(uuidString: token), identity.uuidString == token,
              active == identity, voiceClaimPending, namedGeneration == nil, input.isRunning,
              MiniSightWakePolicy.safetyDecision(context()) == nil,
              ProcessInfo.processInfo.systemUptime - voiceRequestAt <= 3 else { return false }
        if let cycle = remoteCycle {
            guard cycle.stage == .voiceRequested, cycle.voiceGeneration == generation,
                  cycle.token == identity else { return false }
        } else {
            guard let panel = responsePanel, panel === MiniSightChatPanel.existing(),
                  panel.nameWakeRequestToken == token, panel.currentVoiceGeneration == UInt(generation),
                  foreground && context().appRenderer else { return false }
        }
        // Keep the audio lease; Speech atomically replaces it before changing
        // the mixable profile. Stop only OUR physical input, not a VAD/manual tap.
        voiceClaimPending = false; namedGeneration = generation
        replyDeadline?.cancel(); replyDeadline = nil
        stopInputKeepingAudio(); phase = .input
        return true
    }
    func nameWakeVoiceStarted(generation: Int) {
        guard namedGeneration == generation else { return }
        guard MiniSightWakePolicy.safetyDecision(context()) == nil else {
            pause(reason: "开始语音前状态已改变"); return
        }
        ownsWakeAudio = false // Replaced by nameWakeDictation, never end another owner.
        phase = .input; status = "正在听你说话；转写进草稿，仍需手动发送"
    }
    func nameWakeVoiceEnded(generation: Int) {
        guard namedGeneration == generation else { return }
        finishingNamedInput = true
        defer { finishingNamedInput = false }
        namedGeneration = nil; remoteCycle = nil; voiceClaimPending = false
        responsePanel?.nameWakeCancellationHandler = nil
        responsePanel = nil; responseGeneration = 0
        replyDeadline?.cancel(); replyDeadline = nil; active = nil
        ownsWakeAudio = false
        cooldownUntil = ProcessInfo.processInfo.systemUptime + 1
        // The old recording intent is still owned at this synchronous callback.
        // Resume intent FIRST, then await real frames; no idle gap/false backing.
        resumePassiveInput()
    }
    private func speakResponse(_ token: UUID) {
        guard active == token, MiniSightWakePolicy.safetyDecision(context()) == nil else {
            pause(reason: "当前不允许回应"); return
        }
        pulse.setDetectionToken(nil); detector.stop()
        let utterance = AVSpeechUtterance(string: "我在。")
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        pendingUtterance = utterance
        speaker.speak(utterance)
        replyDeadline?.cancel()
        replyDeadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 2_500_000_000) } catch { return }
            guard let self, self.active == token, self.phase == .acknowledging else { return }
            self.finishResponse(token)
        }
    }
    private func detected(_ token: UUID) {
        let c = context(), decision = MiniSightWakePolicy.decision(c)
        guard MiniSightWakePolicy.validHit(active: active, incoming: token,
            isListening: phase == .listening && input.isRunning, decision: decision),
              ownsWakeAudio, AudioSessionCoordinator.shared.appliedIntent == .wakeWord else { return }
        // Keep the authorised input alive but discard frames while the companion
        // responds. A real audio source, not a silent finite background task.
        pulse.setDetectionToken(nil); detector.stop()
        cooldownUntil = c.now + 3
        if isUsingCompanion {
            guard let state = companion, state.isFresh(now: c.now,
                revision: UserDefaults.standard.string(forKey: MiniSightSettingKey.shownRevision) ?? ""),
                  state.allowed, !state.busy else { finishCycle(reason: "插件未就绪，本次不唤醒"); return }
            remoteCycle = RemoteCycle(token: token, state: state)
            phase = .awaitingCompanion; status = "已听到名字，等待当前屏幕桌宠确认"
            remote.post(action: "hit", token: token, state: state) { [weak self] written in
                guard let self, self.remoteCycle?.token == token else { return }
                if !written { self.finishCycle(reason: "名字请求未送达插件") }
                else { self.pollRemoteState() }
            }
            replyDeadline?.cancel()
            replyDeadline = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: 3_000_000_000) } catch { return }
                guard let self, self.remoteCycle?.token == token, self.remoteCycle?.stage == .waitingAccepted else { return }
                self.finishCycle(reason: "插件未确认回应，本次不启动语音")
            }
            return
        }
        phase = .acknowledging; status = "听到名字，正在回应"
        waitingForAnchor = true
        responseActive = true; responseSequence &+= 1
        NotificationCenter.default.post(name: Self.responseNotification, object: nil)
        // Call-only mode first mounts the existing pet window. It must become a
        // real visible anchor before the panel's normal show gate can succeed.
        replyDeadline?.cancel()
        replyDeadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 800_000_000) } catch { return }
            guard let self, self.active == token, self.waitingForAnchor else { return }
            self.pause(reason: "角色窗口暂不可用，回应未启动")
        }
        presentResponse(token)
    }
    private func presentResponse(_ token: UUID) {
        guard active == token, phase == .acknowledging, waitingForAnchor,
              let anchor = petAnchor, let window = anchor.window, !window.isHidden,
              let scene = window.windowScene, scene.activationState == .foregroundActive else { return }
        let c = context()
        guard MiniSightWakePolicy.permitsContinuation(foreground: c.foreground, unlocked: c.unlocked,
            shown: c.shown && c.petStyle && c.appRenderer && c.hasAsset, enabled: c.enabled, cancelled: c.chatVisible),
              !c.recordingOrCall else { pause(reason: "回应已取消或被手动操作接管"); return }
        let panel = MiniSightChatPanel.shared()
        panel.containerPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .deletingLastPathComponent().path
        panel.appearancePreferences = MiniSightConfigStore.shared.appearancePreferencesForWake
        panel.anchorView = anchor
        guard panel.showNameWakeResponse(in: scene) else {
            pause(reason: "聊天正在被使用，唤醒回应已退让"); return
        }
        waitingForAnchor = false
        panel.nameWakeRequestToken = token.uuidString
        responsePanel = panel; responseGeneration = panel.nameWakeResponseGeneration
        panel.nameWakeCancellationHandler = { [weak self] in
            guard let self, self.active == token else { return }
            self.finishCycle(reason: "你已关闭或接管对话，名字回应已停止")
        }
        speakResponse(token)
    }
    private func currentResponse(_ token: UUID) -> MiniSightChatPanel? {
        guard active == token, phase == .acknowledging, !waitingForAnchor,
              let panel = responsePanel, panel === MiniSightChatPanel.existing() else { return nil }
        let c = context()
        let cancelled = !panel.isNameWakeResponseCurrent(generation: responseGeneration)
        guard MiniSightWakePolicy.permitsContinuation(foreground: c.foreground, unlocked: c.unlocked,
            shown: c.shown && c.petStyle && c.appRenderer && c.hasAsset, enabled: c.enabled, cancelled: cancelled),
              !c.recordingOrCall else { return nil }
        return panel
    }
    private func responseMayContinue(_ token: UUID) -> Bool {
        guard active == token, phase == .acknowledging, MiniSightWakePolicy.safetyDecision(context()) == nil else { return false }
        if let cycle = remoteCycle { return cycle.token == token && cycle.stage == .accepted }
        return currentResponse(token) != nil
    }
    private func finishResponse(_ token: UUID) {
        guard !handoffScheduled else { return }
        guard responseMayContinue(token) else { finishCycle(reason: "当前回应已取消，不继续语音输入"); return }
        handoffScheduled = true
        replyDeadline?.cancel(); pendingUtterance = nil
        if speaker.isSpeaking { speaker.stopSpeaking(at: .immediate) }
        // Do not feed the acknowledgement's speaker tail into dictation.
        // A close/edit/lock during this gap invalidates the same response token.
        replyDeadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 200_000_000) } catch { return }
            self?.completeVoiceHandoff(token)
        }
    }
    private func completeVoiceHandoff(_ token: UUID) {
        guard responseMayContinue(token) else {
            if active == token { finishCycle(reason: "回应已被接管，语音输入未启动") }
            return
        }
        handoffScheduled = false; replyDeadline = nil
        if var cycle = remoteCycle {
            cycle.stage = .waitingVoice; remoteCycle = cycle
            remote.post(action: "ready", token: token, state: cycle.state) { [weak self] written in
                guard let self, self.remoteCycle?.token == token else { return }
                if !written { self.finishCycle(reason: "语音交接未送达插件") }
                else { self.pollRemoteState() }
            }
        } else if let panel = responsePanel {
            let generation = responseGeneration
            voiceClaimPending = true; voiceRequestAt = ProcessInfo.processInfo.systemUptime
            if !panel.beginNameWakeVoiceInput(generation: generation) {
                finishCycle(reason: "语音未启动，可手动点麦克风"); return
            }
        } else { finishCycle(reason: "当前回应面板已消失"); return }
        status = "已回应，正在连接短语音；转写进草稿，仍需手动发送"
        replyDeadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 3_000_000_000) } catch { return }
            guard let self, self.active == token, self.namedGeneration == nil else { return }
            self.finishCycle(reason: "短语音没有确认启动，本次停止")
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.pendingUtterance === utterance, let token = self.active else { return }
            self.finishResponse(token)
        }
    }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.pendingUtterance === utterance else { return }
            self.pause(reason: "唤醒回应被中断")
        }
    }
    nonisolated func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            if self.calls.calls.contains(where: { !$0.hasEnded }) { self.pause(reason: "通话期间不监听名字") }
            else { self.refresh() }
        }
    }
    private func routeChanged(_ note: Notification) {
        guard phase == .listening || phase == .acknowledging else { return }
        let raw = note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
        if raw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:)) == .categoryChange,
           AudioSessionCoordinator.shared.appliedIntent == .wakeWord { return }
        pause(reason: "音频路线已改变，名字监听暂时停止")
        cooldownUntil = ProcessInfo.processInfo.systemUptime + 1
    }
    func saveName(_ prepared: MiniSightWakeName.Prepared) {
        install()
        savingIdentity = true
        enableGeneration &+= 1
        permissionTask?.cancel(); permissionTask = nil; permissionPending = false
        pause(reason: "正在保存新的名字与读音")
        MiniSightConfigStore.shared.saveWakeIdentity(prepared)
        savingIdentity = false
        settingsChanged()
    }
    /// Validating a name loads bundled data only; it NEVER initializes an audio engine.
    func validate(name: String, pronunciation: String,
                  completion: @escaping (Result<MiniSightWakeName.Prepared, Error>) -> Void) {
        io.async {
            let result = Result { () throws -> MiniSightWakeName.Prepared in
                let files = try MiniSightWakeAssets.load()
                return try MiniSightWakeName.prepare(name: name, pronunciation: pronunciation,
                                                     vocabulary: files.vocabulary)
            }
            DispatchQueue.main.async { completion(result) }
        }
    }
    /// Call from an explicit user toggle after the visible microphone disclosure.
    /// A persisted enabled flag alone may only probe granted permission, never ask.
    func requestEnabled(_ enabled: Bool) {
        install()
        enableGeneration &+= 1; let request = enableGeneration
        permissionTask?.cancel(); permissionTask = nil
        if !enabled {
            armed = false
            permissionPending = false
            MiniSightConfigStore.shared.wakeEnabled = false
            failureLatched = false; pause(reason: "名字唤醒已关闭")
            timer?.invalidate(); timer = nil
            return
        }
        guard UIApplication.shared.applicationState == .active else {
            status = "请在 App 内主动开启名字唤醒"; return
        }
        let config = MiniSightConfigStore.shared
        guard UserDefaults.standard.integer(forKey: MiniSightSettingKey.style) == 1, !appLocked else {
            permissionPending = false
            status = "请先启用桌宠样式，并解除 App 锁定"; return
        }
        permissionPending = true; status = "正在检查名字与离线模型；尚未开麦"
        validate(name: config.wakeName, pronunciation: config.wakePronunciation) { [weak self] result in
            guard let self, self.enableGeneration == request else { return }
            switch result {
            case .failure(let error):
                self.permissionPending = false; self.status = error.localizedDescription
                self.phase = .failed; self.failureLatched = true
            case .success(let name):
                guard UIApplication.shared.applicationState == .active, !self.appLocked else {
                    self.permissionPending = false; self.status = "请回到未锁定的 App 再开启"; return
                }
                self.resolvedPronunciation = name.pronunciation
                self.permissionTask = Task { [weak self] in
                    // This task is started ONLY by the user's disclosed toggle.
                    // Background hits later probe already-granted permissions and
                    // never foreground the App merely to display a permission UI.
                    let manager = SpeechRecognitionManager.shared
                    let granted = manager.permissionsAlreadyGranted
                        ? true : await manager.requestPermissions()
                    guard let self, self.enableGeneration == request, !Task.isCancelled else { return }
                    self.permissionPending = false; self.permissionTask = nil
                    guard granted else {
                        self.status = "麦克风权限未允许，名字监听未启动"; self.phase = .stopped; return
                    }
                    self.failureLatched = false; self.armed = true
                    MiniSightConfigStore.shared.wakeEnabled = true
                    self.updatePresentation(foreground: self.foreground, shown: self.shown,
                                            hasAsset: self.hasAsset, appLocked: self.appLocked)
                }
            }
        }
    }
    func retry() {
        failureLatched = false; cooldownUntil = 0
        pause(reason: "正在重新检查名字监听")
        updatePresentation(foreground: foreground, shown: shown, hasAsset: hasAsset, appLocked: appLocked)
    }
}
