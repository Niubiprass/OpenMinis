# 主会话滚动异常只读审查

## 范围与结论

- 目标：真机 160644 的主会话 `72422CEC-EDE6-4137-A703-0886EFFBF099`。源码：`/var/minis/workspace/OpenMinis-v64`；证据：`workspace/test-160644/main-*.json`。本报告不以新建会话的结果替代主会话验证。
- 本轮仅读取源码和已有文件，未操作设备 UI、未修改源码、未读取配置密钥。唯一新增文件是本文档。目录不是 Git 仓库，无法用 Git 核验现有修改；行号对应审查时磁盘版本，不保证与已安装二进制完全一致。
- **不能据现有证据认定全部异常已修复，也不能认定主会话这几轮已经复现了实际卡片互相覆盖。** 现有 UI 树体现滚动确实到达不同历史区段；472 字 thinking 成功展开并在往返后保持展开。与此同时，存在实测宿主高度高水位拦截、复用后的同内容候选行高度变化，以及数个可以精确验证的代码风险。
- 最高优先级：①非 TextKit 动态卡被通用 `V64-CONVERGE` 增长闸错误拦截的条件；②宿主单调高度锁把合法收缩当抖动；③延迟高度按 index 存储而未随快照重排/清理；④settle 保存数值 offset 而非 item 锚点。它们更符合长历史、多工具、活跃子代理、反复复用的主会话负载，而不是单条长正文问题。
- 已定位的 `Shared/NSTextContainerSetSizeGuard.m` 中 `>=3000 → 2000` 限高属于独立长文问题；本报告不把它当作全部卡片滚动异常的解释。

## 一、证据能证明什么

### 1. 主会话并非纯文本测试

`main-up-ui-1/2.json` 的动态工具导航为 `工具调用 46 / 74`，`main-round-ui-4.json` 已为 `75 / 75`；有运行中子代理及其执行预览。说明本轮确实是在大量真实动态卡片的工作会话里检查，且测试动作本身还使工作会话继续增加工具卡。

### 2. 真实 thinking 的展开和复用

`main-scroll-log.json`：

```text
18:25:50.807 tap block=A1805373 wasExpanded=false streaming=false contentLen=472
18:25:50.822 post block=A1805373 expanded=true userToggled=true streaming=false
18:25:50.857 HIT block=A1805373 idx=78 cellFound=true frameH=40.0
18:25:50.861 POST block=A1805373 idx=78 frameH=250.3 layoutCache=250.3 delta=210.3
```

因此此次手动展开通知确实命中当前 cell，至少当时 cell 与 layout cache 同步增长，不是只改变箭头。

UI 树中对应 472 字 thinking：

| 文件 | 候选全宽行 y / h | thinking 正文 rect 高度 | 状态 |
|---|---:|---:|---|
| `main-expanded.json` | 318 / 250 | 201 | 展开 |
| `main-round-ui-2.json` | 421 / 284 | 201 | 展开 |
| `main-round-ui-4.json` | 484 / 284 | 201 | 展开 |

正文文本及计数可对应，往返之后仍展开；外行候选高度却比初次展开多约 34pt。这是**值得定位的高度漂移信号**，不是已证明的视觉重叠。匿名 AX element 没有稳定 item 标识，需真实 cell/布局数据进一步确认。

另一个运行中子代理对应的候选全宽行在这些证据中约为 58、84、92pt；由于它是真实动态内容，不能仅据高度变化认定缓存错误。

### 3. 存在真实宿主高度拦截

日志有唯一一条：

```text
18:25:16 [V64R-HOST-HOLD] idx=91 measured=202.0 locked=314.0
```

这证明一次 fitting 的高度 202 被高水位 314 拦住，差 112pt。不能从 index=91 反推固定卡片身份，也不能仅凭这条证明 202 一定正确；但它直接证实了“测量收缩却继续保留更高宿主高度”的路径在本轮发生，不是纯静态猜测。

### 4. 日志覆盖有明显限制

