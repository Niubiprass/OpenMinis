#import "MiniSightNameWakeProtocol.h"
static BOOL gMiniSightScreenKnown, gMiniSightScreenBlanked;
static BOOL fixtureLockKnown, fixtureUnlocked;
static BOOL gMiniSightResourcesReady = YES, gMiniSightResourceLoading = NO;
static NSString *gMiniSightContainer = @"SYNTHETIC-CONTAINER";
static void MiniSightReadScreenState(void) {}
static id MiniSightPref(NSString *key) {
    if ([key isEqual:@"minisight.settings.revision"]) return @"SYNTHETIC-NAME-ROUNDTRIP-REV-1";
    return @YES;
}
static BOOL MiniSightShown(void) { return YES; }
static NSInteger MiniSightStyle(void) { return 1; }
static NSInteger MiniSightRenderer(void) { return 0; }
static BOOL MiniSightMinisIsFrontmost(void) { return NO; }
@interface MiniSightMusicMonitor : NSObject
+ (BOOL)deviceIsUnlockedWithKnown:(BOOL *)known;
@end
@implementation MiniSightMusicMonitor
+ (BOOL)deviceIsUnlockedWithKnown:(BOOL *)known { *known = fixtureLockKnown; return fixtureUnlocked; }
@end
