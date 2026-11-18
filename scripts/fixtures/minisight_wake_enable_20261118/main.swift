import Foundation
import Darwin

@MainActor func check(_ ok: @autoclosure () -> Bool, _ message: String) {
    if !ok() { fputs("CHECK failed: \(message)\n", stderr); exit(1) }
}
@MainActor func drain() async { for _ in 0..<100 { await Task.yield() } }
@MainActor func fresh() -> EnableController {
    resetPermissions()
    SessionLockStore.shared.appIsLocked = false
    UserDefaults.standard.values = [MiniSightSettingKey.style: 1,
        MiniSightSettingKey.wakeEnabled: false,
        MiniSightSettingKey.wakeName: "合成", MiniSightSettingKey.wakePronunciation: "he cheng"]
    UIApplication.shared.applicationState = .active
    UIApplication.shared.isProtectedDataAvailable = true
    AVAudioSession.shared.recordPermission = .granted
    let c = EnableController(); c.defaultsChanged(); return c
}
@MainActor func noCommit(_ c: EnableController, _ message: String) {
    check(!MiniSightConfigStore.shared.wakeEnabled && !c.armed, message)
    check(!c.permissionPending && c.permissionTask == nil, "terminal enable clears waiting state")
}
@MainActor func runEnableCases() async {
    let manager = SpeechRecognitionManager.shared
    // All cancellation is on the same actor BEFORE the queued task can start.
    var c = fresh(); c.requestEnabled(true); c.validated(); c.requestEnabled(false)
    await drain()
    check(manager.requests == 0, "cancelled queued request must not prompt")
    noCommit(c, "OFF cannot enable later")

    c = fresh(); c.requestEnabled(true); c.requestEnabled(false); c.validated(); await drain()
    check(manager.requests == 0, "late validation after OFF never prompts")
    noCommit(c, "late validation cannot enable")

    c = fresh(); c.requestEnabled(true); c.validated()
    c.saveName(.init(name: "新名", pronunciation: "xin ming")); await drain()
    check(manager.requests == 0, "save identity cancels queued permission before prompting")
    noCommit(c, "identity change cannot enable old request")

    c = fresh(); c.requestEnabled(true); c.validated()
    UserDefaults.standard.set("new synthetic reading", forKey: MiniSightSettingKey.wakePronunciation)
    c.defaultsChanged(); await drain()
    check(manager.requests == 0, "didChange identity invalidates queued permission")
    noCommit(c, "didChange old task cannot enable")

    c = fresh(); c.requestEnabled(true); c.validated()
    c.requestEnabled(true); c.validated(); await drain()
    check(manager.requests == 1, "superseded task must not duplicate permission request")
    await denySpeech(); noCommit(c, "permission denial stays disabled")

    // Existing same-identity didChange must not cancel the explicit request.
    c = fresh(); c.requestEnabled(true); c.validated(); c.defaultsChanged(); await drain()
    check(manager.requests == 1 && c.permissionPending, "unrelated didChange retains pending transaction")
    c.requestEnabled(false); await grantPermissions()
    noCommit(c, "in-flight grant after OFF cannot re-enable")

    for condition in 0..<5 {
        c = fresh(); c.requestEnabled(true); c.validated()
        let generation = c.enableGeneration
        switch condition {
        case 0: UIApplication.shared.applicationState = .background; c.foreground = false
        case 1: c.appLocked = true
        case 2: c.protectedDataUnavailable = true
        case 3: UIApplication.shared.isProtectedDataAvailable = false
        default: UserDefaults.standard.set(0, forKey: MiniSightSettingKey.style)
        }
        await drain()
        check(manager.requests == 0, "queued unsafe enable must not prompt")
        noCommit(c, "queued unsafe enable cannot arm")
        check(c.enableGeneration != generation, "unsafe queued fallback invalidates generation")
    }
    for condition in 0..<6 {
        c = fresh(); c.requestEnabled(true); c.validated(); await drain()
        check(manager.requests == 1, "current foreground toggle reaches permission API once")
        let generation = c.enableGeneration
        switch condition {
        case 0: UIApplication.shared.applicationState = .background; c.foreground = false
        case 1: c.appLocked = true
        case 2: c.protectedDataUnavailable = true
        case 3: UIApplication.shared.isProtectedDataAvailable = false
        case 4: UserDefaults.standard.set(0, forKey: MiniSightSettingKey.style)
        default: UIApplication.shared.applicationState = .background // notification not delivered yet
        }
        await grantPermissions()
        noCommit(c, "grant in unsafe context must not arm new listening")
        check(c.enableGeneration != generation, "unsafe commit fallback invalidates generation")
    }
    // A system permission sheet is inactive, NOT an actual background event.
    c = fresh(); c.requestEnabled(true); c.validated(); await drain()
    let beforeInactive = c.enableGeneration
    UIApplication.shared.applicationState = .inactive
    c.updatePresentation(foreground: false, shown: true, hasAsset: true, appLocked: false)
    check(!c.foreground && c.permissionPending && c.enableGeneration == beforeInactive,
          "real presentation inactive is not a background cancellation")
    await grantPermissions()
    check(MiniSightConfigStore.shared.wakeEnabled && !c.foreground && !c.armed,
          "normal inactive permission-sheet completion remains allowed")
    check(!c.permissionPending && c.permissionTask == nil, "successful enable clears task")
    check(manager.recordingStarts == 0, "inactive consent commit must not record")
    UIApplication.shared.applicationState = .active; c.activeNotification()
    c.updatePresentation(foreground: true, shown: true, hasAsset: true, appLocked: false)
    check(c.foreground && c.armed, "only subsequent active chain arms the new request")

    c = fresh(); manager.permissionsAlreadyGranted = true
    c.requestEnabled(true); c.validated(); await drain()
    check(manager.requests == 0 && c.armed && MiniSightConfigStore.shared.wakeEnabled,
          "already-granted explicit enable does not prompt again")

    c = fresh(); c.requestEnabled(true); c.validated()
    UIApplication.shared.applicationState = .background; c.foreground = false
    c.requestEnabled(true); await drain()
    check(!c.permissionPending && manager.requests == 0, "rejected replacement clears old spinner")
    // Unsafe events invalidate even if safety is restored before Speech returns.
    // Phase 0 is model validation, 1 Speech await, 2 microphone await.
    for stage in 0..<3 { for condition in 0..<6 {
        c = fresh(); c.requestEnabled(true)
        if stage > 0 { c.validated(); await drain() }
        if stage == 2 { PermissionProbe.speech(.authorized); await drain() }
        let generation = c.enableGeneration
        switch condition {
        case 0:
            UIApplication.shared.applicationState = .background; c.backgroundNotification()
        case 1: c.lockNotification(true)
        case 2: c.protectedDataNotification()
        case 3: UIApplication.shared.isProtectedDataAvailable = false; c.refresh()
        case 4: UserDefaults.standard.set(0, forKey: MiniSightSettingKey.style); c.defaultsChanged()
        default:
            // didEnterBackground is definitive even if state already became inactive again.
            UIApplication.shared.applicationState = .inactive; c.backgroundNotification()
        }
        check(c.enableGeneration != generation && !c.permissionPending && c.permissionTask == nil,
              "unsafe event cancels pending generation immediately")
        UIApplication.shared.applicationState = .active; UIApplication.shared.isProtectedDataAvailable = true
        c.protectedDataUnavailable = false; c.appLocked = false
        UserDefaults.standard.set(1, forKey: MiniSightSettingKey.style); c.activeNotification()
        if stage == 0 { c.validated(); await drain() }
        if stage == 1 { PermissionProbe.speech(.authorized); await drain() }
        if stage == 2 { PermissionProbe.microphone(true); await drain() }
        check(PermissionProbe.micRequests == (stage == 2 ? 1 : 0),
              "unsafe cancelled name request never advances to microphone")
        noCommit(c, "restored safety cannot revive cancelled enable")
    } }
    for stage in 1...2 { for change in 0..<3 {
        c = fresh(); c.requestEnabled(true); c.validated(); await drain()
        if stage == 2 { PermissionProbe.speech(.authorized); await drain() }
        if change == 0 { c.requestEnabled(false) }
        else if change == 1 { c.saveName(.init(name: "另名", pronunciation: "ling ming")) }
        else { c.requestEnabled(true) } // replacement validation is intentionally still pending
        if stage == 1 { PermissionProbe.speech(.authorized); await drain() }
        else { PermissionProbe.microphone(true); await drain() }
        check(PermissionProbe.micRequests == (stage == 2 ? 1 : 0), "OFF rename replacement cancel second permission")
        if change == 2 { c.requestEnabled(false); c.validated(); await drain() }
        noCommit(c, "cancelled name task cannot turn ON")
    } }
    c = fresh(); MiniSightConfigStore.shared.wakeEnabled = true
    c.armed = true; c.input.isRunning = true; c.phase = .listening
    let priorGeneration = c.enableGeneration
    UIApplication.shared.applicationState = .background; c.backgroundNotification()
    check(c.armed && c.input.isRunning && c.phase == .holding && c.enableGeneration == priorGeneration,
          "already-authorized background input and handoff remain preserved")
    print("PASS literal controller enable lifecycle: real inactive host/two-stage cancel/unsafe events/background handoff")
}

