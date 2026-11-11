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
#import "MiniSightBlip.h"
#import "MiniSightPetBehavior.h"

typedef NS_ENUM(NSInteger, MiniSightPetState) {
    MiniSightPetStateIdle = 0,
    MiniSightPetStateRunRight = 1,
    MiniSightPetStateRunLeft = 2,
    // The asset is already vertically flipped by its loader: row 3 is the
    // raised-hand response and row 5 is the seated/closed-eye sleep clip.
    MiniSightPetStateWaving = 3,
    MiniSightPetStateJumping = 4,
    MiniSightPetStateSleeping = 5,
};

static const NSInteger kMiniSightPetRows = 9;
static const NSInteger kMiniSightPetMaxCols = 8;
static const NSTimeInterval kMiniSightSpriteInterval = 1.0 / 15.0;
static const NSTimeInterval kMiniSightIdleSpriteInterval = MS_PET_IDLE_FRAME_INTERVAL;
static const NSTimeInterval kMiniSightSleepSpriteInterval = MS_PET_SLEEP_FRAME_INTERVAL;

// Roaming delays. Only the delay between actions changes; FPS never does.
static const NSTimeInterval kMiniSightRoamActiveLo = 2.4;   // activityActive == YES
static const NSTimeInterval kMiniSightRoamActiveHi = 5.0;
static const NSTimeInterval kMiniSightRoamIdleLo = 6.0;     // activityActive == NO (resident idle)
static const NSTimeInterval kMiniSightRoamIdleHi = 11.0;

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
    NSInteger _variantIndex;
    NSInteger _spriteLayout;
    CGFloat _flingSpin;
    CGFloat _flingSpinVelocity;
    CGFloat _flingSquash;
    CFTimeInterval _lastSpriteTime;
    CGRect _lastSpriteRect;
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
    MSGravityBody _gravityBody;
    BOOL _physicsMotion;
    CFTimeInterval _lastMotionTick;
    NSUInteger _motionLockReasons;
    CFTimeInterval _gravityImpulseBegan;
    CFTimeInterval _gravityImpulseDuration;
    NSUInteger _gravityGeneration;
    NSUInteger _activeGravityGeneration;
    NSUInteger _motionGeneration, _activeMotionGeneration, _roamGeneration;
    CGRect _centerBounds;
    BOOL _activityActive, _longPressEnabled, _roamingPaused, _interactionActive, _reducedWork, _soundEnabled;
    MSPetResident _resident;
    BOOL _dragging;
    UILabel *_sleepBadge;
    BOOL _reconcilingPlayback;
    BOOL _reconcileAgain;
    double _roamPace;
    NSInteger _preferredFPS;
    void (^_onGeometryChanged)(void);
    void (^_onLongPress)(void);
}
- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize;
- (BOOL)isActuallyVisible;
- (BOOL)shouldAnimate;
- (BOOL)mayRoam;
- (void)reconcilePlayback;
- (MSPetResidentContext)residentContext;
- (void)updateResidentAtTime:(CFTimeInterval)now;
- (void)applyResidentTransition:(MSPetResidentTransition)transition atTime:(CFTimeInterval)now;
- (void)clearResidentForPlayback;
- (void)updateSleepBadge;
- (BOOL)consumeAttentionAtTime:(CFTimeInterval)now;
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

double MiniSightGravityRollForDevice(double x, double y, int orientation) {
    MSPoint projected = MSGravityProject(x, y, orientation);
    return MSGravityRollFromProjected(projected.x);
}

double MiniSightGravityFilterRoll(double previous, double sample, double deltaTime) {
    return MSGravityFilter(previous, sample, deltaTime);
}

@implementation MiniSightPetView
@dynamic image;
// UIImageView's normal image paints the WHOLE atlas behind the sprite child.
// Treat image as the atlas source and keep the host backing layer empty.
@synthesize centerBounds = _centerBounds, onGeometryChanged = _onGeometryChanged;
@synthesize activityActive = _activityActive, longPressEnabled = _longPressEnabled;
@synthesize roamingPaused = _roamingPaused, interactionActive = _interactionActive;
@synthesize reducedWork = _reducedWork, onLongPress = _onLongPress;
@synthesize roamPace = _roamPace, preferredFPS = _preferredFPS;
@synthesize roamInterval = _roamInterval, gravityStrength = _gravityStrength;
@synthesize soundEnabled = _soundEnabled;

