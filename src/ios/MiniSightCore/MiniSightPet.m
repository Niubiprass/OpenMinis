//
//  MiniSightPet.m
//  MiniSight
//
//  One 9-row atlas, one sprite clock, and actual-center motion.
//
//  Every movement of this view is confined to `centerBounds`: the feasible CENTER
//  range the host computes from the safe area plus the bubble headroom. This file
//  never derives a body rectangle from superview.bounds, creates no gesture
//  recognizer, and links to no tweak global. Roaming pace comes from the
//  `activityActive` property only.
//

#import "MiniSightPet.h"
#import "MiniSightGeometry.h"
#import "MiniSightGravity.h"
#import <QuartzCore/QuartzCore.h>
#import <math.h>
#import <stdlib.h>

typedef NS_ENUM(NSInteger, MiniSightPetState) {
    MiniSightPetStateIdle = 0,
    MiniSightPetStateRunRight = 1,
    MiniSightPetStateRunLeft = 2,
    MiniSightPetStateWaving = 3,
    MiniSightPetStateJumping = 4,
};

static const NSInteger kMiniSightPetRows = 9;
static const NSInteger kMiniSightPetMaxCols = 8;
static const NSTimeInterval kMiniSightSpriteInterval = 1.0 / 7.0;

// Roaming delays. Only the delay between actions changes; FPS never does.
static const NSTimeInterval kMiniSightRoamActiveLo = 2.0;   // activityActive == YES
static const NSTimeInterval kMiniSightRoamActiveHi = 5.0;
static const NSTimeInterval kMiniSightRoamIdleLo = 9.0;     // activityActive == NO (resident idle)
static const NSTimeInterval kMiniSightRoamIdleHi = 15.0;

static const double kMiniSightWalkSpeed = 160.0;            // points per second
static const double kMiniSightWalkMinDuration = 0.55;
static const double kMiniSightWalkMaxDuration = 2.2;
static const double kMiniSightJumpDuration = 0.5;
static const double kMiniSightJumpDesiredHeight = 26.0;     // still capped by MSJumpHeight()
static const double kMiniSightJumpMinHeight = 6.0;          // below this a "jump" is a no-op
static const NSTimeInterval kMiniSightWaveHold = 1.2;

// Gravity is rendered on a child layer so the UIView's own transform and
// coordinate conversion remain identity for hit testing and host layout.
// Angle + lateral sway remain inside the shared conservative envelope.
static const CGFloat kMiniSightGravityImpulseAngle = (CGFloat)(M_PI * 42.0 / 180.0);
static const NSTimeInterval kMiniSightGravityImpulseDuration = 0.62;

static CGFloat MSPetClampUnit(CGFloat value) {
    if (!isfinite(value)) return 0.0;
    return MIN(1.0, MAX(-1.0, value));
}

static CGSize MSPetGravityEnvelope(CGSize size) {
    MSSize envelope = MSGravityEnvelope((MSSize){size.width, size.height});
    return CGSizeMake(envelope.w, envelope.h);
}

static double MSPetRandomUnit(void) { return arc4random_uniform(1000001) / 1000000.0; }
static double MSPetRandomRange(double lo, double hi) {
    return (hi <= lo) ? lo : (lo + (hi - lo) * MSPetRandomUnit());
}
static MSPoint MSPetPoint(CGPoint p) { return (MSPoint){(double)p.x, (double)p.y}; }
static CGPoint MSPetCGPoint(MSPoint p) { return CGPointMake((CGFloat)p.x, (CGFloat)p.y); }

// CADisplayLink retains its target: the target must not retain the view.
@interface MiniSightPetDisplayLinkProxy : NSObject
@property (nonatomic, weak) MiniSightPetView *owner;
- (void)displayTick:(CADisplayLink *)link;
- (void)gravityDisplayTick:(CADisplayLink *)link;
@end