@MainActor func runSafetyCases() {
    var c = MiniSightWakePolicy.Context(enabled: true, foreground: false, unlocked: true,
        shown: true, petStyle: true, appRenderer: true, hasAsset: true,
        permissionGranted: true, audioAvailable: true, recordingOrCall: false,
        chatVisible: false, now: 100, cooldownUntil: 0)
    c.armed = true; c.companionRequired = true
    c.updateCompanion(fresh: true, unlocked: true, allowed: true, busy: false,
                      lockKnown: true, screenKnown: true, screenOff: false)
    check(MiniSightWakePolicy.decision(c) == .listen, "already armed background listening preserved")
    let good = c
    c.armed = false
    check(MiniSightWakePolicy.decision(c) == .inactive, "consent committed while inactive cannot enter listening policy")
    check(!MiniSightWakePolicy.mayHoldCompanionTransition(c, inputRunning: true, existingAsset: true, deadline: 102),
          "unarmed new request cannot borrow existing background transition")
    c = good
    c.updateCompanion(fresh: true, unlocked: false, allowed: false, busy: false,
                      lockKnown: false, screenKnown: true, screenOff: false)
    check(MiniSightWakePolicy.decision(c) == .screenUnknown, "unknown lock must remain blocked, not fake unlocked")
    check(!MiniSightWakePolicy.mayHoldCompanionTransition(c, inputRunning: true, existingAsset: true, deadline: 102),
          "unknown lock cannot use background transition hold")
    c = good; c.updateCompanion(fresh: true, unlocked: true, allowed: false, busy: false,
                                lockKnown: true, screenKnown: true, screenOff: true)
    check(MiniSightWakePolicy.decision(c) == .screenOff, "screenOff remains separate hard stop")
    c = good; c.updateCompanion(fresh: false, unlocked: true, allowed: true, busy: false,
                                lockKnown: true, screenKnown: true, screenOff: false)
    check(MiniSightWakePolicy.decision(c) == .companion, "stale or wrong revision is not readiness")
    c = good; c.unlocked = false
    check(MiniSightWakePolicy.decision(c) == .locked, "local lock or protected data remains stop")
    c = good; c.enabled = false
    check(MiniSightWakePolicy.decision(c) == .disabled, "OFF stops background too")
    c = good; c.chatVisible = true
    check(MiniSightWakePolicy.decision(c) == .busy, "new hit yields to visible panel")
    check(MiniSightWakePolicy.safetyDecision(c) == nil, "owned visible ACK does not cancel its own cycle")
    let active = UUID(), other = UUID()
    check(!MiniSightWakePolicy.validHit(active: active, incoming: other, isListening: true, decision: .listen),
          "late detector token cannot create response")
    check(!MiniSightWakePolicy.validHit(active: active, incoming: active, isListening: false, decision: .listen),
          "unstarted input cannot create response")
    check(!MiniSightWakePolicy.remoteReplyCurrent(now: 100, clock: 99, token: "t", expectedToken: "t",
        host: "old", expectedHost: "new", revision: "r", expectedRevision: "r"), "old host ACK rejected")
    check(!MiniSightWakePolicy.remoteReplyCurrent(now: 100, clock: 95, token: "t", expectedToken: "t",
        host: "h", expectedHost: "h", revision: "r", expectedRevision: "r"), "late ACK rejected")
    let state = MiniSightWakeRemote.State(clock: 99, host: "synthetic-host", revision: "r", unlocked: true,
        allowed: true, busy: false, lockKnown: true, screenKnown: true, screenOff: false)
    check(state.isFresh(now: 100, revision: "r"), "current companion revision is fresh")
    check(!state.isFresh(now: 100, revision: "old"), "saved revision mismatch blocks readiness")
    check(!state.isFresh(now: 104, revision: "r"), "expired state blocks readiness")
    check(!state.isFresh(now: 98, revision: "r"), "future state blocks readiness")
    let pulse = MiniSightWakeAudioPulse(), input = UUID()
    pulse.begin(inputToken: input); pulse.setDetectionToken(active)
    check(pulse.markFrame(inputToken: other, now: 100) == nil, "old audio input token ignored")
    check(!pulse.isFresh(now: 100), "running flag alone is not actual frames")
    check(pulse.markFrame(inputToken: input, now: 100) == active, "current real frame can reach detector")
    pulse.stop()
    check(pulse.markFrame(inputToken: input, now: 100) == nil && !pulse.isFresh(now: 100), "OFF removes audio proof")
    print("PASS actual policy/state/pulse: background/unknown-lock/screenOff/revision/late-hit/ACK/frame fences")
}

@main struct Main {
    @MainActor static func main() async {
        await runEnableCases()
        runSafetyCases()
    }
}
