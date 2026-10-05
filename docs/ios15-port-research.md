# iOS 16 → 15.5 移植：官方文档与业界实现调研结论

调研时间：2026-10-05（CI#163 成功后）
目的：把 v13–v65 六代"哪里错补哪里"的补丁式修复，转成"依据官方机制的结构性修复"。

---

## 0. 一句话结论

**v65 之前的所有版本都在最底层（`NSTextContainer.setSize:`）替系统干活，而系统那套自动机制在 iOS 15 上根本不存在。**
不是补丁写错了，是**补丁在补一个 iOS 15 没有的能力**。

---

## 1. ★ 决定性发现：`selfSizingInvalidation` 是 iOS 16 新增，iOS 15 完全没有

### 官方原文（WWDC22 "What's new in UIKit"）

> "Self-sizing cells in UICollectionView and UITableView got a major upgrade. Now cells
> are also **self-resizing**! In **iOS 16**, when the content inside a visible cell changes,
> the cell will **automatically be resized** to fit the new content. This new behavior is
> **enabled by default**, and UICollectionView and UITableView each have a new
> **`selfSizingInvalidation`** property that gives you control over this new functionality."
>
> —— "UICollectionView and UITableView **intelligently coalesce size invalidation from
> cells into a single update performed at the optimal time**."

Apple 文档对 `enabledIncludingConstraints` 的说明：

> "calling `invalidateIntrinsicContentSize()` on a self-sizing cell or its contentView
> causes the cell to resize if necessary. Additionally, **any Auto Layout change within the
> contentView of a self-sizing cell automatically calls `invalidateIntrinsicContentSize()`**."

平台标注：`iOS 16.0+ / iPadOS 16.0+ / Mac Catalyst 16.0+ / tvOS 16.0+`

### 这解释了什么

| | iOS 16+ | iOS 15.5 |
|---|---|---|
| cell 内容变化 | **系统自动** resize | **系统不管**，停在估算高度 |
| 多次尺寸失效 | **合并（coalesce）** 成一次最优时机更新 | 无合并 ⇒ N 次抖动 |
| Auto Layout 变化 | 自动 `invalidateIntrinsicContentSize` | 无 |

**所以 App 在 iOS 16 开发机/测试机上"高度是对的"，换到 15.5 就疯狂抖 —— 这不是 bug，
是缺失的系统机制。** 六代盲区的机制性解释就在这里。

### 业界正解（Apple 论坛 Frameworks Engineer 亲自给的）

Apple 论坛问答 "Variable-height rows in UITableView"（thread/832851），提问者想从数据库异步
取数据后让 cell 变高，官方回答：

> "Yes! Set the table view's **`selfSizingInvalidation`** property to achieve this.
> If your cells are sized with Auto Layout, set `selfSizingInvalidation` to
> **`.enabledIncludingConstraints`**. When you update the contents of the cell, the table
> view will resize the cell automatically. If you're using **manual layout** inside your
> cells, set `selfSizingInvalidation` to **`.enabled`**, and call
> **`invalidateIntrinsicContentSize()`** on the cell when its contents change.
> Note you also need to implement **`sizeThatFits`** on your cell or its content view."

iOS 15 上（无该属性）的对应做法，社区与官方文档一致：

```objc
// 手动布局 cell: 内容变了必须自己"报告"高度
[cell invalidateIntrinsicContentSize];
[tableView beginUpdates];
[tableView endUpdates];          // 或 performBatchUpdates(nil, nil) iOS 11+

// 关键: 让估算值 ≈ 真实值, 系统就不会来回跳
- (CGFloat)tableView:(UITableView *)tv estimatedHeightForRowAtIndexPath:(NSIndexPath *)ip {
    return self.heightCache[ip] ?: 100.0;   // 缓存 willDisplay 里的真实高度
}
- (void)tableView:(UITableView *)tv willDisplayCell:(UITableViewCell *)c
     forRowAtIndexPath:(NSIndexPath *)ip {
    self.heightCache[ip] = CGRectGetHeight(c.bounds);   // 缓存真实高度
}
```

**抖动根因**（业界共识，与 iOS 16 的 coalesce 同源）：估算高度与真实高度差距大时，
table view 先按估算排版、cell 显示后换成真实高度、contentOffset 随之修正 ⇒ 肉眼可见的跳。
修法就是**让估算值贴近真实值**（缓存法），或**合并更新**（`performBatchUpdates`）。

### 对我们的启示（下一版方向）