@interface MiniSightPetView () {
    UIImage *_sheet;
    NSTimer *_frameTimer;
    NSTimer *_roamTimer;
    CADisplayLink *_motionLink;
    MiniSightPetDisplayLinkProxy *_motionProxy;
    CADisplayLink *_gravityLink;
    MiniSightPetDisplayLinkProxy *_gravityProxy;
    CALayer *_gravityLayer;
    MiniSightPetState _state;
    NSInteger _column;
    CFTimeInterval _lastSpriteTime;
    BOOL _wantsPlaying, _suspended, _hasCenterBounds;
    BOOL _geometryReady, _settingGeometry, _motionActive;
    CGPoint _lastNotifiedCenter;
    CGRect _lastNotifiedBounds;
    MSPoint _motionStart, _motionEnd;
    double _jumpHeight;
    CFTimeInterval _motionBegan, _motionDuration;
    CFTimeInterval _stateHoldUntil;
    NSTimeInterval _restAfterMotion;
    BOOL _gravityEnabled;
    CGFloat _gravityRoll;
    CGFloat _gravityImpulseAngle;
    CFTimeInterval _gravityImpulseBegan;
    CFTimeInterval _gravityImpulseDuration;
    NSUInteger _gravityGeneration;
    NSUInteger _activeGravityGeneration;
    NSUInteger _motionGeneration, _activeMotionGeneration, _roamGeneration;
    CGRect _centerBounds;
    BOOL _activityActive, _longPressEnabled, _roamingPaused, _interactionActive, _reducedWork;
    void (^_onGeometryChanged)(void);
    void (^_onLongPress)(void);
}
- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize;
- (BOOL)isActuallyVisible;
- (BOOL)shouldAnimate;
- (BOOL)mayRoam;
- (void)reconcilePlayback;
- (void)invalidateFrameTimer;
- (void)invalidateRoamTimer;
- (void)ensureFrameTimer;
- (void)frameTick:(NSTimer *)timer;
- (NSInteger)frameCountForRow:(NSInteger)row;
- (void)setSpriteState:(MiniSightPetState)state;
- (void)advanceSpriteAtTime:(CFTimeInterval)now;
- (void)applySpriteFrame;
- (MSRect)feasibleCenters;
- (CGPoint)clampedCenter:(CGPoint)point;
- (void)geometryDidChange;
- (void)windowVisibilityChanged:(NSNotification *)notification;
- (void)scheduleRoam;
- (void)armRoamTimerWithDelay:(NSTimeInterval)delay;
- (void)roamOnce;
- (void)holdState:(MiniSightPetState)state forDuration:(NSTimeInterval)duration;
- (void)startMotionTo:(CGPoint)target jump:(BOOL)jump rest:(NSTimeInterval)rest;
- (void)ensureMotionLink;
- (void)finishMotion;
- (void)cancelMotion;
- (void)motionTick:(CADisplayLink *)link;
- (void)ensureGravityLayer;
- (void)updateGravityLayerGeometry;
- (CGFloat)gravityAngleAtTime:(CFTimeInterval)now;
- (void)setGravityLayerAngle:(CGFloat)angle animated:(BOOL)animated;
- (void)applyGravityTransformAtTime:(CFTimeInterval)now;
- (void)ensureGravityLink;
- (void)cancelGravityImpulse;
- (void)gravityTick:(CADisplayLink *)link;
@end

@implementation MiniSightPetDisplayLinkProxy
- (void)displayTick:(CADisplayLink *)link {
    MiniSightPetView *owner = self.owner;
    if (owner) [owner motionTick:link];
    else [link invalidate];
}

- (void)gravityDisplayTick:(CADisplayLink *)link {
    MiniSightPetView *owner = self.owner;
    if (owner) [owner gravityTick:link];
    else [link invalidate];
}
@end

@implementation MiniSightPetView
@synthesize centerBounds = _centerBounds, onGeometryChanged = _onGeometryChanged;
@synthesize activityActive = _activityActive, longPressEnabled = _longPressEnabled;
@synthesize roamingPaused = _roamingPaused, interactionActive = _interactionActive;
@synthesize reducedWork = _reducedWork, onLongPress = _onLongPress;

- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    CGSize size = CGSizeMake(fmax(1., MSFinite(displaySize.width, 1.)),
                             fmax(1., MSFinite(displaySize.height, 1.)));
    self = [super initWithFrame:(CGRect){CGPointZero, size}];
    if (self) {
        _sheet = sprite;
        _longPressEnabled = YES; // Configuration storage; the host owns gestures.
        self.contentMode = UIViewContentModeScaleAspectFit;
        self.userInteractionEnabled = YES;
        self.layer.contentsGravity = kCAGravityResizeAspect;
        self.layer.contentsScale = sprite.scale;
        self.layer.minificationFilter = kCAFilterLinear;
        self.layer.magnificationFilter = kCAFilterLinear;
        self.layer.masksToBounds = NO;
        // Keep the UIView's layer untransformed. The child layer carries the
        // visual tilt, so UIView hit testing and coordinate conversion remain
        // based on the original bounds.
        [self ensureGravityLayer];
        self.layer.contents = nil;
        _state = MiniSightPetStateIdle;
        _lastSpriteTime = CACurrentMediaTime();
        [self applySpriteFrame];
        _lastNotifiedCenter = self.center;
        _lastNotifiedBounds = self.bounds;
        _geometryReady = YES;
        NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
        [nc addObserver:self selector:@selector(windowVisibilityChanged:)
                   name:UIWindowDidBecomeHiddenNotification object:nil];
        [nc addObserver:self selector:@selector(windowVisibilityChanged:)
                   name:UIWindowDidBecomeVisibleNotification object:nil];
    }
    return self;
}

- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
    [_frameTimer invalidate];
    [_roamTimer invalidate];
    [_motionLink invalidate];
    [_gravityLink invalidate];
    _motionProxy.owner = nil;
    _gravityProxy.owner = nil;
}

#pragma mark - Playback intent and lifecycle (main thread)

- (void)startPlaying {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    _wantsPlaying = YES;
    [self reconcilePlayback];
}

- (void)stopPlaying {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    _wantsPlaying = NO;
    [self invalidateFrameTimer];
    [self invalidateRoamTimer];
    [self cancelMotion];
    [self cancelGravityImpulse];
}

- (void)setSuspended:(BOOL)suspended {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_suspended == suspended) return;
    _suspended = suspended;
    if (suspended) [self cancelGravityImpulse];
    [self reconcilePlayback]; // Never invents playback intent; startPlaying is not called.
}

- (void)setActivityActive:(BOOL)active {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_activityActive == active) return;
    _activityActive = active;
    [self invalidateRoamTimer];
    [self scheduleRoam]; // Only the roaming delay changes; no FPS change.
}

- (void)setRoamingPaused:(BOOL)paused {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_roamingPaused == paused) return;
    _roamingPaused = paused;
    [self reconcilePlayback];
}

- (void)setInteractionActive:(BOOL)active {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_interactionActive == active) return;
    _interactionActive = active;
    if (active) [self cancelGravityImpulse];
    [self reconcilePlayback];
}

- (void)setReducedWork:(BOOL)reduced {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_reducedWork == reduced) return;
    _reducedWork = reduced;
    // Do not freeze the sprite or gravity as a substitute for optimization.
    // Only the gap before the NEXT resident-idle roam is extended.
    [self invalidateRoamTimer];
    [self scheduleRoam];
}

- (void)setHidden:(BOOL)hidden {
    [super setHidden:hidden];
    if (_geometryReady) [self reconcilePlayback];
}

- (void)setAlpha:(CGFloat)alpha {
    [super setAlpha:alpha];
    if (_geometryReady) [self reconcilePlayback];
}

- (void)didMoveToWindow {
    [super didMoveToWindow];
    if (!_geometryReady) return;
    [self geometryDidChange];
    [self reconcilePlayback];
}

- (void)windowVisibilityChanged:(NSNotification *)notification {
    if (notification.object == self.window) [self reconcilePlayback];
}

- (BOOL)isActuallyVisible {
    if (!self.window || self.window.hidden || self.window.alpha <= 0.01) return NO;
    for (UIView *view = self; view; view = view.superview) {
        if (view.hidden || view.alpha <= 0.01) return NO;
    }
    return YES;
}

- (BOOL)shouldAnimate {
    return _wantsPlaying && !_suspended && [self isActuallyVisible] && _sheet.CGImage;
}

- (BOOL)mayRoam {
    MSRect area = [self feasibleCenters];
    return [self shouldAnimate] && _hasCenterBounds &&
           !_roamingPaused && !_interactionActive && (area.w > 0. || area.h > 0.);
}

