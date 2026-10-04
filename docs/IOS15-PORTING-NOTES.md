# iOS 15 适配改造报告

> 目标：把 OpenMinis 的最低系统版本从 iOS 16.0 降到 iOS 15.0。
> 状态：**代码改造已完成，尚未经过 Xcode 编译验证**（详见文末「验证方式」）。

---

## 一、改动规模

| 项目 | 数值 |
|---|---|
| 变更文件 | 87 个 |
| 代码行 | +1599 / −601 |
| 新增文件 | 3（兼容层、ActivityKit 桩、CI workflow） |
| 部署目标 | 12 处配置 → iOS 15.0；2 处（Widget）保持 16.2 |

---

## 二、核心难点与解法

### 1. `import` 无法被 `@available` 保护

`@available` 只能保护**类型和成员**，不能保护文件顶部的 `import` 语句。
所以只要文件里 `import AppIntents`，把部署目标降到 15.0 就**直接编译失败**——
哪怕所有用到它的类型都包了 `@available`。

**解法**：`#if canImport(AppIntents)`。这是编译期求值的条件编译，
`canImport` 为假时整个 `import` 及其后所有内容都不参与编译。

涉及 **14 个文件**（`src/ios/Agent/Intents/` 全目录 + `Shared/AudioTogglePlaybackIntent.swift`）。

### 2. SwiftUI 修饰符链不能被 `if #available` 包裹

```swift
// 不可行 —— 修饰符链要求两侧类型一致
.sheet(...) { ... }
    .presentationDetents([.medium])   // iOS 16+
```

`if #available` 会把链条打断，所以**不能**把这些修饰符逐个加守卫。
`ShareLink`、`LabeledContent`、`presentationDetents` 共 41 处调用点都受此约束。

**解法**：在兼容层自建等价类型，让修饰符**无条件可用**，版本判断只存在于兼容层内部：

| 原 API | 兼容层替代 |
|---|---|
| `NavigationStack` | `CompatNavigationStack`（iOS 15 → `NavigationView`） |
| `NavigationPath` | `CompatNavigationPath<Element>`（数组包装，API 表面对齐） |
| `NavigationLink(value:)` | `CompatNavigationLink` |
| `LabeledContent` | `CompatLabeledContent` |
| `ShareLink` | `CompatShareLink` |
| `PresentationDetent` | `CompatPresentationDetent`（自建枚举） |
| `NavigationSplitView` | `compatNavigationSplitView` |
| `NavigationSplitViewVisibility` | `CompatSplitViewVisibility` |
| `onGeometryChange`（iOS 18） | `CompatGeometryObserver` |

### 3. 路径驱动导航在 iOS 15 上没有等价物

`NavigationPath` 本身是 iOS 16 类型，所以 `NavigationStack(path:)` 无法直接降级。

**解法**：`CompatNavigationPath<Element>` 用 `[Element]` 包装模拟，
API 表面（`init()` / `count` / `isEmpty` / `first` / `last` / `append` /
`removeLast` / `removeAll` / `Equatable`）与 `NavigationPath` 对齐，
使 ContentView 中 65 处引用只需改类型名、无需改逻辑。

`CompatPathStack` 负责渲染：
- **iOS 16+**：真 `NavigationStack(path:)`，行为完全不变
- **iOS 15**：用 `path.last` 决定渲染哪个 destination，配 `.id(top)`
  保证每个路径条目有独立 View 身份（避免 `@StateObject` 被复用——这正是
  代码注释里 `[T-ios-stacknav-transition-attributegraph-race]` 记录的 bug）

### 4. iPhone 会话列表的点击层会静默失效（**本次最隐蔽的坑**）

ContentView 里会话行的点击是这样的：

```swift
.background(
    NavigationLink(value: session.id) { EmptyView() }
        .opacity(0)
)
```

行本身**不可点击**，这个零透明度的链接就是唯一的点击区域。
而 `navigationPath` 的其他所有写入（深链、快捷指令、后台看门狗）
**全是程序化的，没有任何用户手势路径**。

