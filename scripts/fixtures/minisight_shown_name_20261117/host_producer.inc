static NSString *MiniSightNameWakeRevision(void) {
    id value = MiniSightPref(@"minisight.settings.revision");
    return [value isKindOfClass:NSString.class] && [value length] <= 128 ? value : @"";
}
static BOOL MiniSightNameWakeEnabled(void) {
    id value = MiniSightPref(@"minisight.wake.enabled");
    return [value isKindOfClass:NSNumber.class] && [value boolValue];
}
static BOOL MiniSightNameWakeSafe(BOOL *unlockedOut, BOOL *lockKnownOut) {
    MiniSightReadScreenState();
    BOOL lockKnown = NO;
    BOOL unlocked = [MiniSightMusicMonitor deviceIsUnlockedWithKnown:&lockKnown];
    if (unlockedOut) *unlockedOut = unlocked;
    if (lockKnownOut) *lockKnownOut = lockKnown;
    id shownPref = MiniSightPref(@"minisight.shown");
    BOOL shown = MiniSightShown() && (!shownPref || ([shownPref isKindOfClass:NSNumber.class] && [shownPref boolValue]));
    return MSNWAllowed(MiniSightNameWakeEnabled(), shown, MiniSightStyle() == 1,
        gMiniSightResourcesReady && !gMiniSightResourceLoading, gMiniSightContainer.length > 0,
        MiniSightNameWakeRevision().length > 0, gMiniSightScreenKnown, gMiniSightScreenBlanked,
        unlocked, MiniSightRenderer() == 1, MiniSightMinisIsFrontmost());
}
