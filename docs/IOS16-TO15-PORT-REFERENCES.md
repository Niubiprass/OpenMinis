# iOS 16 → iOS 15 应用回移：真实开源参考与版本边界

核验日期：2026-10-15。范围：公开 GitHub 源码、提交、构建记录；仅静态研究，不修改生产代码、不推送、不操作手机。OpenMinis 本地对照基线：`5da5b4a6ff4a138a03ec34dfcf595080bbaf6bbf`，并读取工作区当前 `src/ios/iOS15Compat.swift`（工作区可能含未提交改动，不能用基线 SHA 代替当前文件内容）。

## 结论

1. **没有找到并核实“与 OpenMinis 同型的流式 AI 聊天 App，原生最低 iOS 16，完整回移 iOS 15，且有真机行为验证”的公开成功案例。** 不应把下面的 API 库或聊天布局库说成这种案例。
2. 找到一个真正的**完整 App 回移工程与成功构建证据**：`Aut-B/Flare-iOS15`。它是社交流客户端（时间线、私信、AI 功能），不是同型聊天 App；仓库同时含 iOS 17 新目录和目标 iOS 15 的旧目录，因此不能简化描述为严格的“iOS16 App→15”。可以证明 iOS15 目标归档、打包和上传成功，不能据此证明真机运行完全正确。
3. 与当前 hosting shim 最直接相关的是 **simonbs 的 iOS14 hosting 配置 gist**：它明确解决 UICollectionView/UITableView 更新 rootView 后高度不刷新，采取“移除再挂载 + intrinsic size 失效”。但这不是流式聊天性能方案。
4. `woxtu/UIHostingConfigurationBackport` 是标准 UIContentConfiguration 回移库；`shaps80/SwiftUIBackports` 的同名 API 却走自己的协议和 `.backport.contentConfiguration`，两者不能混为可无缝替换品。

## A. 完整应用回移工程：Flare-iOS15（有构建证据，无真机验收证据）

