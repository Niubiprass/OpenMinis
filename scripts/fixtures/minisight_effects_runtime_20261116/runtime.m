// Actual production code in this translation unit; only dependency shims below.
#import "support.h"
#import "MiniSightPetEffects.m"
#import "pet_atlas_excerpt.inc" // Generated verbatim from the current MiniSightPet.m.
#import "MiniSightLyrics.m" // Only timeline/track methods run. No client/session.
#include <stdio.h>
#include <stdlib.h>

static const char *Case = "setup";
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s line %d: %s\n", Case, __LINE__, #x); exit(1); } } while (0)
static double Now = 100.;
CFTimeInterval MSFixtureClock(void) { return Now; }
static BOOL FixtureReduceMotion;
BOOL UIAccessibilityIsReduceMotionEnabled(void) { return FixtureReduceMotion; }

@implementation UIImage { CGImageRef _backing; }
+ (instancetype)imageWithCGImage:(CGImageRef)image {
    UIImage *value = [self new]; value->_backing = CGImageRetain(image); return value;
}
- (CGImageRef)CGImage { return _backing; }
- (CGFloat)scale { return 1.; }
- (void)dealloc { if (_backing) CGImageRelease(_backing); }
@end
@implementation UIView {
    CGRect _frame, _bounds;
    CGPoint _center;
    CALayer *_layer;
    __weak UIView *_superview;
    NSMutableArray<UIView *> *_children;
}
- (instancetype)init {
    if ((self = [super init])) { _alpha = 1.; _layer = [CALayer layer]; _children = [NSMutableArray new]; }
    return self;
}
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [self init])) self.frame = frame;
    return self;
}
- (CGRect)frame { return _frame; }
- (void)setFrame:(CGRect)value {
    _frame = value; _bounds.size = value.size;
    _center = CGPointMake(CGRectGetMidX(value), CGRectGetMidY(value));
}
- (CGRect)bounds { return _bounds; }
- (void)setBounds:(CGRect)value {
    _bounds = value; _frame.size = value.size; [self setCenter:_center];
}
- (CGPoint)center { return _center; }
- (void)setCenter:(CGPoint)value {
    _center = value; _frame.origin = CGPointMake(value.x - _bounds.size.width / 2., value.y - _bounds.size.height / 2.);
}
- (CALayer *)layer { return _layer; }
- (UIView *)superview { return _superview; }
- (UIWindow *)window { return [self isKindOfClass:UIWindow.class] ? (UIWindow *)self : _superview.window; }
- (id)traitCollection { return nil; }
- (void)addSubview:(UIView *)view { [view removeFromSuperview]; view->_superview = self; [_children addObject:view]; }
- (void)removeFromSuperview {
    UIView *parent = _superview; if (parent) [parent->_children removeObject:self]; _superview = nil;
}
@end
@implementation UIWindow @end
@implementation UIImageView @end
@implementation UILabel
- (CGSize)sizeThatFits:(CGSize)size {
    double width = fmax(1., size.width), pixels = self.text.length * 7.;
    return CGSizeMake(fmin(width, pixels), fmin(size.height, 17. * fmax(1., ceil(pixels / width))));
}
@end
@implementation UIFont
+ (instancetype)systemFontOfSize:(CGFloat)size weight:(CGFloat)weight { return [self new]; }
@end
@implementation UIColor { CGColorRef _backing; }
- (instancetype)init { if ((self = [super init])) _backing = CGColorCreateGenericRGB(1., 1., 1., 1.); return self; }
+ (instancetype)secondarySystemBackgroundColor { return [self new]; }
+ (instancetype)labelColor { return [self new]; }
+ (instancetype)systemBlueColor { return [self new]; }
+ (instancetype)systemYellowColor { return [self new]; }
- (UIColor *)resolvedColorWithTraitCollection:(id)traits { return self; }
- (CGColorRef)CGColor { return _backing; }
- (void)dealloc { if (_backing) CGColorRelease(_backing); }
@end
@implementation UIBezierPath { CGMutablePathRef _backing; }
- (instancetype)init { if ((self = [super init])) _backing = CGPathCreateMutable(); return self; }
+ (instancetype)bezierPath { return [self new]; }
- (void)moveToPoint:(CGPoint)p { CGPathMoveToPoint(_backing, NULL, p.x, p.y); }
- (void)addLineToPoint:(CGPoint)p { CGPathAddLineToPoint(_backing, NULL, p.x, p.y); }
- (void)closePath { CGPathCloseSubpath(_backing); }
- (CGPathRef)CGPath { return _backing; }
- (void)dealloc { if (_backing) CGPathRelease(_backing); }
@end
@implementation MSFixtureDisplayLink { BOOL _invalidated; id _target; }
+ (instancetype)displayLinkWithTarget:(id)target selector:(SEL)selector {
    MSFixtureDisplayLink *link = [self new]; link->_target = target; return link;
}
- (BOOL)invalidated { return _invalidated; }
- (void)addToRunLoop:(NSRunLoop *)loop forMode:(NSRunLoopMode)mode { }
- (void)invalidate { _invalidated = YES; _target = nil; }
@end
static MiniSightChatPanel *Panel;
@implementation MiniSightChatPanel
+ (instancetype)existingPanel { return Panel; }
+ (void)fixtureSetVisible:(BOOL)visible { if (!Panel) Panel = [self new]; Panel.visible = visible; }
@end

