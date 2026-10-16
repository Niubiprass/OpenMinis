# 宿主布局与复用只读审查

## 结论与基线

朋友的移植不是简单删除可用性检查：它有完整的 iOS 15 宿主补位和内容高度回传，且 iOS 16+ 明确保留原生路径。不能据此断言它也存在我方当前的空白、重叠、缺字或输入跳字。但旧系统宿主有两个具体正确性风险和一个滚动策略冲突，值得在采用前验证。

- 朋友：`friend-port-audit/repo`，分支 `ios15.6`，已核实 HEAD=`1cda3b422369029fc026d84efc4d2da77962ae8b`，工作树干净。
- 我方只读比较基线：`OpenMinis-push` HEAD=`0960b075448a8879d37bdc16c9d53cd312624af0`。本报告比较的 `iOS15Compat.swift`、`SelectableMarkdownView.swift`、消息列表/基础设施没有工作树改动；已有 ChatInputBar 等未提交改动未用于归因。
- 以下行号均相对各仓库 `src/ios/`。只做静态审查，未编译、未操作手机，未修改两个仓库，未 push。

## 1. 确定风险：合法零高不能覆盖旧高度，空 footer 可能留下永久空白

**代码事实：**朋友 `Shared/IOS15Compatibility.swift:469–474` 的 GeometryReader 回传只接受 `height > 0`；`:515–520` 的主动测量也拒绝零高；`:508–509` 在已有正数 `measuredHeight` 时持续返回旧值。`:463–478` 换内容不清这个高度。与此同时，`Agent/MessageList/CollectionViewMessageListV3.swift:459–464,467–520` 明确允许 footer 没有任何内容且没有 padding，零高是合法状态，不只是测量失败。

因此，已显示的 footer 从正高变为空内容，或者正高宿主被复用于空内容时，即使新的测量正确返回 0，也不能经这两条通路清掉旧高度。列表虽有 footer 缓存清理（同文件 `:2389–2414`），却没有清掉这个私有宿主缓存；重配置仍沿用上述 apply。

**真机未知：**实际会否持久留缝、留下多高，受该 footer 是否继续留在 snapshot、UIKit 是否复用同一个 content view 等条件影响；不是已复现结论。

**关键比较：**这不是“缺少我方 guard”。相反，我方 `iOS15Compat.swift:521–523,603–644` 另有高水位保高/收缩确认，本身也可能延迟收缩，不能据此认定我方更正确。朋友这里的问题是把业务合法的 0 和无效测量统一拒绝。

## 2. 确定复用隔离风险：换消息没有重置宿主状态，也没有隔离迟到高度

**代码事实：**朋友 `Shared/IOS15Compatibility.swift:441–445,463–478` 持有同一个 `UIHostingController<AnyView>`，更新时只换 rootView，没有 item identity，也不重置 `measuredHeight`。四类 cell 都使用同一种 LegacyHostingConfiguration（消息列表 `:1381–1459`）。`:479–500` 的异步回传没有绑定测量时的配置版本/身份/宽度，而是在执行时读取当前 cell 的 contentKey、indexPath 和 collection 宽度。

这使两类跨内容污染有代码路径：

- 相同结构的新消息可保留旧 SwiftUI 局部状态。具体例子不是假设存在某个 State：`Views/Chat/AssistantBlockView.swift:781–783,873,939–947` 确实保存并优先展示 `frozenThinkingContent`；清理只在反向拖动或 streaming 转为 false 时发生（`:976–980`），没有按 block.id 重置。两个均非 streaming、均展开的 thinking block 之间复用时，这些条件未必触发。
- A 的旧高度在新配置 B 绑定后仍可被排队的 publishHeight 以 B 当前身份写入 memo/索引缓存；没有保证“高度对应的内容”和“写入目标身份”一致。后续测量可能纠正它，不能把每次临时错高都称为永久故障。

