// macOS Foundation fixture: production monitor + production parser; no MR/network/disk.
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <dispatch/dispatch.h>
#define MINISIGHT_BRIDGE_IO_H
static NSMutableDictionary *disk;
static NSUInteger writes, posts;
static dispatch_semaphore_t entered, resumeWrite;
static BOOL pauseWrite;
static BOOL MSBridgeWrite(NSString *container, NSString *name, NSDictionary *value) {
    if (pauseWrite) { pauseWrite = NO; dispatch_semaphore_signal(entered); dispatch_semaphore_wait(resumeWrite, DISPATCH_TIME_FOREVER); }
    @synchronized (disk) { disk[container] = [value copy]; ++writes; }
    return YES;
}
static NSDictionary *MSBridgeRead(NSString *container, NSString *name, NSUInteger limit) {
    @synchronized (disk) { return disk[container]; }
}
static void MSBridgePost(NSString *name) { ++posts; }
#define MINISIGHT_MUSIC_MONITOR_TEST 1
#import "MiniSightMusicMonitor.m"

static NSString *fixturePlayer = @"com.apple.Music";
static BOOL fixtureLocked;
@interface SBLockScreenManager : NSObject
+ (instancetype)sharedInstance;
- (BOOL)isUILocked;
@end
@implementation SBLockScreenManager
+ (instancetype)sharedInstance { static id value; if (!value) value = [self new]; return value; }
- (BOOL)isUILocked { return fixtureLocked; }
@end
@interface SBMediaController : NSObject
+ (instancetype)sharedInstance;
- (id)nowPlayingApplication;
- (NSString *)bundleIdentifier;
@end
@implementation SBMediaController
+ (instancetype)sharedInstance { static id obj; if (!obj) obj = [self new]; return obj; }
- (id)nowPlayingApplication { return fixturePlayer ? self : nil; }
- (NSString *)bundleIdentifier { return fixturePlayer; }
@end
@interface SBApplicationController : NSObject
@end
@implementation SBApplicationController
+ (instancetype)sharedInstance { return [self new]; }
- (id)applicationWithPid:(NSInteger)pid { return pid == 123 ? @"com.netease.cloudmusic" : @"com.not.allowed"; }
@end
static int secondPID; static NSUInteger pidCalls;
static void GetPID(dispatch_queue_t q, void (^cb)(int)) { cb(++pidCalls == 1 ? 123 : secondPID); }
@interface WrongReturn : NSObject
- (double)bad;
@end
@implementation WrongReturn
- (double)bad { return 3.5; }
@end
@interface FakeClient : NSObject
@property NSUInteger requests;
@property NSUInteger cancels;
@property(copy) MiniSightLyricsCompletion completion;
@end
@implementation FakeClient
- (void)cancel { ++_cancels; }
- (void)fetchTrack:(MiniSightLyricsTrack *)track result:(MiniSightLyricsResult)completion {
    ++_requests; self.completion = ^(MiniSightLyricsTimeline *t){ completion(t,t ? @"lyrics_timeline" : @"lyrics_not_found"); };
}
@end
static NSMutableArray *infos, *states;
static NSUInteger maxPending;
static void NotePending(void) { maxPending = MAX(maxPending, infos.count + states.count); }
static void GetInfo(dispatch_queue_t q, void (^cb)(CFDictionaryRef)) { [infos addObject:[cb copy]]; NotePending(); }
static void GetState(dispatch_queue_t q, void (^cb)(Boolean)) { [states addObject:[cb copy]]; NotePending(); }
static void Check(BOOL ok, const char *message) { if (!ok) { fprintf(stderr, "FAIL: %s\n", message); exit(1); } }
static void Pump(void) { [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.015]]; }
static NSMutableDictionary *Info(NSString *title, NSString *identifier) {
    return [@{@"kMRMediaRemoteNowPlayingInfoTitle":title, @"kMRMediaRemoteNowPlayingInfoArtist":@"Fixture Artist",
        @"kMRMediaRemoteNowPlayingInfoDuration":@120, @"kMRMediaRemoteNowPlayingInfoElapsedTime":@1,
        @"kMRMediaRemoteNowPlayingInfoPlaybackRate":@1, @"kMRMediaRemoteNowPlayingInfoTimestamp":NSDate.date,
        @"kMRMediaRemoteNowPlayingInfoUniqueIdentifier":identifier} mutableCopy];
}
static void GiveInfo(NSDictionary *info, BOOL mutate) {
    Check(infos.count == 1, "one info request");
    void (^cb)(CFDictionaryRef) = infos.firstObject; [infos removeObjectAtIndex:0];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        cb((__bridge CFDictionaryRef)info);
        if (mutate) [(NSMutableDictionary *)info setObject:@"Mutated" forKey:@"kMRMediaRemoteNowPlayingInfoTitle"];
    });
    Pump();
}
static void GiveState(BOOL playing) {
    Check(states.count == 1, "one state request");
    void (^cb)(Boolean) = states.firstObject; [states removeObjectAtIndex:0];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ cb(playing); }); Pump();
}
static MiniSightMusicMonitor *NewMonitor(FakeClient **client) {
    [infos removeAllObjects]; [states removeAllObjects]; fixturePlayer = @"com.apple.Music";
    MiniSightMusicMonitor *m = [MiniSightMusicMonitor new]; *client = [FakeClient new];
    [m setValue:*client forKey:@"client"];
    m.updateHandler = ^(NSDictionary *s) { Check(NSThread.isMainThread, "main update callback"); };
    m.presentationHandler = ^{ return @{@"allowed": @YES, @"stopReason": @"eligible"}; };
    [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"];
    return m;
}
static void Stop(MiniSightMusicMonitor *m) {
    [m configureAllowed:NO lyrics:YES motion:YES container:@"fixture-A"];
    dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
}
static void Kick(MiniSightMusicMonitor *m) { [m setValue:@0 forKey:@"pollAt"]; [m tick]; }
static void Song(NSString *title, NSString *identifier) {
    GiveInfo(Info(title, identifier), NO); GiveState(YES); GiveInfo(Info(title, identifier), NO);
}
int main(void) { @autoreleasepool {
    disk = [NSMutableDictionary dictionary]; infos = [NSMutableArray array]; states = [NSMutableArray array];
    MSMusicInfo = GetInfo; MSMusicIsPlaying = GetState;
    Check(MSMusicObject([WrongReturn new], @"bad") == nil, "reject scalar ObjC return ABI");
    NSString *playerReason = nil;
    fixturePlayer = @"com.netease.cloudmusic";
    Check([MSMusicResolvePlayer(&playerReason) isEqual:@"com.netease.cloudmusic"] &&
          [playerReason isEqual:@"netease_player_selected"], "identify NetEase Music with fixed reason");
    fixturePlayer = @"fixture.unsupported";
    Check(MSMusicResolvePlayer(&playerReason) == nil && [playerReason isEqual:@"unsupported_player"],
          "identify unsupported player without logging its bundle ID");
    for (NSString *p in @[@"com.tencent.QQMusic", @"com.kugou.kugou1002", @"com.yeelion.kwplayer", @"com.apple.Music"]) {
        fixturePlayer = p; Check([MSMusicResolvePlayer(NULL) isEqual:p], "supported player allowlist remains intact");
    }
    Check([MiniSightMusicMonitor deviceIsUnlocked], "explicit unlocked lock-state ABI");
    fixtureLocked = YES; Check(![MiniSightMusicMonitor deviceIsUnlocked], "lock is not the same as a lit screen");
    fixtureLocked = NO;
    FakeClient *c; MiniSightMusicMonitor *m = NewMonitor(&c);
    NSMutableDictionary *partial = Info(@"A", @"1");
    [partial removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoArtist"];
    GiveInfo(partial, NO); GiveState(YES); GiveInfo(Info(@"A", @"1"), NO);
    Check(c.requests == 1, "partial->complete reaches real lyric client");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]fresh" duration:120]); Pump();
    Kick(m); Song(@"A", @"1");
    Check([m.snapshot[@"line"] isEqual:@"fresh"], "recovered metadata displays current line");
    // MediaRemote IDs are not stable across all players; complete matching
    // metadata keeps the same cached song and timeline.
    NSMutableDictionary *churnedID = Info(@"A", @"2");
    [m applyInfo:churnedID playing:YES player:@"com.apple.Music"];
    Check(c.requests == 1 && [m.snapshot[@"line"] isEqual:@"fresh"], "complete track identity survives MediaRemote ID churn");
    NSMutableDictionary *withoutID = Info(@"A", @"2");
    [withoutID removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoUniqueIdentifier"];
    [m applyInfo:withoutID playing:YES player:@"com.apple.Music"];
    Check(c.requests == 1 && [m.snapshot[@"line"] isEqual:@"fresh"], "identifier omission preserves validated timeline");
    [m applyInfo:partial playing:YES player:@"com.apple.Music"];
    Check(![m.snapshot[@"line"] length] && c.requests == 1, "partial metadata clears display without fetching stale track");
    NSMutableDictionary *changedID = [partial mutableCopy];
    changedID[@"kMRMediaRemoteNowPlayingInfoUniqueIdentifier"] = @"2";
    [m applyInfo:changedID playing:YES player:@"com.apple.Music"];
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length], "partial new identifier invalidates old lyrics");
    Stop(m);
    m = NewMonitor(&c);
    GiveInfo(partial, NO); GiveState(YES); GiveInfo(Info(@"B", @"2"), NO);
    Check(c.requests == 0 && ![m.snapshot[@"line"] length], "partial conflicting title/identifier rejected");
    Stop(m);
    m = NewMonitor(&c);
    NSMutableDictionary *drift = Info(@"A", @"1");
    drift[@"kMRMediaRemoteNowPlayingInfoDuration"] = @121;
    GiveInfo(Info(@"A", @"1"), NO); GiveState(YES); GiveInfo(drift, NO);
    Check(c.requests == 0, "track identity is exact, not response-duration tolerance");
    Stop(m);
    m = NewMonitor(&c);
    for (int i = 0; i < 1000; ++i) [m mediaChanged:nil]; Pump();
    Check(infos.count == 1 && states.count == 0, "storm retains physical slot");
    [m setValue:@(MSMusicNow() - 4) forKey:@"readAt"]; [m tick];
    for (int i = 0; i < 100; ++i) {
        [m configureAllowed:NO lyrics:YES motion:YES container:@"fixture-A"];
        [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"]; [m tick];
    }
    Check(infos.count == 1 && [[m valueForKey:@"reading"] boolValue], "timeout/reopen cannot replace missing callback");
    GiveInfo(Info(@"A", @"1"), NO);
    Check(states.count == 0, "late generation rejected before next API"); Stop(m);

    m = NewMonitor(&c); Song(@"A", @"1");
    fixtureLocked = YES; [m tick];
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] &&
        [m valueForKey:@"timer"] == nil, "lock stops lyrics and motion without more reads");
    Stop(m); fixtureLocked = NO;
    m = NewMonitor(&c); GiveInfo(Info(@"A", @"1"), NO); GiveState(YES); GiveInfo(Info(@"B", @"2"), NO);
    Check(c.requests == 0 && ![m.snapshot[@"playing"] boolValue], "same-player sandwich mismatch"); Stop(m);
    m = NewMonitor(&c); GiveInfo(Info(@"A", @"1"), YES); GiveState(YES); GiveInfo(Info(@"A", @"1"), NO);
    Check(c.requests == 1, "borrowed data copied before queue hop");
    MiniSightLyricsCompletion old = c.completion;
    [m configureAllowed:NO lyrics:NO motion:NO container:@"fixture-A"];
    old([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]old lyric" duration:120]); Pump();
    Check(![m.snapshot[@"line"] length] && [m valueForKey:@"timeline"] == nil, "cancel fences queued lyrics"); Stop(m);

    m = NewMonitor(&c); Song(@"A", @"1");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]old lyric" duration:120]); Pump();
    Check(![m.snapshot[@"line"] length], "lyrics result waits for identity refresh");
    Kick(m); Song(@"B", @"2");
    Check(![m.snapshot[@"line"] length] && c.requests == 2, "late A never displayed as B"); Stop(m);
    m = NewMonitor(&c); Song(@"A", @"1");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]current lyric" duration:120]); Pump();
    Kick(m); Song(@"A", @"1");
    Check([m.snapshot[@"line"] isEqual:@"current lyric"] && [m.snapshot[@"playing"] boolValue], "fresh matching sample displays current lyric");
    Stop(m);

    m = NewMonitor(&c); Song(@"A", @"1");
    for (int i = 0; i < 20; ++i) {
        [m configureAllowed:NO lyrics:YES motion:YES container:@"fixture-A"];
        [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"];
        [m applyInfo:Info(@"A", [@(i) stringValue]) playing:YES player:@"com.apple.Music"];
    }
    Check(c.requests == 1, "single signature cooldown survives reopen/identifier churn"); Stop(m);
    m = NewMonitor(&c); Song(@"A", @"1");
    NSMutableDictionary *stale = Info(@"A", @"1");
    stale[@"kMRMediaRemoteNowPlayingInfoTimestamp"] = [NSDate dateWithTimeIntervalSinceNow:-30];
    [m applyInfo:stale playing:YES player:@"com.apple.Music"];
    Check([m.snapshot[@"playing"] boolValue], "a valid old reference still advances playback");
    Check([[m valueForKey:@"elapsed"] doubleValue] + MSMusicNow() - [[m valueForKey:@"stamp"] doubleValue] >= 30.,
        "reference timestamp contributes to current elapsed time");
    stale[@"kMRMediaRemoteNowPlayingInfoTimestamp"] = [NSDate dateWithTimeIntervalSinceNow:-300];
    [m applyInfo:stale playing:YES player:@"com.apple.Music"];
    Check(![m.snapshot[@"playing"] boolValue], "impossible reference past track end fails closed");
    [m applyInfo:Info(@"A", @"1") playing:NO player:@"com.apple.Music"];
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length], "pause clears line/motion");
    dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
    entered = dispatch_semaphore_create(0); resumeWrite = dispatch_semaphore_create(0);
    NSUInteger before = writes; pauseWrite = YES;
    [m publishLine:@"first" playing:YES force:YES];
    Check(dispatch_semaphore_wait(entered, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC)) == 0, "writer entered");
    for (int i = 0; i < 1000; ++i) [m publishLine:[@(i) stringValue] playing:YES force:YES];
    [m configureAllowed:NO lyrics:YES motion:YES container:@"fixture-A"];
    dispatch_semaphore_signal(resumeWrite); dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
    Check(writes - before <= 2, "writer has only in-flight plus latest mailbox");
    Check(![disk[@"fixture-A"][@"line"] length], "latest disable scrubs disk after in-flight write");
    [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"];
    [m publishLine:@"private current line" playing:YES force:YES];
    dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
    [m configureAllowed:NO lyrics:NO motion:NO container:@"fixture-B"];
    dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
    Check(![disk[@"fixture-A"][@"line"] length] && ![disk[@"fixture-B"][@"line"] length], "container switch clears old and new");
    Check(disk[@"fixture-A"][@"title"] == nil && disk[@"fixture-A"][@"artist"] == nil, "no metadata persisted");
    Check(maxPending <= 1, "at most one pending native API callback");
    m = NewMonitor(&c); Song(@"Recovery", @"recovery");
    c.completion(nil); Pump();
    Check([m.snapshot[@"diagnostics"][@"lyricsDetail"] isEqual:@"lyrics_not_found"], "fixed lyric failure code survives snapshot");
    Check([m.snapshot[@"playing"] boolValue], "no LRC/network failure cannot stop motion");
    [m configureAllowed:NO lyrics:YES motion:YES container:@"fixture-A"];
    [m configureAllowed:YES lyrics:NO motion:YES container:@"fixture-A"];
    Song(@"Recovery", @"recovery");
    Check([m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"lyricsEnabled"] boolValue], "allowed false->true and lyrics switch recover motion");
    for (NSString *flag in @[@"playing", @"allowed", @"lyricsEnabled", @"motionEnabled", @"requestedLyrics", @"requestedMotion"]) {
        Check(CFGetTypeID((__bridge CFTypeRef)m.snapshot[flag]) == CFBooleanGetTypeID(), "writer flags are CFBoolean not logical int");
    }
    NSDictionary *decoded = [NSJSONSerialization JSONObjectWithData:[NSJSONSerialization dataWithJSONObject:m.snapshot options:0 error:nil] options:0 error:nil];
    Check(CFGetTypeID((__bridge CFTypeRef)decoded[@"playing"]) == CFBooleanGetTypeID(), "real writer->JSON->reader boolean round trip");
    __block BOOL visibleGate = YES;
    m.presentationHandler = ^{ return @{@"allowed": @((BOOL)visibleGate), @"stopReason": visibleGate ? @"eligible" : @"screen_state_unknown", @"screenKnown": @((BOOL)visibleGate)}; };
    visibleGate = NO; [m tick];
    Check([m valueForKey:@"timer"] == nil && ![m.snapshot[@"allowed"] boolValue] &&
        [m.snapshot[@"stopReason"] isEqual:@"screen_state_unknown"], "unknown screen gate shuts down without polling");
    NSUInteger pendingAtStop = infos.count + states.count;
    [m tick]; Check(infos.count + states.count == pendingAtStop, "no hidden/unknown polling");
    visibleGate = YES; [m configureAllowed:YES lyrics:NO motion:YES container:@"fixture-A"];
    if (infos.count) Song(@"Recovery", @"recovery");
    Check([m.snapshot[@"playing"] boolValue], "visible show restores after unknown shutdown");
    Stop(m);
    m = NewMonitor(&c);
    NSDictionary *unknown = @{@"kMRMediaRemoteNowPlayingInfoPlaybackRate":@1};
    GiveInfo(unknown, NO); GiveState(YES); GiveInfo(unknown, NO);
    Check([m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] && c.requests == 0, "unknown track allows motion but never lyrics/status text");
    Stop(m);
    for (int changed=0; changed<2; changed++) {
        [infos removeAllObjects];
        m = [MiniSightMusicMonitor new]; c = [FakeClient new]; [m setValue:c forKey:@"client"];
        m.presentationHandler = ^{return @{@"allowed": @YES};}; fixturePlayer=nil;
        MSMusicPID = GetPID; pidCalls=0; secondPID=changed?456:123;
        [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"]; Pump();
        Song(@"Fixture", @"123"); Pump();
        Check(pidCalls == 2 && c.requests == (changed ? 0 : 1), "fresh PID sandwich, no stale track on PID switch");
        if (!changed) {
            Check([m.snapshot[@"source"] isEqual:@"com.netease.cloudmusic"], "exact PID source published");
            [m handleMediaChange];
            Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length], "PID candidate cannot display unverified state");
            Kick(m); Pump(); Song(@"Fixture", @"123"); Pump();
            Check(c.requests == 1 && [m.snapshot[@"playing"] boolValue], "stable reverified PID retains pending lookup");
        }
        Stop(m); MSMusicPID=NULL;
    }
    fixturePlayer = @"com.netease.cloudmusic.extra"; MSMusicPID = GetPID; pidCalls = 0;
    m = [MiniSightMusicMonitor new]; m.presentationHandler = ^{return @{@"allowed": @YES};};
    [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"]; Pump();
    Check(pidCalls == 0 && ![m.snapshot[@"playing"] boolValue] &&
        [m.snapshot[@"diagnostics"][@"playerDetail"] isEqual:@"unsupported_player"], "explicitly unsupported never falls back to PID");
    Stop(m); MSMusicPID=NULL;
    puts("NATIVE PASS: ABI, five players, CF copy, main callbacks, storm, timeout/reopen, sandwich, late lyrics, cooldown, pause/stale, bridge mailbox/privacy, recovery/switches, unknown gate, no-LRC motion, real JSON booleans");
    return 0;
} }