`main-scroll-log.json` 共 160 行，是采集命令用 `V64R|CONVERGE|ThinkingCollapse|MEMWARN|surplus|V53-SHORT` 过滤后的尾部。缺少 Settle、PendingSnap、ScrollDiag、ReflowGap 等，不代表这些路径未发生，也不能据此宣称没有掉帧或 suspend 泄漏。

其中 `V64-CONVERGE` 114 条；逐条比较后，没有一条显示 `recomputed > est + 0.5`。本轮保留下来的记录不能直接证明它拦掉了真实增长。

`V53-SHORT` 汇总里 dedup 从 3018 到 4025，seeded 从 79 到 80，window/live 为 0。这是进程级短路计数；`live=0` 不是全局“没有真实测量”的证明。成功展开本身就有高度重算。

### 5. 避免错误的重叠判读

- `visible_only=true` 仍返回 y<91 或 y>696/844 的子元素；外层聊天内容还被导航栏及底部面板遮挡。AX 返回 rect 不等于最终绘制可见区域。
- thinking 的内嵌 ScrollView 有独立裁切边界；内部全文 rect 不能与下一张卡的 rect 直接求交并宣称覆盖。
- `main-round-ui-4.json` 中候选行依次约为 `(60,49),(117,40),(164,212),(384,92),(484,284),(777,62)`，外行间隔约 7–9pt，未显示候选外行相交。其他抓取的候选全宽行也未显示相交。这只能说这些离散快照没有该类几何证据，不能排除两次抓取之间的瞬态问题。
- 底部工具执行预览/输入面板与聊天内容在屏幕坐标上相交可能是设计遮挡，不是 collection cell 互相覆盖。
- `main-screen.json` 是 base64 图片容器；本轮未进行像素级图像判读，不把它声称为已验证的截图重叠证据。

## 二、身份与复用：已有防线和剩余空隙

### 已确定的防线

1. `MessageListInfrastructure.swift:21–39`：diffable item 身份包含 case、message UUID、block UUID，不用行号充当身份。
2. `CollectionViewMessageListV3.swift:1342–1444`：四类配置统一走 `applyContentConfiguration`，并传入 `.ios15ContentIdentity(item)`。
3. `iOS15Compat.swift:548–617`：同 item 才复用宿主图；换身份重建并清零宿主高水位与 lastGood。当前源码已经不是“不同卡无条件共用 SwiftUI 状态”的实现。
4. `MessageListInfrastructure.swift:862` 起：复用清除 lastComputedHeight/Width；不主动销毁 contentConfiguration 是规避宿主图生命周期崩溃的有意策略，不能把这一点单独认定为漏清理根因。
5. `AssistantBlockView.swift:804–808`：thinking 展开状态存于 block model，而不是 cell 本地 @State；此次往返保留展开与此一致。
6. `CollectionViewMessageListV3.swift:1493–1544,4093–4112`：活跃助手集合包含最新 assistant 和更早仍有 running/streaming 工具的 assistant，避免只排除尾消息的旧错误。

### 剩余风险：身份稳定不等于高度稳定

`contentKey`（同文件 `4157–4176`）对 block 仅编码 message UUID、block UUID、`content.count`。没有编码 thinking 展开状态、工具状态、终端预览形态或子代理卡状态。`renderQualifiedKey`（Infrastructure `837`）仅在子树含 MarkdownTextView 时加异步附件信号；纯 thinking Text、普通工具胶囊通常没有此信号。

因此相同内容长度但不同展示形态可命中相同 memo。thinking 手动切换已有专门全变体失效及 reconfigure（V3 `2844–2917`），此次已证实它工作；不能再泛称 thinking 完全没有失效路径。工具和子代理则需逐类核验同等展示形态变化是否有对称失效，不能仅依靠长度键认为安全。

此外 `liveAssistantMessageIds` 开头有 `guard isProcessing else { return [] }`。如果主助手结束后子代理卡仍能变化，整消息会被视为静态历史并允许播种。**代码条件明确存在，但本轮没有证明主助手 false、子代理仍变高这两个条件同时出现。**

