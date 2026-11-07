#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

/// Typed view of the App-written runtime.json. Absent values keep 0.7 behavior
/// so an upgrade never silently changes gestures or size.
@interface MiniSightRuntimeConfig : NSObject
+ (instancetype)shared;
- (void)reloadWithContainer:(nullable NSString *)container;
- (void)reloadWithContainer:(nullable NSString *)container preferences:(nullable NSDictionary<NSString *, id> *)preferences;
@property (nonatomic, readonly) BOOL valid;
@property (nonatomic, readonly) NSInteger activity;      // 0 lively 1 quiet 2 off
@property (nonatomic, readonly) double activityInterval; // seconds between roams
@property (nonatomic, readonly) NSInteger frameLimit;    // 0 auto 1*30 2*60 3*120
@property (nonatomic, readonly) BOOL dragResponse;
@property (nonatomic, readonly) BOOL interaction;
@property (nonatomic, readonly) BOOL sound;
@property (nonatomic, readonly) double bottomGap;
@property (nonatomic, readonly, copy) NSString *tint;
@property (nonatomic, readonly, copy) NSString *costume;
@property (nonatomic, readonly) BOOL quick;
@property (nonatomic, readonly) double bubbleScale;
@property (nonatomic, readonly) double textScale;
@property (nonatomic, readonly) double dwell;
@property (nonatomic, readonly) NSInteger darkMode; // 0 system 1 light 2 dark
@property (nonatomic, readonly) BOOL proactive;
@property (nonatomic, readonly) double proactiveInterval;
@property (nonatomic, readonly) NSString *returnKey;
@property (nonatomic, readonly) BOOL voiceReply;
@property (nonatomic, readonly) NSString *snore;
@property (nonatomic, readonly) NSString *quickPosition;
@property (nonatomic, readonly) NSArray<NSString *> *quickOrder;
@property (nonatomic, readonly) NSDictionary<NSString *, NSString *> *quickLines;
@property (nonatomic, readonly) NSString *singleTap, *doubleTap, *longPress;
@property (nonatomic, readonly) NSString *revision;
@property (nonatomic, readonly) BOOL aiAdjust;
@property (nonatomic, readonly) NSString *aiPermissions;
@property (nonatomic, readonly) NSString *persona;
@property (nonatomic, readonly) NSString *supplier;
@property (nonatomic, readonly) double gravityStrength;
@property (nonatomic, readonly) BOOL gravityShake;
@property (nonatomic, readonly) NSString *downloadSource;
@property (nonatomic, readonly) NSString *nickname;
@property (nonatomic, readonly) NSArray<NSString *> *adjustments;
@end

NS_ASSUME_NONNULL_END
