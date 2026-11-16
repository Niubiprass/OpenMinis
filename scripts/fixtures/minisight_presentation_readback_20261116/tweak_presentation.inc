// Literal production excerpt; dependencies alone are mocked.
static void MiniSightApplyShownReadback(void) {
    BOOL known = [MiniSightPref(@"_minisightShownKnown") boolValue];
    BOOL shown = known && [MiniSightPref(@"_minisightShown") boolValue];
    if (known && !shown && !gMiniSightShownWritePending) gMiniSightHideObservedOff = YES;
    if (gMiniSightUserHidden) {
        NSString *identity = [MiniSightPref(@"_minisightShownIdentity") isKindOfClass:NSString.class]
            ? MiniSightPref(@"_minisightShownIdentity") : @"";
        if (!gMiniSightHidePreviousShownIdentity.length && identity.length && !gMiniSightShownWritePending) {
            // A restarted host first anchors the already-present ON without
            // un-hiding. Only a later distinct file transaction may release it.
            gMiniSightHidePreviousShownIdentity = [identity copy];
        }
        BOOL changed = identity.length && ![identity isEqualToString:gMiniSightHidePreviousShownIdentity];
        // Runtime ON alone never releases a menu hide. Require observed OFF
        // or a NEW atomic shown-file write relative to the failed hide's file.
        if (MSMusicShownMayReleaseHidden(known, shown, gMiniSightShownWritePending,
                gMiniSightHideObservedOff, gMiniSightHidePreviousShownIdentity.length > 0, changed)) {
            gMiniSightUserHidden = NO;
            gMiniSightHidePreviousShownIdentity = nil;
            MSMiniSightSetPreference(@"MiniSightUserHidden", @NO);
        } else shown = NO;
    }
    gMiniSightShown = shown;
}

static void MiniSightRequestResources(BOOL force, void (^completion)(void)) {
    NSCAssert([NSThread isMainThread], @"Resource state is main-thread only");
    if (completion) {
        if (!gMiniSightResourceCompletions) gMiniSightResourceCompletions = [NSMutableArray array];
        [gMiniSightResourceCompletions addObject:[completion copy]];
    }
    if (gMiniSightResourceLoading) {
        if (force) gMiniSightResourceRefreshAgain = YES;
        return;
    }
    if (gMiniSightResourcesReady && !force) {
        NSArray *pending = [gMiniSightResourceCompletions copy];
        [gMiniSightResourceCompletions removeAllObjects];
        for (void (^block)(void) in pending) block();
        return;
    }
    gMiniSightResourceLoading = YES;
    uint64_t epoch = MSMusicNextEpoch(&gMiniSightSettingsEpoch);
    [MiniSightResources refresh:^(NSString *container, NSDictionary *preferences, BOOL shown, UIImage *atlas) {
        gMiniSightResourceLoading = NO;
        if (!MSMusicEpochIsCurrent(gMiniSightSettingsEpoch, epoch)) {
            gMiniSightResourceRefreshAgain = NO;
            MiniSightRequestResources(YES, nil); // latest read after any queued user hide
            return;
        }
        gMiniSightContainer = [container copy];
        gMiniSightPreferences = [preferences copy] ?: @{};
        gMiniSightPreferencesEpoch = epoch;
        MiniSightChatPanel *panel = MiniSightChatPanel.existingPanel;
        panel.containerPath = gMiniSightContainer;
        panel.appearancePreferences = gMiniSightPreferences;
        gMiniSightShown = shown;
        gMiniSightAtlas = atlas;
        gMiniSightTintBase = atlas;
        gMiniSightActionManifest = [preferences[@"_minisightActionManifest"] isKindOfClass:NSString.class]
            ? [preferences[@"_minisightActionManifest"] copy] : nil;
        gMiniSightPet.actionManifestPath = gMiniSightActionManifest;
        NSInteger spriteLayout = MiniSightSpriteLayoutForContainer(container);
        MSDiagEvent(@"assets", @"layout", @"ok", @{ @"source": @"plugin", @"layout": @(spriteLayout), @"container": @(container.length > 0) });
        if (gMiniSightPet) {
            gMiniSightPet.spriteLayout = spriteLayout;
            if (atlas) {
                gMiniSightPet.image = atlas;
                MiniSightApplyTint(MiniSightRuntimeConfig.shared.tint);
            }
        }
        [MiniSightRuntimeConfig.shared reloadWithContainer:container];
        MSDiagConfigure([preferences[@"minisight.diagnostics"] boolValue], container);
        MSDiagSettingsSnapshot(@"receive", @"plugin", gMiniSightPreferences);
        MSDiagEvent(@"assets", @"load", atlas ? @"ok" : @"skipped", @{ @"source": @"plugin", @"setting": @"pet", @"reason": atlas ? @"atlas_decoded" : @"missing_or_invalid_atlas" });
        gMiniSightResourcesReady = YES;
        MiniSightConfigureRecorder();
        MiniSightReadActivitySnapshot();
        if (gMiniSightResourceRefreshAgain) {
            gMiniSightResourceRefreshAgain = NO;
            MiniSightRequestResources(YES, nil);
            return;
        }
        MiniSightConvergeSettings(YES);
        if (!MiniSightShown()) MiniSightDestroyUI();
        if (gMiniSightResourceLoading) return; // preserve queued callbacks for the current resource pass
        NSArray *pending = [gMiniSightResourceCompletions copy];
        [gMiniSightResourceCompletions removeAllObjects];
        for (void (^block)(void) in pending) block();
        MiniSightUpdateMusic();
        MiniSightNameWakeUpdate();
    }];
}