## 三、按优先级排列的代码问题与假设

### P0：通用收敛闸不能区分“非 TextKit 的合法增长”

位置：`MessageListInfrastructure.swift:727–766`。

实质条件为：

```swift
let grew = reconciled >= attrs.size.height - 0.5
let tkFresh = foundMarkdown && tkSum > attrs.size.height + 0.5
if grew && !tkFresh && attrs.size.height > 4 {
    reconciled = attrs.size.height
}
```

注释宣称真实增长必有 TextKit 权威测量，但 thinking 是 SwiftUI Text，工具/子代理是组合 SwiftUI 视图，并不保证有 SelectableMarkdownTextView。对这些行 `_ios15Found=false`，`tkFresh` 必定 false；当该比较基准仍旧而 fitting 已增长时，会把合法新高度压回比较基准，再记入 cell cache/memo。该闸没有限定“仅 Markdown 文本块”或核对动态状态版本。

注意 `attrs` 来自 `super.preferredLayoutAttributesFitting`，并非保证等于最初 layout estimate；日志里的 est 也不能直接当原始布局高度。这也是必须同时记录 incoming/super/fitting 三个数的原因。

**分级：确定存在的错误判据/可达风险；尚非本轮真实增长被拦的直接证据。** 此次 114 条 hold 都没有严格增长值，不能用它们偷换为已复现。472 字手动展开成功也说明该闸并非每次都挡住非 TextKit 增长。

主会话放大条件：动态卡种类多、展示形态频繁变、历史卡回滑重挂载，且部分形态变化不改变 content 长度；单纯新建短正文很难覆盖。

### P0：宿主高水位锁有合法收缩保留风险

位置：`iOS15Compat.swift:505–543`，同宽下实测比历史高水位低 8pt 以上，保留历史最高值；差超过 80pt 才记录 HOST-HOLD。

同 identity 的重新 apply、宽度变化、以及明确确认收缩的 reset 都能清锁，不能把它说成永久不可解除。但是 block 的 @ObservedObject 状态直接更新并不必然触发 contentConfiguration 重新 apply。卡片 live preview 结束、运行状态栏消失等合法收缩可能只改变 SwiftUI 内容，从而触发高水位保留。

**分级：本轮确定发生一次 202→314 的拦截；是否是合法收缩、对应哪一块，待补身份和状态。** 主会话大量终端/子代理过渡使它比静态新会话更容易触发。该路径更直接解释留白和视觉位置跳变，不能单独证明卡片相互覆盖。

### P1：延迟高度仍是 index 身份，没有随快照重排或会话清理

位置：`MessageListLayout.swift:324,343–363,425,840–868,993–1006`。

- `deferredHeights: [Int: CGFloat]` 在拖动时保存小幅收缩（不大于 50pt）。
- `updateCacheForSnapshot` 按 MessageListItem 重排 heightCache/precalc/estimated，却没有重排或清空 deferredHeights。
- `clearHeightCache` 也没有清空 deferredHeights。
- settle 的 applyDeferredHeights 直接把旧 index 的高度写到当前 heightCache。

**分级：确定的状态一致性缺口；本轮是否发生错写未证实。** 典型触发序列是旧快照 idx=i 的 A 暂存收缩 → 结构变化使 idx=i 对应 B → settle 把 A 的高度写给 B；可导致卡片被错误裁切、空白或布局位移。正常 settle 先 flush 高度再恢复 UI 更新能降低概率，但通知驱动的 reconfigure、异常会话切换/取消交互以及未清理状态仍需核验。只有尾部 append 且目标 index 不变时，不应泛称它必然错写。

### P1：settle 的数值 offset 恢复不保住内容锚点

位置：V3 `5823–5920`，Layout `332–388`。

settle 先恢复 self-sizing、消费 Markdown 延迟纠偏，再抓 anchor，flush deferred heights，恢复原 contentOffset.y；没有根据同一 item 的 frameY 差补偿 offset。源码自己已有 `SettleJitter[settle-shift]` 记录这一点。