- ❌ **继续在 `NSTextContainer.setSize:` 加判据** = 在最底层替系统做它不做的事，
  补丁越堆越厚，且永远补不全（因为缺的是"合并"和"自动失效"两个概念，不是"尺寸钳制"）。
- ✅ **在 cell 层让高度显式化**：真实高度缓存 + `invalidateIntrinsicContentSize` +
  `performBatchUpdates` 合并。SwiftUI `List` 侧对应的是 `.id()` 强制重建
  （StackOverflow 高票答案：List 缓存已创建的 row，`.fixedSize` 无效，
  `.id(item + 变化条件)` 才能让它从头重建）。

---

## 2. TextKit 版本断层：**iOS 15 的 UITextView 是 TextKit 1**

### 官方原文（WWDC22 "What's new in TextKit and text views"）

> "TextKit 2 first came to UIKit in **iOS 15** where **UITextField** was upgraded to use it.
> In **iOS 16**, the UIKit transition to TextKit 2 is **complete**, with **all text controls
> using TextKit 2 by default, including UITextView**."

平台标注确认：

| API | 最低版本 |
|---|---|
| `NSTextLayoutManager`（类本身） | **iOS 15.0+** |
| `UITextView.textLayoutManager`（属性） | **iOS 16.0+** |
| `UITextView(usingTextLayoutManager:)`（构造器） | **iOS 16.0+** |
| `UITableView.SelfSizingInvalidation` | **iOS 16.0+** |

### ⚠️ 一条与官方冲突的说法（不采信，但记录）

Apple 开发者论坛 thread/832952 里有一条用户回答称：
> "**Since iOS 15**, UITextView is backed by TextKit 2 (NSTextLayoutManager) by default."

**这条与 WWDC22 官方原文矛盾，本项目不采信**，理由三条：
1. WWDC22 明确说 iOS 15 只升级了 `UITextField`，`UITextView` 是 **iOS 16** 才纳入默认；
2. `UITextView.textLayoutManager` 与 `UITextView(usingTextLayoutManager:)` 的平台标注
   都是 **iOS 16.0+** —— iOS 15 上**连显式选择 TK2 的构造器都不存在**，
   谈不上"默认用 TK2"；
3. 同一论坛另一条 thread/707410 的 Frameworks Engineer 附了 Apple 头文件注释，
   明确写 `textLayoutManager` 是 `API_AVAILABLE(ios(16.0))` 且 iOS 16 起才默认。

⇒ 结论取官方版本：**iOS 15.5 的 UITextView 走 TextKit 1**，v65 的 swizzle 点成立。
（这条冲突也说明：为什么第 6 节坚持"没查到就说没查到"—— 论坛用户答案不能替代官方标注。）

### 对我们的三条结论

1. **v65 swizzle `NSTextContainer.setSize:` 在 iOS 15.5 上是正确注入点** ——
   iOS 15 的 UITextView 只有 TK1 一条路径，`NSTextContainer.setSize:` 必经。方向没错。
2. **不能用 TK2 的视口布局绕开排版滞后** —— `textLayoutManager` 属性本身就要 iOS 16。
   v65 里"丢弃病态尺寸会停在上一帧"这个两难，在 iOS 15 上**没有 TK2 这条出路**，
   只能继续在 TK1 层做修正/兜底。⇒ 这是平台限制，不是实现不够努力。
3. ⚠️ **纪律新增：注入层禁用 TK1 API** —— 在 iOS 16+ 上访问 `UITextView.layoutManager`
   会触发**永久降级**到 TextKit 1（Apple 注释原文：*"will cause a UITextView that's using
   TextKit 2 to 'fall back' to TextKit 1... **After this happens, .textLayoutManager will
   return nil — and any TextKit 2 objects you may have cached will cease functioning**"*），
   且**不可逆**。当前 guard 文件已验证 **TK1 API 零使用**（`grep layoutManager` 为空），
   这条要作为判据固定下来，防止将来有人顺手加一行。

---

## 3. `CGRect.width` 不是字段，是 category —— Apple 明文劝阻这种写法

### 官方原文（CGGeometry 文档）

> "**your applications should avoid directly reading and writing** the data stored in the
> CGRect data structure. Instead, use the functions described here"
> —— 推荐用 `CGRectGetWidth` / `CGRectGetHeight` 等函数，因为负宽高需要 `standardize`。

这正是 CI#162 编译红的机制（`no member named 'width' in 'struct CGRect'`）。
`CGRect` 的 `width/height` 来自 CoreGraphics `CGGeometry` **category**，
UIKit 的模块化导入**不 re-export** 它；而 `CGSize` 的 `width/height` **是真 struct 成员**，
两者只差一个 `R`。

