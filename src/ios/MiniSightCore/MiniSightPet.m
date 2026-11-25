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
#import "MiniSightPetMusicMotion.h"
#import "MiniSightPetRhythmPolicy.h"
#import "MiniSightPetDailyPolicy.h"
#import "MiniSightPetEffects.h"
#import "MiniSightLiveliness.h"
#import "MiniSightLog.h"

typedef NS_ENUM(NSInteger, MiniSightPetState) {
    MiniSightPetStateIdle = 0,
    MiniSightPetStateRunRight = 1,
    MiniSightPetStateRunLeft = 2,
    // The asset is already vertically flipped by its loader: row 3 is the
    // raised-hand response and row 5 is the seated/closed-eye sleep clip.
    MiniSightPetStateWaving = 3,
    MiniSightPetStateJumping = 4,
    MiniSightPetStateSleeping = 5,
    MiniSightPetStateWaking = 6,
    MiniSightPetStateDragging = 7,
    MiniSightPetStateMusic = 8,
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
    MiniSightPetEffects *_effects;
    BOOL _lyricsSuppressed;
    BOOL _musicMotion; // Only an automatic music route, never a drag/fling.
    unsigned _musicMotionStep;
    BOOL _rhythmFollowing, _rhythmStarting;
    uint64_t _rhythmSessionToken;
    MSPetRhythmPolicy _rhythmPolicy;
    MSPetRhythmAction _rhythmAction;
    MiniSightPetState _state;
    NSInteger _column;
    NSInteger _variantIndex;
    NSInteger _spriteLayout;
    CGFloat _flingSpin;
    CGFloat _flingSpinVelocity;
    CGFloat _flingSquash;
    CFTimeInterval _poseBegan;
    CFTimeInterval _lastSpriteTime;
    CGRect _lastSpriteRect;
    BOOL _wantsPlaying, _suspended, _hasCenterBounds;
    CFTimeInterval _dailyActionDue, _dailyActionHoldUntil, _dailyFallbackBegan;
    BOOL _dailyActionsEnabled, _dailyFirstFramePending;
    CFTimeInterval _dailyPausedRemaining, _dailyDiagAt, _musicDiagAt;
    NSUInteger _dailyBlockers, _musicInputMode;
    MSPetDailyFallback _dailyFallback;
    unsigned _lastDailyFallback;
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
    NSInteger _landingRecoveryStage;
    CFTimeInterval _landingRecoveryBegan;
    NSUInteger _loggedFloorGeneration;
    double _roamPace;
    NSInteger _preferredFPS;
    void (^_onGeometryChanged)(void);
    void (^_onLongPress)(void);
}
- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize;
- (BOOL)isActuallyVisible;
- (BOOL)shouldAnimate;
- (BOOL)mayRoam;
- (BOOL)mayPerformMusicMotion;
- (BOOL)measuredMusicInputAt:(CFTimeInterval)now;
- (void)checkRhythmAtTime:(CFTimeInterval)now;
- (void)reconcilePlayback;
- (void)reconcilePlaybackOnce;
- (MSPetResidentContext)residentContext;
- (void)updateResidentAtTime:(CFTimeInterval)now;
- (void)applyResidentTransition:(MSPetResidentTransition)transition atTime:(CFTimeInterval)now;
- (void)clearResidentForPlayback;
- (void)updateSleepBadge;
- (void)beginLandingRecoveryWithImpact:(CGFloat)impact;
- (void)clearLandingRecovery;
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
- (void)cancelDailyAction;
- (void)scheduleDailyActionFrom:(CFTimeInterval)now;
- (void)tryDailyActionAt:(CFTimeInterval)now;
- (void)startMotionTo:(CGPoint)target jump:(BOOL)jump rest:(NSTimeInterval)rest;
- (void)ensureMotionLink;
- (void)finishMotion;
- (void)beginLandingRecoveryWithImpact:(CGFloat)impact;
- (void)clearLandingRecovery;
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
    // Reassigning the same source must also repair a cleared/repainted layer.
    if (!image.CGImage) return;
    _sheet = image;
    _lastSpriteRect = CGRectNull;
    [super setImage:nil];
    self.layer.contents = nil;
    [self ensureGravityLayer];
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.contentsScale = image.scale;
    _gravityLayer.contentsRect = CGRectMake(0, 0, 1, 1);
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
        _lastSpriteRect = CGRectNull;
        [super setImage:nil];
        _longPressEnabled = YES; // Configuration storage; the host owns gestures.
        _roamPace = 1.;
        _dailyActionsEnabled = YES;
        _rhythmFollowing = YES; // Measured music only; ordinary life stays independent.
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
        _effects.rhythmFollowing = YES;
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
    [_effects invalidate];
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
    [self cancelDailyAction];
    [_effects setRunning:NO];
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
    if (locked) [self clearLandingRecovery];
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
    if (active) [self clearLandingRecovery];
    // Activity boundaries reset inactivity; repeated frame/settings refreshes do not;
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
        .running = [self shouldAnimate], .activity = _activityActive || _effects.musicPlaying,
        .interaction = _interactionActive, .paused = _roamingPaused,
        .moving = _motionActive, .holding = _landingRecoveryStage != 0 || _stateHoldUntil > 0. || _effects.autonomyHeld,
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
    if (_effects.autonomyHeld) return NO;
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

