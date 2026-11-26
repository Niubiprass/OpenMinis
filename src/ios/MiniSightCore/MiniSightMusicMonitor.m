#import "MiniSightMusicMonitor.h"
#import "MiniSightMusicPlayerABI.h"
#import "MiniSightLyrics.h"
#import "MiniSightBridgeIO.h"
#import "MiniSightLog.h"
#import <CoreFoundation/CoreFoundation.h>
#import <objc/message.h>
#import <dlfcn.h>
#import <dispatch/dispatch.h>
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
#ifdef MINISIGHT_MUSIC_MONITOR_TEST
// Controlled fixture clock; production always uses monotonic system uptime.
static NSTimeInterval (*MSMusicTestNow)(void);
#endif
static NSTimeInterval MSMusicNow(void) {
#ifdef MINISIGHT_MUSIC_MONITOR_TEST
    if (MSMusicTestNow) return MSMusicTestNow();
#endif
    return NSProcessInfo.processInfo.systemUptime;
}

// Signatures from the MediaRemote header; symbols remain optional on each OS.
typedef void (*MSMusicInfoFn)(dispatch_queue_t, void (^)(CFDictionaryRef));
typedef void (*MSMusicPlayingFn)(dispatch_queue_t, void (^)(Boolean));
// theos/headers MediaRemote.h: PID completion takes int, not an object.
typedef void (*MSMusicPIDFn)(dispatch_queue_t, void (^)(int));
static MSMusicInfoFn MSMusicInfo;
static MSMusicPlayingFn MSMusicIsPlaying;
static MSMusicPIDFn MSMusicPID;
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
static NSString *MSMusicBundle(id app, NSString **reason) {
    id bundle = [app isKindOfClass:NSString.class] ? app : MSMusicObject(app, @"bundleIdentifier");
    if (![bundle isKindOfClass:NSString.class] || ![bundle length] || [bundle length] > 128) {
        if (reason) *reason = @"player_bundle_missing";
        return nil;
    }
    NSString *value = bundle;
    static NSSet *players; static dispatch_once_t once;
    dispatch_once(&once, ^{ players = [NSSet setWithArray:@[@"com.netease.cloudmusic", @"com.tencent.QQMusic",
        @"com.kugou.kugou1002", @"com.yeelion.kwplayer", @"com.apple.Music"]]; });
    if (![players containsObject:value]) { if (reason) *reason = @"unsupported_player"; return nil; }
    if (reason) *reason = [value isEqualToString:@"com.netease.cloudmusic"]
        ? @"netease_player_selected" : @"supported_player_selected";
    return value;
}
static NSString *MSMusicResolvePlayer(NSString **reason) {
    if (reason) *reason = @"media_controller_unavailable";
    @try {
        id media = MSMusicObject(NSClassFromString(@"SBMediaController"), @"sharedInstance");
        if (!media) return nil;
        NSMethodSignature *sig = [media methodSignatureForSelector:NSSelectorFromString(@"nowPlayingApplication")];
        if (!sig || sig.numberOfArguments != 2 || sig.methodReturnType[0] != '@') return nil;
        id app = MSMusicObject(media, @"nowPlayingApplication");
        if (!app) { if (reason) *reason = @"no_active_player"; return nil; }
        return MSMusicBundle(app, reason);
    } @catch (NSException *exception) {
        (void)exception;
        if (reason) *reason = @"media_controller_unavailable";
        return nil;
    }
}
// Versioned iOS headers disagree (int/pid_t vs NSInteger). Validate the
// runtime signature and use a separately typed send for each supported ABI.
static NSString *MSMusicPIDPlayer(int pid, NSString **reason) {
    if (reason) *reason = @"player_pid_nonpositive";
    if (pid <= 0) return nil;
    @try {
        if (reason) *reason = @"pid_controller_unavailable";
        id controller = MSMusicObject(NSClassFromString(@"SBApplicationController"), @"sharedInstance");
        if (!controller) return nil;
        SEL sel = NSSelectorFromString(@"applicationWithPid:");
        if (reason) *reason = @"pid_method_unavailable";
        if (![controller respondsToSelector:sel]) return nil;
        if (reason) *reason = @"pid_signature_missing";
        NSMethodSignature *sig = [controller methodSignatureForSelector:sel];
        if (!sig) return nil;
        if (reason) *reason = @"pid_signature_rejected";
        if (sig.numberOfArguments != 3) return nil;
        MSMusicPIDABI abi = MSMusicPIDABIForTypes(sig.methodReturnType, sig.numberOfArguments,
            [sig getArgumentTypeAtIndex:0], [sig getArgumentTypeAtIndex:1],
            [sig getArgumentTypeAtIndex:2], @encode(NSInteger));
        id app = nil;
        if (abi == MSMusicPIDABIInt)
            app = ((id (*)(id, SEL, int))objc_msgSend)(controller, sel, pid);
        else if (abi == MSMusicPIDABINSInteger)
            app = ((id (*)(id, SEL, NSInteger))objc_msgSend)(controller, sel, (NSInteger)pid);
        else return nil;
        if (reason) *reason = @"pid_mapping_missing";
        return app ? MSMusicBundle(app, reason) : nil;
    } @catch (NSException *exception) {
        (void)exception; if (reason) *reason = @"pid_resolution_exception"; return nil;
    }
}
// BEGIN MUSIC SAMPLE POLICY (shared verbatim with portable tests)
static bool MSMusicPIDMatches(int first, int last, bool sameBundle) {
    return first > 0 && first == last && sameBundle;
}
static bool MSMusicPublishDue(bool changed, bool force, double now, double previous) {
    return changed || force || now - previous >= 2.;
}
// Metadata-only hints may reuse an ALREADY verified direct sample for at most
// one second total. Hints never renew this lease; PID fallback is not evidence.
static bool MSMusicMetadataLease(bool verified, bool sameDirect, double now, double validAt) {
    return verified && sameDirect && validAt > 0. && now >= validAt && now - validAt <= 1.;
}
static bool MSMusicCandidateAlive(double now, double until) {
    return until > 0. && now <= until;
}
// Music input owns a playback lease, not the lyric-fetch or line generation.
// A real stop/unknown/source transition closes the lease; ordinary revalidation
// and lyric deliveries must not repeatedly restart the beat analyzer.
static unsigned long long MSMusicNextRhythmGeneration(unsigned long long previous,
    bool active, bool wasActive, bool sameSource) {
    if (!active || (wasActive && sameSource && previous)) return previous;
    return previous >= 9007199254740991ULL ? 1ULL : previous + 1ULL;
}
// END MUSIC SAMPLE POLICY
// BEGIN MUSIC PROGRESS POLICY
static bool MSMusicUseFirstProgress(bool sameTrack, bool lastElapsedMissing,
                                    bool firstProgressValid, bool firstTimestampValid) {
    return sameTrack && lastElapsedMissing && firstProgressValid && firstTimestampValid;
}
// END MUSIC PROGRESS POLICY
static BOOL MSMusicMissingSource(NSString *reason) {
    return [reason isEqual:@"no_active_player"] || [reason isEqual:@"player_bundle_missing"] ||
        [reason isEqual:@"media_controller_unavailable"];
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
// BEGIN MUSIC DURATION POLICY (compiled verbatim by portable tests)
static bool MSMusicDurationCompatible(double first, double last) {
    // Continuity only: provider matching and exact lyrics cache keys do not change.
    return isfinite(first) && isfinite(last) && fabs(first - last) <= 1.0;
}
// END MUSIC DURATION POLICY
static NSUInteger MSMusicTrackConflictMask(MiniSightLyricsTrack *firstTrack,
    MiniSightLyricsTrack *lastTrack) {
    if (!firstTrack || !lastTrack) return 0;
    NSUInteger mask = 0;
    if (![firstTrack.title isEqualToString:lastTrack.title]) mask |= 1u;
    if (![firstTrack.artist isEqualToString:lastTrack.artist]) mask |= 2u;
    if (!MSMusicDurationCompatible(firstTrack.duration, lastTrack.duration)) mask |= 4u;
    return mask;
}
static NSUInteger MSMusicIdentityConflictMask(NSDictionary *first, NSDictionary *last) {
    MiniSightLyricsTrack *firstTrack = MSMusicTrack(first), *lastTrack = MSMusicTrack(last);
    NSUInteger mask = MSMusicTrackConflictMask(firstTrack, lastTrack);
    for (NSString *field in @[@"Title", @"Artist"]) {
        NSString *key = MSMusicKey([[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
        id a = key ? first[key] : nil, b = key ? last[key] : nil;
        if ([a isKindOfClass:NSString.class] && [b isKindOfClass:NSString.class]) {
            NSString *normalizedA = MSLyricsNormalize(a), *normalizedB = MSLyricsNormalize(b);
            BOOL equal = normalizedA && normalizedB ? [normalizedA isEqualToString:normalizedB]
                : [[a precomposedStringWithCanonicalMapping] isEqualToString:[b precomposedStringWithCanonicalMapping]];
            if (!equal) mask |= [field isEqualToString:@"Title"] ? 1u : 2u;
        }
    }
    NSString *durationKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoDuration");
    double a = durationKey ? MSMusicNumber(first[durationKey], NAN) : NAN;
    double b = durationKey ? MSMusicNumber(last[durationKey], NAN) : NAN;
    if (isfinite(a) && isfinite(b) && !MSMusicDurationCompatible(a, b)) mask |= 4u;
    NSString *firstID = MSMusicIdentifier(first), *lastID = MSMusicIdentifier(last);
    if (firstID.length && lastID.length && ![firstID isEqualToString:lastID]) mask |= 8u;
    return mask;
}
static BOOL MSMusicTracksCompatible(MiniSightLyricsTrack *firstTrack, NSString *firstID,
    MiniSightLyricsTrack *lastTrack, NSString *lastID, BOOL hasTimeline) {
    if (!firstTrack || !lastTrack) return NO;
    // Preserve baseline complete/exact-track ID-churn semantics. An epsilon
    // match is weaker: it requires a successful timeline and no known ID conflict.
    if ([firstTrack.cacheKey isEqualToString:lastTrack.cacheKey]) return YES;
    return hasTimeline && MSMusicTrackConflictMask(firstTrack, lastTrack) == 0 &&
        !(firstID.length && lastID.length && ![firstID isEqualToString:lastID]);
}
static BOOL MSMusicTrackIdentityCompatible(NSDictionary *first, NSDictionary *last, NSString *player) {
    if (!player.length) return NO;
    // Title/artist remain exact after the existing NFC/POSIX normalization;
    // only the MediaRemote duration field receives a bounded continuity slack.
    return MSMusicIdentityConflictMask(first, last) == 0;
}
static BOOL MSMusicProgressValid(NSDictionary *info, MiniSightLyricsTrack *track);
static NSDictionary *MSMusicResolvedInfo(NSDictionary *first, NSDictionary *last, NSString *player) {
    if (![last isKindOfClass:NSDictionary.class] || !MSMusicTrackIdentityCompatible(first ?: @{}, last, player)) return last;
    NSMutableDictionary *resolved = [last mutableCopy];
    for (NSString *field in @[@"Title", @"Artist", @"Duration", @"UniqueIdentifier"]) {
        NSString *key = MSMusicKey([[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
        if (key && !resolved[key] && first[key]) resolved[key] = first[key];
    }
    MiniSightLyricsTrack *firstTrack = MSMusicTrack(first), *resolvedTrack = MSMusicTrack(resolved);
    NSString *elapsedKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoElapsedTime");
    NSString *timestampKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoTimestamp");
    BOOL sameTrack = firstTrack && resolvedTrack && MSMusicTrackConflictMask(firstTrack, resolvedTrack) == 0;
    if (MSMusicUseFirstProgress(sameTrack, elapsedKey && !last[elapsedKey],
        MSMusicProgressValid(first, firstTrack), timestampKey && [first[timestampKey] isKindOfClass:NSDate.class])) {
        // Preserve a real same-track sample as a GROUP. An elapsed value from
        // the first read must never acquire the last read's newer timestamp/rate.
        // Explicit invalid last progress is not "missing" and is never rescued.
        for (NSString *field in @[@"ElapsedTime", @"PlaybackRate", @"Timestamp"]) {
            NSString *key = MSMusicKey([[ @"kMRMediaRemoteNowPlayingInfo" stringByAppendingString:field] UTF8String]);
            if (!key) continue;
            if (first[key]) resolved[key] = first[key]; else [resolved removeObjectForKey:key];
        }
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
        if (!candidate || ![candidate.title isEqualToString:current.title]) return YES;
    }
    NSString *artistKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoArtist");
    id artist = artistKey ? info[artistKey] : nil;
    if ([artist isKindOfClass:NSString.class]) {
        MiniSightLyricsTrack *candidate = [[MiniSightLyricsTrack alloc] initWithTitle:current.title artist:artist duration:current.duration];
        if (!candidate || ![candidate.artist isEqualToString:current.artist]) return YES;
    }
    NSString *durationKey = MSMusicKey("kMRMediaRemoteNowPlayingInfoDuration");
    double duration = durationKey ? MSMusicNumber(info[durationKey], NAN) : NAN;
    return isfinite(duration) && !MSMusicDurationCompatible(duration, current.duration);
}
static BOOL MSMusicProgressValid(NSDictionary *info, MiniSightLyricsTrack *track) {
    double elapsed = MSMusicNumber(MSMusicField(info, "kMRMediaRemoteNowPlayingInfoElapsedTime"), NAN);
    return track && isfinite(elapsed) && elapsed >= 0. && elapsed <= track.duration + .1;
}

static void MSMusicEvidence(NSString *stage, NSString *result, NSUInteger generation, NSString *reason,
    BOOL valid, BOOL present, BOOL readback, BOOL enabled) {
    // Only compare fixed-vocabulary evidence; heartbeat writes/deliveries still run normally.
    static NSMutableDictionary *times; static NSMutableDictionary *last; static NSObject *lock; static dispatch_once_t once;
    dispatch_once(&once, ^{ last = [NSMutableDictionary dictionary]; times = [NSMutableDictionary dictionary]; lock = [NSObject new]; });
    NSString *slot = [reason isEqual:@"lyrics_fetch"] ? @"lyrics_fetch" : stage;
    NSArray *key = @[result, reason, @(valid), @(present), @(readback), @(enabled)];
    @synchronized (lock) {
        double now = MSMusicNow();
        if ([last[slot] isEqual:key] && now - [times[slot] doubleValue] < 60.) return;
        times[slot] = @(now);
        last[slot] = key;
    }
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
    int _pidRead, _verifiedPID; BOOL _sourceFromPID;
    BOOL _metadataRevalidate, _eventStrong;
    NSTimeInterval _candidateUntil;
    NSUInteger _identityEpoch, _playbackSequence, _rhythmGeneration;
    NSString *_stateReason;
    NSMutableDictionary<NSString *, NSArray *> *_identityEvidence;
    NSMutableDictionary<NSString *, NSNumber *> *_identityEvidenceAt;
    NSString *_playerDetail, *_lyricsDetail;
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
                MSMusicPID = (MSMusicPIDFn)MSMusicSymbol(MSMusicHandle, "MRMediaRemoteGetNowPlayingApplicationPID", YES);
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
- (void)identityEvidence:(NSString *)reason {
    // Fixed reasons + numeric stages only. Separate per-reason slots keep a
    // heartbeat/sample event from overwriting the last rejection evidence.
    if (!_identityEvidence) { _identityEvidence = [NSMutableDictionary dictionary]; _identityEvidenceAt = [NSMutableDictionary dictionary]; }
    NSTimeInterval now = MSMusicNow();
    NSArray *key = @[@(_playbackSequence), @((BOOL)_playing), @((BOOL)(_candidateUntil > 0.))];
    if ([_identityEvidence[reason] isEqual:key] && now - [_identityEvidenceAt[reason] doubleValue] < 60.) return;
    _identityEvidence[reason] = key; _identityEvidenceAt[reason] = @(now);
    MSDiagEvent(@"music", @"sample", @"ok", @{@"source": @"plugin", @"reason": reason,
        @"generation": @(_readGeneration), @"enabled": @((BOOL)_allowed),
        @"present": @((BOOL)(_timeline != nil)), @"valid": @((BOOL)(_playing && !_awaitingFreshInfo && _validAt > 0. && now - _validAt <= 6.)),
        @"read_stage": @(_readStage), @"identity_epoch": @(_identityEpoch),
        @"last_valid_age_ms": @(_validAt > 0. ? fmin(60000., fmax(0., now - _validAt) * 1000.) : -1.)});
}
- (void)beginCandidate:(NSString *)reason {
    // Candidate data is never presentation evidence; expiry is non-sliding.
    if (_candidateUntil <= 0. && _track) _candidateUntil = MSMusicNow() + 3.;
    _metadataRevalidate = NO; _awaitingFreshInfo = YES; _playing = NO;
    _stateReason = reason;
    [self identityEvidence:reason];
}
- (void)discardCandidate:(NSString *)reason {
    ++_trackGeneration; ++_identityEpoch; [_client cancel]; _fetching = NO;
    _timeline = nil; _track = nil; _identity = nil; _identifier = nil;
    _candidateUntil = 0.; _verifiedPID = 0; _lyricsRequestFinished = NO;
    _lyricsDetail = nil; _progressAvailable = NO;
    _metadataRevalidate = NO; _awaitingFreshInfo = YES; _playing = NO;
    _stateReason = reason; [self identityEvidence:reason];
}
- (void)beginPause {
    // Hide immediately and fence unfinished lookups. Successful lyrics remain
    // only a bounded candidate until the full track/source/PID sandwich agrees.
    ++_trackGeneration; ++_identityEpoch; [_client cancel]; _fetching = NO;
    [self beginCandidate:@"confirmed_pause"];
    [self publishLine:nil playing:NO force:NO];
}
- (NSTimeInterval)motionPosition {
    if (!_playing || _validAt <= 0) return 0.;
    double now = MSMusicNow();
    double position = _elapsed + fmax(0., now - _stamp) * _rate;
    return isfinite(position) && position >= 0. && position <= 3600. ? position : 0.;
}
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
    _playerDetail = nil; _lyricsDetail = nil; _sourceFromPID = NO;
    _allowed = allowed; _lyrics = lyrics; _motion = motion; _container = [container copy];
    // Invalidation is not cancellation: MediaRemote has no cancellation API.
    // Keep the physical slot occupied across close/open until its callback arrives.
    ++_readGeneration; ++_trackGeneration; _fetching = NO;
    [_client cancel]; _timeline = nil; _track = nil; _identity = nil; _source = nil;
    _playing = NO; _validAt = 0; _awaitingFreshInfo = YES;
    _playerIdentified = NO; _progressAvailable = NO; _lyricsRequestFinished = NO;
    _lyricsAwaitingFreshInfo = NO;
    _metadataRevalidate = NO; _candidateUntil = 0.; _verifiedPID = 0;
    ++_identityEpoch; _stateReason = @"presentation_invalidated";
    [self identityEvidence:_stateReason];
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
    // Only the known metadata notification is a soft hint. Unknown/nil,
    // application and playback-state notes retain immediate fail-closed handling.
    NSString *metadataName = MSMusicKey("kMRMediaRemoteNowPlayingInfoDidChangeNotification");
    BOOL strong = !note || !metadataName.length || ![note.name isEqualToString:metadataName];
    @synchronized (self) {
        _eventStrong = _eventStrong || strong;
        if (_eventQueued) return;
        _eventQueued = YES;
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        BOOL hard;
        @synchronized (self) { hard = self->_eventStrong; self->_eventStrong = NO; self->_eventQueued = NO; }
        if (hard) [self handleMediaChange]; else [self handleMetadataChange];
    });
}
- (void)handleMetadataChange {
    if (!_timer || ![self refreshPresentation]) return;
    NSString *reason = nil, *direct = MSMusicResolvePlayer(&reason);
    BOOL verified = _playing && !_awaitingFreshInfo && _track && !_lyricsAwaitingFreshInfo;
    if (!MSMusicMetadataLease(verified, direct.length && [direct isEqualToString:_source], MSMusicNow(), _validAt)) {
        [self handleMediaChange]; return;
    }
    // Do not invalidate an in-flight sandwich for redundant metadata hints.
    // Keep only the existing <=1s evidence, never refresh its timestamp here.
    _metadataRevalidate = YES;
    _pollAt = fmin(_pollAt, fmax(_readAt + 0.5, MSMusicNow()));
    [self identityEvidence:@"metadata_revalidate"];
    [self tick];
}
- (void)handleMediaChange {
    if (!_timer) return;
    ++_readGeneration;
    _pollAt = fmax(_readAt + 0.5, MSMusicNow() + 0.15);
    [self beginCandidate:@"identity_revalidate"];
    NSString *reason = nil, *source = MSMusicResolvePlayer(&reason);
    _playerDetail = reason;
    _playerIdentified = source.length > 0;
    // Notifications may precede the PID callback. Keep only a candidate; tick cannot
    // publish a lyric or report playing until fresh metadata AND PID are verified.
    BOOL awaitPID = !source && MSMusicPID && MSMusicMissingSource(reason);
    if (!awaitPID && (!source || ![_source isEqualToString:source])) {
        [self discardCandidate:@"player_changed"];
        _source = [source copy];
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
    if (_candidateUntil > 0. && !MSMusicCandidateAlive(now, _candidateUntil))
        [self discardCandidate:@"candidate_expired"];
    if (_metadataRevalidate && !MSMusicMetadataLease(YES, YES, now, _validAt))
        [self beginCandidate:@"metadata_lease_expired"];
    if (_reading && !_readTimedOut && now - _readAt > 3.) {
        MSMusicEvidence(@"sample", @"failed", _readGeneration, @"media_callback_timeout", NO, NO, NO, YES);
        // Fail closed, never launch replacements for a callback that may never arrive.
        _readTimedOut = YES; ++_readGeneration; ++_trackGeneration;
        [self discardCandidate:@"media_callback_timeout"];
        _validAt = 0;
    }
    if (!_reading && now >= _pollAt) [self pollAt:now];
    BOOL current = _validAt > 0 && now >= _validAt - 1 && now - _validAt <= 6;
    BOOL playing = current && _playing && !_awaitingFreshInfo;
    if (!current && _playing) _stateReason = @"music_stale";
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
    NSString *reason = nil, *direct = MSMusicResolvePlayer(&reason);
    BOOL identityOK = [player isEqualToString:direct] || (_pidRead && !direct && MSMusicMissingSource(reason));
    if (!_timer || !_allowed || ![self refreshPresentation] ||
        generation != _readGeneration || MSMusicNow() - _readAt > 3. || !identityOK) {
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
    NSString *playerReason = nil;
    NSString *player = MSMusicResolvePlayer(&playerReason);
    _pidRead = 0;
    if (player.length && _source.length && ![_source isEqualToString:player]) {
        // This is positive switch evidence, not a soft metadata hint. Revoke A
        // before starting B's first read; do not publish B until it is verified.
        [self discardCandidate:@"player_changed"];
        _source = nil; _playerIdentified = NO;
        [self publishLine:nil playing:NO force:NO];
    }
    BOOL fallback = !player && MSMusicMissingSource(playerReason) && MSMusicPID;
    if (fallback) {
        // No cached PID can admit the next sample. Both fresh PID callbacks
        // are required even when the previous sample also used fallback.
        [self beginCandidate:@"identity_unavailable"];
        _playerIdentified = NO;
        [self publishLine:nil playing:NO force:NO];
    }
    if (!fallback || !_playerIdentified) _playerDetail = playerReason;
    if (!player && !fallback) {
        [self rejectPlayer:(!MSMusicPID && MSMusicMissingSource(playerReason)) ? @"pid_api_unavailable" : playerReason at:now];
        return;
    }
    _reading = YES; _readTimedOut = NO; _readAt = now; _readStage = fallback ? 0 : 1;
    NSUInteger request = ++_readGeneration, ticket = ++_readTicket;
    if (!fallback) { [self samplePlayer:player ticket:ticket request:request]; return; }
    // A PID is never cached between samples. Verify it again after the metadata sandwich.
    __weak typeof(self) weakSelf = self;
    MSMusicPID(dispatch_get_main_queue(), ^(int pid) { dispatch_async(dispatch_get_main_queue(), ^{
        typeof(self) self = weakSelf;
        if (!self || !self->_reading || ticket != self->_readTicket || self->_readStage != 0) return;
        if (!self->_timer || ![self refreshPresentation] || request != self->_readGeneration || MSMusicNow()-self->_readAt > 3.) {
            self->_reading = NO; [self handleMediaChange]; return;
        }
        NSString *reason = nil, *resolved = MSMusicPIDPlayer(pid, &reason);
        if (!resolved) { self->_reading = NO; [self rejectPlayer:reason at:MSMusicNow()]; [self tick]; return; }
        self->_pidRead = pid;
        if (![self acceptRead:ticket generation:request stage:0 player:resolved]) return;
        self->_playerDetail = [resolved isEqual:@"com.netease.cloudmusic"] ? @"netease_pid_selected" : @"supported_pid_selected";
        [self samplePlayer:resolved ticket:ticket request:request];
    }); });
}
- (void)rejectPlayer:(NSString *)reason at:(NSTimeInterval)now {
    _playerDetail = reason ?: @"no_active_player";
    _lyricsDetail = nil; _sourceFromPID = NO;
    MSMusicEvidence(@"sample", @"skipped", _readGeneration, _playerDetail, NO, NO, NO, (_lyrics || _motion));
    _playerIdentified = NO; _progressAvailable = NO; _lyricsRequestFinished = NO;
    BOOL transient = [reason isEqualToString:@"player_pid_nonpositive"];
    if (transient && _track) {
        ++_trackGeneration; ++_identityEpoch; [_client cancel]; _fetching = NO;
        [self beginCandidate:@"identity_unavailable"];
        _pollAt = fmin(_pollAt, now + 0.5);
    } else {
        [self discardCandidate:transient ? @"identity_unavailable" : @"player_rejected"];
        _source = nil;
    }
    // PID0 is unknown, NOT a confirmed stop and NOT a fresh sample.
    _playing = NO; _awaitingFreshInfo = YES;
    [self publishLine:nil playing:NO force:NO];
}
- (void)samplePlayer:(NSString *)player ticket:(NSUInteger)ticket request:(NSUInteger)request {
    MSMusicEvidence(@"request", @"pending", request, _playerDetail, NO, NO, NO, (_lyrics || _motion));
    __weak typeof(self) weakSelf = self;
    [self readInfo:^(NSDictionary *first) {
        typeof(self) self = weakSelf;
        if (!self || ![self acceptRead:ticket generation:request stage:1 player:player]) return;
        MiniSightLyricsTrack *firstTrack = MSMusicTrack(first);
        BOOL firstConflict = self->_track && (firstTrack
            ? !MSMusicTracksCompatible(self->_track, self->_identifier, firstTrack, MSMusicIdentifier(first), self->_timeline != nil)
            : MSMusicPartialConflicts(first, self->_track, self->_identifier));
        if (firstConflict) {
            [self discardCandidate:@"metadata_conflict"];
            [self publishLine:nil playing:NO force:NO];
        }
        MSMusicIsPlaying(dispatch_get_main_queue(), ^(Boolean playing) {
            dispatch_async(dispatch_get_main_queue(), ^{
                typeof(self) self = weakSelf;
                if (!self || ![self acceptRead:ticket generation:request stage:2 player:player]) return;
                if (playing != 1) [self beginPause];
                [self readInfo:^(NSDictionary *last) {
                    typeof(self) self = weakSelf;
                    if (!self || ![self acceptRead:ticket generation:request stage:3 player:player]) return;
                    BOOL compatible = MSMusicTrackIdentityCompatible(first, last, player);
                    if (!compatible) {
                        self->_reading = NO;
                        [self discardCandidate:@"metadata_conflict"];
                        [self handleMediaChange]; return;
                    }
                    // A stable player may fill metadata between reads. Use the
                    // complete side if present, while preserving strict conflict checks.
                    NSDictionary *resolved = MSMusicResolvedInfo(first, last, player);
                    if (!self->_pidRead) { self->_reading = NO; [self applyInfo:resolved playing:playing player:player]; return; }
                    MSMusicPID(dispatch_get_main_queue(), ^(int pid) { dispatch_async(dispatch_get_main_queue(), ^{
                        typeof(self) self = weakSelf;
                        if (!self || ![self acceptRead:ticket generation:request stage:4 player:player]) return;
                        self->_reading = NO;
                        NSString *pidReason = nil, *lastPlayer = MSMusicPIDPlayer(pid, &pidReason);
                        if (!MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])) {
                            [self rejectPlayer:lastPlayer ? @"pid_changed_during_sample" : pidReason at:MSMusicNow()];
                            [self tick]; return;
                        }
                        // Previous PID is a rejection fence only, NEVER used
                        // as evidence for this sample. Both callbacks above are fresh.
                        if (self->_verifiedPID > 0 && self->_verifiedPID != pid) {
                            [self discardCandidate:@"player_instance_changed"];
                            [self publishLine:nil playing:NO force:NO];
                        }
                        [self applyInfo:resolved playing:playing player:player];
                    }); });
                }];
            });
        });
    }];
}
- (void)applyInfo:(NSDictionary *)info playing:(Boolean)playing player:(NSString *)player {
            __weak typeof(self) weakSelf = self;
            NSTimeInterval received = MSMusicNow();
            if (self->_candidateUntil > 0. && !MSMusicCandidateAlive(received, self->_candidateUntil))
                [self discardCandidate:@"candidate_expired"];
            BOOL usedCandidate = self->_candidateUntil > 0. && self->_timeline != nil;
            if (playing != 1 && ![self->_stateReason isEqualToString:@"confirmed_pause"])
                [self beginPause];
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
            BOOL hasMetadata = ([title isKindOfClass:NSString.class] && title.length) ||
                ([artist isKindOfClass:NSString.class] && artist.length) || isfinite(duration) || identifier.length;
            if (playing != 1 && !hasMetadata)
                [self discardCandidate:@"confirmed_stop"];
            BOOL sourceChanged = self->_source.length && ![self->_source isEqualToString:player];
            BOOL conflictingPartial = !track && MSMusicPartialConflicts(info, self->_track, self->_identifier);
            BOOL conflictingIdentifier = identifier.length && self->_identifier.length &&
                ![identifier isEqualToString:self->_identifier] &&
                (!track || !self->_track || ![track.cacheKey isEqualToString:self->_track.cacheKey]);
            BOOL changedTrack = sourceChanged || conflictingIdentifier ||
                (track && self->_track && !MSMusicTracksCompatible(self->_track, self->_identifier,
                    track, identifier, self->_timeline != nil)) || conflictingPartial;
            NSString *identity = MSMusicIdentity(info, player);
            if (changedTrack) {
                [self discardCandidate:@"track_changed"];
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
            self->_sourceFromPID = self->_pidRead > 0;
            // A direct sample has no PID evidence: retain a positive rejection
            // fence, but never use it to admit a sample or avoid fresh PID reads.
            if (self->_pidRead > 0 && self->_track) self->_verifiedPID = self->_pidRead;
            self->_metadataRevalidate = NO;
            // Only complete, conflict-checked identity consumes the absolute
            // candidate deadline. Partial success cannot renew hidden lyrics.
            if (track) self->_candidateUntil = 0.;
            self->_source = player; self->_validAt = received; self->_awaitingFreshInfo = NO;
            // Missing metadata can keep motion alive, but never reuse a lyric line.
            self->_lyricsAwaitingFreshInfo = !track;
            // A retained timeline always uses its ORIGINAL track as the duration
            // and progress anchor; samples must never slide it by repeated +0.8s.
            MiniSightLyricsTrack *progressTrack = track && self->_timeline ? self->_track : track;
            BOOL timing = !track || (isfinite(elapsed) && elapsed >= 0 && elapsed <= progressTrack.duration &&
                // Timestamp is the elapsed-time reference, not the date of this reply.
                // Many players keep it unchanged while the track plays normally.
                isfinite(age) && age >= -3. && age <= progressTrack.duration + 3. &&
                elapsed + fmax(0., age) * rate <= progressTrack.duration + .1);
            self->_playing = playing == 1 && [info isKindOfClass:NSDictionary.class] &&
                isfinite(rate) && rate > 0 && rate <= 4 && timing;
            self->_playerIdentified = player.length > 0;
            self->_progressAvailable = MSMusicProgressValid(info, progressTrack);
            NSString *sample = !track ? @"metadata_missing" : !self->_progressAvailable ? @"progress_missing"
                : !timing ? @"progress_invalid" : !self->_playing ? @"not_playing" : @"track_valid";
            self->_stateReason = playing != 1 ? (hasMetadata ? @"confirmed_pause" : @"confirmed_stop") : sample;
            if (usedCandidate && track && self->_timeline && self->_playing)
                [self identityEvidence:@"candidate_revalidated"];
            MSMusicEvidence(@"sample", @"ok", self->_trackGeneration, sample,
                track != nil, self->_progressAvailable, NO, (self->_lyrics || self->_motion));
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
                [self->_client fetchTrack:self->_track result:^(MiniSightLyricsTimeline *timeline, NSString *detail) {
                    dispatch_async(dispatch_get_main_queue(), ^{
                        typeof(self) self = weakSelf;
                        if (!self || !self->_allowed || !self->_lyrics || generation != self->_trackGeneration) return;
                        self->_fetching = NO; self->_lyricsRequestFinished = YES; self->_timeline = timeline; self->_lyricsDetail = detail;
                        MSMusicEvidence(@"finish", timeline ? @"ok" : @"skipped", generation,
                            detail, YES, timeline != nil, NO, YES);
                        NSString *sourceReason = nil, *direct = MSMusicResolvePlayer(&sourceReason);
                        if (![player isEqualToString:direct] && !(MSMusicPID && !direct && MSMusicMissingSource(sourceReason))) {
                            [self handleMediaChange]; return;
                        }
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
    NSString *source = _allowed && _playerIdentified ? (_source ?: @"") : @"";
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
        @"playerDetail": _playerDetail ?: @"not_applicable",
        @"lyricsDetail": (_lyrics && _lyricsRequestFinished ? _lyricsDetail : nil) ?: @"not_applicable",
        @"player": [NSString stringWithUTF8String:stages.player] ?: @"",
        @"metadata": [NSString stringWithUTF8String:stages.metadata] ?: @"",
        @"progress": [NSString stringWithUTF8String:stages.progress] ?: @"",
        @"lyrics": [NSString stringWithUTF8String:stages.lyrics] ?: @""};
    BOOL motionActive = _allowed && _motion && playing;
    BOOL wasMotionActive = [_snapshot[@"allowed"] boolValue] && [_snapshot[@"motionEnabled"] boolValue] &&
        [_snapshot[@"playing"] boolValue];
    NSUInteger nextRhythmGeneration = (NSUInteger)MSMusicNextRhythmGeneration(_rhythmGeneration,
        motionActive, wasMotionActive, [_snapshot[@"source"] isEqual:source]);
    double motionPosition = self.motionPosition;
    double sampleAge = MSMusicNow() - _validAt;
    BOOL measuredProgress = motionActive && _progressAvailable && !_awaitingFreshInfo &&
        _validAt > 0. && sampleAge >= 0. && sampleAge <= 6. &&
        isfinite(_elapsed) && _elapsed >= 0. && isfinite(_rate) && _rate > 0. && _rate <= 4. &&
        isfinite(motionPosition) && motionPosition >= 0. && motionPosition <= 3600.;
    BOOL changed = nextRhythmGeneration != _rhythmGeneration ||
        [_snapshot[@"progressAvailable"] boolValue] != measuredProgress ||
        ![_snapshot[@"motionRate"] isEqual:@(_rate)] ||
        ![_snapshot[@"line"] isEqual:safeLine] || [_snapshot[@"playing"] boolValue] != playing ||
        ![_snapshot[@"source"] isEqual:source] || [_snapshot[@"lyricsEnabled"] boolValue] != (_allowed && _lyrics) ||
        [_snapshot[@"motionEnabled"] boolValue] != (_allowed && _motion) ||
        ![_snapshot[@"diagnostics"] isEqual:diagnostics] ||
        [_snapshot[@"allowed"] boolValue] != _allowed || ![_snapshot[@"reason"] isEqual:reason] ||
        ![_snapshot[@"stopReason"] isEqual:stopReason];
    if (!MSMusicPublishDue(changed, force, MSMusicNow(), _writeAt)) return;
    _rhythmGeneration = nextRhythmGeneration;
    if ([_snapshot[@"playing"] boolValue] != playing) {
        ++_playbackSequence;
        [self identityEvidence:playing ? @"playing_confirmed" : (_stateReason ?: @"music_stale")];
    }
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
        @"motionTime": @(motionPosition), @"progressAvailable": @((BOOL)measuredProgress),
        @"motionRate": @(isfinite(_rate) ? _rate : 0.),
        @"rhythmGeneration": @(motionActive ? _rhythmGeneration : 0),
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