也就是说：如果只替换 `NavigationStack` 而不管这个链接，
**iOS 15 上点会话完全没反应，而且不报任何错**。

**解法**：新增 `CompatNavigationLink`，iOS 15 分支用 `Button` 直接 append 到
`CompatNavigationPath`——保持"导航栈上有什么"只有一个数据源。

### 5. iOS 18 的 `onGeometryChange` 会让 iOS 15 编译失败

5 处调用点用了 `onGeometryChange`（iOS 18+）。
直接改回 `GeometryReader` 不可行——代码注释明确记录了那正是导致
iOS 18 异步渲染器 SIGTRAP（`ViewGraphGeometryObservers.needsUpdate`）的旧写法。

**解法**：`CompatGeometryObserver`，iOS 18+ 走真 API，iOS 15–17 走
`GeometryReader` + `onAppear`/`onChange` 回退（`GeometryReader` 被限制在
`Color.clear` 背景层内，不影响布局）。`action` 闭包原样保留，业务逻辑零改动。

---

## 三、核查过但**无需改动**的 API

以下高版本 API 原本就自带 `if #available` 守卫和 iOS 15 回退分支：

| API | 版本 | 位置 |
|---|---|---|
| `AVAudioApplication` | iOS 17 | 4 处（`SpeechRecognitionManager`、`VoiceActivityDetector`） |
| `symbolEffect` | iOS 17 | 2 处（`BrowserSheetView`） |
| `glassEffect` / `glassEffectID` | iOS 26 | 8 处 |
| `scrollEdgeEffectHidden` | iOS 26 | 1 处 |
| `toolbarBackgroundVisibility` | iOS 26 | 1 处 |
| `presentationSizing` | iOS 18 | 1 处 |
| `AlarmKit` | iOS 26 | 已用 `#if canImport` |

---

## 四、已知功能缺口（系统框架限制，无法绕过）

| 功能 | 原因 | iOS 15 表现 |
|---|---|---|
| Siri / 快捷指令 | AppIntents 需 iOS 16 | Intent 类型不存在，调用点已条件编译 |
| 实时活动（Live Activity） | ActivityKit 需 iOS 16.1 | 走桩实现，设置界面自动隐藏开关 |
| 小组件 | Widget 需 iOS 16.2 | 该 target 保持 16.2，不随主 target 降级 |
| sheet 高度 detent | iOS 16 | 退化为默认高度，sheet 仍可正常弹出/关闭 |
| iOS 18 几何观察 | iOS 18 | 走 GeometryReader 回退路径 |

> 提示：AgentWidget 扩展保留 `IPHONEOS_DEPLOYMENT_TARGET = 16.2`。
> 若强行降到 15.0，Live Activity 会因 ActivityKit 不可用而编译失败。
> 实际运行中，iOS 15 设备上该扩展会被系统自动忽略。

---

## 五、验证方式（重要）

**本次改造没有经过 Xcode 编译验证。** 沙箱环境是 Linux，没有
`xcodebuild` / `swiftc`，无法编译 iOS 项目。

代码层面的检查已完成（部署目标、API 残留扫描、花括号结构平衡），
但**泛型签名、ViewBuilder 结构、属性包装器推断这类只有编译器才能确认的问题，
仍需实机验证**。

### 你的路径：GitHub Actions + TrollStore

仓库已加入 `.github/workflows/ios-build-unsigned-ipa.yml`，
在 GitHub 的 macOS runner 上编译并产出**未签名 IPA**。

**操作步骤**：

1. 把改动推到 GitHub
2. 打开仓库 → **Actions** → 左侧选 **iOS Build (unsigned IPA)**
3. 点 **Run workflow**（configuration 选 Release）
4. 等约 60–100 分钟（首次；命中缓存后约 15 分钟）
5. 构建成功后，在该次运行页面底部 **Artifacts** 下载
   `minis-unsigned-ipa`
6. 解压得到 `minis-unsigned.ipa`，用**巨魔 (TrollStore)** 打开并安装

