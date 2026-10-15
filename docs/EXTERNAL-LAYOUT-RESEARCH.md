# iOS 15.5 Hosting Collection Cell 外部布局研究

研究日期：2026-10-15。范围：只读本地文件与外部资料，没有修改业务源码、编译或操作手机。源码读取期间工作区已有未提交修改，且 MessageListInfrastructure.swift 内容发生变化，以下行号仅对应读取快照；建议按符号定位。未在 iOS 15.5 实机运行任何外部方案。

## 结论

1. **已可从本地代码直接解释“measured=326，locked=505，停止仍 hold”**：`_HostingContentCellView.ios15FittingSize` 的同宽 `ios15MonoH` 高水位锁，对任何低于最高值 8pt 以上的正高度返回旧最高值，不检查 tracking/dragging/decelerating，也没有空闲自动收敛。日志里的滑动状态仅用于打印。455→679→1015 会使后续正确小高度被拒绝。这是应用自己的持久反馈，不需要假定 UIKit 还在滚动或 item 身份串了。
2. 锁不是每个 item 永久不重置：当前 `apply` 的同 identity 快路径、重建、宽度变化和 `resetIOS15HostingHeightForConfirmedShrink` 都会清它。但同一配置内部 SwiftUI/附件动态变化未必经过 `apply`；在两个 reset 之间仍是不可收缩的历史最大值。`ios15LastGoodFitH = max(...)` 又让零测量回退也偏向历史最高。
3. **不要继续用“高度只能增大”解决 scroll anchor**。成熟聊天布局把“当前真实尺寸”和“因尺寸变化而补偿的位置”分开。永久高水位会把一次错误大值变成终态空白；同时不能修复另一个层的低估导致的截半。短暂保留上一有效值以挡零值是合理防抖，但不等于拒绝有效的负向高度变化。
4. 最值得参考的是：Apple 对 hosting containment 与 iOS16 self-resizing 的明确边界；simonbs 的 iOS14+ backport（小型、可读、非生产聊天引擎）；ChatLayout 的显式 reload/reconfigure + snapshot anchor；MessageKit 的 UIKit/TextKit 确定性测量。它们不是四个可以直接替换 OpenMinis 的 SwiftUI 聊天实现。

## 真实来源与适用限制

### A. Apple 官方：iOS16 才增加自动 self-resizing 集成；hosting controller 必须在 VC hierarchy 内

- WWDC22《Use SwiftUI with UIKit》，已读取页面及 transcript：
  https://developer.apple.com/videos/play/wwdc2022/10072/
- 重点：约 21:50–22:28，ObservableObject 更新导致内容尺寸变化，与 iOS16 collection/table self-resizing 的配合；约 24:33–24:57，`UIHostingController` 必须连同 controller 与 view 一起加入 app，不能只取 view；约 25:01，真正 UIHostingConfiguration 不使用 UIViewController，是不同实现。
- 官方 API：
  https://developer.apple.com/documentation/swiftui/uihostingcontroller/sizingoptions
  https://developer.apple.com/documentation/uikit/uicollectionview/selfsizinginvalidation-swift.property
- 边界：iOS16 的 `.intrinsicContentSize` sizingOptions / 自动 self-sizing invalidation 不能当作 iOS15 已有能力。本地 shim 叫 UIHostingConfiguration 不会获得系统实现的内部传播机制。Apple 的 containment 要求并不证明缺 containment 就是这次高度膨胀的唯一根因。
- 本地对照：`iOS15Compat.swift` 的 `apply` 创建 controller 并 `addSubview(controller.view)`，未见 `addChild` / `didMove` / 成对 `willMove`、`removeFromParent`。这与官方 controller 使用规则及下面 backport 不同，应在独立最小试验检验，而非直接宣布修复完成。

### B. simonbs/SwiftUIHostingConfiguration：真正看过的 backport 源码

- Gist（README + Swift 源码均已读取）：
  https://gist.github.com/simonbs/457725e218fc85fc765ed770815314df
- iOS14+，UIContentConfiguration 包装 UIHostingController；初始化接受 parentViewController（weak），明确 containment。`configuration.set`：更新 rootView，remove hosting controller → add hosting controller → `invalidateIntrinsicContentSize()`。
- 源码原注释直接说明：remove/re-add 再 invalidate “seems to be the only way” 让 collection/table relayout 更新高度。增加：`parent.addChild`、四边 layoutMarginsGuide 约束、`didMove`；移除：`willMove(nil)`、remove view、removeFromParent；deinit 清理。
- 没有历史最大高度锁，也不是依靠固定 estimated height 来掩盖变化。
- 限制：这是演示级 gist，不是经过动态 Markdown、附件、thinking/tool 流式混排验证的聊天框架；其 configuration 更新路径不等价于任意内部 `@State`/ObservableObject 变化都自动回传 UIKit。每 token remove/add 可能过重，只适合先作为隔离基线，不能盲目移植。