当视口上方行缩短，恢复同一个数值 offset 会显示不同内容。锚点还是 indexPath，不是 item；并且抓锚点之前已消费一批 Markdown 纠偏，日志可能漏掉那一阶段位移。恢复 suspension 后的 pending snapshot 是下一次异步更新，也不在本次 flush 的锚点检查闭环里。

**分级：可确定的条件性跳动路径，未有本轮 settle-shift 数值证据。** 它解释“松手后跳到别处/看起来消失”，不能等同于主线程卡死。

### P2：性能负载与恢复链需要原始时序，不能由计数定罪

V3 `2637–2699`：浏览时文本批刷新节流为 3 秒；dirty 更新仍会走 applySnapshot 并再 reconfigure。V3 `3133` 起快照估算遍历所有 item，部分 block 查找又线性扫 message.blocks；Layout prepare 也是全列表工作。活跃消息每次快照会清掉它的全部 item 高度，即便大部分工具已经完成。

在很多卡集中于同一活跃 assistant 的主会话里，失效范围与查找成本会放大；但不能把“74/75 个工具计数”直接当该 assistant 的 blocks 数或每帧测量次数。还需证明 UI 卡顿时间与全表刷新、测量、日志 I/O 同步。

`MessageListInfrastructure.swift:49` 的 contentView 裁切和 iOS15 hosting 裁切意味着短 cell 可表现为文字消失，而不是外溢；必须分别测出 cell 变短、内容未绘制、相邻 frames 真相交，避免把三种症状混为一种。

## 四、下一轮精准诊断建议（本轮未执行）

### A. 必须仍用该主会话，不再以新会话通过结案

保留相同 session UUID，覆盖：有 running 子代理时回滑 → 同一历史工具卡离屏再进入 → 472 字块展开 → 跨过子代理/工具卡 → 往返 → 主助手停止但子代理仍变化。将手势起点分别放在聊天空白/工具行与 thinking 内部，以区分外层 collection 滚动和内层 ScrollView 正常消费拖动。

测试动作通过主会话工具执行会新增卡，应记录每轮 snapshot revision、item 总数与活跃消息，不能假定往返前后数据完全静态。

### B. 先补一条统一的无正文诊断轨迹，而非再加刷新补丁

每个可疑 item 使用稳定身份：`sessionId + messageId + blockId + kind`；记录 cell 实例标识与 host 实例标识。全部探针只输出 ID/长度/枚举/数值，不输出正文、工具参数、命令、URL、密钥。

在 configure、reuse、PLAF、host fitting、layout invalidation、defer/flush、snapshot、settle 前后记录：

- monotonic timestamp、snapshot revision、index 与其当前 item 身份；
- incoming layout H、super 返回 H、raw fitting H、TextKit found/tkH、reconciled H、final H；
- host monoH/lastGoodH 与是否 reset；cell lastComputed/seeded；layout cache/precalc/memo key/height；
- `isThinkingExpanded`、toolStatus、preview 可见形态、子代理状态、isProcessing、liveAssistant 命中与否；
- tracking/dragging/decelerating、deferSelfSizing、streamingUIUpdatesSuspended、hasPendingSnapshot、scrollMode；
- cell frame、layout attr frame、内容裁切后的屏幕 frame、contentOffset/contentSize。

### C. 四个可一锤定音的判据

1. **收敛闸误杀**：同一非 Markdown item 的 raw fitting 比 incoming/比较基准大，tkFound=false，final 被闸压回，并且相应 cell 内容需要更多高度。记录首个发生者，不用仅有 est=recomputed 的日志充数。
2. **高水位合法收缩**：同一 item 的状态明确从 preview/open/running 变为 compact/completed，raw H 降低，hostH 被 mono 保高；reconfigure/reset 后能恢复合理紧凑高度。由此与瞬态错误低估区别开。
3. **deferred 错身份**：入队记录 itemA/revision，flush 时同 index 对应 itemB 或 revision 变化且未重映射；只要 A≠B 即是错写证据。再检查会话切换后是否仍有旧 deferred 项。
4. **settle 锚点漂移**：用 MessageListItem 取同一个 top anchor，从 consumeDeferredCorrection 之前到恢复 snapshot 完成后的多个 runloop 连续记录 screenY；同时分解上方高度变化与 offset 变化。不要只在 flush 内抓一次 index。