- (BOOL)measuredMusicInputAt:(CFTimeInterval)now {
    return _rhythmFollowing && _effects.musicPlaying && MSPetRhythmFresh(&_rhythmPolicy, now);
}

- (BOOL)mayPerformMusicMotion {
    // Follow the user's roam OFF/pace settings; assistant activity, chat and
    // approval own attention. Music never takes over gesture/physics ownership.
    return _effects.musicPlaying && [self mayRoam] && _roamPace > 0. &&
        !_activityActive && !_lyricsSuppressed && !_effects.presentationBlocked &&
        !UIAccessibilityIsReduceMotionEnabled();
}

- (void)reconcilePlayback {
    if (_reconcilingPlayback) { _reconcileAgain = YES; return; }
    _reconcilingPlayback = YES;
    @try {
        // Nested geometry notifications may request another pass, never recurse.
        for (NSUInteger pass = 0; pass < 2; ++pass) {
            _reconcileAgain = NO;
            [self reconcilePlaybackOnce];
            if (!_reconcileAgain) break;
        }
    } @finally { _reconcilingPlayback = NO; }
}
- (void)reconcilePlaybackOnce {
    [self checkRhythmAtTime:CACurrentMediaTime()];
    _effects.busy = _lyricsSuppressed || _motionLockReasons != 0 || _activityActive;
    [_effects setRunning:[self shouldAnimate]];
    if (![self shouldAnimate]) {
        [self clearResidentForPlayback];
        [self cancelDailyAction];
        [self invalidateFrameTimer];
        [self invalidateRoamTimer];
        [self cancelMotion];
        [self cancelGravityImpulse];
        return;
    }
    CFTimeInterval now = CACurrentMediaTime();
    [self updateResidentAtTime:now];
    if (_dailyActionHoldUntil > 0.) [self tryDailyActionAt:now];
    if (![self mayRoam]) {
        [self invalidateRoamTimer];
        // Do not rewrite a drag or active motion to idle while an owner holds it.
        if (_motionActive || _motionLink || _physicsMotion) [self cancelMotion];
        if (_gravityImpulseDuration > 0. || _gravityLink) [self cancelGravityImpulse];
    }
    if (((!_rhythmFollowing && _effects.musicPlaying) || _musicMotion) && ![self mayPerformMusicMotion]) {
        [self invalidateRoamTimer];
        if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];
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
    [self checkRhythmAtTime:now];
    if (((!_rhythmFollowing && _effects.musicPlaying) || _musicMotion) && ![self mayPerformMusicMotion]) {
        [self invalidateRoamTimer];
        if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];
    }
    if (_landingRecoveryStage && (_effects.presentationBlocked || _activityActive || _lyricsSuppressed || _motionLockReasons || _roamingPaused ||
        _interactionActive || UIAccessibilityIsReduceMotionEnabled())) [self clearLandingRecovery];
    if (_landingRecoveryStage) {
        NSInteger stage = MSPetLandingStageAt(now - _landingRecoveryBegan);
        if (!stage && _effects.landingRecoveryHeld) stage = 4;
        if (!stage) [self clearLandingRecovery];
        else if (stage != _landingRecoveryStage) {
            _landingRecoveryStage = stage;
            MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"value": @(stage),
                @"reason": stage == 4 ? @"landing_stand" : @"landing_settle"});
            [_effects setLandingRecoveryStage:stage];
        }
    }
    if (_stateHoldUntil > 0. && now >= _stateHoldUntil && !_landingRecoveryStage) {
        _stateHoldUntil = 0.;
        [self setSpriteState:MiniSightPetStateIdle];
    }
    [self updateResidentAtTime:now];
    [self consumeAttentionAtTime:now];
    [self tryDailyActionAt:now];
    if (!_roamTimer && !_motionActive && _stateHoldUntil <= 0.) [self scheduleRoam];
    [self advanceSpriteAtTime:now];
}

- (NSInteger)frameCountForRow:(NSInteger)row {
    static const NSInteger counts[9] = {6, 8, 8, 4, 5, 8, 6, 6, 6};
    return counts[MSPetPoseAtlasRow((int)row)];
}

- (void)setSpriteState:(MiniSightPetState)state {
    [_effects setLegacyState:state waking:_resident.waking];
    if (_state == state) return;
    _state = state;
    _poseBegan = CACurrentMediaTime();
    _column = 0;
    MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"value": @((NSInteger)state), @"reason": @"pose_selected"});
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
        case MiniSightPetStateMusic: return .82 / 6.;
        default: return kMiniSightSpriteInterval;
    }
}

