#ifndef MINISIGHT_EFFECTS_RUNTIME_FIXTURE_SUPPORT_H
#define MINISIGHT_EFFECTS_RUNTIME_FIXTURE_SUPPORT_H
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <QuartzCore/QuartzCore.h>
#import <dispatch/dispatch.h>
#include <math.h>
#include <stdlib.h>
#include <stdbool.h>

// macOS host-only UIKit surface. Real QuartzCore/CG objects back sprite contents.
// Never substitute the production PetEffects, Liveliness or lyrics implementation.
typedef struct { CGFloat top, left, bottom, right; } UIEdgeInsets;
#define NSTextAlignmentCenter 1
#define NSLineBreakByTruncatingTail 4
#define UIFontWeightMedium ((CGFloat).23)
#define UIFontWeightBold ((CGFloat).4)
#define UIViewContentModeScaleAspectFit 1
#define UIWindowDidBecomeHiddenNotification @"fixture.window.hidden"
#define UIWindowDidBecomeVisibleNotification @"fixture.window.visible"
@class UIColor, UIFont, UIWindow;

@interface UIImage : NSObject
@property(nonatomic, readonly) CGImageRef CGImage;
@property(nonatomic, readonly) CGFloat scale;
+ (instancetype)imageWithCGImage:(CGImageRef)image;
@end
@interface UIView : NSObject
- (instancetype)initWithFrame:(CGRect)frame;
@property(nonatomic) NSInteger contentMode;
@property(nonatomic) BOOL isAccessibilityElement;
@property(nonatomic) CGRect frame;
@property(nonatomic) CGRect bounds;
@property(nonatomic) CGPoint center;
@property(nonatomic) CGFloat alpha;
@property(nonatomic) BOOL hidden;
@property(nonatomic) BOOL userInteractionEnabled;
@property(nonatomic) BOOL accessibilityElementsHidden;
@property(nonatomic) UIEdgeInsets safeAreaInsets;
@property(nonatomic, strong) UIColor *backgroundColor;
@property(nonatomic, readonly) CALayer *layer;
@property(nonatomic, weak, readonly) UIView *superview;
@property(nonatomic, readonly) UIWindow *window;
@property(nonatomic, readonly) id traitCollection;
- (void)addSubview:(UIView *)view;
- (void)removeFromSuperview;
@end
@interface UIWindow : UIView @end
@interface UIImageView : UIView
@property(nonatomic, strong) UIImage *image;
@end
@interface UILabel : UIView
@property(nonatomic, copy) NSString *text;
@property(nonatomic) NSInteger numberOfLines;
@property(nonatomic) NSInteger textAlignment;
@property(nonatomic) NSInteger lineBreakMode;
@property(nonatomic, strong) UIFont *font;
@property(nonatomic, strong) UIColor *textColor;
- (CGSize)sizeThatFits:(CGSize)size;
@end
@interface UIFont : NSObject
+ (instancetype)systemFontOfSize:(CGFloat)size weight:(CGFloat)weight;
@end
@interface UIColor : NSObject
@property(nonatomic, readonly) CGColorRef CGColor;
+ (instancetype)secondarySystemBackgroundColor;
+ (instancetype)labelColor;
+ (instancetype)systemBlueColor;
- (UIColor *)resolvedColorWithTraitCollection:(id)traits;
@end
@interface UIBezierPath : NSObject
@property(nonatomic, readonly) CGPathRef CGPath;
+ (instancetype)bezierPath;
- (void)moveToPoint:(CGPoint)point;
- (void)addLineToPoint:(CGPoint)point;
- (void)closePath;
@end

// Import QuartzCore before aliases: SDKs which expose CADisplayLink on macOS
// remain compatible. Fake links NEVER schedule a timer or a display callback.
@interface MSFixtureDisplayLink : NSObject
@property(nonatomic) NSInteger preferredFramesPerSecond;
@property(nonatomic, readonly) BOOL invalidated;
+ (instancetype)displayLinkWithTarget:(id)target selector:(SEL)selector;
- (void)addToRunLoop:(NSRunLoop *)loop forMode:(NSRunLoopMode)mode;
- (void)invalidate;
@end
CFTimeInterval MSFixtureClock(void);
BOOL UIAccessibilityIsReduceMotionEnabled(void);
#define CADisplayLink MSFixtureDisplayLink
#define CACurrentMediaTime MSFixtureClock

// Use the EXISTING production chat header guard, not an edit/import seam in .m.
// Only the visibility dependency is needed; no real panel/AI/voice code is loaded.
#define MINISIGHT_CHAT_PANEL_H 1
@interface MiniSightChatPanel : NSObject
@property(nonatomic, getter=isVisible) BOOL visible;
+ (instancetype)existingPanel;
+ (void)fixtureSetVisible:(BOOL)visible;
@end
#endif
