#import "MSApprovalSummaryBridge.h"
#include "MiniSightApprovalSummaryCore.h"

@implementation MSApprovalSummaryBridge
+ (NSDictionary<NSString *, id> *)summaryForCommand:(NSString *)command {
    // UTF8String may contain NUL from JSON. Never silently classify a prefix.
    const char *bytes = command.UTF8String;
    NSUInteger length = [command lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
    BOOL valid = bytes && length <= MSA_INPUT_LIMIT && strlen(bytes) == length;
    MSApprovalSummary usage = MSApprovalDescribe(valid ? bytes : NULL);
    return @{
        @"title": [NSString stringWithUTF8String:usage.title],
        @"purpose": [NSString stringWithUTF8String:usage.purpose],
        @"risk": [NSString stringWithUTF8String:usage.risk],
        @"isWrite": @(usage.is_write != 0),
        @"unknown": @(usage.unknown != 0)
    };
}
@end
