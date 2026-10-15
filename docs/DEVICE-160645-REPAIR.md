# DEVICE-160645-REPAIR

## 范围与结论边界

- 唯一修改工作树：`/var/minis/workspace/OpenMinis-push`，分支 `ios15-v64-repair`，起点 `5da5b4a`。
- 未使用旧 OpenMinis-v64 覆盖；未推送、未构建、未安装、未操作手机。
- 本次是可审阅的代码补丁，不是「根因全部确认」或「真机已经通过」。Linux/iSH 无 Swift/UIKit，测试只能证明源码契约和独立状态机行为。

## 160645 证据

核读 `workspace/test-160645/fast-log.json`，其中同一行的 item 与 cellItem 相同：

| 时间 | idx | raw/measured | locked/final | 状态 |
| --- | --- | --- | --- | --- |
| 20:50:37 | 133 | 326 | 505 | tracking=0 dragging=1 decel=1 |
| 20:50:48 | 133 | 326 | 505 | tracking=0 dragging=0 decel=0 |
| 20:50:37 | 143 | 455 | 679 | tracking=0 dragging=1 decel=1 |
| 20:51:05 | 197 | 679 | 1015 | tracking=0 dragging=1 decel=1 |

20:51:00 settle anchor idx186：frameY 16482→16451，offset 16528→16528，screenΔ=-31.3；多次还有 -13/-26。证据支持「已有较小正测量被宿主旧高长期覆盖」及「数值 offset 恢复不能保持屏幕内容位置」。它不能单独证明每个 raw 就是最终正确高度，也不能把所有消失/重叠归于同一原因。未重新使用截图/OCR作额外视觉结论。

## 外部成熟实现对照与取舍

实读：

- https://github.com/woxtu/UIHostingConfigurationBackport
- https://raw.githubusercontent.com/woxtu/UIHostingConfigurationBackport/main/Sources/UIHostingConfigurationBackport/UIHostingConfigurationBackport.swift
- ChatLayout 的运行时 self-sizing / 滚动位置保持方向由主助手另行调研：https://github.com/ekazaev/ChatLayout

woxtu backport 的实质是 rootView 配置更新、四边 constraints 和 `didMoveToSuperview` 中 addChild/removeFromParent；没有自定义「历史最大高度永久真相」，也没有用另一路测量结果充当增长天花板。本项目却同时存在宿主 high-water、cell 缓存、TextKit floor、布局 seed/memo、super fit ceiling，多层高度真相确实互相冲突。本次不引入整库、不再增加全局锁；缩减不成立的 ceiling，将 high-water 改为有可信释放条件的暂存保护。后续应独立验证 controller containment 生命周期，不能在本次无 Swift/真机验证时顺带替换整个宿主实现。

## 明确补丁

### 1. `src/ios/iOS15Compat.swift`

- `sizeThatFits` 与两种 `systemLayoutSizeFitting` 统一进入 `ios15FittingSize`，不再一条返回 raw、另一条返回 high-water。
- 拟合前核对实际 rootView 的宽度约束，避免 fitting 先于 layoutSubviews 时拿新宽测旧 root；保留 collection 全宽真值与坏 proposed width 防御。
- 保留递归防御、宿主 layout、第二次 fitting、无效/近零（<=1）、NaN/Infinity fallback；fallback 使用最后实际接受的高度。
- 大于 8pt 的回缩先记录候选，只有同宿主身份、同有效宽度、当前 collection/cell identity 一致、非 streaming、非 defer、tracking/dragging/decelerating 全 false，且间隔至少 80ms 的两次正测量相差 <=1pt，才接受收缩。
- 高度回弹或候选明显变化会取消/重启确认；配置、身份、宽度变更清候选；异步 retry 另带 hostingRevision，拒绝同 item 内容更新前排队的确认。
- 120ms 一次定向 retry，执行期间保留 scheduled 标记，防止重测自行持续排队。滚动期间不强制收缩，settle 负责消费仍欠的候选。
- 接受收缩后同时清 cell cache/seed、layout cache/precalc、render-qualified memo，再请求布局；不依赖 TextKit，因此 tool/thinking 卡片也可进入此路径。
- 原 `resetIOS15HostingHeightForConfirmedShrink` 保留，现有 TextKit 专用修复不撤销。

### 2. `src/ios/Agent/MessageList/MessageListInfrastructure.swift`

- 删除 V64-CONVERGE 的 `raw >= superFit && !TextKitFresh` 就钉回 superFit 的 ceiling。
- super 已经执行了一次完整 fitting，不能当「上一轮估计值」；无 TextKit 的卡片原先永远没有增长授权来源。
- 保留 compressed/zero-height target 与 fittingSizeLevel，继续在输入端断开旧 H→H+padding 的反馈；保留 TextKit 下界、配置 generation 防护、view graph lifetime/exception 防护及 memo。
- 保留数字诊断字段，hold 为 false，不再伪称 ceiling 是真实增长验证。

### 3. `src/ios/Agent/MessageList/CollectionViewMessageListV3.swift`

