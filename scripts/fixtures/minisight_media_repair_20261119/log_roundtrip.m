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
        @"lyrics_no_space",@"floor_contact",@"landing_settle",@"landing_stand",@"landing_clear",@"feature_removed"];
    for (NSString *reason in reasons) MSDiagEvent(@"music",@"state",@"ok",@{@"source":@"plugin",@"reason":reason,@"generation":@17,@"present":@YES,
        @"title":@"SENSITIVE_TITLE",@"artist":@"SENSITIVE_ARTIST",@"line":@"SENSITIVE_LYRIC",@"credential":@"SENSITIVE_CREDENTIAL"});
    MSDiagEvent(@"lyrics",@"network",@"pending",@{@"reason":@"lyrics_fetch",@"http":@200});
    MSDiagEvent(@"pet",@"state",@"ok",@{@"source":@"app",@"reason":@"landing_settle",@"value":@1});
    MSDiagEvent(@"name_wake",@"stop",@"ok",@{@"source":@"app",@"reason":@"feature_removed",@"active":@NO});
    MSDiagEvent(@"unknown_feature",@"show",@"ok",@{@"source":@"app"});
    MSDiagEvent(@"music",@"state",@"ok",@{@"source":@"SENSITIVE_UNLISTED",@"reason":@"SENSITIVE_REASON"});
    dispatch_sync(MSDiagQueue,^{});
    NSString *path=[[container stringByAppendingPathComponent:@"Documents/MiniSight"] stringByAppendingPathComponent:MSDiagFile];
    NSString *text=[NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
    Check(text.length>0,"production writer created bounded log");
    Check([text rangeOfString:@"SENSITIVE"].location==NSNotFound,"unknown and content fields redacted");
    NSMutableSet *seen=[NSMutableSet set]; NSUInteger count=0;
    for (NSString *row in [text componentsSeparatedByString:@"\n"]) {
        if (!row.length) continue;
        NSRange marker=[row rangeOfString:@" event="];
        Check(marker.location!=NSNotFound,"real event envelope");
        NSData *data=[[row substringFromIndex:NSMaxRange(marker)] dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *event=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        Check([event[@"v"] integerValue]==1,"v1 structured event");
        Check(![event[@"feature"] isEqual:@"unknown_feature"],"unknown feature denied");
        id reason=event[@"fields"][@"reason"];if (reason) [seen addObject:reason];
        ++count;
    }
    for (NSString *reason in reasons) Check([seen containsObject:reason],"every required reason survived write/read");
    Check(count>=reasons.count,"all required basic events written");
    NSDictionary *attrs=[NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
    Check(([attrs[NSFilePosixPermissions] unsignedIntegerValue]&0777)==0600,"log has private mode");
    NSData *raw=[text dataUsingEncoding:NSUTF8StringEncoding];
    Check(raw.length<=MSDiagMaxBytes,"small fixture inside production cap");
    printf("NATIVE PASS log-roundtrip: %lu bounded events; required reasons retained, content redacted\n",(unsigned long)count);
    return 0;
} }