### C. SwiftUIBackports：项目真实，但不能把名字当成熟聊天尺寸保证

- 已克隆并读取 commit `eaeff429ac1ae625179e784680e63e05c2171786`：
  https://github.com/shaps80/SwiftUIBackports/blob/eaeff429ac1ae625179e784680e63e05c2171786/Sources/SwiftUIBackports/iOS/UIHostingConfiguration/UIHostingConfiguration.swift
- 其 `makeContentView` 返回 `UIHostingController(..., ignoreSafeArea: true).view`，用自有 `BackportUIContentConfiguration`；有 background/insets/minSize 数据，其中 minSize 方法在此文件被注释。
- 限制：此文件没有呈现完整的动态高度回传/anchor 机制；不是可以只复制一段就认定等价系统 UIHostingConfiguration 的证据，也不能把 ignoreSafeArea 当本问题已证实答案。未在本报告全面审计其自定义 configuration 基础设施。
- “HostingCollectionView” 精确名称的 GitHub repository/readme 搜索与网页搜索未找到可确认的目标。**未把不明同名类型或示例包装类冒充成熟库**；若后续有确切仓库地址才适合专项对照。

### D. ChatLayout：成熟 UICollectionView 布局，不是 SwiftUI hosting 尺寸引擎

已克隆源码，固定 commit `dd4cb5c8f91623331ba023d0ab64d844f8436204`：

- 布局、失效与 anchor：
  https://github.com/ekazaev/ChatLayout/blob/dd4cb5c8f91623331ba023d0ab64d844f8436204/ChatLayout/Classes/Core/CollectionViewChatLayout.swift
- 尺寸协议（auto / estimated / exact 的区别）：
  https://github.com/ekazaev/ChatLayout/blob/dd4cb5c8f91623331ba023d0ab64d844f8436204/ChatLayout/Classes/Core/ChatLayoutDelegate.swift
- 实际 cell 的 preferred fitting 交接：
  https://github.com/ekazaev/ChatLayout/blob/dd4cb5c8f91623331ba023d0ab64d844f8436204/ChatLayout/Classes/Extras/ContainerCollectionViewCell.swift
- 实际 UIKit 聊天 controller：
  https://github.com/ekazaev/ChatLayout/blob/dd4cb5c8f91623331ba023d0ab64d844f8436204/Example/ChatLayout/Chat/View/ChatViewController.swift

具体机制：

- 支持约束驱动自测，也支持 delegate 提供尺寸；若已经提供确定尺寸，协议提醒不要再在 preferred fitting 调 super 做多余 UIView 测量。不是将“精确测量”和“系统估测”同时无限竞争。
- `supportSelfSizingInvalidation` 标为 iOS16+、experimental；文档反而推荐在多项同时动画变化时使用显式 reload/reconfigure，以保持 offset 一致。**不能在 iOS15 简单打开此开关解决问题。**
- `getContentOffsetSnapshot(from: .top/.bottom)` 保存边缘附近 item 的 indexPath、edge 和相对可视边界 offset。`restoreContentOffset` 触发布局与 context invalidate，由布局保存位置；不是把旧高度变成下界。
- 源码有 content-size 先缩小再增大的讨论，及 animated batch 只处理可视项的控制项，说明其模型允许收缩，并正面处理 offset 修正代价。
- snapshot 原生标识是 indexPath，不是业务 UUID；跨插入/删除或 diffable 更新必须保证映射正确，不能无脑拿旧 indexPath 恢复。OpenMinis 若借鉴应保存 itemID，再在新 snapshot 查 indexPath。
- 限制：换 ChatLayout 能替代布局/anchor 这一层，但不能纠正 host 自己返回错误高水位；仍要修复输入尺寸。当前 master 的 API/工具链需求须按选定 release 核对，不能直接承诺整库可在现有 iOS15 工程无改动编译。

真实 GitHub issue（已浏览正文与维护者回复）：
https://github.com/ekazaev/ChatLayout/issues/23

该 issue 的 iOS15 `UICollectionViewRecursion ... Disabling recursion trigger logging` 最后被说明是 Apple 遗留 logging，不是需要修的无限循环证据。**不要把仅有这一日志当作本案高度 bug 根因。** 它与下面真正抛出异常的循环不同。

### E. MessageKit：确定性 UIKit/TextKit 测量可借鉴，不是 SwiftUI 桥

已克隆 commit `381c08045dac8865005efba010d2b2f4ad917e03`；该快照 Package.swift 声明 iOS14：