- (void)advanceSpriteAtTime:(CFTimeInterval)now {
    BOOL poseFree = !_motionActive && !_dragging && !_landingRecoveryStage && _stateHoldUntil <= 0. &&
        !_resident.sleeping && !_resident.waking && !_activityActive && !_motionLockReasons && !_lyricsSuppressed &&
        !_roamingPaused && !_interactionActive && !_effects.presentationBlocked && !_effects.autonomyHeld && !UIAccessibilityIsReduceMotionEnabled();
    if (poseFree && _effects.musicPlaying && (!_rhythmFollowing || [self measuredMusicInputAt:now]) && _state == MiniSightPetStateIdle)
        [self setSpriteState:MiniSightPetStateMusic];
    else if (_state == MiniSightPetStateMusic && (!_effects.musicPlaying || (_rhythmFollowing && ![self measuredMusicInputAt:now]) || !poseFree))
        [self setSpriteState:MiniSightPetStateIdle];
    [_effects setLegacyState:_state waking:_resident.waking];
    if (_effects.hasActions) return;
    if (_landingRecoveryStage) {
        if (_state != MiniSightPetStateIdle) [self setSpriteState:MiniSightPetStateIdle];
        _column = MSPetLandingColumn((int)_landingRecoveryStage, now - _landingRecoveryBegan);
        [self applySpriteFrame]; return;
    }
    if (_dailyFallback && now < _dailyActionHoldUntil && !_motionActive && !_dragging &&
        _stateHoldUntil <= 0. && !_landingRecoveryStage) {
        _column = MSPetDailyFallbackColumn(_dailyFallback, now - _dailyFallbackBegan);
        [self applySpriteFrame]; return;
    }
    if (_dragging || _state == MiniSightPetStateMusic) {
        if (_state == MiniSightPetStateDragging) _column = MSPetPoseColumnAt((int)_state, now - _poseBegan);
        [self applySpriteFrame]; return;
    }
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
    if (!_sheet.CGImage || !_gravityLayer || _effects.hasActions) return;
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
    // Import validates actionPack + singleImage/layoutVersion 1 as a poster.
    // Its aspect ratio may match an atlas; never apply the legacy guess to it.
    // A stale manifest must NOT turn an explicit sheet/pack into a whole image.
    BOOL actionPoster = effectiveLayout == 1 && _effects.actionManifestPath.length > 0;
    if (!actionPoster && effectiveLayout <= 1 && sw > 0 && sh > 0 && fabs(sw / sh - 768.0 / 936.0) < 0.03) effectiveLayout = 3;
    double position = _state == MiniSightPetStateMusic && !_rhythmFollowing ? _effects.musicPosition : 0.;
    NSInteger row = MSPetPoseAtlasRowAt((int)_state, position);
    NSInteger column = _state == MiniSightPetStateMusic ? MSPetPoseColumnAt((int)_state, position) : _column;
    CGRect rect;
    if (effectiveLayout == 1) {
        rect = CGRectMake(0, 0, 1, 1);
    } else if (effectiveLayout == 4 || effectiveLayout == 2) {
        rect = CGRectMake((CGFloat)(v % packCols) / packCols,
                          (CGFloat)(v / packCols) / packRows,
                          1.0 / packCols, 1.0 / packRows);
    } else if (effectiveLayout == 3) {
        NSInteger maxCol = [self frameCountForRow:row];
        NSInteger col = MIN(MAX(0, column), MAX(0, maxCol - 1));
        rect = CGRectMake((CGFloat)col / packCols,
                          (CGFloat)row / packRows,
                          1.0 / packCols, 1.0 / packRows);
    } else {
        NSInteger maxCol = [self frameCountForRow:row];
        NSInteger col = MIN(MAX(0, column), MAX(0, maxCol - 1));
        NSInteger totalCols = packCols * innerCols, totalRows = packRows * innerRows;
        rect = CGRectMake((CGFloat)((v % packCols) * innerCols + col) / totalCols,
                          (CGFloat)((v / packCols) * innerRows + row) / totalRows,
                          1.0 / totalCols, 1.0 / totalRows);
    }
    // Crop the frame out of the sheet instead of relying on contentsRect:
    // a missed/zeroed contentsRect used to paint the whole atlas on respring.
    CGFloat w = (CGFloat)CGImageGetWidth(_sheet.CGImage), h = (CGFloat)CGImageGetHeight(_sheet.CGImage);
    CGRect pixels = CGRectMake(floor(rect.origin.x * w), floor(rect.origin.y * h),
                               MAX(1., floor(rect.size.width * w)), MAX(1., floor(rect.size.height * h)));
    if (CGRectEqualToRect(pixels, _lastSpriteRect) && _gravityLayer.contents) return;
    CGImageRef cell = CGImageCreateWithImageInRect(_sheet.CGImage, pixels);
    _lastSpriteRect = cell ? pixels : CGRectNull; // A failed crop must be retryable.
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    _gravityLayer.contentsRect = CGRectMake(0, 0, 1, 1);
    _gravityLayer.contents = (__bridge id)cell;
    [CATransaction commit];
    if (cell && _dailyFirstFramePending && _dailyFallback != MSPetDailyNone) {
        _dailyFirstFramePending = NO;
        MSDiagEvent(@"pet", @"daily_action", @"ok", @{@"source": @"app", @"reason": @"daily_first_frame",
            @"action_id": @((unsigned)_dailyFallback), @"frame_count": @([self frameCountForRow:row]), @"frame_index": @(column)});
    }
    if (cell) CGImageRelease(cell);
}

