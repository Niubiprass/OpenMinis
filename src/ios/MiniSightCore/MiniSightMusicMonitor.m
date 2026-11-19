#import "MiniSightMusicMonitor.h"
#import "MiniSightLyrics.h"
#import "MiniSightBridgeIO.h"
#import "MiniSightLog.h"
#import <CoreFoundation/CoreFoundation.h>
#import <objc/message.h>
#import <dlfcn.h>
#import <math.h>
#import <mach-o/loader.h>
#import <mach/vm_prot.h>
#import <string.h>
#import <stdbool.h>
#if __has_feature(ptrauth_calls)
#import <ptrauth.h>
#endif

// dlsym has no type information: distinguish code from a pointer-sized data
// export BEFORE calling/dereferencing it. This is not proof of private API ABI.
static void *MSMusicSymbol(void *handle, const char *name, BOOL function) {
    void *symbol = handle ? dlsym(handle, name) : NULL;
    const void *address = symbol;
#if __has_feature(ptrauth_calls)
    address = ptrauth_strip(address, ptrauth_key_function_pointer);
#endif
    Dl_info image;
    if (!address || !dladdr(address, &image)) return NULL;
    const struct mach_header_64 *header = image.dli_fbase;
    if (!header || header->magic != MH_MAGIC_64) return NULL;
    const uint8_t *first = (const uint8_t *)(header + 1), *end = first + header->sizeofcmds;
    intptr_t slide = 0; BOOL found = NO;
    for (const uint8_t *p = first; p + sizeof(struct load_command) <= end;) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmdsize < sizeof(*lc) || lc->cmdsize > (size_t)(end - p)) return NULL;
        if (lc->cmd == LC_SEGMENT_64 && lc->cmdsize >= sizeof(struct segment_command_64)) {
            const struct segment_command_64 *seg = (const void *)p;
            // dyld rewrites fileoff to a cache-wide offset for shared-cache
            // images. Like MachOLoaded::getSlide(), anchor to __TEXT.vmaddr,
            // not an on-disk file offset. Keep the section/protection checks.
            if (strncmp(seg->segname, SEG_TEXT, sizeof(seg->segname)) == 0) {
                if (found) return NULL;
                slide = (intptr_t)header - (intptr_t)seg->vmaddr; found = YES;
            }
        }
        p += lc->cmdsize;
    }
    if (!found) return NULL;
    for (const uint8_t *p = first; p + sizeof(struct load_command) <= end;) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmd == LC_SEGMENT_64 && lc->cmdsize >= sizeof(struct segment_command_64)) {
            const struct segment_command_64 *seg = (const void *)p;
            if (seg->nsects > (lc->cmdsize - sizeof(*seg)) / sizeof(struct section_64)) return NULL;
            const struct section_64 *sections = (const void *)(seg + 1);
            for (uint32_t i = 0; i < seg->nsects; ++i) {
                uintptr_t start = (uintptr_t)(sections[i].addr + slide), value = (uintptr_t)address;
                size_t needed = function ? 1 : sizeof(CFStringRef);
                if (value < start || sections[i].size < needed || value - start > sections[i].size - needed) continue;
                BOOL code = (sections[i].flags & (S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS)) != 0;
                if (function ? (code && (seg->initprot & VM_PROT_EXECUTE)) :
                    (!code && (seg->initprot & VM_PROT_READ) && !(seg->initprot & VM_PROT_EXECUTE))) return symbol;
                return NULL;
            }
        }
        p += lc->cmdsize;
    }
    return NULL;
}
static NSTimeInterval MSMusicNow(void) { return NSProcessInfo.processInfo.systemUptime; }

