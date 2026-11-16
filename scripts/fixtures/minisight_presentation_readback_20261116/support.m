#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <stdatomic.h>
#import "MiniSightMusicPresentationPolicy.h"
#import "MiniSightShownReadback.h"
// No UIKit, media source, device bridge, microphone or real preferences.
@interface UIImage : NSObject @end
@implementation UIImage @end
@interface MiniSightPetView : NSObject
@property (nonatomic) NSInteger spriteLayout;
@property (nonatomic, strong) UIImage *image;
@property (nonatomic, copy) NSString *actionManifestPath;
@end
@implementation MiniSightPetView @end
@interface MiniSightChatPanel : NSObject
+ (instancetype)existingPanel;
- (void)close;
@property (nonatomic, copy) NSString *containerPath;
@property (nonatomic, copy) NSDictionary *appearancePreferences;
@end
@implementation MiniSightChatPanel
+ (instancetype)existingPanel { static id value; if (!value) value = [self new]; return value; }
- (void)close {}
@end
@interface MiniSightRuntimeConfig : NSObject
+ (instancetype)shared;
@property (nonatomic) double tint;
- (void)reloadWithContainer:(NSString *)container;
@end
@implementation MiniSightRuntimeConfig
+ (instancetype)shared { static id value; if (!value) value = [self new]; return value; }
- (void)reloadWithContainer:(NSString *)container { (void)container; }
@end
static NSString *gMiniSightContainer;
static NSDictionary *gMiniSightPreferences;
static UIImage *gMiniSightAtlas, *gMiniSightTintBase;
static NSString *gMiniSightActionManifest;
static MiniSightPetView *gMiniSightPet;
static BOOL gMiniSightShown, gMiniSightResourcesReady, gMiniSightResourceLoading;
static BOOL gMiniSightSettingsLoading, gMiniSightSettingsRefreshAgain, gMiniSightResourceRefreshAgain;
static BOOL gMiniSightShownWritePending, gMiniSightHideObservedOff, gMiniSightUserHidden, gMiniSightBurst;
static NSString *gMiniSightHidePreviousShownIdentity;
static NSInteger gMiniSightAppliedRenderer = -1, gMiniSightAppliedStyle = -1;
static uint64_t gMiniSightSettingsEpoch, gMiniSightPreferencesEpoch, gMiniSightFadeEpoch, gMiniSightShownWriteEpoch;
static BOOL gMiniSightNameWakePresentationHeld;
static NSMutableArray *gMiniSightResourceCompletions, *resourceReads, *preferenceReads;
static NSUInteger showed, built, destroyed, applied, musicUpdates, callbackCount, userHiddenCleared;
static NSInteger desiredRenderer, desiredStyle = 1;
static atomic_uint notifications;
static void MiniSightConvergeSettings(BOOL fresh);
static void MiniSightReloadSettings(void);
static void MiniSightRequestResources(BOOL force, void (^completion)(void));
static id MiniSightPref(NSString *key) { return gMiniSightPreferences[key]; }
static BOOL MiniSightShown(void) { return gMiniSightShown && !gMiniSightUserHidden; }
static NSInteger MiniSightRenderer(void) { return [MiniSightPref(@"minisight.renderer") integerValue]; }
static NSInteger MiniSightStyle(void) { return [MiniSightPref(@"minisight.style") integerValue]; }
static BOOL MiniSightAlwaysShow(void) { return [MiniSightPref(@"minisight.mode") integerValue] == 1; }
static BOOL MiniSightAppOwnsPresentation(void) { return MiniSightRenderer() == 1 && MiniSightStyle() == 1 && MiniSightShown(); }
static void MSMiniSightSetPreference(NSString *key, id value) { if ([key isEqual:@"MiniSightUserHidden"] && ![value boolValue]) ++userHiddenCleared; }
static void MiniSightStopGravity(void) {}
static void MiniSightNameWakeCancel(NSString *reason, BOOL panel) { (void)reason; (void)panel; }
static void MiniSightCancelConfirm(void) {}
static void MiniSightHide(void) {}
static void MiniSightDestroyUI(void) { ++destroyed; }
static void MiniSightShow(void) { ++showed; gMiniSightAppliedRenderer = MiniSightRenderer(); gMiniSightAppliedStyle = MiniSightStyle(); }
static void MiniSightBuildUI(void) { ++built; }
static void MiniSightApplySettingsLive(void) { ++applied; }
static void MiniSightUpdateMusic(void) { ++musicUpdates; }
static void MiniSightNameWakeUpdate(void) {}
static void MiniSightConfigureRecorder(void) {}
static void MiniSightReadActivitySnapshot(void) {}
static NSInteger MiniSightSpriteLayoutForContainer(NSString *container) { (void)container; return 1; }
static void MiniSightApplyTint(double tint) { (void)tint; }
static void MSDiagConfigure(BOOL enabled, NSString *container) { (void)enabled; (void)container; }
static void MSDiagSettingsSnapshot(NSString *phase, NSString *source, NSDictionary *preferences) { (void)phase; (void)source; (void)preferences; }
static void MSDiagEvent(NSString *module, NSString *action, NSString *result, NSDictionary *fields) { (void)module; (void)action; (void)result; (void)fields; }
static dispatch_queue_t MSResourceQueue(void) { static dispatch_queue_t queue; static dispatch_once_t once; dispatch_once(&once, ^{ queue = dispatch_queue_create("fixture.resources", DISPATCH_QUEUE_SERIAL); }); return queue; }
static void MSBridgePost(NSString *name) { (void)name; atomic_fetch_add(&notifications, 1); }
@interface MiniSightResources : NSObject
+ (void)refresh:(void (^)(NSString *, NSDictionary *, BOOL, UIImage *))completion;
+ (void)refreshPreferences:(void (^)(NSString *, NSDictionary *))completion;
+ (void)writeShown:(BOOL)shown container:(NSString *)container;
+ (void)writeShown:(BOOL)shown container:(NSString *)container completion:(void (^)(BOOL))completion;
+ (void)writeShown:(BOOL)shown container:(NSString *)container verifiedReadback:(void (^)(BOOL, NSString *))completion;
@end
@implementation MiniSightResources
+ (void)refresh:(void (^)(NSString *, NSDictionary *, BOOL, UIImage *))completion { [resourceReads addObject:[completion copy]]; }
+ (void)refreshPreferences:(void (^)(NSString *, NSDictionary *))completion { [preferenceReads addObject:[completion copy]]; }
#include "resources_shown_writer.inc"
@end
#include "tweak_presentation.inc"
static void Check(BOOL ok, NSString *label) { if (!ok) { fprintf(stderr, "%s\n", label.UTF8String); abort(); } }
static NSDictionary *Preferences(void) {
    NSMutableDictionary *prefs = [MSMusicShownEvidence(gMiniSightContainer, @YES) mutableCopy];
    prefs[@"minisight.renderer"] = @(desiredRenderer); prefs[@"minisight.style"] = @(desiredStyle);
    prefs[@"minisight.mode"] = @1; return prefs;
}
static void CompleteResource(NSDictionary *prefs) {
    Check(resourceReads.count > 0, @"actual production must request a resource read");
    void (^reply)(NSString *, NSDictionary *, BOOL, UIImage *) = resourceReads[0];
    [resourceReads removeObjectAtIndex:0]; reply(gMiniSightContainer, prefs, [prefs[@"_minisightShown"] boolValue], [UIImage new]);
}
static void CompletePreferences(NSDictionary *prefs) {
    Check(preferenceReads.count > 0, @"actual production must request the latest preferences");
    void (^reply)(NSString *, NSDictionary *) = preferenceReads[0]; [preferenceReads removeObjectAtIndex:0]; reply(gMiniSightContainer, prefs);
}
static void Wait(BOOL (^ready)(void)) {
    NSDate *until = [NSDate dateWithTimeIntervalSinceNow:3];
    while (!ready() && until.timeIntervalSinceNow > 0) { [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]]; }
    Check(ready(), @"real asynchronous save feedback did not complete");
}
