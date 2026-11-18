import Foundation

@MainActor func runPermissionCases() async {
    let manager = SpeechRecognitionManager.shared
    resetPermissions()
    let queued = Task { await manager.requestPermissions() }; queued.cancel()
    await drain()
    check(PermissionProbe.speechRequests == 0, "cancelled permission entry never presents Speech")
    let queuedResult = await queued.value
    check(!queuedResult, "cancelled permission entry returns false")

    resetPermissions()
    let afterSpeech = Task { await manager.requestPermissions() }; await drain()
    afterSpeech.cancel(); PermissionProbe.speech(.authorized); await drain()
    check(PermissionProbe.micRequests == 0, "cancelled Speech continuation never presents microphone")
    let speechResult = await afterSpeech.value
    check(!speechResult, "cancelled Speech returns false")

    resetPermissions()
    let afterMic = Task { await manager.requestPermissions() }; await drain()
    PermissionProbe.speech(.authorized); await drain()
    check(PermissionProbe.micRequests == 1, "authorized Speech reaches exactly one microphone API")
    afterMic.cancel(); PermissionProbe.microphone(true); await drain()
    let cancelledGrant = await afterMic.value
    check(!cancelledGrant, "cancelled microphone completion returns false")

    // Literal manual startListening invokes the same literal permission body.
    for phase in 0..<3 {
        resetPermissions(); let bridge = ManualBridge(); let task = bridge.begin()
        if phase > 0 { await drain() }
        if phase == 2 { PermissionProbe.speech(.authorized); await drain() }
        task.cancel()
        if phase == 1 { PermissionProbe.speech(.authorized) }
        if phase == 2 { PermissionProbe.microphone(true) }
        await drain(); await task.value
        check(PermissionProbe.speechRequests == (phase == 0 ? 0 : 1), "manual cancellation Speech boundary")
        check(PermissionProbe.micRequests == (phase == 2 ? 1 : 0), "manual cancellation cannot request second permission")
        check(manager.recordingStarts == 0 && manager.recognizedText == "synthetic draft",
              "manual cancellation preserves draft and never starts recording")
        bridge.stop()
    }
    for outcome in 0..<3 {
        resetPermissions(); let bridge = ManualBridge(); let task = bridge.begin(); await drain()
        PermissionProbe.speech(outcome == 0 ? .denied : .authorized); await drain()
        if outcome > 0 { PermissionProbe.microphone(outcome == 2); await drain() }
        await task.value
        check(PermissionProbe.speechRequests == 1 && PermissionProbe.micRequests == (outcome == 0 ? 0 : 1),
              "manual two-stage permission API counts preserved")
        check(manager.recordingStarts == (outcome == 2 ? 1 : 0), "manual grant starts only synthetic recording boundary")
        if outcome < 2 {
            check(bridge.writes.contains("permission") && manager.recognizedText == "synthetic draft",
                  "manual denial preserves permission failure and draft semantics")
        }
        bridge.stop()
    }
    print("PASS literal two-stage permissions + literal manual path: entry/Speech/mic cancellation, denial, grant, draft")
}
