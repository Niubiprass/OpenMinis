#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
/// SpringBoard-only observer; never controls playback or records audio.
@interface MiniSightMusicMonitor : NSObject
+ (instancetype)shared;
/// Main-thread, fail-closed private lock-state query; missing/wrong ABI returns NO.
+ (BOOL)deviceIsUnlocked;
@property (nonatomic, copy, nullable) void (^updateHandler)(NSDictionary<NSString *, id> *snapshot);
@property (nonatomic, readonly, copy) NSDictionary<NSString *, id> *snapshot;
/// allowed describes actual presentation eligibility (including App-owned mode).
- (void)configureAllowed:(BOOL)allowed lyrics:(BOOL)lyrics motion:(BOOL)motion
              container:(nullable NSString *)container;
@end
NS_ASSUME_NONNULL_END