- (void)restorePosterFrame {
    NSAssert([NSThread isMainThread], @"Pet UI must be used on the main thread");
    [super setImage:nil];
    self.layer.contents = nil;
    _lastSpriteRect = CGRectNull;
    [self applySpriteFrame];
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
    // Only applySpriteFrame may publish the poster, after physical cropping.
    layer.contents = nil;
    [self.layer addSublayer:layer];
    _gravityLayer = layer;
    _effects = [[MiniSightPetEffects alloc] initWithPet:self layer:layer];
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
    CGPoint offset = _effects.visualOffset;
    return CGPointMake(self.center.x + offset.x, self.center.y + offset.y);
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
    [_effects setTilt:angle sway:sway];
    // The effects driver owns one damped sprite transform; host and text stay upright.
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
    if (!_gravityEnabled || ![self shouldAnimate] || _roamingPaused || _interactionActive || _motionLockReasons || _physicsMotion) return;
    [self wakeForInteraction];
    MSPetResidentCancelWakePose(&_resident);
    direction = MSPetClampUnit(direction);
    strength = MIN(1.0, MAX(0.0, isfinite(strength) ? strength : 0.0));
    if (fabs(direction) < 0.01 || strength < 0.05) return;
    _gravityImpulseAngle = direction * strength * kMiniSightGravityImpulseAngle;
    _gravityImpulseBegan = CACurrentMediaTime();
    _gravityImpulseDuration = kMiniSightGravityImpulseDuration;
    _activeGravityGeneration = ++_gravityGeneration;
    [_effects shakeDirection:direction strength:strength];
    if (strength >= .55) [self triggerGravityFlingWithDirection:direction strength:strength];
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
    [self clearRhythm];
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
    if (!CGRectEqualToRect(self.bounds, bounds)) [self clearRhythm];
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

- (BOOL)dailyActionsEnabled { return _dailyActionsEnabled; }
- (void)setDailyActionsEnabled:(BOOL)enabled {
    NSAssert(NSThread.isMainThread, @"Daily actions are main-thread owned");
    if (_dailyActionsEnabled == enabled) return;
    _dailyActionsEnabled = enabled;
    if (!enabled) { [self cancelDailyAction]; _dailyPausedRemaining = 0.; }
    // No dedicated daily timer exists. The existing sprite clock may continue
    // for manual/resident animation, but cannot rearm daily work while OFF.
}
- (void)cancelDailyAction {
    BOOL restore = _dailyFallback != MSPetDailyNone &&
        _state == MSPetDailyFallbackPose(_dailyFallback) && !_motionActive && !_physicsMotion &&
        !_dragging && !_landingRecoveryStage && _stateHoldUntil <= 0. &&
        !_resident.sleeping && !_resident.waking;
    _dailyActionDue = 0.; _dailyActionHoldUntil = 0.; _dailyFallbackBegan = 0.; _dailyPausedRemaining = 0.;
    _dailyFallback = MSPetDailyNone; _dailyFirstFramePending = NO;
    [_effects cancelDailyAction];
    if (restore) [self setSpriteState:MiniSightPetStateIdle];
}
- (void)scheduleDailyActionFrom:(CFTimeInterval)now {
    if (_dailyActionsEnabled && _dailyActionDue <= 0.) {
        _dailyActionDue = now + (_dailyPausedRemaining > 0. ? _dailyPausedRemaining : MSPetRandomRange(8.0, 14.0));
        _dailyPausedRemaining = 0.;
    }
}
- (void)tryDailyActionAt:(CFTimeInterval)now {
    // Bits describe independent owners, not musical metadata. Pausing preserves
    // remaining eligible wait, never a backlog of actions; hard gates retire art now.
    NSUInteger blockers = (!_dailyActionsEnabled ? 1u : 0u) | (![self shouldAnimate] ? 2u : 0u) |
        ((_resident.sleeping || _resident.waking) ? 4u : 0u) | (_landingRecoveryStage ? 8u : 0u) |
        (_motionActive ? 16u : 0u) | (_physicsMotion ? 32u : 0u) | (_dragging ? 64u : 0u) |
        ((_activityActive || _lyricsSuppressed || _motionLockReasons || _interactionActive || _effects.presentationBlocked) ? 128u : 0u) |
        ((_effects.musicPlaying && (!_rhythmFollowing || [self measuredMusicInputAt:now])) ? 256u : 0u) |
        ((_stateHoldUntil > now || (_effects.autonomyHeld && _dailyActionHoldUntil <= 0.)) ? 512u : 0u) |
        (UIAccessibilityIsReduceMotionEnabled() ? 1024u : 0u);
    if (blockers != _dailyBlockers || now - _dailyDiagAt >= 30.) {
        _dailyBlockers = blockers; _dailyDiagAt = now;
        MSDiagEvent(@"pet", @"daily_action", @"ok", @{@"source": @"app", @"reason": @"daily_gate",
            @"blockers": @(blockers), @"due_ms": @((NSInteger)lrint(fmax(0., _dailyActionDue - now) * 1000.)),
            @"action_id": @((unsigned)_dailyFallback), @"enabled": @(_dailyActionsEnabled)});
    }
    if (blockers) {
        double remaining = _dailyActionDue > 0. ? fmax(.05, _dailyActionDue - now) : _dailyPausedRemaining;
        if (_dailyActionHoldUntil > 0.) remaining = MSPetRandomRange(8.0, 14.0);
        [self cancelDailyAction];
        _dailyPausedRemaining = (blockers & (1u | 2u | 4u | 1024u)) ? 0. : remaining;
        return;
    }
    if (_dailyActionHoldUntil > now || (_dailyActionHoldUntil > 0. && !_dailyFallback && _effects.autonomyHeld)) return;
    if (_dailyActionHoldUntil > 0.) {
        [self cancelDailyAction];
        _dailyActionDue = now + MSPetRandomRange(14.0, 25.0);
        return;
    }
    [self scheduleDailyActionFrom:now];
    if (now < _dailyActionDue) return;
    NSTimeInterval duration = [_effects performDailyAction]; // Dedicated real artwork wins.
    if (duration <= 0.) {
        _dailyFallback = MSPetDailyChooseFallback((int)_spriteLayout, _sheet.CGImage != nil,
            _effects.hasActions, _lastDailyFallback, (unsigned)arc4random_uniform(3));
        duration = MSPetDailyFallbackDuration(_dailyFallback);
        if (duration > 0.) {
            _lastDailyFallback = (unsigned)_dailyFallback;
            _dailyFallbackBegan = now;
            _dailyFirstFramePending = YES;
            [self setSpriteState:(MiniSightPetState)MSPetDailyFallbackPose(_dailyFallback)];
        }
    }
    if (!(duration > 0.) || !isfinite(duration)) {
        _dailyActionDue = now + MSPetRandomRange(24.0, 36.0);
        return; // Static/unverified art stays honest and motionless.
    }
    _dailyActionDue = 0.;
    _dailyActionHoldUntil = now + duration + .25;
    [self invalidateRoamTimer]; // Pose ownership never changes the center or transform.
    MSDiagEvent(@"pet", @"daily_action", @"ok", @{@"source": @"app", @"reason": @"daily_selected", @"action_id": @((unsigned)_dailyFallback), @"duration_ms": @((NSInteger)lrint(duration * 1000.))});
}

- (void)scheduleRoam {
    if ([self measuredMusicInputAt:CACurrentMediaTime()]) {
        [self invalidateRoamTimer]; return; // No free-running/fallback beat.
    }
    if ((_effects.presentationBlocked && !_activityActive) || _effects.autonomyHeld || (!_rhythmFollowing && _effects.musicPlaying && ![self mayPerformMusicMotion])) {
        [self invalidateRoamTimer]; return;
    }
    // A state hold (waving) owns the sprite state: frameTick arms the next roam.
    // A running motion arms the next roam itself, in finishMotion.
    if (_landingRecoveryStage || _stateHoldUntil > 0. || _dailyActionHoldUntil > CACurrentMediaTime() || _motionActive || ![self mayRoam]) {
        [self invalidateRoamTimer];
        return;
    }
    // activityActive replaces the old tweak global: YES while the assistant is
    // acting (lively), NO for the resident idle pet (a move every 9-15 s).
    NSTimeInterval base = (!_rhythmFollowing && _effects.musicPlaying) ? MSPetRandomRange(1.5, 2.3) : _activityActive
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
    if ([self measuredMusicInputAt:CACurrentMediaTime()]) { [self invalidateRoamTimer]; return; }
    [self invalidateRoamTimer];
    if ((_effects.presentationBlocked && !_activityActive) || _effects.autonomyHeld || ![self mayRoam] || _motionActive) return;
    if (!_rhythmFollowing && _effects.musicPlaying) {
        if (![self mayPerformMusicMotion] || _landingRecoveryStage || _stateHoldUntil > 0.) return;
        MSPetMusicTravel travel = MSPetMusicTravelAt([self feasibleCenters], MSPetPoint(self.center), _musicMotionStep);
        if (travel.valid) {
            ++_musicMotionStep;
            _musicMotion = YES;
            [self startMotionTo:MSPetCGPoint(travel.target) jump:travel.jump rest:.25];
            if (!_motionActive) _musicMotion = NO;
        } else [self scheduleRoam];
        return;
    }
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
    } else {
        // Daily pose clips have their own clock above; roaming no longer owns
        // their frequency. Keep the old waving fallback only for legacy atlases.
        if (!_effects.hasDailyActions && roll < 90) [self holdState:MiniSightPetStateWaving forDuration:kMiniSightWaveHold];
        else {
            _restAfterMotion = MSPetRandomRange(2.0, 5.0);
            [self scheduleRoam];
        }
    }
}