- (void)reconcilePlayback {
    if (![self shouldAnimate]) {
        [self invalidateFrameTimer];
        [self invalidateRoamTimer];
        [self cancelMotion];
        [self cancelGravityImpulse];
        return;
    }
    if (![self mayRoam]) {
        [self invalidateRoamTimer];
        [self cancelMotion];
    }
    if (!_motionActive) [self ensureFrameTimer];
    if (!_motionActive && !_roamTimer && _stateHoldUntil <= 0.) [self scheduleRoam];
}

- (void)invalidateFrameTimer {
    [_frameTimer invalidate];
    _frameTimer = nil;
}

- (void)invalidateRoamTimer {
    ++_roamGeneration;
    [_roamTimer invalidate];
    _roamTimer = nil;
}

#pragma mark - Atlas playback (7 sprite frames per second, never a frame cache)

- (void)ensureFrameTimer {
    if (_frameTimer || _motionActive || ![self shouldAnimate]) return;
    _lastSpriteTime = CACurrentMediaTime();
    __weak typeof(self) weakSelf = self;
    _frameTimer = [NSTimer timerWithTimeInterval:kMiniSightSpriteInterval repeats:YES
                                         block:^(NSTimer *timer) {
        [weakSelf frameTick:timer];
    }];
    _frameTimer.tolerance = 0.025;
    [NSRunLoop.mainRunLoop addTimer:_frameTimer forMode:NSRunLoopCommonModes];
}

- (void)frameTick:(NSTimer *)timer {
    if (timer != _frameTimer) return;
    if (![self shouldAnimate]) { [self reconcilePlayback]; return; }
    CFTimeInterval now = CACurrentMediaTime();
    if (_stateHoldUntil > 0. && now >= _stateHoldUntil) {
        _stateHoldUntil = 0.;
        [self setSpriteState:MiniSightPetStateIdle];
        if (!_roamTimer && !_motionActive) [self scheduleRoam];
    }
    [self advanceSpriteAtTime:now];
}

- (NSInteger)frameCountForRow:(NSInteger)row {
    static const NSInteger counts[9] = {6, 8, 8, 4, 5, 8, 6, 6, 6};
    return (row >= 0 && row < kMiniSightPetRows) ? counts[row] : 1;
}

- (void)setSpriteState:(MiniSightPetState)state {
    if (_state == state) return;
    _state = state;
    _column = 0;
    _lastSpriteTime = CACurrentMediaTime();
    [self applySpriteFrame];
}

- (void)advanceSpriteAtTime:(CFTimeInterval)now {
    double elapsed = fmax(0., now - _lastSpriteTime);
    if (elapsed < kMiniSightSpriteInterval) return;
    double steps = floor(elapsed / kMiniSightSpriteInterval);
    NSInteger count = [self frameCountForRow:_state];
    _lastSpriteTime = now - fmod(elapsed, kMiniSightSpriteInterval);
    NSInteger next = (_column + (NSInteger)fmod(steps, (double)count)) % count;
    if (next == _column) return;
    _column = next;
    [self applySpriteFrame];
}

- (void)applySpriteFrame {
    if (!_sheet.CGImage || !_gravityLayer) return;
    CGRect rect = CGRectMake((CGFloat)_column / kMiniSightPetMaxCols,
                             (CGFloat)_state / kMiniSightPetRows,
                             1.0 / kMiniSightPetMaxCols, 1.0 / kMiniSightPetRows);
    if (CGRectEqualToRect(_gravityLayer.contentsRect, rect)) return;
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.contentsRect = rect;
    [CATransaction commit];
}

#pragma mark - Gravity visual layer

- (CGSize)gravitySafeSize {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    CGSize size = self.bounds.size;
    return _gravityEnabled ? MSPetGravityEnvelope(size) : size;
}

- (void)ensureGravityLayer {
    if (_gravityLayer) return;
    CALayer *layer = [CALayer layer];
    layer.contentsGravity = kCAGravityResizeAspect;
    layer.contentsScale = _sheet.scale;
    layer.minificationFilter = kCAFilterLinear;
    layer.magnificationFilter = kCAFilterLinear;
    // Host guarantees an upright, already decoded/downsampled atlas.
    layer.contents = (__bridge id)_sheet.CGImage;
    [self.layer addSublayer:layer];
    _gravityLayer = layer;
    [self updateGravityLayerGeometry];
}

