#import "MiniSightPetEffects.h"
#import "MiniSightPet.h"
#import "MiniSightActionLibrary.h"
#import "MiniSightLiveliness.h"
#import "MiniSightLog.h"
#import "MiniSightGeometry.h"
#import "MiniSightChatPanel.h"
#import <QuartzCore/QuartzCore.h>

@class MiniSightPetEffects;
@interface MSPetEffectsProxy : NSObject
@property (nonatomic, weak) MiniSightPetEffects *owner;
- (void)tick:(CADisplayLink *)link;
@end
@interface MiniSightPetEffects () {
    __weak MiniSightPetView *_pet;
    __weak CALayer *_sprite;
    CADisplayLink *_link;
    MSPetEffectsProxy *_proxy;
    MiniSightActionLibrary *_library;
    MiniSightActionClip *_clip;
    NSString *_actionManifestPath, *_lyricsLine, *_role, *_wantedRole, *_lastClip, *_lastDailyClip;
    UIView *_bubble;
    UILabel *_label;
    CAShapeLayer *_tail, *_dizzyStars;
    BOOL _running, _busy, _musicPlaying, _dragging, _flying, _waking, _framePending, _ownsSprite;
    NSUInteger _manifestRetries;
    CFTimeInterval _selectionBegan;
    NSSet<NSString *> *_failedClips;
    NSInteger _state;
    NSUInteger _generation, _frameRequest, _displayedFrame;
    CFTimeInterval _lastTime, _clipStart, _transientUntil, _shakeUntil, _landUntil, _frameRetryAt, _landBegan, _shakeBegan;
    NSUInteger _frameFailures;
    MSPetDamped _pivotX, _pivotY;
    NSString *_transientRole;
    CGFloat _tilt, _sway, _flightAngle, _impact, _landImpact, _grabX, _grabY, _shakeStrength, _shakeDirection;
    double _musicAnchor, _musicAnchorAt, _musicAmplitude, _recoveryBegan;
    NSInteger _recoveryStage;
    unsigned _musicEvidenceBudget, _lastMusicCue;
    BOOL _rhythmFollowing, _dailyActionOwned;
    double _rhythmStrength, _rhythmPulse, _rhythmAt;
    MSPetDamped _angle, _offsetX, _offsetY, _scaleX, _scaleY, _dragX, _dragY;
    MSPetDragTrail _trail;
    CGPoint _dragTarget, _visualOffset;
    CGSize _bubbleSize, _lastTailSize;
    CGFloat _lastTailX, _measurementWidth;
    BOOL _lyricsVisibleEvidence, _lyricsHadTextEvidence;
    NSString *_lyricsReasonEvidence;
}
- (void)tick:(CADisplayLink *)link;
- (void)chooseRole;
- (void)loadManifestGeneration:(NSUInteger)generation;
- (void)restorePoster;
- (void)resetRigidPresentation;
- (BOOL)presentationBlocked;
- (void)requestFrame:(NSUInteger)index;
- (void)advanceActions:(double)now;
- (void)placeLyricsBlocked:(BOOL)blocked;
@end
@implementation MSPetEffectsProxy
- (void)tick:(CADisplayLink *)link {
    MiniSightPetEffects *owner = self.owner;
    if (owner) [owner tick:link]; else [link invalidate];
}
@end
@implementation MiniSightPetEffects
- (instancetype)initWithPet:(MiniSightPetView *)pet layer:(CALayer *)layer {
    if ((self = [super init])) {
        _pet = pet; _sprite = layer; _scaleX.value = 1.; _scaleY.value = 1.;
        _displayedFrame = NSNotFound;
        _proxy = [MSPetEffectsProxy new]; _proxy.owner = self;
    }
    return self;
}
- (NSString *)actionManifestPath { return _actionManifestPath; }
- (void)setActionManifestPath:(NSString *)path {
    NSAssert(NSThread.isMainThread, @"Actions are main-thread owned");
    if ((_actionManifestPath == path) || [_actionManifestPath isEqualToString:path]) return;
    _actionManifestPath = [path copy]; ++_generation; ++_frameRequest; _framePending = NO;
    _clip = nil; _role = nil; _wantedRole = nil; _displayedFrame = NSNotFound;
    _ownsSprite = NO; _manifestRetries = 0; _failedClips = [NSSet set];
    _dailyActionOwned = NO;
    _lastDailyClip = nil; // A different manifest owns a fresh daily-action history.
    [_library purgeFrames]; _library = nil;
    [self restorePoster]; // Retire the previous clip even if the new manifest fails.
    if (path.length) [self loadManifestGeneration:_generation];
}
- (void)loadManifestGeneration:(NSUInteger)generation {
    NSString *path = [_actionManifestPath copy];
    __weak typeof(self) weakSelf = self;
    [MiniSightActionLibrary loadManifestAtPath:path completion:^(MiniSightActionLibrary *library, NSError *error) {
        typeof(self) self = weakSelf;
        if (!self || generation != self->_generation) return;
        if (!library) {
            if (error.code == 5 && self->_manifestRetries++ < 2) {
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                    typeof(self) self = weakSelf;
                    if (self && generation == self->_generation) [self loadManifestGeneration:generation];
                });
            }
            return; // Invalid packages leave the host's poster/legacy image intact.
        }
        self->_library = library;
        if (self->_running) [self chooseRole];
    }];
}
- (BOOL)hasActions { return _ownsSprite; }
- (BOOL)hasDailyActions { return _library.roles[@"idleAlt"].count > 0; }
- (BOOL)isDragging { return _dragging; }
- (BOOL)presentationBlocked { return _busy || MiniSightChatPanel.existingPanel.isVisible; }
- (BOOL)rhythmFollowing { return _rhythmFollowing; }
- (void)setRhythmFollowing:(BOOL)following {
    _rhythmFollowing = following;
    _rhythmStrength = _rhythmPulse = _rhythmAt = 0.;
    _musicAmplitude = 0.;
}
- (void)applyRhythmStrength:(CGFloat)strength pulse:(CGFloat)pulse {
    _rhythmStrength = MSPetFiniteClamp(strength, 0., 1.);
    _rhythmPulse = MSPetFiniteClamp(pulse, 0., 1.);
    _rhythmAt = CACurrentMediaTime();
}
- (BOOL)musicPlaying { return _musicPlaying; }
- (void)setMusicPlaying:(BOOL)playing {
    if (_musicPlaying == playing) return;
    if (!playing) _musicAnchor = self.musicPosition; // Freeze the render clock on pause.
    _musicAnchorAt = CACurrentMediaTime();
    _musicPlaying = playing; _musicEvidenceBudget = playing ? 3 : 0; _lastMusicCue = 8;
}
- (NSTimeInterval)musicPosition {
    return MSPetMusicInterpolate(_musicAnchor, CACurrentMediaTime() - _musicAnchorAt, _musicPlaying);
}
- (void)setMusicPosition:(NSTimeInterval)position {
    _musicAnchor = isfinite(position) ? fmax(0., position) : 0.;
    _musicAnchorAt = CACurrentMediaTime();
}
- (BOOL)landingRecoveryHeld {
    if (!_running || !_recoveryStage || [self presentationBlocked] || _dragging || _flying ||
        UIAccessibilityIsReduceMotionEnabled() || ![_role isEqualToString:@"land"] || !_clip) return NO;
    double now = CACurrentMediaTime();
    // The real clip begins with its first decoded frame, not its request time.
    // A missing first frame may wait only within the existing bounded window.
    return _clipStart > 0 ? now - _clipStart < _clip.duration : now - _selectionBegan < 2.;
}
- (BOOL)autonomyHeld {
    if (!_running || [self presentationBlocked] || _dragging) return NO;
    double now = CACurrentMediaTime();
    BOOL transient = [@[@"tap", @"idleAlt", @"land", @"shakeSoft", @"shakeHard", @"wake"] containsObject:_role];
    if (!transient || !_clip) return NO;
    return _clipStart > 0 ? now - _clipStart < _clip.duration : now - _selectionBegan < 2.;
}
- (void)restorePoster {
    _ownsSprite = NO;
    [_pet restorePosterFrame];
}
- (CGPoint)visualOffset { return _visualOffset; }
- (void)setLegacyState:(NSInteger)state waking:(BOOL)waking {
    double now = CACurrentMediaTime();
    if (_state != state && state == 3 && !([_role isEqualToString:@"tap"] && [self autonomyHeld])) {
        _wantedRole = nil; _role = nil; // A new tap after the prior clip ended may replay the same asset.
    }
    if (_waking && !waking && [_role isEqualToString:@"wake"] && _clipStart > 0 && now - _clipStart < _clip.duration)
        _waking = YES;
    else _waking = waking;
    _state = state;
}
- (NSString *)currentRole {
    double now = CACurrentMediaTime();
    if (_dragging) return @"drag";
    if ([self presentationBlocked]) return @"idle";
    if (now < _shakeUntil) return _shakeStrength >= .55 ? @"shakeHard" : @"shakeSoft";
    if (_flying) return @"flight";
    if (_recoveryStage && !UIAccessibilityIsReduceMotionEnabled()) {
        // An explicit user-supplied land clip owns the WHOLE recovery.
        // Never restart it or substitute sleep/wake as the phases advance.
        return _library.roles[@"land"].count ? @"land" : @"idle";
    }
    if (_transientRole && now < _transientUntil) return _transientRole;
    if (now < _landUntil && !UIAccessibilityIsReduceMotionEnabled()) return @"land";
    if (_state == 0 && [_role isEqualToString:@"tap"] &&
        (_clipStart > 0 ? now - _clipStart < _clip.duration : now - _selectionBegan < 2.))
        return @"tap"; // Count the clip from its prepared first frame, not the input event.
    if (_waking) return @"wake";
    if (_state == 5) return @"sleep";
    if (_state == 1) return @"walkRight";
    if (_state == 2) return @"walkLeft";
    if (_state == 3) return @"tap";
    if (_state == 4) return @"jump";
    // Automatic music playback adds in-place sway to idle art only. A legacy
    // music clip can contain travelling/jumping frames, so do not auto-select it.
    if (_state == 8 && _musicPlaying) return @"idle";
    return @"idle";
}
- (void)chooseRole {
    if (!_library || !_running) return;
    NSString *wanted = [self currentRole];
    if ([_wantedRole isEqualToString:wanted] && (_clip || [_role isEqualToString:@"poster"])) return;
    NSArray<MiniSightActionClip *> *pool = _library.roles[wanted];
    NSString *actual = wanted;
    NSPredicate *usable = [NSPredicate predicateWithBlock:^BOOL(id item, NSDictionary *bindings) {
        (void)bindings;
        if (![item isKindOfClass:MiniSightActionClip.class]) return NO;
        MiniSightActionClip *clip = item;
        return ![self->_failedClips containsObject:clip.identifier];
    }];
    pool = [pool filteredArrayUsingPredicate:usable];
    NSArray<MiniSightActionClip *> *allUsablePool = pool;
    if ([actual isEqualToString:@"idleAlt"] && pool.count > 1) {
        NSMutableDictionary<NSString *, NSMutableArray<MiniSightActionClip *> *> *groups = [NSMutableDictionary dictionary];
        for (MiniSightActionClip *clip in pool) {
            NSString *category = clip.category ?: @"micro"; // Older packs remain a valid small-action pool.
            if (!groups[category]) groups[category] = [NSMutableArray array];
            [groups[category] addObject:clip];
        }
        NSDictionary<NSString *, NSNumber *> *weights = @{@"micro": @55, @"play": @30, @"food": @15,
            @"seasonal": @10, @"social": @10};
        NSUInteger totalWeight = 0;
        for (NSString *category in groups) totalWeight += MAX(1, weights[category].unsignedIntegerValue);
        NSUInteger roll = arc4random_uniform((uint32_t)MAX(1, totalWeight));
        for (NSString *category in @[@"micro", @"play", @"food", @"seasonal", @"social"]) {
            NSArray *items = groups[category]; if (!items.count) continue;
            NSUInteger weight = MAX(1, weights[category].unsignedIntegerValue);
            if (roll < weight) { pool = items; break; }
            roll -= weight;
        }
    }
    if (!pool.count) { pool = [_library.roles[@"idle"] filteredArrayUsingPredicate:usable]; actual = @"idle"; }
    _wantedRole = wanted;
    if ([_role isEqualToString:actual] && _clip) return;
    if (!pool.count) { _clip = nil; _role = @"poster"; [self restorePoster]; return; }
    // Base idle and interaction clips must not erase the last daily choice.
    NSString *avoidClip = [actual isEqualToString:@"idleAlt"] ? _lastDailyClip : _lastClip;
    NSMutableArray<MiniSightActionClip *> *choices = [pool mutableCopy];
    if (choices.count > 1 && avoidClip) {
        NSIndexSet *indexes = [choices indexesOfObjectsPassingTest:^BOOL(MiniSightActionClip *item, NSUInteger idx, BOOL *stop) {
            (void)idx; (void)stop; return [item.identifier isEqualToString:avoidClip];
        }];
        [choices removeObjectsAtIndexes:indexes];
    }
    if (!choices.count) choices = [pool mutableCopy];
    if (choices.count == 1 && allUsablePool.count > 1 &&
        [choices.firstObject.identifier isEqualToString:avoidClip]) {
        choices = [allUsablePool mutableCopy];
        NSIndexSet *indexes = [choices indexesOfObjectsPassingTest:^BOOL(MiniSightActionClip *item, NSUInteger idx, BOOL *stop) {
            (void)idx; (void)stop; return [item.identifier isEqualToString:avoidClip];
        }];
        if (indexes.count) [choices removeObjectsAtIndexes:indexes];
    }
    MiniSightActionClip *next = choices[arc4random_uniform((uint32_t)choices.count)];
    _role = actual; _clip = next; _lastClip = next.identifier;
    if ([actual isEqualToString:@"idleAlt"]) _lastDailyClip = next.identifier;
    _selectionBegan = CACurrentMediaTime();
    _clipStart = 0; _displayedFrame = NSNotFound; _frameRetryAt = 0; _frameFailures = 0;
    ++_frameRequest; _framePending = NO;
    [self requestFrame:0];
}
- (void)requestFrame:(NSUInteger)index {
    if (!_running || !_clip || !_library || _framePending || _displayedFrame == index ||
        CACurrentMediaTime() < _frameRetryAt) return;
    _framePending = YES;
    NSUInteger generation = _generation, request = _frameRequest;
    MiniSightActionClip *clip = _clip;
    __weak typeof(self) weakSelf = self;
    [_library requestFrameForClip:clip index:index completion:^(UIImage *image) {
        typeof(self) self = weakSelf;
        if (!self || generation != self->_generation || request != self->_frameRequest || !self->_running) return;
        self->_framePending = NO;
        if (!image.CGImage) {
            self->_frameFailures++;
            self->_frameRetryAt = CACurrentMediaTime() + fmin(30., .5 * (double)self->_frameFailures);
            if (self->_frameFailures >= 3) {
                self->_failedClips = [self->_failedClips setByAddingObject:clip.identifier];
                self->_clip = nil; self->_role = nil; self->_wantedRole = nil;
                [self restorePoster]; [self chooseRole];
            }
            return; // Keep the last good image; a corrupt frame never creates a hot retry loop.
        }
        self->_frameFailures = 0; self->_frameRetryAt = 0;
        BOOL first = self->_clipStart == 0;
        if (first && self->_recoveryStage && [self->_role isEqualToString:@"land"]) {
            // A delayed real land frame must not inherit fallback rotation/stars.
            [self resetRigidPresentation]; self->_dizzyStars.hidden = YES;
        }
        self->_ownsSprite = YES;
        [CATransaction begin]; [CATransaction setDisableActions:YES];
        self->_sprite.contents = (__bridge id)image.CGImage;
        self->_sprite.contentsGravity = kCAGravityResizeAspect;
        self->_sprite.contentsRect = CGRectMake(0, 0, 1, 1);
        [CATransaction commit];
        self->_displayedFrame = index;
        if (first) {
            self->_clipStart = CACurrentMediaTime();
            if (self->_dailyActionOwned && [self->_role isEqualToString:@"idleAlt"]) {
                NSUInteger actionID = [self->_library.roles[@"idleAlt"] indexOfObjectIdenticalTo:clip];
                MSDiagEvent(@"pet", @"daily_action", @"ok", @{@"source": ([NSProcessInfo.processInfo.processName isEqualToString:@"SpringBoard"] ? @"plugin" : @"app"), @"reason": @"daily_first_frame",
                    @"action_id": @(actionID == NSNotFound ? 0 : actionID + 100), @"frame_count": @(clip.frameCount), @"frame_index": @(index)});
            }
            if (!self->_recoveryStage && [self->_role isEqualToString:@"land"]) self->_landUntil = self->_clipStart + clip.duration;
            if ([self->_role isEqualToString:@"shakeSoft"] || [self->_role isEqualToString:@"shakeHard"])
                self->_shakeUntil = self->_clipStart + clip.duration;
            if ([self->_role isEqualToString:self->_transientRole]) self->_transientUntil = self->_clipStart + clip.duration;
            // Only a prepared first frame switches; no blank between clips.
            CATransition *fade = [CATransition animation]; fade.type = kCATransitionFade; fade.duration = .10;
            [self->_sprite addAnimation:fade forKey:@"minisight.clip.transition"];
        }
    }];
}
- (void)advanceActions:(double)now {
    if (_transientRole && now >= _transientUntil) { _transientRole = nil; _transientUntil = 0; }
    [self chooseRole];
    if (!_clip) return;
    if (_clipStart <= 0) { [self requestFrame:0]; return; }
    double duration = _clip.duration;
    if (!(duration > 0)) return;
    double elapsed = [_role isEqualToString:@"music"] ? self.musicPosition : fmax(0., now - _clipStart);
    if (elapsed >= duration && [_role isEqualToString:@"idle"] && _library.roles[@"idle"].count > 1) {
        _role = nil; _wantedRole = nil; [self chooseRole]; return;
    }
    if (elapsed >= duration && _transientRole) {
        _transientRole = nil; _transientUntil = 0; _wantedRole = nil;
        [self chooseRole]; return;
    }
    BOOL loops = [@[@"idle", @"music", @"drag", @"walkLeft", @"walkRight", @"flight", @"sleep"] containsObject:_role];
    double time = loops ? fmod(elapsed, duration) : fmin(elapsed, duration);
    double edge = 0;
    NSUInteger index = 0;
    for (NSNumber *length in _clip.durations) {
        edge += length.doubleValue;
        if (time < edge) break;
        ++index;
    }
    [self requestFrame:MIN(index, _clip.frameCount - 1)];
}
- (void)setRunning:(BOOL)running {
    if (_running == running) return;
    _running = running;
    if (!running) {
        ++_frameRequest; _framePending = NO; _frameRetryAt = 0; _frameFailures = 0;
        [_link invalidate]; _link = nil;
        _dailyActionOwned = NO;
        _dragging = NO; _flying = NO; _waking = NO; _state = 0; _transientRole = nil;
        _shakeUntil = 0; _landUntil = 0; _musicAmplitude = 0; _recoveryStage = 0;
        memset(&_trail, 0, sizeof(_trail));
        [_library purgeFrames];
        [self restorePoster];
        _angle = (MSPetDamped){0,0}; _offsetX = (MSPetDamped){0,0}; _offsetY = (MSPetDamped){0,0};
        _scaleX = (MSPetDamped){1,0}; _scaleY = (MSPetDamped){1,0}; _visualOffset = CGPointZero;
        [_sprite removeAnimationForKey:@"minisight.clip.transition"];
        [CATransaction begin]; [CATransaction setDisableActions:YES]; _sprite.affineTransform = CGAffineTransformIdentity; [CATransaction commit];
        _bubble.hidden = YES;
        _dizzyStars.hidden = YES; _dizzyStars.path = nil;
        return;
    }
    _lastTime = CACurrentMediaTime(); _clipStart = 0; _displayedFrame = NSNotFound;
    _link = [CADisplayLink displayLinkWithTarget:_proxy selector:@selector(tick:)];
    _link.preferredFramesPerSecond = _preferredFPS > 0 ? _preferredFPS : 60;
    [_link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
    [self chooseRole];
    if (_clip) [self requestFrame:0];
}
- (void)setPreferredFPS:(NSInteger)fps {
    _preferredFPS = fps == 30 || fps == 60 || fps == 120 ? fps : 0;
    _link.preferredFramesPerSecond = _preferredFPS > 0 ? _preferredFPS : 60;
}
- (void)setTilt:(CGFloat)angle sway:(CGFloat)sway { _tilt = angle; _sway = sway; }
- (void)setFlightAngle:(CGFloat)angle squash:(CGFloat)squash active:(BOOL)active {
    BOOL begins = active && !_flying;
    _flightAngle = MSPetFiniteClamp(angle, -.35, .35);
    _impact = MSPetFiniteClamp(squash, 0, 1); _flying = active;
    if (begins) { _landImpact = 0.; _wantedRole = nil; [self chooseRole]; }
}
- (void)setFloorImpactVelocity:(CGFloat)velocity {
    CGFloat bounded = MSPetFiniteClamp(velocity, 0., 1800.);
    _landImpact = MSPetFiniteClamp((bounded - 360.) / 840., 0., 1.);
}
- (void)resetRigidPresentation {
    _angle = (MSPetDamped){0,0}; _offsetX = (MSPetDamped){0,0}; _offsetY = (MSPetDamped){0,0};
    _scaleX = (MSPetDamped){1,0}; _scaleY = (MSPetDamped){1,0}; _visualOffset = CGPointZero;
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    _sprite.affineTransform = CGAffineTransformIdentity; [CATransaction commit];
}
- (void)setLandingRecoveryStage:(NSInteger)stage {
    stage = MIN(4, MAX(0, stage));
    if (_recoveryStage == stage) return;
    if (stage == 1) _recoveryBegan = CACurrentMediaTime();
    if (stage == 1 || !stage) {
        // Retire flight squash/tilt at contact, and retire recovery on cancellation.
        // Whole-body recovery must never inherit a flattened flight presentation.
        [self resetRigidPresentation];
    }
    _recoveryStage = stage;
    _transientRole = nil; _transientUntil = 0.; _landUntil = 0.; _shakeUntil = 0.;
    if (!stage) {
        _recoveryBegan = 0.; _dizzyStars.hidden = YES;
        ++_frameRequest; _framePending = NO; // Fence a cancelled land's late frame.
        _clip = nil; _role = nil; _wantedRole = nil;
        [self restorePoster];
    } else if (stage == 1) { _wantedRole = nil; }
    [self chooseRole];
}
- (void)beginDragAt:(CGPoint)localPoint {
    if (_dragging) return;
    MiniSightPetView *pet = _pet;
    _dragging = YES; _flying = NO; _landUntil = 0; _shakeUntil = 0;
    _landImpact = 0.; // A new gentle placement cannot reuse an earlier hard contact.
    _transientRole = nil; _transientUntil = 0;
    _dragTarget = pet.center; _dragX = (MSPetDamped){pet.center.x, 0}; _dragY = (MSPetDamped){pet.center.y, 0};
    _grabX = MSPetFiniteClamp(localPoint.x / fmax(1., pet.bounds.size.width), 0., 1.);
    _grabY = MSPetFiniteClamp(localPoint.y / fmax(1., pet.bounds.size.height), 0., 1.);
    memset(&_trail, 0, sizeof(_trail));
    MSPetDragRemember(&_trail, CACurrentMediaTime(), pet.center.x, pet.center.y);
    _wantedRole = nil; [self chooseRole];
}
- (void)dragTo:(CGPoint)center {
    if (!_dragging) return;
    _dragTarget = center;
    MSPetDragRemember(&_trail, CACurrentMediaTime(), center.x, center.y);
}
- (CGPoint)endDragCancelled:(BOOL)cancelled {
    double vx = 0., vy = 0.;
    if (_dragging && !cancelled) MSPetReleaseVelocity(&_trail, CACurrentMediaTime(), &vx, &vy);
    _dragging = NO; memset(&_trail, 0, sizeof(_trail));
    _wantedRole = nil;
    if (!cancelled && vx == 0 && vy == 0) [self land];
    [self chooseRole];
    return CGPointMake(vx, vy);
}
- (void)shakeDirection:(CGFloat)direction strength:(CGFloat)strength {
    double now = CACurrentMediaTime();
    if (now < _shakeUntil || _busy || _dragging) return;
    _shakeStrength = MSPetFiniteClamp(strength, 0, 1);
    _shakeDirection = direction < 0 ? -1 : 1;
    _shakeBegan = now;
    _shakeUntil = now + (_shakeStrength >= .55 ? 1.0 : .65);
    _wantedRole = nil; [self chooseRole];
}
- (void)land {
    _landBegan = CACurrentMediaTime();
    // _landImpact comes only from setFloorImpactVelocity:, never from visual squash.
    _landUntil = _landBegan + .5 + .28 * _landImpact; _flying = NO; _shakeUntil = 0; _wantedRole = nil;
    [self chooseRole];
}
- (NSTimeInterval)performIdleAction {
    return [self performDailyAction];
}
- (NSTimeInterval)performDailyAction {
    if (!_library.roles[@"idleAlt"].count || [self presentationBlocked] || _dragging || _flying || !_running ||
        (_musicPlaying && (!_rhythmFollowing || (_rhythmStrength > 0. && CACurrentMediaTime() - _rhythmAt <= .40)))) return 0.;
    if ([_role isEqualToString:@"idleAlt"] && [self autonomyHeld]) return fmax(.2, _clip.duration - (CACurrentMediaTime() - _clipStart));
    _dailyActionOwned = YES;
    _role = nil;
    _transientRole = @"idleAlt"; _transientUntil = CACurrentMediaTime() + 120.;
    _wantedRole = nil; [self chooseRole];
    if (_clip && [_role isEqualToString:@"idleAlt"]) return _clip.duration;
    _transientRole = nil; _transientUntil = 0.; _wantedRole = nil; _role = nil;
    _dailyActionOwned = NO;
    [self chooseRole]; // All daily clips failed: visibly fall back to the base idle.
    return 0.;
}
- (void)cancelDailyAction {
    if (!_dailyActionOwned) return;
    _dailyActionOwned = NO;
    if (![_transientRole isEqualToString:@"idleAlt"]) return;
    _transientRole = nil; _transientUntil = 0.;
    if (![_role isEqualToString:@"idleAlt"]) return; // Another role already took over.
    ++_frameRequest; _framePending = NO; // Fence daily's outstanding decode only.
    _frameRetryAt = 0.; _frameFailures = 0; _clip = nil; _role = nil; _wantedRole = nil;
    [self restorePoster];
    [self chooseRole]; // Never clears _lastDailyClip or a manual owner's timers.
}
- (void)tick:(CADisplayLink *)link {
    if (!_running || link != _link) return;
    MiniSightPetView *pet = _pet;
    if (!pet || !pet.window || pet.window.hidden || pet.hidden || pet.alpha <= .01) { [self setRunning:NO]; return; }
    double now = CACurrentMediaTime(), dt = fmin(.05, fmax(0., now - _lastTime)); _lastTime = now;
    BOOL blocked = [self presentationBlocked];
    if (blocked) { _transientRole = nil; _transientUntil = 0; _shakeUntil = 0; _landUntil = 0; }
    if (_dragging) {
        MSPetDampedStep(&_dragX, _dragTarget.x, dt, 28.);
        MSPetDampedStep(&_dragY, _dragTarget.y, dt, 28.);
        pet.center = CGPointMake(_dragX.value, _dragY.value);
        // Host clamps are authoritative when rotation/shown geometry changes.
        if (fabs(pet.center.x - _dragX.value) > .1) { _dragX.value = pet.center.x; _dragX.velocity = 0.; }
        if (fabs(pet.center.y - _dragY.value) > .1) { _dragY.value = pet.center.y; _dragY.velocity = 0.; }
    }
    [self advanceActions:now];
    BOOL reduce = UIAccessibilityIsReduceMotionEnabled();
    BOOL dance = !_rhythmFollowing && _musicPlaying && !blocked && !_dragging && !_flying && _state == 8 && !_recoveryStage && now >= _landUntil && now >= _shakeUntil && !reduce;
    MSPetMusicCue cue = MSPetMusicCueAt(dance ? self.musicPosition : -1.);
    _musicAmplitude = MSPetMusicAmplitude(_musicAmplitude, dance ? 1. : 0., dt);
    double angle = blocked || reduce ? 0. : MSPetFiniteClamp(_tilt, -.22, .22);
    double x = blocked || reduce ? 0. : MSPetFiniteClamp(_sway, -5., 5.);
    double y = 0., sx = 1., sy = 1.;
    if (_dragging && !reduce) {
        angle = MSPetFiniteClamp(-_dragX.velocity / 3000., -.18, .18);
        // A stable grab pivot, not repeated mirroring every direction change.
        y = fmin(3., fabs(_dragY.velocity) / 650.);
        sy = 1. + fmin(.035, hypot(_dragX.velocity, _dragY.velocity) / 40000.);
    } else if (_flying && !blocked && !reduce) {
        angle += _flightAngle; sx += .07 * _impact; sy -= .09 * _impact;
    } else if (_recoveryStage && !blocked && !reduce) {
        // Do not bend, flatten or rotate actual land artwork a second time.
        BOOL hasLandArt = _ownsSprite && _displayedFrame != NSNotFound && [_role isEqualToString:@"land"];
        MSPetLandingPresentation recovery = MSPetLandingPresentationAt(now - _recoveryBegan);
        angle = hasLandArt ? 0. : recovery.angle;
        x = 0.;
    } else if (now < _landUntil && !blocked && !reduce) {
        double t = MSPetFiniteClamp((now - _landBegan) / .5, 0., 1.);
        double rebound = .018 + .017 * _landImpact;
        // A small whole-body rebound distinguishes a gentle set-down without flattening the sprite.
        y -= pet.bounds.size.height * rebound * sin(M_PI * t);
        angle += .035 * sin(M_PI * t);
    } else if (now < _shakeUntil && !blocked && !reduce) {
        double elapsed = fmax(0., now - _shakeBegan);
        angle += _shakeDirection * (.06 + .09 * _shakeStrength) * sin(elapsed * 8.) * exp(-elapsed * 4.);
    }
    if (dance) {
        double position = self.musicPosition;
        if (_musicEvidenceBudget && cue.cue != _lastMusicCue) {
            --_musicEvidenceBudget; _lastMusicCue = cue.cue;
            NSString *source = [NSBundle.mainBundle.bundleIdentifier isEqualToString:@"com.apple.springboard"] ? @"plugin" : @"app";
            MSDiagEvent(@"pet", @"state", @"ok", @{@"source":source, @"reason":@"pose_selected", @"value":@(80 + cue.cue)});
        }
        MSPetMusicPresentation sway = MSPetMusicPresentationAt(position);
        // No x translation, walk/jump pose, scale squash, or host-center write.
        angle = _musicAmplitude * sway.angle;
        x = 0.; y = pet.bounds.size.height * _musicAmplitude * sway.bob;
        sx = 1.; sy = 1.;
    }
    // Sample-and-decay only: phase is supplied by a fresh producer frame.
    // No musicPosition/time oscillator, travel, scale, or host geometry writes.
    BOOL rhythm = _rhythmFollowing && _musicPlaying && !blocked && !reduce &&
        !_dragging && !_flying && !_recoveryStage && _state == 8 &&
        now >= _landUntil && now >= _shakeUntil && now >= _rhythmAt && now - _rhythmAt <= .40;
    if (rhythm) {
        double envelope = exp(-10. * (now - _rhythmAt));
        angle = .055 * _rhythmPulse * envelope;
        x = 0.; y = -pet.bounds.size.height * .014 * _rhythmStrength * _rhythmPulse * envelope;
        sx = 1.; sy = 1.;
    }
    if (_rhythmFollowing && (!rhythm || now - _rhythmAt > .40)) {
        _rhythmStrength = _rhythmPulse = 0.;
    }
    MSPetLandingPresentation recoveryMark = MSPetLandingPresentationAt(now - _recoveryBegan);
    BOOL showDizzy = _recoveryStage && !blocked && !reduce && !_dragging && !_flying &&
        !(_ownsSprite && _displayedFrame != NSNotFound && [_role isEqualToString:@"land"]) && recoveryMark.dizzy > .01;
    if (showDizzy) {
        if (!_dizzyStars) {
            _dizzyStars = [CAShapeLayer layer];
            _dizzyStars.fillColor = UIColor.systemYellowColor.CGColor;
            _dizzyStars.strokeColor = UIColor.labelColor.CGColor;
            _dizzyStars.lineWidth = .5;
            [_sprite addSublayer:_dizzyStars]; // Follows the transformed sprite; no view/hit target.
        }
        UIBezierPath *stars = [UIBezierPath bezierPath];
        double orbit = (now - _recoveryBegan) * 6.;
        for (int i = 0; i < 3; i++) {
            double phase = orbit + i * 2. * M_PI / 3.;
            CGPoint center = CGPointMake(pet.bounds.size.width * (.5 + .24 * cos(phase)),
                                        pet.bounds.size.height * (.15 + .070 * sin(phase)));
            CGFloat radius = MIN(pet.bounds.size.width, pet.bounds.size.height) * .045;
            for (int point = 0; point < 8; point++) {
                double a = point * M_PI / 4. - M_PI_2;
                CGFloat r = radius * (point % 2 ? .34 : 1.);
                CGPoint p = CGPointMake(center.x + r * cos(a), center.y + r * sin(a));
                if (point == 0) [stars moveToPoint:p]; else [stars addLineToPoint:p];
            }
            [stars closePath];
        }
        [CATransaction begin]; [CATransaction setDisableActions:YES];
        _dizzyStars.frame = pet.bounds; _dizzyStars.path = stars.CGPath;
        _dizzyStars.opacity = recoveryMark.dizzy; _dizzyStars.hidden = NO;
        [CATransaction commit];
    } else _dizzyStars.hidden = YES;
    // Owner/accessibility gates retire residual motion in this very tick.
    // A drag keeps its center owner, but cannot smuggle tilt through busy.
    if (blocked || reduce) { angle = 0.; x = 0.; y = 0.; sx = 1.; sy = 1.;
        _angle = (MSPetDamped){0,0}; _offsetX = (MSPetDamped){0,0}; _offsetY = (MSPetDamped){0,0};
        _scaleX = (MSPetDamped){1,0}; _scaleY = (MSPetDamped){1,0}; _musicAmplitude = 0.;
    }
    MSPetDampedStep(&_angle, angle, dt, 20.);
    MSPetDampedStep(&_offsetX, x, dt, 22.); MSPetDampedStep(&_offsetY, y, dt, 22.);
    MSPetDampedStep(&_scaleX, sx, dt, 25.); MSPetDampedStep(&_scaleY, sy, dt, 25.);
    _visualOffset = CGPointMake(_offsetX.value, _offsetY.value);
    CGPoint targetPivot = _dragging ? CGPointMake((_grabX-.5)*pet.bounds.size.width, (_grabY-.5)*pet.bounds.size.height)
                                   : CGPointMake(0, pet.bounds.size.height * .40);
    MSPetDampedStep(&_pivotX, targetPivot.x, dt, 22.);
    MSPetDampedStep(&_pivotY, targetPivot.y, dt, 22.);
    CGPoint pivot = CGPointMake(_pivotX.value, _pivotY.value);
    CGAffineTransform transform = CGAffineTransformMakeTranslation(_visualOffset.x + pivot.x, _visualOffset.y + pivot.y);
    transform = CGAffineTransformRotate(transform, _angle.value);
    transform = CGAffineTransformScale(transform, _scaleX.value, _scaleY.value);
    transform = CGAffineTransformTranslate(transform, -pivot.x, -pivot.y);
    UIView *viewport = pet.superview;
    if (viewport && viewport.bounds.size.width > 0 && viewport.bounds.size.height > 0) {
        MSVisualTransform fitted = MSPetFitVisualTransform(
            (MSRect){viewport.bounds.origin.x, viewport.bounds.origin.y,
                     viewport.bounds.size.width, viewport.bounds.size.height},
            (MSPoint){pet.center.x, pet.center.y},
            (MSSize){pet.bounds.size.width, pet.bounds.size.height},
            (MSVisualTransform){transform.a, transform.b, transform.c, transform.d, transform.tx, transform.ty});
        _visualOffset.x += fitted.tx - transform.tx;
        _visualOffset.y += fitted.ty - transform.ty;
        transform = CGAffineTransformMake(fitted.a, fitted.b, fitted.c, fitted.d, fitted.tx, fitted.ty);
    }
    if (!CGAffineTransformEqualToTransform(_sprite.affineTransform, transform)) {
        [CATransaction begin]; [CATransaction setDisableActions:YES]; _sprite.affineTransform = transform; [CATransaction commit];
    }
    [self placeLyricsBlocked:blocked];
}
- (NSString *)lyricsLine { return _lyricsLine; }
- (void)setLyricsLine:(NSString *)line {
    NSString *text = [line isKindOfClass:NSString.class] && line.length <= 240 ? line : nil;
    if ((_lyricsLine == text) || [_lyricsLine isEqualToString:text]) return;
    _lyricsLine = [text copy];
    if (!text.length) { [self recordLyricsVisible:NO reason:@"empty_line"]; _bubble.hidden = YES; }
    _bubbleSize = CGSizeZero;
}
- (void)recordLyricsVisible:(BOOL)visible reason:(NSString *)reason {
    BOOL text = _lyricsLine.length > 0;
    if (_lyricsReasonEvidence && _lyricsVisibleEvidence == visible && _lyricsHadTextEvidence == text &&
        [_lyricsReasonEvidence isEqualToString:reason]) return;
    _lyricsVisibleEvidence = visible; _lyricsHadTextEvidence = text; _lyricsReasonEvidence = [reason copy];
    NSString *source = [NSBundle.mainBundle.bundleIdentifier isEqualToString:@"com.apple.springboard"] ? @"plugin" : @"app";
    MSDiagEvent(@"music", @"display", visible ? @"ok" : @"skipped", @{@"source": source,
        @"visible": @((BOOL)visible), @"present": @((BOOL)text), @"reason": reason});
}
- (void)placeLyricsBlocked:(BOOL)blocked {
    MiniSightPetView *pet = _pet;
    UIView *root = pet.superview;
    if (!_running || blocked || !_lyricsLine.length || !root || pet.window.hidden) {
        [self recordLyricsVisible:NO reason:blocked ? @"blocked" : (_lyricsLine.length ? @"hidden" : @"empty_line")];
        _bubble.hidden = YES; return;
    }
    if (!_bubble) {
        _bubble = [UIView new]; _bubble.userInteractionEnabled = NO;
        _bubble.accessibilityElementsHidden = YES;
        _bubble.backgroundColor = UIColor.secondarySystemBackgroundColor;
        _bubble.layer.cornerRadius = 9.;
        _label = [UILabel new]; _label.numberOfLines = 3; _label.textAlignment = NSTextAlignmentCenter;
        _label.font = [UIFont systemFontOfSize:13. weight:UIFontWeightMedium];
        _label.textColor = UIColor.labelColor; _label.lineBreakMode = NSLineBreakByTruncatingTail;
        [_bubble addSubview:_label];
        _tail = [CAShapeLayer layer]; [_bubble.layer addSublayer:_tail];
    }
    if (_bubble.superview != root) { [_bubble removeFromSuperview]; [root addSubview:_bubble]; }
    CGFloat available = MIN(240., root.bounds.size.width - root.safeAreaInsets.left - root.safeAreaInsets.right - 16.);
    if (available < 36.) { [self recordLyricsVisible:NO reason:@"lyrics_no_space"]; _bubble.hidden = YES; return; }
    if (_bubbleSize.width == 0 || ![_label.text isEqual:_lyricsLine] || fabs(_measurementWidth - available) > .5) {
        _measurementWidth = available; _label.text = _lyricsLine;
        CGSize size = [_label sizeThatFits:CGSizeMake(available - 20., 58.)];
        _bubbleSize = CGSizeMake(MIN(available, MAX(42., ceil(size.width) + 20.)), MIN(66., ceil(size.height) + 14.));
    }
    CGFloat x = pet.center.x + _visualOffset.x - _bubbleSize.width * .5;
    x = MAX(root.safeAreaInsets.left + 8., MIN(x, root.bounds.size.width - root.safeAreaInsets.right - 8. - _bubbleSize.width));
    CGFloat y = pet.center.y + _visualOffset.y - pet.bounds.size.height * .5 - 10. - _bubbleSize.height;
    y = MAX(root.safeAreaInsets.top + 4., y);
    if (y + _bubbleSize.height > pet.center.y - pet.bounds.size.height * .5 - 5.) {
        [self recordLyricsVisible:NO reason:@"lyrics_no_space"];
        _bubble.hidden = YES; return; // No room: never move the pet or cover its face just for lyrics.
    }
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    _bubble.frame = (CGRect){CGPointMake(x, y), _bubbleSize};
    _label.frame = CGRectInset(_bubble.bounds, 10., 7.);
    CGFloat tailX = MAX(12., MIN(_bubbleSize.width - 12., pet.center.x + _visualOffset.x - x));
    if (!CGSizeEqualToSize(_lastTailSize, _bubbleSize) || fabs(tailX - _lastTailX) > .5 || !_tail.path) {
        UIBezierPath *path = [UIBezierPath bezierPath];
        [path moveToPoint:CGPointMake(tailX - 4., _bubbleSize.height - 1.)];
        [path addLineToPoint:CGPointMake(tailX, _bubbleSize.height + 5.)];
        [path addLineToPoint:CGPointMake(tailX + 4., _bubbleSize.height - 1.)]; [path closePath];
        _tail.path = path.CGPath; _lastTailSize = _bubbleSize; _lastTailX = tailX;
    }
    _tail.fillColor = [UIColor.secondarySystemBackgroundColor resolvedColorWithTraitCollection:pet.traitCollection].CGColor;
    _bubble.hidden = NO;
    [self recordLyricsVisible:YES reason:@"lyrics_line"];
    [CATransaction commit];
}
- (void)invalidate {
    [self setRunning:NO]; ++_generation; ++_frameRequest; [_library purgeFrames];
    [_dizzyStars removeFromSuperlayer]; _dizzyStars = nil;
    [_bubble removeFromSuperview]; _bubble = nil; _label = nil; _tail = nil;
}
- (void)dealloc { [_link invalidate]; [_dizzyStars removeFromSuperlayer]; [_bubble removeFromSuperview]; }
@end