**当前 KVC 修法可用但非最优**：官方正解是 `CGRectGetWidth()`。本轮不动
（改动要重跑全量回归，收益仅是"更正统"），但记入待办。

---

## 4. ⚠️ 需要重新审视的旧判断：1e7 不是病态循环源

### 官方原文（Tracking Size 文档）

> "set the text container's size in the appropriate dimension **large enough to accommodate
> a great amount of text—for example, 10,000,000 points (this incurs no cost)** whatever in
> processing or storage). **If you set both objects up to resize automatically in the same
> dimension, your application can get trapped in an infinite loop.**"

⇒ Apple 说 **1e7 是 "no cost"**，真正的循环条件是
**"两个对象在同一维度上都自动调整"** —— 是"双向自动调整"，不是"尺寸太大"。

⇒ v37 把 1e7 当"病态循环源"钳制的判断，**依据不足**。
好在 v65 现在的做法是**从 `.greatestFiniteMagnitude` 钳到 1e7**，
反而**更接近 Apple 推荐值**，方向是对的。文档注释里"1e7 仍近乎无限/会被当成无界"
的说法应当修正为"1e7 是 Apple 明确推荐的容纳上限，本身无代价"。

---

## 5. SwiftUI 反馈环：Apple 官方承认这个机制存在

WWDC22 "Custom Layout"：

> "**Sending the information up the view hierarchy is bypassing the Layout engine which
> can result in a loop.**"

⇒ v64 那条"每帧返回上一帧高度 + 固定增量（实测恒 +170pt/拍）"的累加线，
就是官方描述的 layout 环。**SwiftUI 没有提供"打断环"的官方开关**，
业界共识做法是**把高度变成显式状态**（`Animatable` / 自定义 `Layout` / 手动缓存），
而不是试图让 `sizeThatFits` 变聪明。

社区补充（fatbobman，SwiftUI 自定义 Layout 实战）：
> "**List does not automatically interpolate height changes for a dynamically-sized row.**"
> 且 SwiftUI 缺少 UIKit 的"先测量后提交"缓冲 —— `State` 一变，数据流立即传播并触发重排，
> 开发者**没有机会**在"状态已变"与"List 已响应"之间插入测量步骤。
⇒ 要拿回控制权，就必须**自己接管高度**（缓存 + 显式赋值），这与第 1 节的 cell 层方案同源。

---

## 6. 没查到的（不编）

- SwiftUI 在 iOS 15 上 `List` 行高抖动的 Apple 官方 issue：**没查到**。
  只找到社区文章与 SO 答案，无官方 issue 编号可引。
- `estimatedHeightForRowAt` 缓存法在 SwiftUI `List`（而非 UIKit `UITableView`）上的
  等价物：**没查到官方文档**。SwiftUI `List` 不暴露 `estimatedHeight` 钩子，
  `.id()` 是社区方案。
- v65 装机后 `[V65] FIXED-NONPOSITIVE` 是否真的出现：**仍未知**（等用户装机反馈）。

---

## 7. 下一版（v66）建议动作，按性价比排序

| 优先级 | 动作 | 依据 | 风险 |
|---|---|---|---|
| **P0** | 停止在 `NSTextContainer.setSize:` 加判据，改在 **cell 层**做高度缓存 + `invalidateIntrinsicContentSize` + 合并更新 | §1 iOS 16 才有 self-sizing，iOS 15 必须自己报告 | 中，需重跑全量回归 |
| **P0** | 判据加一层：**禁注入层出现 `layoutManager` / `textLayoutManager` 等 TK1 API** | §2.3 iOS 16+ 永久降级不可逆 | 低（当前已合规，纯加防线） |
| P1 | 把 1e7 的注释与判据改为"Apple 推荐容纳上限" | §4 旧判断依据不足 | 低 |
| P1 | 高度缓存用真实 `cell.bounds.height`，估算值返回缓存 | §1 业界标准解抖动法 | 中 |
| P2 | `.bounds.width` 改 `CGRectGetWidth()` | §3 Apple 明文劝阻直接读成员 | 低（但要重跑回归） |
| P2 | 修 1e7 相关注释表述 | §4 | 低 |

★ 纪律要点（沿用 §21/§22.4「拦下 ≠ 测到」）：
新增判据时，**先造一个"旧代码会红、新代码会绿"的反例**，
确认报的是**新加的那一层**而不是先撞上别的层。
