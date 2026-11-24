#import <Foundation/Foundation.h>
#import "MiniSightRhythmFrame.h"
@class MiniSightPetView;
NS_ASSUME_NONNULL_BEGIN
/// Never captures audio itself. Optional loopback-only feature receiver.
/// Default local candidate has live transport compiled OFF. Enabling it or
/// installing its mediaserverd dependency requires separate user approval.
@interface MiniSightRhythmClient : NSObject
@property(nonatomic,copy,nullable) void (^updateHandler)(MSRhythmFrame frame,double receivedAt);
@property(nonatomic,copy,nullable) void (^clearHandler)(void);
@property(nonatomic,copy,nullable) void (^sessionHandler)(uint64_t fencedOwnerToken);
- (void)configureEnabled:(BOOL)enabled;
- (void)stop;
@end
/// Main-thread host wiring; token is the current playback generation/identity,
/// not a platform song ID. Binding/lifetime is scoped to this exact pet view.
FOUNDATION_EXPORT void MiniSightRhythmConfigurePet(MiniSightPetView * _Nullable pet, BOOL enabled, NSUInteger token);
FOUNDATION_EXPORT BOOL MiniSightRhythmLiveTransportCompiled(void);
NS_ASSUME_NONNULL_END