// Signatures from the MediaRemote header; symbols remain optional on each OS.
typedef void (*MSMusicInfoFn)(dispatch_queue_t, void (^)(CFDictionaryRef));
typedef void (*MSMusicPlayingFn)(dispatch_queue_t, void (^)(Boolean));
static MSMusicInfoFn MSMusicInfo;
static MSMusicPlayingFn MSMusicIsPlaying;
static void *MSMusicHandle;
static NSString *MSMusicKey(const char *symbol) {
#ifdef MINISIGHT_MUSIC_MONITOR_TEST
    return [NSString stringWithUTF8String:symbol]; // Synthetic keys, never load MediaRemote in tests.
#else
    CFStringRef *address = (CFStringRef *)MSMusicSymbol(MSMusicHandle, symbol, NO);
    CFStringRef value = address ? *address : NULL;
    return value && CFGetTypeID(value) == CFStringGetTypeID() ? [(__bridge NSString *)value copy] : nil;
#endif
}
static NSString *MSMusicKey(const char *symbol);
static double MSMusicNumber(id value, double fallback);
static id MSMusicObject(id receiver, NSString *selector) {
    SEL sel = NSSelectorFromString(selector);
    if (!receiver || ![receiver respondsToSelector:sel]) return nil;
    NSMethodSignature *signature = [receiver methodSignatureForSelector:sel];
    const char *type = signature.methodReturnType;
    if (!signature || signature.numberOfArguments != 2 || !type || (type[0] != '@' && type[0] != '#')) return nil;
    return ((id (*)(id, SEL))objc_msgSend)(receiver, sel);
}
static NSString *MSMusicPlayer(void) {
    // This is a borrowed system object, not an App-injected lyric hook.
    @try {
        id media = MSMusicObject(NSClassFromString(@"SBMediaController"), @"sharedInstance");
        id app = MSMusicObject(media, @"nowPlayingApplication");
        id bundle = MSMusicObject(app, @"bundleIdentifier");
        if (![bundle isKindOfClass:NSString.class]) return nil;
        NSSet *players = [NSSet setWithArray:@[@"com.netease.cloudmusic", @"com.tencent.QQMusic",
            @"com.kugou.kugou1002", @"com.yeelion.kwplayer", @"com.apple.Music"]];
        return [players containsObject:bundle] ? bundle : nil;
    } @catch (NSException *exception) { (void)exception; return nil; }
}
static double MSMusicNumber(id value, double fallback) {
    if (![value isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID()) return fallback;
    double v = [value doubleValue]; return isfinite(v) ? v : fallback;
}

static id MSMusicField(NSDictionary *info, const char *symbol);
static NSString *MSMusicIdentifier(NSDictionary *info) {
    id value = MSMusicField(info, "kMRMediaRemoteNowPlayingInfoUniqueIdentifier");
    if ([value isKindOfClass:NSNumber.class]) value = [value stringValue];
    return [value isKindOfClass:NSString.class] && [value length] <= 256 ? value : @"";
}
static MiniSightLyricsTrack *MSMusicTrack(NSDictionary *info) {
    return [[MiniSightLyricsTrack alloc]
        initWithTitle:MSMusicField(info, "kMRMediaRemoteNowPlayingInfoTitle")
        artist:MSMusicField(info, "kMRMediaRemoteNowPlayingInfoArtist")
        duration:MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoDuration"), NAN)];
}
static BOOL MSMusicTracksCompatible(MiniSightLyricsTrack *firstTrack, NSString *firstID,
    MiniSightLyricsTrack *lastTrack, NSString *lastID) {
    if (firstTrack && lastTrack) return [firstTrack.cacheKey isEqualToString:lastTrack.cacheKey];
    return !(firstID.length && lastID.length && ![firstID isEqualToString:lastID]);
}
static BOOL MSMusicTrackIdentityCompatible(NSDictionary *first, NSDictionary *last, NSString *player) {
    if (!player.length) return NO;
    MiniSightLyricsTrack *firstTrack = MSMusicTrack(first), *lastTrack = MSMusicTrack(last);
    if (firstTrack && lastTrack) return [firstTrack.cacheKey isEqualToString:lastTrack.cacheKey];
    for (NSString *field in @[@"Title", @"Artist"]) {
        NSString *key = MSMusicKey([[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
        id a = key ? first[key] : nil, b = key ? last[key] : nil;
        if ([a isKindOfClass:NSString.class] && [b isKindOfClass:NSString.class] &&
            ![[a precomposedStringWithCanonicalMapping] isEqualToString:[b precomposedStringWithCanonicalMapping]]) return NO;
    }
    NSString *durationKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoDuration");
    double a = durationKey ? MSMusicNumber(first[durationKey], NAN) : NAN;
    double b = durationKey ? MSMusicNumber(last[durationKey], NAN) : NAN;
    if (isfinite(a) && isfinite(b) && fabs(a-b) > .001) return NO;
    NSString *firstID = MSMusicIdentifier(first), *lastID = MSMusicIdentifier(last);
    if (firstID.length && lastID.length && ![firstID isEqualToString:lastID]) return NO;
    if ((firstTrack || lastTrack) && !firstID.length && !lastID.length) {
        // No shared title/artist/duration/identifier contradicted the sample;
        // allow this player to populate fields on its next poll.
        return YES;
    }
    return MSMusicTracksCompatible(firstTrack, firstID, lastTrack, lastID);
}
static NSDictionary *MSMusicResolvedInfo(NSDictionary *first, NSDictionary *last, NSString *player) {
    if (![last isKindOfClass:NSDictionary.class] || !MSMusicTrackIdentityCompatible(first ?: @{}, last, player)) return last;
    NSMutableDictionary *resolved = [last mutableCopy];
    for (NSString *field in @[@"Title", @"Artist", @"Duration", @"UniqueIdentifier"]) {
        NSString *key = MSMusicKey([[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
        if (key && !resolved[key] && first[key]) resolved[key] = first[key];
    }
    return [resolved copy];
}
static BOOL MSMusicPartialConflicts(NSDictionary *info, MiniSightLyricsTrack *current, NSString *currentID) {
    if (!current) return NO;
    NSString *identifier = MSMusicIdentifier(info);
    if (identifier.length && currentID.length && ![identifier isEqualToString:currentID]) return YES;
    NSString *titleKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoTitle");
    id title = titleKey ? info[titleKey] : nil;
    if ([title isKindOfClass:NSString.class]) {
        MiniSightLyricsTrack *candidate = [[MiniSightLyricsTrack alloc] initWithTitle:title artist:current.artist duration:current.duration];
        if (!candidate || ![candidate.cacheKey isEqualToString:current.cacheKey]) return YES;
    }
    NSString *artistKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoArtist");
    id artist = artistKey ? info[artistKey] : nil;
    if ([artist isKindOfClass:NSString.class]) {
        MiniSightLyricsTrack *candidate = [[MiniSightLyricsTrack alloc] initWithTitle:current.title artist:artist duration:current.duration];
        if (!candidate || ![candidate.cacheKey isEqualToString:current.cacheKey]) return YES;
    }
    NSString *durationKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoDuration");
    double duration = durationKey ? MSMusicNumber(info[durationKey], NAN) : NAN;
    return isfinite(duration) && fabs(duration-current.duration) > .001;
}
static BOOL MSMusicProgressValid(NSDictionary *info, MiniSightLyricsTrack *track) {
    double elapsed = MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoElapsedTime"), NAN);
    return track && isfinite(elapsed) && elapsed >= 0. && elapsed <= track.duration + .1;
}
static NSTimeInterval MSMusicLastSampleLogAt;
static void MSMusicEvidence(NSString *stage, NSString *result, NSUInteger generation, NSString *reason,
    BOOL valid, BOOL present, BOOL readback, BOOL enabled) {
    MSDiagEvent(@"music", stage, result, @{@"source": @"plugin", @"generation": @(generation),
        @"reason": reason, @"valid": @((BOOL)valid), @"present": @((BOOL)present),
        @"readback": @((BOOL)readback), @"enabled": @((BOOL)enabled)});
}

// Fixed-vocabulary evidence only; never used to admit reads, fetches or rendering.
// This C-only block is also compiled verbatim by the portable regression fixture.
// BEGIN MUSIC DIAGNOSTIC STAGES
typedef struct {
    const char *player, *metadata, *progress, *lyrics;
} MSMusicDiagnosticStages;
static MSMusicDiagnosticStages MSMusicDiagnose(bool active, bool mediaAvailable,
    bool playerIdentified, bool awaitingFreshInfo, bool trackAvailable, bool progressAvailable,
    bool lyricsEnabled, bool playing, bool fetching, bool lyricsAwaitingFreshInfo,
    bool lyricsRequestFinished, bool timelineAvailable, bool lineReady) {
    MSMusicDiagnosticStages s = {"not_applicable", "not_applicable", "not_applicable", "inactive"};
    if (!active) return s;
    if (!mediaAvailable) { s.player = "unavailable"; s.lyrics = "media_api_unavailable"; return s; }
    s.player = playerIdentified ? "selected" : "none";
    s.metadata = !playerIdentified ? "not_applicable" : awaitingFreshInfo ? "awaiting_fresh_info"
        : trackAvailable ? "coherent" : "missing";
    s.progress = !playerIdentified || awaitingFreshInfo || !trackAvailable ? "not_applicable"
        : progressAvailable ? "available" : "missing";
    s.lyrics = !lyricsEnabled ? "disabled"
        : !playerIdentified ? "no_supported_player"
        : awaitingFreshInfo ? "awaiting_fresh_identity"
        : !trackAvailable ? "metadata_missing"
        : !progressAvailable ? "progress_missing"
        : !playing ? "not_playing"
        : fetching ? "fetching"
        : lyricsAwaitingFreshInfo ? "awaiting_fresh_identity"
        : !timelineAvailable && !lyricsRequestFinished ? "awaiting_fetch"
        : !timelineAvailable ? "no_synced_lyrics"
        : !lineReady ? "no_current_line" : "current_line";
    return s;
}
// END MUSIC DIAGNOSTIC STAGES

@interface MiniSightMusicMonitor () {
    NSTimer *_timer;
    MiniSightLyricsClient *_client;
    MiniSightLyricsTimeline *_timeline;
    MiniSightLyricsTrack *_track;
    NSString *_identity, *_identifier, *_source, *_container;
    NSDictionary *_snapshot;
    BOOL _allowed, _lyrics, _motion, _playing, _reading, _eventQueued, _springBoard;
    BOOL _playerIdentified, _progressAvailable, _lyricsRequestFinished;
    NSUInteger _readGeneration, _trackGeneration, _readTicket, _readStage;
    NSTimeInterval _pollAt, _readAt, _elapsed, _stamp, _rate, _validAt, _writeAt;
    BOOL _fetching, _awaitingFreshInfo, _lyricsAwaitingFreshInfo, _readTimedOut;
    NSDictionary *_presentation;
    NSMutableDictionary<NSString *, NSNumber *> *_retryTimes;
    dispatch_queue_t _bridgeQueue;
    NSDictionary *_pendingSnapshot;
    NSString *_pendingContainer, *_writtenContainer;
    NSUInteger _bridgeVersion;
    BOOL _bridgeScheduled, _bridgePending;
}
@end

@implementation MiniSightMusicMonitor
+ (BOOL)deviceIsUnlocked { return [self deviceIsUnlockedWithKnown:NULL]; }
+ (BOOL)deviceIsUnlockedWithKnown:(BOOL *)known {
    if (known) *known = NO;
    NSAssert(NSThread.isMainThread, @"Lock state is main-thread owned");
    @try {
        id manager = MSMusicObject(NSClassFromString(@"SBLockScreenManager"), @"sharedInstance");
        SEL sel = NSSelectorFromString(@"isUILocked");
        if (!manager || ![manager respondsToSelector:sel]) return NO;
        NSMethodSignature *signature = [manager methodSignatureForSelector:sel];
        const char *type = signature.methodReturnType;
        if (!signature || signature.numberOfArguments != 2 || !type || (type[0] != 'B' && type[0] != 'c')) return NO;
        unsigned char locked = ((unsigned char (*)(id, SEL))objc_msgSend)(manager, sel);
        if (locked > 1) return NO;
        if (known) *known = YES;
        return locked == 0; // Unknown/non-boolean values never count as unlocked.
    } @catch (NSException *exception) { (void)exception; return NO; }
}
+ (instancetype)shared {
    static MiniSightMusicMonitor *value; static dispatch_once_t once;
    dispatch_once(&once, ^{ value = [MiniSightMusicMonitor new]; });
    return value;
}
- (instancetype)init {
    if ((self = [super init])) {
        _client = [MiniSightLyricsClient new];
        _snapshot = @{ @"version": @1, @"line": @"", @"playing": @NO, @"source": @"", @"time": @0,
            @"diagnostics": @{ @"version": @1, @"player": @"not_applicable", @"metadata": @"not_applicable",
                @"progress": @"not_applicable", @"lyrics": @"not_applicable" } };
        _retryTimes = [NSMutableDictionary dictionary];
        _bridgeQueue = dispatch_queue_create("com.openminis.minisight.music.bridge", DISPATCH_QUEUE_SERIAL);
        _springBoard = [NSBundle.mainBundle.bundleIdentifier isEqualToString:@"com.apple.springboard"];
#ifdef MINISIGHT_MUSIC_MONITOR_TEST
        _springBoard = YES; // Only the Foundation fixture build supplies fake providers.
#else
        if (_springBoard) {
            MSMusicHandle = dlopen("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote", RTLD_LAZY | RTLD_LOCAL);
            if (MSMusicHandle) {
                MSMusicInfo = (MSMusicInfoFn)MSMusicSymbol(MSMusicHandle, "MRMediaRemoteGetNowPlayingInfo", YES);
                MSMusicIsPlaying = (MSMusicPlayingFn)MSMusicSymbol(MSMusicHandle, "MRMediaRemoteGetNowPlayingApplicationIsPlaying", YES);
            }
            for (NSString *name in @[@"kMRMediaRemoteNowPlayingInfoDidChangeNotification",
                    @"kMRMediaRemoteNowPlayingApplicationDidChangeNotification",
                    @"kMRMediaRemoteNowPlayingApplicationIsPlayingDidChangeNotification"]) {
                NSString *notification = MSMusicKey(name.UTF8String);
                if (notification.length) [NSNotificationCenter.defaultCenter addObserver:self
                    selector:@selector(mediaChanged:) name:notification object:nil];
            }
            // Do not unregister SpringBoard's shared MediaRemote notifications.
            // Bounded polling below also covers OS versions missing these notes.
        }
#endif
    }
    return self;
}
- (NSDictionary *)snapshot { return _snapshot; }
- (void)configureAllowed:(BOOL)allowed lyrics:(BOOL)lyrics motion:(BOOL)motion container:(NSString *)container {
    NSDictionary *presentation = _presentationHandler ? _presentationHandler() :
        @{@"allowed": @((BOOL)allowed), @"stopReason": allowed ? @"eligible" : @"not_visible_or_disabled"};
    [self configureAllowed:allowed lyrics:lyrics motion:motion container:container presentation:presentation];
}
- (void)configureAllowed:(BOOL)allowed lyrics:(BOOL)lyrics motion:(BOOL)motion container:(NSString *)container presentation:(NSDictionary *)presentation {
    NSAssert(NSThread.isMainThread, @"Music monitor is main-thread owned");
    allowed = allowed && _springBoard;
    if (!_presentationHandler) {
        allowed = NO;
        presentation = @{@"allowed": @NO, @"stopReason": @"presentation_provider_missing"};
    } else if (allowed) {
        presentation = _presentationHandler(); // production provider, never caller's stale ON
    }
    BOOL lockKnown = NO;
    if (allowed && ![MiniSightMusicMonitor deviceIsUnlockedWithKnown:&lockKnown]) {
        allowed = NO;
        NSMutableDictionary *closed = [presentation mutableCopy] ?: [NSMutableDictionary dictionary];
        closed[@"allowed"] = @NO; closed[@"lockKnown"] = @((BOOL)lockKnown); closed[@"unlocked"] = @NO;
        closed[@"stopReason"] = lockKnown ? @"device_locked" : @"lock_state_unknown";
        presentation = closed;
    }
    id gate = presentation[@"allowed"];
    if (_presentationHandler && (![gate isKindOfClass:NSNumber.class] ||
        CFGetTypeID((__bridge CFTypeRef)gate) != CFBooleanGetTypeID() || ![gate boolValue])) allowed = NO;
    _presentation = [presentation copy] ?: @{};
    BOOL changed = _allowed != allowed || _lyrics != lyrics || _motion != motion ||
        !((_container == container) || [_container isEqualToString:container]);
    if (!changed) {
        [self publishLine:_snapshot[@"line"] playing:[_snapshot[@"playing"] boolValue] force:NO];
        return;
    }
    _allowed = allowed; _lyrics = lyrics; _motion = motion; _container = [container copy];
    // Invalidation is not cancellation: MediaRemote has no cancellation API.
    // Keep the physical slot occupied across close/open until its callback arrives.
    ++_readGeneration; ++_trackGeneration; _fetching = NO;
    [_client cancel]; _timeline = nil; _track = nil; _identity = nil; _source = nil;
    _playing = NO; _validAt = 0; _awaitingFreshInfo = YES;
    _playerIdentified = NO; _progressAvailable = NO; _lyricsRequestFinished = NO;
    _lyricsAwaitingFreshInfo = NO;
    [_timer invalidate]; _timer = nil;
    [self publishLine:nil playing:NO force:YES];
    if (!_allowed || (!_lyrics && !_motion) || !_container.length || !MSMusicInfo || !MSMusicIsPlaying) {
        MSMusicEvidence(@"stop", @"skipped", _readGeneration, !_allowed ? @"not_visible_or_disabled" : @"media_api_unavailable", NO, NO, NO, (_lyrics || _motion));
        return;
    }
    __weak typeof(self) weakSelf = self;
    _timer = [NSTimer timerWithTimeInterval:0.25 repeats:YES block:^(NSTimer *timer) {
        (void)timer; [weakSelf tick];
    }];
    _timer.tolerance = 0.05;
    [NSRunLoop.mainRunLoop addTimer:_timer forMode:NSRunLoopCommonModes];
    _pollAt = 0;
    [self tick];
}
- (void)mediaChanged:(NSNotification *)note {
    (void)note;
    // One queued event even if notifications arrive off-main in a burst.
    @synchronized (self) { if (_eventQueued) return; _eventQueued = YES; }
    dispatch_async(dispatch_get_main_queue(), ^{
        @synchronized (self) { self->_eventQueued = NO; }
        [self handleMediaChange];
    });
}
- (void)handleMediaChange {
    if (!_timer) return;
    ++_readGeneration;
    _pollAt = fmax(_readAt + 0.5, MSMusicNow() + 0.15);
    _awaitingFreshInfo = YES; _playing = NO;
    NSString *source = MSMusicPlayer();
    _playerIdentified = source.length > 0;
    if (![_source isEqualToString:source]) {
        ++_trackGeneration; [_client cancel]; _fetching = NO; _timeline = nil;
        _identity = nil; _track = nil; _source = [source copy];
        _lyricsRequestFinished = NO; _progressAvailable = NO;
    }
    [self publishLine:nil playing:NO force:NO];
}
- (BOOL)refreshPresentation {
    if (!_presentationHandler) {
        [self configureAllowed:NO lyrics:_lyrics motion:_motion container:_container presentation:@{}];
        return NO;
    }
    if (_presentationHandler) {
        NSDictionary *current = _presentationHandler();
        id gate = current[@"allowed"];
        BOOL eligible = [gate isKindOfClass:NSNumber.class] &&
            CFGetTypeID((__bridge CFTypeRef)gate) == CFBooleanGetTypeID() && [gate boolValue];
        _presentation = [current copy] ?: @{};
        if (!eligible) {
            [self configureAllowed:NO lyrics:_lyrics motion:_motion container:_container presentation:_presentation];
            return NO;
        }
    }
    BOOL known = NO;
    if (![MiniSightMusicMonitor deviceIsUnlockedWithKnown:&known]) {
        NSMutableDictionary *closed = [_presentation mutableCopy] ?: [NSMutableDictionary dictionary];
        closed[@"allowed"] = @NO; closed[@"lockKnown"] = @((BOOL)known); closed[@"unlocked"] = @NO;
        closed[@"stopReason"] = known ? @"device_locked" : @"lock_state_unknown";
        [self configureAllowed:NO lyrics:_lyrics motion:_motion container:_container presentation:closed];
        return NO;
    }
    return YES;
}
- (void)tick {
    if (!_timer || !_allowed) return;
    if (![self refreshPresentation]) return;
    NSTimeInterval now = MSMusicNow();
    if (_reading && !_readTimedOut && now - _readAt > 3.) {
        // Fail closed, never launch replacements for a callback that may never arrive.
        _readTimedOut = YES; ++_readGeneration; ++_trackGeneration;
        [_client cancel]; _fetching = NO; _timeline = nil;
        _awaitingFreshInfo = YES; _playing = NO; _validAt = 0;
    }
    if (!_reading && now >= _pollAt) [self pollAt:now];
    BOOL current = _validAt > 0 && now >= _validAt - 1 && now - _validAt <= 6;
    BOOL playing = current && _playing && !_awaitingFreshInfo;
    NSString *line = nil;
    if (_lyrics && playing && _track && !_lyricsAwaitingFreshInfo) {
        double position = _elapsed + fmax(0., now - _stamp) * _rate;
        if (isfinite(position) && position >= 0 && position <= _track.duration + 0.1)
            line = [_timeline lineAtTime:position];
    }
    [self publishLine:line playing:playing force:NO];
}
static id MSMusicField(NSDictionary *info, const char *symbol) {
    NSString *key = MSMusicKey(symbol); return key.length ? info[key] : nil;
}
static NSDictionary *MSMusicCopyInfo(CFDictionaryRef raw) {
    // Own the borrowed dictionary before any queue hop; don't retain artwork/full metadata.
    if (!raw || CFGetTypeID(raw) != CFDictionaryGetTypeID()) return nil;
    NSDictionary *borrowed = (__bridge NSDictionary *)raw;
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSString *field in @[@"Title", @"Artist", @"Duration", @"ElapsedTime", @"PlaybackRate", @"Timestamp", @"UniqueIdentifier"]) {
        NSString *key = MSMusicKey([[@"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
        id value = key ? borrowed[key] : nil;
        if (([value isKindOfClass:NSString.class] && [value length] <= 512) ||
            [value isKindOfClass:NSNumber.class] || [value isKindOfClass:NSDate.class]) result[key] = [value copy];
    }
    return [result copy];
}
static NSString *MSMusicIdentity(NSDictionary *info, NSString *player) {
    MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc]
        initWithTitle:MSMusicField(info, "kMRMediaRemoteNowPlayingInfoTitle")
        artist:MSMusicField(info, "kMRMediaRemoteNowPlayingInfoArtist")
        duration:MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoDuration"), NAN)];
    id identifier = MSMusicField(info, "kMRMediaRemoteNowPlayingInfoUniqueIdentifier");
    if ([identifier isKindOfClass:NSNumber.class]) identifier = [identifier stringValue];
    if (![identifier isKindOfClass:NSString.class] || [identifier length] > 256) identifier = @"";
    if (![info isKindOfClass:NSDictionary.class] || !player.length) return nil;
    // Motion needs a current playback sample, not an LRCLIB-searchable title.
    // Unknown metadata never becomes bubble text; lyrics still require a track.
    return [NSString stringWithFormat:@"%@|%@|%lu:%@", player, track.cacheKey ?: @"unknown",
        (unsigned long)[identifier length], identifier];
}
- (BOOL)acceptRead:(NSUInteger)ticket generation:(NSUInteger)generation stage:(NSUInteger)stage player:(NSString *)player {
    NSAssert(NSThread.isMainThread, @"Media callbacks must hop to main");
    if (!_reading || ticket != _readTicket || stage != _readStage) return NO;
    ++_readStage; // Duplicate/reordered callbacks cannot consume the next stage.
    if (!_timer || !_allowed || ![self refreshPresentation] ||
        generation != _readGeneration || MSMusicNow() - _readAt > 3. || ![player isEqualToString:MSMusicPlayer()]) {
        _reading = NO;
        [self handleMediaChange];
        return NO;
    }
    return YES;
}
- (void)readInfo:(void (^)(NSDictionary *))completion {
    MSMusicInfo(dispatch_get_main_queue(), ^(CFDictionaryRef raw) {
        NSDictionary *info = MSMusicCopyInfo(raw);
        dispatch_async(dispatch_get_main_queue(), ^{ completion(info); });
    });
}
- (void)pollAt:(NSTimeInterval)now {
    _pollAt = now + 2.;
    NSString *player = MSMusicPlayer();
    if (!player.length) {
        if (!MSMusicLastSampleLogAt || now - MSMusicLastSampleLogAt >= 10.) {
            MSMusicLastSampleLogAt = now;
            MSMusicEvidence(@"sample", @"skipped", _readGeneration, @"no_supported_player", NO, NO, NO, (_lyrics || _motion));
        }
        _playerIdentified = NO; _progressAvailable = NO; _lyricsRequestFinished = NO;
        if (_source || _track) {
            ++_trackGeneration; [_client cancel]; _timeline = nil; _track = nil;
            _identity = nil; _source = nil; _fetching = NO;
        }
        _playing = NO; _validAt = now;
        return;
    }
    _reading = YES; _readTimedOut = NO; _readAt = now; _readStage = 1;
    NSUInteger request = ++_readGeneration, ticket = ++_readTicket;
    if (!MSMusicLastSampleLogAt || now - MSMusicLastSampleLogAt >= 10.) {
        MSMusicLastSampleLogAt = now;
        MSMusicEvidence(@"request", @"pending", request, @"media_sample", NO, NO, NO, (_lyrics || _motion));
    }
    __weak typeof(self) weakSelf = self;
    [self readInfo:^(NSDictionary *first) {
        typeof(self) self = weakSelf;
        if (!self || ![self acceptRead:ticket generation:request stage:1 player:player]) return;
        MSMusicIsPlaying(dispatch_get_main_queue(), ^(Boolean playing) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) self = weakSelf;
                if (!self || ![self acceptRead:ticket generation:request stage:2 player:player]) return;
                [self readInfo:^(NSDictionary *last) {
                    typeof(self) self = weakSelf;
                    if (!self || ![self acceptRead:ticket generation:request stage:3 player:player]) return;
                    self->_reading = NO;
                    BOOL compatible = MSMusicTrackIdentityCompatible(first, last, player);
                    if (!compatible) {
                        ++self->_trackGeneration; [self->_client cancel]; self->_fetching = NO;
                        self->_timeline = nil; self->_track = nil; self->_identity = nil; self->_identifier = nil;
                        [self handleMediaChange]; return;
                    }
                    // A stable player may fill metadata between reads. Use the
                    // complete side if present, while preserving strict conflict checks.
                    NSDictionary *resolved = MSMusicResolvedInfo(first, last, player);
                    [self applyInfo:resolved playing:playing player:player];
                }];
            });
        });
    }];
}
- (void)applyInfo:(NSDictionary *)info playing:(Boolean)playing player:(NSString *)player {
            __weak typeof(self) weakSelf = self;
            NSTimeInterval received = MSMusicNow();
            NSTimeInterval wall = NSDate.date.timeIntervalSince1970;
            NSString *title = MSMusicField(info, "kMRMediaRemoteNowPlayingInfoTitle");
            NSString *artist = MSMusicField(info, "kMRMediaRemoteNowPlayingInfoArtist");
            double duration = MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoDuration"), NAN);
            double elapsed = MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoElapsedTime"), NAN);
            double rate = MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoPlaybackRate"), playing ? 1. : 0.);
            id timestamp = MSMusicField(info, "kMRMediaRemoteNowPlayingInfoTimestamp");
            double stamp = [timestamp isKindOfClass:NSDate.class] ? [timestamp timeIntervalSince1970] : wall;
            double age = wall - stamp;
            MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc] initWithTitle:title artist:artist duration:duration];
            NSString *identifier = MSMusicIdentifier(info);
            BOOL sourceChanged = self->_source.length && ![self->_source isEqualToString:player];
            BOOL conflictingPartial = !track && MSMusicPartialConflicts(info, self->_track, self->_identifier);
            BOOL conflictingIdentifier = identifier.length && self->_identifier.length &&
                ![identifier isEqualToString:self->_identifier] &&
                (!track || !self->_track || ![track.cacheKey isEqualToString:self->_track.cacheKey]);
            BOOL changedTrack = sourceChanged || conflictingIdentifier ||
                (track && self->_track && ![track.cacheKey isEqualToString:self->_track.cacheKey]) || conflictingPartial;
            NSString *identity = MSMusicIdentity(info, player);
            if (changedTrack) {
                ++self->_trackGeneration; [self->_client cancel]; self->_fetching = NO;
                self->_timeline = nil; self->_track = nil; self->_identity = nil; self->_identifier = nil;
                [self publishLine:nil playing:NO force:YES];
            }
            if (track) {
                if (!self->_track) {
                    self->_track = track; self->_timeline = nil; self->_lyricsRequestFinished = NO;
                    if (!changedTrack) ++self->_trackGeneration;
                }
                self->_identity = identity;
                if (identifier.length) self->_identifier = [identifier copy];
            }
            self->_source = player; self->_validAt = received; self->_awaitingFreshInfo = NO;
            // Missing metadata can keep motion alive, but never reuse a lyric line.
            self->_lyricsAwaitingFreshInfo = !track;
            BOOL timing = !track || (isfinite(elapsed) && elapsed >= 0 && elapsed <= track.duration &&
                // Timestamp is the elapsed-time reference, not the date of this reply.
                // Many players keep it unchanged while the track plays normally.
                isfinite(age) && age >= -3. && age <= track.duration + 3. &&
                elapsed + fmax(0., age) * rate <= track.duration + .1);
            self->_playing = playing == 1 && [info isKindOfClass:NSDictionary.class] &&
                isfinite(rate) && rate > 0 && rate <= 4 && timing;
            self->_playerIdentified = player.length > 0;
            self->_progressAvailable = MSMusicProgressValid(info, track);
            if (!MSMusicLastSampleLogAt || received - MSMusicLastSampleLogAt >= 10.) {
                MSMusicLastSampleLogAt = received;
                MSMusicEvidence(@"sample", @"ok", self->_trackGeneration, track ? @"track_valid" : @"metadata_missing",
                    track != nil, self->_progressAvailable, NO, (self->_lyrics || self->_motion));
            }
            self->_elapsed = elapsed; self->_rate = self->_playing ? rate : 0;
            self->_stamp = received - fmax(0., age);
            NSString *retryKey = self->_track.cacheKey;
            if (self->_playing && self->_lyrics && track && self->_track && self->_progressAvailable && !self->_timeline &&
                !self->_fetching && received >= [self->_retryTimes[retryKey] doubleValue]) {
                for (NSString *key in [self->_retryTimes.allKeys copy])
                    if ([self->_retryTimes[key] doubleValue] <= received) [self->_retryTimes removeObjectForKey:key];
                // Strictly bounded, fail closed if 16 distinct signatures are cooling down.
                if (self->_retryTimes.count >= 16 && !self->_retryTimes[retryKey]) { [self tick]; return; }
                self->_fetching = YES; self->_lyricsRequestFinished = NO;
                MSMusicEvidence(@"request", @"pending", self->_trackGeneration, @"lyrics_fetch", YES, NO, NO, YES);
                self->_retryTimes[retryKey] = @(received + 60.);
                NSUInteger generation = self->_trackGeneration;
                [self->_client fetchTrack:self->_track completion:^(MiniSightLyricsTimeline *timeline) {
                    dispatch_async(dispatch_get_main_queue(), ^{
                        typeof(self) self = weakSelf;
                        if (!self || !self->_allowed || !self->_lyrics || generation != self->_trackGeneration) return;
                        self->_fetching = NO; self->_lyricsRequestFinished = YES; self->_timeline = timeline;
                        MSMusicEvidence(@"finish", timeline ? @"ok" : @"skipped", generation,
                            timeline ? @"lyrics_timeline" : @"no_synced_lyrics", YES, timeline != nil, NO, YES);
                        if (![player isEqualToString:MSMusicPlayer()]) { [self handleMediaChange]; return; }
                        // A result never publishes against the old sample: force a fresh
                        // identity sandwich, also covering same-player changes without a note.
                        self->_lyricsAwaitingFreshInfo = YES;
                        self->_pollAt = fmax(self->_readAt + 0.5, MSMusicNow());
                        [self tick];
                    });
                }];
            }
            [self tick];
}
- (void)publishLine:(NSString *)line playing:(BOOL)playing force:(BOOL)force {
    NSTimeInterval now = NSDate.date.timeIntervalSince1970;
    NSString *safeLine = [line isKindOfClass:NSString.class] && line.length <= 240 ? line : @"";
    if (!_allowed || !_lyrics || !playing) safeLine = @"";
    NSString *source = _allowed ? (_source ?: @"") : @"";
    // Bounded diagnostics, never track metadata or status text for the bubble.
    NSString *stopReason = [_presentation[@"stopReason"] isKindOfClass:NSString.class] ? _presentation[@"stopReason"] : @"unknown_gate";
    NSString *reason = !_allowed ? @"not_visible_or_disabled"
        : (!_lyrics && !_motion) ? @"settings_disabled"
        : (!MSMusicInfo || !MSMusicIsPlaying) ? @"media_api_unavailable"
        : _readTimedOut && _reading ? @"media_callback_timeout"
        : _awaitingFreshInfo ? @"waiting_for_current_state"
        : !playing ? @"not_playing"
        : !_track ? @"playing_without_lyrics_metadata"
        : !_lyrics ? @"motion_only"
        : _fetching ? @"lyrics_pending"
        : !_timeline ? @"no_synced_lyrics"
        : !safeLine.length ? @"no_current_line" : @"current_line";
    MSMusicDiagnosticStages stages = MSMusicDiagnose(_allowed && (_lyrics || _motion),
        (bool)(MSMusicInfo && MSMusicIsPlaying), _playerIdentified, _awaitingFreshInfo,
        _track != nil, _progressAvailable, _lyrics, playing, _fetching,
        _lyricsAwaitingFreshInfo, _lyricsRequestFinished, _timeline != nil, safeLine.length > 0);
    NSDictionary *diagnostics = @{@"version": @1,
        @"player": [NSString stringWithUTF8String:stages.player] ?: @"",
        @"metadata": [NSString stringWithUTF8String:stages.metadata] ?: @"",
        @"progress": [NSString stringWithUTF8String:stages.progress] ?: @"",
        @"lyrics": [NSString stringWithUTF8String:stages.lyrics] ?: @""};
    BOOL changed = ![_snapshot[@"line"] isEqual:safeLine] || [_snapshot[@"playing"] boolValue] != playing ||
        ![_snapshot[@"source"] isEqual:source] || [_snapshot[@"lyricsEnabled"] boolValue] != (_allowed && _lyrics) ||
        [_snapshot[@"motionEnabled"] boolValue] != (_allowed && _motion) ||
        ![_snapshot[@"diagnostics"] isEqual:diagnostics] ||
        [_snapshot[@"allowed"] boolValue] != _allowed || ![_snapshot[@"reason"] isEqual:reason] ||
        ![_snapshot[@"stopReason"] isEqual:stopReason];
    if (!changed && !force && MSMusicNow() - _writeAt < 2.) return;
    _writeAt = MSMusicNow();
    if (changed) MSMusicEvidence(@"publish", @"ok", _trackGeneration,
        safeLine.length ? @"lyrics_line" : @"empty_line", YES, safeLine.length > 0, NO, _lyrics);
    // Explicit BOOL casts prevent logical/conditional expressions boxing as int.
    // Keep v1 envelope for installed readers; evidence is additive and separately versioned.
    _snapshot = @{@"version": @1, @"evidenceVersion": @1, @"line": safeLine, @"playing": @((BOOL)(_allowed && playing)),
        @"allowed": @((BOOL)_allowed), @"source": source,
        @"lyricsEnabled": @((BOOL)(_allowed && _lyrics)),
        @"motionEnabled": @((BOOL)(_allowed && _motion)),
        @"requestedLyrics": @((BOOL)_lyrics), @"requestedMotion": @((BOOL)_motion),
        @"diagnostics": diagnostics, @"presentation": _presentation ?: @{}, @"stopReason": stopReason,
        @"time": @(now), @"generation": @(_trackGeneration), @"reason": reason};
    if (_updateHandler) _updateHandler(_snapshot);
    if (!_springBoard) return;
    @synchronized (self) {
        _pendingContainer = [_container copy]; _pendingSnapshot = _snapshot;
        ++_bridgeVersion; _bridgePending = YES;
        if (_bridgeScheduled) return;
        _bridgeScheduled = YES;
    }
    dispatch_async(_bridgeQueue, ^{ [self drainBridge]; });
}
- (void)drainBridge {
    // One writer plus one latest-value mailbox, never a queue of historic lyrics.
    for (;;) { @autoreleasepool {
        NSDictionary *snapshot; NSString *container; NSUInteger version;
        @synchronized (self) {
            if (!_bridgePending) { _bridgeScheduled = NO; return; }
            snapshot = _pendingSnapshot; container = _pendingContainer; version = _bridgeVersion;
            _pendingSnapshot = nil; _pendingContainer = nil; _bridgePending = NO;
        }
        if (_writtenContainer.length && ![_writtenContainer isEqualToString:container]) {
            NSMutableDictionary *clear = [snapshot mutableCopy];
            clear[@"line"] = @""; clear[@"source"] = @""; clear[@"playing"] = @NO;
            clear[@"allowed"] = @NO; clear[@"lyricsEnabled"] = @NO; clear[@"motionEnabled"] = @NO;
            clear[@"reason"] = @"container_changed"; clear[@"stopReason"] = @"container_changed";
            clear[@"presentation"] = @{@"allowed": @NO, @"stopReason": @"container_changed"};
            if (MSBridgeWrite(_writtenContainer, @"music-state.json", clear) &&
                [MSBridgeRead(_writtenContainer, @"music-state.json", 16384) isEqualToDictionary:clear])
                MSBridgePost(@"com.openminis.minisight.music");
            _writtenContainer = nil;
        }
        @synchronized (self) { if (version != _bridgeVersion) continue; }
        if (!container.length) continue;
        _writtenContainer = container;
        BOOL verified = MSBridgeWrite(container, @"music-state.json", snapshot) &&
            [MSBridgeRead(container, @"music-state.json", 16384) isEqualToDictionary:snapshot];
        MSMusicEvidence(@"readback", verified ? @"ok" : @"failed", [snapshot[@"generation"] unsignedIntegerValue],
            verified ? @"snapshot_verified" : @"snapshot_write_failed", YES,
            [snapshot[@"line"] length] > 0, verified, [snapshot[@"lyricsEnabled"] boolValue]);
        @synchronized (self) {
            // If invalidated during I/O, don't announce it; immediately drain the
            // latest clear/state. An already-running atomic write cannot be cancelled.
            if (verified && version == _bridgeVersion) {
                MSBridgePost(@"com.openminis.minisight.music");
                MSMusicEvidence(@"deliver", @"ok", [snapshot[@"generation"] unsignedIntegerValue],
                    @"darwin_notification", YES, [snapshot[@"line"] length] > 0, YES,
                    [snapshot[@"lyricsEnabled"] boolValue]);
            }
        }
    } }
}
- (void)dealloc {
    [_timer invalidate]; [_client cancel];
    [NSNotificationCenter.defaultCenter removeObserver:self];
}
@end