- (void)updateGravityLayerGeometry {
    if (!_gravityLayer) return;
    // Setting frame while affineTransform is nonidentity is undefined. bounds +
    // position keeps atlas sizing stable across rotations and pet-size changes.
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.bounds = (CGRect){CGPointZero, self.bounds.size};
    _gravityLayer.anchorPoint = CGPointMake(0.5, 0.5);
    _gravityLayer.position = CGPointMake(CGRectGetMidX(self.bounds), CGRectGetMidY(self.bounds));
    [CATransaction commit];
}

- (CGPoint)speechAnchor {
    CGFloat sway = _gravityEnabled ? MSPetClampUnit(_gravityRoll) * MSGravitySway(self.bounds.size.width) : 0.;
    return CGPointMake(self.center.x + sway, self.center.y);
}

- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    // The visible sprite can tilt outside the original UIImageView bounds.
    // Only its bounded envelope catches touches; the rest of the window passes.
    CGSize envelope = self.gravitySafeSize;
    CGRect target = CGRectMake(CGRectGetMidX(self.bounds) - envelope.width * .5,
                               CGRectGetMidY(self.bounds) - envelope.height * .5,
                               envelope.width, envelope.height);
    return CGRectContainsPoint(CGRectInset(target, -4., -4.), point);
}

- (CGFloat)gravityAngleAtTime:(CFTimeInterval)now {
    if (!_gravityEnabled) return 0.;
    double progress = _gravityImpulseDuration > 0. ? (now - _gravityImpulseBegan) / _gravityImpulseDuration : 1.;
    return MSGravityAngle(_gravityRoll, _gravityImpulseAngle, progress);
}

- (void)setGravityLayerAngle:(CGFloat)angle animated:(BOOL)animated {
    (void)animated;
    if (!_gravityLayer) return;
    angle = MSClamp(angle, -MS_GRAVITY_MAX_ANGLE, MS_GRAVITY_MAX_ANGLE);
    CGFloat sway = _gravityEnabled ? MSPetClampUnit(_gravityRoll) * MSGravitySway(self.bounds.size.width) : 0.;
    CGAffineTransform transform = CGAffineTransformMakeRotation(angle);
    transform.tx = sway;
    if (CGAffineTransformEqualToTransform(_gravityLayer.affineTransform, transform)) return;
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.affineTransform = transform;
    [CATransaction commit];
    // This callback is cheap and position-only in the host (no text measurement).
    if (_geometryReady && _onGeometryChanged) _onGeometryChanged();
}

- (void)applyGravityTransformAtTime:(CFTimeInterval)now {
    [self setGravityLayerAngle:[self gravityAngleAtTime:now] animated:NO];
}

- (void)setGravityEnabled:(BOOL)enabled {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_gravityEnabled == enabled) {
        [self applyGravityTransformAtTime:CACurrentMediaTime()];
        return;
    }
    _gravityEnabled = enabled;
    if (!enabled) {
        _gravityRoll = 0.0;
        [self cancelGravityImpulse];
    }
    [self updateGravityLayerGeometry];
    [self applyGravityTransformAtTime:CACurrentMediaTime()];
}

- (BOOL)gravityEnabled {
    return _gravityEnabled;
}

- (CGFloat)gravityRoll {
    return _gravityRoll;
}

- (void)setGravityRoll:(CGFloat)roll {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_interactionActive) return; // finger-down freezes the visible tilt too
    _gravityRoll = MSPetClampUnit(roll);
    [self applyGravityTransformAtTime:CACurrentMediaTime()];
}