- (void)holdState:(MiniSightPetState)state forDuration:(NSTimeInterval)duration {
    [self invalidateRoamTimer]; // No walking during the hold; frameTick arms the next one.
    [self setSpriteState:state];
    _stateHoldUntil = CACurrentMediaTime() + fmax(0., duration);
    [self reconcilePlayback];
}

#pragma mark - Imported actions and lyrics (shared presentation driver)
- (NSString *)actionManifestPath { return _effects.actionManifestPath; }
- (void)setActionManifestPath:(NSString *)path {
    if ((path == _effects.actionManifestPath) || [path isEqualToString:_effects.actionManifestPath]) return;
    [self ensureGravityLayer];
    _effects.actionManifestPath = path;
    _lastSpriteRect = CGRectNull;
    [self applySpriteFrame]; // Show a valid poster until a new first frame is ready.
}
- (NSString *)lyricsLine { return _effects.lyricsLine; }
- (void)setLyricsLine:(NSString *)line { _effects.lyricsLine = line; }
- (BOOL)rhythmFollowing { return _rhythmFollowing; }
- (void)setRhythmFollowing:(BOOL)following {
    NSAssert(NSThread.isMainThread, @"Rhythm is main-thread owned");
    if (_rhythmFollowing == following) return;
    [self clearRhythm];
    _rhythmFollowing = following;
    _effects.rhythmFollowing = following;
    [self invalidateRoamTimer];
    if (following && _musicMotion && !_physicsMotion && !_dragging)
        [self cancelMotion];
    [self reconcilePlayback];
}
- (void)resetRhythmForSession:(uint64_t)sessionToken {
    NSAssert(NSThread.isMainThread, @"Rhythm is main-thread owned");
    if (!sessionToken || sessionToken == _rhythmSessionToken) return;
    [self clearRhythm];
    _rhythmSessionToken = sessionToken;
    _rhythmPolicy = (MSPetRhythmPolicy){0};
}
- (void)clearRhythm {
    NSAssert(NSThread.isMainThread, @"Rhythm is main-thread owned");
    MSPetRhythmClear(&_rhythmPolicy);
    _rhythmStarting = NO;
    _rhythmAction = (MSPetRhythmAction){0};
    [_effects applyRhythmStrength:0 pulse:0];
    if (_musicMotion && !_physicsMotion && !_dragging) {
        [self cancelMotion];
        [self ensureFrameTimer];
        [self scheduleRoam]; // The measured link may have owned the only clock.
    }
}
- (void)checkRhythmAtTime:(CFTimeInterval)now {
    if (!_rhythmFollowing) return;
    if (![self mayPerformMusicMotion] || _dragging || _interactionActive || _physicsMotion ||
        !MSPetRhythmFresh(&_rhythmPolicy, now)) [self clearRhythm];
    NSUInteger mode = [self measuredMusicInputAt:now] ? 2u : (_effects.musicPlaying ? 1u : 0u);
    if (mode != _musicInputMode || (_effects.musicPlaying && now - _musicDiagAt >= 30.)) {
        _musicInputMode = mode; _musicDiagAt = now;
        MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"reason": @"music_input_mode",
            @"input_mode": @(mode), @"input_ready": @(mode == 2u), @"enabled": @(_rhythmFollowing)});
    }
}
- (void)applyRhythmFrame:(MSRhythmFrame)frame receivedAt:(CFTimeInterval)receivedAt {
    NSAssert(NSThread.isMainThread, @"Rhythm is main-thread owned");
    if (!_rhythmFollowing) return;
    BOOL gate = [self mayPerformMusicMotion] && !_dragging && !_physicsMotion && !_interactionActive;
    BOOL available = gate && (!_motionActive || !_musicMotion) && !_landingRecoveryStage &&
        _stateHoldUntil <= 0. && (!_effects.autonomyHeld || _dailyActionHoldUntil > 0.);
    MSPetRhythmAction action = MSPetRhythmConsume(&_rhythmPolicy, frame,
        receivedAt, CACurrentMediaTime(), [self feasibleCenters], MSPetPoint(self.center), available);
    if (!gate || !action.accepted) {
        if (CACurrentMediaTime() - _musicDiagAt >= 5.) {
            _musicDiagAt = CACurrentMediaTime();
            MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app",
                @"reason": gate ? @"rhythm_frame_rejected" : @"rhythm_owner_blocked", @"valid": @(action.accepted), @"input_ready": @NO});
        }
        [self clearRhythm]; return;
    }
    [self invalidateRoamTimer];
    if (_dailyActionHoldUntil > 0.) [self cancelDailyAction];
    [_effects applyRhythmStrength:action.strength pulse:action.pulse];
    if (!action.valid || !available) return;
    [self cancelDailyAction];
    if (_motionActive && !_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];
    _rhythmAction = action;
    _rhythmStarting = YES;
    _musicMotion = YES;
    [self startMotionTo:MSPetCGPoint(action.target) jump:action.jump rest:0];
    _rhythmStarting = NO; // Manual physics never inherits measured duration/height.
    _rhythmAction = (MSPetRhythmAction){0};
    if (!_motionActive) _musicMotion = NO;
}

