// Synthetic-only native harness. Compile with the unchanged production .m and Foundation.
#import <Foundation/Foundation.h>
#import <math.h>
#import <stdlib.h>
#import <stdio.h>
#import <dispatch/dispatch.h>
#import "MiniSightLyrics.h"

static NSUInteger checks = 0;
#define CHECK(c, label) do { checks++; if (!(c)) { fprintf(stderr, "FAIL: %s (line %d)\n", label, __LINE__); exit(1); } } while (0)

// Private transport callbacks are exercised directly for a deterministic late-callback race.
@interface MiniSightLyricsClient (FixtureAccess)
+ (MiniSightLyricsTimeline *)timelineForSearchResponseData:(NSData *)data response:(NSHTTPURLResponse *)response track:(MiniSightLyricsTrack *)track reason:(NSString **)reason;
- (void)receivedResponse:(NSURLResponse *)response task:(NSURLSessionDataTask *)task completion:(void (^)(NSURLSessionResponseDisposition))completion;
- (void)receivedData:(NSData *)data task:(NSURLSessionDataTask *)task;
- (void)finishedTask:(NSURLSessionTask *)task error:(NSError *)error;
@end

static BOOL Equal(id a, id b) { return a == b || [a isEqual:b]; }
static NSData *JSON(id value) { return [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingFragmentsAllowed error:NULL]; }
static NSHTTPURLResponse *ResponseAt(NSInteger status, NSDictionary *headers, NSURL *url) {
    return [[NSHTTPURLResponse alloc] initWithURL:url statusCode:status HTTPVersion:@"HTTP/1.1" headerFields:headers ?: @{@"Content-Type": @"application/json"}];
}
static NSHTTPURLResponse *Response(NSInteger status, NSDictionary *headers) {
    return ResponseAt(status, headers, [NSURL URLWithString:@"https://lrclib.net/api/get"]);
}
static NSMutableDictionary *Record(MiniSightLyricsTrack *track) {
    return [@{@"trackName": track.title, @"artistName": track.artist, @"duration": @(track.duration),
               @"instrumental": @NO, @"syncedLyrics": @"[00:01]Synthetic line\n[00:03]"} mutableCopy];
}
static void Pump(NSTimeInterval seconds) {
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([end timeIntervalSinceNow] > 0) [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.005]];
}
static void Wait(BOOL (^condition)(void), const char *label) {
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:3];
    while (!condition() && [end timeIntervalSinceNow] > 0) Pump(0.005);
    CHECK(condition(), label);
}

@class FixtureProtocol;
static void (^handler)(FixtureProtocol *);
static NSUInteger starts;
static NSURLRequest *lastRequest;
@interface FixtureProtocol : NSURLProtocol
@property(atomic) BOOL stopped;
@end
@implementation FixtureProtocol
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return YES; } // Catch ALL, never a live fallback.
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.stopped) return;
        starts++; lastRequest = self.request;
        CHECK(handler != nil, "fake transport handler required");
        handler(self);
    });
}
- (void)stopLoading { self.stopped = YES; }
@end