- (void)ensureGravityLink {
    if (_gravityLink || !_gravityEnabled || !_gravityImpulseDuration) return;
    if (![self shouldAnimate] || _suspended) return;
    if (!_gravityProxy) _gravityProxy = [[MiniSightPetDisplayLinkProxy alloc] init];
    _gravityProxy.owner = self;
    CADisplayLink *link = [CADisplayLink displayLinkWithTarget:_gravityProxy
                                                      selector:@selector(gravityDisplayTick:)];
    if (!link) return;
    link.preferredFramesPerSecond = 30;
    [link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
    _gravityLink = link;
}

- (void)cancelGravityImpulse {
    ++_gravityGeneration;
    _gravityImpulseAngle = 0.0;
    _gravityImpulseBegan = 0.0;
    _gravityImpulseDuration = 0.0;
    [_gravityLink invalidate];
    _gravityLink = nil;
    [self applyGravityTransformAtTime:CACurrentMediaTime()];
}

- (void)triggerGravityImpulseWithDirection:(CGFloat)direction strength:(CGFloat)strength {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (!_gravityEnabled || !_wantsPlaying || _suspended || _interactionActive || ![self isActuallyVisible]) return;
    direction = MSPetClampUnit(direction);
    strength = MIN(1.0, MAX(0.0, isfinite(strength) ? strength : 0.0));
    if (fabs(direction) < 0.01 || strength < 0.05) return;
    _gravityImpulseAngle = direction * strength * kMiniSightGravityImpulseAngle;
    _gravityImpulseBegan = CACurrentMediaTime();
    _gravityImpulseDuration = kMiniSightGravityImpulseDuration;
    _activeGravityGeneration = ++_gravityGeneration;
    [self ensureGravityLink];
    [self applyGravityTransformAtTime:_gravityImpulseBegan];
}

- (void)gravityTick:(CADisplayLink *)link {
    if (link != _gravityLink) return;
    if (!_gravityEnabled || !_wantsPlaying || _suspended || _interactionActive || ![self isActuallyVisible]) {
        [self cancelGravityImpulse];
        return;
    }
    if (_activeGravityGeneration != _gravityGeneration) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - _gravityImpulseBegan >= _gravityImpulseDuration) {
        [self cancelGravityImpulse];
        return;
    }
    [self applyGravityTransformAtTime:now];
}

#pragma mark - Actual geometry, shared with hit testing and the bubble

- (void)setCenterBounds:(CGRect)bounds {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    CGRect clean = CGRectMake(MSFinite(bounds.origin.x, self.center.x),
                              MSFinite(bounds.origin.y, self.center.y),
                              fmax(0., MSFinite(bounds.size.width, 0.)),
                              fmax(0., MSFinite(bounds.size.height, 0.)));
    if (_hasCenterBounds && CGRectEqualToRect(clean, _centerBounds)) return;
    _hasCenterBounds = YES;
    _centerBounds = clean;
    // A new feasible range invalidates the old trajectory before clamping.
    [self invalidateRoamTimer];
    [self cancelMotion];
    self.center = self.center;
    [self reconcilePlayback];
}

- (MSRect)feasibleCenters {
    return (MSRect){_centerBounds.origin.x, _centerBounds.origin.y,
                    _centerBounds.size.width, _centerBounds.size.height};
}

- (CGPoint)clampedCenter:(CGPoint)point {
    if (!_hasCenterBounds) return point;
    return MSPetCGPoint(MSClampCenter([self feasibleCenters], MSPetPoint(point)));
}

- (void)setCenter:(CGPoint)center {
    center = [self clampedCenter:center];
    BOOL nested = _settingGeometry;
    _settingGeometry = YES;
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    [super setCenter:center];
    [CATransaction commit];
    _settingGeometry = nested;
    if (!nested) [self geometryDidChange];
}

- (void)setBounds:(CGRect)bounds {
    BOOL nested = _settingGeometry;
    _settingGeometry = YES;
    [super setBounds:bounds];
    [self updateGravityLayerGeometry];
    _settingGeometry = nested;
    if (!nested) [self geometryDidChange];
}

- (void)setFrame:(CGRect)frame {
    BOOL nested = _settingGeometry;
    _settingGeometry = YES;
    [super setFrame:frame];
    [self updateGravityLayerGeometry];
    _settingGeometry = nested;
    if (!nested) [self geometryDidChange];
}

- (void)geometryDidChange {
    if (!_geometryReady) return;
    CGPoint center = [self clampedCenter:self.center];
    if (!CGPointEqualToPoint(center, self.center)) {
        BOOL nested = _settingGeometry;
        _settingGeometry = YES;
        [CATransaction begin];
        [CATransaction setDisableActions:YES];
        [super setCenter:center];
        [CATransaction commit];
        _settingGeometry = nested;
    }
    // Notify on real changes only, and save the geometry first: a callback may
    // clamp, hide or stop us, and must not be re-entered with the same values.
    if (CGPointEqualToPoint(center, _lastNotifiedCenter) &&
        CGRectEqualToRect(self.bounds, _lastNotifiedBounds)) return;
    _lastNotifiedCenter = center;
    _lastNotifiedBounds = self.bounds;
    NSAssert([NSThread isMainThread], @"Geometry callbacks are main-thread only");
    void (^callback)(void) = _onGeometryChanged;
    if (callback) callback();
}

