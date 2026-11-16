import CoreFoundation
import Foundation

// Reader/policy behavior comes only from the production Swift files compiled by
// the runner. State dictionaries originate in the real ObjC builder's files.
struct FixtureFailure: Error, CustomStringConvertible { let description: String }
var assertions = 0
func check(_ condition: @autoclosure () -> Bool, _ label: String) throws {
    assertions += 1
    if !condition() { throw FixtureFailure(description: "FAIL assertion: " + label) }
}
let host = "11111111-2222-4333-8444-555555555555"
let otherHost = "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
let revision = "SYNTHETIC-NAME-ROUNDTRIP-REV-1"
let token = "66666666-7777-4888-8999-AAAAAAAAAAAA"
let replacementToken = "BBBBBBBB-CCCC-4DDD-8EEE-FFFFFFFFFFFF"
let now = 1000.0
func object(_ directory: String, _ name: String) throws -> [String: Any] {
    let file = URL(fileURLWithPath: directory).appendingPathComponent(name)
    let data = try Data(contentsOf: file)
    guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw FixtureFailure(description: "FAIL assertion: writer file is not a JSON object")
    }
    return value
}
func decoded(_ directory: String, _ name: String) throws -> MiniSightWakeRemote.State {
    guard let state = MiniSightWakeRemote.decodeState(try object(directory, name)) else {
        throw FixtureFailure(description: "FAIL assertion: decode writer file " + name)
    }
    return state
}
func context(_ state: MiniSightWakeRemote.State?, foreground: Bool = true,
             required: Bool = true, enabled: Bool = true, localUnlocked: Bool = true,
             freshness: Bool? = nil) -> MiniSightWakePolicy.Context {
    // Synthetic context inputs; the production Controller is only source-guarded,
    // not instantiated, so no UIKit, permission, timer or microphone can run.
    let fresh = freshness ?? (state?.isFresh(now: now, revision: revision) == true)
    let ready = fresh && state?.allowed == true
    var c = MiniSightWakePolicy.Context(enabled: enabled, foreground: foreground,
        unlocked: localUnlocked, shown: true, petStyle: true, appRenderer: !required,
        hasAsset: required ? ready : true, permissionGranted: true, audioAvailable: true,
        recordingOrCall: false, chatVisible: required && fresh && state?.busy == true,
        now: now, cooldownUntil: 0)
    c.armed = true
    c.companionRequired = required
    c.updateCompanion(fresh: fresh, unlocked: state?.unlocked, allowed: state?.allowed, busy: state?.busy,
                      lockKnown: state?.lockKnown, screenKnown: state?.screenKnown, screenOff: state?.screenOff)
    return c
}
func realFloat(_ value: Double) throws -> NSNumber {
    var input = value
    guard let number = CFNumberCreate(nil, .float64Type, &input) else {
        throw FixtureFailure(description: "FAIL assertion: create floating CFNumber")
    }
    try check(CFNumberIsFloatType(number), "fixture floating CFNumber has float type")
    return unsafeBitCast(number, to: NSNumber.self)
}
func stateFixtures(_ directory: String) throws -> [String: Any] {
    let allowed = [false, false, false, false, false, false, true, true]
    let decisions: [MiniSightWakePolicy.Decision] = [.locked, .locked, .locked, .locked, .companion, .busy, .listen, .busy]
    for mask in 0..<8 {
        let wire = try object(directory, "flags-\(mask).json")
        for field in ["unlocked", "allowed", "busy", "lockKnown", "screenKnown", "screenOff"] {
            guard let number = wire[field] as? NSNumber else {
                throw FixtureFailure(description: "FAIL assertion: boolean NSNumber " + field)
            }
            try check(CFGetTypeID(number) == CFBooleanGetTypeID(), "reader wire CFBoolean " + field)
        }
        let state = try decoded(directory, "flags-\(mask).json")
        try check(state.unlocked == (mask >= 4), "all flags unlocked")
        try check(state.allowed == allowed[mask], "all flags allowed literal gate")
        try check(state.busy == (mask % 2 == 1), "all flags busy")
        try check(state.host == host && state.revision == revision && state.clock == now, "writer identity and clock")
        for foreground in [true, false] {
            let c = context(state, foreground: foreground)
            try check(MiniSightWakePolicy.decision(c) == decisions[mask], "all flags production policy foreground/background")
        }
    }
    for i in 0..<4 {
        let wire = try object(directory, "revision-\(i).json")
        let expected = [false, true, true, false][i]
        try check((wire["allowed"] as? NSNumber)?.boolValue == expected, "revision writer gate")
        let lockedWire = try object(directory, "revision-locked-\(i).json")
        try check((lockedWire["allowed"] as? NSNumber)?.boolValue == false, "lock dominates revision gate")
        if i == 1 || i == 2 {
            let s = try decoded(directory, "revision-\(i).json")
            try check(s.revision.utf8.count == (i == 1 ? 1 : 128), "reader revision boundaries")
            try check(!s.isFresh(now: now, revision: revision), "revision mismatch not fresh")
            try check(MiniSightWakePolicy.decision(context(s)) == .companion, "revision mismatch policy unknown not locked")
        } else {
            try check(MiniSightWakeRemote.decodeState(wire) == nil, "reader empty/129 revision rejected")
            try check(MiniSightWakeRemote.decodeState(lockedWire) == nil, "reader invalid locked revision rejected")
        }
    }
    let base = try object(directory, "flags-6.json")
    for field in ["unlocked", "allowed", "busy", "lockKnown", "screenKnown", "screenOff"] {
        for integer in [0, 1] {
            var value = base; value[field] = NSNumber(value: integer)
            guard let state = MiniSightWakeRemote.decodeState(value) else {
                throw FixtureFailure(description: "FAIL assertion: legacy integer 0/1 rejected " + field)
            }
            let actual = MiniSightWakeRemote.boolean(value[field])
            try check(actual == (integer == 1), "legacy integer 0/1 semantics " + field)
            try check(!state.allowed || (state.lockKnown && state.unlocked && state.screenKnown && !state.screenOff), "normalized state cannot grant unsafe listen")
            let data = try JSONSerialization.data(withJSONObject: value)
            let file = URL(fileURLWithPath: directory).appendingPathComponent("legacy-\(field)-\(integer).json")
            try data.write(to: file, options: .atomic)
            let reread = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
            try check(MiniSightWakeRemote.decodeState(reread) != nil, "legacy integer actual temporary file " + field)
        }
        let invalid: [Any] = ["true", "false", "1", "0", "", 2, -1, Int64.max, UInt64.max,
                              NSNull(), [true], ["flag": true], try realFloat(0), try realFloat(1),
                              try realFloat(1.5), try realFloat(-1), try realFloat(.infinity), try realFloat(.nan)]
        for bad in invalid {
            var value = base; value[field] = bad
            try check(MiniSightWakeRemote.decodeState(value) == nil, "invalid boolean " + field)
        }
        var missing = base; missing.removeValue(forKey: field)
        try check(MiniSightWakeRemote.decodeState(missing) == nil, "missing boolean " + field)
    }
    let invalidFields: [(String, Any)] = [
        ("host", "not-a-uuid"), ("host", otherHost.lowercased()), ("host", ""), ("host", NSNull()), ("host", 1),
        ("revision", ""), ("revision", String(repeating: "R", count: 129)),
        ("revision", "SYNTHETIC\nREV"), ("revision", String(repeating: "界", count: 43)), ("revision", true),
        ("schema", true), ("schema", 0), ("schema", 3), ("schema", -1), ("schema", "1"), ("schema", NSNull()),
        ("clock", true), ("clock", "1000"), ("clock", -1), ("clock", NSNull()),
        ("clock", Double.nan), ("clock", Double.infinity)]
    for (field, bad) in invalidFields {
        var value = base; value[field] = bad
        try check(MiniSightWakeRemote.decodeState(value) == nil, "invalid state field " + field)
    }
    for field in base.keys {
        var value = base; value.removeValue(forKey: field)
        try check(MiniSightWakeRemote.decodeState(value) == nil, "state exact schema missing " + field)
    }
    var extra = base; extra["syntheticExtra"] = true
    try check(MiniSightWakeRemote.decodeState(extra) == nil, "state exact schema extra")
    let negativeClock = try object(directory, "clock-negative.json")
    try check(MiniSightWakeRemote.decodeState(negativeClock) == nil, "negative writer clock")
    let good = try decoded(directory, "flags-6.json")
    try check(good.isFresh(now: now, revision: revision), "clock now fresh")
    try check(good.isFresh(now: now + 4, revision: revision), "clock inclusive four second freshness")
    try check(!good.isFresh(now: now + 4.001, revision: revision), "clock stale")
    try check(!good.isFresh(now: now - 0.001, revision: revision), "clock future")
    try check(!good.isFresh(now: .nan, revision: revision), "clock invalid now")
    try check(!good.isFresh(now: .infinity, revision: revision), "clock infinite now")
    try check(!good.isFresh(now: now, revision: "SYNTHETIC-OTHER-REV"), "clock revision mismatch")
    let boundaryClock = try decoded(directory, "clock-boundary.json")
    try check(boundaryClock.isFresh(now: now, revision: revision), "writer boundary clock")
    for file in ["clock-stale.json", "clock-future.json"] {
        let state = try decoded(directory, file)
        try check(!state.isFresh(now: now, revision: revision), "writer stale/future clock")
        let c = context(state)
        try check(!c.companionLocked && !c.companionReady, "stale/future means unknown not lock")
        try check(MiniSightWakePolicy.decision(c) == .companion, "stale/future policy stops through readiness")
    }
    return base
}