- (BOOL)musicPlaying { return _effects.musicPlaying; }
- (NSTimeInterval)musicPosition { return _effects.musicPosition; }
- (void)setMusicPosition:(NSTimeInterval)position { _effects.musicPosition = position; }
- (void)setMusicPlaying:(BOOL)playing {
    if (_effects.musicPlaying == playing) return;
    if (playing && !_rhythmFollowing) [self cancelDailyAction];
    _effects.musicPlaying = playing;
    [self clearRhythm];
    MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"active": @((BOOL)playing), @"reason": @"music_state"});
    if (!_rhythmFollowing) [self invalidateRoamTimer];
    if (playing) {
        _musicMotionStep = 0;
        // Retire only the old automatic route, not a manual drag or fling.
        if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];
        [self wakeForInteraction];
    } else {
        // Freeze at the current real center; no snap to an unfinished target.
        if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];
        if (_state == MiniSightPetStateMusic) [self setSpriteState:MiniSightPetStateIdle];
    }
    [self reconcilePlayback]; // Reuses the one ordinary roam timer/link.
}
- (BOOL)lyricsSuppressed { return _lyricsSuppressed; }
- (void)setLyricsSuppressed:(BOOL)suppressed {
    _lyricsSuppressed = suppressed;
    if (suppressed) [self clearRhythm];
    _effects.busy = suppressed || _motionLockReasons != 0 || _activityActive;
}