#pragma mark - Roaming (every target comes from centerBounds)

- (void)scheduleRoam {
    // A state hold (waving) owns the sprite state: frameTick arms the next roam.
    // A running motion arms the next roam itself, in finishMotion.
    if (_stateHoldUntil > 0. || _motionActive || ![self mayRoam]) {
        [self invalidateRoamTimer];
        return;
    }
    // activityActive replaces the old tweak global: YES while the assistant is
    // acting (lively), NO for the resident idle pet (a move every 9-15 s).
    NSTimeInterval delay = _activityActive
        ? MSPetRandomRange(kMiniSightRoamActiveLo, kMiniSightRoamActiveHi)
        : MSPetRandomRange(kMiniSightRoamIdleLo, kMiniSightRoamIdleHi);
    if (_reducedWork && !_activityActive) delay *= 1.5;
    delay += _restAfterMotion;
    _restAfterMotion = 0.;
    [self armRoamTimerWithDelay:delay];
}

- (void)armRoamTimerWithDelay:(NSTimeInterval)delay {
    if (![self mayRoam]) { [self invalidateRoamTimer]; return; }
    [self invalidateRoamTimer]; // At most one roam timer, ever.
    NSUInteger generation = _roamGeneration;
    __weak typeof(self) weakSelf = self;
    NSTimer *timer = [NSTimer timerWithTimeInterval:fmax(0.05, delay) repeats:NO
                                              block:^(NSTimer *fired) {
        MiniSightPetView *strongSelf = weakSelf;
        if (!strongSelf || strongSelf->_roamGeneration != generation || fired != strongSelf->_roamTimer) return;
        [strongSelf roamOnce];
    }];
    _roamTimer = timer;
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
}

- (void)roamOnce {
    if (![self mayRoam] || _motionActive) { [self invalidateRoamTimer]; return; }
    MSRect area = [self feasibleCenters];
    uint32_t roll = arc4random_uniform(100);
    if (roll < 52) {
        // Wander to a random feasible CENTER; y is never taken from the row above.
        MSPoint target = {MSPetRandomRange(area.x, area.x + area.w),
                          MSPetRandomRange(area.y, area.y + area.h)};
        [self startMotionTo:MSPetCGPoint(target) jump:NO rest:MSPetRandomRange(0.6, 2.2)];
    } else if (roll < 80) {
        // Hop in place. The height is capped by MSJumpHeight(), so the apex can
        // never rise above the top of the feasible range; if there is no room
        // left overhead, walk instead of "jumping" zero pixels.
        CGPoint origin = self.center;
        double height = MSJumpHeight(area, MSPetPoint(origin), kMiniSightJumpDesiredHeight);
        if (height < kMiniSightJumpMinHeight) {
            MSPoint target = {MSPetRandomRange(area.x, area.x + area.w), origin.y};
            [self startMotionTo:MSPetCGPoint(target) jump:NO rest:MSPetRandomRange(0.6, 2.2)];
        } else {
            [self startMotionTo:origin jump:YES rest:MSPetRandomRange(1.0, 2.4)];
        }
    } else if (roll < 90) {
        [self holdState:MiniSightPetStateWaving forDuration:kMiniSightWaveHold];
    } else {
        // Do nothing this beat, then wait a visibly longer stretch.
        _restAfterMotion = MSPetRandomRange(2.0, 5.0);
        [self scheduleRoam];
    }
}

- (void)holdState:(MiniSightPetState)state forDuration:(NSTimeInterval)duration {
    [self invalidateRoamTimer]; // No walking during the hold; frameTick arms the next one.
    [self setSpriteState:state];
    _stateHoldUntil = CACurrentMediaTime() + fmax(0., duration);
    [self reconcilePlayback];
}

#pragma mark - Motion (one CADisplayLink; position and sprite for the same frame)