- (void)setImage:(UIImage *)image {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (!image.CGImage) return;
    _sheet = image;
    [super setImage:nil];
    self.layer.contents = nil;
    [self ensureGravityLayer];
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.contents = (__bridge id)image.CGImage;
    _gravityLayer.contentsScale = image.scale;
    _gravityLayer.contentsRect = CGRectZero;
    [CATransaction commit];
    [self applySpriteFrame];
}

- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    CGSize size = CGSizeMake(fmax(1., MSFinite(displaySize.width, 1.)),
                             fmax(1., MSFinite(displaySize.height, 1.)));
    self = [super initWithFrame:(CGRect){CGPointZero, size}];
    if (self) {
        _sheet = sprite;
        _longPressEnabled = YES; // Configuration storage; the host owns gestures.
        _roamPace = 1.;
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
        _sleepBadge = [[UILabel alloc] initWithFrame:CGRectZero];
        _sleepBadge.text = @"Z";
        _sleepBadge.textAlignment = NSTextAlignmentCenter;
        _sleepBadge.textColor = [UIColor systemBlueColor];
        _sleepBadge.font = [UIFont systemFontOfSize:15.0 weight:UIFontWeightBold];
        _sleepBadge.userInteractionEnabled = NO;
        _sleepBadge.isAccessibilityElement = NO;
        _sleepBadge.accessibilityElementsHidden = YES;
        _sleepBadge.hidden = YES;
        _sleepBadge.alpha = 0.0;
        [self addSubview:_sleepBadge];
    }
    return self;
}