static void Emit(FixtureProtocol *protocol, NSInteger status, NSData *data, NSDictionary *headers) {
    if (protocol.stopped) return;
    [protocol.client URLProtocol:protocol didReceiveResponse:ResponseAt(status, headers, protocol.request.URL) cacheStoragePolicy:NSURLCacheStorageNotAllowed];
    if (data.length) {
        NSUInteger half = data.length / 2;
        [protocol.client URLProtocol:protocol didLoadData:[data subdataWithRange:NSMakeRange(0, half)]];
        [protocol.client URLProtocol:protocol didLoadData:[data subdataWithRange:NSMakeRange(half, data.length - half)]];
    }
    [protocol.client URLProtocolDidFinishLoading:protocol];
}
static MiniSightLyricsClient *Client(void) {
    return [[MiniSightLyricsClient alloc] initWithProtocolClasses:@[FixtureProtocol.class]];
}
static NSString *lastReason;
static MiniSightLyricsTimeline *Fetch(MiniSightLyricsClient *client, MiniSightLyricsTrack *track) {
    __block NSUInteger completed = 0;
    __block MiniSightLyricsTimeline *result;
    [client fetchTrack:track result:^(MiniSightLyricsTimeline *timeline, NSString *reason) {
        lastReason = reason;
        CHECK(NSThread.isMainThread, "completion on main"); completed++; result = timeline;
    }];
    Wait(^BOOL{ return completed > 0; }, "completion arrived");
    Pump(0.02);
    CHECK(completed == 1, "completion exactly once");
    return result;
}
static void ParserTests(NSDictionary *fixture) {
    MiniSightLyricsTimeline *timeline = [MiniSightLyricsTimeline timelineWithLRC:fixture[@"lrc"] duration:60];
    NSArray *markers = fixture[@"markers"];
    CHECK(timeline.lines.count == markers.count, "retain multistamps and blanks");
    for (NSUInteger i = 0; i < markers.count; i++) CHECK(fabs(timeline.lines[i].time - [markers[i] doubleValue]) < 0.000001, "decimal and colon fractions plus global offset");
    for (NSArray *sample in fixture[@"samples"]) {
        NSString *expected = sample[1] == NSNull.null ? nil : sample[1];
        CHECK(Equal([timeline lineAtTime:[sample[0] doubleValue]], expected), "current line golden sample");
    }
    CHECK([timeline lineAtTime:NAN] == nil && [timeline lineAtTime:INFINITY] == nil && [timeline lineAtTime:-1] == nil, "invalid playback time");
    for (NSString *bad in fixture[@"invalid_lrc"]) CHECK([MiniSightLyricsTimeline timelineWithLRC:bad duration:60] == nil, "reject malformed and untimed");
    for (NSNumber *bad in @[@0, @(-1), @3601, @(NAN), @(INFINITY)]) CHECK([MiniSightLyricsTimeline timelineWithLRC:@"[00:00]A" duration:bad.doubleValue] == nil, "reject invalid duration");
    timeline = [MiniSightLyricsTimeline timelineWithLRC:@"[00:03]Later\n[00:00]First\n[00:00]\n[offset:-500]\n[00:02]Middle" duration:20];
    CHECK(timeline.lines.count == 3 && [timeline lineAtTime:0] == nil, "sort, clamp negative offset, blank tie wins");
    CHECK(Equal([timeline lineAtTime:1.5], @"Middle"), "negative offset exact boundary");
    CHECK(Equal([timeline lineAtTime:2.5], @"Later"), "binary search forward");
    CHECK([timeline lineAtTime:0.1] == nil, "binary search rewind");
    // 12s display window: a line must not survive an instrumental gap.
    timeline = [MiniSightLyricsTimeline timelineWithLRC:@"[00:01]Brief\n[00:30]Next line" duration:60];
    CHECK(Equal([timeline lineAtTime:2], @"Brief") && [timeline lineAtTime:13] == nil, "line expires after the display window");
    CHECK(Equal([timeline lineAtTime:31], @"Next line"), "next marker starts its own window");
    timeline = [MiniSightLyricsTimeline timelineWithLRC:@"[offset:200]\n[00:00]A\n[offset:500]" duration:1];
    CHECK([timeline lineAtTime:0.49] == nil && Equal([timeline lineAtTime:0.5], @"A") && [timeline lineAtTime:1] == nil, "last offset and duration clipping");
    NSString *huge = [@"X" stringByPaddingToLength:1024 * 1024 + 1 withString:@"X" startingAtIndex:0];
    CHECK([MiniSightLyricsTimeline timelineWithLRC:huge duration:60] == nil, "LRC byte cap");
    NSMutableString *many = [NSMutableString string];
    for (NSUInteger i = 0; i < 4097; i++) [many appendString:@"[00:01]A\n"];
    CHECK([MiniSightLyricsTimeline timelineWithLRC:many duration:60] == nil, "marker count cap");
}

