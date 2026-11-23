// Synthetic-only additions. Uses production .m plus the catch-all FixtureProtocol.
// No live URL loader, device media, iOS build, account, or microphone is involved.
static void ExplicitUnsyncedFallbackTests(MiniSightLyricsTrack *track) {
    for (id empty in @[NSNull.null, @""]) {
        NSMutableDictionary *unsynced = Record(track); unsynced[@"syncedLyrics"] = empty;
        handler = ^(FixtureProtocol *p) {
            if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 200, JSON(unsynced), nil);
            else Emit(p, 200, JSON(@[Record(track)]), nil);
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        MiniSightLyricsTimeline *t = Fetch(client, track);
        CHECK(t != nil && Equal([t lineAtTime:2], @"Synthetic line") && Equal(lastReason, @"lyrics_timeline"), "validated null/empty exact LRC searches once and returns synced same track");
        CHECK(starts == before + 2, "empty exact response adds only one search");
        before = starts;
        CHECK(Fetch(client, track) != nil && starts == before, "unsynced rescue positive cache skips both endpoints");
        [client cancel];
    }
    for (NSString *kind in @[@"instrumental", @"invalid_lrc", @"missing_field", @"wrong_artist", @"wrong_duration", @"wrong_type"]) {
        NSMutableDictionary *record = Record(track);
        if (Equal(kind, @"instrumental")) { record[@"instrumental"] = @YES; record[@"syncedLyrics"] = NSNull.null; }
        if (Equal(kind, @"invalid_lrc")) record[@"syncedLyrics"] = @"untimed synthetic";
        if (Equal(kind, @"missing_field")) [record removeObjectForKey:@"syncedLyrics"];
        if (Equal(kind, @"wrong_artist")) { record[@"artistName"] = @"Other Artist"; record[@"syncedLyrics"] = NSNull.null; }
        if (Equal(kind, @"wrong_duration")) { record[@"duration"] = @62.001; record[@"syncedLyrics"] = NSNull.null; }
        if (Equal(kind, @"wrong_type")) record[@"syncedLyrics"] = @42;
        handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(record), nil); };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && starts == before + 1, "instrumental/invalid/missing/mismatched exact response never searches");
        CHECK(!Equal(lastReason, @"no_synced_lyrics"), "rejected schema or wrong track cannot impersonate explicit unsynced result");
        [client cancel];
    }
}

