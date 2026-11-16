// macOS native-test delivery shim ONLY. Production iOS typecheck uses real UIKit.
// No parser, filesystem, ImageIO, crop, cache or scheduler behavior is mocked.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
typedef NS_ENUM(NSInteger, UIImageOrientation) { UIImageOrientationUp = 0 };
@interface UIImage : NSObject
@property(nonatomic, readonly) CGImageRef CGImage;
+ (instancetype)imageWithCGImage:(CGImageRef)image scale:(CGFloat)scale orientation:(UIImageOrientation)orientation;
@end