- (void)layoutSubviews {
    [super layoutSubviews];
    if (!_sleepBadge) return;
    CGFloat size = MIN(20.0, MAX(13.0, self.bounds.size.width * 0.30));
    _sleepBadge.font = [UIFont systemFontOfSize:size weight:UIFontWeightBold];
    _sleepBadge.frame = CGRectMake(self.bounds.size.width - size * 0.72,
                                   -size * 0.40, size * 0.9, size * 1.15);
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
    [self clearResidentForPlayback];
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

- (void)setMotionLocked:(BOOL)locked forReason:(MiniSightPetMotionLockReason)reason {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    NSUInteger mask = (NSUInteger)reason;
    NSUInteger next = locked ? (_motionLockReasons | mask) : (_motionLockReasons & ~mask);
    if (!mask || next == _motionLockReasons) return;
    _motionLockReasons = next;
    // Approval/editor ownership wakes the visual pose but never cancels a user
    // drag or active trajectory; owner locks remain independently scoped.
    if (locked) [self wakeForInteraction];
    [self reconcilePlayback];
}

- (void)setRoamPace:(double)pace {
    pace = MSClamp(MSFinite(pace, 1.), 0., 10.);
    if (_roamPace == pace) return;
    _roamPace = pace;
    [self invalidateRoamTimer];
    [self scheduleRoam];
}

- (void)setActivityActive:(BOOL)active {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (_activityActive == active) return;
    _activityActive = active;
    // Activity boundaries reset inactivity; repeated frame/settings refreshes do not.
    [self wakeForInteraction];
    [self invalidateRoamTimer];
    [self reconcilePlayback];
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
    if (active) [self wakeForInteraction];
    if (active) [self cancelGravityImpulse];
    [self reconcilePlayback];
}

- (MSPetResidentContext)residentContext {
    return (MSPetResidentContext){
        .running = [self shouldAnimate], .activity = _activityActive,
        .interaction = _interactionActive, .paused = _roamingPaused,
        .moving = _motionActive, .holding = _stateHoldUntil > 0.,
        .locks = (unsigned)_motionLockReasons
    };
}

- (BOOL)isResidentSleeping {
    return _resident.sleeping;
}

- (void)updateSleepBadge {
    BOOL visible = _resident.sleeping && [self shouldAnimate];
    // Static decoration only: no animation, gesture recognizer or accessibility
    // element is added for the resident nap indicator.
    [_sleepBadge.layer removeAllAnimations];
    _sleepBadge.hidden = !visible;
    _sleepBadge.alpha = visible ? 1.0 : 0.0;
}

- (void)clearResidentForPlayback {
    BOOL hadSleepPose = _resident.sleeping || _resident.waking;
    MSPetResidentReset(&_resident);
    _dragging = NO;
    [self updateSleepBadge];
    if (hadSleepPose) [self setSpriteState:MiniSightPetStateIdle];
}

- (void)applyResidentTransition:(MSPetResidentTransition)transition
                        atTime:(CFTimeInterval)now {
    (void)now;
    switch (transition) {
        case MSPetResidentFellAsleep:
            if (_roamTimer) {
                MSPetResidentSaveRoam(&_resident, CACurrentMediaTime(),
                                      [_roamTimer.fireDate timeIntervalSinceNow]);
            }
            [self invalidateRoamTimer];
            [self cancelGravityImpulse];
            [self setSpriteState:MiniSightPetStateSleeping];
            break;
        case MSPetResidentWoke:
            // A wake transition never replaces a drag, held pose or motion
            // owner. Those owners cancel only the visual wake pose.
            if (_dragging || _motionActive || _stateHoldUntil > 0.) {
                MSPetResidentCancelWakePose(&_resident);
            }
            if (!_resident.waking && _state == MiniSightPetStateSleeping) {
                [self setSpriteState:MiniSightPetStateIdle];
            }
            break;
        case MSPetResidentFinishedWaking:
            if (_state == MiniSightPetStateSleeping) {
                [self setSpriteState:MiniSightPetStateIdle];
            }
            break;
        case MSPetResidentUnchanged:
            break;
    }
    [self updateSleepBadge];
}

- (void)updateResidentAtTime:(CFTimeInterval)now {
    MSPetResidentTransition transition =
        MSPetResidentAdvance(&_resident, now, [self residentContext]);
    [self applyResidentTransition:transition atTime:now];
}

- (void)setResidentSleeping:(BOOL)sleeping {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (!sleeping) {
        [self wakeForInteraction];
        return;
    }
    CFTimeInterval now = CACurrentMediaTime();
    if (MSPetResidentTrySleep(&_resident, now, [self residentContext])) {
        [self applyResidentTransition:MSPetResidentFellAsleep atTime:now];
        [self reconcilePlayback];
    }
}

- (void)wakeForInteraction {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (![self shouldAnimate]) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (MSPetResidentTouch(&_resident, now)) {
        [self applyResidentTransition:MSPetResidentWoke atTime:now];
    }
    [self reconcilePlayback];
}

- (BOOL)consumeAttentionAtTime:(CFTimeInterval)now {
    BOOL poseAvailable = !_motionActive && !_dragging && !_interactionActive &&
                         _stateHoldUntil <= 0. && _state == MiniSightPetStateIdle;
    if (!MSPetResidentTakeAttention(&_resident, now, poseAvailable)) return NO;
    [self holdState:MiniSightPetStateWaving forDuration:0.75];
    return YES;
}

- (void)requestAttentionResponse {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (![self shouldAnimate]) return;
    [self wakeForInteraction];
    CFTimeInterval now = CACurrentMediaTime();
    MSPetResidentRequestAttention(&_resident, now);
    [self consumeAttentionAtTime:now];
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
    return [self shouldAnimate] && _hasCenterBounds && !_resident.sleeping && !_resident.waking &&
           MSGravityMotionAllowed(_wantsPlaying, _suspended, [self isActuallyVisible],
                                  _roamingPaused, _interactionActive, (unsigned)_motionLockReasons) &&
           (area.w > 0. || area.h > 0.);
}

- (void)reconcilePlayback {
    if (![self shouldAnimate]) {
        [self clearResidentForPlayback];
        [self invalidateFrameTimer];
        [self invalidateRoamTimer];
        [self cancelMotion];
        [self cancelGravityImpulse];
        return;
    }
    CFTimeInterval now = CACurrentMediaTime();
    [self updateResidentAtTime:now];
    if (![self mayRoam]) {
        [self invalidateRoamTimer];
        // Do not rewrite a drag or active motion to idle while an owner holds it.
        if (_motionActive || _motionLink || _physicsMotion) [self cancelMotion];
        if (_gravityImpulseDuration > 0. || _gravityLink) [self cancelGravityImpulse];
    }
    if (!_motionActive) [self ensureFrameTimer];
    [self consumeAttentionAtTime:now];
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
    }
    [self updateResidentAtTime:now];
    [self consumeAttentionAtTime:now];
    if (!_roamTimer && !_motionActive && _stateHoldUntil <= 0.) [self scheduleRoam];
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
    MSPetResidentResetBlink(&_resident);
    _lastSpriteTime = CACurrentMediaTime();
    [self applySpriteFrame];
}

