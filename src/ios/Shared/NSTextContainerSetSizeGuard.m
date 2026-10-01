//
//  NSTextContainerSetSizeGuard.m
//

#import "NSTextContainerSetSizeGuard.h"
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>

// Associated-object key used to stash the per-container "last seen"
// state (last size + last tick + repeat count in this tick).
static const void *kGuardStateKey = &kGuardStateKey;

// Threshold: when the same container is asked to setSize: to the same
// value more than N times in a single runloop tick (after the first),
// short-circuit the rest. Picked to be > 1 so an initial legitimate
// duplicate (e.g. SwiftUI's two-axis probing) still flows through, but
// a reentrancy storm is broken.
static const NSInteger kRepeatThreshold = 2;

// [IOS15-FIX-STORM] 风暴熔断阈值: 同一容器在同一 runloop tick 内被转发 setSize:
// 超过这个次数, 停止转发、保留已提交几何, 斩断 CoreText fillLayoutHole 的
// re-entrant 链 (实测完整堆栈 CoreFoundation + #1-#7 全 CoreText, 最长 11918ms
// 主线程卡死)。40 是经验值: 正常一 tick 内单个容器合法 setSize 远不到此数
// (多 cell 批量排版时每容器也就几次), 但 re-entrant 风暴会一 tick 内打几千次。
static const NSInteger kStormForwardLimit = 40;

// [IOS15-FIX-STORM] 容器高度上限。源码用 .greatestFiniteMagnitude 关掉高度钳制;
// 旧 guard 钳到 1e7 (仍近乎无限)。iOS 15 上近乎无限的容器让 fillLayoutHole 对长
// 流式消息病态循环。1e5(≈100000pt ≈ 16× 最高真实气泡) 既保留"足够高不裁真实
// 内容", 又给 CoreText 一个有限终点 -> 单次 typeset 成本有界。
static const CGFloat kMaxContainerHeight = 1e5;

// Monotonic tick id, bumped from a runloop observer (BeforeWaiting).
// Two setSize: calls within the same tick share the same value here.
static uint64_t gRunloopTick = 0;

// Counter for analytics.
static uint64_t gShortCircuitCount = 0;

typedef struct {
    CGSize lastSize;
    uint64_t lastTick;
    NSInteger repeatCount;
    NSInteger commitCount;   // [IOS15-FIX-STORM] 本 tick 内已转发次数
    BOOL stormed;            // [IOS15-FIX-STORM] 本 tick 熔断已触发
    BOOL initialized;
} GuardState;

@interface _NSTextContainerGuardState : NSObject {
@public
    GuardState state;
}
@end

@implementation _NSTextContainerGuardState
@end

static IMP gOriginalSetSize = NULL;