static void MiniSightConvergeSettings(BOOL resourcesFresh) {
    NSCAssert(NSThread.isMainThread, @"Latest settings convergence is main-thread owned");
    if (!MSMusicEpochIsCurrent(gMiniSightSettingsEpoch, gMiniSightPreferencesEpoch)) {
        MiniSightReloadSettings();
        return;
    }
    BOOL wasUserHidden = gMiniSightUserHidden;
    MiniSightApplyShownReadback();
    NSInteger renderer = MiniSightRenderer(), style = MiniSightStyle();
    BOOL structural = renderer != gMiniSightAppliedRenderer || style != gMiniSightAppliedStyle;
    if (structural) {
        MiniSightStopGravity();
        MiniSightDestroyUI();
        if (!resourcesFresh) { MiniSightRequestResources(YES, nil); return; }
        // Re-evaluate at the RESOURCE tail, not from an old settings completion.
        gMiniSightAppliedRenderer = renderer;
        gMiniSightAppliedStyle = style;
        if (MiniSightShown() && !MiniSightAppOwnsPresentation()) {
            if (gMiniSightBurst || MiniSightAlwaysShow()) MiniSightShow();
            else MiniSightBuildUI(); // hidden call-mode host, never force show
        }
    } else {
        if (wasUserHidden && !gMiniSightUserHidden) MiniSightShow(); // fences an old hide fade
        MiniSightApplySettingsLive();
    }
    MiniSightUpdateMusic();
    MiniSightNameWakeUpdate();
}

static void MiniSightReloadSettings(void) {
    NSCAssert(NSThread.isMainThread, @"Settings requests are main-thread owned");
    uint64_t epoch = MSMusicNextEpoch(&gMiniSightSettingsEpoch);
    if (gMiniSightResourceLoading) {
        gMiniSightResourceRefreshAgain = YES;
        return; // the resource tail will read and apply the latest full state
    }
    if (gMiniSightSettingsLoading) {
        gMiniSightSettingsRefreshAgain = YES;
        return;
    }
    gMiniSightSettingsLoading = YES;
    gMiniSightSettingsRefreshAgain = NO;
    [MiniSightResources refreshPreferences:^(NSString *container, NSDictionary *preferences) {
        gMiniSightSettingsLoading = NO;
        if (!MSMusicEpochIsCurrent(gMiniSightSettingsEpoch, epoch) || gMiniSightSettingsRefreshAgain) {
            gMiniSightSettingsRefreshAgain = NO;
            MiniSightReloadSettings(); // stale completion cannot swallow the last requested apply
            return;
        }
        gMiniSightContainer = [container copy];
        gMiniSightPreferences = [preferences copy] ?: @{};
        gMiniSightPreferencesEpoch = epoch;
        [MiniSightRuntimeConfig.shared reloadWithContainer:gMiniSightContainer];
        MiniSightConfigureRecorder();
        MSDiagSettingsSnapshot(@"receive", @"plugin", gMiniSightPreferences);
        MSDiagEvent(@"settings", @"reload", @"ok", @{ @"source": @"plugin", @"reason": @"darwin_notification" });
        MiniSightConvergeSettings(NO);
    }];
}

static void MiniSightUserHide(void) {
    gMiniSightNameWakePresentationHeld = NO;
    MiniSightNameWakeCancel(@"user_hidden", YES);
    gMiniSightNameWakePresentationHeld = NO;
    gMiniSightShown = NO;
    gMiniSightUserHidden = YES;
    MSMiniSightSetPreference(@"MiniSightUserHidden", @YES);
    // The preference helper owns only position/UserHidden; minisight.shown
    // was a no-op there. Preserve the authoritative hide file, never force
    // runtime.json ON over it. Fence any delayed old resource/settings read.
    MSMusicNextEpoch(&gMiniSightSettingsEpoch);
    MSMusicNextEpoch(&gMiniSightFadeEpoch);
    gMiniSightShownWritePending = YES;
    gMiniSightHideObservedOff = NO;
    gMiniSightHidePreviousShownIdentity = nil;
    uint64_t writeEpoch = MSMusicNextEpoch(&gMiniSightShownWriteEpoch);
    NSString *hideContainer = [gMiniSightContainer copy];
    [MiniSightResources writeShown:NO container:hideContainer verifiedReadback:^(BOOL verified, NSString *previousIdentity) {
        if (!MSMusicEpochIsCurrent(gMiniSightShownWriteEpoch, writeEpoch)) return;
        gMiniSightShownWritePending = NO;
        BOOL sameContainer = [hideContainer isEqualToString:gMiniSightContainer];
        gMiniSightHidePreviousShownIdentity = sameContainer ? [previousIdentity copy] : nil;
        gMiniSightHideObservedOff = verified && sameContainer;
        MSDiagEvent(@"settings", @"shown_save", verified ? @"ok" : @"failed",
            @{ @"source": @"plugin", @"shown": @NO, @"reason": verified ? @"verified_readback" : @"write_or_readback_failed" });
        MiniSightReloadSettings(); // same queue: readback -> notify -> latest apply
    }];
    MiniSightUpdateMusic();
    [[MiniSightChatPanel existingPanel] close];
    MiniSightCancelConfirm(); // hide must not be blocked by an approval bubble
    MiniSightHide();
    [[NSNotificationCenter defaultCenter] postNotificationName:@"MiniSightUserHiddenChanged" object:nil];
}
