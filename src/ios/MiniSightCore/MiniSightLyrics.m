#import "MiniSightLyrics.h"
#import <math.h>
#import <float.h>
#import <stdlib.h>
#import <stdbool.h>
#import <stddef.h>
#import <stdint.h>
#import <dispatch/dispatch.h>

NS_ASSUME_NONNULL_BEGIN

static const NSUInteger MSLyricsMaxBytes = 1024 * 1024;
static const NSTimeInterval MSLyricsMaxDisplay = 12.0;

// BEGIN LYRICS PORTABLE POLICY
// Compiled verbatim on the host; Foundation parsing/transport are tested separately.
static bool MSLyricsDurationOK(double value) {
    return isfinite(value) && value >= 1.0 && value <= 3600.0;
}
typedef double (*MSLyricsMarkerTimeFn)(const void *, size_t);
static size_t MSLyricsMarkerIndex(double time, double duration, size_t count,
                                  const void *context, MSLyricsMarkerTimeFn timeAt) {
    if (!isfinite(time) || time < 0.0 || !MSLyricsDurationOK(duration) ||
        time >= duration || !count || count > 4096 || !context || !timeAt) return SIZE_MAX;
    size_t lo = 0, hi = count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (timeAt(context, mid) <= time) lo = mid + 1; else hi = mid;
    }
    return lo ? lo - 1 : SIZE_MAX;
}
static size_t MSLyricsClosestCandidate(const double *durations, const size_t *equivalent,
                                      size_t count, double duration) {
    if (!durations || !equivalent || !count || count > 20 || !MSLyricsDurationOK(duration)) return SIZE_MAX;
    size_t best = SIZE_MAX; double bestDelta = DBL_MAX;
    for (size_t i = 0; i < count; ++i) {
        double delta = fabs(durations[i] - duration);
        if (!MSLyricsDurationOK(durations[i]) || delta > 2.0) return SIZE_MAX;
        if (delta < bestDelta) { best = i; bestDelta = delta; }
    }
    // Only ambiguity at the GLOBAL nearest distance matters. Do not reject a
    // farther tie before seeing a later, unique closer candidate.
    for (size_t i = 0; i < count; ++i) {
        if (i != best && fabs(fabs(durations[i] - duration) - bestDelta) < 0.000001 &&
            equivalent[i] != equivalent[best]) return SIZE_MAX;
    }
    return best;
}
static bool MSLyricsShouldSearch(bool failed, long status, bool search, bool attempted) {
    return !failed && status == 404 && !search && !attempted;
}
static bool MSLyricsShouldCache(bool failed, bool timeline, bool search, long status, bool rejected) {
    return !failed && (timeline || (search && (status == 404 || (status == 200 && !rejected))));
}
static bool MSLyricsDispatchReady(double now, double deadline) {
    return isfinite(now) && isfinite(deadline) && now < deadline;
}
// END LYRICS PORTABLE POLICY

static NSRegularExpression * _Nullable MSLyricsRegex(NSString *pattern) {
    return [NSRegularExpression regularExpressionWithPattern:pattern options:0 error:NULL];
}

@interface MiniSightLyricLine ()
- (instancetype)initWithTime:(NSTimeInterval)time text:(NSString *)text;
@end
@implementation MiniSightLyricLine
- (instancetype)initWithTime:(NSTimeInterval)time text:(NSString *)text {
    if ((self = [super init])) { _time = time; _text = [text copy]; }
    return self;
}
@end

static double MSLyricsMarkerTime(const void *context, size_t index) {
    NSArray<MiniSightLyricLine *> *lines = (__bridge NSArray<MiniSightLyricLine *> *)context;
    return lines[index].time;
}

