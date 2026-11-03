#import "MiniSightAppRecorder.h"
#import "tools/recorder/MiniSightRecorderFile.h"
#import <ReplayKit/ReplayKit.h>
#import <AVFoundation/AVFoundation.h>
#import <sys/stat.h>
#import <fcntl.h>
#import <unistd.h>
#import <stdatomic.h>
#include <string.h>

@interface MiniSightAppRecorder ()
@property(nonatomic, readwrite, getter=isRecording) BOOL recording;
@property(nonatomic, copy) NSURL *temporaryURL;
@property(nonatomic, copy) NSURL *finalURL;
@property(nonatomic, strong) AVAssetWriter *writer;
@property(nonatomic, strong) AVAssetWriterInput *videoInput;
@property(nonatomic, strong) dispatch_queue_t writerQueue;
@property(nonatomic) BOOL startedSession;
@end

@implementation MiniSightAppRecorder

- (instancetype)init {
    if ((self = [super init])) {
        _writerQueue = dispatch_queue_create("com.openminis.minisight.app-recorder", DISPATCH_QUEUE_SERIAL);
    }
    return self;
}

- (void)emit:(NSString *)message {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.messageHandler) self.messageHandler(message);
    });
}

- (void)setRecordingState:(BOOL)recording {
    NSCAssert(NSThread.isMainThread, @"ReplayKit state belongs to the main thread");
    _recording = recording;
    if (self.stateHandler) self.stateHandler(recording);
}

- (void)start {
    NSCAssert(NSThread.isMainThread, @"ReplayKit start is main-thread owned");
    if (self.recording) return;
    RPScreenRecorder *recorder = RPScreenRecorder.sharedRecorder;
    if (!recorder.isAvailable) { [self emit:@"系统暂不允许开始屏幕录制。"]; return; }

    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *directory = [documents URLByAppendingPathComponent:@"MiniSight/recordings" isDirectory:YES];
    NSError *directoryError = nil;
    if (![NSFileManager.defaultManager createDirectoryAtURL:directory withIntermediateDirectories:YES attributes:nil error:&directoryError]) {
        [self emit:@"录屏目录创建失败。"];
        return;
    }

    NSString *stem = [NSString stringWithFormat:@"app-%@", NSUUID.UUID.UUIDString];
    self.temporaryURL = [directory URLByAppendingPathComponent:[stem stringByAppendingString:@".partial.mp4"]];
    self.finalURL = [directory URLByAppendingPathComponent:[stem stringByAppendingString:@".mp4"]];
    NSError *writerError = nil;
    self.writer = [[AVAssetWriter alloc] initWithURL:self.temporaryURL fileType:AVFileTypeMPEG4 error:&writerError];
    if (!self.writer) { [NSFileManager.defaultManager removeItemAtURL:self.temporaryURL error:nil]; self.temporaryURL = nil; self.finalURL = nil; [self emit:@"录屏文件初始化失败。"]; return; }
    self.startedSession = NO;
    [self setRecordingState:YES];

    __weak typeof(self) weakSelf = self;
    dispatch_queue_t queue = self.writerQueue;
    [recorder startCaptureWithHandler:^(CMSampleBufferRef sampleBuffer, RPSampleBufferType type, NSError *error) {
        if (error || !sampleBuffer) return;
        CFRetain(sampleBuffer);
        dispatch_async(queue, ^{
            MiniSightAppRecorder *strongSelf = weakSelf;
            if (strongSelf) [strongSelf appendSample:sampleBuffer type:type];
            CFRelease(sampleBuffer);
        });
    } completionHandler:^(NSError *error) {
        if (error) {
            dispatch_async(queue, ^{
                MiniSightAppRecorder *strongSelf = weakSelf;
                if (!strongSelf) return;
                [strongSelf cleanupOnWriterQueue];
                dispatch_async(dispatch_get_main_queue(), ^{
                    [strongSelf setRecordingState:NO];
                    [strongSelf emit:@"ReplayKit 启动录屏失败。"];
                });
            });
        }
    }];
}

- (void)appendSample:(CMSampleBufferRef)sample type:(RPSampleBufferType)type {
    if (!self.writer || self.writer.status == AVAssetWriterStatusFailed || !CMSampleBufferDataIsReady(sample)) return;
    CMTime pts = CMSampleBufferGetPresentationTimeStamp(sample);
    if (type == RPSampleBufferTypeVideo && !self.videoInput) {
        CVImageBufferRef image = CMSampleBufferGetImageBuffer(sample);
        if (!image) return;
        NSDictionary *videoSettings = @{ AVVideoCodecKey: AVVideoCodecTypeH264,
            AVVideoWidthKey: @(CVPixelBufferGetWidth(image)), AVVideoHeightKey: @(CVPixelBufferGetHeight(image)) };
        AVAssetWriterInput *video = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo outputSettings:videoSettings];
        video.expectsMediaDataInRealTime = YES;
        if (![self.writer canAddInput:video]) { [self failWriter]; return; }
        [self.writer addInput:video]; self.videoInput = video;

        if (![self.writer startWriting]) { [self failWriter]; return; }
        [self.writer startSessionAtSourceTime:pts];
        self.startedSession = YES;
    }
    if (!self.startedSession || self.writer.status != AVAssetWriterStatusWriting) return;
    if (type != RPSampleBufferTypeVideo) return;
    if (self.videoInput.readyForMoreMediaData && ![self.videoInput appendSampleBuffer:sample]) [self failWriter];
}