// Metadata uses the REAL readonly public header. This is a controllable mock of
// ActionLibrary delivery, not a second implementation of its parser/decoder.
typedef void (^FrameReply)(UIImage *);
typedef void (^LoadReply)(MiniSightActionLibrary *, NSError *);
@interface MSFrameJob : NSObject
@property(nonatomic, strong) MiniSightActionClip *clip;
@property(nonatomic) NSUInteger index;
@property(nonatomic, copy) FrameReply reply;
@end
@implementation MSFrameJob @end
@interface MSLoadJob : NSObject
@property(nonatomic, copy) NSString *path;
@property(nonatomic, copy) LoadReply reply;
@end
@implementation MSLoadJob @end
@interface MiniSightActionClip ()
- (instancetype)initFixtureRole:(NSString *)role durations:(NSArray<NSNumber *> *)durations;
- (instancetype)initFixtureID:(NSString *)identifier category:(NSString *)category durations:(NSArray<NSNumber *> *)durations;
@end
@implementation MiniSightActionClip
- (instancetype)initFixtureRole:(NSString *)role durations:(NSArray<NSNumber *> *)durations {
    if ((self = [super init])) {
        _identifier = [@"fixture-" stringByAppendingString:role]; _role = [role copy];
        _durations = [durations copy]; _frameCount = durations.count;
        for (NSNumber *length in durations) _duration += length.doubleValue;
    }
    return self;
}
- (instancetype)initFixtureID:(NSString *)identifier category:(NSString *)category durations:(NSArray<NSNumber *> *)durations {
    if ((self = [super init])) {
        _identifier = [@"fixture-" stringByAppendingString:identifier]; _role = @"idleAlt"; _category = [category copy];
        _durations = [durations copy]; _frameCount = durations.count;
        for (NSNumber *length in durations) _duration += length.doubleValue;
    }
    return self;
}
@end
@interface MiniSightActionLibrary ()
@property(nonatomic, strong) NSMutableArray<MSFrameJob *> *requests;
@property(nonatomic, strong) MSFrameJob *pending;
@property(nonatomic) NSUInteger purges;
- (instancetype)initFixtureRoles:(NSDictionary *)roles;
@end
static NSMutableArray<MSLoadJob *> *Loads;
@implementation MiniSightActionLibrary
- (instancetype)initFixtureRoles:(NSDictionary *)roles {
    if ((self = [super init])) { _roles = [roles copy]; _requests = [NSMutableArray new]; }
    return self;
}
+ (void)loadManifestAtPath:(NSString *)path completion:(LoadReply)completion {
    CHECK(NSThread.isMainThread); if (!Loads) Loads = [NSMutableArray new];
    MSLoadJob *job = [MSLoadJob new]; job.path = path; job.reply = completion; [Loads addObject:job];
}
- (void)requestFrameForClip:(MiniSightActionClip *)clip index:(NSUInteger)index completion:(FrameReply)completion {
    CHECK(NSThread.isMainThread && clip && index < clip.frameCount);
    _pending.reply = nil; // Latest wins, as promised by the actual library API.
    MSFrameJob *job = [MSFrameJob new]; job.clip = clip; job.index = index; job.reply = completion;
    [_requests addObject:job]; _pending = job;
}
- (void)cancelPendingFrameRequests { _pending.reply = nil; _pending = nil; }
- (void)purgeFrames { ++_purges; [self cancelPendingFrameRequests]; }
@end

