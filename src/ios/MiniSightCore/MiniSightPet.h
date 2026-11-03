//
//  MiniSightPet.h
//  MiniSight
//
//  Petdex-style animated pet. A 9-row sprite sheet: row 0 idle, 1 run-right,
//  2 run-left, 3 waving, 4 jumping, 5 failed, 6 waiting, 7 running, 8 review.
//  Frame counts/timings follow crafter-station/petdex (MIT).
//

#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

@interface MiniSightPetView : UIImageView

/// Main-thread API, like UIView. sprite is an already decoded/downsampled,
/// upright 9-row / 8-column atlas; preparation belongs to the host, off-main.
- (instancetype)initWithSprite:(UIImage *)sprite displaySize:(CGSize)displaySize;

/// Record explicit playback intent. Starting does not clear suspension.
- (void)startPlaying;
/// Clear intent and invalidate every clock/motion; unsuspending cannot restart it.
- (void)stopPlaying;
- (void)setSuspended:(BOOL)suspended;

/// Main-thread normalized roll input in the range -1...1 (-1 left, +1 right).
/// The visual tilt is finite and clamped; this never changes center, bounds, or
/// centerBounds.
@property (nonatomic) CGFloat gravityRoll;
/// Whether the host has enabled the gravity visual treatment. Disabled pets
/// always use the identity transform and do not retain an impulse animation.
@property (nonatomic) BOOL gravityEnabled;
/// The conservative, unrotated layout size needed to keep the pet's maximum
/// tilt/fall envelope on-screen. This is stable while gravityEnabled is set and
/// does not change the view's bounds.
@property (nonatomic, readonly) CGSize gravitySafeSize;
/// Visual centre in the parent coordinates, including the bounded sway.
/// The bubble tail follows this point; UIView geometry remains untransformed.
@property (nonatomic, readonly) CGPoint speechAnchor;
/// Apply one transient fall/rebound. direction is normalized to -1...1 and
/// strength is normalized to 0...1. The impulse uses a display link only while
/// it is settling and is discarded when playback is stopped/hidden.
- (void)triggerGravityImpulseWithDirection:(CGFloat)direction strength:(CGFloat)strength;

/// Feasible CENTER range in the fixed overlay parent's coordinates, not a body
/// rectangle. The host has already reserved safe-area and bubble headroom.
/// Assign before playing; a zero width/height is a valid collapsed range.
@property (nonatomic) CGRect centerBounds;
/// Main-thread, changed geometry only (including the final motion point/clamps).
@property (nonatomic, copy, nullable) void (^onGeometryChanged)(void);

/// Only changes the delay between roaming actions, not sprite/display-link FPS.
@property (nonatomic) BOOL activityActive;
/// Host-owned gesture configuration; this view creates NO gesture recognizers.
@property (nonatomic) BOOL longPressEnabled;
/// Both flags freeze/cancel roaming at its actual position, not playback intent.
/// The host brackets drag/press with interactionActive = YES / NO.
@property (nonatomic) BOOL roamingPaused;
@property (nonatomic) BOOL interactionActive;
/// Low power: longer resident-idle gaps only; sprite/movement/gravity stay fluid.
@property (nonatomic) BOOL reducedWork;

/// Compatibility callback storage only. The host owns/invokes the unified press.
@property (nonatomic, copy, nullable) void (^onLongPress)(void);

@end

NS_ASSUME_NONNULL_END
