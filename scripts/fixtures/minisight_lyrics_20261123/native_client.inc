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
        else if ([p.request.URL.host isEqual:@"lrclib.net"]) Emit(p, 200, JSON(test[0]), nil);
        else { CHECK([test[2] boolValue], "bad/ambiguous LRCLIB input never queries QQ"); CHECK(QQEmptyReply(p,track,Equal(test[1],@"no_synced_lyrics")), "QQ conclusive fixture"); }
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        NSUInteger expected = ![test[2] boolValue] ? 2 : (Equal(test[1],@"no_synced_lyrics") ? 4 : 3);
        CHECK(Fetch(client, track) == nil && Equal(lastReason, test[1]) && starts == before + expected, "wrong artist/no-lyrics need QQ confirmation; tie/conflict/overflow never leave LRCLIB");
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
            else if (QQEmptyReply(p,track,NO)) return;
            else Emit(p, status.integerValue, nil, @{@"Retry-After": @"120", @"Location": @"https://example.invalid/never"});
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client, track) == nil && starts == before + (status.integerValue == 404 ? 3 : 2), "only 404 can fall back to QQ; never recurse or follow Location");
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
        Pump(.05); CHECK(starts == before + (status.integerValue == 404 ? 3 : status.integerValue == 302 ? 2 : 0), "no scheduled automatic retry");
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
    handler = ^(FixtureProtocol *p) { if (!QQEmptyReply(p,track,YES)) Emit(p,404,nil,nil); };
    MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
    CHECK(Fetch(client, track) == nil && starts == before + 4, "diagnostic exact404-search404 then QQ explicit no-sync");
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
    BOOL exact404=NO, search404=NO, qqSearchOK=NO, qqNoSync=NO, negative200=NO, positive=NO, rejected21=NO;
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
        if (Equal(route,@"qq_search") && http==200 && Equal(event[@"result"],@"ok")) qqSearchOK=YES;
        if (Equal(route,@"qq_lyric") && http==200 && Equal(f[@"lyrics_detail"],@"no_synced_lyrics")) qqNoSync=YES;
        if (Equal(route,@"negative_cache") && http==200 && Equal(f[@"lyrics_detail"],@"no_synced_lyrics")) { negative200=YES; negativeEvents++; }
        if (Equal(route,@"positive_cache")) positive=YES;
        if (Equal(route,@"search") && http==200 && [f[@"count"] integerValue]==21 && Equal(f[@"lyrics_detail"],@"lyrics_response_rejected")) rejected21=YES;
    }
    CHECK(exact404 && search404 && qqSearchOK && qqNoSync && negative200 && positive && rejected21, "get404/search404/cache paths and candidate rejection survive real log roundtrip");
    CHECK(negativeEvents == 1, "repeated identical cache facts emit at most once per minute");
    MSDiagConfigure(NO, nil);
    [NSFileManager.defaultManager removeItemAtPath:container error:NULL];
}
// Synthetic QQ stage transport tests; every URL is intercepted by FixtureProtocol.
static NSData *QQJSONPData(NSDictionary *dict) {
    NSData *json=JSON(dict); NSString *inner=[[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding];
    return [[NSString stringWithFormat:@"MusicJsonCallback (%@);",inner] dataUsingEncoding:NSUTF8StringEncoding];
}
static void QQFallbackNativeTests(MiniSightLyricsTrack *track) {
    NSString *b64=[[@"[00:01]QQ synthetic line\n[00:03]" dataUsingEncoding:NSUTF8StringEncoding] base64EncodedStringWithOptions:0];
    __block NSUInteger qqSearches=0, qqLyrics=0;
    handler=^(FixtureProtocol *p) { NSURL *u=p.request.URL;
        NSDictionary *headers=p.request.allHTTPHeaderFields;
        CHECK(!headers[@"Cookie"] && !headers[@"cookie"] && !headers[@"Authorization"] && !headers[@"authorization"],"no QQ cookie/auth");
        if([u.host isEqual:@"lrclib.net"]) { CHECK([u.path isEqual:@"/api/get"] || [u.path isEqual:@"/api/search"],"LRCLIB route allowlisted"); Emit(p,404,nil,nil); return; }
        if([u.host isEqual:@"c.y.qq.com"] && [u.path isEqual:@"/soso/fcgi-bin/client_search_cp"]) {
            qqSearches++; NSURLComponents *searchParts=[NSURLComponents componentsWithURL:u resolvingAgainstBaseURL:NO]; NSArray<NSURLQueryItem *> *searchItems=searchParts.queryItems;
            CHECK(searchItems.count==1 && [searchItems.firstObject.name isEqual:@"w"],"QQ search uses validated public-probe parameter");
            CHECK([[p.request valueForHTTPHeaderField:@"Referer"] isEqual:@"https://y.qq.com/"],"QQ search carries verified public-page Referer");
            NSDictionary *wrong=@{@"songname":track.title,@"singer":@[@{@"name":@"Guest Artist"}],@"interval":@(track.duration),@"songmid":@"wrong01"};
            NSDictionary *nearer=@{@"songname":track.title,@"singer":@[@{@"name":track.artist}],@"interval":@(track.duration+0.25),@"songmid":@"nearer01"};
            NSDictionary *exact=@{@"songname":track.title,@"singer":@[@{@"name":track.artist}],@"interval":@(track.duration),@"songmid":@"abc123"};
            Emit(p,200,QQJSONPData(@{@"code":@0,@"data":@{@"song":@{@"list":@[wrong,nearer,exact]}}}),@{@"Content-Type":@"application/x-javascript"}); return;
        }
        if([u.host isEqual:@"c.y.qq.com"] && [u.path isEqual:@"/lyric/fcgi-bin/fcg_query_lyric_new.fcg"]) {
            qqLyrics++; NSURLComponents *parts=[NSURLComponents componentsWithURL:u resolvingAgainstBaseURL:NO]; NSArray<NSURLQueryItem *> *items=parts.queryItems;
            CHECK(items.count==2 && [items[0].name isEqual:@"songmid"] && [items[0].value isEqual:@"abc123"] && [items[1].name isEqual:@"g_tk"] && [items[1].value isEqual:@"5381"],"QQ lyric uses unique closest exact MID and verified params");
            CHECK([[p.request valueForHTTPHeaderField:@"Referer"] isEqual:@"https://y.qq.com/portal/player.html"],"QQ lyrics carries verified player Referer");
            Emit(p,200,QQJSONPData(@{@"code":@0,@"lyric":b64}),@{@"Content-Type":@"text/html"}); return;
        }
        CHECK(NO,"unexpected fixture route");
    };
    MiniSightLyricsClient *client=Client(); NSUInteger before=starts; MiniSightLyricsTimeline *t=Fetch(client,track);
    CHECK(t && Equal([t lineAtTime:2],@"QQ synthetic line"),"LRCLIB miss falls back to same-track QQ timed lyrics");
    CHECK(starts==before+4 && qqSearches==1 && qqLyrics==1,"fallback has one bounded search and one lyric request"); [client cancel];

    // A valid empty QQ candidate list is conclusive for five minutes; malformed
    // service responses, non-200, and unverified schemas must never be cached.
    for(NSString *mode in @[@"empty",@"malformed",@"error"]) {
        __block NSUInteger searches=0; handler=^(FixtureProtocol *p) { NSURL *u=p.request.URL;
            if([u.host isEqual:@"lrclib.net"]) { Emit(p,404,nil,nil); return; }
            if([u.path isEqual:@"/soso/fcgi-bin/client_search_cp"]) { searches++; if([mode isEqual:@"empty"]) Emit(p,200,QQJSONPData(@{@"code":@0,@"data":@{@"song":@{@"list":@[]}}}),@{@"Content-Type":@"application/x-javascript"}); else if([mode isEqual:@"error"]) Emit(p,503,nil,nil); else Emit(p,200,QQJSONPData(@{@"code":@0,@"data":@{@"song":@{@"list":@[@42]}}}),@{@"Content-Type":@"application/x-javascript"}); return; }
            CHECK(NO,"QQ miss case must not request lyrics");
        };
        client=Client(); NSUInteger count=starts; CHECK(Fetch(client,track)==nil,"QQ empty/error does not fabricate lyrics"); NSUInteger after=starts;
        CHECK(after==count+3 && searches==1,"two LRCLIB requests then one QQ search");
        id entry=[[client valueForKey:@"cache"] objectForKey:track.cacheKey];
        CHECK((entry!=nil)==[mode isEqual:@"empty"],"cache only conclusive QQ miss");
        if([mode isEqual:@"empty"]) CHECK(Fetch(client,track)==nil && starts==after,"conclusive QQ no-match is briefly cached");
        else if ([mode isEqual:@"malformed"]) CHECK(Fetch(client,track)==nil && starts==after+3 && searches==2,"malformed QQ is retryable");
        else {
            CHECK(Fetch(client,track)==nil && Equal(lastReason,@"lyrics_cooldown") && starts==after+2 && searches==1,"QQ 503 cools only QQ; do not retry QQ early");
            MiniSightLyricsTrack *other=[[MiniSightLyricsTrack alloc] initWithTitle:@"Unrelated" artist:track.artist duration:60];
            handler=^(FixtureProtocol *p){CHECK([p.request.URL.host isEqual:@"lrclib.net"],"primary remains independent"); Emit(p,200,JSON(Record(other)),nil);};
            CHECK(Fetch(client,other)!=nil && starts==after+3,"QQ outage cannot block a primary hit");
        }
        [client cancel];
    }

    // An explicit empty lyric body is a confirmed no-sync result, not malformed
    // text; only that exact state is cached, while absent fields are rejected.
    for(NSString *mode in @[@"empty",@"absent",@"invalid",@"echo_mismatch",@"only_blank"]) {
        handler=^(FixtureProtocol *p) { NSURL *u=p.request.URL;
            if([u.host isEqual:@"lrclib.net"]) { Emit(p,404,nil,nil); return; }
            if([u.path isEqual:@"/soso/fcgi-bin/client_search_cp"]) {
                NSDictionary *song=@{@"songname":track.title,@"singer":@[@{@"name":track.artist}],@"interval":@(track.duration),@"songmid":@"abc123"};
                Emit(p,200,QQJSONPData(@{@"code":@0,@"data":@{@"song":@{@"list":@[song]}}}),@{@"Content-Type":@"application/x-javascript"}); return;
            }
            if([u.path isEqual:@"/lyric/fcgi-bin/fcg_query_lyric_new.fcg"]) {
                NSDictionary *payload=[mode isEqual:@"absent"]?@{@"code":@0}:@{@"code":@0,@"lyric":[mode isEqual:@"empty"]?@"":@"not-base64-LRC"};
                if ([mode isEqual:@"only_blank"]) payload=@{@"code":@0,@"lyric":[[@"[00:00]\n[00:06]" dataUsingEncoding:NSUTF8StringEncoding] base64EncodedStringWithOptions:0]};
                if ([mode isEqual:@"echo_mismatch"]) payload=@{@"code":@0,@"lyric":b64,@"songmid":@"elsewhere"};
                Emit(p,200,QQJSONPData(payload),@{@"Content-Type":@"text/html"}); return;
            }
        };
        client=Client(); NSUInteger count=starts; CHECK(Fetch(client,track)==nil,"QQ empty or invalid lyrics never display garbage"); NSUInteger after=starts;
        if ([mode isEqual:@"echo_mismatch"]) CHECK(Equal(lastReason,@"lyrics_track_mismatch"),"conflicting QQ response identity never draws lyrics");
        if([mode isEqual:@"empty"] || [mode isEqual:@"only_blank"]) CHECK(Equal(lastReason,@"no_synced_lyrics") && Fetch(client,track)==nil && starts==after,"explicit QQ no-sync is briefly cached");
        else CHECK(Fetch(client,track)==nil && starts==after+4,"missing or invalid QQ lyric schema is not negative-cached");
        CHECK(after==count+4,"QQ lyric path bounded to four requests"); [client cancel];
    }
}

static void QQQueuedLifecycleTests(MiniSightLyricsTrack *track) {
    MiniSightLyricsTrack *next = [[MiniSightLyricsTrack alloc] initWithTitle:@"Replacement" artist:track.artist duration:60];
    for (NSString *mode in @[@"switch", @"cancel", @"timeout"]) {
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        handler = ^(FixtureProtocol *p) {
            CHECK(Equal(p.request.URL.host,@"lrclib.net"), "no QQ dispatch after replacement/cancel/expiry");
            if (Equal(p.request.URL.path,@"/api/get")) Emit(p,404,nil,nil);
            else Emit(p,200,JSON(@[]),nil);
        };
        __block NSUInteger oldCalls=0, newCalls=0;
        [client fetchTrack:track result:^(MiniSightLyricsTimeline *t, NSString *reason){
            CHECK(Equal(mode,@"timeout") && !t && Equal(reason,@"lyrics_timeout"),"only timed out current QQ ticket may complete"); oldCalls++;
        }];
        Wait(^BOOL{ return [[client valueForKey:@"qqSearchAttempted"] boolValue] && [[client valueForKey:@"qqSearchPending"] boolValue]; },"queued QQ search reached");
        CHECK(starts==before+2,"only two primary requests before QQ dispatch");
        if (Equal(mode,@"switch")) {
            // Keep B's LRCLIB search pending when A's QQ block fires. Comparing
            // merely current==active cannot distinguish these two tickets.
            [client setValue:@0 forKey:@"lastRequestAt"];
            handler=^(FixtureProtocol *p) {
                CHECK(Equal(p.request.URL.host,@"lrclib.net"),"A's delayed QQ block must not dispatch a search for B");
                if (Equal(p.request.URL.path,@"/api/get")) {
                    [client setValue:@(NSProcessInfo.processInfo.systemUptime+.55) forKey:@"lastRequestAt"];
                    Emit(p,404,nil,nil);
                } else Emit(p,200,JSON(@[Record(next)]),nil);
            };
            [client fetchTrack:next result:^(MiniSightLyricsTimeline *t, NSString *reason){CHECK(t && Equal(reason,@"lyrics_timeline"),"B uses its own successful LRCLIB search");newCalls++;}];
            Wait(^BOOL{return newCalls>0;},"new track completes");
            CHECK(starts==before+4 && oldCalls==0 && newCalls==1,"no stale IO or result across pending QQ/primary transition");
        } else if (Equal(mode,@"cancel")) {
            [client cancel]; Pump(.42); CHECK(starts==before+2 && oldCalls==0,"OFF cancels pending QQ without callback or IO");
        } else {
            [client setValue:@0 forKey:@"deadline"]; Wait(^BOOL{return oldCalls>0;},"expired QQ wait completes");
            CHECK(starts==before+2 && oldCalls==1 && [client valueForKey:@"completion"]==nil && [client valueForKey:@"track"]==nil,"deadline cleans both completion and track");
        }
        [client cancel]; handler=nil;
    }
    // A and B can both have a delayed QQ search. B's queue is intentionally
    // later; a timer that checks only current==active would dispatch B too early.
    {
        MiniSightLyricsClient *pendingClient=Client(); __block NSUInteger oldDone=0, currentDone=0;
        handler=^(FixtureProtocol *p) {
            CHECK(Equal(p.request.URL.host,@"lrclib.net"),"A has not dispatched QQ before replacement");
            if (Equal(p.request.URL.path,@"/api/search")) [pendingClient setValue:@(NSProcessInfo.processInfo.systemUptime+.70) forKey:@"lastRequestAt"];
            if (Equal(p.request.URL.path,@"/api/get")) Emit(p,404,nil,nil); else Emit(p,200,JSON(@[]),nil);
        };
        [pendingClient fetchTrack:track result:^(MiniSightLyricsTimeline *t,NSString *reason){oldDone++;}];
        Wait(^BOOL{return [[pendingClient valueForKey:@"qqSearchPending"] boolValue];},"A queues QQ");
        NSUInteger before=starts; __block NSTimeInterval earliest=0;
        [pendingClient setValue:@0 forKey:@"lastRequestAt"];
        handler=^(FixtureProtocol *p) {
            if (Equal(p.request.URL.host,@"lrclib.net")) {
                if (Equal(p.request.URL.path,@"/api/get")) Emit(p,404,nil,nil);
                else { earliest=NSProcessInfo.processInfo.systemUptime+1.25;
                    [pendingClient setValue:@(earliest-.35) forKey:@"lastRequestAt"]; Emit(p,200,JSON(@[]),nil); }
            } else if (Equal(p.request.URL.path,@"/soso/fcgi-bin/client_search_cp")) {
                CHECK(earliest>0 && NSProcessInfo.processInfo.systemUptime >= earliest-.01,"A timer cannot dispatch B's own pending QQ ticket");
                CHECK(QQEmptyReply(p,next,YES),"B selects only B's QQ identity");
            } else {
                NSString *lrc=@"[00:01]B current lyric\n[00:03]";
                Emit(p,200,QQJSONPData(@{@"code":@0,@"lyric":[[lrc dataUsingEncoding:NSUTF8StringEncoding] base64EncodedStringWithOptions:0]}),@{@"Content-Type":@"text/html"});
            }
        };
        [pendingClient fetchTrack:next result:^(MiniSightLyricsTimeline *t,NSString *r){CHECK(t && Equal([t lineAtTime:2],@"B current lyric"),"only B's own QQ lyrics delivered");currentDone++;}];
        Wait(^BOOL{return currentDone>0;},"B QQ request completes");
        CHECK(oldDone==0 && currentDone==1 && starts==before+4,"one current-ticket two-source flow; no premature stale timer");
        [pendingClient cancel]; handler=nil;
    }
    // A's QQ lyric request is already in flight when B takes over; inject its
    // late callbacks after B to check both cache and observable completion.
    MiniSightLyricsClient *client=Client(); __block FixtureProtocol *held=nil; __block NSUInteger oldCalls=0;
    handler=^(FixtureProtocol *p){ if (Equal(p.request.URL.host,@"lrclib.net")) Emit(p,404,nil,nil);
        else if (Equal(p.request.URL.path,@"/soso/fcgi-bin/client_search_cp")) { CHECK(QQEmptyReply(p,track,YES),"QQ same-track fixture"); } else held=p; };
    [client fetchTrack:track result:^(MiniSightLyricsTimeline *t,NSString *r){oldCalls++;}];
    Wait(^BOOL{return held!=nil;},"held actual QQ lyric task"); NSURLSessionDataTask *old=[client valueForKey:@"task"];
    handler=^(FixtureProtocol *p){ CHECK(Equal(p.request.URL.host,@"lrclib.net"),"replacement uses primary"); Emit(p,200,JSON(Record(next)),nil); };
    CHECK(Fetch(client,next)!=nil,"replacement after active QQ fetch succeeds");
    __block BOOL refused=NO;
    [client receivedResponse:ResponseAt(429,@{@"Retry-After":@"999"},held.request.URL) task:old completion:^(NSURLSessionResponseDisposition v){refused=(v==NSURLSessionResponseCancel);}];
    [client receivedData:QQJSONPData(@{@"code":@0,@"lyric":@""}) task:old]; [client finishedTask:old error:nil]; Pump(.02);
    CHECK(refused && !oldCalls && [[client valueForKey:@"cache"] objectForKey:track.cacheKey]==nil && [[client valueForKey:@"qqNotBefore"] doubleValue]==0,"stale QQ response does not overwrite, cache or throttle B");
    [client cancel]; handler=nil;
}

static void QQRejectedInputsTests(MiniSightLyricsTrack *track) {
    NSDictionary *valid=@{@"songname":track.title,@"singer":@[@{@"name":track.artist}],@"interval":@60,@"songmid":@"abc123"};
    for (NSString *mode in @[@"tied",@"bad_mid",@"wrong_mime",@"bad_wrapper",@"bad_service_code",@"bad_shape",@"outside_duration",@"only_wrong_artist"]) {
        handler=^(FixtureProtocol *p){
            if (Equal(p.request.URL.host,@"lrclib.net")) { if (Equal(p.request.URL.path,@"/api/get")) Emit(p,404,nil,nil); else Emit(p,200,JSON(@[]),nil); return; }
            CHECK(Equal(p.request.URL.path,@"/soso/fcgi-bin/client_search_cp"),"invalid or ambiguous QQ result never fetches a lyric");
            NSMutableDictionary *other=[valid mutableCopy]; other[@"songmid"]=@"other";
            if (Equal(mode,@"bad_mid")) other[@"songmid"]=@"bad/id";
            if (Equal(mode,@"outside_duration")) other[@"interval"]=@62.01;
            if (Equal(mode,@"only_wrong_artist")) other[@"singer"]=@[@{@"name":@"Someone else"}];
            NSArray *list=Equal(mode,@"tied")?@[valid,other]:@[other];
            id code=Equal(mode,@"bad_service_code")?@0.5:@0;
            id container=Equal(mode,@"bad_shape")?(id)NSNull.null:(id)@{@"song":@{@"list":list}};
            NSData *body=Equal(mode,@"bad_wrapper")?[@"CALL({});junk" dataUsingEncoding:NSUTF8StringEncoding]:QQJSONPData(@{@"code":code,@"data":container});
            Emit(p,200,body,@{@"Content-Type":Equal(mode,@"wrong_mime")?@"text/html":@"application/x-javascript"});
        };
        MiniSightLyricsClient *client=Client(); NSUInteger before=starts;
        BOOL miss=Equal(mode,@"outside_duration")||Equal(mode,@"only_wrong_artist");
        CHECK(Fetch(client,track)==nil && starts==before+3 && Equal(lastReason,miss?@"lyrics_not_found":@"lyrics_response_rejected"),"QQ exact match: reject wrong types, wrong version, ambiguous ties or bad envelope");
        CHECK(([[client valueForKey:@"cache"] objectForKey:track.cacheKey]!=nil)==miss,"only confirmed miss is cached"); [client cancel];
    }
}