static void OnMain(void (^work)(void)) {
    __block BOOL done = NO;
    dispatch_async(dispatch_get_main_queue(), ^{ CHECK(NSThread.isMainThread); work(); done = YES; });
    CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + 3.;
    while (!done && CFAbsoluteTimeGetCurrent() < deadline) CFRunLoopRunInMode(kCFRunLoopDefaultMode, .001, true);
    CHECK(done);
}
static void Load(MSLoadJob *job, MiniSightActionLibrary *library) {
    LoadReply reply = [job.reply copy]; CHECK(reply); job.reply = nil; [Loads removeObject:job];
    OnMain(^{ reply(library, nil); });
}
static void Finish(MiniSightActionLibrary *library, UIImage *image) {
    FrameReply reply = [library.pending.reply copy]; CHECK(reply);
    library.pending.reply = nil; library.pending = nil; OnMain(^{ reply(image); });
}
static UIImage *Pixel(unsigned char red) {
    CGColorSpaceRef color = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, 8, 8, 8, 32, color,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big); CGColorSpaceRelease(color); CHECK(context);
    CGContextSetRGBFillColor(context, red / 255., .2, .4, 1.); CGContextFillRect(context, CGRectMake(0, 0, 8, 8));
    CGImageRef cg = CGBitmapContextCreateImage(context); CGContextRelease(context); CHECK(cg);
    UIImage *image = [UIImage imageWithCGImage:cg]; CGImageRelease(cg); return image;
}
static NSArray *Clip(NSString *role, NSArray *durations) {
    return @[[[MiniSightActionClip alloc] initFixtureRole:role durations:durations]];
}
static MiniSightActionClip *DailyClip(NSString *identifier, NSString *category, NSArray *durations) {
    return [[MiniSightActionClip alloc] initFixtureID:identifier category:category durations:durations];
}
static NSString *Role(MiniSightPetEffects *effects) { return [effects valueForKey:@"role"]; }
static BOOL Pending(MiniSightPetEffects *effects) { return [[effects valueForKey:@"framePending"] boolValue]; }
static double Start(MiniSightPetEffects *effects) { return [[effects valueForKey:@"clipStart"] doubleValue]; }
static NSUInteger Epoch(MiniSightPetEffects *effects) { return [[effects valueForKey:@"frameRequest"] unsignedIntegerValue]; }
static void Tick(MiniSightPetEffects *effects, double time) { Now = time; [effects tick:[effects valueForKey:@"link"]]; }
static BOOL BubbleHidden(MiniSightPetEffects *effects) {
    UIView *bubble = [effects valueForKey:@"bubble"]; return !bubble || bubble.hidden;
}
@interface MSRig : NSObject
@property(nonatomic, strong) UIWindow *root;
@property(nonatomic, strong) MiniSightPetView *pet;
@property(nonatomic, strong) CALayer *sprite;
@property(nonatomic, strong) UIImage *poster;
@property(nonatomic, strong) MiniSightPetEffects *effects;
@property(nonatomic, strong) MiniSightActionLibrary *library;
@end
@implementation MSRig
- (void)dealloc { [_effects invalidate]; }
@end
static BOOL MatchesPoster(MSRig *r);
static MSRig *Rig(NSDictionary *roles) {
    CHECK(!Loads.count); Now = 100.; [MiniSightChatPanel fixtureSetVisible:NO];
    MSRig *rig = [MSRig new]; rig.root = [UIWindow new]; rig.root.frame = CGRectMake(0, 0, 360, 780);
    rig.root.safeAreaInsets = (UIEdgeInsets){20, 8, 20, 8}; rig.poster = Pixel(15);
    rig.pet = [[MiniSightPetView alloc] initWithSprite:rig.poster displaySize:CGSizeMake(80, 90)];
    rig.pet.spriteLayout = 1;
    rig.pet.frame = CGRectMake(140, 400, 80, 90); [rig.root addSubview:rig.pet];
    rig.sprite = [rig.pet valueForKey:@"gravityLayer"];
    rig.effects = [rig.pet valueForKey:@"effects"];
    CHECK(rig.pet.image == nil && rig.pet.layer.contents == nil);
    rig.library = [[MiniSightActionLibrary alloc] initFixtureRoles:roles];
    rig.effects.actionManifestPath = @"fixture-only/no-file-read"; [rig.effects setRunning:YES];
    CHECK(!rig.effects.hasActions && Loads.count == 1); Load(Loads.lastObject, rig.library);
    CHECK(Pending(rig.effects)); return rig;
}

