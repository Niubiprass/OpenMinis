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

// [V65-FIXSIZE-S] 非正尺寸(宽或高 <= 0)的**跨 tick** 硬上限。
// 装机实测(8.log): 单容器 14 秒被喂 2644129 次 0x0, 内存 +470MB ⇒ SIGKILL。
// 40 太大(单条消息正常排版也就几次), 这里取一个既能止住风暴、又不会误伤
// 正常排版的值: 正常一轮排版里"上游算崩"最多偶发 1-2 次, 连续 400 次
// 意味着上游已经进入死循环, 此时停止转发是唯一正确的选择。
static const NSInteger kNonPositiveHardLimit = 400;

// [V68-DOWNFREQ] 命中 kNonPositiveHardLimit 之后的**放行步长**: 每 64 次里放 1 次。
// v66 是"永久停止转发", 代价是容器高度永久冻结 ⇒ 屏幕保留一整块旧几何
// ⇒ 巨大空白(v61 刚修掉的症状换个形态回来)。
// 降频 1/64 把 197 万次压到约 3 万次(内存增速 1.4GB → 20MB 量级),
// 同时**保留上行通道**: 上游一旦自愈, 高度仍能一帧一帧追回来。
static const NSInteger kNonPositiveSkipStride = 4096;
// [V73] 非正尺寸风暴进程级硬降频步长 64→4096: 实测「点击选择模型」re-entrant
// 死循环 6 秒 43 万次 0x0 修正转发(v68 1/64 仍转发 ~6800/s 打满主线程 ⇒ SIGKILL)。
// F=外部调用/(N-1): N=4096 ⇒ F≈17/s, 主线程不再饱和 ⇒ 看门狗不杀;
// 前 kNonPositiveGlobalLimit 次仍全转发建立 lastGoodHeight。保留 ⑨ 与 S15 锚点。