- 文本尺寸：
  https://github.com/MessageKit/MessageKit/blob/381c08045dac8865005efba010d2b2f4ad917e03/Sources/Layout/TextMessageSizeCalculator.swift
- TextKit 的实际 labelSize：
  https://github.com/MessageKit/MessageKit/blob/381c08045dac8865005efba010d2b2f4ad917e03/Sources/Layout/MessageSizeCalculator.swift
- cell 配置与复用：
  https://github.com/MessageKit/MessageKit/blob/381c08045dac8865005efba010d2b2f4ad917e03/Sources/Views/Cells/TextMessageCell.swift

具体：根据 message/container 可用宽减去 label insets，按 font/attributedString，设置 NSTextContainer 约束盒；replace textStorage → layoutManager.ensureLayout → usedRect → 宽高向上取整，再加 padding。`TextMessageCell.apply` 用 layout attributes 将 messageLabel.frame 设为 container bounds；prepareForReuse 清 attributedText/text。测量和显示有明确同源参数，不把前一个 cell 历史最大高度保留下来。

限制：普通文本的 TextKit usedRect 不能直接替代当前自定义异步 Markdown attachment 最终布局；thinking/tool 卡必须有各自 calculator 或 UIKit 约束；MessageKit 不是“已解决 SwiftUI hosting”的证据。键盘输入栏位置保持也不等于流式高度锚定，不应混用。

### F. 技术讨论：确实存在 iOS15 自适应循环，但各方案针对不同布局

- 原问题及全部 answers 已从 StackExchange API 读取：
  https://stackoverflow.com/questions/70213395/self-sizing-collection-view-enters-a-recursive-loop-in-ios-15
- 一个回答针对手动计算尺寸的项目关闭 Estimated Size；另一个是给所有垂直 flow cell 提供固定宽、低 vertical priority 的 preferred fitting；还有直接 shouldInvalidate=true 的回答。**三者不是可以叠加的通用修复。**
- 原问题有 collectionView 的 intrinsicContentSize=contentSize，contentSize 改变再 invalidate 的反馈结构，iOS15 触发 “stuck in its update/layout loop / preferred attributes not returning a consistent size”。这说明应验证同输入幂等和单一测量权威，但没有证明 OpenMinis 是相同循环。
- 该讨论引用 Apple forum： https://developer.apple.com/forums/thread/694141 。实际打开被 Security Verification 拦截；未读取原文，不将引用内容算 Apple 已确认。
- 深入 hosting 技术文章（已浏览）：
  https://noahgilmore.com/blog/swiftui-self-sizing-cells
  展示 `sizeThatFits` 对带无限高度布局返回 0、`.fixedSize(horizontal:false, vertical:true)` 的有限适用场景，以及 rootView 更新后的 intrinsic invalidation、parent-child containment 对复用错误高度的重要性。作者也记录 iOS14/Xcode12 safe-area/键盘回归并警告生产使用风险。
- 限制：该文主要是 2020 年 UITableView/iOS13–14，不能当作 iOS15.5 UICollectionView 的实机修复保证；不要把 fixedSize 全局贴到包含内部 scroll/tool 的任意树。

## 与 OpenMinis 读到的结构逐项对照

- `SelfSizingCell` 至少有 lastComputed、seeded、layout memo 等缓存入口；`clearCachedHeight()` 清 cell cache，不等于清 `_HostingContentCellView` 的 MonoH。只修上层 invalidation 后，下层仍可合法返回旧锁值，属于“两层 invalidation 不闭合”。
- `sizeThatFits` 和 `systemLayoutSizeFitting` 在本地不是同一语义：前者直接返回 ceil(raw)，后者进入 lastGood/max/mono；于是同 item、同宽、同版本可能由不同调用入口得到不同高度。应在日志中明确入口，不能混称 measured。
- host 四边贴父、测量又先 `host.view.layoutIfNeeded()`，应排查当前父 bounds 对 SwiftUI/UIViewRepresentable 布局提议的影响；这只是反馈风险推断，不是已证明 455→679→1015 的起因。
- 身份快路径已经使用 message/block identity，且 apply 清锁；当前证据不足以把问题都归为 reuse 串 item。应把 itemID、host pointer、generation 与 width 一起验证。
- 本地注释出现 FB13213926/iOS27 的防重入策略，这是代码自身说明，不是这次研究核实过的 Apple bug；不能直接把针对新系统的所有短路推导成 iOS15 必需。

## 最小试验（建议清单，尚未实施）

### 试验 1：证明持久 hold 是否独立于 UIKit/复用

