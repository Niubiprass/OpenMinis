#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Immutable, line-level LRC marker. Empty text explicitly clears the bubble.
@interface MiniSightLyricLine : NSObject
@property(nonatomic, readonly) NSTimeInterval time;
@property(nonatomic, copy, readonly) NSString *text;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

@interface MiniSightLyricsTimeline : NSObject
@property(nonatomic, copy, readonly) NSArray<MiniSightLyricLine *> *lines;
/// Strict timed LRC; nil for malformed/untimed/oversized input. Duration: 1...3600s.
/// Global offset is milliseconds (last valid offset wins); negative times clamp to 0.
+ (nullable instancetype)timelineWithLRC:(NSString *)lrc duration:(NSTimeInterval)duration;
/// Nil before first marker, at a blank, after 12s without a new line, or at track end.
- (nullable NSString *)lineAtTime:(NSTimeInterval)time;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

@interface MiniSightLyricsTrack : NSObject
@property(nonatomic, copy, readonly) NSString *title;
@property(nonatomic, copy, readonly) NSString *artist;
@property(nonatomic, readonly) NSTimeInterval duration;
@property(nonatomic, copy, readonly) NSString *cacheKey;
/// NFC, POSIX lowercase and whitespace normalization only; no fuzzy/feature stripping.
- (nullable instancetype)initWithTitle:(NSString *)title
                               artist:(NSString *)artist
                             duration:(NSTimeInterval)duration NS_DESIGNATED_INITIALIZER;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

typedef void (^MiniSightLyricsCompletion)(MiniSightLyricsTimeline * _Nullable timeline);

typedef void (^MiniSightLyricsResult)(MiniSightLyricsTimeline * _Nullable timeline, NSString *reason);

@interface MiniSightLyricsClient : NSObject
/// Fixed-vocabulary result, never server text, URL, metadata, or lyric content.
- (void)fetchTrack:(MiniSightLyricsTrack *)track result:(MiniSightLyricsResult)completion;
/// Any queue: generation invalidation is immediate; I/O state/completions use MAIN.
/// A new fetch cancels the previous fetch, including any queued completion.
/// No automatic retry. A cache miss during cooldown completes nil; no UI text/logging.
- (void)fetchTrack:(MiniSightLyricsTrack *)track completion:(MiniSightLyricsCompletion)completion;
/// Suppresses callbacks, including already queued cache/network deliveries.
- (void)cancel;

/// Test seam. Default init uses the same ephemeral configuration with no overrides.
/// Tests MUST supply a catch-all NSURLProtocol so no synthetic request escapes.
- (instancetype)initWithProtocolClasses:(NSArray<Class> *)protocolClasses;
/// Pure production response evaluator (no request, state, cache or side effects).
+ (nullable MiniSightLyricsTimeline *)timelineForResponseData:(NSData *)data
                                                  response:(NSHTTPURLResponse *)response
                                                     track:(MiniSightLyricsTrack *)track;
/// Pure 429/503 policy, no jitter: max(Retry-After, capped 30...300s backoff).
/// HTTP-date supported; excessive numeric values suppress further requests, not shorten waits.
+ (NSTimeInterval)retryDelayForResponse:(NSHTTPURLResponse *)response
                                  now:(NSDate *)now
                              attempt:(NSUInteger)attempt;
@end

NS_ASSUME_NONNULL_END
