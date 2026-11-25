#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
@class MiniSightPetView;
/// Owns only sprite presentation. Host geometry/chat never rotate or squash.
@interface MiniSightPetEffects : NSObject
- (instancetype)initWithPet:(MiniSightPetView *)pet layer:(CALayer *)layer;
@property (nonatomic, copy, nullable) NSString *actionManifestPath;
@property (nonatomic, copy, nullable) NSString *lyricsLine;
@property (nonatomic) BOOL musicPlaying;
@property (nonatomic) NSTimeInterval musicPosition;
@property (nonatomic) BOOL busy;
@property (nonatomic, readonly) BOOL presentationBlocked;
@property (nonatomic) NSInteger preferredFPS;
@property (nonatomic, readonly) BOOL hasActions;
@property (nonatomic, readonly) BOOL hasDailyActions;
@property (nonatomic, readonly) BOOL isDragging;
@property (nonatomic, readonly) BOOL autonomyHeld;
@property (nonatomic, readonly) CGPoint visualOffset;
- (void)setRunning:(BOOL)running;
- (void)invalidate;
- (void)setLegacyState:(NSInteger)state waking:(BOOL)waking;
- (void)setTilt:(CGFloat)angle sway:(CGFloat)sway;
- (void)setFlightAngle:(CGFloat)angle squash:(CGFloat)squash active:(BOOL)active;
/// Records the solver's downward speed immediately before a floor hit.
/// This is separate from visual squash and drag impulse state.
- (void)setFloorImpactVelocity:(CGFloat)velocity;
/// Uses an explicit land clip continuously when supplied; otherwise a neutral
/// sprite with a bounded presentation fallback. These are not new art frames.
/// 0 clears; 1 topples, 2 pauses, 3 collects, 4 returns upright.
- (void)setLandingRecoveryStage:(NSInteger)stage;
/// Keeps the host from cutting a real land clip off at the fallback deadline.
@property (nonatomic, readonly) BOOL landingRecoveryHeld;
- (void)beginDragAt:(CGPoint)localPoint;
- (void)dragTo:(CGPoint)center;
- (CGPoint)endDragCancelled:(BOOL)cancelled;
- (void)shakeDirection:(CGFloat)direction strength:(CGFloat)strength;
- (void)land;
/// Returns the chosen clip's finite duration; zero means use the legacy action.
- (NSTimeInterval)performIdleAction;
/// Selects a non-moving, non-music daily-life clip from idleAlt. Zero means unavailable.
- (NSTimeInterval)performDailyAction;
@end
NS_ASSUME_NONNULL_END
