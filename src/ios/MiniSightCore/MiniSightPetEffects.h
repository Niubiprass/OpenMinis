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
/// Selects existing sleep/wake action roles for a non-resident landing recovery.
/// 0 clears; 1 falls, 2 wobbles, 3 sits, 4 rises.
- (void)setLandingRecoveryStage:(NSInteger)stage;
- (void)beginDragAt:(CGPoint)localPoint;
- (void)dragTo:(CGPoint)center;
- (CGPoint)endDragCancelled:(BOOL)cancelled;
- (void)shakeDirection:(CGFloat)direction strength:(CGFloat)strength;
- (void)land;
/// Returns the chosen clip's finite duration; zero means use the legacy action.
- (NSTimeInterval)performIdleAction;
@end
NS_ASSUME_NONNULL_END