#pragma mark - Motion (one CADisplayLink; position and sprite for the same frame)

- (void)beginDraggingWithDirection:(CGFloat)direction {
    (void)direction;
    [self beginDraggingAtPoint:CGPointMake(self.bounds.size.width * .5, self.bounds.size.height * .35)];
}
- (void)beginDraggingAtPoint:(CGPoint)localPoint {
    NSAssert(NSThread.isMainThread, @"Drag is main-thread owned");
    if (_dragging || ![self shouldAnimate]) return;
    [self wakeForInteraction];
    [self cancelDailyAction];
    _dragging = YES; _interactionActive = YES;
    [self clearRhythm];
    MSDiagEvent(@"drag", @"begin", @"ok", @{@"source": @"app", @"reason": @"pet_drag"});
    MSPetResidentCancelWakePose(&_resident);
    [self cancelMotion]; [self cancelGravityImpulse];
    [self setSpriteState:MiniSightPetStateDragging];
    _stateHoldUntil = DBL_MAX;
    [self invalidateRoamTimer];
    [_effects beginDragAt:localPoint];
    [self reconcilePlayback];
}
- (void)updateDraggingTarget:(CGPoint)center {
    if (_dragging && [self shouldAnimate]) [_effects dragTo:[self clampedCenter:center]];
}
- (void)endDragging { [self endDraggingCancelled:YES]; }
- (void)endDraggingCancelled:(BOOL)cancelled {
    NSAssert(NSThread.isMainThread, @"Drag is main-thread owned");
    if (!_dragging) return;
    CGPoint velocity = [_effects endDragCancelled:cancelled];
    _dragging = NO; _interactionActive = NO;
    MSDiagEvent(@"drag", @"end", @"ok", @{@"source": @"app", @"reason": cancelled ? @"cancelled" : (hypot(velocity.x, velocity.y)>0.?@"released_with_velocity":@"released_static")});
    if (![self shouldAnimate]) { [self reconcilePlayback]; return; }
    MSPetResidentTouch(&_resident, CACurrentMediaTime());
    MSPetResidentCancelWakePose(&_resident);
    [self setSpriteState:MiniSightPetStateIdle];
    _stateHoldUntil = CACurrentMediaTime() + .5; _restAfterMotion = .5;
    if (!cancelled && !_roamingPaused && !_motionLockReasons && hypot(velocity.x, velocity.y) > 0.) {
        MSGravityBodyLaunch(&_gravityBody, [self feasibleCenters], MSPetPoint(self.center), MSPetPoint(velocity));
        _physicsMotion = _gravityBody.active; _motionActive = _physicsMotion;
        _activeMotionGeneration = ++_motionGeneration;
        _lastMotionTick = CACurrentMediaTime(); _stateHoldUntil = 0.;
        _flingSpin = 0.; _flingSpinVelocity = (velocity.x < 0 ? -1. : 1.) * 2.; _flingSquash = 0.;
        if (_physicsMotion) [self setSpriteState:MiniSightPetStateJumping];
        [_effects setFlightAngle:0 squash:0 active:_physicsMotion];
        [self invalidateFrameTimer]; [self invalidateRoamTimer]; [self ensureMotionLink];
    }
    [self reconcilePlayback];
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
        height = MSPetSafeJumpHeight([self feasibleCenters], MSPetPoint(start), MSPetPoint(end),
            _rhythmStarting ? _rhythmAction.height : kMiniSightJumpDesiredHeight);
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
    if (_rhythmStarting) _motionDuration = _rhythmAction.duration;
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
    _effects.preferredFPS = fps;
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
    [self checkRhythmAtTime:CACurrentMediaTime()];
    if (!_motionActive || _activeMotionGeneration != _motionGeneration) return;
    if (![self shouldAnimate] || _roamingPaused || _interactionActive || _motionLockReasons ||
        (!_physicsMotion && _effects.presentationBlocked && !_activityActive) ||
        (_musicMotion && ![self mayPerformMusicMotion])) {
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
        BOOL absorbed = MSGravityBodyAbsorbHardFloor(&_gravityBody, [self feasibleCenters], hits);
        if ((hits & MSGravityHitFloor) && (_loggedFloorGeneration != generation || absorbed)) {
            _loggedFloorGeneration = generation;
            MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"reason": @"floor_contact", @"value": @(absorbed ? 2 : 1), @"generation": @(generation)});
        }
        self.center = MSPetCGPoint(_gravityBody.position);
        // Geometry callbacks may hide, replace, resize, or lock this pet.
        if (!_motionActive || generation != _motionGeneration || !_physicsMotion) return;
        double spinDT = MIN(MAX(elapsed, 0.), .1);
        _flingSpin += _flingSpinVelocity * spinDT;
        _flingSpinVelocity *= exp(-1.7 * spinDT);
        if (hits) {
            _flingSpinVelocity *= -0.62;
            _flingSquash = (hits & MSGravityHitFloor) ? 1.0 : .55;
        } else {
            _flingSquash *= exp(-9.0 * spinDT);
        }
        [_effects setFlightAngle:0.24 * sin(_flingSpin) squash:_flingSquash active:YES];
        self.transform = CGAffineTransformIdentity;
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