static void FirstFrame(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@1.])});
    CHECK(!r.effects.hasDailyActions); // Single/legacy idle is not a daily-action pool.
    CHECK(MatchesPoster(r) && !r.effects.hasActions);
    Finish(r.library, nil); CHECK(!r.effects.hasActions && !Pending(r.effects));
    Tick(r.effects, 100.49); CHECK(r.library.requests.count == 1);
    Tick(r.effects, 100.51); CHECK(Pending(r.effects));
    UIImage *ready = Pixel(210); Finish(r.library, ready);
    CHECK(r.effects.hasActions && !Pending(r.effects) && Start(r.effects) == Now);
    CHECK(r.sprite.contents == (__bridge id)ready.CGImage);
}
static void ThreeBadFrames(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@.1, @5.])});
    UIImage *good = Pixel(180); Finish(r.library, good); Tick(r.effects, 100.2);
    CHECK(r.library.pending.index == 1); Finish(r.library, nil);
    CHECK(r.effects.hasActions && r.sprite.contents == (__bridge id)good.CGImage);
    Tick(r.effects, 100.69); CHECK(r.library.requests.count == 2);
    Tick(r.effects, 100.71); CHECK(Pending(r.effects)); Finish(r.library, [UIImage new]);
    CHECK(r.effects.hasActions); Tick(r.effects, 101.70); CHECK(r.library.requests.count == 3);
    Tick(r.effects, 101.72); Finish(r.library, nil);
    CHECK(!r.effects.hasActions && !Pending(r.effects));
    CHECK([[r.effects valueForKey:@"failedClips"] containsObject:@"fixture-idle"]);
    CHECK(![r.effects valueForKey:@"clip"] && MatchesPoster(r));
    Tick(r.effects, 150.); CHECK(r.library.requests.count == 4); // No hot retry/reselection.
}
static void SupersededRoleAndManifest(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@1.]), @"tap": Clip(@"tap", @[@1.])});
    FrameReply stale = [r.library.pending.reply copy]; NSUInteger token = Epoch(r.effects);
    [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 100.1);
    CHECK([Role(r.effects) isEqual:@"tap"] && Epoch(r.effects) > token);
    UIImage *old = Pixel(55), *fresh = Pixel(240);
    OnMain(^{ stale(old); }); // Simulate an already-dispatched old worker completion.
    CHECK(Pending(r.effects) && !r.effects.hasActions && Start(r.effects) == 0.);
    Finish(r.library, fresh); double start = Start(r.effects);
    OnMain(^{ stale(old); });
    CHECK(Start(r.effects) == start && r.sprite.contents == (__bridge id)fresh.CGImage);

    // Load completion generation and frame generation are independently fenced.
    [r.effects setLegacyState:0 waking:NO]; Tick(r.effects, 102.);
    FrameReply oldGeneration = [r.library.pending.reply copy]; CHECK(oldGeneration);
    r.effects.actionManifestPath = @"fixture-generation-old"; MSLoadJob *older = Loads.lastObject;
    r.effects.actionManifestPath = @"fixture-generation-new"; MSLoadJob *newer = Loads.lastObject;
    MiniSightActionLibrary *newLibrary = [[MiniSightActionLibrary alloc] initFixtureRoles:@{@"idle": Clip(@"idle", @[@1.])}];
    Load(newer, newLibrary); Load(older, r.library);
    CHECK([r.effects valueForKey:@"library"] == newLibrary && newLibrary.requests.count == 1);
    OnMain(^{ oldGeneration(old); }); CHECK(Pending(r.effects) && !r.effects.hasActions);
    Finish(newLibrary, fresh); OnMain(^{ oldGeneration(old); });
    CHECK(r.effects.hasActions && r.sprite.contents == (__bridge id)fresh.CGImage);
}
static void MissingDragAndChanged(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.]), @"walkRight": Clip(@"walkRight", @[@5.])});
    Finish(r.library, Pixel(100)); [r.effects setLegacyState:1 waking:NO]; Tick(r.effects, 100.01);
    CHECK([Role(r.effects) isEqual:@"walkRight"]); Finish(r.library, Pixel(110));
    CGPoint origin = r.pet.center; [r.effects beginDragAt:CGPointMake(20, 20)];
    CHECK([Role(r.effects) isEqual:@"idle"] && [[r.effects valueForKey:@"wantedRole"] isEqual:@"drag"]);
    CHECK([r.library.pending.clip.role isEqual:@"idle"]); Finish(r.library, Pixel(120));
    double start = Start(r.effects); NSUInteger token = Epoch(r.effects), count = r.library.requests.count;
    for (NSUInteger i = 1; i <= 8; ++i) {
        Now = 100.01 + i * .02; [r.effects beginDragAt:CGPointMake(30, 30)]; [r.effects dragTo:origin]; Tick(r.effects, Now);
        CHECK([Role(r.effects) isEqual:@"idle"] && Epoch(r.effects) == token && Start(r.effects) == start);
        CHECK(CGPointEqualToPoint(r.pet.center, origin)); // Missing drag never presents a walking clip.
    }
    CHECK(r.library.requests.count == count && r.effects.isDragging);
    CHECK(CGPointEqualToPoint([r.effects endDragCancelled:YES], CGPointZero));
}
static void CancelAndVelocity(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.]), @"drag": Clip(@"drag", @[@5.])});
    Finish(r.library, Pixel(100)); [r.effects beginDragAt:CGPointMake(20, 20)]; Finish(r.library, Pixel(110));
    double start = Start(r.effects); NSUInteger token = Epoch(r.effects), count = r.library.requests.count;
    CGPoint origin = r.pet.center;
    for (NSUInteger i = 1; i <= 5; ++i) {
        Now = 100. + i * .02; [r.effects beginDragAt:CGPointMake(20, 20)];
        [r.effects dragTo:CGPointMake(origin.x + i * 10., origin.y)]; Tick(r.effects, Now);
        CHECK([Role(r.effects) isEqual:@"drag"] && Epoch(r.effects) == token && Start(r.effects) == start);
    }
    CHECK(r.library.requests.count == count);
    CHECK(CGPointEqualToPoint([r.effects endDragCancelled:YES], CGPointZero) && !r.effects.isDragging);
    CHECK(![[r.effects valueForKey:@"flying"] boolValue] && [[r.effects valueForKey:@"landUntil"] doubleValue] == 0.);
    Finish(r.library, Pixel(120));
    Now = 101.; origin = r.pet.center; [r.effects beginDragAt:CGPointMake(20, 20)]; Finish(r.library, Pixel(130));
    Now = 101.05; [r.effects dragTo:CGPointMake(origin.x + 20., origin.y + 10.)];
    Now = 101.10; [r.effects dragTo:CGPointMake(origin.x + 40., origin.y + 20.)];
    Now = 101.12; CGPoint velocity = [r.effects endDragCancelled:NO];
    CHECK(fabs(velocity.x - 400.) < .00001 && fabs(velocity.y - 200.) < .00001 && !r.effects.isDragging);
    // A cancelled gesture did not leak samples; stale normal releases do not fling.
    Now = 102.; [r.effects beginDragAt:CGPointMake(20, 20)];
    Now = 102.05; [r.effects dragTo:CGPointMake(origin.x + 40., origin.y)]; Now = 102.25;
    CHECK(CGPointEqualToPoint([r.effects endDragCancelled:NO], CGPointZero));
}
static void StopAndPurge(void) {
    for (NSUInteger mode = 0; mode < 3; ++mode) { @autoreleasepool {
        MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@1.])});
        FrameReply stale = [r.library.pending.reply copy]; NSUInteger token = Epoch(r.effects), purges = r.library.purges;
        MSFixtureDisplayLink *link = [r.effects valueForKey:@"link"];
        if (mode == 0) [r.effects setRunning:NO];
        else if (mode == 1) r.effects.actionManifestPath = nil;
        else [r.effects invalidate];
        CHECK(!Pending(r.effects) && !r.library.pending && r.library.purges > purges && Epoch(r.effects) > token);
        CHECK(!r.effects.hasActions && BubbleHidden(r.effects));
        UIImage *late = Pixel(250); OnMain(^{ stale(late); }); CHECK(!r.effects.hasActions && !Pending(r.effects));
        if (mode != 1) CHECK(link.invalidated && ![r.effects valueForKey:@"link"]);
        if (mode == 0) {
            [r.effects setRunning:YES]; CHECK(Pending(r.effects));
            OnMain(^{ stale(late); }); CHECK(Pending(r.effects) && !r.effects.hasActions);
            Finish(r.library, late); CHECK(r.effects.hasActions);
        }
    } }
}
static void TapAndIdleAltFinish(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@1.]), @"tap": Clip(@"tap", @[@.25, @.25, @.5]),
                    @"idleAlt": Clip(@"idleAlt", @[@.2, @.3, @.8])});
    Finish(r.library, Pixel(100)); CHECK(r.effects.hasDailyActions); [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 100.1);
    CHECK(r.effects.autonomyHeld && [Role(r.effects) isEqual:@"tap"] && Start(r.effects) == 0.);
    Now = 100.5; Finish(r.library, Pixel(200)); double start = Start(r.effects);
    [r.effects setLegacyState:0 waking:NO]; Tick(r.effects, 100.8);
    CHECK(r.library.pending.index == 1); Finish(r.library, Pixel(201));
    Tick(r.effects, 101.49); CHECK(r.library.pending.index == 2);
    UIImage *tapEnd = Pixel(202); Finish(r.library, tapEnd);
    CHECK([Role(r.effects) isEqual:@"tap"] && r.effects.autonomyHeld && Start(r.effects) == start);
    Tick(r.effects, 101.51); CHECK([Role(r.effects) isEqual:@"idle"] && !r.effects.autonomyHeld);
    CHECK(r.sprite.contents == (__bridge id)tapEnd.CGImage); Finish(r.library, Pixel(100));

    CHECK(fabs([r.effects performIdleAction] - 1.3) < .00001 && r.effects.autonomyHeld);
    Now = 101.91; Finish(r.library, Pixel(210)); start = Start(r.effects); NSUInteger token = Epoch(r.effects);
    CHECK(fabs([[r.effects valueForKey:@"transientUntil"] doubleValue] - start - 1.3) < .00001);
    Tick(r.effects, 102.2); CHECK(r.library.pending.index == 1); Finish(r.library, Pixel(211));
    Tick(r.effects, 102.7); CHECK(r.library.pending.index == 2); Finish(r.library, Pixel(212));
    double remaining = [r.effects performIdleAction];
    CHECK(fabs(remaining - .51) < .00001 && Start(r.effects) == start && Epoch(r.effects) == token);
    Tick(r.effects, 103.20); CHECK([Role(r.effects) isEqual:@"idleAlt"] && r.effects.autonomyHeld);
    Tick(r.effects, 103.22); CHECK([Role(r.effects) isEqual:@"idle"] && !r.effects.autonomyHeld);
    CHECK(![r.effects valueForKey:@"transientRole"]); Finish(r.library, Pixel(100));
}
static void DailyActionCategoryAndRepeat(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@2.]),
        @"idleAlt": @[DailyClip(@"stretch", @"micro", @[@.2, @.3]), DailyClip(@"toy", @"play", @[@.4])]});
    Finish(r.library, Pixel(100));
    CGPoint fixed = r.pet.center;
    CHECK([r.effects performDailyAction] > 0.);
    MiniSightActionClip *first = [r.effects valueForKey:@"clip"];
    CHECK([first.role isEqual:@"idleAlt"] && ([first.category isEqual:@"micro"] || [first.category isEqual:@"play"]));
    Finish(r.library, Pixel(110));
    Now = Start(r.effects) + first.duration + .02; Tick(r.effects, Now);
    CHECK([Role(r.effects) isEqual:@"idle"] && CGPointEqualToPoint(fixed, r.pet.center));
    CHECK([r.effects performDailyAction] > 0.);
    MiniSightActionClip *second = [r.effects valueForKey:@"clip"];
    CHECK(![first.identifier isEqualToString:second.identifier]); // Even a one-clip category cannot repeat immediately.
    CHECK(CGPointEqualToPoint(fixed, r.pet.center));
    r.effects.musicPlaying = YES;
    CHECK([r.effects performDailyAction] == 0.); // Daily life never substitutes for music beat capture.
}
static void DelayedTapFirstFrame(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.]), @"tap": Clip(@"tap", @[@1.])});
    Finish(r.library, Pixel(100)); [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 100.1);
    NSUInteger token = Epoch(r.effects); [r.effects setLegacyState:0 waking:NO]; Tick(r.effects, 100.9);
    CHECK([Role(r.effects) isEqual:@"tap"] && Pending(r.effects) && Epoch(r.effects) == token);
    Finish(r.library, Pixel(200)); CHECK(Start(r.effects) == 100.9);
    Tick(r.effects, 101.8); CHECK([Role(r.effects) isEqual:@"tap"] && r.effects.autonomyHeld);
    Tick(r.effects, 101.91); CHECK([Role(r.effects) isEqual:@"idle"]); Finish(r.library, Pixel(100));
}
static void ShortTapDoesNotLoop(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.]), @"tap": Clip(@"tap", @[@.1, @.1])});
    Finish(r.library, Pixel(100)); [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 100.01);
    Finish(r.library, Pixel(200)); Tick(r.effects, 100.22);
    CHECK(r.library.pending.index == 1); Finish(r.library, Pixel(201));
    NSUInteger count = r.library.requests.count; double start = Start(r.effects);
    Tick(r.effects, 100.9); CHECK(r.library.requests.count == count && Start(r.effects) == start);
    CHECK([Role(r.effects) isEqual:@"tap"]); // Holding an input does not replay frame zero.
    [r.effects setLegacyState:0 waking:NO]; Tick(r.effects, 101.0); Finish(r.library, Pixel(100));
    [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 101.1);
    CHECK([Role(r.effects) isEqual:@"tap"] && r.library.pending.index == 0); Finish(r.library, Pixel(200));
}
static void BusyRetreat(void) {
    for (NSUInteger trigger = 0; trigger < 2; ++trigger) for (NSUInteger blocker = 0; blocker < 2; ++blocker) { @autoreleasepool {
        MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@1.]), @"tap": Clip(@"tap", @[@1.]), @"idleAlt": Clip(@"idleAlt", @[@1.3])});
        Finish(r.library, Pixel(100));
        if (trigger == 0) { [r.effects setLegacyState:3 waking:NO]; Tick(r.effects, 100.01); }
        else CHECK([r.effects performIdleAction] > 0.);
        Now = 100.05; Finish(r.library, Pixel(200));
        if (trigger == 0) [r.effects setLegacyState:0 waking:NO];
        r.effects.lyricsLine = @"synthetic local line"; Tick(r.effects, 100.06);
        CHECK(r.effects.autonomyHeld && !BubbleHidden(r.effects));
        if (blocker == 0) r.effects.busy = YES; else [MiniSightChatPanel fixtureSetVisible:YES];
        CHECK(!r.effects.autonomyHeld); Tick(r.effects, 100.1);
        CHECK([Role(r.effects) isEqual:@"idle"] && [r.effects performIdleAction] == 0. && BubbleHidden(r.effects));
        CHECK(![r.effects valueForKey:@"transientRole"] && [[r.effects valueForKey:@"transientUntil"] doubleValue] == 0.);
        Finish(r.library, Pixel(100)); r.effects.busy = NO; [MiniSightChatPanel fixtureSetVisible:NO]; Tick(r.effects, 100.2);
        CHECK([Role(r.effects) isEqual:@"idle"] && !r.effects.autonomyHeld); // No interrupted transient replay.
    } }
}
static void LyricsOnly(void) {
    // Entirely synthetic data; no account, defaults, user files or track metadata
    // lookup. Only the actual production lineAtTime result reaches lyricsLine.
    NSString *lrc = @"[ti:NEVER_TITLE]\n[ar:NEVER_ARTIST]\n[00:01.00]local alpha\n[00:03.00]\n[00:05.00]local beta\n[00:30.00]local gamma";
    MiniSightLyricsTimeline *timeline = [MiniSightLyricsTimeline timelineWithLRC:lrc duration:60.]; CHECK(timeline);
    MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc] initWithTitle:@"NEVER_TITLE" artist:@"NEVER_ARTIST" duration:60.]; CHECK(track);
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.])}); Finish(r.library, Pixel(100));
    CGPoint center = r.pet.center; CGRect bounds = r.pet.bounds;
    NSArray *times = @[@.5, @1., @2.99, @3., @5., @16.99, @17., @30., @59.99, @60., @(NAN)];
    NSArray *texts = @[NSNull.null, @"local alpha", @"local alpha", NSNull.null, @"local beta", @"local beta", NSNull.null, @"local gamma", NSNull.null, NSNull.null, NSNull.null];
    for (NSUInteger i = 0; i < times.count; ++i) {
        NSString *line = [timeline lineAtTime:[times[i] doubleValue]];
        if (texts[i] == NSNull.null) CHECK(!line); else CHECK([line isEqual:texts[i]]);
        r.effects.lyricsLine = line; Tick(r.effects, Now + .02);
        if (!line) CHECK(BubbleHidden(r.effects));
        else {
            UILabel *label = [r.effects valueForKey:@"label"];
            CHECK(!BubbleHidden(r.effects) && [label.text isEqual:line]);
            CHECK(![label.text isEqual:track.title] && ![label.text isEqual:track.artist]);
            CHECK(![label.text containsString:@"NEVER_"]);
        }
        CHECK(CGPointEqualToPoint(r.pet.center, center) && CGRectEqualToRect(r.pet.bounds, bounds));
    }
    // Changing unrelated track metadata/music intent cannot manufacture a title bubble.
    track = [[MiniSightLyricsTrack alloc] initWithTitle:@"OTHER_TITLE" artist:@"OTHER_ARTIST" duration:60.];
    r.effects.musicPlaying = YES; r.effects.lyricsLine = [timeline lineAtTime:1.]; Tick(r.effects, Now + .02);
    CHECK(!BubbleHidden(r.effects) && [[[r.effects valueForKey:@"label"] text] isEqual:@"local alpha"]);
    r.effects.lyricsLine = [timeline lineAtTime:60.]; Tick(r.effects, Now + .02); CHECK(BubbleHidden(r.effects));
    r.effects.lyricsLine = (id)NSNull.null; CHECK(!r.effects.lyricsLine && BubbleHidden(r.effects));
    r.effects.lyricsLine = [@"" stringByPaddingToLength:241 withString:@"x" startingAtIndex:0];
    Tick(r.effects, Now + .02); CHECK(!r.effects.lyricsLine && BubbleHidden(r.effects));
    CHECK(track && r.effects.hasActions);
    // Exercise the actual Effects tick with actual CoreGraphics transformed
    // corners. Edge fitting must not move the host/hit target or break lyrics.
    [r.effects setLegacyState:8 waking:NO]; r.effects.musicPosition = 0.;
    [r.effects setTilt:.22 sway:5.];
    for (int edge = 0; edge < 4; ++edge) {
        r.pet.center = CGPointMake((edge & 1) ? 318. : 42., (edge & 2) ? 733. : 47.);
        CGPoint fixedCenter = r.pet.center;
        for (int frame = 0; frame < 30; ++frame) {
            Tick(r.effects, Now + .02);
            CGRect visual = CGRectApplyAffineTransform(CGRectMake(-40., -45., 80., 90.), r.sprite.affineTransform);
            visual.origin.x += r.pet.center.x; visual.origin.y += r.pet.center.y;
            CHECK(CGRectGetMinX(visual) >= 2. - .001 && CGRectGetMaxX(visual) <= 358. + .001);
            CHECK(CGRectGetMinY(visual) >= 2. - .001 && CGRectGetMaxY(visual) <= 778. + .001);
            CHECK(CGPointEqualToPoint(fixedCenter, r.pet.center));
        }
    }
    // Exercise the continuous, ratio-preserving fallback. These checks do NOT
    // certify new character artwork; the rig's art is deliberately synthetic.
    [r.effects setTilt:0 sway:0]; r.effects.musicPlaying = NO;
    r.pet.center = CGPointMake(180,390);
    [r.effects setFloorImpactVelocity:220]; [r.effects land];
    for (int i=0;i<10;++i) Tick(r.effects,Now+.02);
    CHECK(r.sprite.affineTransform.d > .85); // Ordinary light landing preserved.
    [r.effects setFloorImpactVelocity:950]; [r.effects land];
    [r.effects setLandingRecoveryStage:1];
    for (int i=0;i<16;++i) Tick(r.effects,Now+.02);
    CHECK(r.sprite.affineTransform.b > .35);
    [r.effects setLandingRecoveryStage:2];
    for (int i=0;i<18;++i) Tick(r.effects,Now+.02);
    CAShapeLayer *stars = [r.effects valueForKey:@"dizzyStars"];
    CHECK(stars && !stars.hidden && stars.path && stars.opacity > .5);
    CGAffineTransform t = r.sprite.affineTransform;
    CHECK(fabs(hypot(t.a,t.b)-1.)<.002 && fabs(hypot(t.c,t.d)-1.)<.002);
    [r.effects setLandingRecoveryStage:3];
    for (int i=0;i<40;++i) Tick(r.effects,Now+.02);
    t = r.sprite.affineTransform;
    CHECK(fabs(hypot(t.a,t.b)-1.)<.002 && fabs(hypot(t.c,t.d)-1.)<.002);
    [r.effects setLandingRecoveryStage:4];
    for (int i=0;i<35;++i) Tick(r.effects,Now+.02);
    CHECK(r.sprite.affineTransform.d>.94);
    [r.effects setLandingRecoveryStage:0]; CHECK(stars.hidden);
    FixtureReduceMotion=YES; r.effects.musicPlaying=YES;
    for (int i=0;i<40;++i) Tick(r.effects,Now+.02);
    CHECK(stars.hidden && fabs(r.sprite.affineTransform.b)<.001 && fabs(r.sprite.affineTransform.d-1.)<.001);
    FixtureReduceMotion=NO;
}

