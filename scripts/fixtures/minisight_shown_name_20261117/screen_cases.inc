        // Call the literal real NameWakeHost safe function, not a model.
        const BOOL lockProof[5] = { YES, YES, YES, YES, NO };
        const BOOL deviceUnlocked[5] = { YES, NO, YES, YES, NO };
        const BOOL screenProof[5] = { NO, YES, YES, YES, YES };
        const BOOL screenBlank[5] = { NO, NO, YES, NO, NO };
        const BOOL expected[5] = { NO, NO, NO, YES, NO };
        for (NSUInteger i = 0; i < 5; ++i) {
            fixtureLockKnown = lockProof[i]; fixtureUnlocked = deviceUnlocked[i];
            gMiniSightScreenKnown = screenProof[i]; gMiniSightScreenBlanked = screenBlank[i];
            BOOL unlocked = NO, known = NO;
            BOOL safe = MiniSightNameWakeSafe(&unlocked, &known);
            Check(safe == expected[i], @"actual host safety readiness");
            NSDictionary *entry = MSNameWakeStateMessage(host, revision, known, unlocked,
                gMiniSightScreenKnown, gMiniSightScreenBlanked, safe, NO, 1000.);
            // A mutated old host may deliberately misencode lock facts. The
            // actual Swift policy MUST reject that via screen_cases.swift.
            Write(directory, [NSString stringWithFormat:@"screen-%lu.json", (unsigned long)i],
                entry, unlocked, expected[i], NO);
        }
