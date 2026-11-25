// Host-only. Production writer, synthetic temp directory, no media/mic/network.
#import <Foundation/Foundation.h>
#import "MiniSightLog.m"
#include <stdio.h>
#include <stdlib.h>
static void Check(BOOL value, const char *reason) {
    if (!value) { fprintf(stderr,"FAIL log-roundtrip: %s\n",reason); exit(1); }
}
int main(int argc,const char **argv) { @autoreleasepool {
    Check(argc==2,"temp directory supplied");
    NSString *container=[NSString stringWithUTF8String:argv[1]];
    NSString *dir=[container stringByAppendingPathComponent:@"Documents/MiniSight"];
    [NSFileManager.defaultManager createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
    MSDiagConfigure(NO,container); // basic events are available even without detail
    NSArray *reasons=@[@"no_supported_player",@"metadata_missing",@"lyrics_fetch",@"lyrics_timeline",
        @"no_synced_lyrics",@"snapshot_verified",@"snapshot_write_failed",@"lyrics_received",@"lyrics_line",
        @"lyrics_no_space",@"floor_contact",@"landing_settle",@"landing_stand",@"landing_clear",@"feature_removed",
        @"daily_gate",@"daily_selected",@"daily_first_frame",@"music_input_mode",@"activity_applied",
        @"rhythm_frame_rejected",@"rhythm_owner_blocked",@"rhythm_transport_mode",@"metadata_revalidate",
        @"candidate_expired",@"candidate_revalidated",@"player_instance_changed",@"confirmed_pause",@"confirmed_stop"];
    for (NSString *reason in reasons) MSDiagEvent(@"music",@"state",@"ok",@{@"source":@"plugin",@"reason":reason,@"generation":@17,@"present":@YES,
        @"title":@"SENSITIVE_TITLE",@"artist":@"SENSITIVE_ARTIST",@"line":@"SENSITIVE_LYRIC",@"credential":@"SENSITIVE_CREDENTIAL"});
    MSDiagEvent(@"pet",@"daily_action",@"ok",@{@"source":@"plugin",@"reason":@"daily_gate",
        @"blockers":@128,@"action_id":@2,@"due_ms":@2500,@"frame_count":@6,@"frame_index":@1,
        @"input_mode":@1,@"input_ready":@NO});
    MSDiagEvent(@"music",@"sample",@"ok",@{@"source":@"plugin",@"reason":@"candidate_revalidated",
        @"read_stage":@5,@"last_valid_age_ms":@0,@"identity_epoch":@7});
    MSDiagEvent(@"lyrics",@"match",@"skipped",@{@"lyrics_route":@"qq_search",@"lyrics_detail":@"match_mixed",
        @"match_total":@3,@"match_title_rejected":@1,@"match_artist_rejected":@1,
        @"match_duration_rejected":@1,@"match_invalid":@0,@"match_ambiguous":@0});
    MSDiagEvent(@"lyrics",@"network",@"pending",@{@"reason":@"lyrics_fetch",@"http":@200});
    MSDiagEvent(@"pet",@"state",@"ok",@{@"source":@"app",@"reason":@"landing_settle",@"value":@1});
    MSDiagEvent(@"name_wake",@"stop",@"ok",@{@"source":@"app",@"reason":@"feature_removed",@"active":@NO});
    MSDiagEvent(@"unknown_feature",@"show",@"ok",@{@"source":@"app"});
    MSDiagEvent(@"music",@"state",@"ok",@{@"source":@"SENSITIVE_UNLISTED",@"reason":@"SENSITIVE_REASON"});
    // Real production settings logger: changing private readback evidence must
    // not overwrite action/lyrics history with hundreds of identical snapshots.
    NSString *revision = NSUUID.UUID.UUIDString;
    NSMutableDictionary *settings = [@{@"minisight.settings.revision": revision,
        @"minisight.activity": @"lively", @"minisight.activity.interval": @3,
        @"minisight.actions.daily": @YES, @"minisight.music.motion": @YES,
        @"minisight.music.lyrics": @YES, @"minisight.shown": @YES,
        @"_private": @"SENSITIVE_PRIVATE"} mutableCopy];
    for (NSUInteger i = 0; i < 100; ++i) {
        settings[@"_readbackNonce"] = @(i); // Not an allowlisted setting.
        MSDiagSettingsSnapshot(@"receive", @"plugin", settings);
    }
    settings[@"minisight.actions.daily"] = @NO;
    MSDiagSettingsSnapshot(@"receive", @"plugin", settings); // Same revision, real value change.
    MSDiagSettingsSnapshot(@"apply", @"plugin", settings); // Applied state is separate from received state.
    MSDiagSettingsSnapshot(@"receive", @"SENSITIVE_UNLISTED", settings);
    dispatch_sync(MSDiagQueue,^{});
    NSString *path=[[container stringByAppendingPathComponent:@"Documents/MiniSight"] stringByAppendingPathComponent:MSDiagFile];
    NSString *text=[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
    Check(text.length>0,"production writer created bounded log");
    Check([text rangeOfString:@"SENSITIVE"].location==NSNotFound,"unknown and content fields redacted");
    NSMutableSet *seen=[NSMutableSet set]; NSUInteger count=0, receivedSettings=0, appliedSettings=0, dailyChanges=0;
    BOOL receivedActivity=NO, receivedInterval=NO, dailyFields=NO, identityFields=NO, matchFields=NO;
    for (NSString *row in [text componentsSeparatedByString:@"\n"]) {
        if (!row.length) continue;
        NSRange marker=[row rangeOfString:@" event="];
        Check(marker.location!=NSNotFound,"real event envelope");
        NSData *data=[[row substringFromIndex:NSMaxRange(marker)] dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *event=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        Check([event[@"v"] integerValue]==1,"v1 structured event");
        Check(![event[@"feature"] isEqual:@"unknown_feature"],"unknown feature denied");
        id reason=event[@"fields"][@"reason"];if (reason) [seen addObject:reason];
        if ([event[@"feature"] isEqual:@"settings"]) {
            if ([event[@"stage"] isEqual:@"receive"]) {
                ++receivedSettings;
                if ([event[@"fields"][@"setting"] isEqual:@"minisight.actions.daily"]) ++dailyChanges;
                if ([event[@"fields"][@"setting"] isEqual:@"minisight.activity"])
                    receivedActivity = [event[@"fields"][@"activity_mode"] isEqual:@"lively"];
                if ([event[@"fields"][@"setting"] isEqual:@"minisight.activity.interval"])
                    receivedInterval = [event[@"fields"][@"value"] integerValue] == 3;
            } else if ([event[@"stage"] isEqual:@"apply"]) ++appliedSettings;
        }
        NSDictionary *f = event[@"fields"];
        if ([event[@"feature"] isEqual:@"pet"] && [event[@"stage"] isEqual:@"daily_action"])
            dailyFields = [f[@"blockers"] integerValue] == 128 && [f[@"action_id"] integerValue] == 2 &&
                [f[@"due_ms"] integerValue] == 2500 && [f[@"frame_count"] integerValue] == 6 && [f[@"frame_index"] integerValue] == 1 &&
                [f[@"input_mode"] integerValue] == 1 && f[@"input_ready"] != nil && ![f[@"input_ready"] boolValue];
        if ([event[@"feature"] isEqual:@"music"] && [event[@"stage"] isEqual:@"sample"])
            identityFields = [f[@"read_stage"] integerValue] == 5 && f[@"last_valid_age_ms"] != nil &&
                [f[@"last_valid_age_ms"] integerValue] == 0 && [f[@"identity_epoch"] integerValue] == 7;
        if ([event[@"feature"] isEqual:@"lyrics"] && [event[@"stage"] isEqual:@"match"])
            matchFields = [f[@"lyrics_detail"] isEqual:@"match_mixed"] && [f[@"match_total"] integerValue] == 3 &&
                [f[@"match_title_rejected"] integerValue] == 1 && [f[@"match_artist_rejected"] integerValue] == 1 &&
                [f[@"match_duration_rejected"] integerValue] == 1 && f[@"match_invalid"] != nil &&
                [f[@"match_invalid"] integerValue] == 0 && f[@"match_ambiguous"] != nil && [f[@"match_ambiguous"] integerValue] == 0;
        ++count;
    }
    for (NSString *reason in reasons) Check([seen containsObject:reason],"every required reason survived write/read");
    Check(receivedSettings == appliedSettings + 1 && appliedSettings > 0 && appliedSettings <= 32,
        "100 private-only refreshes coalesce per setting without conflating receive/apply");
    Check(dailyChanges == 2,"same-revision actual daily change is not hidden by deduplication");
    Check(dailyFields && identityFields && matchFields,"new bounded motion/identity/match counters survive real write/read");
    Check(receivedActivity && receivedInterval,"actual activity mode and interval survive allowlist/write/read");
    Check(count>=reasons.count,"all required basic events written");
    NSDictionary *attrs=[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
    Check(([attrs[NSFilePosixPermissions] unsignedIntegerValue]&0777)==0600,"log has private mode");
    NSData *raw=[text dataUsingEncoding:NSUTF8StringEncoding];
    Check(raw.length<=MSDiagMaxBytes,"small fixture inside production cap");
    printf("NATIVE PASS log-roundtrip: %lu bounded events; required reasons retained, content redacted\n",(unsigned long)count);
    return 0;
} }