static void EvaluatorTests(MiniSightLyricsTrack *track) {
    CHECK(Equal(track.title, @"fixture song") && Equal(track.artist, @"example artist"), "conservative normalization");
    CHECK([[MiniSightLyricsTrack alloc] initWithTitle:@" " artist:@"A" duration:60] == nil, "empty title rejected");
    CHECK([[MiniSightLyricsTrack alloc] initWithTitle:(id)@42 artist:@"A" duration:60] == nil, "wrong title type rejected");
    CHECK([[MiniSightLyricsTrack alloc] initWithTitle:@"A\x01" artist:@"B" duration:60] == nil, "control rejected");
    for (NSNumber *bad in @[@0, @3601, @(NAN), @(INFINITY)]) CHECK([[MiniSightLyricsTrack alloc] initWithTitle:@"A" artist:@"B" duration:bad.doubleValue] == nil, "track duration validated");
    MiniSightLyricsTrack *unicode = [[MiniSightLyricsTrack alloc] initWithTitle:@"E\u0301cho" artist:@"A" duration:60];
    CHECK(Equal(unicode.title, @"écho"), "NFC case normalization, not accent stripping");
    MiniSightLyricsTrack *fraction = [[MiniSightLyricsTrack alloc] initWithTitle:track.title artist:track.artist duration:60.001];
    CHECK(!Equal(track.cacheKey, fraction.cacheKey), "cache duration not rounded");
    NSMutableDictionary *record = Record(track);
    record[@"trackName"] = @"  FIXTURE\tSong ";
    CHECK([MiniSightLyricsClient timelineForResponseData:JSON(record) response:Response(200, nil) track:track] != nil, "exact normalized match accepted");
    NSDictionary *invalid = @{@"trackName": @[@"Fixture Song (Live)", @"Fixture-Song", @"Fixture", NSNull.null],
                             @"artistName": @[@"Example Artist & Guest", @"Example", NSNull.null],
                             @"duration": @[@62.001, @57.999, @"60", @YES, @0, NSNull.null],
                             @"instrumental": @[@YES, @0, @"false", NSNull.null],
                             @"syncedLyrics": @[NSNull.null, @"not timed", @42]};
    for (NSString *key in invalid) for (id value in invalid[key]) {
        NSMutableDictionary *bad = Record(track); bad[key] = value;
        CHECK([MiniSightLyricsClient timelineForResponseData:JSON(bad) response:Response(200, nil) track:track] == nil, "schema/mismatch rejected, no plain fallback");
    }
    for (NSNumber *duration in @[@58, @62]) {
        record = Record(track); record[@"duration"] = duration;
        CHECK([MiniSightLyricsClient timelineForResponseData:JSON(record) response:Response(200, nil) track:track] != nil, "inclusive duration tolerance");
    }
    for (NSNumber *status in @[@404, @429, @500]) CHECK([MiniSightLyricsClient timelineForResponseData:JSON(Record(track)) response:Response(status.integerValue, nil) track:track] == nil, "status checked before JSON");
    CHECK([MiniSightLyricsClient timelineForResponseData:JSON(@[]) response:Response(200, nil) track:track] == nil, "array response rejected");
    CHECK([MiniSightLyricsClient timelineForResponseData:[@"{" dataUsingEncoding:NSUTF8StringEncoding] response:Response(200, nil) track:track] == nil, "broken JSON rejected");
    CHECK([MiniSightLyricsClient timelineForResponseData:JSON(Record(track)) response:Response(200, @{@"Content-Type": @"text/html"}) track:track] == nil, "wrong content type rejected");
    for (NSString *url in @[@"http://lrclib.net/api/get", @"https://example.invalid/api/get", @"https://lrclib.net/api/search", @"https://user@lrclib.net/api/get"]) {
        NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:url] statusCode:200 HTTPVersion:nil headerFields:@{@"Content-Type": @"application/json"}];
        CHECK([MiniSightLyricsClient timelineForResponseData:JSON(Record(track)) response:response track:track] == nil, "foreign endpoint rejected");
    }
}

