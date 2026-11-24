// Included by the Foundation client fixture; inherits its catch-all NSURLProtocol.
// No live network. Assertions exercise production cache/task/deadline paths.
static void CacheDeadlineAndPendingCancelTests(MiniSightLyricsTrack *track) {
    NSMutableDictionary *unsynced = Record(track); unsynced[@"syncedLyrics"] = NSNull.null;
    handler = ^(FixtureProtocol *p) {
        if (QQEmptyReply(p,track,YES)) return;
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
        else Emit(p, 200, JSON(@[unsynced]), nil);
    };
    MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"no_synced_lyrics") && starts == before + 4, "both sources lack synced lyrics: retain the confirmed reason");
    id entry = [[client valueForKey:@"cache"] objectForKey:track.cacheKey];
    CHECK(entry && Equal([entry valueForKey:@"reason"], @"no_synced_lyrics"), "negative entry stores fixed original reason");
    double ttl = [[entry valueForKey:@"expires"] doubleValue] - NSProcessInfo.processInfo.systemUptime;
    CHECK(ttl > 298 && ttl <= 300, "negative memory TTL remains 300 seconds");
    before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"no_synced_lyrics") && starts == before, "negative hit neither fetches nor relabels as not-found");
    __block NSUInteger cancelledCalls = 0;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *t) { cancelledCalls++; }];
    [client cancel]; Pump(.05);
    CHECK(cancelledCalls == 0, "negative queued delivery is also generation fenced");
    MiniSightLyricsTrack *other = [[MiniSightLyricsTrack alloc] initWithTitle:@"Fixture Unrelated" artist:track.artist duration:60];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(other)), nil); };
    before = starts;
    CHECK(Fetch(client, other) != nil && starts == before + 1, "negative cache for previous key does not hide new track");
    [client cancel];

    // A strictly validated empty 200 may search ONCE, never recurse on empty search.
    handler = ^(FixtureProtocol *p) {
        if (QQEmptyReply(p,track,YES)) return;
        Emit(p, 200, JSON([p.request.URL.path isEqual:@"/api/get"] ? (id)unsynced : (id)@[unsynced]), nil);
    };
    client = Client(); before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"no_synced_lyrics") && starts == before + 4, "one search per provider, no recursion after explicit unsynced result");
    [client cancel];
    for (NSNumber *code in @[@(NSURLErrorTimedOut), @(NSURLErrorNotConnectedToInternet)]) {
        handler = ^(FixtureProtocol *p) { [p.client URLProtocol:p didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:code.integerValue userInfo:nil]]; };
        client = Client(); before = starts;
        CHECK(Fetch(client, track) == nil && starts == before + 1, "transport errors never invoke search");
        CHECK(Equal(lastReason, code.integerValue == NSURLErrorTimedOut ? @"lyrics_timeout" : @"lyrics_network_error"), "transport errors retain fixed detail");
        CHECK([[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil, "transport errors never become negative cache");
        [client cancel];
    }

    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(track)), nil); };
    client = Client(); [client setValue:@(NSProcessInfo.processInfo.systemUptime) forKey:@"lastRequestAt"];
    before = starts; __block NSUInteger expiredCalls = 0;
    [client fetchTrack:track result:^(MiniSightLyricsTimeline *t, NSString *reason) {
        CHECK(t == nil && Equal(reason, @"lyrics_timeout"), "late queued GET returns timeout, never a timeline"); expiredCalls++;
    }];
    CHECK([[client valueForKey:@"requestPending"] boolValue], "queued GET seam actually reached");
    [client setValue:@0 forKey:@"deadline"];
    Wait(^BOOL{ return expiredCalls > 0; }, "expired queued GET completion");
    CHECK(expiredCalls == 1 && starts == before && [client valueForKey:@"task"] == nil, "expired dispatch cannot start even a fake protocol request");
    [client cancel];

    handler = ^(FixtureProtocol *p) { Emit(p, 404, nil, nil); };
    client = Client(); before = starts; __block NSUInteger calls = 0;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *t) { calls++; }];
    Wait(^BOOL{ return [[client valueForKey:@"searchPending"] boolValue]; }, "404 delayed search seam reached");
    CHECK(starts == before + 1, "only exact request before queued fallback");
    [client cancel]; Pump(.4);
    CHECK(starts == before + 1 && calls == 0, "OFF/cancel between 404 and delayed search suppresses IO and callback");
}
