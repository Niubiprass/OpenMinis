#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// App-owned ReplayKit capture. Files are written only inside Minis Documents;
/// success is reported only after the MP4 is validated and atomically published.
@interface MiniSightAppRecorder : NSObject
@property (nonatomic, readonly, getter=isRecording) BOOL recording;
@property (nonatomic, copy, nullable) void (^stateHandler)(BOOL recording);
@property (nonatomic, copy, nullable) void (^messageHandler)(NSString *message);
- (void)start;
- (void)stop;
- (void)stopIfNeeded;
@end

NS_ASSUME_NONNULL_END