- (NSTimeInterval)currentSpriteInterval {
    // Idle clip has only six poses; at 15 fps it blinked roughly once a second.
    // Walking/acting keeps the snappy 15 fps.
    switch (_state) {
        case MiniSightPetStateIdle: return kMiniSightIdleSpriteInterval;
        case MiniSightPetStateSleeping: return kMiniSightSleepSpriteInterval;
        case MiniSightPetStateWaving: return 1.0 / 7.0;
        case MiniSightPetStateJumping: return 1.0 / 11.0;
        default: return kMiniSightSpriteInterval;
    }
}

- (void)advanceSpriteAtTime:(CFTimeInterval)now {
    if (_state == MiniSightPetStateSleeping || _state == MiniSightPetStateIdle) {
        NSInteger next;
        if (_state == MiniSightPetStateSleeping) {
            next = _resident.waking ? MSPetResidentWakeColumn(now - _resident.wakeBegan)
                                    : MSPetResidentSleepColumn(now - _resident.sleepBegan);
        } else {
            BOOL needsDelay = _resident.nextBlinkAt <= 0. ||
                (_resident.blinking && now - _resident.blinkBegan >= 6. * kMiniSightIdleSpriteInterval);
            next = MSPetResidentIdleColumn(&_resident, now, needsDelay ? MSPetRandomUnit() : 0.5);
        }
        if (next != _column) { _column = next; [self applySpriteFrame]; }
        return;
    }
    NSTimeInterval interval = [self currentSpriteInterval];
    double elapsed = fmax(0., now - _lastSpriteTime);
    if (elapsed < interval) return;
    double steps = floor(elapsed / interval);
    NSInteger count = [self frameCountForRow:_state];
    _lastSpriteTime = now - fmod(elapsed, interval);
    NSInteger next = (_column + (NSInteger)fmod(steps, (double)count)) % count;
    if (next == _column) return;
    _column = next;
    [self applySpriteFrame];
}

- (void)setVariantIndex:(NSInteger)variantIndex {
    _variantIndex = MIN(71, MAX(0, variantIndex));
    [self applySpriteFrame];
}
- (NSInteger)variantIndex { return _variantIndex; }
- (void)setSpriteLayout:(NSInteger)spriteLayout {
    _spriteLayout = MIN(4, MAX(0, spriteLayout));
    [self applySpriteFrame];
}
- (NSInteger)spriteLayout { return _spriteLayout; }