static void SearchEvaluatorTests(NSDictionary *fixture, MiniSightLyricsTrack *track) {
    NSString *reason = nil;
    NSURL *searchURL = [NSURL URLWithString:@"https://lrclib.net/api/search?q=fixture"];
    NSArray *records = fixture[@"search_records"];
    MiniSightLyricsTimeline *timeline = [MiniSightLyricsClient timelineForSearchResponseData:JSON(records) response:ResponseAt(200, nil, searchURL) track:track reason:&reason];
    CHECK(timeline != nil && Equal(reason, @"lyrics_timeline") && Equal([timeline lineAtTime:2], @"Nearest exact song"), "normalized exact metadata picks closest valid synced lyrics");
    NSArray *badRecords = @[
        @{@"trackName": @"Different Song", @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Wrong title"},
        @{@"trackName": track.title, @"artistName": @"Different Artist", @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Wrong artist"},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @62.001, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Wrong duration"},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @60, @"instrumental": @YES, @"syncedLyrics": NSNull.null},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @""},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"plain text"}
    ];
    for (NSDictionary *record in badRecords) CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(@[record]) response:ResponseAt(200, nil, searchURL) track:track reason:&reason] == nil, "wrong metadata, instrumental or missing synced LRC rejected");
    NSArray *ambiguous = @[
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @59, @"instrumental": @NO, @"syncedLyrics": @"[00:02]Conflicting A"},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @61, @"instrumental": @NO, @"syncedLyrics": @"[00:02]Conflicting B"}
    ];
    CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(ambiguous) response:ResponseAt(200, nil, searchURL) track:track reason:&reason] == nil, "equidistant conflicting candidates rejected");
    for (id malformed in @[@{}, @"bad", @[@{}], @[@{@"trackName": track.title, @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"[00:01]A"}, @42]])
        CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(malformed) response:ResponseAt(200, nil, searchURL) track:track reason:&reason] == nil, "malformed search structure rejected");
    for (NSString *url in @[@"https://lrclib.net/api/get", @"https://example.invalid/api/search", @"http://lrclib.net/api/search", @"https://lrclib.net/api/search/extra"]) {
        NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:[NSURL URLWithString:url] statusCode:200 HTTPVersion:nil headerFields:@{@"Content-Type": @"application/json"}];
        CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(records) response:response track:track reason:&reason] == nil, "search response requires pinned HTTPS endpoint");
    }
    NSMutableArray *tooMany = [NSMutableArray array]; for (NSUInteger i = 0; i < 21; i++) [tooMany addObject:records[0]];
    CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(tooMany) response:ResponseAt(200, nil, searchURL) track:track reason:&reason] == nil, "candidate count bounded");
}
static void SearchOrderAndDetailTests(NSDictionary *fixture, MiniSightLyricsTrack *track) {
    NSURL *url = [NSURL URLWithString:@"https://lrclib.net/api/search?q=fixture"];
    NSArray *records = fixture[@"search_late_closest"];
    NSString *reason = nil;
    for (NSUInteger a = 0; a < 3; ++a) for (NSUInteger b = 0; b < 3; ++b) if (a != b) {
        NSUInteger c = 3 - a - b;
        MiniSightLyricsTimeline *t = [MiniSightLyricsClient timelineForSearchResponseData:JSON(@[records[a], records[b], records[c]]) response:ResponseAt(200, nil, url) track:track reason:&reason];
        CHECK(t != nil && Equal([t lineAtTime:2], @"Unique closest") && Equal(reason, @"lyrics_timeline"), "all six orders choose unique global closest despite farther tie");
    }
    CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(@[records[2], records[2]]) response:ResponseAt(200, nil, url) track:track reason:&reason] != nil, "identical duration and LRC duplicates are not ambiguous");
    NSArray *values = @[NSNull.null, @"", @"untimed synthetic"];
    NSArray *reasons = @[@"no_synced_lyrics", @"no_synced_lyrics", @"lyrics_invalid_lrc"];
    for (NSUInteger i = 0; i < values.count; ++i) {
        NSMutableDictionary *record = Record(track); record[@"syncedLyrics"] = values[i];
        CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(@[record]) response:ResponseAt(200, nil, url) track:track reason:&reason] == nil && Equal(reason, reasons[i]), "exact candidate failure retains no-synced/invalid reason");
    }
    NSMutableDictionary *record = Record(track); record[@"instrumental"] = @YES; record[@"syncedLyrics"] = NSNull.null;
    CHECK([MiniSightLyricsClient timelineForSearchResponseData:JSON(@[record]) response:ResponseAt(200, nil, url) track:track reason:&reason] == nil && Equal(reason, @"lyrics_instrumental"), "exact instrumental reason is distinct from not-found");
}

static void BackoffTests(void) {
    NSDate *now = [NSDate dateWithTimeIntervalSince1970:0];
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(429, @{@"Retry-After": @"120"}) now:now attempt:0] == 120, "honor numeric Retry-After");
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(429, @{@"Retry-After": @"999999"}) now:now attempt:0] >= 999999, "never shorten server wait");
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(429, @{@"Retry-After": @"Thu, 01 Jan 1970 00:02:00 GMT"}) now:now attempt:0] == 120, "honor HTTP-date Retry-After");
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(429, @{@"Retry-After": @"broken"}) now:now attempt:0] == 30, "malformed header fallback");
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(429, @{}) now:now attempt:100] == 300, "bounded exponential backoff");
    CHECK([MiniSightLyricsClient retryDelayForResponse:Response(200, @{}) now:now attempt:0] == 0, "non throttle status");
}

