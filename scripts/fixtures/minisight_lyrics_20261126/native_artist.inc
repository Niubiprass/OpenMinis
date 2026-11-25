// Catch-all FixtureProtocol runs the real production QQ parser/state machine.
// Synthetic identities only; no request can escape to a live loader.
static void ArtistIdentityNativeTests(void) {
    NSString *container = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    MSDiagConfigure(NO, container);
    NSMutableArray<NSDictionary *> *cases = [NSMutableArray array];
    for (NSString *credit in @[@"Alpha/Beta", @"Alpha / Beta", @"Beta/Alpha", @"Alpha、Beta", @"Beta 、 Alpha", @"Alpha&Beta", @"Beta & Alpha", @"Alpha Beta"]) {
        [cases addObject:@{@"credit":credit, @"names":@[@"Alpha", @"Beta"], @"ok":@YES}];
    }
    [cases addObjectsFromArray:@[
        @{@"credit":@"Solo Artist", @"names":@[@"Solo Artist"], @"ok":@YES},
        @{@"credit":@"AC/DC", @"names":@[@"AC/DC"], @"ok":@YES},
        @{@"credit":@"A&B", @"names":@[@"A&B"], @"ok":@YES},
        @{@"credit":@"ÁLPHA / Beta", @"names":@[@"A\u0301lpha", @"Beta"], @"ok":@YES},
        @{@"credit":@"Gamma & Alpha、Beta", @"names":@[@"Alpha", @"Beta", @"Gamma"], @"ok":@YES},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha"], @"ok":@NO},
        @{@"credit":@"Alpha", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta", @"Gamma"], @"ok":@NO},
        @{@"credit":@"Alpha / Beta / Gamma", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha Alpha", @"names":@[@"Alpha", @"Alpha"], @"ok":@NO},
        @{@"credit":@"Alpha / Alpha", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha / Alpha", @"names":@[@"Alpha", @"Alpha"], @"ok":@NO},
        @{@"credit":@"Beta Alpha", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha // Beta", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha / Beta /", @"names":@[@"Alpha", @"Beta"], @"ok":@NO},
        @{@"credit":@"Alpha & Beta / Gamma", @"names":@[@"Alpha & Beta", @"Gamma"], @"ok":@NO},
        @{@"credit":@"AC / DC / Beta", @"names":@[@"AC/DC", @"Beta"], @"ok":@NO},
        @{@"credit":@"A-B", @"names":@[@"AB"], @"ok":@NO},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta"], @"seconds":@62, @"ok":@YES},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta"], @"seconds":@62.001, @"ok":@NO},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta"], @"candidateTitle":@"Synthetic Identity Song (Live)", @"ok":@NO},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta"], @"candidateTitle":@"Synthetic Identity Song (Remix)", @"ok":@NO},
        @{@"credit":@"Alpha / Beta", @"names":@[@"Alpha", @"Beta"], @"candidateTitle":@"Synthetic Identity Song (Cover)", @"ok":@NO}
    ]];
    for (NSDictionary *test in cases) {
        MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc] initWithTitle:@"Synthetic Identity Song" artist:test[@"credit"] duration:60];
        NSMutableArray *singers = [NSMutableArray array]; for (NSString *name in test[@"names"]) [singers addObject:@{@"name":name}];
        NSDictionary *song = @{@"songname":test[@"candidateTitle"] ?: track.title, @"singer":singers, @"interval":test[@"seconds"] ?: @60, @"songmid":@"abc123"};
        __block NSUInteger lyricRequests = 0;
        handler = ^(FixtureProtocol *p) {
            if (Equal(p.request.URL.host, @"lrclib.net")) { if (Equal(p.request.URL.path, @"/api/get")) Emit(p,404,nil,nil); else Emit(p,200,JSON(@[]),nil); }
            else if (Equal(p.request.URL.path, @"/soso/fcgi-bin/client_search_cp")) Emit(p,200,QQJSONPData(@{@"code":@0, @"data":@{@"song":@{@"list":@[song]}}}),@{@"Content-Type":@"application/x-javascript"});
            else {
                CHECK([test[@"ok"] boolValue], "rejected identity cannot start QQ lyric request"); lyricRequests++;
                NSString *b64 = [[@"[00:01]Synthetic identity line\n[00:03]" dataUsingEncoding:NSUTF8StringEncoding] base64EncodedStringWithOptions:0];
                Emit(p,200,QQJSONPData(@{@"code":@0, @"songmid":@"abc123", @"lyric":b64}),@{@"Content-Type":@"text/html"});
            }
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        MiniSightLyricsTimeline *timeline = Fetch(client, track); BOOL ok = [test[@"ok"] boolValue];
        CHECK((timeline != nil) == ok && starts == before + (ok ? 4 : 3) && lyricRequests == (ok ? 1 : 0), "production complete artist identity and title/duration guards drive request count");
        CHECK(Equal(lastReason, ok ? @"lyrics_timeline" : @"lyrics_not_found"), "legacy final reason is unchanged");
        [client cancel];
    }
    // Mixed rejection layers, a conflicting MID tie, malformed shape and 21+ bound.
    MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc] initWithTitle:@"Synthetic Diagnostic Song" artist:@"Alpha / Beta" duration:60];
    NSDictionary *valid = @{@"songname":track.title, @"singer":@[@{@"name":@"Alpha"}, @{@"name":@"Beta"}], @"interval":@60, @"songmid":@"abc123"};
    NSMutableDictionary *title = [valid mutableCopy]; title[@"songname"] = @"Wrong Title";
    NSMutableDictionary *artist = [valid mutableCopy]; artist[@"singer"] = @[@{@"name":@"Wrong Artist"}];
    NSMutableDictionary *duration = [valid mutableCopy]; duration[@"interval"] = @63;
    NSMutableDictionary *conflict = [valid mutableCopy]; conflict[@"songmid"] = @"def456";
    NSMutableDictionary *bad = [valid mutableCopy]; bad[@"singer"] = NSNull.null;
    NSMutableArray *over = [NSMutableArray array]; for (unsigned i = 0; i < 21; ++i) [over addObject:valid];
    for (NSArray *list in @[@[title,artist,duration], @[valid,conflict], @[bad], over]) {
        handler = ^(FixtureProtocol *p) {
            if (Equal(p.request.URL.host,@"lrclib.net")) { if (Equal(p.request.URL.path,@"/api/get")) Emit(p,404,nil,nil); else Emit(p,200,JSON(@[]),nil); }
            else { CHECK(Equal(p.request.URL.path,@"/soso/fcgi-bin/client_search_cp"), "mixed/ambiguous/invalid QQ never fetches lyrics"); Emit(p,200,QQJSONPData(@{@"code":@0,@"data":@{@"song":@{@"list":list}}}),@{@"Content-Type":@"application/x-javascript"}); }
        };
        MiniSightLyricsClient *client = Client(); NSUInteger before = starts;
        CHECK(Fetch(client,track) == nil && starts == before + 3, "bounded invalid/ambiguous/mixed candidates rejected by production"); [client cancel];
    }
    MSDiagEvent(@"lyrics", @"finish", @"ok", @{@"http":@419});
    NSString *path = [container stringByAppendingPathComponent:@"Documents/MiniSight/diagnostic-app.log"];
    Wait(^BOOL{ return [[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL] containsString:@"419"]; }, "match diagnostic writer drained");
    NSString *text = [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:NULL];
    CHECK(![text containsString:@"Alpha"] && ![text containsString:@"abc123"] && ![text containsString:track.title] && ![text containsString:@"Synthetic identity line"] && ![text containsString:@"https://"], "match log contains no raw identity/MID/LRC/URL");
    NSMutableSet *details = [NSMutableSet set]; BOOL mixed = NO, tie = NO, invalid = NO, overflow = NO;
    for (NSString *line in [text componentsSeparatedByString:@"\n"]) {
        NSRange at = [line rangeOfString:@" event="]; if (at.location == NSNotFound) continue;
        NSDictionary *event = [NSJSONSerialization JSONObjectWithData:[[line substringFromIndex:NSMaxRange(at)] dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
        if (!Equal(event[@"stage"],@"match")) continue;
        NSDictionary *f = event[@"fields"]; [details addObject:f[@"lyrics_detail"] ?: @"missing"];
        for (NSString *key in @[@"match_total",@"match_title_rejected",@"match_artist_rejected",@"match_duration_rejected",@"match_invalid",@"match_ambiguous"]) CHECK([f[key] isKindOfClass:NSNumber.class] && [f[key] unsignedIntegerValue] <= 21, "all match counters survive the real writer within bounds");
        if (!Equal(f[@"lyrics_route"],@"qq_search")) continue;
        if (Equal(f[@"lyrics_detail"],@"match_mixed")) mixed = [f[@"match_total"] integerValue] == 3 && [f[@"match_title_rejected"] integerValue] == 1 && [f[@"match_artist_rejected"] integerValue] == 1 && [f[@"match_duration_rejected"] integerValue] == 1;
        if (Equal(f[@"lyrics_detail"],@"match_ambiguous")) tie = [f[@"match_ambiguous"] integerValue] == 2;
        if (Equal(f[@"lyrics_detail"],@"match_invalid")) { invalid = YES; if ([f[@"match_total"] integerValue] == 21) overflow = YES; }
    }
    for (NSString *detail in @[@"match_accepted",@"match_empty",@"match_title_rejected",@"match_artist_rejected",@"match_duration_rejected"]) CHECK([details containsObject:detail], "fixed match layer code survives log roundtrip");
    CHECK(mixed && tie && invalid && overflow, "exact rejection counts, ambiguity and over-limit sentinel survive logging");
    MSDiagConfigure(NO,nil); [NSFileManager.defaultManager removeItemAtPath:container error:NULL];
}