- (void)failWriter {
    if (self.writer.status == AVAssetWriterStatusWriting) [self.writer cancelWriting];
}

- (void)stopIfNeeded { if (self.recording) [self stop]; }

- (void)stop {
    NSCAssert(NSThread.isMainThread, @"ReplayKit stop is main-thread owned");
    if (!self.recording) return;
    [self setRecordingState:NO];
    __weak typeof(self) weakSelf = self;
    dispatch_queue_t queue = self.writerQueue;
    [RPScreenRecorder.sharedRecorder stopCaptureWithHandler:^(NSError *captureError) {
        dispatch_async(queue, ^{
            MiniSightAppRecorder *strongSelf = weakSelf;
            if (!strongSelf) return;
            AVAssetWriter *writer = strongSelf.writer;
            if (captureError || !writer || !strongSelf.startedSession || writer.status != AVAssetWriterStatusWriting) {
                [strongSelf cleanupOnWriterQueue];
                [strongSelf emit:@"录屏停止或编码失败，没有保留无效文件。"];
                return;
            }
            [strongSelf.videoInput markAsFinished];
            [writer finishWritingWithCompletionHandler:^{
                MiniSightAppRecorder *finishedSelf = weakSelf;
                if (!finishedSelf) return;
                dispatch_async(queue, ^{ [finishedSelf verifyAndPublish]; });
            }];
        });
    }];
}

- (void)verifyAndPublish {
    AVAssetWriter *writer = self.writer;
    if (writer.status != AVAssetWriterStatusCompleted) {
        [self cleanupOnWriterQueue]; [self emit:@"录屏编码未完成，未发布文件。"]; return;
    }
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:self.temporaryURL options:nil];
    [asset loadValuesAsynchronouslyForKeys:@[@"duration", @"tracks", @"playable"] completionHandler:^{
        dispatch_async(self.writerQueue, ^{
            BOOL valid = YES;
            for (NSString *key in @[@"duration", @"tracks", @"playable"])
                valid &= [asset statusOfValueForKey:key error:nil] == AVKeyValueStatusLoaded;
            CMTime duration = asset.duration;
            valid &= asset.playable && [asset tracksWithMediaType:AVMediaTypeVideo].count > 0 &&
                     CMTIME_IS_NUMERIC(duration) && CMTimeGetSeconds(duration) > 0;
            if (!valid) {
                [self cleanupOnWriterQueue]; [self emit:@"录屏文件校验失败，未发布。"]; return;
            }
            int dir = open(self.finalURL.URLByDeletingLastPathComponent.fileSystemRepresentation,
                           O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (dir < 0) { [self cleanupOnWriterQueue]; [self emit:@"录屏目录打开失败。"]; return; }
            atomic_bool cancelled; atomic_init(&cancelled, false);
            bool published = false; int publishError = 0;
            struct stat st;
            int fd = openat(dir, self.temporaryURL.lastPathComponent.fileSystemRepresentation,
                            O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
            uint64_t bytes = (fd >= 0 && fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_size > 0)
                ? (uint64_t)st.st_size : 0;
            if (fd >= 0) close(fd);
            BOOL ok = bytes >= 1024 && MSRFilePublishWithError(
                dir, self.temporaryURL.lastPathComponent.fileSystemRepresentation,
                self.finalURL.lastPathComponent.fileSystemRepresentation, bytes,
                &cancelled, &published, &publishError);
            MSRFileCleanup(dir, self.temporaryURL.lastPathComponent.fileSystemRepresentation,
                self.finalURL.lastPathComponent.fileSystemRepresentation, published && !ok);
            if (!ok) {
                [self cleanupOnWriterQueue];
                [self emit:[NSString stringWithFormat:@"录屏文件发布失败（errno %d）。", publishError]];
                return;
            }
            [self finishPublishedFile];
            [self emit:@"录屏已保存到 MiniSight/recordings。"];
        });
    }];
}

- (void)cleanupOnWriterQueue {
    if (self.temporaryURL) [NSFileManager.defaultManager removeItemAtURL:self.temporaryURL error:nil];
    self.writer = nil; self.videoInput = nil;
    self.temporaryURL = nil; self.finalURL = nil; self.startedSession = NO;
}

- (void)finishPublishedFile {
    self.writer = nil;
    self.videoInput = nil;
    self.temporaryURL = nil;
    self.finalURL = nil;
    self.startedSession = NO;
}
@end