static void TransportTests(MiniSightLyricsTrack *track) {
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(track)), nil); };
    MiniSightLyricsClient *client = Client();
    NSURLSessionConfiguration *config = [[client valueForKey:@"session"] configuration];
    CHECK(config.URLCache == nil && config.URLCredentialStorage == nil && config.HTTPCookieStorage == nil && !config.HTTPShouldSetCookies, "ephemeral privacy configuration");
    CHECK(config.timeoutIntervalForRequest <= 12 && config.timeoutIntervalForResource <= 15, "bounded timeouts");
    CHECK(Fetch(client, track) != nil, "fake network success");
    CHECK(Equal(lastRequest.HTTPMethod, @"GET") && lastRequest.HTTPBody == nil, "GET only");
    CHECK([lastRequest valueForHTTPHeaderField:@"User-Agent"].length > 10 && !lastRequest.HTTPShouldHandleCookies, "identified cookieless client");
    NSURLComponents *components = [NSURLComponents componentsWithURL:lastRequest.URL resolvingAgainstBaseURL:NO];
    CHECK(Equal(components.scheme, @"https") && Equal(components.host, @"lrclib.net") && Equal(components.path, @"/api/get"), "fixed HTTPS endpoint");
    CHECK(components.queryItems.count == 3, "only three approved metadata fields");
    NSMutableDictionary *query = [NSMutableDictionary dictionary];
    for (NSURLQueryItem *item in components.queryItems) query[item.name] = item.value;
    CHECK(Equal(query[@"track_name"], track.title) && Equal(query[@"artist_name"], track.artist) && [query[@"duration"] doubleValue] == track.duration, "exact query signature");
    NSUInteger before = starts;
    CHECK(Fetch(client, track) != nil && starts == before, "positive memory cache");
    __block BOOL cachedCallback = NO;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *result) { cachedCallback = YES; }];
    [client cancel]; Pump(0.05);
    CHECK(!cachedCallback, "cancel suppresses queued cache delivery");
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *result) { cachedCallback = YES; }];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ [client cancel]; });
    Pump(0.05);
    CHECK(!cachedCallback, "off-main cancel immediately invalidates queued delivery");
    __block BOOL first = NO, second = NO;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *result) { first = YES; }];
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *result) { second = YES; }];
    Wait(^BOOL{ return second; }, "latest cached completion");
    CHECK(!first, "replacement suppresses old queued callback");
    NSCache *cache = [client valueForKey:@"cache"];
    CHECK(cache.countLimit == 16 && cache.totalCostLimit == 4 * 1024 * 1024, "small cache limits");
    [client cancel];

    __block NSMutableArray<NSURLRequest *> *requests = [NSMutableArray array];
    NSArray *searchCandidates = @[
        @{@"trackName": @"Other Title", @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"[00:01]wrong title"},
        @{@"trackName": track.title, @"artistName": track.artist, @"duration": @60.5, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Fallback success"}
    ];
    handler = ^(FixtureProtocol *p) {
        [requests addObject:p.request];
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
        else Emit(p, 200, JSON(searchCandidates), nil);
    };
    client = Client(); before = starts;
    CHECK(Fetch(client, track) != nil && Equal(lastReason, @"lyrics_timeline"), "exact 404 falls back to exact search match");
    CHECK(starts == before + 2 && requests.count == 2, "maximum two requests for one track");
    CHECK(Equal(requests[0].URL.path, @"/api/get") && Equal(requests[1].URL.path, @"/api/search"), "exact request precedes search once");
    CHECK([requests[1].HTTPMethod isEqual:@"GET"] && !requests[1].HTTPBody && !requests[1].HTTPShouldHandleCookies, "search is credentialless GET");
    CHECK(Equal([requests[1] valueForHTTPHeaderField:@"User-Agent"], @"MiniSight-Lyrics/1.0 (+https://openminis.app)"), "same identified user agent on search");
    NSURLComponents *searchComponents = [NSURLComponents componentsWithURL:requests[1].URL resolvingAgainstBaseURL:NO];
    CHECK(Equal(searchComponents.scheme, @"https") && Equal(searchComponents.host, @"lrclib.net") && Equal(searchComponents.path, @"/api/search"), "fixed HTTPS search host and path");
    CHECK(searchComponents.queryItems.count == 1 && Equal(searchComponents.queryItems[0].name, @"q") && [searchComponents.queryItems[0].value containsString:track.title] && [searchComponents.queryItems[0].value containsString:track.artist], "encoded title and artist search query");
    Pump(0.36); before = starts;
    CHECK(Fetch(client, track) != nil && starts == before, "search success memory cache");
    [client cancel];

    handler = ^(FixtureProtocol *p) {
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
        else Emit(p, 200, JSON(@[
            @{@"trackName": @"Wrong Title", @"artistName": track.artist, @"duration": @60, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Wrong"},
            @{@"trackName": track.title, @"artistName": track.artist, @"duration": @63, @"instrumental": @NO, @"syncedLyrics": @"[00:01]Wrong duration"}
        ]), nil);
    };
    client = Client(); before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"lyrics_not_found") && starts == before + 2, "search with no exact candidate safely misses");
    id entry = [[client valueForKey:@"cache"] objectForKey:track.cacheKey];
    CHECK(entry != nil, "search no-match negative cache exists");
    [entry setValue:@0 forKey:@"expires"];
    Pump(0.36); before = starts;
    CHECK(Fetch(client, track) == nil && starts == before + 2, "expired miss still does exact then at most one search");
    [client cancel];

    handler = ^(FixtureProtocol *p) { Emit(p, 429, [@"not JSON" dataUsingEncoding:NSUTF8StringEncoding], @{@"Retry-After": @"120"}); };
    client = Client();
    CHECK(Fetch(client, track) == nil && [lastReason isEqual:@"lyrics_rate_limited"], "429 non JSON body");
    NSTimeInterval wait = [[client valueForKey:@"notBefore"] doubleValue] - NSProcessInfo.processInfo.systemUptime;
    CHECK(wait > 119 && wait <= 125, "429 cooldown and bounded positive jitter");
    before = starts; Pump(0.36);
    MiniSightLyricsTrack *other = [[MiniSightLyricsTrack alloc] initWithTitle:@"Fixture B" artist:track.artist duration:60];
    CHECK(Fetch(client, other) == nil && starts == before && [lastReason isEqual:@"lyrics_cooldown"], "429 cooldown also gates other tracks");
    Pump(0.05); CHECK(starts == before, "no automatic retry loop");
    [client cancel];

    NSMutableDictionary *big = Record(track);
    big[@"padding"] = [@"X" stringByPaddingToLength:1024 * 1024 withString:@"X" startingAtIndex:0];
    NSData *oversized = JSON(big);
    handler = ^(FixtureProtocol *p) { Emit(p, 200, oversized, nil); };
    client = Client();
    CHECK(Fetch(client, track) == nil && [lastReason isEqual:@"lyrics_oversized"], "streaming unknown-length body cap");
    [client cancel];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(track)), @{@"Content-Type": @"application/json", @"Content-Length": @"1048577"}); };
    client = Client();
    CHECK(Fetch(client, track) == nil && [lastReason isEqual:@"lyrics_oversized"], "declared-length body cap");
    [client cancel];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(other)), nil); };
    client = Client();
    CHECK(Fetch(client, track) == nil && [lastReason isEqual:@"lyrics_track_mismatch"], "fake transport mismatched track rejected");
    [client cancel];
}