@interface MiniSightLyricsTimeline ()
@property(nonatomic) NSTimeInterval duration;
- (instancetype)initWithLines:(NSArray<MiniSightLyricLine *> *)lines duration:(NSTimeInterval)duration;
@end
@implementation MiniSightLyricsTimeline
- (instancetype)initWithLines:(NSArray<MiniSightLyricLine *> *)lines duration:(NSTimeInterval)duration {
    if ((self = [super init])) { _lines = [lines copy]; _duration = duration; }
    return self;
}
+ (nullable instancetype)timelineWithLRC:(NSString *)lrc duration:(NSTimeInterval)duration {
    if (!MSLyricsDurationOK(duration) || ![lrc isKindOfClass:NSString.class] ||
        !lrc.length || lrc.length > MSLyricsMaxBytes || ![lrc canBeConvertedToEncoding:NSUTF8StringEncoding] ||
        [lrc lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > MSLyricsMaxBytes) return nil;
    if ([lrc hasPrefix:@"\uFEFF"]) lrc = [lrc substringFromIndex:1];
    NSArray<NSString *> *rows = [lrc componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet];
    if (rows.count > 8192) return nil;
    static NSRegularExpression *stamp, *offset, *metadata;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        stamp = MSLyricsRegex(@"^\\[([0-9]{1,3}):([0-5][0-9])(?:[.:]([0-9]{1,3}))?\\]");
        offset = MSLyricsRegex(@"^\\[offset:([+-]?[0-9]{1,7})\\]$");
        metadata = MSLyricsRegex(@"^\\[[A-Za-z][A-Za-z0-9_-]*:[^\\]\\r\\n]*\\]$");
    });
    NSMutableArray<MiniSightLyricLine *> *raw = [NSMutableArray array];
    NSTimeInterval shift = 0;
    for (NSString *row in rows) {
        NSString *line = [row stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        if (!line.length) continue;
        if (line.length > 2048) return nil;
        NSString *lower = line.lowercaseString;
        if ([lower hasPrefix:@"[offset:"]) {
            NSTextCheckingResult *match = [offset firstMatchInString:lower options:0 range:NSMakeRange(0, lower.length)];
            if (!match) return nil;
            shift = [[lower substringWithRange:[match rangeAtIndex:1]] doubleValue] / 1000.0;
            if (!isfinite(shift) || fabs(shift) > 600.0) return nil;
            continue;
        }
        if ([metadata numberOfMatchesInString:line options:0 range:NSMakeRange(0, line.length)]) continue;
        NSMutableArray<NSNumber *> *times = [NSMutableArray array];
        NSUInteger cursor = 0;
        while (cursor < line.length) {
            NSString *tail = [line substringFromIndex:cursor];
            NSTextCheckingResult *match = [stamp firstMatchInString:tail options:0 range:NSMakeRange(0, tail.length)];
            if (!match) {
                // Do not silently display malformed secondary numeric timestamp tags.
                if ([tail hasPrefix:@"["] && tail.length > 1 &&
                    [[NSCharacterSet characterSetWithCharactersInString:@"0123456789+-"] characterIsMember:[tail characterAtIndex:1]]) return nil;
                break;
            }
            double time = [[tail substringWithRange:[match rangeAtIndex:1]] doubleValue] * 60.0 +
                          [[tail substringWithRange:[match rangeAtIndex:2]] doubleValue];
            NSRange fraction = [match rangeAtIndex:3];
            if (fraction.location != NSNotFound) time += [[tail substringWithRange:fraction] doubleValue] / pow(10.0, fraction.length);
            if (!isfinite(time) || time > 3600.0) return nil;
            [times addObject:@(time)];
            cursor += match.range.length;
            if (times.count + raw.count > 4096) return nil;
        }
        if (!times.count) return nil;
        NSString *text = [[line substringFromIndex:cursor] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        if (text.length > 1024 || [text rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) return nil;
        for (NSNumber *time in times) [raw addObject:[[MiniSightLyricLine alloc] initWithTime:time.doubleValue text:text]];
    }
    NSMutableDictionary<NSNumber *, MiniSightLyricLine *> *unique = [NSMutableDictionary dictionary];
    for (MiniSightLyricLine *line in raw) {
        NSTimeInterval time = MAX(0.0, line.time + shift);
        if (time >= duration) continue;
        // Last source marker wins ties, including explicit blanks and clamped negatives.
        unique[@(time)] = [[MiniSightLyricLine alloc] initWithTime:time text:line.text];
    }
    if (!unique.count) return nil;
    NSMutableArray *lines = [NSMutableArray arrayWithCapacity:unique.count];
    for (NSNumber *time in [[unique allKeys] sortedArrayUsingSelector:@selector(compare:)]) [lines addObject:unique[time]];
    return [[self alloc] initWithLines:lines duration:duration];
}
- (nullable NSString *)lineAtTime:(NSTimeInterval)time {
    size_t index = MSLyricsMarkerIndex(time, _duration, _lines.count,
        (__bridge const void *)_lines, MSLyricsMarkerTime);
    if (index == SIZE_MAX) return nil;
    MiniSightLyricLine *line = _lines[index];
    if (!line.text.length) return nil;
    // A line only stays on screen for a bounded window; a long instrumental gap
    // must clear the bubble instead of holding the previous line forever.
    if (time - line.time >= MSLyricsMaxDisplay) return nil;
    return line.text;
}
@end

@implementation MiniSightLyricsTrack
- (nullable instancetype)initWithTitle:(NSString *)title artist:(NSString *)artist duration:(NSTimeInterval)duration {
    NSString *normalizedTitle = MSLyricsNormalize(title), *normalizedArtist = MSLyricsNormalize(artist);
    if (!normalizedTitle || !normalizedArtist || !MSLyricsDurationOK(duration)) return nil;
    if ((self = [super init])) {
        _title = [normalizedTitle copy]; _artist = [normalizedArtist copy]; _duration = duration;
        // Length-prefix prevents separator collisions; do not round distinct durations.
        _cacheKey = [NSString stringWithFormat:@"%lu:%@%lu:%@/%.17g", (unsigned long)_title.length,
                     _title, (unsigned long)_artist.length, _artist, duration];
    }
    return self;
}
@end

static BOOL MSLyricsAllowedURL(NSURL * _Nullable url, NSString *path) {
    return [url.scheme.lowercaseString isEqualToString:@"https"] &&
           [url.host.lowercaseString isEqualToString:@"lrclib.net"] &&
           [url.path isEqualToString:path] && (!url.port || url.port.integerValue == 443) &&
           !url.user.length && !url.password.length && !url.fragment.length;
}

@interface MSLyricsCacheEntry : NSObject
@property(nonatomic, strong, nullable) MiniSightLyricsTimeline *timeline;
@property(nonatomic, copy) NSString *reason;
@property(nonatomic) NSTimeInterval expires;
@end
@implementation MSLyricsCacheEntry
@end

@interface MSLyricsSessionDelegate : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, weak, nullable) MiniSightLyricsClient *owner;
@end

@interface MiniSightLyricsClient ()
+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason;
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason;
@property(nonatomic, strong) NSURLSession *session;
@property(nonatomic, strong) NSCache<NSString *, MSLyricsCacheEntry *> *cache;
@property(nonatomic, strong, nullable) NSURLSessionDataTask *task;
@property(nonatomic, strong, nullable) NSMutableData *body;
@property(nonatomic, strong, nullable) NSHTTPURLResponse *response;
@property(nonatomic, strong, nullable) MiniSightLyricsTrack *track;
@property(nonatomic, copy, nullable) MiniSightLyricsResult completion;
@property(nonatomic) BOOL searchTask;
@property(nonatomic) BOOL searchAttempted;
@property(nonatomic) BOOL searchPending;
@property(nonatomic) BOOL requestPending;
@property(atomic) NSUInteger generation; // Ticket invalidation is immediate, even off-main.
@property(nonatomic) NSUInteger activeGeneration;
@property(nonatomic) NSUInteger rateAttempt;
@property(nonatomic) NSTimeInterval notBefore;
@property(nonatomic) NSTimeInterval lastRequestAt;
@property(nonatomic) NSTimeInterval deadline;
- (void)startTrack:(MiniSightLyricsTrack *)track generation:(NSUInteger)generation completion:(MiniSightLyricsResult)completion;
- (void)startSearchForGeneration:(NSUInteger)generation;
- (void)sendGetForTrack:(MiniSightLyricsTrack *)track;
- (void)sendSearchForTrack:(MiniSightLyricsTrack *)track;
- (void)receivedResponse:(NSURLResponse *)response task:(NSURLSessionDataTask *)task completion:(void (^)(NSURLSessionResponseDisposition))completion;
- (void)receivedData:(NSData *)data task:(NSURLSessionDataTask *)task;
- (void)finishedTask:(NSURLSessionTask *)task error:(nullable NSError *)error;
@end

@implementation MiniSightLyricsClient
- (instancetype)init { return [self initWithProtocolClasses:@[]]; }
- (instancetype)initWithProtocolClasses:(NSArray<Class> *)protocolClasses {
    if ((self = [super init])) {
        _cache = [[NSCache alloc] init];
        _cache.countLimit = 16;
        _cache.totalCostLimit = 4 * MSLyricsMaxBytes;
        NSURLSessionConfiguration *config = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        config.timeoutIntervalForRequest = 12.0;
        config.timeoutIntervalForResource = 15.0;
        config.HTTPMaximumConnectionsPerHost = 1;
        config.HTTPCookieStorage = nil;
        config.HTTPShouldSetCookies = NO;
        config.HTTPCookieAcceptPolicy = NSHTTPCookieAcceptPolicyNever;
        config.URLCredentialStorage = nil;
        config.URLCache = nil;
        config.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
        if (protocolClasses.count) config.protocolClasses = [protocolClasses copy];
        MSLyricsSessionDelegate *delegate = [[MSLyricsSessionDelegate alloc] init];
        delegate.owner = self; // NSURLSession retains delegate, never the client.
        _session = [NSURLSession sessionWithConfiguration:config delegate:delegate delegateQueue:NSOperationQueue.mainQueue];
    }
    return self;
}
- (void)dealloc { [_session invalidateAndCancel]; }

+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track {
    NSString *reason;
    return [self timelineForResponseData:data response:response track:track reason:&reason];
}
+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason {
    *reason = @"lyrics_response_rejected";
    if (![track isKindOfClass:MiniSightLyricsTrack.class] || ![response isKindOfClass:NSHTTPURLResponse.class] ||
        response.statusCode != 200 || !MSLyricsAllowedURL(response.URL, @"/api/get") ||
        ![response.MIMEType.lowercaseString isEqualToString:@"application/json"] ||
        ![data isKindOfClass:NSData.class] || !data.length || data.length > MSLyricsMaxBytes) return nil;
    id record = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if (![record isKindOfClass:NSDictionary.class]) return nil;
    NSString *title = MSLyricsNormalize(record[@"trackName"]), *artist = MSLyricsNormalize(record[@"artistName"]);
    id duration = record[@"duration"], instrumental = record[@"instrumental"], lrc = record[@"syncedLyrics"];
    if (!title.length || !artist.length || ![duration isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)duration) == CFBooleanGetTypeID() ||
        !MSLyricsDurationOK([duration doubleValue]) ||
        ![instrumental isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)instrumental) != CFBooleanGetTypeID()) return nil;
    if (![title isEqualToString:track.title] || ![artist isEqualToString:track.artist] || fabs([duration doubleValue] - track.duration) > 2.0) {
        *reason = @"lyrics_track_mismatch"; return nil;
    }
    if ([instrumental boolValue]) { *reason = @"lyrics_instrumental"; return nil; }
    if (!lrc || lrc == NSNull.null || ([lrc isKindOfClass:NSString.class] && ![lrc length])) { *reason = @"no_synced_lyrics"; return nil; }
    if (![lrc isKindOfClass:NSString.class]) return nil;
    MiniSightLyricsTimeline *timeline = [MiniSightLyricsTimeline timelineWithLRC:lrc duration:track.duration];
    *reason = timeline ? @"lyrics_timeline" : @"lyrics_invalid_lrc";
    return timeline;
}
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason {
    *reason = @"lyrics_not_found";
    if (![track isKindOfClass:MiniSightLyricsTrack.class] || ![response isKindOfClass:NSHTTPURLResponse.class] ||
        response.statusCode != 200 || !MSLyricsAllowedURL(response.URL, @"/api/search") ||
        ![response.MIMEType.lowercaseString isEqualToString:@"application/json"] ||
        ![data isKindOfClass:NSData.class] || !data.length || data.length > MSLyricsMaxBytes) {
        *reason = @"lyrics_response_rejected"; return nil;
    }
    id payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if (![payload isKindOfClass:NSArray.class] || [payload count] > 20) {
        *reason = @"lyrics_response_rejected"; return nil;
    }
    NSMutableArray<NSDictionary *> *matches = [NSMutableArray array];
    BOOL sawInstrumental = NO, sawUnsynced = NO, sawInvalidLRC = NO;
    for (id value in (NSArray *)payload) {
        if (![value isKindOfClass:NSDictionary.class]) { *reason = @"lyrics_response_rejected"; return nil; }
        NSDictionary *record = value;
        NSString *title = MSLyricsNormalize(record[@"trackName"]), *artist = MSLyricsNormalize(record[@"artistName"]);
        id duration = record[@"duration"], instrumental = record[@"instrumental"], lrc = record[@"syncedLyrics"];
        if (!title.length || !artist.length || ![duration isKindOfClass:NSNumber.class] ||
            CFGetTypeID((__bridge CFTypeRef)duration) == CFBooleanGetTypeID() || !MSLyricsDurationOK([duration doubleValue]) ||
            ![instrumental isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)instrumental) != CFBooleanGetTypeID() ||
            (! [lrc isKindOfClass:NSString.class] && lrc != NSNull.null)) {
            *reason = @"lyrics_response_rejected"; return nil;
        }
        if (![title isEqualToString:track.title] || ![artist isEqualToString:track.artist] ||
            fabs([duration doubleValue] - track.duration) > 2.0) continue;
        if ([instrumental boolValue]) { sawInstrumental = YES; continue; }
        if (lrc == NSNull.null || ![lrc length]) { sawUnsynced = YES; continue; }
        MiniSightLyricsTimeline *candidateTimeline = [MiniSightLyricsTimeline timelineWithLRC:lrc duration:track.duration];
        if (!candidateTimeline) { sawInvalidLRC = YES; continue; }
        [matches addObject:@{@"duration": duration, @"syncedLyrics": lrc, @"timeline": candidateTimeline}];
    }
    if (!matches.count) {
        *reason = sawInvalidLRC ? @"lyrics_invalid_lrc" : sawUnsynced ? @"no_synced_lyrics"
            : sawInstrumental ? @"lyrics_instrumental" : @"lyrics_not_found";
        return nil;
    }
    double durations[20]; size_t equivalent[20];
    for (NSUInteger i = 0; i < matches.count; ++i) {
        durations[i] = [matches[i][@"duration"] doubleValue]; equivalent[i] = i;
        for (NSUInteger j = 0; j < i; ++j) {
            if ([matches[i][@"duration"] isEqual:matches[j][@"duration"]] &&
                [matches[i][@"syncedLyrics"] isEqual:matches[j][@"syncedLyrics"]]) {
                equivalent[i] = equivalent[j]; break;
            }
        }
    }
    size_t best = MSLyricsClosestCandidate(durations, equivalent, matches.count, track.duration);
    if (best == SIZE_MAX) { *reason = @"lyrics_response_rejected"; return nil; }
    *reason = @"lyrics_timeline";
    return matches[best][@"timeline"];
}
+ (NSTimeInterval)retryDelayForResponse:(NSHTTPURLResponse *)response now:(NSDate *)now attempt:(NSUInteger)attempt {
    if (response.statusCode != 429 && response.statusCode != 503) return 0;
    NSTimeInterval fallback = MIN(300.0, 30.0 * pow(2.0, MIN(attempt, (NSUInteger)4)));
    NSString *header = nil;
    for (id key in response.allHeaderFields) {
        if ([[key description] caseInsensitiveCompare:@"Retry-After"] == NSOrderedSame) {
            id value = response.allHeaderFields[key];
            if ([value isKindOfClass:NSString.class]) header = [value stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        }
    }
    if (!header.length) return fallback;
    if ([header rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789"] invertedSet]].location == NSNotFound) {
        double seconds = header.doubleValue;
        return isfinite(seconds) ? MAX(fallback, seconds) : DBL_MAX;
    }
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    formatter.dateFormat = @"EEE, dd MMM yyyy HH:mm:ss z";
    formatter.lenient = NO;
    NSDate *date = [formatter dateFromString:header];
    return date ? MAX(fallback, [date timeIntervalSinceDate:now]) : fallback;
}
- (void)deliver:(MiniSightLyricsTimeline * _Nullable)timeline reason:(NSString *)reason generation:(NSUInteger)generation completion:(MiniSightLyricsResult _Nullable)completion {
    __weak typeof(self) weakSelf = self;
    dispatch_async(dispatch_get_main_queue(), ^{
        MiniSightLyricsClient *owner = weakSelf;
        if (owner && owner.generation == generation && completion) completion(timeline, reason);
    });
}
- (NSUInteger)nextGeneration {
    @synchronized (self) {
        NSUInteger generation = self.generation + 1;
        self.generation = generation;
        return generation;
    }
}
- (void)clearActive {
    [_task cancel];
    _task = nil; _body = nil; _response = nil; _track = nil; _completion = nil;
    _searchTask = NO; _searchAttempted = NO; _searchPending = NO; _requestPending = NO;
}
- (void)cancel {
    NSUInteger generation = [self nextGeneration];
    void (^clear)(void) = ^{ if (self.generation == generation) [self clearActive]; };
    if (NSThread.isMainThread) clear(); else dispatch_async(dispatch_get_main_queue(), clear);
}
- (void)fetchTrack:(MiniSightLyricsTrack *)track completion:(MiniSightLyricsCompletion)completion {
    [self fetchTrack:track result:^(MiniSightLyricsTimeline *timeline, NSString *reason) {
        if (completion) completion(timeline);
    }];
}
- (void)fetchTrack:(MiniSightLyricsTrack *)track result:(MiniSightLyricsResult)completion {
    NSUInteger generation = [self nextGeneration];
    void (^start)(void) = ^{
        if (self.generation == generation) [self startTrack:track generation:generation completion:completion];
    };
    if (NSThread.isMainThread) start(); else dispatch_async(dispatch_get_main_queue(), start);
}
- (void)startTrack:(MiniSightLyricsTrack *)track generation:(NSUInteger)generation completion:(MiniSightLyricsResult)completion {
    [self clearActive];
    _activeGeneration = generation;
    _deadline = NSProcessInfo.processInfo.systemUptime + 15.0;
    if (![track isKindOfClass:MiniSightLyricsTrack.class]) {
        [self deliver:nil reason:@"metadata_missing" generation:generation completion:completion];
        return;
    }
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    MSLyricsCacheEntry *entry = [_cache objectForKey:track.cacheKey];
    if (entry && entry.expires > now) {
        [self deliver:entry.timeline reason:entry.reason generation:generation completion:completion];
        return;
    }
    if (entry) [_cache removeObjectForKey:track.cacheKey];
    if (now < _notBefore) {
        [self deliver:nil reason:@"lyrics_cooldown" generation:generation completion:completion];
        return;
    }
    NSTimeInterval requestDelay = MAX(0.0, _lastRequestAt + 0.35 - now);
    if (now + requestDelay >= _deadline) {
        [self deliver:nil reason:@"lyrics_timeout" generation:generation completion:completion]; return;
    }
    _searchAttempted = NO; _searchTask = NO; _searchPending = NO;
    _track = track; _completion = [completion copy];
    if (requestDelay > 0.0) {
        _requestPending = YES;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(requestDelay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            if (self.generation != generation || self.activeGeneration != generation || !self.requestPending || self.task) return;
            self.requestPending = NO;
            [self sendGetForTrack:track];
        });
        return;
    }
    _requestPending = NO;
    [self sendGetForTrack:track];
}
- (void)sendGetForTrack:(MiniSightLyricsTrack *)track {
    NSURLComponents *url = [NSURLComponents componentsWithString:@"https://lrclib.net/api/get"];
    url.queryItems = @[[NSURLQueryItem queryItemWithName:@"track_name" value:track.title],
                       [NSURLQueryItem queryItemWithName:@"artist_name" value:track.artist],
                       [NSURLQueryItem queryItemWithName:@"duration" value:[NSString stringWithFormat:@"%.17g", track.duration]]];
    [self sendRequestURL:url.URL track:track search:NO];
}
- (void)sendSearchForTrack:(MiniSightLyricsTrack *)track {
    NSURLComponents *url = [NSURLComponents componentsWithString:@"https://lrclib.net/api/search"];
    url.queryItems = @[[NSURLQueryItem queryItemWithName:@"q" value:[NSString stringWithFormat:@"%@ %@", track.title, track.artist]]];
    [self sendRequestURL:url.URL track:track search:YES];
}
- (void)sendRequestURL:(NSURL *)url track:(MiniSightLyricsTrack *)track search:(BOOL)search {
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    // A dispatch_after block may run late. Never start a GET/search after the
    // shared deadline merely by clamping its request timeout to 0.1 seconds.
    if (!MSLyricsDispatchReady(now, _deadline)) {
        MiniSightLyricsResult completion = _completion; NSUInteger generation = _activeGeneration;
        _track = nil; _completion = nil;
        [self deliver:nil reason:@"lyrics_timeout" generation:generation completion:completion];
        return;
    }
    NSTimeInterval remaining = _deadline - now;
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:MIN(12.0, remaining)];
    request.HTTPMethod = @"GET";
    request.HTTPShouldHandleCookies = NO;
    [request setValue:@"application/json" forHTTPHeaderField:@"Accept"];
    [request setValue:@"MiniSight-Lyrics/1.0 (+https://openminis.app)" forHTTPHeaderField:@"User-Agent"];
    _lastRequestAt = NSProcessInfo.processInfo.systemUptime;
    _searchTask = search;
    _body = [NSMutableData data]; _response = nil;
    _task = [_session dataTaskWithRequest:request];
    [_task resume];
}
- (void)startSearchForGeneration:(NSUInteger)generation {
    if (_activeGeneration != generation || self.generation != generation || !_track || _task || _searchAttempted) return;
    _searchAttempted = YES;
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    NSTimeInterval delay = MAX(0.0, _lastRequestAt + 0.35 - now);
    if (now + delay >= _deadline) {
        MiniSightLyricsResult completion = _completion; NSUInteger active = _activeGeneration;
        _track = nil; _completion = nil;
        [self deliver:nil reason:@"lyrics_timeout" generation:active completion:completion];
        return;
    }
    if (delay > 0.0) {
        _searchPending = YES;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            if (self.generation != generation || self.activeGeneration != generation || !self.searchPending || self.task) return;
            self.searchPending = NO;
            if (NSProcessInfo.processInfo.systemUptime >= self.deadline) {
                MiniSightLyricsResult completion = self.completion; MiniSightLyricsTrack *track = self.track;
                self.track = nil; self.completion = nil;
                [self deliver:nil reason:@"lyrics_timeout" generation:generation completion:completion];
                return;
            }
            [self sendSearchForTrack:self.track];
        });
        return;
    }
    [self sendSearchForTrack:_track];
}
- (void)receivedResponse:(NSURLResponse *)response task:(NSURLSessionDataTask *)task completion:(void (^)(NSURLSessionResponseDisposition))completion {
    if (task != _task) { completion(NSURLSessionResponseCancel); return; }
    if (_activeGeneration != self.generation) { completion(NSURLSessionResponseCancel); return; }
    NSString *expectedPath = _searchTask ? @"/api/search" : @"/api/get";
    if (![response isKindOfClass:NSHTTPURLResponse.class] || !MSLyricsAllowedURL(response.URL, expectedPath)) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorBadServerResponse userInfo:nil]];
        return;
    }
    _response = (NSHTTPURLResponse *)response;
    if (_response.statusCode == 429 || _response.statusCode == 503) {
        double delay = [MiniSightLyricsClient retryDelayForResponse:_response now:NSDate.date attempt:_rateAttempt];
        _rateAttempt = MIN(_rateAttempt + 1, (NSUInteger)4);
        double jitter = MIN(5.0, delay * 0.1) * arc4random_uniform(1001) / 1000.0;
        _notBefore = MAX(_notBefore, NSProcessInfo.processInfo.systemUptime + delay + jitter);
    }
    if (_response.statusCode != 200) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:nil]; // Status/header only; never buffer an error page.
        return;
    }
    if (![response.MIMEType.lowercaseString isEqualToString:@"application/json"]) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorBadServerResponse userInfo:nil]];
        return;
    }
    if (response.expectedContentLength > (int64_t)MSLyricsMaxBytes) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorDataLengthExceedsMaximum userInfo:nil]];
        return;
    }
    completion(NSURLSessionResponseAllow);
}
- (void)receivedData:(NSData *)data task:(NSURLSessionDataTask *)task {
    if (task != _task) return;
    if (_activeGeneration != self.generation) return;
    if (data.length > MSLyricsMaxBytes - _body.length) {
        [task cancel];
        [self finishedTask:task error:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorDataLengthExceedsMaximum userInfo:nil]];
        return;
    }
    [_body appendData:data];
}
- (void)finishedTask:(NSURLSessionTask *)task error:(NSError * _Nullable)error {
    if (task != _task) return;
    if (_activeGeneration != self.generation) return;
    if (MSLyricsShouldSearch(error != nil, _response.statusCode, _searchTask, _searchAttempted)) {
        NSUInteger generation = _activeGeneration;
        _task = nil; _body = nil; _response = nil;
        [self startSearchForGeneration:generation];
        return;
    }
    BOOL wasSearch = _searchTask;
    MiniSightLyricsTimeline *timeline = nil;
    NSInteger status = _response.statusCode;
    NSString *reason = @"lyrics_http";
    if (error) {
        BOOL urlError = [error.domain isEqualToString:NSURLErrorDomain];
        reason = urlError && error.code == NSURLErrorTimedOut ? @"lyrics_timeout"
            : urlError && error.code == NSURLErrorDataLengthExceedsMaximum ? @"lyrics_oversized"
            : urlError && error.code == NSURLErrorBadServerResponse ? @"lyrics_response_rejected" : @"lyrics_network_error";
    } else if (status == 404) reason = @"lyrics_not_found";
    else if (status == 429) reason = @"lyrics_rate_limited";
    else if (status == 503) reason = @"lyrics_service_unavailable";
    else if (status == 200) timeline = wasSearch
        ? [MiniSightLyricsClient timelineForSearchResponseData:_body response:_response track:_track reason:&reason]
        : [MiniSightLyricsClient timelineForResponseData:_body response:_response track:_track reason:&reason];
    if (MSLyricsShouldCache(error != nil, timeline != nil, wasSearch, status,
        [reason isEqualToString:@"lyrics_response_rejected"])) {
        MSLyricsCacheEntry *entry = [[MSLyricsCacheEntry alloc] init];
        entry.timeline = timeline; entry.reason = reason;
        entry.expires = NSProcessInfo.processInfo.systemUptime + (timeline ? 3600.0 : 300.0);
        [_cache setObject:entry forKey:_track.cacheKey cost:MAX((NSUInteger)1, _body.length)];
    }
    if (!error && status == 200) _rateAttempt = 0;
    if (error || (_response.statusCode >= 500 && _response.statusCode != 503))
        _notBefore = MAX(_notBefore, NSProcessInfo.processInfo.systemUptime + 5.0);
    MiniSightLyricsResult completion = _completion;
    NSUInteger generation = _activeGeneration;
    _task = nil; _body = nil; _response = nil; _track = nil; _completion = nil;
    [self deliver:timeline reason:reason generation:generation completion:completion];
}
@end

