#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN
// All scanning, property-list I/O and atlas decoding runs on one utility queue.
// Completion is main-thread. No renderer, gesture or display-link calls this.
@interface MiniSightResources : NSObject
/// A complete allowlisted merge: plist fallback, runtime snapshot wins. The
/// independently written shown file remains authoritative for visibility.
+ (NSDictionary<NSString *, id> *)mergedPreferencesWithContainer:(nullable NSString *)container
                                                  preferences:(nullable NSDictionary<NSString *, id> *)preferences;
/// Raw minisight.* keys -> legacy runtime.json aliases (exactly 45).
+ (NSDictionary<NSString *, NSString *> *)runtimeFields;
+ (void)refresh:(void (^)(NSString * _Nullable container, NSDictionary *preferences,
                         BOOL shown, UIImage * _Nullable atlas))completion;
+ (void)refreshPreferences:(void (^)(NSString * _Nullable container, NSDictionary *preferences))completion;
+ (void)writeShown:(BOOL)shown container:(NSString *)container;
+ (void)releaseCachedAtlas;
@end
NS_ASSUME_NONNULL_END
