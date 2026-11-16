#import <Foundation/Foundation.h>
@class UIImage;

NS_ASSUME_NONNULL_BEGIN

/// Immutable metadata. IDs are data, never executable selectors or paths.
@interface MiniSightActionClip : NSObject
@property(nonatomic, copy, readonly) NSString *identifier;
@property(nonatomic, copy, readonly) NSString *role;
@property(nonatomic, copy, readonly) NSArray<NSNumber *> *durations;
@property(nonatomic, readonly) NSTimeInterval duration;
@property(nonatomic, readonly) NSUInteger frameCount;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

@interface MiniSightActionLibrary : NSObject
@property(nonatomic, copy, readonly) NSDictionary<NSString *, NSArray<MiniSightActionClip *> *> *roles;

/// Call all public methods on MAIN. All completions are asynchronous on MAIN.
/// Reads only local files; validates the complete manifest and source metadata,
/// then primes idle[0]/frame 0 before succeeding. Keep the old display on failure.
/// At most two manifest jobs are admitted process-wide; excess calls fail rather
/// than growing an unbounded I/O queue. Caller must fence superseded load results.
+ (void)loadManifestAtPath:(NSString *)path
               completion:(void (^)(MiniSightActionLibrary * _Nullable library,
                                    NSError * _Nullable error))completion;

/// One in-flight job plus ONE latest pending request per library. A new request
/// cancels the previous callback (latest wins). An invalid clip/index yields nil.
/// Cache hits, including the primed first frame, require no disk I/O.
/// All library instances share one hard <=8 MiB / <=32-frame CG pixel cache.
- (void)requestFrameForClip:(MiniSightActionClip *)clip
                    index:(NSUInteger)index
               completion:(void (^)(UIImage * _Nullable image))completion;
/// Drops callbacks and fences late cache writes; cannot interrupt ImageIO itself.
- (void)cancelPendingFrameRequests;
/// Cancels requests AND removes this library's entries from the shared CG cache.
/// Other live libraries keep their entries within the process-wide budget.
- (void)purgeFrames;
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
@end

NS_ASSUME_NONNULL_END
