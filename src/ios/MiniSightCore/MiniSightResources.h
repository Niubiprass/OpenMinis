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
/// Bounded shared 0/1 readback, including its opaque file identity. No scan.
+ (NSDictionary<NSString *, id> *)shownEvidenceWithContainer:(nullable NSString *)container
    NS_SWIFT_NAME(shownEvidence(container:));
/// Synchronous settings transaction: atomic write -> exact readback. Notify only afterwards.
+ (BOOL)saveShown:(BOOL)shown container:(nullable NSString *)container
    NS_SWIFT_NAME(saveShown(_:container:));
+ (void)writeShown:(BOOL)shown container:(NSString *)container;
/// Main-thread feedback; only verified writes emit the settings notification.
+ (void)writeShown:(BOOL)shown container:(nullable NSString *)container completion:(nullable void (^)(BOOL verified))completion;
/// Opaque previous file identity distinguishes an old ON from a new atomic enable.
+ (void)writeShown:(BOOL)shown container:(nullable NSString *)container
    verifiedReadback:(void (^ _Nullable)(BOOL verified, NSString *previousIdentity))completion;
+ (void)releaseCachedAtlas;
@end
NS_ASSUME_NONNULL_END
