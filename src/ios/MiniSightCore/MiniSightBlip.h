#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
/// One short generated click; no bundled asset, no audio session takeover.
@interface MiniSightBlip : NSObject
+ (void)playIfEnabled:(BOOL)enabled;
@end
NS_ASSUME_NONNULL_END