**关键比较：**我方列表四处传 `config.ios15ContentIdentity(item)`（`CollectionViewMessageListV3.swift:1393,1405,1429,1445`）；我方宿主只对相同 identity 保留图，不同 identity 重建并清空几何（`iOS15Compat.swift:647–712`）。这是明确的身份边界差异，不是 guard 数量比较；朋友的 `SelfSizingCell.applyContentConfiguration` 确实会清 cell 级缓存（`MessageListInfrastructure.swift:130–140`），但这不等于重置内层宿主/SwiftUI State。

**真机未知：**UIKit 实际如何在这些行类型之间复用、是否观察到旧 thinking 内容或错高，需要真机覆盖；不能称为已发生的串消息事故。

## 3. 确定策略冲突：宿主直接写高度，绕过列表的延迟收缩与偏移补偿路径

**代码事实：**朋友 `Shared/IOS15Compatibility.swift:497–501` 直接 `setCachedHeight` 后全局 invalidate，没有咨询 `deferSelfSizing`。而 `MessageListLayout.swift:391–409` 明确将拖动期间的收缩放入 deferredHeights；其 preferred-attributes 路径还有 `:526–556` 的 viewport/bottom pin 偏移补偿。直接写缓存不经过这些处理。`setCachedHeight` 同时标记 geometryReaderConfirmed（`:807–809`），普通 self-sizing 后来还会被 `:423–432` 拒绝，直到显式清除该标记。

另外宿主 `layoutSubviews` 每次都同步调用 `host.sizeThatFits` 并排队 publish（兼容文件 `:511–522`），没有宽度/内容指纹或排队合并；最终是否写缓存虽有差值去重，但测量和排队已经发生。

**评估：**“旧高度确实被替换”是其优点，避免只 invalidate 却保留 layout 缓存；代价是形成第二条高度权威路径，未遵守原列表已有的滚动收缩/锚定约定。可能表现为滚动中重排或增长后追底一拍，而非能够静态证明必然重叠或卡死。长文测量成本与视觉影响尚无此 SHA 的真机数据。不建议直接照搬我方多层补丁；先验证是否应把这条回传接入统一的延迟/补偿机制。

## 4. 明确优点：系统分流、containment 和内容变化传播均有实际实现

- `Shared/IOS15Compatibility.swift:423–427` 在 iOS 16+ 使用原生 UIHostingConfiguration，旧系统才走 Legacy。`SelectableMarkdownView.swift:8752–8753` 同样将 ProposedViewSize 测量限定于 iOS 16+；iOS 15 通过 `:7185–7193` 的 intrinsic 高度补位，宽度不报 unwrapped intrinsic width。这些是合理兼容设计，不能因为没有我方复杂防护就判错。
- 朋友宿主进入 window 后沿 responder chain 找父 VC 并 addChild/didMove，离开时移除 parent（兼容文件 `:524–537`）。我方 `_HostingContentCellView` 创建/替换 host 的 `iOS15Compat.swift:647–713` 没有同等 containment，朋友这一点更完整。这里仅肯定有配对的父子关系处理，不宣称所有 UIKit appearance/移动时序已验证。
- 内容变化并非只更新画面：朋友 `SelectableMarkdownView.swift:8579–8581` 会 invalidate intrinsic 和 cell size；异步附件还会清 memo/Coordinator 尺寸缓存并触发校正（`:7084–7115`）。宿主再经全行 GeometryReader 反馈实际行高。故“bridge 没实现所以必然缺字”不成立。iOS 15 不走 iOS 16 的 sizeThatFits 缓存/离屏测量分支，也不应把那部分保护直接当成 iOS 15 已生效。

## 优先验证

先做三组有针对性的真机用例：①已存在 footer 从正高变零高；②展开并拖离底部的历史 thinking A 滚出，再让另一展开历史 thinking B 复用；③拖动/减速中附件完成或工具卡收缩，同时记录实际行高、缓存高、内容偏移。未覆盖这些前，最准确结论是“移植有可取之处，也有明确待消除的宿主边界风险”，而不是“朋友也坏”或“朋友肯定比我方好”。本报告未审查输入法组合文本链路，不能据这些布局差异解释输入跳字。