- (void)beginLandingRecoveryWithImpact:(CGFloat)impact {
    if (!(impact >= 720.) || ![self shouldAnimate] || _dragging || _interactionActive || _motionLockReasons ||
        _activityActive || _lyricsSuppressed || _roamingPaused || _effects.presentationBlocked || UIAccessibilityIsReduceMotionEnabled()) {
        [self setSpriteState:MiniSightPetStateIdle]; return;
    }
    [self clearLandingRecovery];
    _landingRecoveryStage = 1;
    _landingRecoveryBegan = CACurrentMediaTime();
    MSDiagEvent(@"pet", @"state", @"ok", @{@"source": @"app", @"value": @1, @"reason": @"landing_settle"});
    // Unverified atlas art is not a new sleep/fall sequence. Use the neutral
    // row for the presentation fallback; a real land clip owns its own frames.
    [self setSpriteState:MiniSightPetStateIdle];
    [_effects setLandingRecoveryStage:1];
    [self invalidateRoamTimer];
}
- (void)clearLandingRecovery {
    if (!_landingRecoveryStage) return;
    _landingRecoveryStage = 0; _landingRecoveryBegan = 0.;
    MSDiagEvent(@"pet", @"finish", @"ok", @{@"source": @"app", @"reason": @"landing_clear"});
    [_effects setLandingRecoveryStage:0];
    if (!_resident.sleeping && !_resident.waking && _state == MiniSightPetStateSleeping)
        [self setSpriteState:MiniSightPetStateIdle]; // Normal pose arbitration may resume music on the next tick.
}
- (void)finishMotion {
    BOOL landed = _physicsMotion || _jumpHeight > 0.;
    NSUInteger generation = _motionGeneration;
    CGPoint end = _physicsMotion ? MSPetCGPoint(_gravityBody.position) : MSPetCGPoint(_motionEnd);
    self.center = [self clampedCenter:end];
    if (!_motionActive || generation != _motionGeneration) return;
    CGFloat floorImpact = (landed && _physicsMotion) ? (CGFloat)_gravityBody.floorImpactVelocity : 0.;
    [_effects setFlightAngle:0 squash:0 active:NO];
    [_effects setFloorImpactVelocity:floorImpact];
    if (landed) [_effects land];
    BOOL heavyLanding = floorImpact >= 720.;
    _motionActive = NO;
    _musicMotion = NO;
    _physicsMotion = NO;
    _activeMotionGeneration = 0;
    _flingSpin = 0.; _flingSpinVelocity = 0.; _flingSquash = 0.;
    self.transform = CGAffineTransformIdentity;
    MSGravityBodyCancel(&_gravityBody);
    [_motionLink invalidate];
    _motionLink = nil;
    if (heavyLanding) [self beginLandingRecoveryWithImpact:floorImpact];
    else [self setSpriteState:MiniSightPetStateIdle];
    [self applyGravityTransformAtTime:CACurrentMediaTime()];
    [self reconcilePlayback]; // Restarts sprite clock; never invents a rebound target.
}

- (void)cancelMotion {
    [self clearLandingRecovery];
    [_effects setFlightAngle:0 squash:0 active:NO];
    ++_motionGeneration; // Fence any already-delivered callback before it can rearm.
    _motionActive = NO;
    _musicMotion = NO;
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
    if (_resident.sleeping || _resident.waking) [self setSpriteState:MiniSightPetStateSleeping];
    else if (!_dragging) [self setSpriteState:MiniSightPetStateIdle];
}

@end