**注意**：
- 未签名 IPA 正是 TrollStore 需要的格式，它会自己伪签名
- macOS runner 免费额度每月约 200 分钟，**不要**挂到 push/PR 自动触发
  （workflow 已经是手动触发）
- 首次运行若 Metal Toolchain 缺失，FFmpeg 会静默丢掉
  `yadif_videotoolbox` 滤镜（不影响编译成功）

**若构建失败**，把运行日志里 `BUILD FAILED` 附近的错误发我，
绝大多数问题会集中在新写的兼容层泛型签名上，改动量很小。

---

## 六、逐文件改动清单

### 新增文件（3）

| 文件 | 作用 |
|---|---|
| `src/ios/Shared/iOS15Compat.swift` | 兼容层，收敛全部 iOS 16/17/18 API |
| `src/ios/Agent/Background/AgentLiveActivityManager+iOS15.swift` | iOS 15 下的 Live Activity 空实现（19 个公开成员对齐真实版本） |
| `.github/workflows/ios-build-unsigned-ipa.yml` | 云端编译 → 未签名 IPA |

### 部署目标（1）

| 文件 | 改动 |
|---|---|
| `src/ios/Minis.xcodeproj/project.pbxproj` | 14 处 → 15.0（其中 AgentWidget 的 2 处回退为 16.2）；注册 2 个新文件 |

### 条件编译（18）

`Agent/Intents/` 13 个文件 + `Shared/AudioTogglePlaybackIntent.swift`
+ `Agent/Background/AgentLiveActivityManager.swift`
+ `Shared/AgentActivityAttributes.swift`
+ `BackgroundKeepAliveManager.swift`（删 import）
+ `MinisApp.swift`（调用点保护）
+ `Agent/Jobs/HelperRunner.swift`（改调提取出的文件级函数）
+ `Agent/Intents/SendPromptIntent.swift`（提取 `extractShortcutResponseText`）

### 批量替换（约 240 处调用点，60+ 文件）

| API | 替换数 |
|---|---|
| `CompatNavigationStack` | 72 |
| `CompatLabeledContent` | 79 |
| `compatPresentationDetents` | 29 |
| `compatPresentationDragIndicator` | 11 |
| `CompatPathStack` | 4 |
| `CompatNavigationPath` | 9 |
| `CompatShareLink` | 1 |
| `compatNavigationSplitView` / `CompatSplitViewVisibility` | 各 1 |
| `CompatNavigationLink` | 2 |
| `CompatGeometryObserver` | 5 |

### 构建脚本（4）

| 文件 | 改动 |
|---|---|
| `deps/build_rclone_ios.sh` | 版本标志 16.0 → 15.0；加幂等跳过 |
| `deps/build_ffmpeg.sh` | 加幂等跳过（其 `IOS_DEPLOYMENT_TARGET` 本就是 14.0） |
| `deps/prepare_alpine_rootfs.sh` | 加幂等跳过 |
| `BUILDING.md` | 版本说明 iOS 26.2 → iOS 15.0 |

---

## 七、代码层面的验证记录

| 检查项 | 结果 |
|---|---|
| 部署目标分布 | 12 × 15.0 + 2 × 16.2 ✓ |
| 原生依赖版本标志 | rclone 15.0；ffmpeg/ish 14.0 ✓ |
| iOS 16+ API 残留扫描 | 8 类全部为 0 ✓ |
| `onGeometryChange` 残留 | 仅测试文件中的字符串字面量 ✓ |
| 新文件注册 | 4 个 pbxproj ID 全部 defined ✓ |
| 花括号结构平衡 | ContentView 保持基线 −3；AIChatView / ChatMessageViews 为 0 ✓ |
| workflow YAML 语法 | 解析通过，16 步骤顺序正确 ✓ |
| 构建脚本语法 | `bash -n` 通过 ✓ |
| 源码扫描测试 | `VoiceToolbarLabelFitTests` 断言的业务代码未变，仍会通过 ✓ |
