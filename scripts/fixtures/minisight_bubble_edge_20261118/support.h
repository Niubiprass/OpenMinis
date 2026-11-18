// macOS Foundation/CoreGraphics host surface only; no UIKit/device claim.
// Frame/bounds behavior follows the existing effects-runtime fixture.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <QuartzCore/QuartzCore.h>
#import <dispatch/dispatch.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { CGFloat top, left, bottom, right; } UIEdgeInsets;
#define UIScrollViewContentInsetAdjustmentNever 2
#define UIGestureRecognizerStateEnded 3
#define MiniSightPetMotionLockApproval 1
@class UIColor, UIFont, UITapGestureRecognizer;
@interface UIView : NSObject
@property(nonatomic) CGRect frame;
@property(nonatomic) CGRect bounds;
@property(nonatomic) CGPoint center;
@property(nonatomic) CGFloat alpha;
@property(nonatomic) BOOL hidden, userInteractionEnabled;
@property(nonatomic) UIEdgeInsets safeAreaInsets;
@property(nonatomic, strong) UIColor *backgroundColor;
@property(nonatomic, readonly) CALayer *layer;
@property(nonatomic, weak, readonly) UIView *superview;
- (void)addSubview:(UIView *)view;
- (void)removeFromSuperview;
- (void)addGestureRecognizer:(id)recognizer;
- (void)bringSubviewToFront:(UIView *)view;
- (void)setNeedsLayout;
- (void)layoutIfNeeded;
@end
@interface UIViewController : NSObject
@property(nonatomic, strong) UIView *view;
@end
@interface UIWindow : UIView
@property(nonatomic, strong) UIViewController *rootViewController;
@end
@interface FixturePet : UIView
@property(nonatomic) BOOL gravityEnabled, lyricsSuppressed, motionLocked;
@property(nonatomic) CGSize gravitySafeSize;
- (void)setMotionLocked:(BOOL)locked forReason:(NSInteger)reason;
@end
@interface UIScrollView : UIView
@property(nonatomic) CGSize contentSize;
@property(nonatomic) CGPoint contentOffset;
@property(nonatomic) BOOL scrollEnabled, showsHorizontalScrollIndicator, showsVerticalScrollIndicator, alwaysBounceVertical;
@property(nonatomic) NSInteger contentInsetAdjustmentBehavior;
@end
@interface UILabel : UIView
@property(nonatomic, copy) NSString *text;
@property(nonatomic, strong) UIFont *font;
@property(nonatomic, strong) UIColor *textColor;
@property(nonatomic) NSInteger numberOfLines;
- (CGSize)sizeThatFits:(CGSize)size;
@end
@interface UIFont : NSObject
@property(nonatomic) CGFloat lineHeight;
+ (instancetype)systemFontOfSize:(CGFloat)size;
@end
@interface UIColor : NSObject
@property(nonatomic, readonly) CGColorRef CGColor;
+ (instancetype)systemBackgroundColor;
+ (instancetype)separatorColor;
+ (instancetype)clearColor;
+ (instancetype)labelColor;
@end
@interface UIBezierPath : NSObject
@property(nonatomic, readonly) CGPathRef CGPath;
+ (instancetype)bezierPath;
- (void)moveToPoint:(CGPoint)point;
- (void)addQuadCurveToPoint:(CGPoint)point controlPoint:(CGPoint)control;
- (void)closePath;
@end
@interface UIStackView : UIView
@property(nonatomic) NSUInteger layoutCalls;
@end
@interface UIButton : UIView @end
@interface UITapGestureRecognizer : NSObject
@property(nonatomic) NSInteger state;
- (instancetype)initWithTarget:(id)target action:(SEL)action;
@end
@interface MiniSightChatPanel : NSObject
@property(nonatomic, getter=isVisible) BOOL visible;
+ (instancetype)existingPanel;
@end