- (void)applySpriteFrame {
    if (!_sheet.CGImage || !_gravityLayer) return;
    // 0 is a 72-pet pack (each outer cell has its own 8x9 frames).
    // 3 is ONE character's 8x9 sheet: row = action, column = frame.
    // 4 is a static contact sheet, one outer cell per pose.
    const NSInteger packCols = kMiniSightPetMaxCols, packRows = kMiniSightPetRows;
    const NSInteger innerCols = 8, innerRows = 9;
    NSInteger v = MIN(71, MAX(0, _variantIndex));
    // Fallback: a 12:13 sheet is always one character's animation even if
    // the startup path failed to read pet.json (layout 0/1).
    NSInteger effectiveLayout = _spriteLayout;
    CGFloat sw = (CGFloat)CGImageGetWidth(_sheet.CGImage), sh = (CGFloat)CGImageGetHeight(_sheet.CGImage);
    if (effectiveLayout <= 1 && sw > 0 && sh > 0 && fabs(sw / sh - 768.0 / 936.0) < 0.03) effectiveLayout = 3;
    CGRect rect;
    if (effectiveLayout == 1) {
        rect = CGRectMake(0, 0, 1, 1);
    } else if (effectiveLayout == 4 || effectiveLayout == 2) {
        rect = CGRectMake((CGFloat)(v % packCols) / packCols,
                          (CGFloat)(v / packCols) / packRows,
                          1.0 / packCols, 1.0 / packRows);
    } else if (effectiveLayout == 3) {
        NSInteger maxCol = [self frameCountForRow:_state];
        NSInteger col = MIN(MAX(0, _column), MAX(0, maxCol - 1));
        rect = CGRectMake((CGFloat)col / packCols,
                          (CGFloat)_state / packRows,
                          1.0 / packCols, 1.0 / packRows);
    } else {
        NSInteger maxCol = [self frameCountForRow:_state];
        NSInteger col = MIN(MAX(0, _column), MAX(0, maxCol - 1));
        NSInteger totalCols = packCols * innerCols, totalRows = packRows * innerRows;
        rect = CGRectMake((CGFloat)((v % packCols) * innerCols + col) / totalCols,
                          (CGFloat)((v / packCols) * innerRows + _state) / totalRows,
                          1.0 / totalCols, 1.0 / totalRows);
    }
    // Crop the frame out of the sheet instead of relying on contentsRect:
    // a missed/zeroed contentsRect used to paint the whole atlas on respring.
    CGFloat w = (CGFloat)CGImageGetWidth(_sheet.CGImage), h = (CGFloat)CGImageGetHeight(_sheet.CGImage);
    CGRect pixels = CGRectMake(floor(rect.origin.x * w), floor(rect.origin.y * h),
                               MAX(1., floor(rect.size.width * w)), MAX(1., floor(rect.size.height * h)));
    if (CGRectEqualToRect(pixels, _lastSpriteRect)) return;
    _lastSpriteRect = pixels;
    CGImageRef cell = CGImageCreateWithImageInRect(_sheet.CGImage, pixels);
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.contentsRect = CGRectMake(0, 0, 1, 1);
    _gravityLayer.contents = (__bridge id)cell;
    [CATransaction commit];
    if (cell) CGImageRelease(cell);
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
    CGFloat strength = _gravityStrength > 0 ? _gravityStrength : 1.;
    return MSGravityAngle(_gravityRoll * strength, _gravityImpulseAngle * strength, progress);
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
        if (_physicsMotion) [self cancelMotion];
        [self cancelGravityImpulse];
        [self reconcilePlayback];
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
    if (_interactionActive || _roamingPaused || _motionLockReasons) return; // editing/approval freezes sway too
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

- (void)triggerGravityFlingWithDirection:(CGFloat)direction strength:(CGFloat)strength {
    if (!_gravityEnabled || ![self mayRoam]) return;
    BOOL alreadyFlying = _physicsMotion;
    if (!alreadyFlying) [self cancelMotion];
    MSPoint velocity = MSGravityLaunchVelocity(direction, strength);
    MSGravityBodyLaunch(&_gravityBody, [self feasibleCenters], MSPetPoint(self.center), velocity);
    _physicsMotion = _gravityBody.active;
    _motionActive = _physicsMotion;
    _activeMotionGeneration = ++_motionGeneration;
    _lastMotionTick = CACurrentMediaTime();
    _restAfterMotion = .45;
    _flingSpin = 0.;
    _flingSpinVelocity = (direction >= 0 ? 1. : -1.) * (2.0 + 3.4 * MAX(.2, strength));
    _flingSquash = 0.;
    if (!alreadyFlying) [self setSpriteState:MiniSightPetStateJumping];
    [self invalidateFrameTimer];
    [self invalidateRoamTimer];
    [self ensureMotionLink];
    if (!_motionActive) [self reconcilePlayback];
}

- (void)triggerGravityImpulseWithDirection:(CGFloat)direction strength:(CGFloat)strength {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    if (!_gravityEnabled || ![self mayRoam]) return;
    direction = MSPetClampUnit(direction);
    strength = MIN(1.0, MAX(0.0, isfinite(strength) ? strength : 0.0));
    if (fabs(direction) < 0.01 || strength < 0.05) return;
    _gravityImpulseAngle = direction * strength * kMiniSightGravityImpulseAngle;
    _gravityImpulseBegan = CACurrentMediaTime();
    _gravityImpulseDuration = kMiniSightGravityImpulseDuration;
    _activeGravityGeneration = ++_gravityGeneration;
    [self triggerGravityFlingWithDirection:direction strength:strength];
    [self ensureGravityLink];
    [self applyGravityTransformAtTime:_gravityImpulseBegan];
}

- (void)gravityTick:(CADisplayLink *)link {
    if (link != _gravityLink) return;
    if (!_gravityEnabled || ![self mayRoam]) {
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
    NSTimeInterval base = _activityActive
        ? MSPetRandomRange(kMiniSightRoamActiveLo, kMiniSightRoamActiveHi)
        : MSPetRandomRange(kMiniSightRoamIdleLo, kMiniSightRoamIdleHi);
    NSTimeInterval delay = MSPetRoamDelay(base, _roamPace, _roamInterval,
                                          _reducedWork, _activityActive,
                                          MSPetRandomUnit());
    if (_roamPace == 0) { [self invalidateRoamTimer]; return; }
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
        // Move to a nearby perch so the pet reads as walking across the
        // desktop, not teleporting to an arbitrary screen point.
        MSPoint target = MSPetNearbyTarget(area, MSPetPoint(self.center),
                                           MSPetRandomUnit(), MSPetRandomUnit(), false);
        [self startMotionTo:MSPetCGPoint(target) jump:NO rest:MSPetRandomRange(0.35, 1.1)];
    } else if (roll < 80) {
        // Hop to the next nearby lane, with the arc capped by the safe range.
        CGPoint origin = self.center;
        MSPoint target = MSPetNearbyTarget(area, MSPetPoint(origin),
                                           MSPetRandomUnit(), MSPetRandomUnit(), true);
        double height = MSPetSafeJumpHeight(area, MSPetPoint(origin), target,
                                            kMiniSightJumpDesiredHeight);
        if (height < kMiniSightJumpMinHeight) {
            [self startMotionTo:MSPetCGPoint(target) jump:NO rest:MSPetRandomRange(0.35, 1.1)];
        } else {
            [self startMotionTo:MSPetCGPoint(target) jump:YES rest:MSPetRandomRange(0.65, 1.5)];
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

- (void)beginDraggingWithDirection:(CGFloat)direction {
    _interactionActive = YES;
    _stateHoldUntil = DBL_MAX;
    [self invalidateRoamTimer];
    if (direction >= 0) [self setSpriteState:MiniSightPetStateRunRight];
    else [self setSpriteState:MiniSightPetStateRunLeft];
}

- (void)endDragging {
    _interactionActive = NO;
    _stateHoldUntil = CACurrentMediaTime() + 0.35;
    [self setSpriteState:MiniSightPetStateIdle];
    _restAfterMotion = 0.35;
    [self scheduleRoam];
}

- (void)startMotionTo:(CGPoint)target jump:(BOOL)jump rest:(NSTimeInterval)rest {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    // Without a host-provided feasible range there is nothing safe to move to.
    if (!_hasCenterBounds || ![self shouldAnimate]) return;
    if (_roamingPaused || _interactionActive || _motionLockReasons) return;
    _physicsMotion = NO;
    MSGravityBodyCancel(&_gravityBody);
    _stateHoldUntil = 0.;

    CGPoint start = [self clampedCenter:self.center];
    CGPoint end = [self clampedCenter:target];
    double height = 0.;
    if (jump) {
        height = MSPetSafeJumpHeight([self feasibleCenters], MSPetPoint(start), MSPetPoint(end), kMiniSightJumpDesiredHeight);
        if (height < kMiniSightJumpMinHeight) height = 0.;
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

- (void)applyPreferredFPS {
    NSInteger fps = _preferredFPS;
    if (fps <= 0) return;
    if (@available(iOS 15.0, *)) {
        _motionLink.preferredFrameRateRange = CAFrameRateRangeMake(fps, fps, fps);
        _gravityLink.preferredFrameRateRange = CAFrameRateRangeMake(fps, fps, fps);
    } else {
        _motionLink.preferredFramesPerSecond = fps;
        _gravityLink.preferredFramesPerSecond = fps;
    }
}

- (void)setPreferredFPS:(NSInteger)fps {
    _preferredFPS = fps;
    [self applyPreferredFPS];
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
    if (![self shouldAnimate] || _roamingPaused || _interactionActive || _motionLockReasons) {
        // Freeze at the actual position, then let reconcile resume the sprite clock.
        [self cancelMotion];
        [self reconcilePlayback];
        return;
    }
    CFTimeInterval now = CACurrentMediaTime();
    NSUInteger generation = _activeMotionGeneration;
    if (_physicsMotion) {
        uint64_t token = _gravityBody.activeGeneration;
        double elapsed = now - _lastMotionTick;
        _lastMotionTick = now;
        unsigned hits = MSGravityBodyStep(&_gravityBody, [self feasibleCenters], _gravityRoll, elapsed, token);
        self.center = MSPetCGPoint(_gravityBody.position);
        // Geometry callbacks may hide, replace, resize, or lock this pet.
        if (!_motionActive || generation != _motionGeneration || !_physicsMotion) return;
        double spinDT = MIN(MAX(elapsed, 0.), .1);
        _flingSpin += _flingSpinVelocity * spinDT;
        _flingSpinVelocity *= exp(-1.7 * spinDT);
        if (hits & MSGravityHitFloor) {
            _flingSpinVelocity *= -0.62;
            _flingSquash = 1.0;
        } else {
            _flingSquash *= exp(-9.0 * spinDT);
        }
        CGFloat sx = 1.0 + 0.10 * _flingSquash;
        CGFloat sy = 1.0 - 0.16 * _flingSquash;
        self.transform = CGAffineTransformConcat(CGAffineTransformMakeRotation(_flingSpin),
                                                 CGAffineTransformMakeScale(sx, sy));
        [self applyGravityTransformAtTime:now];
        if (!_motionActive || generation != _motionGeneration) return;
        if (!_gravityBody.active) { [self finishMotion]; return; }
        [self advanceSpriteAtTime:now];
        return;
    }
    double t = _motionDuration > 0. ? (now - _motionBegan) / _motionDuration : 1.;
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
    NSUInteger generation = _motionGeneration;
    CGPoint end = _physicsMotion ? MSPetCGPoint(_gravityBody.position) : MSPetCGPoint(_motionEnd);
    self.center = [self clampedCenter:end];
    if (!_motionActive || generation != _motionGeneration) return;
    _motionActive = NO;
    _physicsMotion = NO;
    _activeMotionGeneration = 0;
    _flingSpin = 0.; _flingSpinVelocity = 0.; _flingSquash = 0.;
    self.transform = CGAffineTransformIdentity;
    MSGravityBodyCancel(&_gravityBody);
    [_motionLink invalidate];
    _motionLink = nil;
    if (_state == MiniSightPetStateSleeping || _state == MiniSightPetStateWaving) {
        _state = MiniSightPetStateIdle;
        _column = 0;
        _lastSpriteTime = CACurrentMediaTime();
        [self applySpriteFrame];
    }
    [self reconcilePlayback]; // Restarts sprite clock; never invents a rebound target.
}

- (void)cancelMotion {
    ++_motionGeneration; // Fence any already-delivered callback before it can rearm.
    _motionActive = NO;
    _physicsMotion = NO;
    _activeMotionGeneration = 0;
    _flingSpin = 0.; _flingSpinVelocity = 0.; _flingSquash = 0.;
    self.transform = CGAffineTransformIdentity;
    _lastMotionTick = 0.;
    MSGravityBodyCancel(&_gravityBody);
    _jumpHeight = 0.;
    _stateHoldUntil = 0.;
    _restAfterMotion = 0.;
    [_motionLink invalidate];
    _motionLink = nil;
    [self setSpriteState:MiniSightPetStateIdle];
}

@end
