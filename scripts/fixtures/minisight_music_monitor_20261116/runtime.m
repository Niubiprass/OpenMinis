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
static id fixturePIDController;
static NSString *fixturePIDBundle = @"com.netease.cloudmusic";
static BOOL fixtureControllerMissing;
@implementation SBApplicationController
+ (instancetype)sharedInstance { return fixtureControllerMissing ? nil : (fixturePIDController ?: [self new]); }
- (id)applicationWithPid:(int)pid { return pid == 123 ? fixturePIDBundle : nil; }
@end
@interface PIDNSInteger : NSObject
- (id)applicationWithPid:(NSInteger)pid;
@end
@implementation PIDNSInteger
- (id)applicationWithPid:(NSInteger)pid { return pid == 123 ? fixturePIDBundle : @"com.tencent.QQMusic"; }
@end
@interface PIDSameBundle : NSObject
- (id)applicationWithPid:(int)pid;
@end
@implementation PIDSameBundle
- (id)applicationWithPid:(int)pid { return pid > 0 ? fixturePIDBundle : nil; }
@end
@interface PIDFloat : NSObject
- (id)applicationWithPid:(double)pid;
@end
@implementation PIDFloat
- (id)applicationWithPid:(double)pid { abort(); }
@end
@interface PIDObject : NSObject
- (id)applicationWithPid:(id)pid;
@end
@implementation PIDObject
- (id)applicationWithPid:(id)pid { abort(); }
@end
@interface PIDNoSignature : SBApplicationController
@end
@implementation PIDNoSignature
- (NSMethodSignature *)methodSignatureForSelector:(SEL)sel {
    return sel == @selector(applicationWithPid:) ? nil : [super methodSignatureForSelector:sel];
}
@end
static NSMutableArray *pids;
static NSUInteger pidCalls;
static void NotePending(void);
static void GetPID(dispatch_queue_t q, void (^cb)(int)) { ++pidCalls; [pids addObject:[cb copy]]; NotePending(); }
static NSTimeInterval fixtureTime = 1000.;
static NSTimeInterval FixtureNow(void) { return fixtureTime; }
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
static void NotePending(void) { maxPending = MAX(maxPending, infos.count + states.count + pids.count); }
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
static void GivePID(int pid) {
    Check(pids.count == 1, "one PID request");
    void (^cb)(int) = pids.firstObject; [pids removeObjectAtIndex:0];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ cb(pid); }); Pump();
}
static void GiveState(BOOL playing) {
    Check(states.count == 1, "one state request");
    void (^cb)(Boolean) = states.firstObject; [states removeObjectAtIndex:0];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ cb(playing); }); Pump();
}
static MiniSightMusicMonitor *NewMonitor(FakeClient **client) {
    [infos removeAllObjects]; [states removeAllObjects]; [pids removeAllObjects]; fixturePlayer = @"com.apple.Music";
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
static NSMutableDictionary *DurationInfo(double duration, NSString *identifier) {
    NSMutableDictionary *info = Info(@"Continuity", identifier);
    info[@"kMRMediaRemoteNowPlayingInfoDuration"] = @(duration);
    return info;
}
static void DurationSong(double first, double last) {
    GiveInfo(DurationInfo(first, @"duration-id"), NO); GiveState(YES);
    GiveInfo(DurationInfo(last, @"duration-id"), NO);
}
static MiniSightMusicMonitor *ReadyDuration(FakeClient **client) {
    MiniSightMusicMonitor *m = NewMonitor(client);
    DurationSong(261., 261.);
    Check((*client).requests == 1, "one mocked lyrics GET dispatch, not bridge POST");
    (*client).completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]duration-current" duration:261]); Pump();
    Check(![m.snapshot[@"line"] length], "fetch result still requires a fresh sandwich");
    Kick(m); DurationSong(261.1316, 261.2245);
    Check([m.snapshot[@"line"] isEqual:@"duration-current"] && (*client).requests == 1,
        "261 -> 261.1316/261.2245 fresh double read reuses timeline without another lyrics GET");
    return m;
}
static void TestPendingDurationContinuity(void) {
    FakeClient *c; MiniSightMusicMonitor *m = NewMonitor(&c);
    DurationSong(261., 261.);
    MiniSightLyricsTrack *anchor = [m valueForKey:@"track"];
    NSUInteger generation = [[m valueForKey:@"trackGeneration"] unsignedIntegerValue];
    MiniSightLyricsCompletion pending = [c.completion copy];
    Kick(m); DurationSong(261.1316, 261.2245);
    Check(c.requests == 1 && [m valueForKey:@"track"] == anchor &&
        [[m valueForKey:@"trackGeneration"] unsignedIntegerValue] == generation &&
        [[m valueForKey:@"fetching"] boolValue] && ![m.snapshot[@"line"] length],
        "same nonempty ID keeps one pending lookup and fixed anchor, never fabricates a line");
    pending([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]synthetic-pending" duration:261]); Pump();
    Check(![m.snapshot[@"line"] length], "pending result still needs fresh sandwich");
    Kick(m); DurationSong(261.2245, 261.1316);
    dispatch_sync([m valueForKey:@"bridgeQueue"], ^{});
    NSDictionary *delivered = MSBridgeRead(@"fixture-A", @"music-state.json", 16384);
    Check([delivered[@"line"] isEqual:@"synthetic-pending"] &&
        [delivered[@"playing"] boolValue] && c.requests == 1,
        "production monitor to snapshot to bridge readback delivers only freshly revalidated synthetic line");
    Stop(m);
    for (NSString *field in @[@"Title", @"Artist", @"Duration", @"UniqueIdentifier"]) {
        m = NewMonitor(&c); DurationSong(261.,261.);
        pending = [c.completion copy];
        NSMutableDictionary *changed = DurationInfo(261.2,@"duration-id");
        changed[[@"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field]] =
            [field isEqual:@"Duration"] ? (id)@262.01 : @"Other";
        Kick(m); GiveInfo(changed, NO);
        Check([m valueForKey:@"track"] == nil && ![m.snapshot[@"line"] length],
            "pending continuity cannot override title artist duration or ID conflict");
        pending([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late" duration:261]); Pump();
        Check([m valueForKey:@"timeline"] == nil, "cancelled pending result remains generation fenced");
        Stop(m);
    }
}
static void TestDurationContinuity(void) {
    FakeClient *c; MiniSightMusicMonitor *m = ReadyDuration(&c);
    MiniSightLyricsTrack *anchor = [m valueForKey:@"track"];
    MiniSightLyricsTimeline *timeline = [m valueForKey:@"timeline"];
    NSUInteger generation = [[m valueForKey:@"trackGeneration"] unsignedIntegerValue];
    for (int i=0; i<4; ++i) {
        Kick(m); DurationSong(i % 2 ? 261.2245 : 261.1316, i % 2 ? 261.1316 : 261.2245);
        Check([m valueForKey:@"track"] == anchor && anchor.duration == 261. &&
            [m valueForKey:@"timeline"] == timeline && c.requests == 1 &&
            [[m valueForKey:@"trackGeneration"] unsignedIntegerValue] == generation,
            "continuous fractional samples keep same timeline, original anchor, generation and GET count");
    }
    Kick(m); DurationSong(261., 262.);
    Check([m valueForKey:@"timeline"] == timeline && [m valueForKey:@"track"] == anchor && c.requests == 1,
        "inclusive one-second anchor boundary survives");
    Kick(m); GiveInfo(DurationInfo(262.000001, @"duration-id"), NO);
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length],
        "one second plus epsilon rejected on FIRST read"); Stop(m);

    m = ReadyDuration(&c); timeline = [m valueForKey:@"timeline"];
    Kick(m); DurationSong(261.8, 261.8);
    Check([m valueForKey:@"timeline"] == timeline && ((MiniSightLyricsTrack *)[m valueForKey:@"track"]).duration == 261.,
        "first +0.8 does not move anchor");
    Kick(m); GiveInfo(DurationInfo(262.6, @"duration-id"), NO);
    Check([m valueForKey:@"timeline"] == nil, "second +0.8 cannot accumulate drift"); Stop(m);

    for (NSString *field in @[@"Title", @"Artist", @"UniqueIdentifier"]) {
        m = ReadyDuration(&c);
        NSMutableDictionary *changed = DurationInfo(261.2245, @"duration-id");
        changed[[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field]] = @"Different";
        Kick(m); GiveInfo(changed, NO);
        Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length],
            "epsilon never overrides title/artist/known identifier conflict"); Stop(m);
    }
    m = ReadyDuration(&c); fixturePlayer = @"com.tencent.QQMusic"; Kick(m);
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length],
        "source switch revokes before B first read"); Stop(m);

    m = ReadyDuration(&c); timeline = [m valueForKey:@"timeline"];
    Kick(m); GiveInfo(DurationInfo(261.1316, @"duration-id"), NO); GiveState(YES);
    NSMutableDictionary *otherID = DurationInfo(261.2245, @"different-id"); GiveInfo(otherID, NO);
    Check([m valueForKey:@"timeline"] == nil, "sandwich ID conflict rejected even with bounded duration"); Stop(m);

    m = ReadyDuration(&c); timeline = [m valueForKey:@"timeline"];
    Kick(m); NSMutableDictionary *firstProgress = DurationInfo(261.1316, @"duration-id");
    firstProgress[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] = @2;
    firstProgress[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"] = @0.5;
    GiveInfo(firstProgress, NO); GiveState(YES);
    NSMutableDictionary *lastMissing = DurationInfo(261.2245, @"duration-id");
    [lastMissing removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoElapsedTime"];
    GiveInfo(lastMissing, NO);
    Check([[m valueForKey:@"elapsed"] doubleValue] == 2. && [[m valueForKey:@"rate"] doubleValue] == .5 &&
        [m valueForKey:@"timeline"] == timeline && c.requests == 1, "fractional double read preserves progress as GROUP");
    NSMutableDictionary *beyondAnchor = DurationInfo(261.8, @"duration-id");
    beyondAnchor[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] = @261.5;
    [m applyInfo:beyondAnchor playing:YES player:@"com.apple.Music"];
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length],
        "epsilon cannot extend original timeline progress boundary"); Stop(m);

    m = ReadyDuration(&c); timeline = [m valueForKey:@"timeline"];
    fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil;
    fixturePIDController = [PIDSameBundle new]; MSMusicPID = GetPID;
    Kick(m); GivePID(123); DurationSong(261.1316, 261.2245); GivePID(123);
    Check([m valueForKey:@"timeline"] == timeline && [[m valueForKey:@"verifiedPID"] intValue] == 123,
        "fresh two-PID fractional sandwich retains anchor");
    fixturePlayer = @"com.apple.Music"; Kick(m); DurationSong(261.2245, 261.1316);
    Check([[m valueForKey:@"verifiedPID"] intValue] == 123 && [m valueForKey:@"timeline"] == timeline,
        "fractional direct sample cannot erase positive PID fence");
    fixturePlayer = nil; Kick(m); GivePID(456); DurationSong(261.2245, 261.2245); GivePID(456);
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length],
        "new PID instance rejects fractional same-song candidate");
    Stop(m); MSMusicPID = NULL; fixturePIDController = nil; fixturePIDBundle = @"com.netease.cloudmusic";

    m = ReadyDuration(&c); timeline = [m valueForKey:@"timeline"];
    Kick(m); GiveInfo(DurationInfo(261.1316, @"duration-id"), NO); GiveState(NO);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue], "fractional pause immediately hidden");
    GiveInfo(DurationInfo(261.2245, @"duration-id"), NO);
    fixtureTime += 1.; Kick(m); DurationSong(261.2245, 261.1316);
    Check([m valueForKey:@"timeline"] == timeline && c.requests == 1 && [m.snapshot[@"line"] length],
        "fractional pause/resume requires completed fresh sandwich, no second GET");
    [m handleMediaChange]; double deadline = [[m valueForKey:@"candidateUntil"] doubleValue];
    NSMutableDictionary *partialDuration = DurationInfo(261.2245, @"duration-id");
    [partialDuration removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoArtist"];
    fixtureTime += .5; Kick(m); GiveInfo(partialDuration, NO); GiveState(YES); GiveInfo(partialDuration, NO);
    Check([[m valueForKey:@"candidateUntil"] doubleValue] == deadline && ![m.snapshot[@"line"] length],
        "fractional partial cannot consume/renew absolute hidden deadline");
    fixtureTime = deadline + .01; [m setValue:@(fixtureTime+10.) forKey:@"pollAt"]; [m tick];
    Check([m valueForKey:@"timeline"] == nil && [m valueForKey:@"track"] == nil,
        "fractional partial candidate destroyed after original three seconds"); Stop(m);

    m = NewMonitor(&c); DurationSong(261., 261.); c.completion(nil); Pump();
    Kick(m); DurationSong(261.1316, 261.2245);
    Check(c.requests == 2 && ((MiniSightLyricsTrack *)[m valueForKey:@"track"]).duration == 261.2245,
        "without successful timeline, fractional retry retains exact track key");
    c.completion(nil); Pump(); Kick(m); DurationSong(261.2245, 261.2245);
    Check(c.requests == 2, "same exact failed signature still observes 60-second cooldown"); Stop(m);
}
static void TestMusicHostLease(void) {
    FakeClient *c; MiniSightMusicMonitor *m = NewMonitor(&c);
    Song(@"Lease", @"lease-id");
    NSUInteger token=[m.snapshot[@"rhythmGeneration"] unsignedIntegerValue];
    Check(token == 1 && [m.snapshot[@"playing"] boolValue], "initial active music lease starts at one");
    Check(CFGetTypeID((__bridge CFTypeRef)m.snapshot[@"progressAvailable"]) == CFBooleanGetTypeID() &&
        [m.snapshot[@"progressAvailable"] boolValue] && [m.snapshot[@"motionRate"] doubleValue] == 1., "fresh position flag is a real JSON BOOL and finite normal rate");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]lease-line" duration:120]); Pump();
    Kick(m); Song(@"Lease", @"lease-id");
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token && [m.snapshot[@"line"] length], "timeline callback and lyric generation are independent of music lease");
    for (NSUInteger i=0;i<100;++i) {
        [m setValue:@([[m valueForKey:@"trackGeneration"] unsignedIntegerValue]+1) forKey:@"trackGeneration"];
        [m publishLine:nil playing:YES force:YES];
        Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token && ![m.snapshot[@"line"] length], "line:nil and one hundred lyric generations never restart motion token");
    }
    [m setValue:@(fixtureTime-6.01) forKey:@"validAt"]; [m publishLine:nil playing:YES force:YES];
    Check(![m.snapshot[@"progressAvailable"] boolValue] && [m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token, "expired position evidence is false without restarting music lease");
    [m setValue:@(fixtureTime) forKey:@"validAt"]; [m setValue:@YES forKey:@"awaitingFreshInfo"];
    [m publishLine:nil playing:YES force:YES];
    Check(![m.snapshot[@"progressAvailable"] boolValue], "awaiting fresh identity cannot manufacture measured position");
    [m setValue:@NO forKey:@"awaitingFreshInfo"];
    [m setValue:@NO forKey:@"progressAvailable"]; [m publishLine:nil playing:YES force:YES];
    Check(![m.snapshot[@"progressAvailable"] boolValue] && [m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token, "missing position evidence does not close enabled music lease");
    [m beginPause];
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == 0 && [[m valueForKey:@"rhythmGeneration"] unsignedIntegerValue] == token &&
        ![m.snapshot[@"progressAvailable"] boolValue], "pause closes snapshot token and evidence but retains internal counter");
    Kick(m); Song(@"Lease", @"lease-id");
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token+1, "fresh resumed sandwich advances music lease once");
    fixturePlayer=@"com.tencent.QQMusic"; Kick(m);
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == 0 && ![m.snapshot[@"progressAvailable"] boolValue], "source switch closes old music input before callback");
    Song(@"Lease", @"lease-id");
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == token+2, "verified new source advances music lease");
    [m applyInfo:@{} playing:NO player:fixturePlayer];
    Check([m.snapshot[@"rhythmGeneration"] unsignedIntegerValue] == 0 && ![m.snapshot[@"progressAvailable"] boolValue], "confirmed stop clears motion token and fresh position flag");
    Stop(m);
}