### D. 将“卡住”区分为四类

- 手势被 thinking 内层正常消费：外层 offset 不动、内层 offset 动。
- 自动 pin/恢复逻辑反复拉回：外层 offset 动后被代码改回，主线程心跳正常。
- cell 高度/布局不一致导致消失：scroll offset 继续动，但可见 item 的 frame/cache/content 不一致。
- 真正主线程 stall：CADisplayLink/主线程心跳有持续缺口，且可关联测量或快照耗时。捕获 app 原始日志中 ScrollDiag、Settle、PendingSnap、ReflowGap、CellSizing、HOST-HOLD 的同一时间窗，不再沿用本次过滤条件。

获取 snapshot 前后实际 UICollectionViewCell/layoutAttributes 数据，验证相邻 item frame.maxY 与 next.frame.minY；thinking 内容先与内层 clip rect 求交，再与 cell/外层 viewport 交。只有不同 item 的实际可绘制区域相交，才报真实重叠。

### E. 通过标准

在主会话完成相同卡片的至少三次离屏复用与四轮往返后：稳定内容和展示状态的 cell 高度不漂移；状态变化后最终高度收敛；不存在 deferred 身份错写；浏览模式的 item 锚点在各个恢复阶段保持；无持续 suspend/pending 残留；视觉证据与 cell 几何相符。长文限高问题另设测试，不与此组通过标准混淆。

## 最终判断

现有证据已排除“本轮只测了新会话纯文本”的说法，也不支持“手动展开完全没有触发外层高度更新”。它尚不足以给主会话卡住、消失、重叠的全部症状指定单一根因。最有价值的实测异常是宿主 112pt 高水位保留，以及同一 472 字展开块回滑后的候选外行增高约 34pt；最明确的源码缺口是非 TextKit 增长闸判据与未随身份重排/清空的 deferredHeights。下一步应以这两类状态链的身份化日志定位首个错误写入，而不是继续扩大刷新频率或把正文 2000pt 限高修复当作整体验收。

## 2026-10-15 补记：连续快滑证据与确定性状态修复

本节更新前述“只读审查”的阶段性结论：本轮确实修改了下述源码，但没有操作手机、没有构建/安装/推送。用户实际触发为**快速滑动期间卡片错位/重叠，随后大量空白**，不能用静止快照没有外行相交、或者本机未复现，判定问题不存在或验收通过。

### 新证据与边界

- `workspace/test-160644/burst-0..11-gesture.json` 为连续 12 手势；UI/截图保留在 `burst-{2,4,6,8,11}-{ui,screen}.json`，日志为 `burst-scroll-log.json`。这些是既有采集，本轮未触碰设备。
- 日志 18:38:16.013 flush 两项，insideΣ=-12.7（idx136 -3.7、idx137 -9.0）；18:38:16.015 settle anchor idx133 screenΔ=+12.7，frameY 11262→11262、offset 11560→11547。这次可见位移伴随 offset 改变，不能直接归因于锚点上方 frame 收缩，也不能证明延迟错身份。
- `HOST-HOLD` 多次 idx126 measured=303 locked=483（保留180pt）、idx129 measured=247 locked=381（保留134pt）。反复滚动 cache 行数 36→45→56/70 增长值得跟踪，但新行被首次测量也会增加 cache；仅凭计数不证明泄漏或所有空白根因。旧日志只有 index，不能把同一 index 当稳定卡片身份。
- 另有委派方新增 18 次 85ms/440pt、steps8 快甩，分组证据 `fast-0..2-ui.json` / `fast-0..2-screen.json`（每6次保留一次）。这些静态采样不覆盖全部离屏复用/减速中间帧，本轮不声称已做像素重叠判读，更不声称修改后的真机快滑已通过。

