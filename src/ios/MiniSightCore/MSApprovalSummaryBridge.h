#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
/// Display adapter only. It never executes input and never grants permission.
@interface MSApprovalSummaryBridge : NSObject
+ (NSDictionary<NSString *, id> *)summaryForCommand:(NSString *)command
    NS_SWIFT_NAME(summary(command:));
@end
NS_ASSUME_NONNULL_END