int main(void) { @autoreleasepool {
    disk = [NSMutableDictionary dictionary]; infos = [NSMutableArray array]; states = [NSMutableArray array];
    pids = [NSMutableArray array]; MSMusicTestNow = FixtureNow;
    MSMusicInfo = GetInfo; MSMusicIsPlaying = GetState;
    TestMusicHostLease();
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
    TestPendingDurationContinuity();
    TestDurationContinuity();
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
    partial[@"kMRMediaRemoteNowPlayingInfoUniqueIdentifier"] = @"2";
    NSUInteger beforePartialGeneration = [[m valueForKey:@"trackGeneration"] unsignedIntegerValue];
    [m applyInfo:partial playing:YES player:@"com.apple.Music"];
    Check(![m.snapshot[@"line"] length] && c.requests == 1, "partial metadata clears display without fetching stale track");
    Check([m valueForKey:@"timeline"] != nil &&
        [[m valueForKey:@"trackGeneration"] unsignedIntegerValue] == beforePartialGeneration,
        "same-ID partial hides display but preserves the actual verified timeline");
    NSMutableDictionary *changedID = [partial mutableCopy];
    changedID[@"kMRMediaRemoteNowPlayingInfoUniqueIdentifier"] = @"3";
    [m applyInfo:changedID playing:YES player:@"com.apple.Music"];
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length], "partial new identifier invalidates old lyrics");
    Stop(m);
    m = NewMonitor(&c);
    GiveInfo(partial, NO); GiveState(YES); GiveInfo(Info(@"B", @"2"), NO);
    Check(c.requests == 0 && ![m.snapshot[@"line"] length], "partial conflicting title/identifier rejected");
    Stop(m);
    m = NewMonitor(&c);
    NSMutableDictionary *drift = Info(@"A", @"1");
    drift[@"kMRMediaRemoteNowPlayingInfoDuration"] = @121.000001;
    GiveInfo(Info(@"A", @"1"), NO); GiveState(YES); GiveInfo(drift, NO);
    Check(c.requests == 0, "double read rejects over-one-second continuity, not provider response tolerance");
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
    for (id controller in @[[SBApplicationController new], [PIDNSInteger new]]) {
        fixturePIDController = controller;
        Check([MSMusicPIDPlayer(123, &playerReason) isEqual:@"com.netease.cloudmusic"], "int and NSInteger typed PID sends");
    }
    for (id controller in @[[PIDFloat new], [PIDObject new]]) {
        fixturePIDController = controller;
        Check(!MSMusicPIDPlayer(123, &playerReason) && [playerReason isEqual:@"pid_signature_rejected"], "wrong PID ABI never invoked");
    }
    fixturePIDController = [PIDNoSignature new];
    Check(!MSMusicPIDPlayer(123, &playerReason) && [playerReason isEqual:@"pid_signature_missing"], "missing PID signature");
    fixturePIDController = [NSObject new];
    Check(!MSMusicPIDPlayer(123, &playerReason) && [playerReason isEqual:@"pid_method_unavailable"], "missing PID selector");
    fixturePIDController = nil; fixtureControllerMissing = YES;
    Check(!MSMusicPIDPlayer(123, &playerReason) && [playerReason isEqual:@"pid_controller_unavailable"], "missing PID controller");
    fixtureControllerMissing = NO;
    Check(!MSMusicPIDPlayer(0, &playerReason) && [playerReason isEqual:@"player_pid_nonpositive"], "nonpositive PID");
    Check(!MSMusicPIDPlayer(456, &playerReason) && [playerReason isEqual:@"pid_mapping_missing"], "nil PID application mapping");
    for (int width=0; width<2; ++width) for (int changed=0; changed<2; changed++) {
        fixturePIDController = width ? [PIDNSInteger new] : nil;
        [infos removeAllObjects]; [pids removeAllObjects];
        m = [MiniSightMusicMonitor new]; c = [FakeClient new]; [m setValue:c forKey:@"client"];
        m.presentationHandler = ^{return @{@"allowed": @YES};}; fixturePlayer=nil;
        MSMusicPID = GetPID; pidCalls=0;
        [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"];
        GivePID(123); Song(@"Fixture", @"123"); GivePID(changed ? 456 : 123);
        Check(pidCalls == 2 && c.requests == (changed ? 0 : 1), "fresh PID sandwich, no stale track on PID switch");
        if (!changed) {
            Check([m.snapshot[@"source"] isEqual:@"com.netease.cloudmusic"], "exact PID source published");
            [m handleMediaChange];
            Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length], "PID candidate cannot display unverified state");
            Kick(m); GivePID(123); Song(@"Fixture", @"123"); GivePID(123);
            Check(c.requests == 1 && [m.snapshot[@"playing"] boolValue], "stable reverified PID retains pending lookup");
            MiniSightLyricsCompletion savedLookup = [c.completion copy];
            Check(savedLookup != nil, "pending lookup remains owned after stable PID revalidation");
            savedLookup([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]pending-current" duration:120]); Pump();
            Kick(m); GivePID(123); Song(@"Fixture", @"123"); GivePID(123);
            Check([m.snapshot[@"line"] isEqual:@"pending-current"] && c.requests == 1,
                  "PID candidate actually receives its original lookup, not only a request counter");
            Kick(m); GivePID(123); Song(@"Fixture", @"123"); GivePID(456);
            Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue] &&
                  ![m.snapshot[@"source"] length], "changed ending PID clears existing lyric/source state");
            savedLookup([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-old" duration:120]); Pump();
            Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue],
                  "late old lookup cannot revive lyrics after PID rejection");
        }
        Stop(m); MSMusicPID=NULL;
    }
    fixturePIDController = nil;
    // Foreground direct -> background direct nil: retain only an invisible
    // candidate, then recover the exact same player using current PID twice.
    m = NewMonitor(&c); Song(@"A", @"1");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]current" duration:120]); Pump();
    Kick(m); Song(@"A", @"1");
    fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil; MSMusicPID = GetPID;
    MiniSightLyricsTimeline *beforeBackground = [m valueForKey:@"timeline"];
    Check(beforeBackground != nil, "foreground current lyrics exist before first background notification");
    [m handleMediaChange];
    Check([m valueForKey:@"timeline"] == beforeBackground, "first direct-loss notification retains only a hidden candidate");
    Kick(m);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"source"] length], "direct loss cannot publish cached player");
    GivePID(123); Song(@"A", @"1"); GivePID(123);
    Check([m.snapshot[@"line"] isEqual:@"current"] && c.requests == 1, "background current PID restores verified same-track lyrics");
    [m handleMediaChange]; Kick(m); GivePID(123);
    GiveInfo(Info(@"A", @"1"), NO); GiveState(NO); GiveInfo(Info(@"A", @"1"), NO); GivePID(123);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue], "background pause clears lyrics");
    [m handleMediaChange]; Kick(m); GivePID(123); GiveInfo(@{}, NO); GiveState(NO); GiveInfo(@{}, NO); GivePID(123);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue], "background stop clears lyrics");
    // An explicit other direct source mid-sandwich must reject the old PID.
    Kick(m); GivePID(123); fixturePlayer = @"com.tencent.QQMusic"; GiveInfo(Info(@"A", @"1"), NO);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue], "switch App rejects old PID sample");
    Stop(m); MSMusicPID = NULL; fixturePIDBundle = @"com.netease.cloudmusic";
    fixturePlayer = @"com.netease.cloudmusic.extra"; MSMusicPID = GetPID; pidCalls = 0;
    m = [MiniSightMusicMonitor new]; m.presentationHandler = ^{return @{@"allowed": @YES};};
    [m configureAllowed:YES lyrics:YES motion:YES container:@"fixture-A"]; Pump();
    Check(pidCalls == 0 && ![m.snapshot[@"playing"] boolValue] &&
        [m.snapshot[@"diagnostics"][@"playerDetail"] isEqual:@"unsupported_player"], "explicitly unsupported never falls back to PID");
    Stop(m); MSMusicPID=NULL;
    // Known metadata hints are not application/play-state invalidations.
    // Observe EVERY delivered snapshot, not only the final state.
    m = NewMonitor(&c); Song(@"Hints", @"h");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]stable" duration:120]); Pump();
    Kick(m); Song(@"Hints", @"h");
    __block NSUInteger falseSnapshots = 0, emptySnapshots = 0;
    m.updateHandler = ^(NSDictionary *s) { if (![s[@"playing"] boolValue]) ++falseSnapshots; if (![s[@"line"] length]) ++emptySnapshots; };
    for (int round=0; round<5; ++round) {
        fixtureTime += 0.5;
        for (int hint=0; hint<20; ++hint) [m mediaChanged:[NSNotification notificationWithName:MSMusicKey("kMRMediaRemoteNowPlayingInfoDidChangeNotification") object:nil]];
        Pump();
        Check(infos.count == 1 && [m.snapshot[@"line"] isEqual:@"stable"], "recent verified same-direct metadata hints do not clear");
        GiveInfo(Info(@"Hints", @"h"), NO);
        [m mediaChanged:[NSNotification notificationWithName:MSMusicKey("kMRMediaRemoteNowPlayingInfoDidChangeNotification") object:nil]]; Pump();
        GiveState(YES); GiveInfo(Info(@"Hints", @"h"), NO);
    }
    Check(falseSnapshots == 0 && emptySnapshots == 0 && c.requests == 1, "same-song metadata bursts cannot manufacture false/empty snapshots or cancel sampler");
    fixtureTime += 0.5;
    [m mediaChanged:[NSNotification notificationWithName:MSMusicKey("kMRMediaRemoteNowPlayingInfoDidChangeNotification") object:nil]]; Pump();
    fixtureTime += 1.01; [m tick];
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] && infos.count == 1, "metadata evidence lease expires without replacing native slot");
    GiveInfo(Info(@"Hints", @"h"), NO); GiveState(YES); GiveInfo(Info(@"Hints", @"h"), NO);
    Check([m.snapshot[@"line"] isEqual:@"stable"], "expired visible lease recovers only through completed fresh sandwich");
    [m mediaChanged:[NSNotification notificationWithName:MSMusicKey("kMRMediaRemoteNowPlayingInfoDidChangeNotification") object:nil]];
    [m mediaChanged:[NSNotification notificationWithName:MSMusicKey("kMRMediaRemoteNowPlayingApplicationIsPlayingDidChangeNotification") object:nil]]; Pump();
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length], "hard play-state note dominates coalesced metadata hints");
    Stop(m);
    m = NewMonitor(&c); Song(@"Switch A", @"same-id");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]A-only" duration:120]); Pump();
    Kick(m); Song(@"Switch A", @"same-id");
    MiniSightLyricsCompletion switchedLookup = [c.completion copy];
    Kick(m); GiveInfo(Info(@"Switch B", @"same-id"), NO);
    Check(![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue], "first conflicting same-App metadata hides old lyrics before state callback");
    GiveState(YES); GiveInfo(Info(@"Switch B", @"same-id"), NO);
    switchedLookup([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-A" duration:120]); Pump();
    Check(c.requests == 2 && ![m.snapshot[@"line"] length], "same identifier does not admit late previous-song lyrics");
    Stop(m);
    // PID0 remains public unknown, while a bounded INVISIBLE candidate can
    // survive for a later fully fresh same-player/same-track PID sandwich.
    m = NewMonitor(&c); Song(@"Candidate", @"c");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]candidate" duration:120]); Pump();
    Kick(m); Song(@"Candidate", @"c");
    MiniSightLyricsTimeline *candidate = [m valueForKey:@"timeline"];
    MiniSightLyricsCompletion preUnknown = [c.completion copy];
    fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil; MSMusicPID = GetPID;
    Kick(m); GivePID(0);
    Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] && ![m.snapshot[@"source"] length] && [m valueForKey:@"timeline"] == candidate, "PID0 is hidden unknown not cached-player success");
    preUnknown([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late" duration:120]); Pump();
    Check([m valueForKey:@"timeline"] == candidate, "pre-unknown late result is generation-rejected");
    Kick(m); GivePID(123); Song(@"Candidate", @"c"); GivePID(123);
    Check([m.snapshot[@"line"] isEqual:@"candidate"] && c.requests == 1, "fresh PID sandwich recovers bounded matching candidate without cooldown refetch");
    Kick(m); GivePID(0);
    fixtureTime += 3.01; [m tick];
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length], "PID0 candidate expiry is absolute and clears old lyrics");
    Stop(m);
    if (pids.count) GivePID(123);
    MSMusicPID = NULL;
    m = NewMonitor(&c); fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil;
    fixturePIDController = [PIDSameBundle new]; MSMusicPID = GetPID;
    // Consume the direct request started by NewMonitor under the original
    // direct source, then explicitly begin a new, fresh PID sample.
    GiveInfo(Info(@"Instance", @"i"), NO);
    Kick(m); GivePID(123); Song(@"Instance", @"i"); GivePID(123);
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]old-instance" duration:120]); Pump();
    Kick(m); GivePID(123); Song(@"Instance", @"i"); GivePID(123);
    Check([m.snapshot[@"line"] isEqual:@"old-instance"], "first PID instance has confirmed lyrics");
    Kick(m); GivePID(456); Song(@"Instance", @"i"); GivePID(456);
    Check(![m.snapshot[@"line"] length] && [m valueForKey:@"timeline"] == nil,
        "two matching NEW PIDs for same App cannot reuse previous process timeline");
    Stop(m); fixturePIDController = nil; MSMusicPID = NULL; fixturePIDBundle = @"com.netease.cloudmusic";
    // B1/D1: partial (playing OR paused) cannot consume/renew the PID0 deadline.
    for (int partialPlaying = 0; partialPlaying < 2; ++partialPlaying) {
        m = NewMonitor(&c); Song(@"Absolute", @"abs");
        c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]absolute-old" duration:120]); Pump();
        Kick(m); Song(@"Absolute", @"abs");
        fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil; MSMusicPID = GetPID;
        Kick(m); GivePID(0);
        double absoluteUntil = [[m valueForKey:@"candidateUntil"] doubleValue];
        Check(absoluteUntil == fixtureTime + 3., "PID0 owns one absolute three-second deadline");
        fixtureTime += 1.;
        NSMutableDictionary *incomplete = Info(@"Absolute", @"abs");
        [incomplete removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoArtist"];
        Kick(m); GivePID(123); GiveInfo(incomplete, NO); GiveState(partialPlaying);
        GiveInfo(incomplete, NO); GivePID(123);
        Check([[m valueForKey:@"candidateUntil"] doubleValue] == absoluteUntil &&
            [m valueForKey:@"timeline"] != nil && ![m.snapshot[@"line"] length],
            "partial sandwich neither consumes nor extends original candidate deadline");
        fixtureTime = absoluteUntil + .01;
        [m setValue:@(fixtureTime + 10.) forKey:@"pollAt"]; [m tick];
        Check([m valueForKey:@"timeline"] == nil && [m valueForKey:@"track"] == nil &&
            [[m valueForKey:@"verifiedPID"] intValue] == 0,
            "post-deadline tick destroys partial candidate and PID fence");
        Kick(m); GivePID(123); Song(@"Absolute", @"abs"); GivePID(123);
        Check(c.requests == 1 && [m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length],
            "complete same song after absolute expiry cannot revive old lyrics or bypass 60s request fence");
        Stop(m); MSMusicPID = NULL;
    }
    // B2: a direct sample cannot erase the previous positive process fence.
    m = NewMonitor(&c); fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil;
    fixturePIDController = [PIDSameBundle new]; MSMusicPID = GetPID;
    GiveInfo(Info(@"Direct fence", @"df"), NO);
    Kick(m); GivePID(123); Song(@"Direct fence", @"df"); GivePID(123);
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]process-123" duration:120]); Pump();
    Kick(m); GivePID(123); Song(@"Direct fence", @"df"); GivePID(123);
    MiniSightLyricsTimeline *process123 = [m valueForKey:@"timeline"];
    MiniSightLyricsCompletion processLookup = [c.completion copy];
    fixturePlayer = @"com.apple.Music"; Kick(m); Song(@"Direct fence", @"df");
    Check([[m valueForKey:@"verifiedPID"] intValue] == 123 && [m valueForKey:@"timeline"] == process123,
        "direct same metadata retains positive PID rejection fence");
    fixturePlayer = nil; Kick(m); GivePID(456); Song(@"Direct fence", @"df"); GivePID(456);
    processLookup([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-123" duration:120]); Pump();
    Check([m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length] && c.requests == 1,
        "PID123 to direct to PID456 same App/song rejects old process timeline without cooldown refetch");
    Stop(m); fixturePIDController = nil; MSMusicPID = NULL;
    fixturePIDBundle = @"com.netease.cloudmusic";
    // B3: no notification; B has the same cache key and its first callback stalls.
    m = NewMonitor(&c); Song(@"Same source key", @"same");
    c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]A-only-source" duration:120]); Pump();
    Kick(m); Song(@"Same source key", @"same");
    MiniSightLyricsCompletion sourceLookup = [c.completion copy];
    fixturePlayer = @"com.tencent.QQMusic"; Kick(m);
    Check(infos.count == 1 && [m valueForKey:@"timeline"] == nil &&
        ![m.snapshot[@"line"] length] && ![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"source"] length],
        "known direct A to B revokes old timeline and source before first B metadata callback");
    fixtureTime += .25; [m tick];
    sourceLookup([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-A-source" duration:120]); Pump();
    Check(infos.count == 1 && [m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length] &&
        ![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"source"] length],
        "delayed same-cache-key B read owns one slot and old lookup cannot republish A");
    Song(@"Same source key", @"same");
    Check([m.snapshot[@"source"] isEqual:@"com.tencent.QQMusic"] && ![m.snapshot[@"line"] length] && c.requests == 1,
        "new source belongs only to completed B sample and does not bypass same-key cooldown");
    Stop(m);
    // D1: direct AND fresh two-PID pause/resume keep a successful same-song timeline.
    for (int usePID = 0; usePID < 2; ++usePID) {
        m = NewMonitor(&c);
        if (usePID) {
            fixturePIDBundle = @"com.apple.Music"; fixturePlayer = nil; MSMusicPID = GetPID;
            GiveInfo(Info(@"Pause resume", @"pr"), NO); Kick(m); GivePID(123);
        }
        Song(@"Pause resume", @"pr"); if (usePID) GivePID(123);
        c.completion([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]resume-current" duration:120]); Pump();
        Kick(m); if (usePID) GivePID(123); Song(@"Pause resume", @"pr"); if (usePID) GivePID(123);
        MiniSightLyricsTimeline *pausedTimeline = [m valueForKey:@"timeline"];
        MiniSightLyricsCompletion beforePause = [c.completion copy];
        NSUInteger pauseGeneration = [[m valueForKey:@"trackGeneration"] unsignedIntegerValue];
        Kick(m); if (usePID) GivePID(123);
        GiveInfo(Info(@"Pause resume", @"pr"), NO); GiveState(NO);
        Check(![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] &&
            [[m valueForKey:@"trackGeneration"] unsignedIntegerValue] > pauseGeneration &&
            ![[m valueForKey:@"fetching"] boolValue], "pause callback immediately hides and generation-fences lookup");
        GiveInfo(Info(@"Pause resume", @"pr"), NO); if (usePID) GivePID(123);
        beforePause([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-before-pause" duration:120]); Pump();
        Check(pausedTimeline != nil && [m valueForKey:@"timeline"] == pausedTimeline &&
            [[m valueForKey:@"candidateUntil"] doubleValue] == 0. && ![m.snapshot[@"line"] length],
            "only complete same track/source/PID pause retains mature successful timeline without showing it");
        fixtureTime += 1.;
        Kick(m); if (usePID) GivePID(123);
        GiveInfo(Info(@"Pause resume", @"pr"), NO); GiveState(YES);
        Check(![m.snapshot[@"line"] length], "resume still waits for final metadata and PID");
        GiveInfo(Info(@"Pause resume", @"pr"), NO); if (usePID) GivePID(123);
        Check([m.snapshot[@"line"] isEqual:@"resume-current"] && [m valueForKey:@"timeline"] == pausedTimeline &&
            c.requests == 1, "one-second pause resumes original timeline with no new lyric request");
        Kick(m); if (usePID) GivePID(123); GiveInfo(@{}, NO); GiveState(NO); GiveInfo(@{}, NO);
        if (usePID) GivePID(123);
        beforePause([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]late-after-stop" duration:120]); Pump();
        Check([m valueForKey:@"timeline"] == nil && [[m valueForKey:@"verifiedPID"] intValue] == 0 &&
            ![m.snapshot[@"playing"] boolValue] && ![m.snapshot[@"line"] length] && c.requests == 1,
            "empty-metadata stop destroys timeline and old callback cannot revive it");
        Stop(m); MSMusicPID = NULL;
    }
    fixturePIDBundle = @"com.netease.cloudmusic";
    m = NewMonitor(&c); Song(@"Pending pause", @"pp");
    MiniSightLyricsCompletion unfinishedPause = [c.completion copy];
    NSUInteger cancelsBeforePause = c.cancels;
    Kick(m); GiveInfo(Info(@"Pending pause", @"pp"), NO); GiveState(NO); GiveInfo(Info(@"Pending pause", @"pp"), NO);
    unfinishedPause([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]cancelled-pause" duration:120]); Pump();
    Check(c.cancels > cancelsBeforePause && ![[m valueForKey:@"fetching"] boolValue] &&
        [m valueForKey:@"timeline"] == nil && ![m.snapshot[@"line"] length] && c.requests == 1,
        "pause cancels unfinished lyric request and generation-rejects its late completion");
    fixtureTime += 1.; Kick(m); Song(@"Pending pause", @"pp");
    Check(c.requests == 1 && [m valueForKey:@"timeline"] == nil, "pause cancellation cannot reopen 60s lyric cooldown");
    Stop(m);
    // Same-track partial progress keeps the first read's elapsed/timestamp/rate
    // together; explicit invalid progress must never be rescued.
    NSMutableDictionary *firstProgress = Info(@"Progress", @"p");
    firstProgress[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] = @30;
    firstProgress[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"] = @0.5;
    NSMutableDictionary *lastProgress = Info(@"Progress", @"p");
    [lastProgress removeObjectForKey:@"kMRMediaRemoteNowPlayingInfoElapsedTime"];
    NSDictionary *resolvedProgress = MSMusicResolvedInfo(firstProgress, lastProgress, @"com.apple.Music");
    Check([resolvedProgress[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] isEqual:@30] &&
        [resolvedProgress[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"] isEqual:@0.5] &&
        [resolvedProgress[@"kMRMediaRemoteNowPlayingInfoTimestamp"] isEqual:firstProgress[@"kMRMediaRemoteNowPlayingInfoTimestamp"]], "same-track progress group is atomic");
    lastProgress[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] = @(-1);
    Check([MSMusicResolvedInfo(firstProgress,lastProgress,@"com.apple.Music")[@"kMRMediaRemoteNowPlayingInfoElapsedTime"] isEqual:@(-1)], "explicit invalid progress is not rescued");
    Check(maxPending <= 1, "at most one pending native API callback including PID");
    puts("NATIVE PASS: ABI, five players, CF copy, main callbacks, storm, timeout/reopen, sandwich, late lyrics, cooldown, pause/stale, bridge mailbox/privacy, recovery/switches, unknown gate, no-LRC motion, real JSON booleans");
    return 0;
} }