func policyFixtures(_ directory: String) throws {
    let ready = try decoded(directory, "flags-6.json")
    let locked = try decoded(directory, "flags-0.json")
    let busy = try decoded(directory, "flags-5.json")
    for foreground in [true, false] {
        let unknown = context(nil, foreground: foreground)
        try check(unknown.unlocked && !unknown.companionLocked && !unknown.companionReady && !unknown.companionBusy,
                  "unknown companion is absence of proof, not trusted locked")
        try check(MiniSightWakePolicy.decision(unknown) == .companion, "unknown companion pause reason")
        let untrusted = context(locked, foreground: foreground, freshness: false)
        try check(!untrusted.companionLocked, "untrusted locked ignored")
        try check(MiniSightWakePolicy.decision(untrusted) == .companion, "untrusted lock remains unknown")
        let trusted = context(locked, foreground: foreground)
        try check(trusted.companionLocked, "fresh false unlocked is trusted lock")
        try check(MiniSightWakePolicy.decision(trusted) == .locked, "trusted true lock policy")
        try check(MiniSightWakePolicy.decision(context(busy, foreground: foreground)) == .busy, "companion busy")
        try check(MiniSightWakePolicy.decision(context(ready, foreground: foreground)) == .listen, "authorized foreground/background")
        try check(MiniSightWakePolicy.decision(context(nil, foreground: foreground, enabled: false)) == .disabled, "OFF unknown precedence")
        try check(MiniSightWakePolicy.decision(context(locked, foreground: foreground, enabled: false)) == .disabled, "OFF locked precedence")
        try check(MiniSightWakePolicy.decision(context(ready, foreground: foreground, localUnlocked: false)) == .locked,
                  "local protected-data/lock fact overrides ready companion")
        try check(MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: true, shown: true,
                  enabled: true, cancelled: false), "continuation foreground does not grant/deny intent")
        try check(!MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: false, shown: true,
                  enabled: true, cancelled: false), "continuation locked")
        try check(!MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: true, shown: false,
                  enabled: true, cancelled: false), "continuation hidden")
        try check(!MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: true, shown: true,
                  enabled: false, cancelled: false), "continuation OFF")
        try check(!MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: true, shown: true,
                  enabled: true, cancelled: true), "continuation cancelled, including late completion")
    }
    let transitional = context(nil, foreground: false)
    try check(MiniSightWakePolicy.mayHoldCompanionTransition(transitional, inputRunning: true,
              existingAsset: true, deadline: now + 3), "already authorized input bounded handoff retained")
    try check(!MiniSightWakePolicy.mayHoldCompanionTransition(transitional, inputRunning: false,
              existingAsset: true, deadline: now + 3), "unknown companion cannot open new audio")
    try check(!MiniSightWakePolicy.mayHoldCompanionTransition(transitional, inputRunning: true,
              existingAsset: true, deadline: now), "handoff deadline stops unknown input")
    try check(!MiniSightWakePolicy.mayHoldCompanionTransition(transitional, inputRunning: true,
              existingAsset: true, deadline: now + 3.001), "handoff cannot become indefinite")
    try check(!MiniSightWakePolicy.mayHoldCompanionTransition(context(locked, foreground: false), inputRunning: true,
              existingAsset: true, deadline: now + 3), "fresh lock hard-stops handoff")
    try check(!MiniSightWakePolicy.mayHoldCompanionTransition(context(nil, enabled: false), inputRunning: true,
              existingAsset: true, deadline: now + 3), "OFF hard-stops handoff")
    let app = context(nil, required: false)
    try check(MiniSightWakePolicy.decision(app) == .listen, "foreground App renderer does not require unknown companion")
    try check(MiniSightWakePolicy.decision(context(nil, required: false, localUnlocked: false)) == .locked,
              "App renderer still honors local protected-data fact")
    var c = context(ready); c.armed = false
    try check(MiniSightWakePolicy.decision(c) == .inactive, "not armed")
    c = context(ready); c.shown = false
    try check(MiniSightWakePolicy.decision(c) == .hidden, "hidden pet")
    c = context(ready); c.petStyle = false
    try check(MiniSightWakePolicy.decision(c) == .hidden, "non-pet style")
    c = context(ready); c.hasAsset = false
    try check(MiniSightWakePolicy.decision(c) == .missingAsset, "missing asset")
    c = context(ready); c.permissionGranted = false
    try check(MiniSightWakePolicy.decision(c) == .permission, "permission not granted (no permission request)")
    c = context(ready); c.audioAvailable = false
    try check(MiniSightWakePolicy.decision(c) == .busy, "audio unavailable (no audio opened)")
    c = context(ready); c.recordingOrCall = true
    try check(MiniSightWakePolicy.decision(c) == .busy, "recording/call")
    c = context(ready); c.chatVisible = true
    try check(MiniSightWakePolicy.safetyDecision(c) == nil, "existing response can continue while chat visible")
    try check(MiniSightWakePolicy.decision(c) == .busy, "new hit cannot interrupt chat")
    c = context(ready); c.cooldownUntil = now + 1
    try check(MiniSightWakePolicy.decision(c) == .cooldown, "cooldown")
    c.cooldownUntil = now
    try check(MiniSightWakePolicy.decision(c) == .listen, "cooldown inclusive end")
    c.now = .nan
    try check(MiniSightWakePolicy.decision(c) == .cooldown, "nonfinite policy time")
}
func replyFixtures() throws {
    let value: [String: Any] = ["schema": 1, "clock": now, "host": host, "revision": revision,
        "token": token, "state": "accepted", "responseGeneration": 1, "voiceGeneration": 0, "reason": ""]
    func current(_ reply: MiniSightWakeRemote.Reply, at time: Double = now, expectedToken: String = token) -> Bool {
        MiniSightWakePolicy.remoteReplyCurrent(now: time, clock: reply.clock, token: reply.token,
            expectedToken: expectedToken, host: reply.host, expectedHost: host,
            revision: reply.revision, expectedRevision: revision)
    }
    guard let reply = MiniSightWakeRemote.decodeReply(value), let identity = UUID(uuidString: token),
          let replacement = UUID(uuidString: replacementToken) else {
        throw FixtureFailure(description: "FAIL assertion: decode synthetic accepted reply")
    }
    try check(current(reply), "matching reply token/host/revision")
    try check(current(reply, at: now + 3), "matching reply three second boundary")
    try check(!current(reply, at: now + 3.001), "late reply stale")
    try check(!current(reply, at: now - 0.001), "future reply")
    try check(!current(reply, at: .nan) && !current(reply, at: .infinity), "reply invalid now")
    try check(!current(reply, expectedToken: replacementToken), "late replaced token reply")
    try check(MiniSightWakePolicy.validHit(active: identity, incoming: identity, isListening: true, decision: .listen), "matching active hit")
    try check(!MiniSightWakePolicy.validHit(active: nil, incoming: identity, isListening: true, decision: .listen), "cancel clears active token; late hit rejected")
    try check(!MiniSightWakePolicy.validHit(active: replacement, incoming: identity, isListening: true, decision: .listen), "replacement rejects old token")
    try check(!MiniSightWakePolicy.validHit(active: identity, incoming: identity, isListening: false, decision: .listen), "stopped listener late callback")
    let gatedDecisions: [MiniSightWakePolicy.Decision] = [.disabled, .inactive, .locked, .screenOff, .screenUnknown, .companion, .busy, .cooldown]
    for decision in gatedDecisions {
        try check(!MiniSightWakePolicy.validHit(active: identity, incoming: identity, isListening: true, decision: decision), "gated late hit")
    }
    for state in ["accepted", "voice_requested", "cancelled", "declined"] {
        var message = value; message["state"] = state
        guard let decoded = MiniSightWakeRemote.decodeReply(message) else {
            throw FixtureFailure(description: "FAIL assertion: decode reply state " + state)
        }
        try check(current(decoded), "matching reply state " + state)
        if state == "cancelled" || state == "declined" {
            try check(!MiniSightWakePolicy.permitsContinuation(foreground: false, unlocked: true,
                shown: true, enabled: true, cancelled: true), "cancelled/declined cannot resume late continuation")
        }
    }
    for (field, different) in [("host", otherHost), ("token", replacementToken), ("revision", "SYNTHETIC-OTHER-REV")] {
        var message = value; message[field] = different
        guard let decoded = MiniSightWakeRemote.decodeReply(message) else {
            throw FixtureFailure(description: "FAIL assertion: syntactically valid mismatching reply")
        }
        try check(!current(decoded), "reply mismatch " + field)
    }
    let invalid: [(String, Any)] = [("state", "ready"), ("state", ""), ("state", true), ("token", "invalid"),
        ("host", otherHost.lowercased()), ("revision", ""), ("revision", String(repeating: "R", count: 129)),
        ("schema", true), ("schema", 2), ("clock", true), ("clock", -1), ("clock", Double.nan),
        ("clock", Double.infinity), ("responseGeneration", true), ("responseGeneration", -1),
        ("responseGeneration", "1"), ("responseGeneration", 1.5), ("voiceGeneration", true),
        ("voiceGeneration", -1), ("voiceGeneration", "1"), ("voiceGeneration", 1.5),
        ("reason", "SYNTHETIC\nREASON"), ("reason", String(repeating: "R", count: 97)), ("reason", NSNull())]
    for (field, bad) in invalid {
        var message = value; message[field] = bad
        try check(MiniSightWakeRemote.decodeReply(message) == nil, "invalid reply " + field)
    }
    for field in value.keys {
        var message = value; message.removeValue(forKey: field)
        try check(MiniSightWakeRemote.decodeReply(message) == nil, "reply missing field " + field)
    }
    var extra = value; extra["syntheticExtra"] = true
    try check(MiniSightWakeRemote.decodeReply(extra) == nil, "reply extra field")
}
do {
    try check(CommandLine.arguments.count == 2, "reader temporary directory argument")
    _ = try stateFixtures(CommandLine.arguments[1])
    try policyFixtures(CommandLine.arguments[1])
    try replyFixtures()
    print("PASS native Swift reader/policy: \(assertions) assertions; real ObjC JSON file roundtrip + static decode/policy only")
} catch {
    fputs(String(describing: error) + "\n", stderr)
    exit(1)
}