static void InPlaceMusicAndLandOwnership(void) {
    @autoreleasepool {
        MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@5.]), @"music": Clip(@"music", @[@.2,@.2])});
        Finish(r.library, Pixel(100));
        CGPoint fixed = r.pet.center; CGRect bounds = r.pet.bounds;
        [r.effects setLegacyState:8 waking:NO]; r.effects.musicPlaying = YES;
        double low=1.,high=-1.;
        for (int i=0;i<240;i++) {
            r.effects.musicPosition = i*.02; Tick(r.effects, Now+.02);
            CHECK([Role(r.effects) isEqual:@"idle"]);
            CHECK(CGPointEqualToPoint(fixed,r.pet.center) && CGRectEqualToRect(bounds,r.pet.bounds));
            CGAffineTransform t = r.sprite.affineTransform;
            CHECK(fabs(hypot(t.a,t.b)-1.)<.001 && fabs(hypot(t.c,t.d)-1.)<.001);
            CHECK(fabs(t.b)<.13);
            low=fmin(low,t.b);high=fmax(high,t.b);
        }
        CHECK(low<-.04 && high>.04); // Sway, not walking, jumping or flattening.
        for (MSFrameJob *job in r.library.requests) CHECK(![job.clip.role isEqual:@"music"]);
        r.effects.musicPlaying=NO; [r.effects setLegacyState:0 waking:NO];
        [r.effects setLandingRecoveryStage:1];
        for(int i=0;i<30;i++) Tick(r.effects,Now+.02);
        CAShapeLayer *stars=[r.effects valueForKey:@"dizzyStars"];
        CHECK(stars && !stars.hidden);
        r.effects.busy=YES;Tick(r.effects,Now+.02);CHECK(stars.hidden);
        r.effects.busy=NO;[r.effects setLandingRecoveryStage:0];
        [r.effects setLandingRecoveryStage:1];
        for(int i=0;i<30;i++) Tick(r.effects,Now+.02);
        CHECK(!stars.hidden); [r.effects setRunning:NO]; CHECK(stars.hidden && !stars.path);
        [r.effects invalidate]; CHECK(!stars.superlayer);
    }
    @autoreleasepool {
        MSRig *r=Rig(@{@"idle":Clip(@"idle",@[@5.]),@"land":Clip(@"land",@[@3.])});
        Finish(r.library,Pixel(100)); [r.effects setLandingRecoveryStage:1];
        CHECK([Role(r.effects) isEqual:@"land"] && r.effects.landingRecoveryHeld);
        FrameReply stale=[r.library.pending.reply copy]; CHECK(stale);
        Now+=1.; Finish(r.library,Pixel(120)); double start=Start(r.effects);
        Now+=2.3; [r.effects setLandingRecoveryStage:4];
        CHECK(r.effects.landingRecoveryHeld && Start(r.effects)==start);
        Tick(r.effects,Now+.01);
        CHECK(fabs(r.sprite.affineTransform.b)<.001); // No second rotation of real art.
        Now+=.8;CHECK(!r.effects.landingRecoveryHeld);
        [r.effects setLandingRecoveryStage:0];CHECK(!r.effects.landingRecoveryHeld);
        CHECK(Pending(r.effects));UIImage *fresh=Pixel(130);Finish(r.library,fresh);
        OnMain(^{stale(Pixel(240));});
        CHECK(r.sprite.contents==(__bridge id)fresh.CGImage && [Role(r.effects) isEqual:@"idle"]);
    }
}