// [V69-GLOBAL] **进程级**非正尺寸风暴计数。
//
// 【为什么必须有全局一份 —— 见上方 v69 装机铁证】
// 风暴的第二种形态是"容器工厂": 上游每次循环新建一个 NSTextContainer,
// 用完即弃。此时所有 per-container 计数器(含 v68 的三条)随容器一起消失,
// 恒为初始值 ⇒ 累加不动、游标恒 0、历史高度恒 0 ⇒ 闸门永远不开。
// 进程级计数与容器生命周期无关, 是这种形态下**唯一**还能累加的东西。
static NSInteger gGlobalNonPositiveStreak = 0;
// [V69-GLOBAL] 进程级降频游标。必须是全局的: per-container 的
// nonPositiveSkipTick 在容器重建时恒为 0 ⇒ 每次都放行 ⇒ 降频完全落空。
static NSInteger gGlobalSkipTick = 0;
// [V69-GLOBAL] 进程级"上一次真实排版过的高度"。容器是新的时候,
// s->lastGoodHeight 恒为 0, 这是唯一还能拿到的真实高度。
static CGFloat gGlobalLastGoodHeight = 0.0;
// [V69-GLOBAL] 连续收到**正**尺寸的计数, 用于风暴结束后退出降频态。
static NSInteger gGlobalGoodRun = 0;
// [V69-GLOBAL] 进程级硬上限: 与 per-container 的 400 同量级。正常排版里
// 非正尺寸最多偶发几次; 连续 400 次意味上游已进入死循环。
static const NSInteger kNonPositiveGlobalLimit = 400;
// [V69-GLOBAL] 连续这么多次正尺寸即认定上游已自愈, 全局计数清零。
// 取 128 而不是更大: 一帧正常排版里正尺寸 setSize 远多于 128 次,
// 取大了会让 App 在一次风暴后长期滞留降频态。
static const NSInteger kNonPositiveGoodRunReset = 128;

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
    // [V65-FIXSIZE-S] 非正高度连续命中次数。**跨 tick 累加**(故意不清零):
    // 装机实测 0x0 在每个 tick 都被反复喂, 只按 tick 清零 ⇒ 永不熔断 ⇒
    // 单容器 14 秒 264 万次 ⇒ 内存 +470MB ⇒ SIGKILL。跨 tick 累加才能拦住它。
    NSInteger nonPositiveStreak;
    // [V68-GOODH] 该容器**上一次被转发的真实高度** (>0)。非正高度修正时优先用它,
    // 而不是猜一个 1.0 —— 1.0 装不下任何一行, 上游会继续算崩(活锁)。
    CGFloat lastGoodHeight;
    // [V68-DOWNFREQ] 降频丢弃的游标: 每 kNonPositiveSkipStride 次放行 1 次。
    NSInteger nonPositiveSkipTick;
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
    // [V65-FIXSIZE-S] 原始尺寸的函数级副本 (赋值在下面的修正分支里)。
    // 必须声明在函数体开头: 块内声明对后续兄弟块不可见(clang 实测 4 处
    // "use of undeclared identifier"), 本项目 §19 同族第四次。
    CGFloat _v65orig_w = newSize.width;
    CGFloat _v65orig_h = newSize.height;
    // [V68-HOIST] 容器状态**提前到函数体开头**取。
    //
    // 【为什么必须提升 —— §19「标识符存在 != 可见」同族第五次】
    // v68 要在**非正高度修正段**里读 `s->lastGoodHeight`(用上一次真实高度
    // 代替猜出来的 1.0), 而原来 `holder`/`s` 的获取在那个段**之后**
    // (实测产物: 非正修正段 idx=6644, `GuardState *s` idx=13695)
    // ⇒ 修正段里写 `s->...` 会 clang 报 "use of undeclared identifier"。
    // 与其把 lastGoodHeight 再提升成一个全局/静态变量(多容器会串),
    // 不如把 s 的获取整体前移 —— objc_getAssociatedObject 无副作用,
    // 前移只影响"state 对象创建得早一点", 不改变任何判定语义。
    _NSTextContainerGuardState *holder = objc_getAssociatedObject(self, kGuardStateKey);
    if (!holder) {
        holder = [_NSTextContainerGuardState new];
        objc_setAssociatedObject(self, kGuardStateKey, holder, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }

    GuardState *s = &holder->state;

    if (!isfinite(newSize.width) || !isfinite(newSize.height)) {
        // [V65] NaN/inf 仍然硬拒 —— 它们会触发 CoreText fillLayoutHole 病态循环
        // (v4 实证 11918ms 主线程卡死), 且 TextKit 无法表示, 无从"修正"。
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] short-circuited setSize: "
                  @"REJECT-NAN-INF size=%.1fx%.1f total=%llu container=%p",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        return;
    }
    // [V77-EARLY-NONPOS] 非正原始尺寸在 KVC/NSLog/重入哨兵之前直接 return。
    // 装机 minis-2026-10-06 2.log PID 52989: build=V76 在跑, SHORT-CIRCUIT 0 次,
    // FIXED-NONPOSITIVE 21084 条(每 32 打 1) ⇒ 675425 次 0x0→326x307,
    // 内存 48.5→2043.3MB / 9s / pressure=CRITICAL ⇒ PID 53046 重启。
    // 根因: V76 的 return 在 V65 KVC+NSLog 与 V74 `if (_gSetSizeForwarding)` 之后。
    // 重入 setSize 先付完 V65 税, 再被 V74 return, V76 一次都看不见。
    // 修法: orig<=0 在 valueForKey 之前 return, 不转发、不做 KVC。
    if (newSize.height == 0.0) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V77] EARLY-NONPOSITIVE-RETURN "
                  @"orig=%.1fx%.1f total=%llu — 入口短路(不 KVC/不转发)",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount);
        }
        return;
    }
    // [V65-FIXSIZE] 有限但非正的尺寸: **就地修正后转发, 不再丢弃**。
    //
    // 【装机铁证】v64 之后 (minis-2026-10-05 13:21) 这个分支命中 61 次:
    //   size=0.0x-8.0  ×43
    //   size=0.0x-16.0 ×18
    // 宽 0 + 负高 = 宽度算崩了、高度算成了 -inset/2。旧代码在这里 `return`
    // ⇒ **TextKit 容器尺寸一次都没被更新** ⇒ 排版停在上一帧 ⇒ 屏幕上的字
    // 被上一帧的旧高度裁掉一半。旁证: tk=27.0 ×83 / est=31.0 ×96,
    // 31pt 就是一行 —— 「卡字」不是布局算错, 是排版压根没跑。
    //
    // 【为什么必须修正而不是丢弃】丢弃看起来"安全"(不把脏值喂给 TextKit),
    // 但它恰恰是卡字的直接原因: 丢弃 = 保留过期几何 = 排版结果永远滞后。
    // 而这些值是**有限**的, 数值上完全可以变成一个合法尺寸 —— 不存在
    // "喂进去会病态循环"的风险(那是 inf/NaN 的问题, 上面已硬拒)。
    //
    // 【修正规则, 逐条都有装机依据】
    //   宽 <= 0 → 用容器**自己当前的宽**(它是上一次排版的正确答案);
    //            拿不到就退回屏宽-32(358, 日志实测的真实排版宽度)。
    //            ★不用 UIScreen 满宽 390: v13/v34 已实证 390 排版/358 显示
    //              会导致末行裁断与拉锯闪字(REVERTED-v11 注释详述)。
    //   高 <= 0 → 取绝对值。8/16 正好是 textContainerInset 的量级, 说明
    //            上游算的是 "容器高 - inset", inset 被减了两遍。
    //            取绝对值后 8/16 是一个合法的最小容器高, 排版能正常跑。
    if (newSize.width <= 0 || newSize.height <= 0) {
        CGSize _v65orig = newSize;
        // [V65-FIXSIZE-S] 把原始(未修正)尺寸**提升到函数作用域**。
        // ★clang 实测: 声明写在上面的 if 块内时, 下面的熔断段
        //   "use of undeclared identifier '_v65orig_h'"(4 处)——
        //   即本项目 §19「标识符存在 != 标识符**可见**」第四次同族。
        //   C 的块作用域: 块内声明只到块尾可见, 后面够不着。
        // ⇒ 必须在**函数体开头**声明, 这里只赋值。
        _v65orig_w = newSize.width;
        _v65orig_h = newSize.height;
        if (newSize.width <= 0) {
            // [V65] 取容器自己当前的宽。走 KVC 而不是 `[(id)self width]`:
            // NSTextContainer 是私有类, 直接发消息在 ARC 下要求编译器知道该
            // selector 声明, 会报 "no visible @interface" —— 这正是我担心的
            // 又一处编译红(run#157/run#159 同类)。KVC 纯运行期查找, 无声明依赖。
            CGFloat _w = 0;
            @try {
                NSValue *_wv = [(id)self valueForKey:@"size"];
                if (_wv) _w = (CGFloat)[_wv CGSizeValue].width;
            } @catch (__unused NSException *_e) {
                _w = 0;
            }
            if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {
                // ★★必须走 KVC 而不是 `[UIScreen mainScreen].bounds.width`:
                //   CGRect 的 `.width` / `.height` **不是 struct 成员**, 而是
                //   CoreGraphics 里 `CGGeometry` 这个 **category**(NSGeometry on
                //   macOS / CoreGraphics on iOS)提供的。UIKit 的模块化导入
                //   **不 re-export 它**, 所以本文件写了 `#import <UIKit/UIKit.h>`
                //   仍然报 (CI#162 / run 37275980272 实测):
                //       NSTextContainerSetSizeGuard.m:153:51:
                //       error: no member named 'width' in 'struct CGRect'
                //   ⇒ 走 KVC `valueForKey:@"bounds"` 拿 NSValue 再取 CGSizeValue,
                //     纯运行期查找, 不需要编译器认识任何 category 声明。
                //   ★这也是本项目**第六次**「本地验证手段骗了自己」:
                //     上轮我自建 UIKit 桩做 clang 检查, 桩里给 CGRect 加了
                //     .width 访问器 ⇒ 0 error 的**假绿**。桩比真实 SDK 宽松,
                //     它给不了的保证它会假装能给。
                _w = 0;
                @try {
                    NSValue *_bv = [[UIScreen mainScreen] valueForKey:@"bounds"];
                    if (_bv) _w = (CGFloat)[_bv CGSizeValue].width;
                } @catch (__unused NSException *_e) {
                    _w = 0;
                }
                // 358 = 日志实测的真实排版宽度(iPhone 14/15 屏宽 390 - 32)。
                // ★不用 390 满宽: v13/v34 已实证 390 排版/358 显示会导致
                //   末行裁断与拉锯闪字(REVERTED-v11 注释详述)。
                if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {
                    _w = 358.0;
                }
                _w -= 32.0;
            }
            newSize.width = _w;
        }
        if (newSize.height <= 0) {
            // [V65-FIXSIZE-H] 高度 <= 0 **不能只取 fabs**。
            //
            // 【v65 装机铁证 —— 这次不是"没修", 是"修了个空"】
            // minis-2026-10-05 8.log (17:20:41-17:20:55, iOS 15.5 / iPhone13,2):
            //   size=0.0x0.0 -> 326.0x0.0    × 82507 条日志 (每 32 次打 1 条)
            //   ⇒ 实际进入本分支 **2644129 次**, 全部是 height **0.0**。
            // 而 `fabs(0.0) == 0.0` ⇒ 打印出来的前后尺寸**完全相同**:
            //   "FIXED-NONPOSITIVE size=0.0x0.0 -> 326.0x0.0"  ← 高度 0 → 还是 0
            // ⇒ 所谓"修正转发"对最常见的形态(0x0)是**空操作**:
            //   高度 0 原样喂给 TextKit, 排版出 0 行, 下一帧还是 0。
            // 这就是用户说的"还是有一点点闪、会抖动"的**直接根因**。
            //
            // 【正确做法】0 高不是一个合法容器高(TextKit 认为"没有高度"),
            // 必须夹到一个**能跑排版的最小合法高度**。用 1.0 而不是 0:
            // TextKit 对 height<=0 视为无容器可用, 对极小正高仍会排版。
            CGFloat _ah = fabs(newSize.height);
            // [V68-GOODH] 修正值**优先用该容器上一次真实排版过的高度**。
            //
            // 【为什么 1.0 反而是活锁的燃料 —— v66 装机日志实证】
            // v66 把 fabs(0.0)==0.0 抬到 1.0, 生效了
            // (日志实测 size=0.0x0.0 -> **326.0x1.0**), 但整机仍然崩:
            //   · 197 万次修正的**结果全是同一个值 1.0**
            //   · 上游收到 1.0 和收到 0.0 在它眼里是同一件事:
            //     **都排不出任何东西**(1pt 装不下任何一行)
            //   · 于是它的自反馈回路一秒都没被改变:
            //     算崩→喂0→抬成1→排0行→上游仍算崩→再喂0 ...
            //   风暴以原速跑完 11 秒、吃掉 1.4GB。
            //
            // ★ v65 的病是"修正成了和原来一样的值"(空操作);
            //   v66 的病是"修正成了一个**上游仍然不满意**的值"(活锁)。
            //   两者要断的位置不同: v65 改"修正成什么", v66 改"还转不转发"。
            //
            // 唯一**已知可用**的高度是本容器上一次被转发的正高度
            // (lastGoodHeight, 由下面 [V68-GOODH] 在每次转发正高度时记录)。
            // 用它: 上游即便继续崩, 屏幕上仍保留崩溃前的真实几何
            //       (不空白、不闪), 而不是反复让 TextKit 在 1pt 上空排。
            // 无历史(首次就是 0x0)时才退回 1.0 —— 那时至少不是空容器。
            if (!(_ah > 1.0)) {
                CGFloat _prev = s->lastGoodHeight;
                if (!(_prev > 1.0 && isfinite(_prev) &&
                      _prev <= kMaxContainerHeight)) {
                    // [V69-GLOBAL]④ 本容器无历史(**容器是新建的**, 这正是
                    // 「选择模型」风暴的形态) ⇒ 退回进程级历史高度。
                    // 没有这一层兜底, 修正值恒为 1.0 ⇒ 上游拿到 1.0 和拿到
                    // 0.0 同样排不出东西 ⇒ 自反馈回路一秒都没断(活锁)。
                    _prev = gGlobalLastGoodHeight;
                }
                _ah = (_prev > 1.0 && isfinite(_prev) &&
                       _prev <= kMaxContainerHeight) ? _prev : 1.0;
            }
            if (_ah > kMaxContainerHeight) { _ah = kMaxContainerHeight; }
            newSize.height = _ah;
        }
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [V65] FIXED-NONPOSITIVE size=%.1fx%.1f "
                  @"-> %.1fx%.1f total=%llu container=%p — 修正转发(旧版丢弃=卡字)",
                  _v65orig.width, _v65orig.height, newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        // 不 return —— 继续往下走熔断逻辑, 修正后的尺寸照常转发给 TextKit。
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

    // [V68-HOIST] holder / s 已在本函数**开头**取好(见上方 [V68-HOIST]),
    // 非正高度修正段要用 s->lastGoodHeight, 那段比这里更早。

    // [V77-MARKER] 一次性打印构建版本(装机确认)。V76 = V75 persistentStorm + **V76 非正尺寸跨 tick 持久短路**(非正原始尺寸 0x-16/0x0/0x-8 到达时直接 return 不转发 CoreText, 斩断 V65 修正转发引发的 layout 活锁; 容器保留 lastGoodHeight 合法几何, 文字照常显示, 上游算对即自动 re-arm)。专治 V75 仍未斩净的「选择模型卡死」(实测 8.3 万次非正转发→objc_sync_enter 锁卡死→7349ms HANG→SIGKILL)。
    static BOOL _v77GuardLogged = NO;
    if (!_v77GuardLogged) {
        _v77GuardLogged = YES;
        NSLog(@"[Minis-Guard] build=V77 ios15-pickerCap+inputFlicker+reentrantBreak+persistentStorm+nonPositiveShortCircuit+earlyNonPositiveReturn (cappedEntriesByInstance 非搜索态截断 150; intrinsicContentSize 反馈环路守卫斩输入闪屏; setSize: 递归哨兵斩断重入环; 同尺寸风暴跨 tick 持久熔断斩断选择模型 measure 死循环; V76 非正尺寸短路不转发; **V77 入口短路: orig<=0 在 valueForKey 之前 return, 重入不再付 KVC 税**)");
    }

    // [V74-REENT] 递归哨兵: 斩断 setSize: → gOriginalSetSize → layout → setSize: 重入环。
    // 实测 V73 启动期 setSize: 被重入调用 ~120 万次(storm-breaker SKIP total 飙到
    // 1239121), 根因是 gOriginalSetSize 触发布局 → 布局再调 setSize: → 再转发... 的主线程
    // 锁自旋(NSAllocateObject + objc_sync_enter / os_unfair_recursive_lock)→ 看门狗 SIGKILL。
    // 重入态(正在 gOriginalSetSize 内部)直接 return, 不转发原始实现 ⇒ 不再触发布局 ⇒ 环断开;
    // 仅重入期间生效, 平时正常转发(非永久冻结, 满足断言69 ⑨)。哨兵置于 GuardState *s 之后
    // (逻辑等价), 以保留下游 v68 的多行锚点(以 `}` 与 `GuardState *s` 之间无插入为前提)。
    static BOOL _gSetSizeForwarding = NO;
    if (_gSetSizeForwarding) {
        return;   // 重入: 保留上次已提交几何, 不再触发布局
    }

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断后, 只丢弃"同尺寸重复"
    // (自旋源); 不同尺寸的调用仍有限放行 —— v9 实证: 无差别丢弃会把正确的宽度
    // 修正 (358x550.9) 连坐丢掉, 容器宽停在旧值 → 文字不换行 → 横向裁切。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
        if (CGSizeEqualToSize(s->lastSize, newSize)) {
            gShortCircuitCount += 1;
            if ((gShortCircuitCount & 0xFFFFF) == 1) {
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
            // [V70-DEDUP] 关键修复: 不再第 2 次同尺寸就跳过。
            // 旧 kRepeatThreshold=2 让 re-entrant 风暴里 CoreText fillLayoutHole
            // 只在第 1 次拿到尺寸提交, 其后全部 return -> 永远收敛不了 ->
            // 递归不终止 -> 627k 次/tick -> 主线程打满崩溃(装机 2026-10-06 实测)。
            // 改为: 本 tick 已转发次数(commitCount, 由下方 gOriginalSetSize 累加)
            // 未超 kStormForwardLimit*4 时"放过", 落到 gOriginalSetSize 真正提交
            // 尺寸让 CoreText 收敛; 超阈值说明已收敛, 置 stormed 并跳过(安全)。
            if (s->commitCount > kStormForwardLimit * 4) {
                s->stormed = YES;
                return; // 收敛后跳过
            }
            // 否则 fall-through 到 gOriginalSetSize 转发(让 CoreText 收敛)
        }
    } else {
        // Different tick or different size — reset bookkeeping.
        // [V75-PERSISTENT-STORM] 必须在覆盖 s->lastSize 之前算好 _sizeChanged:
        // 它比的是「本次到达的尺寸」与「上一帧已记录的尺寸」是否不同。
        BOOL _sizeChanged = !CGSizeEqualToSize(s->lastSize, newSize);
        s->lastSize = newSize;
        s->repeatCount = 1;
        s->initialized = YES;
        // [v26] 仅新 tick 才清零转发计数; 同 tick 内不同尺寸的放行
        // 调用继续累计 commitCount, 保证 4x 硬上限对交替拉锯 (390<->358) 有效。
        // [V75-PERSISTENT-STORM] stormed 跨 tick 持久 —— 只在不同尺寸到达时解除,
        // 不再随 tick 清零。旧逻辑每 tick 把 stormed 复位 ⇒ 陷入「布局永不合收敛」
        // 的容器每帧重燃: 每帧拿到 kStormForwardLimit*4 (160) 次免费转发额度,
        // 主线程被永久喂满 ⇒ HangDetector 时长跨 tick 单调递增 (2055→4407ms+) ⇒
        // 看门狗 SIGKILL。这正是「选择模型卡死」在 V74 仍未斩净的形态:
        // setSize→runloop 新布局 pass→setSize 的跨调用重入, _gSetSizeForwarding
        // 哨兵(仅拦单次调用栈内的重入)根本抓不到。跨 tick 保留 stormed ⇒ 一旦某
        // tick 内同尺寸重复超 160 次被熔断, 后续所有 tick 的同尺寸调用一律 SKIP,
        // 环被永久斩断; 上游若真收敛到新尺寸(不同尺寸到达)即自动 re-arm, 合法
        // 更新零丢失。单次/少量同尺寸每帧只占 repeatCount=1, 永不到 160 阈值,
        // stormed 不会置位, 合法场景零影响。
        BOOL _newTick = (s->lastTick != gRunloopTick);
        if (_newTick) { s->commitCount = 0; }
        if (_sizeChanged) { s->stormed = NO; s->commitCount = 0; }
        s->lastTick = gRunloopTick;
    }

    // [IOS15-FIX-STORM] 累加本 tick 转发次数; 超过阈值即置熔断标志,
    // 后续同 tick 调用走上面的 storm-breaker SKIP 直接 return。
    // [V65-STORM] 只有**哨兵**尺寸才计入风暴预算; 真实排版高度永不参与。
    //
    // 【装机铁证】v64 之后 (13:21 装机日志) 熔断误伤了 85 次真实排版:
    //   size=358.0x19.0 ×39   ← 一行, 真实高度
    //   size=358.0x41.0 ×46   ← 两行, 真实高度
    // 这些不是哨兵(哨兵是 ≥3000 被压到 2000), 是**真正的行高**。丢掉它们
    // ⇒ 这一帧排版作废 ⇒ 下一帧拿旧高度上屏 ⇒ 用户看到的「打一个字母抖一下」。
    //
    // 【为什么这样切是安全的】熔断(kStormForwardLimit=40)存在的唯一目的是
    // 斩断哨兵驱动的 fillLayoutHole re-entrant 风暴(v4 的 11918ms 卡死)。
    // 真实排版尺寸**不是**风暴源 —— 它进 CoreText 是一次有界的正常排版。
    // 之前把两者混在同一个计数器里, 于是熔断在杀哨兵的路上把真实排版
    // 一起吞了: 这就是「哨兵没治好、真排版先受害」。
    //
    // 判据用高度: ≥ 2000 即已被上面 kProbeHeightCeiling 压到哨兵值, 那才是
    // 风暴源; < 2000 是真实内容高度, 不计预算、不触发熔断。
    // ★为什么写字面量 2000 而不是引用 kProbeHeightCeiling: 那个 const 声明在
    //   本函数体内它自己那段 `{ ... }` 里, 与本处**不在同一作用域**, 直接
    //   引用会编译失败(这正是 run#159/run#157 同类错误的第四次)。写死字面量
    //   并在上面的哨兵压位处加了注释锚点, 两处靠 2000 这个数字对齐。
    if (newSize.height >= 2000.0) {
        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
        }
    } else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {
        // [V65-FIXSIZE-S] **非正高度同样计入风暴预算**。
        //
        // 【v65 装机铁证 —— 上一版的豁免规则漏了最毒的形态】
        // v65 只让"哨兵(≥2000)"计费, 理由是"真实排版高度不该被熔断吞掉"。
        // 但装机日志显示: 2644129 次修正里 **82507 条日志(全部 0x0)** 走的是
        // `_v65orig_h <= 0` 这条路, 它 **既不是哨兵、也不是正常高度**, 而是
        // 上游算崩的产物 —— 恰恰是最该被熔断的东西, 却被豁免了。
        // 后果(14 秒内, 单容器 0x2802b8820):
        //   · 264 万次 KVC 取值 + NSNumber 装箱 ⇒ 内存 151.8MB → **624.2MB**
        //     (17:20:39→17:20:44, +470MB) ⇒ 内存压力 ⇒ **SIGKILL 闪退**
        //   · 同时每次都走完修正+转发 ⇒ 主线程 **6281ms 卡顿**(HangDetector
        //     抓到 UIKitCore/QuartzCore/UIFoundation 满屏栈) ⇒ 抖动
        // ⇒ 抖、卡、崩**三者是同一个根因**, 不是三个病。
        //
        // 【为什么不能靠"每 tick 40 次"现成熔断】
        // 上面的 storm-breaker 是 per-tick 的; 而 0x0 在**每个 tick 都被反复喂**,
        // tick 一换计数就清零 ⇒ 永远不超阈值 ⇒ 永远不熔断。
        // ⇒ 必须让"非正高度"这一类**跨 tick 也计费**, 才可能触发熔断。
        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
        }
        // [V68-STREAK] **跨 tick 累加必须无条件执行**。
        //
        // 【v68 装机铁证 —— v66 把这一行埋进了 per-tick 门槛里, 它从未执行】
        // minis-2026-10-06.log (iOS 15.5):
        //   size=0.0x0.0 -> 326.0x1.0  total=1970881  container=0x283da6f80
        //   × 61584 条日志(每 32 打 1) ⇒ 实际 **197 万次 / 11 秒 / 单容器**
        //   内存 35.5MB → **1474.6MB**(+1.4GB) ⇒ SIGKILL(PID 28466→28473)
        //   storm-breaker / NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP **各 0 次**
        //
        // v66 写的是:
        //     if (s->commitCount > kStormForwardLimit) {   // per-tick 门槛
        //         s->stormed = YES;
        //         s->nonPositiveStreak += 1;              // ← 死代码
        //     }
        // 而 commitCount 由 `if (_newTick) { s->commitCount = 0; }` **每 tick 清零**;
        // 0x0 是"每 tick 只喂一两次"的形态 ⇒ commitCount 永远到不了 40
        // ⇒ streak 永不增长 ⇒ 硬闸门永不触发 ⇒ 197 万次全部真转发。
        //
        // ★ 本项目**第八次**「验证手段骗了自己」:
        //   v66 的第 ⑦ 层判据问的是"`nonPositiveStreak` 会不会被清零",
        //   而病根是"它会不会被**累加**"。前者恒真、后者恒假 ——
        //   **问错了问题, 绿灯就是假的**。判据必须问"累加是否在门槛之外"。
        s->nonPositiveStreak += 1;
        if ((s->nonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"streak=%ld tickCommit=%lld — 非正尺寸跨 tick 累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak,
                  (long long)s->commitCount);
        }
        // [V69-GLOBAL]① 进程级累加: 容器每次重建也断不了这一条。
        gGlobalNonPositiveStreak += 1;
        gGlobalGoodRun = 0;
        if ((gGlobalNonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V69] GLOBAL-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"gstreak=%ld cstreak=%ld — 进程级非正尺寸累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)gGlobalNonPositiveStreak,
                  (long)s->nonPositiveStreak);
        }
        // [V76-NONPOS-SHORTCIRCUIT] 非正原始尺寸直接短路, **不转发 CoreText**。
        // 与 NSTextContainerSetSizeGuard.m 第 ~5xx 行 V76 改动一致: 非正尺寸
        // (0x-16/0x0/0x-8) 被 V65 修正转发会触发 layout 活锁(实测 83526 次转发
        // → 8.3 万次 layout → objc_sync_enter 锁卡死 → 7349ms HANG → SIGKILL)。
        // 直接短路斩断活锁; 容器保留合法几何(lastGoodHeight), 文字照常显示。
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V76] NONPOSITIVE-SHORT-CIRCUIT "
                  @"container=%p orig=%.1fx%.1f streak=%ld gstreak=%ld "
                  @"— 非正尺寸直接短路(不转发 CoreText)",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  (long)s->nonPositiveStreak, (long)gGlobalNonPositiveStreak);
        }
        return;
    } else if (_v65orig_h > 0.0 && _v65orig_w > 0.0) {
        // [V69-GLOBAL]⑤ 自愈退出: 连续收到正尺寸 ⇒ 上游已恢复, 全局计数清零。
        //
        // 【为什么必须显式退出】降频是"每 64 次放 1 次", 若风暴结束后计数
        // 不清零, App 会**永久**滞留降频态 —— 与 v66「永久冻结」同类错误:
        // 那一次是冻结单个容器, 这一次是冻结整个进程, 更狠。
        //
        // 判据用**原始**尺寸而不是修正后的: 修正后的值恒为正(守卫干的正是
        // 这件事), 用它判断"上游是否自愈"会永远为真 ⇒ 计数刚加上就被清掉。
        // 走到本分支意味着: 高度 <2000(非哨兵) 且 原始宽高都为正 —— 即
        // 上游这次**真的**算出了一个合法尺寸。
        gGlobalGoodRun += 1;
        if (gGlobalGoodRun >= kNonPositiveGoodRunReset) {
            if (gGlobalNonPositiveStreak > 0) {
                NSLog(@"[TextContainerGuard] [INFO] [V69] GLOBAL-RECOVER "
                      @"gstreak=%ld — 连续正尺寸已 %d 次, 全局风暴计数清零",
                      (long)gGlobalNonPositiveStreak,
                      (int)kNonPositiveGoodRunReset);
            }
            gGlobalNonPositiveStreak = 0;
            gGlobalGoodRun = 0;
        }
    }
    // [V65-FIXSIZE-S] **跨 tick 硬闸门**: 非正高度连续命中超限后, 停止转发。
    //
    // 【为什么必须有这一刀, 而不能只靠 per-tick 的 storm-breaker】
    // 装机实测(8.log 17:20:41-55): 单容器 0x2802b8820 在 14 秒内被喂
    // **2644129 次 0x0**。per-tick 熔断每换一次 tick 就清零, 而上游每个
    // tick 都在喂 ⇒ 计数永远到不了 40 ⇒ 永远不熔断 ⇒ 无限转发。
    // 而每一次转发都要: KVC 取 NSValue → CGSizeValue → 装箱 → 修正 → 转发,
    // 14 秒堆出 **+470MB**(151.8→624.2MB) ⇒ SIGKILL; 同期主线程 6281ms 卡顿。
    //
    // 【为什么这里 return 是安全的 —— 不再是"丢弃=卡字"】
    // v65 之前靠"丢弃坏尺寸"来止风暴, 代价是 TextKit 保留过期几何 ⇒ 卡字。
    // 现在非正高度**先被修正成合法尺寸**(高度抬到 1.0), 连续命中到上限后
    // 才停止转发 —— 此时容器已经拿到过一个**合法几何**, 保留它即可,
    // 不是"从未更新过的过期几何"。⇒ 与 v65 的修正转发不冲突。
    // [V68-DOWNFREQ] 命中上限后**降频放行**, 不是永久停止转发。
    //
    // 【为什么必须改 v66 的"永久停止"】
    // v66 是 `if (streak > 400) { return; }` —— 一旦触发, 该容器**再也收不到
    // 任何 setSize**。若上游持续算崩(而它正是这么崩了 197 万次), 高度就永久
    // 冻结在最后一个值上 ⇒ 屏幕保留一整块旧几何 ⇒ **巨大空白**。
    // ★ 这就是 v61 刚修掉的症状换了个形态回来: v66 用"永久冻结"止住了内存,
    //   却把内存问题原地换成了空白问题 —— 守卫的职责是让 App 活下去,
    //   **永久冻结是让 App 死得更快**: 它连"上游万一自愈"的可能性都一并删掉了。
    //
    // v68 改成: 上限之后每 kNonPositiveSkipStride 次才真转发 1 次(1/64 降频)。
    //   · 197 万次 → 约 3 万次 ⇒ 内存增速降到 1/64(1.4GB → 约 20MB 量级)
    //   · 上游一旦自愈(哪怕很慢), 高度仍能一帧一帧追回来
    //   · 容器不会失去合法几何: 上一次放行的值本身就是合法的
    // [V69-GLOBAL]② 闸门判据加**进程级**一路: 容器工厂形态下
    // per-container 的 streak 恒为 1, 只有全局这一路可能超限。
    if ((s->nonPositiveStreak > kNonPositiveHardLimit) ||
        (gGlobalNonPositiveStreak > kNonPositiveGlobalLimit)) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-DOWNFREQ "
                  @"container=%p streak=%ld — 降频 1/%d 放行(保留上行通道)",
                  (__bridge void *)self, (long)s->nonPositiveStreak,
                  (int)kNonPositiveSkipStride);
        }
        // [V69-GLOBAL]③ 游标必须用**全局**的: 容器每次都是新的,
        // per-container 的 nonPositiveSkipTick 恒为 0 ⇒ 每次都走到"放行",
        // 降频等于没写(这正是 v68 装机 196 万次一次没减的原因)。
        gGlobalSkipTick += 1;
        if (gGlobalSkipTick < kNonPositiveSkipStride) {
            return;   // 本次丢弃: 只丢这一次, 不是永久
        }
        gGlobalSkipTick = 0;   // 本次放行
    }
    // [V68-GOODH] 转发一个**真实排版过的高度**, 记进 lastGoodHeight。
    // 只在高度为正且有限时记录 —— 负值/0 不是"排版过的高度"。
    // [V69-GOODH-PURE] 只有**上游真的算出了正尺寸**时才记历史高度。
    //
    // 【v68 的 GOODH 有个自锁 bug —— 装机日志 (5) 的第二层原因】
    // v68 的条件只看 `newSize.height > 0`。而 0x0 经过守卫修正后是 **1.0**,
    // 1.0 > 0 ⇒ 被当成"真实排版过的高度"记进 lastGoodHeight; 下一次 0x0
    // 再来, 取到的"历史"就是自己上次造出来的 1.0 ⇒ 修正值恒为 1.0
    // ⇒ 上游拿到 1.0 和拿到 0.0 一样排不出东西 ⇒ **活锁一圈没断**。
    // 日志实测修正值恒为 326.0x**1.0**, 与此完全吻合。
    //
    // ⇒ 必须按**原始**尺寸判定: 只有 orig 宽高都为正, 这次才是"上游算对了";
    //   守卫修正出来的值**永远不是**"排版过的真实高度"。
    // 另外排除 >= 2000: 那是哨兵钳位后的值, 同样不是真实内容高度。
    if (newSize.height > 0.0 && isfinite(newSize.height) &&
        newSize.height <= kMaxContainerHeight &&
        newSize.height < 2000.0 &&
        _v65orig_h > 0.0 && _v65orig_w > 0.0) {
        s->lastGoodHeight = newSize.height;
        // [V69-GLOBAL]④ 同步写进程级历史: 只有这里记下来,
        // 下一个**新建**的容器才可能在崩溃时拿到一个真实高度。
        gGlobalLastGoodHeight = newSize.height;
    }
    _gSetSizeForwarding = YES;
    ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
    _gSetSizeForwarding = NO;
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
