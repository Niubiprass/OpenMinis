#import "MiniSightLyrics.h"
#import "MiniSightLog.h"
#import <math.h>
#import <float.h>
#import <stdlib.h>
#import <stdbool.h>
#import <stddef.h>
#import <stdint.h>
#import <string.h>
#import <dispatch/dispatch.h>

NS_ASSUME_NONNULL_BEGIN

static const NSUInteger MSLyricsMaxBytes = 1024 * 1024;
static const NSTimeInterval MSLyricsMaxDisplay = 12.0;

// Candidate-local evidence: first failing identity layer per record. Never metadata.
typedef struct {
    NSUInteger total, titleRejected, artistRejected, durationRejected, invalid, ambiguous;
} MSLyricsMatchStats;

// Fixed-vocabulary local evidence only: never metadata, URLs, errors or LRC.
// Seven fixed routes x three stages bound the dedupe table; repeated facts emit at most
// once per minute. The shared writer also caps pending events and rotates files.
static void MSLyricsEvidenceRecord(NSString *stage, NSString *result, NSString *route,
    NSString *reason, NSUInteger generation, NSInteger status, NSUInteger bytes, NSUInteger candidates,
    const MSLyricsMatchStats * _Nullable stats) {
    static NSMutableDictionary *last, *times; static NSObject *lock; static dispatch_once_t once;
    dispatch_once(&once, ^{ last = [NSMutableDictionary dictionary]; times = [NSMutableDictionary dictionary]; lock = [NSObject new]; });
    NSInteger http = MAX(0, MIN(599, status));
    NSUInteger count = MIN((NSUInteger)21, candidates); // 21 is the over-limit sentinel.
    NSMutableDictionary *fields = [@{@"lyrics_route": route, @"lyrics_detail": reason,
        @"generation": @(MIN(generation, (NSUInteger)1000000000)), @"http": @(http),
        @"bytes": @(MIN(bytes, MSLyricsMaxBytes)), @"count": @(count)} mutableCopy];
    if (stats) {
        fields[@"match_total"] = @(MIN((NSUInteger)21, stats->total));
        fields[@"match_title_rejected"] = @(MIN((NSUInteger)21, stats->titleRejected));
        fields[@"match_artist_rejected"] = @(MIN((NSUInteger)21, stats->artistRejected));
        fields[@"match_duration_rejected"] = @(MIN((NSUInteger)21, stats->durationRejected));
        fields[@"match_invalid"] = @(MIN((NSUInteger)21, stats->invalid));
        fields[@"match_ambiguous"] = @(MIN((NSUInteger)21, stats->ambiguous));
    }
    NSArray *fact = @[result, reason, @(http), @(count), stats ? @[
        fields[@"match_total"], fields[@"match_title_rejected"], fields[@"match_artist_rejected"],
        fields[@"match_duration_rejected"], fields[@"match_invalid"], fields[@"match_ambiguous"]] : @[]];
    NSString *slot = [route stringByAppendingFormat:@"/%@", stage];
    @synchronized (lock) {
        double now = NSProcessInfo.processInfo.systemUptime;
        if ([last[slot] isEqual:fact] && now - [times[slot] doubleValue] < 60.0) return;
        last[slot] = fact; times[slot] = @(now);
    }
    MSDiagEvent(@"lyrics", stage, result, fields);
}
static void MSLyricsEvidence(NSString *stage, NSString *result, NSString *route,
    NSString *reason, NSUInteger generation, NSInteger status, NSUInteger bytes, NSUInteger candidates) {
    MSLyricsEvidenceRecord(stage, result, route, reason, generation, status, bytes, candidates, NULL);
}
static void MSLyricsMatchEvidence(NSString *route, NSUInteger generation, NSInteger status,
    NSUInteger bytes, const MSLyricsMatchStats *stats, BOOL accepted) {
    NSString *detail = accepted ? @"match_accepted" : stats->invalid ? @"match_invalid"
        : stats->ambiguous ? @"match_ambiguous" : !stats->total ? @"match_empty" : @"match_no_timeline";
    NSUInteger layers = (stats->titleRejected > 0) + (stats->artistRejected > 0) + (stats->durationRejected > 0);
    if (!accepted && !stats->invalid && !stats->ambiguous && layers)
        detail = layers > 1 ? @"match_mixed" : stats->titleRejected ? @"match_title_rejected"
            : stats->artistRejected ? @"match_artist_rejected" : @"match_duration_rejected";
    MSLyricsEvidenceRecord(@"match", accepted ? @"ok" : @"skipped", route, detail,
        generation, status, bytes, stats->total, stats);
}

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
static bool MSLyricsShouldSearch(bool failed, long status, bool search, bool attempted, bool validatedUnsynced) {
    return !failed && !search && !attempted && (status == 404 || (status == 200 && validatedUnsynced));
}
static bool MSLyricsShouldCache(bool failed, bool timeline, bool search, long status, bool rejected) {
    return !failed && (timeline || (search && (status == 404 || (status == 200 && !rejected))));
}
static bool MSLyricsDispatchReady(double now, double deadline) {
    return isfinite(now) && isfinite(deadline) && now < deadline;
}
// QQ is a second source, not a retry for network or service failures.
static bool MSLyricsMayTryQQ(bool lrclibSearch, bool attempted, bool failed, bool hasTimeline,
                              long status, bool confirmedMissing) {
    return lrclibSearch && !attempted && !failed && !hasTimeline &&
        (status == 404 || (status == 200 && confirmedMissing));
}
static bool MSLyricsQQTicket(size_t captured, size_t current, size_t active,
                             bool pending, bool hasTrack, bool hasTask) {
    return captured == current && captured == active && pending && hasTrack && !hasTask;
}
static bool MSLyricsASCIIAlpha(uint8_t c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
static bool MSLyricsASCIIDigit(uint8_t c) { return c >= '0' && c <= '9'; }
static bool MSLyricsQQMIDOK(const uint8_t *bytes, size_t n) {
    if (!bytes || n == 0 || n > 64) return false;
    for (size_t i = 0; i < n; ++i) if (!MSLyricsASCIIAlpha(bytes[i]) && !MSLyricsASCIIDigit(bytes[i])) return false;
    return true;
}
static bool MSLyricsQQSpace(uint8_t c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
static bool MSLyricsQQNameStart(uint8_t c) { return MSLyricsASCIIAlpha(c) || c == '$' || c == '_'; }
// Locate one JSONP argument, without executing or interpreting its contents.
// Foundation still has to parse the ENTIRE extracted slice as a JSON dictionary.
static bool MSLyricsQQPayloadRange(const uint8_t *p, size_t n, size_t *at, size_t *length) {
    if (!p || !at || !length || !n || n > 1024u * 1024u) return false;
    size_t i = 0, end = n;
    while (i < end && MSLyricsQQSpace(p[i])) i++;
    if (end - i >= 3 && p[i] == 0xef && p[i+1] == 0xbb && p[i+2] == 0xbf) i += 3;
    while (i < end && MSLyricsQQSpace(p[i])) i++;
    size_t name = i;
    for (int part = 0; part < 2; ++part) {
        if (i >= end || !MSLyricsQQNameStart(p[i++])) return false;
        while (i < end && (MSLyricsQQNameStart(p[i]) || MSLyricsASCIIDigit(p[i]))) i++;
        if (i >= end || p[i] != '.' || part == 1) break;
        i++;
    }
    if (i - name > 128) return false;
    while (i < end && MSLyricsQQSpace(p[i])) i++;
    if (i >= end || p[i++] != '(') return false;
    while (i < end && MSLyricsQQSpace(p[i])) i++;
    while (end > i && MSLyricsQQSpace(p[end-1])) end--;
    if (end > i && p[end-1] == ';') end--;
    while (end > i && MSLyricsQQSpace(p[end-1])) end--;
    if (end <= i || p[--end] != ')') return false;
    while (end > i && MSLyricsQQSpace(p[end-1])) end--;
    if (end - i < 2 || p[i] != '{' || p[end-1] != '}') return false;
    *at = i; *length = end - i; return true;
}
// Explicit credit separators: '/', '&', or U+3001. Whitespace is never split
// into artist names. The original ordered whole-list space-join is kept as an
// exact compatibility form, NOT a fuzzy/name-subset rule.
static size_t MSLyricsArtistSeparator(const uint8_t *p, size_t n) {
    if (!n) return 0;
    if (p[0] == '/' || p[0] == '&') return 1;
    return n >= 3 && p[0] == 0xe3 && p[1] == 0x80 && p[2] == 0x81 ? 3 : 0;
}
static bool MSLyricsArtistIdentity(const uint8_t *credit, size_t n,
    const uint8_t *const *names, const size_t *lengths, size_t count) {
    if (!credit || !n || n > 2048 || !names || !lengths || !count || count > 20) return false;
    for (size_t i = 0; i < count; ++i) if (!names[i] || !lengths[i] || lengths[i] > 2048) return false;
    // An atomic solo name (including AC/DC, A&B, etc.) is never split or stripped.
    if (count == 1) return n == lengths[0] && memcmp(credit, names[0], n) == 0;
    for (size_t i = 0; i < count; ++i) {
        for (size_t j = 0; j < i; ++j)
            if (lengths[i] == lengths[j] && memcmp(names[i], names[j], lengths[i]) == 0) return false;
    }
    // Preserve the original QQ complete-list exact positive. No whitespace
    // parsing: the structured singer list constructs the whole expected string.
    size_t joinedLength = count - 1;
    for (size_t i = 0; i < count; ++i) joinedLength += lengths[i];
    if (joinedLength == n) {
        size_t at = 0; bool same = true;
        for (size_t i = 0; i < count; ++i) {
            if (i && credit[at++] != ' ') same = false;
            if (memcmp(credit + at, names[i], lengths[i]) != 0) same = false;
            at += lengths[i];
        }
        if (same) return true;
    }
    // Reordering uses explicit separators only. Embedded punctuation in an
    // atomic multi-credit name is ambiguous here and is not stripped or split.
    for (size_t i = 0; i < count; ++i) for (size_t j = 0; j < lengths[i]; ++j)
        if (MSLyricsArtistSeparator(names[i] + j, lengths[i] - j)) return false;
    bool seen[20] = {false}; size_t start = 0, tokens = 0;
    for (size_t end = 0; end <= n;) {
        size_t separator = end < n ? MSLyricsArtistSeparator(credit + end, n - end) : 0;
        if (end < n && !separator) { ++end; continue; }
        size_t left = start, right = end;
        while (left < right && credit[left] == ' ') ++left;
        while (right > left && credit[right - 1] == ' ') --right;
        if (left == right || tokens >= count) return false;
        size_t found = SIZE_MAX;
        for (size_t i = 0; i < count; ++i)
            if (right - left == lengths[i] && memcmp(credit + left, names[i], lengths[i]) == 0) { found = i; break; }
        if (found == SIZE_MAX || seen[found]) return false;
        seen[found] = true; ++tokens;
        if (end == n) break;
        end += separator; start = end;
    }
    return tokens == count;
}
// END LYRICS PORTABLE POLICY

// Candidate-local QQ singer[] is the only structured artist list available.
// LRCLIB artistName remains exact: no documented multi-credit grammar there.
// No change to global Normalize, track identity, cache keys, query or title guards.
static BOOL MSLyricsQQArtistsMatch(NSArray<NSString *> *names, NSString *credit) {
    if (!names.count || names.count > 20) return NO;
    NSData *observed = [credit dataUsingEncoding:NSUTF8StringEncoding];
    NSMutableArray<NSData *> *storage = [NSMutableArray arrayWithCapacity:names.count];
    const uint8_t *parts[20]; size_t lengths[20];
    for (NSString *name in names) [storage addObject:[name dataUsingEncoding:NSUTF8StringEncoding]];
    for (NSUInteger i = 0; i < storage.count; ++i) { parts[i] = storage[i].bytes; lengths[i] = storage[i].length; }
    return MSLyricsArtistIdentity(observed.bytes, observed.length, parts, lengths, storage.count);
}

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

typedef NS_ENUM(NSUInteger, MSLyricsRoute) { MSLyricsRouteLRCLibGet, MSLyricsRouteLRCLibSearch, MSLyricsRouteQQSearch, MSLyricsRouteQQLyric };
static BOOL MSLyricsAllowedURL(NSURL * _Nullable url, MSLyricsRoute route) {
    NSString *host = route <= MSLyricsRouteLRCLibSearch ? @"lrclib.net" : @"c.y.qq.com";
    NSString *path = route == MSLyricsRouteLRCLibGet ? @"/api/get" : route == MSLyricsRouteLRCLibSearch ? @"/api/search" : route == MSLyricsRouteQQSearch ? @"/soso/fcgi-bin/client_search_cp" : @"/lyric/fcgi-bin/fcg_query_lyric_new.fcg";
    return [url.scheme.lowercaseString isEqualToString:@"https"] && [url.host.lowercaseString isEqualToString:host] && [url.path isEqualToString:path] && (!url.port || url.port.integerValue == 443) && !url.user.length && !url.password.length && !url.fragment.length;
}

@interface MSLyricsCacheEntry : NSObject
@property(nonatomic, strong, nullable) MiniSightLyricsTimeline *timeline;
@property(nonatomic, copy) NSString *reason;
@property(nonatomic) NSTimeInterval expires;
@property(nonatomic) NSInteger status;
@property(nonatomic) NSUInteger candidates;
@end
@implementation MSLyricsCacheEntry
@end

@interface MSLyricsSessionDelegate : NSObject <NSURLSessionDataDelegate>
@property(nonatomic, weak, nullable) MiniSightLyricsClient *owner;
@end

@interface MiniSightLyricsClient ()
+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason;
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason candidates:(NSUInteger * _Nullable)candidates;
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
@property(nonatomic) BOOL qqTask;
@property(nonatomic) BOOL qqSearching;
@property(nonatomic) BOOL qqSearchAttempted;
@property(nonatomic, copy, nullable) NSString *qqSongMID;
@property(nonatomic) BOOL searchPending; // LRCLIB only.
@property(nonatomic) BOOL qqSearchPending;
@property(nonatomic) BOOL requestPending;
@property(atomic) NSUInteger generation; // Ticket invalidation is immediate, even off-main.
@property(nonatomic) NSUInteger activeGeneration;
@property(nonatomic) NSUInteger rateAttempt;
@property(nonatomic) NSTimeInterval notBefore; // LRCLIB only; a QQ outage must not disable the primary source.
@property(nonatomic) NSTimeInterval qqNotBefore;
@property(nonatomic) NSUInteger qqRateAttempt;
@property(nonatomic) NSTimeInterval lastRequestAt;
@property(nonatomic) NSTimeInterval deadline;
- (void)startTrack:(MiniSightLyricsTrack *)track generation:(NSUInteger)generation completion:(MiniSightLyricsResult)completion;
- (void)startSearchForGeneration:(NSUInteger)generation;
- (void)sendGetForTrack:(MiniSightLyricsTrack *)track;
- (void)sendSearchForTrack:(MiniSightLyricsTrack *)track;
- (void)startQQSearch;
- (void)sendQQSearch;
- (void)sendQQLyric;
- (void)finishQQTimeoutForRoute:(NSString *)route;
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
    return [self timelineForResponseData:data response:response track:track reason:reason match:NULL];
}
+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason match:(MSLyricsMatchStats * _Nullable)stats {
    MSLyricsMatchStats local = {0}; if (!stats) stats = &local;
    *stats = (MSLyricsMatchStats){.total = 1, .invalid = 1};
    *reason = @"lyrics_response_rejected";
    if (![track isKindOfClass:MiniSightLyricsTrack.class] || ![response isKindOfClass:NSHTTPURLResponse.class] ||
        response.statusCode != 200 || !MSLyricsAllowedURL(response.URL, MSLyricsRouteLRCLibGet) ||
        ![response.MIMEType.lowercaseString isEqualToString:@"application/json"] ||
        ![data isKindOfClass:NSData.class] || !data.length || data.length > MSLyricsMaxBytes) return nil;
    id record = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if (![record isKindOfClass:NSDictionary.class]) return nil;
    NSString *title = MSLyricsNormalize(record[@"trackName"]), *artist = MSLyricsNormalize(record[@"artistName"]);
    id duration = record[@"duration"], instrumental = record[@"instrumental"], lrc = record[@"syncedLyrics"];
    if (!title.length || !artist.length || ![duration isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)duration) == CFBooleanGetTypeID() ||
        !MSLyricsDurationOK([duration doubleValue]) ||
        ![instrumental isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)instrumental) != CFBooleanGetTypeID()) return nil;
    stats->invalid = 0;
    if (![title isEqualToString:track.title]) stats->titleRejected++;
    else if (![artist isEqualToString:track.artist]) stats->artistRejected++;
    else if (fabs([duration doubleValue] - track.duration) > 2.0) stats->durationRejected++;
    if (stats->titleRejected || stats->artistRejected || stats->durationRejected) {
        *reason = @"lyrics_track_mismatch"; return nil;
    }
    if (!lrc) stats->invalid++;
    if (!lrc) return nil; // Absent schema field is not an explicit null/empty lyric.
    if ([instrumental boolValue]) { *reason = @"lyrics_instrumental"; return nil; }
    if (lrc == NSNull.null || ([lrc isKindOfClass:NSString.class] && ![lrc length])) { *reason = @"no_synced_lyrics"; return nil; }
    if (![lrc isKindOfClass:NSString.class]) return nil;
    MiniSightLyricsTimeline *timeline = [MiniSightLyricsTimeline timelineWithLRC:lrc duration:track.duration];
    *reason = timeline ? @"lyrics_timeline" : @"lyrics_invalid_lrc";
    return timeline;
}
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason {
    return [self timelineForSearchResponseData:data response:response track:track reason:reason candidates:NULL];
}
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason candidates:(NSUInteger * _Nullable)candidates {
    return [self timelineForSearchResponseData:data response:response track:track reason:reason candidates:candidates match:NULL];
}
+ (nullable MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason candidates:(NSUInteger * _Nullable)candidates match:(MSLyricsMatchStats * _Nullable)stats {
    MSLyricsMatchStats local = {0}; if (!stats) stats = &local; *stats = local;
    if (candidates) *candidates = 0;
    *reason = @"lyrics_not_found";
    if (![track isKindOfClass:MiniSightLyricsTrack.class] || ![response isKindOfClass:NSHTTPURLResponse.class] ||
        response.statusCode != 200 || !MSLyricsAllowedURL(response.URL, MSLyricsRouteLRCLibSearch) ||
        ![response.MIMEType.lowercaseString isEqualToString:@"application/json"] ||
        ![data isKindOfClass:NSData.class] || !data.length || data.length > MSLyricsMaxBytes) {
        stats->invalid++; *reason = @"lyrics_response_rejected"; return nil;
    }
    id payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
    if ([payload isKindOfClass:NSArray.class]) stats->total = MIN((NSUInteger)21, [payload count]);
    if (candidates && [payload isKindOfClass:NSArray.class]) *candidates = MIN((NSUInteger)21, [payload count]);
    if (![payload isKindOfClass:NSArray.class] || [payload count] > 20) {
        stats->invalid++; *reason = @"lyrics_response_rejected"; return nil;
    }
    NSMutableArray<NSDictionary *> *matches = [NSMutableArray array];
    BOOL sawInstrumental = NO, sawUnsynced = NO, sawInvalidLRC = NO;
    for (id value in (NSArray *)payload) {
        if (![value isKindOfClass:NSDictionary.class]) { stats->invalid++; *reason = @"lyrics_response_rejected"; return nil; }
        NSDictionary *record = value;
        NSString *title = MSLyricsNormalize(record[@"trackName"]), *artist = MSLyricsNormalize(record[@"artistName"]);
        id duration = record[@"duration"], instrumental = record[@"instrumental"], lrc = record[@"syncedLyrics"];
        if (!title.length || !artist.length || ![duration isKindOfClass:NSNumber.class] ||
            CFGetTypeID((__bridge CFTypeRef)duration) == CFBooleanGetTypeID() || !MSLyricsDurationOK([duration doubleValue]) ||
            ![instrumental isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)instrumental) != CFBooleanGetTypeID() ||
            (! [lrc isKindOfClass:NSString.class] && lrc != NSNull.null)) {
            stats->invalid++; *reason = @"lyrics_response_rejected"; return nil;
        }
        if (![title isEqualToString:track.title]) { stats->titleRejected++; continue; }
        if (![artist isEqualToString:track.artist]) { stats->artistRejected++; continue; }
        if (fabs([duration doubleValue] - track.duration) > 2.0) { stats->durationRejected++; continue; }
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
    if (best == SIZE_MAX) { stats->ambiguous = matches.count; *reason = @"lyrics_response_rejected"; return nil; }
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
    NSTimeInterval deadline = _deadline;
    dispatch_async(dispatch_get_main_queue(), ^{
        MiniSightLyricsClient *owner = weakSelf;
        if (owner && owner.generation == generation && completion) {
            BOOL ready = MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, deadline);
            completion(ready ? timeline : nil, ready ? reason : @"lyrics_timeout");
        }
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
    _searchTask = NO; _searchAttempted = NO; _qqTask = NO; _qqSearching = NO;
    _qqSearchAttempted = NO; _qqSongMID = nil; _searchPending = NO; _qqSearchPending = NO; _requestPending = NO;
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
        MSLyricsEvidence(@"finish", entry.timeline ? @"ok" : @"skipped", entry.timeline ? @"positive_cache" : @"negative_cache",
            entry.reason, generation, entry.status, 0, entry.candidates);
        [self deliver:entry.timeline reason:entry.reason generation:generation completion:completion];
        return;
    }
    if (entry) [_cache removeObjectForKey:track.cacheKey];
    if (now < _notBefore) {
        MSLyricsEvidence(@"finish", @"skipped", @"cooldown", @"lyrics_cooldown", generation, 0, 0, 0);
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
- (void)startQQSearch {
    if (_qqSearchAttempted || !_track || _activeGeneration != self.generation || _task) return;
    _qqSearchAttempted = YES;
    if (NSProcessInfo.processInfo.systemUptime < _qqNotBefore) {
        MiniSightLyricsResult completion = _completion; NSUInteger generation = _activeGeneration;
        _completion = nil; _track = nil;
        MSLyricsEvidence(@"finish", @"skipped", @"qq_search", @"lyrics_cooldown", generation, 0, 0, 0);
        [self deliver:nil reason:@"lyrics_cooldown" generation:generation completion:completion];
        return;
    }
    NSTimeInterval delay = MAX(0.0, _lastRequestAt + 0.35 - NSProcessInfo.processInfo.systemUptime);
    if (!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime + delay, _deadline)) { [self finishQQTimeoutForRoute:@"qq_search"]; return; }
    const NSUInteger ticket = _activeGeneration;
    _qqSearchPending = YES;
    __weak typeof(self) weakSelf = self;
    void (^dispatchSearch)(void) = ^{
        typeof(self) owner = weakSelf;
        if (!owner || !MSLyricsQQTicket(ticket, owner.generation, owner.activeGeneration,
                                        owner.qqSearchPending, owner.track != nil, owner.task != nil)) return;
        owner.qqSearchPending = NO;
        [owner sendQQSearch];
    };
    if (delay > 0) dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(delay * NSEC_PER_SEC)), dispatch_get_main_queue(), dispatchSearch);
    else dispatchSearch();
}
- (void)finishQQTimeoutForRoute:(NSString *)route {
    if (_activeGeneration != self.generation || !_completion) return;
    NSUInteger generation = _activeGeneration; MiniSightLyricsResult completion = _completion;
    [_task cancel]; _task = nil; _body = nil; _response = nil; _track = nil; _completion = nil;
    _searchPending = NO; _qqSearchPending = NO; _requestPending = NO;
    MSLyricsEvidence(@"finish", @"skipped", route, @"lyrics_timeout", generation, 0, 0, 0);
    [self deliver:nil reason:@"lyrics_timeout" generation:generation completion:completion];
}
- (void)sendQQSearch {
    MiniSightLyricsTrack *t=_track;
    if (!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime,_deadline)) { [self finishQQTimeoutForRoute:@"qq_search"]; return; }
    if (!t) return;
    NSURLComponents *u=[NSURLComponents componentsWithString:@"https://c.y.qq.com/soso/fcgi-bin/client_search_cp"];
    // Keep the request shape identical to the previously successful public probe.
    u.queryItems=@[[NSURLQueryItem queryItemWithName:@"w" value:[NSString stringWithFormat:@"%@ %@",t.title,t.artist]]];
    [self sendQQURL:u.URL search:YES];
}
- (void)sendQQLyric {
    if (!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime,_deadline)) { [self finishQQTimeoutForRoute:@"qq_lyric"]; return; }
    if (!_qqSongMID.length || !_track) return;
    NSURLComponents *u=[NSURLComponents componentsWithString:@"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"];
    // Exact parameter set from the previously successful public probe.
    u.queryItems=@[[NSURLQueryItem queryItemWithName:@"songmid" value:_qqSongMID],[NSURLQueryItem queryItemWithName:@"g_tk" value:@"5381"]];
    [self sendQQURL:u.URL search:NO];
}
- (void)sendQQURL:(NSURL *)url search:(BOOL)search {
    const NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    if (_activeGeneration != self.generation || !_track || _task) return;
    if (!MSLyricsDispatchReady(now, _deadline)) { [self finishQQTimeoutForRoute:search ? @"qq_search" : @"qq_lyric"]; return; }
    NSMutableURLRequest *r = [NSMutableURLRequest requestWithURL:url cachePolicy:NSURLRequestReloadIgnoringLocalCacheData timeoutInterval:MIN(12.0, _deadline - now)];
    r.HTTPMethod = @"GET";
    r.HTTPShouldHandleCookies = NO;
    [r setValue:@"application/json" forHTTPHeaderField:@"Accept"];
    [r setValue:@"MiniSight-Lyrics/1.0 (+https://openminis.app)" forHTTPHeaderField:@"User-Agent"];
    [r setValue:(search ? @"https://y.qq.com/" : @"https://y.qq.com/portal/player.html") forHTTPHeaderField:@"Referer"];
    _lastRequestAt=NSProcessInfo.processInfo.systemUptime; _searchTask=NO; _qqTask=YES; _qqSearching=search; _body=[NSMutableData data]; _response=nil;
    MSLyricsEvidence(@"request", @"pending", search ? @"qq_search" : @"qq_lyric", @"not_applicable", _activeGeneration, 0, 0, 0);
    _task=[_session dataTaskWithRequest:r]; [_task resume];
}
- (void)sendRequestURL:(NSURL *)url track:(MiniSightLyricsTrack *)track search:(BOOL)search {
    NSTimeInterval now = NSProcessInfo.processInfo.systemUptime;
    // A dispatch_after block may run late. Never start a GET/search after the
    // shared deadline merely by clamping its request timeout to 0.1 seconds.
    if (!MSLyricsDispatchReady(now, _deadline)) {
        MiniSightLyricsResult completion = _completion; NSUInteger generation = _activeGeneration;
        _track = nil; _completion = nil;
        MSLyricsEvidence(@"finish", @"skipped", search ? @"search" : @"exact", @"lyrics_timeout", generation, 0, 0, 0);
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
    MSLyricsEvidence(@"request", @"pending", search ? @"search" : @"exact", @"not_applicable", _activeGeneration, 0, 0, 0);
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
                MiniSightLyricsResult completion = self.completion;
                self.track = nil; self.completion = nil; self.searchPending = NO;
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
    MSLyricsRoute expectedRoute = _qqTask ? (_qqSearching ? MSLyricsRouteQQSearch : MSLyricsRouteQQLyric) : (_searchTask ? MSLyricsRouteLRCLibSearch : MSLyricsRouteLRCLibGet);
    if (![response isKindOfClass:NSHTTPURLResponse.class] || !MSLyricsAllowedURL(response.URL, expectedRoute) ||
        (_qqTask && ![response.URL isEqual:task.originalRequest.URL])) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorBadServerResponse userInfo:nil]];
        return;
    }
    _response = (NSHTTPURLResponse *)response;
    if (_response.statusCode == 429 || _response.statusCode == 503) {
        NSUInteger *attempt = _qqTask ? &_qqRateAttempt : &_rateAttempt;
        NSTimeInterval *notBefore = _qqTask ? &_qqNotBefore : &_notBefore;
        double delay = [MiniSightLyricsClient retryDelayForResponse:_response now:NSDate.date attempt:*attempt];
        *attempt = MIN(*attempt + 1, (NSUInteger)4);
        double jitter = MIN(5.0, delay * 0.1) * arc4random_uniform(1001) / 1000.0;
        *notBefore = MAX(*notBefore, NSProcessInfo.processInfo.systemUptime + delay + jitter);
    }
    if (_response.statusCode != 200) {
        completion(NSURLSessionResponseCancel);
        [self finishedTask:task error:nil]; // Status/header only; never buffer an error page.
        return;
    }
    NSString *mime = response.MIMEType.lowercaseString;
    BOOL mimeOK = _qqTask
        ? (_qqSearching ? [mime isEqualToString:@"application/x-javascript"] || [mime isEqualToString:@"application/javascript"]
                        : [mime isEqualToString:@"text/html"])
        : [mime isEqualToString:@"application/json"];
    if (!mimeOK) {
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
static NSDictionary *MSQQJSONP(NSData *data) {
    size_t at = 0, length = 0;
    if (!MSLyricsQQPayloadRange(data.bytes, data.length, &at, &length)) return nil;
    NSData *json = [data subdataWithRange:NSMakeRange(at, length)];
    if (![[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding]) return nil;
    id object = [NSJSONSerialization JSONObjectWithData:json options:0 error:NULL];
    return [object isKindOfClass:NSDictionary.class] ? object : nil;
}
static NSString *MSQQBase64LRC(id value) {
    if(![value isKindOfClass:NSString.class] || ![value length] || [value length]>MSLyricsMaxBytes*2) return nil;
    NSData *d=[[NSData alloc] initWithBase64EncodedString:value options:0]; if(!d.length || d.length>MSLyricsMaxBytes) return nil;
    NSString *b=[d base64EncodedStringWithOptions:0]; if(![b isEqual:value]) return nil;
    NSString *text=[[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding]; return text.length ? text : nil;
}
- (void)finishedTask:(NSURLSessionTask *)task error:(NSError * _Nullable)error {
    if (task != _task) return;
    if (_activeGeneration != self.generation) return;
    // Delegate callbacks can sit on a busy main queue beyond NSURLSession's
    // timers. The two legs share one deadline, including parsing/delivery.
    if (!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, _deadline))
        error = [NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorTimedOut userInfo:nil];
    BOOL wasSearch = _searchTask; BOOL wasQQ = _qqTask, qqSearch = _qqSearching;
    MiniSightLyricsTimeline *timeline = nil;
    NSInteger status = _response.statusCode;
    NSUInteger candidates = 0;
    MSLyricsMatchStats match = {0};
    BOOL hasMatch = !error && status == 200 && (!wasQQ || qqSearch);
    NSString *reason = @"lyrics_http";
    if (error) {
        BOOL urlError = [error.domain isEqualToString:NSURLErrorDomain];
        reason = urlError && error.code == NSURLErrorTimedOut ? @"lyrics_timeout"
            : urlError && error.code == NSURLErrorDataLengthExceedsMaximum ? @"lyrics_oversized"
            : urlError && error.code == NSURLErrorBadServerResponse ? @"lyrics_response_rejected" : @"lyrics_network_error";
    } else if (status == 404) reason = @"lyrics_not_found";
    else if (status == 429) reason = @"lyrics_rate_limited";
    else if (status == 503) reason = @"lyrics_service_unavailable";
    else if (status == 200 && !wasQQ) timeline = wasSearch
        ? [MiniSightLyricsClient timelineForSearchResponseData:_body response:_response track:_track reason:&reason candidates:&candidates match:&match]
        : [MiniSightLyricsClient timelineForResponseData:_body response:_response track:_track reason:&reason match:&match];
    else if (status == 200 && wasQQ) reason = @"lyrics_response_rejected";
    NSString *qqMID = nil;
    if (!error && status == 200 && wasQQ) {
        if (qqSearch) match.invalid = 1; // Invalid envelope unless a bounded list is proven.
        NSDictionary *obj=MSQQJSONP(_body); id code=obj[@"code"];
        BOOL good=[code isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)code)!=CFBooleanGetTypeID() && [code isEqualToNumber:@0];
        if(good && qqSearch) {
            NSDictionary *data=[obj[@"data"] isKindOfClass:NSDictionary.class]?obj[@"data"]:nil;
            NSDictionary *songBlock=[data[@"song"] isKindOfClass:NSDictionary.class]?data[@"song"]:nil;
            id rawList=songBlock[@"list"];
            if ([rawList isKindOfClass:NSArray.class]) { candidates = MIN((NSUInteger)21, [rawList count]); match.total = candidates; }
            if([rawList isKindOfClass:NSArray.class] && [rawList count]<=20) {
                match.invalid = 0;
                NSArray *list=(NSArray *)rawList; NSMutableArray *matches=[NSMutableArray array];
                for(id item in list) {
                    if(![item isKindOfClass:NSDictionary.class]) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                    NSDictionary *song=(NSDictionary *)item; id rawSingers=song[@"singer"];
                    if(![rawSingers isKindOfClass:NSArray.class] || ![(NSArray *)rawSingers count] || [(NSArray *)rawSingers count]>20) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                    NSMutableArray *names=[NSMutableArray array];
                    for(id singer in (NSArray *)rawSingers) {
                        if(![singer isKindOfClass:NSDictionary.class]) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                        NSString *name=MSLyricsNormalize(((NSDictionary *)singer)[@"name"]);
                        if(!name) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                        [names addObject:name];
                    }
                    if(!matches) break;
                    NSString *title=MSLyricsNormalize(song[@"songname"]);
                    id seconds=song[@"interval"]; id mid=song[@"songmid"];
                    if(!title || ![seconds isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)seconds)==CFBooleanGetTypeID() || !isfinite([seconds doubleValue])) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                    if(![title isEqual:_track.title]) { match.titleRejected++; continue; }
                    if(!MSLyricsQQArtistsMatch(names, _track.artist)) { match.artistRejected++; continue; }
                    if(fabs([seconds doubleValue]-_track.duration)>2.0) { match.durationRejected++; continue; }
                    NSData *midBytes = [mid isKindOfClass:NSString.class] && [mid length] <= 64 ? [mid dataUsingEncoding:NSUTF8StringEncoding] : nil;
                    if (!MSLyricsQQMIDOK(midBytes.bytes, midBytes.length)) { match.invalid++; reason=@"lyrics_response_rejected"; matches=nil; break; }
                    [matches addObject:@{@"duration":seconds,@"mid":mid}];
                }
                if(matches) {
                    candidates=list.count;
                    if(!matches.count) reason=@"lyrics_not_found";
                    else {
                        double durations[20]; size_t equivalent[20];
                        for(NSUInteger i=0;i<matches.count;i++) {
                            durations[i]=[matches[i][@"duration"] doubleValue]; equivalent[i]=i;
                            for(NSUInteger j=0;j<i;j++) if([matches[i][@"mid"] isEqual:matches[j][@"mid"]]) { equivalent[i]=equivalent[j]; break; }
                        }
                        size_t best=MSLyricsClosestCandidate(durations,equivalent,matches.count,_track.duration);
                        if(best!=SIZE_MAX) qqMID=matches[best][@"mid"];
                        else match.ambiguous = matches.count;
                        reason=qqMID?@"not_applicable":@"lyrics_response_rejected";
                    }
                }
            } else reason=@"lyrics_response_rejected";
        } else if (good && !qqSearch && obj[@"songmid"] && ![obj[@"songmid"] isEqual:_qqSongMID]) {
            reason = @"lyrics_track_mismatch"; // Echo is optional, but a conflicting echo must never supply lyrics.
        } else if(good && !qqSearch) {
            id lyric=obj[@"lyric"];
            if(!lyric) reason=@"lyrics_response_rejected";
            else if(lyric==NSNull.null || ([lyric isKindOfClass:NSString.class] && ![(NSString *)lyric length])) reason=@"no_synced_lyrics";
            else {
                NSString *lrc=MSQQBase64LRC(lyric);
                timeline=lrc?[MiniSightLyricsTimeline timelineWithLRC:lrc duration:_track.duration]:nil;
                if (timeline) {
                    BOOL visible = NO;
                    for (MiniSightLyricLine *line in timeline.lines) if (line.text.length) { visible = YES; break; }
                    if (!visible) { timeline = nil; reason = @"no_synced_lyrics"; }
                    else reason = @"lyrics_timeline";
                } else reason = @"lyrics_invalid_lrc";
            }
        }
    }
    if (!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, _deadline)) {
        timeline = nil; reason = @"lyrics_timeout";
        error = [NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorTimedOut userInfo:nil];
    }
    if (_activeGeneration != self.generation || _task != task) return;
    NSString *evidenceRoute = wasQQ ? (qqSearch ? @"qq_search" : @"qq_lyric") : (wasSearch ? @"search" : @"exact");
    if (hasMatch && !error) MSLyricsMatchEvidence(evidenceRoute, _activeGeneration, status, _body.length,
        &match, timeline != nil || qqMID != nil);
    MSLyricsEvidence(@"finish", (timeline || (qqMID && !error)) ? @"ok" : @"skipped", evidenceRoute,
        reason, _activeGeneration, status, _body.length, candidates);
    // Only a strict same-track, non-instrumental 200 with null/empty synced LRC
    // may join 404 here. Rejected/malformed/mismatched LRC and all HTTP failures
    // never broaden the fallback, and a search response cannot recurse.
    if (!wasQQ && MSLyricsShouldSearch(error != nil, status, wasSearch, _searchAttempted,
        [reason isEqualToString:@"no_synced_lyrics"])) {
        NSUInteger generation = _activeGeneration;
        _task = nil; _body = nil; _response = nil;
        [self startSearchForGeneration:generation];
        return;
    }
    if (MSLyricsMayTryQQ(!wasQQ && wasSearch, _qqSearchAttempted, error != nil, timeline != nil,
                         status, [reason isEqualToString:@"lyrics_not_found"] || [reason isEqualToString:@"no_synced_lyrics"])) {
        _task=nil; _body=nil; _response=nil; [self startQQSearch]; return;
    }
    if (wasQQ && !error && status==200 && qqSearch && qqMID) { _qqSongMID=qqMID; _task=nil; _body=nil; _response=nil; [self sendQQLyric]; return; }
    BOOL conclusiveQQMiss = wasQQ && !error && status == 200 && !timeline &&
        ((qqSearch && !qqMID && [reason isEqualToString:@"lyrics_not_found"]) ||
         (!qqSearch && [reason isEqualToString:@"no_synced_lyrics"]));
    if (conclusiveQQMiss || MSLyricsShouldCache(error != nil, timeline != nil, wasSearch, status,
        [reason isEqualToString:@"lyrics_response_rejected"] || [reason isEqualToString:@"lyrics_invalid_lrc"])) {
        MSLyricsCacheEntry *entry = [[MSLyricsCacheEntry alloc] init];
        entry.timeline = timeline; entry.reason = reason; entry.status = status; entry.candidates = candidates;
        entry.expires = NSProcessInfo.processInfo.systemUptime + (timeline ? 3600.0 : 300.0);
        [_cache setObject:entry forKey:_track.cacheKey cost:MAX((NSUInteger)1, _body.length)];
    }
    if (!error && status == 200) { if (wasQQ) _qqRateAttempt = 0; else _rateAttempt = 0; }
    if (error || (status >= 500 && status != 503)) {
        NSTimeInterval *notBefore = wasQQ ? &_qqNotBefore : &_notBefore;
        *notBefore = MAX(*notBefore, NSProcessInfo.processInfo.systemUptime + 5.0);
    }
    MiniSightLyricsResult completion = _completion;
    NSUInteger generation = _activeGeneration;
    _task = nil; _body = nil; _response = nil; _track = nil; _completion = nil;
    _searchPending = NO; _qqSearchPending = NO; _requestPending = NO;
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