static void SearchBoundaryTransportTests(NSDictionary *fixture, MiniSightLyricsTrack *track) {
    NSMutableDictionary *wrong = Record(track); wrong[@"artistName"] = @"Other Artist";
    NSMutableDictionary *empty = Record(track); empty[@"syncedLyrics"] = NSNull.null;
    NSMutableDictionary *conflict = Record(track); conflict[@"syncedLyrics"] = @"[00:01]Conflicting lyrics";
    NSMutableArray *overflow = [NSMutableArray array]; for (unsigned i=0;i<21;i++) [overflow addObject:Record(track)];
    NSArray *cases = @[
        @[@[wrong], @"lyrics_not_found", @YES],
        @[fixture[@"search_ambiguous"], @"lyrics_response_rejected", @NO],
        @[@[Record(track), conflict], @"lyrics_response_rejected", @NO],
        @[@[empty], @"no_synced_lyrics", @YES],
        @[overflow, @"lyrics_response_rejected", @NO],
        @[@{}, @"lyrics_response_rejected", @NO]
    ];
    for (NSArray *test in cases) {
        handler = ^(FixtureProtocol *p) {
            if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
            else Emit(p, 200, JSON(test[0]), nil);
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && Equal(lastReason, test[1]) && starts == before + 2, "strict search wrong artist/tie/conflict/no-LRC/overflow rejects with at most two requests");
        id entry = [[client valueForKey:@"cache"] objectForKey:track.cacheKey];
        CHECK((entry != nil) == [test[2] boolValue], "only conclusive bounded search misses use negative cache, never rejected payloads");
        if (entry) {
            before = starts;
            CHECK(Fetch(client, track) == nil && Equal(lastReason, test[1]) && starts == before, "negative cache preserves detail and prevents repeated fallback");
        }
        [client cancel];
    }
    for (NSNumber *status in @[@302, @404, @429, @503]) {
        handler = ^(FixtureProtocol *p) {
            if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
            else Emit(p, status.integerValue, nil, @{@"Retry-After": @"120", @"Location": @"https://example.invalid/never"});
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && starts == before + 2, "search error or redirect never recurses or follows Location");
        if (status.integerValue == 429 || status.integerValue == 503) {
            CHECK(Equal(lastReason, status.integerValue == 429 ? @"lyrics_rate_limited" : @"lyrics_service_unavailable"), "both throttle statuses retain fixed detail");
            double delay = [[client valueForKey:@"notBefore"] doubleValue] - NSProcessInfo.processInfo.systemUptime;
            CHECK(delay > 119 && delay <= 125, "search Retry-After plus bounded positive jitter honored");
            CHECK([[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil, "throttle is not negative cache");
            before = starts;
            MiniSightLyricsTrack *other = [[MiniSightLyricsTrack alloc] initWithTitle:@"Cooling Next" artist:track.artist duration:60];
            for (unsigned i=0;i<5;i++) CHECK(Fetch(client, other) == nil && Equal(lastReason, @"lyrics_cooldown"), "throttle also gates other track keys");
            CHECK(starts == before, "repeated fetches during backoff never start protocol");
        }
        Pump(.05); CHECK(starts == before + (status.integerValue == 302 || status.integerValue == 404 ? 2 : 0), "no scheduled automatic retry");
        [client cancel];
    }
    for (NSNumber *code in @[@(NSURLErrorTimedOut), @(NSURLErrorNotConnectedToInternet)]) {
        handler = ^(FixtureProtocol *p) {
            if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
            else [p.client URLProtocol:p didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:code.integerValue userInfo:nil]];
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && starts == before + 2, "search timeout/network failure has no third request");
        CHECK(Equal(lastReason, code.integerValue == NSURLErrorTimedOut ? @"lyrics_timeout" : @"lyrics_network_error"), "search network detail retained");
        CHECK([[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil, "search transport failures never cached as not-found");
        CHECK([[client valueForKey:@"notBefore"] doubleValue] > NSProcessInfo.processInfo.systemUptime + 4, "search transport failure imposes bounded cooldown");
        [client cancel];
    }
}

static void SearchCancelDeadlineTests(MiniSightLyricsTrack *track) {
    handler = ^(FixtureProtocol *p) { Emit(p, 404, nil, nil); };
    MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
    __block NSUInteger expired = 0;
    [client fetchTrack:track result:^(MiniSightLyricsTimeline *t, NSString *reason) {
        CHECK(t == nil && Equal(reason, @"lyrics_timeout"), "expired queued search delivers only timeout"); expired++;
    }];
    Wait(^BOOL{ return [[client valueForKey:@"searchPending"] boolValue]; }, "queued search reached before deadline injection");
    [client setValue:@0 forKey:@"deadline"];
    Wait(^BOOL{ return expired > 0; }, "expired queued search completes");
    CHECK(expired == 1 && starts == before + 1 && [client valueForKey:@"task"] == nil, "expired queued search starts no second request");
    [client cancel];

    // Replacement while fallback is queued must invalidate that queued block.
    handler = ^(FixtureProtocol *p) { Emit(p, 404, nil, nil); };
    client = Client(); before = starts; __block NSUInteger oldCalls = 0, newCalls = 0;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *t) { oldCalls++; }];
    Wait(^BOOL{ return [[client valueForKey:@"searchPending"] boolValue]; }, "replacement reaches pending fallback");
    MiniSightLyricsTrack *other = [[MiniSightLyricsTrack alloc] initWithTitle:@"Fixture Replaced" artist:track.artist duration:60];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(other)), nil); };
    [client fetchTrack:other completion:^(MiniSightLyricsTimeline *t) { CHECK(t != nil, "replacement GET succeeds"); newCalls++; }];
    Wait(^BOOL{ return newCalls > 0; }, "replacement completion"); Pump(.4);
    CHECK(oldCalls == 0 && newCalls == 1 && starts == before + 2, "track switch while queued suppresses old search and old result");
    [client cancel];

    // A real fake-protocol search is held, then its delegate completion arrives late.
    handler = ^(FixtureProtocol *p) { if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil); };
    client = Client(); before = starts; oldCalls = 0;
    [client fetchTrack:track completion:^(MiniSightLyricsTimeline *t) { oldCalls++; }];
    Wait(^BOOL{ return starts == before + 2; }, "active held search reached");
    NSURLSessionDataTask *oldTask = [client valueForKey:@"task"];
    dispatch_sync(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{ [client cancel]; });
    __block NSURLSessionResponseDisposition disposition = NSURLSessionResponseAllow;
    [client receivedResponse:ResponseAt(429, @{@"Retry-After": @"9999"}, [NSURL URLWithString:@"https://lrclib.net/api/search"]) task:oldTask completion:^(NSURLSessionResponseDisposition d) { disposition = d; }];
    [client receivedData:JSON(@[Record(track)]) task:oldTask];
    [client finishedTask:oldTask error:nil];
    Pump(.05);
    CHECK(disposition == NSURLSessionResponseCancel && oldCalls == 0, "off-main cancel immediately fences active-search response/data/completion");
    CHECK([[client valueForKey:@"notBefore"] doubleValue] < NSProcessInfo.processInfo.systemUptime + 1, "late cancelled 429 cannot poison cooldown");
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(other)), nil); };
    CHECK(Fetch(client, other) != nil, "new track remains fetchable after cancelled search");
    [client receivedData:JSON(@[Record(track)]) task:oldTask];
    [client finishedTask:oldTask error:nil];
    CHECK([[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil && oldCalls == 0, "late old search never contaminates cache or callback");
    [client cancel];

    // The callback arrives after the shared deadline, even though transport exists.
    __block FixtureProtocol *held = nil;
    handler = ^(FixtureProtocol *p) {
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil); else held = p;
    };
    client = Client(); before = starts; expired = 0;
    [client fetchTrack:track result:^(MiniSightLyricsTimeline *t, NSString *reason) {
        CHECK(t == nil && Equal(reason, @"lyrics_timeout"), "late active search cannot deliver timeline"); expired++;
    }];
    Wait(^BOOL{ return held != nil; }, "held search for expiry");
    [client setValue:@0 forKey:@"deadline"];
    Emit(held, 200, JSON(@[Record(track)]), nil);
    Wait(^BOOL{ return expired > 0; }, "late active search callback");
    CHECK(expired == 1 && starts == before + 2 && [[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil, "expired active callback never caches lyrics or starts another request");
    [client cancel]; held = nil;

    client = Client(); [client setValue:@0 forKey:@"deadline"]; expired = 0;
    before = starts;
    MiniSightLyricsTimeline *cached = [MiniSightLyricsTimeline timelineWithLRC:@"[00:01]Synthetic line" duration:60];
    [client deliver:cached reason:@"lyrics_timeline" generation:[[client valueForKey:@"generation"] unsignedIntegerValue] completion:^(MiniSightLyricsTimeline *t, NSString *reason) {
        CHECK(t == nil && Equal(reason,@"lyrics_timeout"), "queued delivery rechecks its captured monotonic deadline"); expired++;
    }];
    Wait(^BOOL{ return expired > 0; }, "expired queued delivery callback");
    CHECK(expired == 1 && starts == before, "expired delivery starts no transport");
    [client cancel];
}

static void SearchSizeAndRedirectTests(MiniSightLyricsTrack *track) {
    NSMutableDictionary *record = Record(track);
    record[@"padding"] = [@"X" stringByPaddingToLength:1024*1024 withString:@"X" startingAtIndex:0];
    for (NSNumber *declared in @[@NO, @YES]) {
        handler = ^(FixtureProtocol *p) {
            if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
            else Emit(p, 200, declared.boolValue ? JSON(@[Record(track)]) : JSON(@[record]), declared.boolValue ? @{@"Content-Type": @"application/json", @"Content-Length": @"1048577"} : nil);
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && Equal(lastReason, @"lyrics_oversized") && starts == before + 2, "search stream and declared byte caps stop at second request");
        CHECK([[client valueForKey:@"cache"] objectForKey:track.cacheKey] == nil, "oversized search is never negative cache");
        [client cancel];
    }
    handler = ^(FixtureProtocol *p) { Emit(p, 302, nil, @{@"Location": @"https://example.invalid/never"}); };
    MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"lyrics_http") && starts == before + 1, "exact redirect is neither followed nor searched");
    [client cancel];
    handler = ^(FixtureProtocol *p) {
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
        else Emit(p, 200, JSON(@[Record(track)]), @{@"Content-Type": @"text/html"});
    };
    client = Client(); before = starts;
    CHECK(Fetch(client, track) == nil && Equal(lastReason, @"lyrics_response_rejected") && starts == before + 2, "search MIME rejection does not parse or recurse");
    [client cancel];
}