- (void)startMotionTo:(CGPoint)target jump:(BOOL)jump rest:(NSTimeInterval)rest {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    // Without a host-provided feasible range there is nothing safe to move to.
    if (!_hasCenterBounds || ![self shouldAnimate]) return;
    if (_roamingPaused || _interactionActive) return;
    _stateHoldUntil = 0.;

    CGPoint start = [self clampedCenter:self.center];
    CGPoint end = [self clampedCenter:target];
    double height = 0.;
    if (jump) {
        height = MSJumpHeight([self feasibleCenters], MSPetPoint(start), kMiniSightJumpDesiredHeight);
        if (height < kMiniSightJumpMinHeight) height = 0.;
        else end = start; // A hop stays in place: no horizontal drift under the apex.
    }
    double distance = hypot((double)end.x - start.x, (double)end.y - start.y);
    if (distance < 1. && height <= 0.) {
        _restAfterMotion = rest;
        [self scheduleRoam];
        return;
    }

    _motionStart = MSPetPoint(start);
    _motionEnd = MSPetPoint(end);
    _jumpHeight = height;
    _motionDuration = jump ? kMiniSightJumpDuration
                           : MSClamp(distance / kMiniSightWalkSpeed,
                                     kMiniSightWalkMinDuration, kMiniSightWalkMaxDuration);
    _motionBegan = CACurrentMediaTime();
    _restAfterMotion = rest;
    _motionActive = YES;
    _activeMotionGeneration = ++_motionGeneration;

    if (height > 0.) [self setSpriteState:MiniSightPetStateJumping];
    else if (end.x > start.x) [self setSpriteState:MiniSightPetStateRunRight];
    else [self setSpriteState:MiniSightPetStateRunLeft];

    // While the link runs it also advances the atlas; one clock, never two.
    [self invalidateFrameTimer];
    [self invalidateRoamTimer];
    self.center = start; // No UIView animation: the model geometry is the truth.
    [self ensureMotionLink];
    if (!_motionActive) [self reconcilePlayback]; // Link creation failed: restart the clock.
}

- (void)ensureMotionLink {
    if (_motionLink || !_motionActive) return; // Only a live motion may hold the link.
    if (!_motionProxy) _motionProxy = [[MiniSightPetDisplayLinkProxy alloc] init];
    _motionProxy.owner = self; // Weak: the link retains the proxy, never the view.
    CADisplayLink *link = [CADisplayLink displayLinkWithTarget:_motionProxy
                                                      selector:@selector(displayTick:)];
    if (!link) { [self cancelMotion]; return; } // Never leave a motion without a clock.
    link.preferredFramesPerSecond = 60;
    [link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
    _motionLink = link;
}

- (void)motionTick:(CADisplayLink *)link {
    if (link != _motionLink) return;
    if (!_motionActive || _activeMotionGeneration != _motionGeneration) return;
    if (![self shouldAnimate] || _roamingPaused || _interactionActive) {
        // Freeze at the actual position, then let reconcile resume the sprite clock.
        [self cancelMotion];
        [self reconcilePlayback];
        return;
    }
    double t = _motionDuration > 0. ? (CACurrentMediaTime() - _motionBegan) / _motionDuration : 1.;
    if (t >= 1.) { [self finishMotion]; return; }
    if (t < 0.) t = 0.;

    MSPoint sample = MSMotionPoint(_motionStart, _motionEnd, t);
    if (_jumpHeight > 0.) sample.y -= _jumpHeight * sin(M_PI * t);
    // Clamp every intermediate sample too: a bubble resize or rotation can shrink
    // the feasible range while the pet is mid-flight.
    self.center = [self clampedCenter:MSPetCGPoint(sample)];
    if (!_motionActive) return; // A geometry callback may have cancelled the motion.
    [self advanceSpriteAtTime:CACurrentMediaTime()];
}

- (void)finishMotion {
    _motionActive = NO;
    [_motionLink invalidate];
    _motionLink = nil;
    self.center = [self clampedCenter:MSPetCGPoint(_motionEnd)];
    [self setSpriteState:MiniSightPetStateIdle];
    [self reconcilePlayback]; // Restarts the sprite clock and arms the next roam.
}

- (void)cancelMotion {
    ++_motionGeneration; // Fence any already-delivered callback before it can rearm.
    _motionActive = NO;
    _jumpHeight = 0.;
    _stateHoldUntil = 0.;
    _restAfterMotion = 0.;
    [_motionLink invalidate];
    _motionLink = nil;
    [self setSpriteState:MiniSightPetStateIdle];
}

@end