独立诊断页，仅 30 条 immutable 快照数据，固定完整可用宽；类型按长文本、thinking 展开/收起、tool 终端展开/收起交错。先不用 Markdown attachment、动画和 streaming。只留一个高度权威；关闭多层 seeded/memo/滑动短路，作为隔离实验而非线上直接删除防护。

输入序列：同 item 同宽依次 long→short→long→short；再固定 short，快滑往返；同一 cell A(长)→B(短)→A。对每轮记录 itemID、content revision、host/cell pointer、width、raw、lastGood、locked、returned、layoutAttributes.height、bounds.height。

A/B 只改一项：A 保留 MonoH；B 不对有效正高度做 max，仅暂时保留 invalid/zero 的 last **accepted** 值。停止后下一 layout transaction 必须允许负向高度变化。预期：若 raw 始终短而 A locked 长、B 收敛，就证明终态空白来自持久锁；若 B raw 仍阶梯增大，则继续排查测量反馈，不能宣告全部修复。

### 试验 2：同宽幂等性与“双入口分叉”

无 model 更新时，同一 host、相同 layout width，分别记录 sizeThatFits / system fitting 的原始值与最终值；对相同 revision 重复询问，跨当前不同 bounds.height（例如 326、505、1015）比较。不要在一次 UIKit preferred fitting 内递归测全部路径，可在独立离屏 fixture 分轮执行。

期望：固定内容固定宽的 accepted height 不应依赖历史 bounds 或询问次数。若 raw 随旧 bounds 变化，查 root 的 maxHeight infinity、GeometryReader、UIViewRepresentable size/layout、safeArea/attachment 回写；若只有 final 变化，查锁与缓存。尽量统一两入口的测量规范，再考虑 memo。

### 试验 3：真正 controller containment 的差异

使用 simonbs 最小版本作为单独实验组，明确 addChild/didMove 与对应移除；同数据同宽，先只显式配置更新，再测试内部状态变化。比较“只 invalidate”与“配置更新时 remove/add + invalidate”，不加入高水位锁。测量次数、CPU、reuse 后状态归属与 anchor 同时记录。若通过只能证明此最小树有效，再逐个加入 TextKit、attachment、thinking、tool，不一次装回全部复杂子树。

### 试验 4：把位置保护与高度验收分开

用户离底时保存稳定可见 itemID + 其相对 viewport 的 y；批次更新/高度变化前后恢复同 item 的相对 y，不调用 scrollToBottom。用户贴底时才保存 bottom gap 并跟随末端。合并同 runloop/一帧的尺寸事件，一次明确 invalidation；不能为了防跳拒绝真实收缩。至少覆盖拖拽/减速中、停住后、prepend 历史、tool 337→47、thinking 折叠、宽度变化。

验收：停止后 raw/accepted/layout/bounds 收敛（容差约一像素到 1pt，含明确 padding）；没有持久负债/盈余；任何同 revision 同宽的高度不得随访问次数单调膨胀；anchor drift 有预先规定阈值（例如非交互时 ≤1–2pt）。

## 替代结构与取舍

1. **最小长期风险：iOS15 的关键动态行改 UIKit，SwiftUI 保留稳定卡片/外壳。** 文本用同一 TextKit 渲染与测量配置；tool/thinking 做约束明确的 UIKit view；高度按 itemID+render revision+width+font/contentSizeCategory+展开状态+附件完成状态缓存，允许双向更新。参考 MessageKit 的 calculator，而非移植其全部消息模型。成本是 UIKit 重写，但可摆脱 UIKit↔SwiftUI↔TextKit 三层循环。
2. **保留 SwiftUI：标准 containment + 单一 hosting 测量路径 + 显式尺寸失效事务。** 高度变化源可由已知内容 revision/附件完成/展开事件触发，而不是每次布局都改 model；先证实纯 Text 基线再增复杂度。未知树内容仍可能异步需要二次测量，不能保证一次 sizeThatFits 得到最终结果。
3. **布局层试用 ChatLayout，但先修 host 高度权威。** 用它接管 batch、estimated/exact 与位置补偿，避免自建多套 anchor/cache。不是立即替换就能消除 UIHostingController 的坏输入；要先锁定兼容 iOS15 的 release/Swift 版本、diffable/indexPath 映射与性能成本。
4. **单个纵向栈/UIScrollView 或纯 SwiftUI ScrollView 只作为对照。** 能去掉 UICollectionView reuse/invalidation 变量，有助判断宿主问题，但 iOS15 大聊天历史、内存、滚动定位能力另有风险，不是已经验证的生产替代。

最优先证伪顺序：同 revision 固定宽的 raw 是否稳定 → 下层 MonoH 是否覆盖正确 raw → 上层 cache 是否再次覆盖 → anchor 是否独立补偿。不要再把四个问题揉成一个“防抖高度锁”补丁。
