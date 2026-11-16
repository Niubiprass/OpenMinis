#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
@class MiniSightPetView;
/// Owns only sprite presentation. Host geometry/chat never rotate or squash.
@interface MiniSightPetEffects : NSObject
- (instancetype)initWithPet:(MiniSightPetView *)pet layer:(CALayer *)layer;
@property (nonatomic, copy, nullable) NSString *actionManifestPath;
@property (nonatomic, copy, nullable) NSString *lyricsLine;
@property (nonatomic) BOOL musicPlaying;
@property (nonatomic) BOOL busy;
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
- (void)beginDragAt:(CGPoint)localPoint;
- (void)dragTo:(CGPoint)center;
- (CGPoint)endDragCancelled:(BOOL)cancelled;
- (void)shakeDirection:(CGFloat)direction strength:(CGFloat)strength;
- (void)land;
/// Returns the chosen clip's finite duration; zero means use the legacy action.
- (NSTimeInterval)performIdleAction;
@end
NS_ASSUME_NONNULL_END