static void CancellationTests(MiniSightLyricsTrack *track) {
    handler = ^(FixtureProtocol *p) { /* held; intentionally no response */ };
    MiniSightLyricsClient *client = Client();
    NSUInteger before = starts;
    __block NSUInteger oldCalls = 0, newCalls = 0;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *timeline) { oldCalls++; }];
    Wait(^BOOL{ return starts > before; }, "held request started");
    NSURLSessionDataTask *oldTask = [client valueForKey:@"task"];
    [client cancel];
    __block NSURLSessionResponseDisposition disposition = NSURLSessionResponseAllow;
    [client receivedResponse:Response(200, nil) task:oldTask completion:^(NSURLSessionResponseDisposition value) { disposition = value; }];
    [client receivedData:JSON(Record(track)) task:oldTask];
    [client finishedTask:oldTask error:nil];
    Pump(0.05);
    CHECK(disposition == NSURLSessionResponseCancel && oldCalls == 0, "cancel drops transport callbacks");
    Pump(0.36);
    // Begin another held request, then replace it after the bounded inter-request gap.
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *timeline) { oldCalls++; }];
    before = starts;
    Wait(^BOOL{ return starts > before; }, "second held request started");
    oldTask = [client valueForKey:@"task"];
    Pump(0.36);
    MiniSightLyricsTrack *other = [[MiniSightLyricsTrack alloc] initWithTitle:@"Fixture Next" artist:track.artist duration:60];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(other)), nil); };
    [client fetchTrack:other completion:^(MiniSightLyricsTimeline *timeline) {
        CHECK(timeline != nil, "new request survives stale callback"); newCalls++;
    }];
    NSURLSessionDataTask *newTask = [client valueForKey:@"task"];
    CHECK(newTask && newTask != oldTask, "one new active task");
    [client receivedResponse:Response(429, @{@"Retry-After": @"9999"}) task:oldTask completion:^(NSURLSessionResponseDisposition value) { disposition = value; }];
    CHECK(disposition == NSURLSessionResponseCancel, "old response rejected by task identity");
    CHECK([[client valueForKey:@"notBefore"] doubleValue] - NSProcessInfo.processInfo.systemUptime < 1, "old 429 cannot poison new cooldown");
    [client receivedData:JSON(Record(track)) task:oldTask];
    CHECK([[client valueForKey:@"body"] length] == 0, "old bytes not appended");
    [client finishedTask:oldTask error:nil];
    CHECK([client valueForKey:@"task"] == newTask, "old completion cannot finish new task");
    Wait(^BOOL{ return newCalls > 0; }, "replacement request finished");
    CHECK(oldCalls == 0 && newCalls == 1, "only current generation delivered");
    NSURLSession *session = [client valueForKey:@"session"];
    id<NSURLSessionTaskDelegate> delegate = (id)session.delegate;
    __block NSURLRequest *redirect = [NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.invalid/"]];
    [delegate URLSession:session task:newTask willPerformHTTPRedirection:Response(302, nil) newRequest:redirect completionHandler:^(NSURLRequest *request) { redirect = request; }];
    CHECK(redirect == nil, "redirect denied without forwarding signature");
    [client cancel];
    __block BOOL backgroundDone = NO;
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(track)), nil); };
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        [client fetchTrack:track completion:^(MiniSightLyricsTimeline *timeline) { oldCalls++; }];
        [client cancel];
        dispatch_async(dispatch_get_main_queue(), ^{ backgroundDone = YES; });
    });
    Wait(^BOOL{ return backgroundDone; }, "background API dispatch completed");
    Pump(0.05); CHECK(oldCalls == 0, "background fetch then cancel ordered");
    __weak MiniSightLyricsClient *weakClient;
    @autoreleasepool {
        MiniSightLyricsClient *temporary = Client(); weakClient = temporary;
        [temporary fetchTrack:track completion:^(MiniSightLyricsTimeline *timeline) {}];
        temporary = nil;
    }
    Pump(0.05); CHECK(weakClient == nil, "delegate does not retain client");
}

#include "minisight_lyrics_20261122/native_client.inc"

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        CHECK(argc == 2, "fixture path argument");
        NSDictionary *fixture = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]] options:0 error:NULL];
        CHECK([fixture isKindOfClass:NSDictionary.class], "load synthetic fixture");
        NSDictionary *meta = fixture[@"track"];
        MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc] initWithTitle:meta[@"title"] artist:meta[@"artist"] duration:[meta[@"duration"] doubleValue]];
        CHECK(track != nil, "synthetic track valid");
        ParserTests(fixture); EvaluatorTests(track); SearchEvaluatorTests(fixture, track);
        SearchOrderAndDetailTests(fixture, track); BackoffTests();
        TransportTests(track); CacheDeadlineAndPendingCancelTests(track); CancellationTests(track);
        handler = nil; lastRequest = nil;
        printf("NATIVE PASS: %lu checks; synthetic Fake NSURLProtocol only\n", (unsigned long)checks);
    }
    return 0;
}