### 实际补丁

1. `src/ios/Agent/MessageList/MessageListLayout.swift`：保留当前 index 索引接口，但 `updateCacheForSnapshot` 用完整 `MessageListItem`（case/message UUID/block UUID）将旧 `deferredHeights` 与其他高度缓存一起安全映射到新 index；删除 item 的延迟值自动丢弃。prepend/reorder 不再把 A 的待消费高度写进当前同 index 的 B；尾 append 保留未移动身份的高度。`clearHeightCache` 同时清空延迟值，避免跨会话/宽度或字体重置后旧值残留。
2. 同文件补时序一致性：`invalidateHeight`、新接受的 preferred 高度（`invalidationContext`）及直接 `setCachedHeight` 均取消同 index 的旧延迟值。快滑期间 A 先暂存小收缩、后接受真实增长/大纠偏时，settle 不再把旧收缩覆盖回来。保持原有浏览期小收缩延迟、大收缩/增长即时应用策略；未改 settle 的 offset/anchor 算法。
3. `MessageListInfrastructure.swift`：新增 `MessageListItem.scrollDiagnosticID`，对 case+UUID 身份用确定性 FNV-1a 生成十进制 UInt64；不输入正文/contentKey，非 Swift hashValue。仅用于诊断，哈希理论可碰撞，不用作实际缓存身份。cell 在 configure 时保存该值、reuse 时清零。`V64-CONVERGE` 保留原闸门决策，增加 item/cell 数字ID、idx、incoming（调用super前保存）、super（结果被原地改写前保存）、raw fitting、reconciled、final、tkFound/tk、hold、generation。hold 或 reconciled 与 super 差>0.5 时记录；这不是每次短路PLAF的全量轨迹。
4. `CollectionViewMessageListV3.swift`：仅在 configureCell 入口给 cell 绑定 `item.scrollDiagnosticID`，不改配置/刷新策略。
5. `iOS15Compat.swift`：`HOST-HOLD` 用宿主持有的 `contentIdentity` 算 item ID，并同时记录 cellItem ID（有助发现复用窗口身份不一致）、host/cell 数字实例ID、idx、incoming target H、raw、fallback后的 measured、lastGood、locked/final、width 和 tracking/dragging/decelerating。宿主没有super高度语义；super高度在上层PLAF行记录。取消仅差>80才有日志的筛选，但保留每宿主0.5秒节流；8pt保高判据、失败兜底、重置逻辑均未删除或放宽。

新增日志只输出数字/状态位，不输出正文、命令、工具参数、URL、密钥或 UUID 字符串。未知身份/复用窗口用0；UInt64摘要不是全局无碰撞数据库标识。诊断不增加测量/布局调用，仍可能带来一定日志I/O成本。

### 测试与未覆盖项

新增 `scripts/test_scroll_deferred_identity.py`，12项通过：源码绑定实际重映射表达式、prepend、reorder、多项延迟、删除替换、尾append、空快照、连续重排、clear、新高度/显式失效取消旧延迟、确定性数字身份、PLAF捕获时序与字段、宿主身份与节流。转移案例为Python oracle配合Swift源码契约，**不是执行UIKit/Swift生产代码的单元测试**。

同时运行：`python3 scripts/test_v64r_render_contracts.py` 7项通过；`python3 scripts/test_v64r_live_assistant.py` 源码契约PASS，生产Swift执行SKIP（本机无Swift）。本目录无.git，未能使用git diff；本机为Linux，无Xcode/UIKit，未声称Swift编译/运行或真机通过。

此次修复封住明确可推导的延迟状态错写及旧值覆盖链，但不证明它解释所有实际卡住/重叠/空白。通用非TextKit增长闸、宿主保高是否拦截合法状态变化、减速期高度纠偏及settle锚点保持仍待新二进制在**相同主会话快速甩动、离屏复用、减速阶段**用数字身份轨迹检验。不删除全部高度锁，不改压缩、ChatStore、文本容器已有补丁；不以静止截图作为快滑验收。