@implementation MSLyricsSessionDelegate
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveResponse:(NSURLResponse *)response completionHandler:(void (^)(NSURLSessionResponseDisposition))completionHandler {
    MiniSightLyricsClient *owner = self.owner;
    if (owner) [owner receivedResponse:response task:task completion:completionHandler];
    else completionHandler(NSURLSessionResponseCancel);
}
- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)task didReceiveData:(NSData *)data {
    [self.owner receivedData:data task:task];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didCompleteWithError:(NSError * _Nullable)error {
    [self.owner finishedTask:task error:error];
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task willPerformHTTPRedirection:(NSHTTPURLResponse *)response newRequest:(NSURLRequest *)request completionHandler:(void (^)(NSURLRequest * _Nullable))completionHandler {
    completionHandler(nil); // Including same-host redirects: never resend the signature elsewhere.
}
- (void)URLSession:(NSURLSession *)session didReceiveChallenge:(NSURLAuthenticationChallenge *)challenge completionHandler:(void (^)(NSURLSessionAuthChallengeDisposition, NSURLCredential * _Nullable))completionHandler {
    if ([challenge.protectionSpace.authenticationMethod isEqualToString:NSURLAuthenticationMethodServerTrust])
        completionHandler(NSURLSessionAuthChallengePerformDefaultHandling, nil); // Standard TLS validation only.
    else completionHandler(NSURLSessionAuthChallengeCancelAuthenticationChallenge, nil);
}
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task didReceiveChallenge:(NSURLAuthenticationChallenge *)challenge completionHandler:(void (^)(NSURLSessionAuthChallengeDisposition, NSURLCredential * _Nullable))completionHandler {
    [self URLSession:session didReceiveChallenge:challenge completionHandler:completionHandler];
}
@end

NS_ASSUME_NONNULL_END
