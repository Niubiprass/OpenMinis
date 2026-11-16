#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
@interface MiniSightResources : NSObject
+ (NSDictionary<NSString *, id> *)shownEvidenceWithContainer:(nullable NSString *)container NS_SWIFT_NAME(shownEvidence(container:));
+ (BOOL)saveShown:(BOOL)shown container:(nullable NSString *)container NS_SWIFT_NAME(saveShown(_:container:));
@end
NS_ASSUME_NONNULL_END
