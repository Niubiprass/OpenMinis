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
// [V38C-PROBEH] 被识别为 intrinsic 哨兵的 setSize 累计次数 (诊断用)。
static NSUInteger gProbeHeightCount = 0;

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
    // [V38C-PROBEH] intrinsic 探测哨兵高度收敛。
    //
    // 背景 (minis-2026-10-03 6.log, v37 实测): setSize: size=358.0x100000.0
    // 出现 87 次(最高频), totalShortCircuits 累计 2913, tick 横跨 1586~12402。
    // 根因: kMaxContainerHeight 恰好 = 1e5 = 100000, 而这里是 `<=` 边界 → 100000
    // **恰好放行**; 熔断只丢"同 tick 同尺寸", 这些调用跨 tick 尺寸相同 → 每个
    // 新 tick 重新初始化并真跑一次 CoreText 在 358x100000 上排版, 熔断形同虚设。
    //
    // 100000 一定是错的: 它是 intrinsic 探测的哨兵值(与 v37 处理的 lineFrag.width
    // = 10M 同源), 只想让 TextKit 报"我不约束高度"; 真实气泡最高 ~1748pt
    // (同日志实测 cell 高上限), 100000 是它的 57 倍。按 100000 高排版后 TextKit
    // 认为下方还有 ~98000pt 假空白, usedRect/高度回报都不可信。
    //
    // 修法: 高度 >= 3000 判定为探测哨兵, 压到 2000。
    //
    // 【v39 实测修正】初版取 8000/4000 过于保守: log7 显示 4000 反而成了新的最高频
    // (358x4000 × 131 次), 因为 4000 仍远超真实需求。log7 实测真实气泡最高只有
    // **901.3pt**(FIRST-MEASURE newH 与 needH 双向确认), 3000 已有 3.3× 余量,
    // 2000 也有 2.2× 余量。既保持"真实尺寸零影响", 又能把哨兵排版成本再降一半。
    // 哨兵本身不丢弃(下游需要它做 max-width/高度发现), 只是不再让 CoreText
    // 在十万点高度上真的排版。
    //
    // 【v40 实测: 阈值维持 3000/2000 不动, 不能收紧】
    // log8 看似"2000 成了最高频 x221"支持收紧, 但 FIRST-MEASURE 的 newH 实证
    // **真实气泡最高 2002.3pt**, 且 setSize 里真实尺寸已出现 1994.3 / 1863.0 / 1799.0
    // —— 它们紧贴 2000。若收到 1200/800, 这些**真实排版会被误判成哨兵并压掉**,
    // 直接制造一轮新的裁字(比现在更隐蔽, 因为只在长文本出现)。
    // 结论: 2000 不是"新风暴源"而是"真实上限", 221 次命中恰恰说明真实内容这么高。
    // 风暴的真正解法是消掉哨兵**探测行为**, 而不是压低哨兵值的上限 ——
    // 那属于 v25/v26 测高链的职责, 不在哨兵钳位这一层。
    const CGFloat kProbeHeightFloor = 3000.0;
    const CGFloat kProbeHeightCeiling = 2000.0;
    if (newSize.height >= kProbeHeightFloor) {
        if (gProbeHeightCount == 0) {
            NSLog(@"[TextContainerGuard] [V38C] probe-height %.0f -> %.0f "
                  @"container=%p",
                  newSize.height, kProbeHeightCeiling,
                  (__bridge void *)self);
        }
        gProbeHeightCount += 1;
        newSize.height = kProbeHeightCeiling;
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

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断后, 只丢弃"同尺寸重复"
    // (自旋源); 不同尺寸的调用仍有限放行 —— v9 实证: 无差别丢弃会把正确的宽度
    // 修正 (358x550.9) 连坐丢掉, 容器宽停在旧值 → 文字不换行 → 横向裁切。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
        if (CGSizeEqualToSize(s->lastSize, newSize)) {
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
        if (s->commitCount > kStormForwardLimit * 4) {
            // [v26] 不同尺寸但本 tick 已转发过多 (390<->358 交替拉锯): 也丢弃,
            // 防止交替对每次走 else 重置把熔断永久绕过。
            gShortCircuitCount += 1;
            return;
        }
        // 不同尺寸且未超硬上限: 放行, 正确修正不再被连坐。
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
        s->repeatCount = 1;
        s->initialized = YES;
        // [v26] 仅新 tick 才清零转发计数/熔断标志; 同 tick 内不同尺寸的放行
        // 调用继续累计 commitCount, 保证 4x 硬上限对交替拉锯 (390<->358) 有效。
        BOOL _newTick = (s->lastTick != gRunloopTick);
        if (_newTick) { s->commitCount = 0; s->stormed = NO; }
        s->lastTick = gRunloopTick;
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
