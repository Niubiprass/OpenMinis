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
/// enabled MUST already include the independent music-motion setting and real
/// musicPlaying/scene activity. token stays stable for one playback generation;
/// never change it for metadata jitter or an ordinary position tick.
/// Pass NAN when real MediaRemote position evidence is missing. This API does
/// not treat interpolated musicPosition/default zero as a seek observation.
FOUNDATION_EXPORT void MiniSightRhythmConfigurePetWithPosition(MiniSightPetView * _Nullable pet, BOOL enabled, NSUInteger token, double measuredPosition);
FOUNDATION_EXPORT BOOL MiniSightRhythmLiveTransportCompiled(void);
NS_ASSUME_NONNULL_END