- settle 在任何 correction 之前捕获顶部可见 item 身份、旧 frameY 与 offset，而不是 correction 后才取锚点。
- 在单个 isFlushing / suppressContentOffsetAdjustment 窗口内消费宿主候选、现有 markdown correction、deferred heights，并实际 layoutIfNeeded。
- userBrowsing 恢复 `oldOffset + newAnchorY - oldAnchorY`，按当前 contentInsets/contentSize clamp；通过 diffable item identity 重查 indexPath。
- 不全表重建、不全局 cache reset；autoScrolling 的语义不改。

### 4. `MessageListLayout.swift` 审阅结论

不新增锁。保留已修复的 deferred identity remap、新测量取消旧 parked shrink、large shrink 放行、仅实证 DOWN→UP 的 V31 bounce 防御。本次修复的是 deferred 上游测量真相与 settle 下游锚点，不以删除全局保护掩盖问题。

## 测试

新增 `scripts/test_host_stable_shrink.py`：12 项通过（源码契约 + 可执行 Python 状态机 oracle，非 Swift 实现执行）：

1. 505→326 / 679→455 / 1015→679 的稳定低测量可释放。
2. 同一 runloop 重复测量不能算稳定确认。
3. 零、负数、NaN、Infinity 不确认收缩。
4. 拖动/减速/streaming 不释放，停稳后可释放。
5. 低→高回弹取消候选，近似稳定候选可确认。
6. 身份/宽度变更不继承旧高。
7. 生产 guard、缓存逐层失效、有限 retry 契约。
8. 无 TextKit 的合法增长不被 super ceiling 限制。
9. settle 消费非 TextKit host，捕获锚点早于 correction。
10. -31.3/-13/+100 的锚点补偿数学。
11. 同 identity、390pt 固定宽的 long→short→long→short 与每阶段 invalid/近零 fallback；确认前保留旧接受值，确认后 fallback 不回到旧最高值。
12. 两种 system fitting 与 sizeThatFits 均委派同一函数，入口无直接 raw 返回旁路（仅源码契约，不是 UIKit 双入口实际调用测试）。

既有回归：

- `scripts/test_scroll_deferred_identity.py`：12/12 通过。
- `scripts/test_v64r_render_contracts.py`：7/7 通过；宽度断言更新为统一拟合入口，不再要求旧的第二份 raw 路径。
- `scripts/test_v64r_text_layout.py`：源码契约通过。
- `scripts/test_v64r_live_assistant.py`：源码契约通过，Swift 执行跳过。
- `scripts/test_thinking_visibility.py`：源码契约通过，Swift 执行跳过。
- `scripts/test_v64r_autocompress.py`：源码契约通过，Swift 执行跳过。
- `git diff --check`：通过。

未改 thinking 业务可见性、autocompress、搜索逻辑。未声称 XCTest/编译/真机通过。

## 风险与必须验证

- 两次稳定测量仍可能是稳定的错误值；此次候选只降低暂态误判概率，不把 raw 自动提升为绝对权威。
- 去掉 super ceiling 后，需重点检查旧 H→H+padding 是否在某个 representable 内仍有其他反馈路径。若出现单调发散，应修输入链，不恢复无 TextKit 卡片的全局 ceiling。
- 非 streaming/idle 的确认门可能推迟同一消息其他块的修复；有意优先避免 live cell 塌缩。
- 异步确认会多一次局部宿主重测，需检查 fast-scroll 后时延与主线程成本；不做整表 sweep。
- 屏幕锚点只覆盖 settle 同步事务；后续独立异步 attachment 或 snapshot 引起的变化仍需各自锚定，不能声称全生命周期零跳动。
- 顶部可见卡片本身内部高度改变、锚点被删除、越界 clamp 时无法维持卡片内每个字符的原屏幕位置。
- 当前无 Swift 编译器；合入/构建前必须在 macOS 执行编译与可运行测试。按限制本次不触发 CI。

下一轮批准后的真机验收：同主会话冷进入即观察 tool/thinking/text；20 次 85ms/440pt 快滑及停稳；核对同 item raw/accepted/缓存/layout 一致、无卡片消失或重叠；验证合理稳定收缩，不以「日志没 hold」代替视觉通过。另覆盖 streaming、附件异步加载、thinking 展开收起、旋转/分屏、会话切换、搜索结果进入与自动压缩。

## 外部研究交叉审阅（交付前）

已读同目录 `EXTERNAL-LAYOUT-RESEARCH.md`。其独立发现的双入口分叉、下层 lock 与上层 invalidation 不闭合、禁止拿不可收缩高度保护 anchor，与本补丁吻合；ChatLayout 的 item-edge snapshot 思路也支持本次 identity+screenY 的方向。研究另核实 simonbs 的来源实际是 gist `https://gist.github.com/simonbs/457725e218fc85fc765ed770815314df`，并非同名 GitHub 仓库；本补丁直接审阅的是 woxtu 的真实仓库源码。成熟参考没有承诺任意 SwiftUI 内部状态在 iOS15 自动触发 collection 重测，因此本次仍保留显式 pending 收缩消费。外部研究建议的纯 immutable fixture、父高度变化幂等性试验及 containment A/B 尚未实施，不能由 Python oracle 替代。