static void LyricsDiagnosticRoundtripTests(MiniSightLyricsTrack *track) {
    NSString *container = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    MSDiagConfigure(NO, container); // Only a private synthetic directory, no app settings.
    handler = ^(FixtureProtocol *p) { Emit(p, 404, nil, nil); };
    MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
    CHECK(Fetch(client, track) == nil && starts == before + 2, "diagnostic exact404-search404 flow");
    before = starts;
    for (unsigned i=0;i<5;i++) CHECK(Fetch(client, track) == nil && starts == before, "diagnostic negative cache never reaches network");
    [client cancel];
    handler = ^(FixtureProtocol *p) { Emit(p, 200, JSON(Record(track)), nil); };
    client = Client(); CHECK(Fetch(client, track) != nil, "diagnostic exact success");
    CHECK(Fetch(client, track) != nil, "diagnostic positive cache"); [client cancel];
    NSMutableArray *overflow = [NSMutableArray array]; for(unsigned i=0;i<21;i++) [overflow addObject:Record(track)];
    handler = ^(FixtureProtocol *p) {
        if ([p.request.URL.path isEqual:@"/api/get"]) Emit(p, 404, nil, nil);
        else Emit(p, 200, JSON(overflow), nil);
    };
    client = Client(); CHECK(Fetch(client, track) == nil && Equal(lastReason, @"lyrics_response_rejected"), "diagnostic over-limit rejection"); [client cancel];
    MSDiagEvent(@"lyrics", @"finish", @"ok", @{@"http": @418, @"lyrics_route": @"PRIVATE_ROUTE",
        @"lyrics_detail": @"PRIVATE_REASON", @"title": @"PRIVATE_TITLE", @"artist": @"PRIVATE_ARTIST",
        @"lyric": @"PRIVATE_LYRIC", @"url": @"https://PRIVATE_URL.invalid", @"cookies": @"PRIVATE_COOKIE"});
    NSString *path = [container stringByAppendingPathComponent:@"Documents/MiniSight/diagnostic-app.log"];
    Wait(^BOOL{ return [[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL] containsString:@"418"]; }, "diagnostic writer drained through sentinel");
    NSString *text = [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL];
    CHECK(text.length && ![text containsString:@"PRIVATE_"] && ![text containsString:track.title] && ![text containsString:track.artist] && ![text containsString:@"Synthetic line"] && ![text containsString:@"https://"], "production writer persists no metadata/fullURL/lyric/cookie or unlisted enum");
    BOOL exact404=NO, search404=NO, negative404=NO, positive=NO, rejected21=NO;
    NSUInteger negativeEvents=0;
    NSSet *keys = [NSSet setWithArray:@[@"lyrics_route", @"lyrics_detail", @"generation", @"http", @"bytes", @"count"]];
    for (NSString *line in [text componentsSeparatedByString:@"\n"]) {
        NSRange marker = [line rangeOfString:@" event="]; if (marker.location == NSNotFound) continue;
        NSDictionary *event = [NSJSONSerialization JSONObjectWithData:[[line substringFromIndex:NSMaxRange(marker)] dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
        NSDictionary *f = event[@"fields"]; CHECK([event[@"feature"] isEqual:@"lyrics"], "only lyrics feature in isolated diagnostic fixture");
        for (NSString *key in f) CHECK([keys containsObject:key], "diagnostic contains only six explicit fixed/numeric fields");
        NSString *route = f[@"lyrics_route"];
        NSInteger http = [f[@"http"] integerValue];
        CHECK(http >= 0 && http <= 599 && [f[@"count"] unsignedIntegerValue] <= 21 && [f[@"bytes"] unsignedIntegerValue] <= 1024*1024, "diagnostic numeric budgets remain bounded");
        if (Equal(route,@"exact") && http==404) exact404=YES;
        if (Equal(route,@"search") && http==404) search404=YES;
        if (Equal(route,@"negative_cache") && http==404) { negative404=YES; negativeEvents++; }
        if (Equal(route,@"positive_cache")) positive=YES;
        if (Equal(route,@"search") && http==200 && [f[@"count"] integerValue]==21 && Equal(f[@"lyrics_detail"],@"lyrics_response_rejected")) rejected21=YES;
    }
    CHECK(exact404 && search404 && negative404 && positive && rejected21, "get404/search404/cache paths and candidate rejection survive real log roundtrip");
    CHECK(negativeEvents == 1, "repeated identical cache facts emit at most once per minute");
    MSDiagConfigure(NO, nil);
    [NSFileManager.defaultManager removeItemAtPath:container error:NULL];
}
