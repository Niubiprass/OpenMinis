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
- (id)nowPlayingApplication { return self; }
- (NSString *)bundleIdentifier { return fixturePlayer; }
@end
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
- (void)fetchTrack:(MiniSightLyricsTrack *)track completion:(MiniSightLyricsCompletion)completion {
    ++_requests; self.completion = completion;
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
    for (NSString *p in @[@"com.netease.cloudmusic", @"com.tencent.QQMusic", @"com.kugou.kugou1002", @"com.yeelion.kwplayer", @"com.apple.Music"]) {
        fixturePlayer = p; Check([MSMusicPlayer() isEqual:p], "five allowlisted players");
    }
    fixturePlayer = @"fixture.unsupported"; Check(MSMusicPlayer() == nil, "deny unsupported player");
    Check([MiniSightMusicMonitor deviceIsUnlocked], "explicit unlocked lock-state ABI");
    fixtureLocked = YES; Check(![MiniSightMusicMonitor deviceIsUnlocked], "lock is not the same as a lit screen");
    fixtureLocked = NO;
    FakeClient *c; MiniSightMusicMonitor *m = NewMonitor(&c);
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
    puts("NATIVE PASS: ABI, five players, CF copy, main callbacks, storm, timeout/reopen, sandwich, late lyrics, cooldown, pause/stale, bridge mailbox/privacy");
    return 0;
} }