static void minis_NSTextContainer_setSize(id self, SEL _cmd, CGSize newSize) {
    if (![NSThread isMainThread]) {
        // Off-main calls (rare) bypass the guard entirely. Safer to
        // forward unconditionally than risk dropping a legit update.
        ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
        return;
    }

    // Sanitise obviously poisoned sizes that SwiftUI's measure path
    // occasionally leaks through (observed in Minis-2026-05-22-225827.ips
    // ViewGraphGeometryObservers crash logs: `408 x 1.79e308` from
    // Double.greatestFiniteMagnitude, and `-16 x 0` from a ViewGraph
    // arithmetic underflow). NSTextContainer reacts to setSize: by
    // invalidating its layout manager's typeset and re-entering the
    // _fillLayoutHole storm; that re-entry runs concurrently with
    // SwiftUI's AsyncRenderer thread mutating ViewGraphGeometryObservers,
    // which is exactly the FB13213926 race.
    //
    // Two classes of input:
    //
    //  (1) Structurally bad — NaN / inf / negative. NSTextContainer can't
    //      represent these meaningfully; hard-reject before TextKit sees
    //      them. The original setSize: never runs, the reentrant
    //      _fillLayoutHole cascade never fires.
    //
    //  (2) Legitimate "unbounded container" — code calls
    //      `tc.size = CGSize(width: w, height: .greatestFiniteMagnitude)`
    //      on purpose to disable height clamping during typesetting (used
    //      throughout SelectableMarkdownView for the live + measure
    //      textViews). The previous version rejected these outright as
    //      "> 1e7", which silently dropped the width too — leading to
    //      typesetter measuring against a 0×0 container, a wrong height,
    //      and the rightmost characters of the last visual line getting
    //      clipped (T-truncated-last-line, observed via STF-trace dump).
    //      Clamp instead of reject: 1e7 is still ~30× the tallest real
    //      chat bubble (6000pt CALayer ceiling), so the typesetter
    //      treats it as unbounded just like .greatestFiniteMagnitude
    //      would. dedup below still collapses repeat probes within the
    //      same runloop tick, preserving the race-mitigation effect.
    if (!isfinite(newSize.width) || !isfinite(newSize.height) ||
        newSize.width < 0 || newSize.height < 0) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] short-circuited setSize: "
                  @"REJECT-NAN-INF-NEG size=%.1fx%.1f total=%llu container=%p",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        return;
    }
    if (newSize.width > 1e5) newSize.width = 1e5;
    // [IOS15-FIX-STORM] 容器高度上限改有限值: 旧版钳到 1e7 仍近乎无限, iOS 15 上
    // 让 fillLayoutHole 对长流式消息病态循环 (多秒主线程卡死)。钳到 kMaxContainerHeight
    // (1e5 ≈ 16× 最高真实气泡) 既保留"足够高不裁真实内容", 又给 CoreText 有限终点。
    if (newSize.height > kMaxContainerHeight) newSize.height = kMaxContainerHeight;
    // [REVERTED-v11] 曾在此处加过"正文容器宽度硬钳制"(v9/v9.1/v10 三版), 已全部移除:
    // 实测三版全部更差 —— 目标宽度只能靠猜(屏宽390), 而真实可用宽是 358, 按 390 排版
    // 显示在 358 框里必然错位(用户反馈"字更加对不齐"); 且 v9.1 把 App 故意用的
    // greatestFiniteMagnitude 无限宽测量也钳成 390, 破坏测量语义 -> 布局永不收敛 ->
    // 单容器 44131 次同步死循环 + 508 次 10s 卡死。结论: 不要在派生的容器尺寸上
    // 和 UIKit 对抗(widthTracksTextView=true 时宽度由 UIKit 从 frame 派生), 要修
    // 就修产生它的 frame 源头。此处回退到已验证最好的 v8 行为。

    _NSTextContainerGuardState *holder = objc_getAssociatedObject(self, kGuardStateKey);
    if (!holder) {
        holder = [_NSTextContainerGuardState new];
        objc_setAssociatedObject(self, kGuardStateKey, holder, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }

    GuardState *s = &holder->state;

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断, 直接跳过转发、保留
    // 上次已提交几何。这样 re-entrant 的 setSize 链在到达阈值后立刻断掉, 不再
    // 驱动 CoreText fillLayoutHole 自旋 (实测 11918ms 主线程卡死的根因)。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] storm-breaker SKIP "
                  @"size=%.1fx%.1f tick=%llu total=%llu container=%p",
                  newSize.width, newSize.height,
                  (unsigned long long)gRunloopTick,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        return;
    }

    if (s->initialized && s->lastTick == gRunloopTick &&
        CGSizeEqualToSize(s->lastSize, newSize)) {
        // Same tick, same container, same target size — increment and
        // short-circuit once we cross the threshold.
        s->repeatCount += 1;
        if (s->repeatCount >= kRepeatThreshold) {
            gShortCircuitCount += 1;
            // Periodic warn log: every 16 short-circuits (≈ once per
            // visible reentrancy storm) to bound log volume.
            if ((gShortCircuitCount & 0xF) == 1) {
                NSLog(@"[TextContainerGuard] [WARN] short-circuited setSize: "
                      @"size=%.1fx%.1f tick=%llu repeatThisTick=%ld "
                      @"totalShortCircuits=%llu container=%p",
                      newSize.width, newSize.height,
                      (unsigned long long)gRunloopTick,
                      (long)s->repeatCount,
                      (unsigned long long)gShortCircuitCount,
                      (__bridge void *)self);
            }
            return; // skip forwarding to original setSize:
        }
    } else {
        // Different tick or different size — reset bookkeeping.
        s->lastSize = newSize;
        s->lastTick = gRunloopTick;
        s->repeatCount = 1;
        s->commitCount = 0;   // [IOS15-FIX-STORM] 重置本 tick 转发计数
        s->stormed = NO;      // [IOS15-FIX-STORM] 重置熔断标志
        s->initialized = YES;
    }

    // [IOS15-FIX-STORM] 累加本 tick 转发次数; 超过阈值即置熔断标志,
    // 后续同 tick 调用走上面的 storm-breaker SKIP 直接 return。
    s->commitCount += 1;
    if (s->commitCount > kStormForwardLimit) {
        s->stormed = YES;
    }
    ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
}

static void bumpRunloopTick(CFRunLoopObserverRef obs, CFRunLoopActivity act, void *info) {
    (void)obs; (void)act; (void)info;
    // Increment per runloop pass. We bump on BOTH BeforeWaiting and
    // AfterWaiting so a runloop pass that doesn't sleep (e.g. a busy
    // scene-update commit) still rotates the tick. Wrapping uint64
    // is fine for this purpose.
    gRunloopTick += 1;
}

@implementation NSTextContainerSetSizeGuard

+ (void)install {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        if (![NSThread isMainThread]) {
            NSLog(@"[TextContainerGuard] [WARN] install called off main; deferring");
            dispatch_async(dispatch_get_main_queue(), ^{ [NSTextContainerSetSizeGuard install]; });
            return;
        }

        Class cls = NSClassFromString(@"NSTextContainer");
        SEL sel = @selector(setSize:);
        Method m = class_getInstanceMethod(cls, sel);
        if (!m) {
            NSLog(@"[TextContainerGuard] [WARN] setSize: method not found on NSTextContainer");
            return;
        }
        gOriginalSetSize = method_setImplementation(m, (IMP)minis_NSTextContainer_setSize);

        // Runloop observer to rotate the tick id. Order 999_999 puts us
        // after typical layout observers; the exact value is not
        // critical because all we need is a monotonic-ish counter that
        // increases at least once per pass.
        CFRunLoopObserverRef obs = CFRunLoopObserverCreate(
            kCFAllocatorDefault,
            kCFRunLoopBeforeWaiting | kCFRunLoopAfterWaiting,
            true /* repeats */,
            999999 /* order */,
            bumpRunloopTick,
            NULL);
        if (obs) {
            CFRunLoopAddObserver(CFRunLoopGetMain(), obs, kCFRunLoopCommonModes);
            CFRelease(obs);
        }

        NSLog(@"[TextContainerGuard] [INFO] installed (threshold=%ld)", (long)kRepeatThreshold);
    });
}

+ (uint64_t)shortCircuitCount {
    return gShortCircuitCount;
}

@end
