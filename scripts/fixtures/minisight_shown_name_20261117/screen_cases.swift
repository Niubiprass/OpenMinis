func screenCases(_ directory: String) throws {
    let decisions: [MiniSightWakePolicy.Decision] = [.screenUnknown, .locked, .screenOff, .listen, .screenUnknown]
    for i in 0..<5 {
        let state = try decoded(directory, "screen-\(i).json")
        for field in ["lockKnown", "unlocked", "screenKnown", "screenOff", "allowed", "busy"] {
            let wire = try object(directory, "screen-\(i).json")
            guard let number = wire[field] as? NSNumber else { throw FixtureFailure(description: "missing bool") }
            try check(CFGetTypeID(number) == CFBooleanGetTypeID(), "host wire exact boolean " + field)
        }
        for foreground in [false, true] {
            let c = context(state, foreground: foreground)
            if i == 0 { try check(!c.companionLocked, "unknown screen is not trusted locked") }
            try check(c.companionLocked == (i == 1), "only known lock sets trusted locked")
            try check(MiniSightWakePolicy.decision(c) == decisions[i], "host screen reason exact")
            try check(state.allowed == (i == 3), "unsafe host fails closed")
            if i != 3 {
                try check(!MiniSightWakePolicy.mayHoldCompanionTransition(c, inputRunning: true,
                    existingAsset: true, deadline: now + 3), "screen unknown/off/known lock hard stops input")
            }
        }
    }
    // Legacy false is ambiguous; pause with accurate unknown rather than lock.
    var legacy = try object(directory, "flags-0.json")
    legacy["schema"] = 1
    for key in ["lockKnown", "screenKnown", "screenOff"] { legacy.removeValue(forKey: key) }
    guard let state = MiniSightWakeRemote.decodeState(legacy) else { throw FixtureFailure(description: "legacy state rejected") }
    let c = context(state)
    try check(!c.companionLocked && !c.companionReady, "old false is not lock proof")
    try check(MiniSightWakePolicy.decision(c) == .screenUnknown, "legacy unsafe reason unknown")
    print("PASS native literal host producer -> boolean writer -> Swift reader: screen unknown/locked/off/unlocked")
}