#import "atlas_cases.inc"

int main(void) { @autoreleasepool {
    CHECK(NSThread.isMainThread);
    const struct { const char *name; void (*run)(void); } tests[] = {
        {"first-frame-ownership", FirstFrame}, {"three-bad-frames-poster", ThreeBadFrames},
        {"superseded-role-and-manifest", SupersededRoleAndManifest}, {"missing-drag-and-changed", MissingDragAndChanged},
        {"cancel-and-release-velocity", CancelAndVelocity}, {"stop-purge-parent-pending", StopAndPurge},
        {"tap-idleAlt-finish", TapAndIdleAltFinish}, {"daily-category-no-repeat-no-travel", DailyActionCategoryAndRepeat}, {"delayed-first-tap", DelayedTapFirstFrame},
        {"short-tap-no-loop", ShortTapDoesNotLoop}, {"busy-chat-retreat", BusyRetreat}, {"lyrics-never-title", LyricsOnly},
        {"in-place-music-land-ownership", InPlaceMusicAndLandOwnership},
        {"atlas-layouts-first-frame", AtlasLayouts}, {"atlas-repaint-same-image", AtlasRepaintAndSameImage},
        {"atlas-crop-failure-retry", AtlasCropFailureRetry}, {"atlas-action-poster-metadata", AtlasActionPosterMetadata},
        {"atlas-effects-failure-stop", AtlasEffectsFailureStop}, {"atlas-manifest-swap", AtlasManifestSwap}
    };
    @try {
        for (NSUInteger i = 0; i < sizeof(tests) / sizeof(tests[0]); ++i) {
            Case = tests[i].name; @autoreleasepool { tests[i].run(); }
            printf("NATIVE PASS: %s\n", Case);
        }
    } @catch (NSException *error) {
        fprintf(stderr, "FAIL: %s exception: %s\n", Case, error.name.UTF8String); return 1;
    }
    CHECK(!Loads.count);
    puts("NATIVE PASS: 11 original PetEffects + 1 daily-action + 6 production-excerpt atlas + 1 in-place/land ownership groups; no iOS/visual/network/device execution");
    return 0;
} }