固定提交：[ca1d61bcb2bd73633511b3a2ffab4b796a117793](https://github.com/Aut-B/Flare-iOS15/commit/ca1d61bcb2bd73633511b3a2ffab4b796a117793)。项目 README 描述 Flare 为整合 Mastodon、Misskey、Bluesky 等服务的 Kotlin Multiplatform 社交客户端，含时间线、DM 和 AI 功能。

**最低版本证据必须看实际构建路径：**

- [`appleApp/project.yml`](https://github.com/Aut-B/Flare-iOS15/blob/ca1d61bcb2bd73633511b3a2ffab4b796a117793/appleApp/project.yml)：`deploymentTarget.iOS: "15.0"`。
- 同一提交 [`iosApp/project.yml`](https://github.com/Aut-B/Flare-iOS15/blob/ca1d61bcb2bd73633511b3a2ffab4b796a117793/iosApp/project.yml) 仍为 `17.0`；README badge 也仍是 iOS17。只查默认 README 会漏掉回移工程；只见 iOS15 仓库名也不足以下结论。
- 成功 [Actions run 38727424211](https://github.com/Aut-B/Flare-iOS15/actions/runs/38727424211)，head SHA 为上述提交，实际 workflow path 是 `.github/workflows/ios.yml`，而非仅凭名字猜测的 `build-ios15.yml`。Jobs API 中 `Generate Xcode project (appleApp)`、`Build unsigned IPA (iOS 15, device)`、`Package IPA`、`Upload IPA artifact` 均为 success。可据此称“公开 CI 构建/打包成功的回移工程”，不称“真机移植验收通过”。

**真正采用的方法：**

- [`IOS15LayoutCompat.swift`](https://github.com/Aut-B/Flare-iOS15/blob/ca1d61bcb2bd73633511b3a2ffab4b796a117793/appleApp/Shared/FlareAppleCore/Sources/FlareAppleUI/IOS15LayoutCompat.swift)：把 iOS16 `Layout` 实现留在 availability 分支，新建兼容包装 View。iOS15 的 AdaptiveGrid 用 `LazyVGrid`，轮播布局直接返回 content；注释明确不保留所有图片比例/高度约束效果。是“选择性降级”，不是重造完整 Layout 引擎。
- [`iOS15Backports.swift`](https://github.com/Aut-B/Flare-iOS15/blob/ca1d61bcb2bd73633511b3a2ffab4b796a117793/appleApp/Shared/FlareAppleCore/Sources/FlareAppleCore/iOS15Backports.swift)：命名 `backportOnChange`，以 `onReceive(Just(value))` 加旧值比较兼容新 onChange 调用；ContentUnavailableView 用 VStack 替代；`backportScrollPosition` 在 iOS17 以下直接透传，不提供定位行为。
- 同目录还有 BackportPhotosPicker、BackportShareLink；说明完整 App 回移需要拆分多个新 API，不能只换 hosting。

**适合 OpenMinis：** 列出“等价实现 / 行为降级 / 明确不可用”三类兼容能力，保留新系统原生分支；单 API 显式 backport 命名可避免与 SDK 类型冲突。

**不能直接套用：** Flare 的 no-op scrollPosition 不保证聊天尾随；简化布局不保证 Markdown/工具卡动态高度；该证据没有证明 OpenMinis 的 UICollectionView 自定义高度缓存、流式更新或 attachment 场景已被解决。它也不是严格同型 iOS16→15 App。

## B. 单 API 回移：simonbs / SwiftUIHostingConfiguration（最直接的高度失效参考）

来源：[gist 说明与源码](https://gist.github.com/simonbs/457725e218fc85fc765ed770815314df)，[已核验原始 Swift 源码版本](https://gist.githubusercontent.com/simonbs/457725e218fc85fc765ed770815314df/raw/9d067216de8e08d4e55dbf3a0a4e8fc082e1b3da/SwiftUIHostingConfiguration.swift)。说明明确写 iOS16 UIHostingConfiguration 回移至 **iOS14**；这是 gist 示例，没有 Package.swift 或完整 App 发布证据。

- `SwiftUIHostingConfiguration<Content>: UIContentConfiguration`，`ContentView: UIView, UIContentView`，用于 table/collection cell。
- init 显式传入 weak `parentViewController`；建立 addChild / addSubview / didMove；移除走 willMove(nil) / removeFromSuperview / removeFromParent，deinit 清理。
- configuration setter 更新 `hostingController.rootView`，随后 **removeHostingControllerFromViewHierarchy → addHostingControllerToViewHierarchy → invalidateIntrinsicContentSize**。
- 作者直接在这段 setter 注释：仅更新内容不足以令 UICollectionView / UITableView 重排高度，移除/重新挂载并令 intrinsic content size 失效才触发刷新。这是源码作者观察，不是苹果保证或全场景定理。
- `supports(_:)` 仅接受匹配泛型的配置；不是每次更新都新建 controller，但每次都重新挂载其视图/父子关系。

**可用方法：** 将 containment、rootView 更新、内容尺寸失效视为不同责任；可用“重新挂载”作隔离诊断，判断高度不变是否来自 hosting 失效传播。

**不能直接套用：** 每 token 重新挂载可能影响性能、动画与生命周期，且示例没有消息 identity、宽度契约、流式节流、外层缓存失效和滚动锚点机制。不要把这一招直接塞进现有快速路径。

## C. 单 API 回移：woxtu/UIHostingConfigurationBackport

固定提交 `6091f2d38faa4b24fc2ca0389c651e2f666624a3`。

- [Package.swift](https://github.com/woxtu/UIHostingConfigurationBackport/blob/6091f2d38faa4b24fc2ca0389c651e2f666624a3/Package.swift)：Swift tools 5.3，最低 **iOS14 / tvOS14**。
- [完整实现](https://github.com/woxtu/UIHostingConfigurationBackport/blob/6091f2d38faa4b24fc2ca0389c651e2f666624a3/Sources/UIHostingConfigurationBackport/UIHostingConfigurationBackport.swift)：遵守 UIKit 原生 `UIContentConfiguration`，内层 `UIContentView`；支持 background、margins、minSize；host view 四边约束到 layoutMarginsGuide。
- 更新 configuration 时设置 rootView 和 directionalLayoutMargins；`didMoveToSuperview` 通过 responder chain 寻找 parent controller 并建立/移除 containment。
- **在已核验版本中，setter 没有显式 invalidateIntrinsicContentSize，也没有 OpenMinis 那样的宽度驱动 sizeThatFits、消息 identity 或复用高度缓存清理。** intrinsicContentSize override 只对 super 的尺寸施加 minWidth/minHeight，不能据此宣称已解决 SwiftUI 动态高度。

**可用方法：** 原生 UIContentConfiguration 桥接、margin/背景语义及 containment 是干净的小型参考。

**不能直接套用：** 不是完整 App 移植；README 可运行用例不能证明流式 Markdown 高度稳定；不应以这个短实现整体替换 OpenMinis 当前 shim。

## D. API 回移合集：SwiftUIBackports 与 SwiftBackports（不可误称完整 App）

SwiftUIBackports 固定提交 `eaeff429ac1ae625179e784680e63e05c2171786`：

- [Package.swift](https://github.com/shaps80/SwiftUIBackports/blob/eaeff429ac1ae625179e784680e63e05c2171786/Package.swift)：**当前分支最低 iOS15、Swift tools 6.0**。README 明确从 v27 起最低 iOS15，需要更老系统应停留 26.x。不要把历史“iOS13+”宣传直接套用当前主线。
- [hosting 配置源码](https://github.com/shaps80/SwiftUIBackports/blob/eaeff429ac1ae625179e784680e63e05c2171786/Sources/SwiftUIBackports/iOS/UIHostingConfiguration/UIHostingConfiguration.swift)：`Backport.UIHostingConfiguration` **不遵守原生 UIContentConfiguration**，而是自己的 `BackportUIContentConfiguration`；makeContentView 创建 UIHostingController 的 view，设置 ignoreSafeArea。
- [UICollectionViewCell 桥接源码](https://github.com/shaps80/SwiftUIBackports/blob/eaeff429ac1ae625179e784680e63e05c2171786/Sources/SwiftUIBackports/iOS/UIHostingConfiguration/Cells/UICollectionViewCell.swift)：应通过 `cell.backport.contentConfiguration` 使用；getter 恒 nil；每次 setter 移除 configuredView，创建并四边约束一个新的 configuredView。margins 通过反射配置字段施加。不是当前 shim 的相同消息复用 rootView 模型，也没有当前 shim 的显式高度失效链。
- 此提交 `minSize` 方法在 hosting 源码中**被注释**；不可假设它拥有原生完整行为。相关 ignoreSafeArea 实现也应单独审计，不能仅凭同名 API 判断等价。
- [Presentation/Detents.swift](https://github.com/shaps80/SwiftUIBackports/blob/eaeff429ac1ae625179e784680e63e05c2171786/Sources/SwiftUIBackports/iOS/Presentation/Detents.swift)：`.backport.presentationDetents` 在 iOS15 用 UISheetPresentationController；API 标记 introduced 15 / deprecated 16，包含 medium / large。该来源证明“新 SwiftUI 接口可桥接旧 UIKit 能力”，不代表 iOS16 所有自定义 detent 都能回移。

SwiftBackports 是其底层 namespace / Foundation 回移库，不是同一产品：

- [固定 Package.swift](https://github.com/shaps80/SwiftBackports/blob/2fd64af06ba280d20d93236e99177a8b8f6011ee/Package.swift)：最低 **iOS12**，但 Swift tools **6.0**。运行系统下限与编译工具链下限是两件事。
- 其 Sources 包含 Backport namespace、URLSession async、UTType 等；最低 iOS12 不表示依赖它的 SwiftUIBackports 也支持 iOS12，更不表示任意 App 可以降到该版本。

**可用方法：** 按 API 对照包清单/源文件选择性引入，使用 `.backport` 命名空间隔离；sheet 先桥接 iOS15 已有 UIKit 能力。

**不能直接套用：** 不能只写 `typealias UIHostingConfiguration = Backport.UIHostingConfiguration` 然后继续走原生 cell.contentConfiguration；协议/入口、getter、minSize、复用语义均不同。不要为了小部分接口盲目升级整个包主版本或工具链。

## E. 单 API 回移：NavigationBackport（补充应用级 API 缺口，不解决聊天高度）

固定提交 `540d823fdfbbe495cbbe0afc80c409d63c9995c0`。

- [Package.swift](https://github.com/johnpatrickmorgan/NavigationBackport/blob/540d823fdfbbe495cbbe0afc80c409d63c9995c0/Package.swift)：Swift tools 5.6、最低 **iOS14**。
- [README](https://github.com/johnpatrickmorgan/NavigationBackport/blob/540d823fdfbbe495cbbe0afc80c409d63c9995c0/README.md)：提供 NBNavigationStack / NBNavigationLink / NBNavigationPath / nbNavigationDestination 等，面向 iOS16 导航 API 的旧系统兼容。
- [NBNavigationStack.swift](https://github.com/johnpatrickmorgan/NavigationBackport/blob/540d823fdfbbe495cbbe0afc80c409d63c9995c0/Sources/NavigationBackport/NBNavigationStack.swift)：iOS16 且 policy 允许时走原生 NavigationStack，否则用 NavigationView；源码也明确旧 NavigationView 初始化时只支持一个已 push 屏幕，之后通过 path 更新机制处理。

**可用方法：** 比本地全局 destination registry / 单层 NavigationLink 更完整的导航兼容实现可以独立评估；仍须测深链、pop、交互返回和多窗口，不能当成未经验证的无差异替身。

## F. 对当前 OpenMinis hosting shim 的具体对照

读取路径：`src/ios/iOS15Compat.swift` 中 `_HostingContentCellView` 与 `UIHostingConfiguration`，研究时约 351–760 行；以下是静态代码观察，不是运行验证。

| 关注点 | 当前 OpenMinis 工作区 | 外部可借鉴 / 风险边界 |
|---|---|---|
| 桥接入口 | 原生 UIContentConfiguration / UIContentView | 与 simonbs、woxtu 同一路径；与 shaps80 自有协议不兼容 |
| 宿主生命周期 | host 强持有 UIHostingController，但该类内未见 addChild/didMove/removeFromParent | simonbs 明确父 VC 注入，woxtu responder chain 查找；可独立检查 containment，不能直接推断它就是当前 bug 根因 |
| 同 item 更新 | contentIdentity 相同则保留 host，更新 rootView；不同 item 重建并清空历史高度 | 有意比外部简单示例更适合 token 更新；不要换成每 token 新建 host |
| SwiftUI 状态隔离 | `.id(contentIdentity)`，消息/块身份而非更新代数 | 外部示例未覆盖流式 identity；必须保留身份隔离并测复用后状态不串行 |
| 给定宽测量 | 两个 systemLayoutSizeFitting 重载及 sizeThatFits 汇入 ios15FittingSize；实际 collection 宽优先，root frame 同宽 | 外部库没有同等的显式测量契约，不可因源码较短就删除本地宽度处理 |
| 避免递归 | 使用 host.view.sizeThatFits，不走与父四边约束互相回问的 Auto Layout fitting | simonbs 重挂载不是测量算法替代品；不要恢复已在本地注释记载会递归的路径 |
| 高度失效 | host.view 与 content view invalidateIntrinsicContentSize、setNeedsLayout；确认稳定缩小时清 cell cache / layout height / memo 后 invalidateLayout | 外部例子通常没有这些外层缓存；只抄一句 invalidateIntrinsicContentSize 不会自动清理 MessageListLayout |
| 防塌缩/回缩 | 同宽历史高水位、last-good fallback、延时双次小高度确认；受 streaming/drag/deceleration/identity 条件约束 | 外部无此策略。此报告不主张删除高水位或绕开 confirmed-shrink 保护 |
| margins/minSize | margins 明确 no-op；minSize 储存参数，但已读取 hosting 测量/应用路径未见用其执行下限 | 当前是项目特定近似，不是原生完整 API 等价；woxtu 可作行为对照，不能直接导入改变现有几何 |

### 可以马上采用的研究/验证方法（不改生产代码）

1. **优先级 1：建立失效链观察表。** 对同 item 内容变化，分别观察 rootView 更新、host intrinsic size、contentView fitting、cell preferred attributes、layout cache/memo 和最终 frame。不要只测静态 Text 或只看截图。
2. **优先级 2：把 containment 作为独立假设。** 用测试宿主参考 simonbs/woxtu，验证父控制器生命周期、trait/safe area、旋转传播；不把每 token 重挂载当默认解决方案。
3. **优先级 3：在隔离实验中比较“只 invalidate”与“重新挂载再 invalidate”。** 如果只有后者使 UIKit 重新询问高度，定位是失效传播问题；然后寻找可节流/定向触发办法，而不是粗暴重建全表。
4. **优先级 4：建立 API 版本矩阵。** 区分运行时最低版本、SDK 引入版本、Swift tools/编译器版本、依赖版本与能力降级；对导航、相册、分享、sheet 分开验证。
5. 回归场景至少包括：窄/宽旋转、长短消息交叉复用、流式增长、终止后真缩高、图片/工具卡异步高度、滚动中更新、返回前台、Dynamic Type；同一消息测量宽与渲染宽必须一致。

## 分类与证据强度小结

| 来源 | 分类 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| Aut-B/Flare-iOS15 | 完整 App 回移工程 | iOS15 目标、真实回移源码、CI archive/package/upload 成功 | 同型 iOS16 聊天 App、真机无缺陷、流式高度稳定 |
| simonbs gist | 单 API 回移示例 | iOS14 起的 hosting 桥接与高度失效 workaround | 完整 App 回移、性能/全场景保证 |
| woxtu | 单 API 兼容库 | iOS14 包平台、原生 UIContentConfiguration 桥接 | 已解决动态高度/流式复用 |
| shaps80 SwiftUIBackports / SwiftBackports | 多 API 回移库 / 底层库 | API 级兼容及各自版本边界 | 完整 App 最低版本可直接下降、hosting 可无缝替换 |
| NavigationBackport | 单领域 API 回移库 | iOS14 导航兼容方案 | UICollectionView 动态高度问题 |

一般聊天布局库（如 ChatLayout）是布局机制参考，**不属于 App 最低系统回移案例**；本报告不重复另一份布局研究，也不以 Flare 依赖 ChatLayout 为“动态高度问题已解决”的证据。

研究限制：没有构建或运行外部样本，没有下载验证 Flare IPA 的 Mach-O/Info.plist，也没有真机复现。因此“成功”严格限定于所引用 CI 的公开步骤；所有高度建议都是由已核验源码提出的待验证方法，而非已证实修复。
