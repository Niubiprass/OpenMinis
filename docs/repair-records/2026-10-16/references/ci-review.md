# CI／显示问题验证审查

审查对象：`ios15.6` 分支，HEAD `1cda3b422369029fc026d84efc4d2da77962ae8b`；本地工作树只读、状态干净。使用无认证公开 API 读取成功 run、job steps、artifact 元数据，并在网页仅展开成功任务的 Xcode／fallback 检查和前次失败的 fallback 局部日志；未下载 IPA、未安装到手机、未读取 token 或私有凭据。

## 1. 构建成功属实，但 xcodebuild 并未运行模拟器上的完整 App 或 XCTest

[成功 run 37912110126](https://github.com/moxuan1121/OpenMinis/actions/runs/37912110126) 的 API 返回 HEAD 与审查提交一致，`completed/success`；唯一 [job 113759474604](https://github.com/moxuan1121/OpenMinis/actions/runs/37912110126/job/113759474604) 中 step 5 `Check iOS 15 fallbacks`、step 11 `Build for iOS 15.6`、step 12 `Verify and package iOS 15 app` 都为 success。step 3 局部日志 L28–29 明确为 **Xcode 26.3，Build 17C529**；`macos-15` 是宿主 runner，不是被测 iOS 版本。

[`.github/workflows/ios15.yml:L74–81`](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/.github/workflows/ios15.yml#L74-L81) 执行的是 `xcodebuild … -configuration Release -destination 'generic/platform=iOS' … build`，不是 `test`、`test-without-building`，也不是模拟器 destination。它证明 device-target 构建和后续打包通过，**不等于在真机运行过**。虽然 [Minis.xcscheme:L26–55](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/src/ios/Minis.xcodeproj/xcshareddata/xcschemes/Minis.xcscheme#L26-L55) 列出了 MinisTests／MinisUITests，这次 workflow 没有调用其测试动作。

[Artifacts API](https://api.github.com/repos/moxuan1121/OpenMinis/actions/runs/37912110126/artifacts) 仅列 2 个未过期产物：`OpenMinis-iOS15.6-fixed`（73,660,523 bytes）及 `ios15-build-log`（118,783 bytes），不是截图或 `.xcresult` 测试报告。

## 2. 确有自动启动的 UIKit 模拟器布局回归，不是只有编译；但不是证实在 iOS 15.6 上运行

[workflow:L27–32](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/.github/workflows/ios15.yml#L27-L32) 调用 `check_ios15_text_layout.py`。该脚本不是 xcodebuild 启动完整 Minis，而是提取生产代码创建独立 `LayoutProbe.app`：用 `swiftc -target arm64-apple-ios15.6-simulator` 编译，再 `simctl boot/install/launch --console`，等待应用在 Documents 写出 PASS 文件，缺失即失败（[脚本:L145–188](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/scripts/check_ios15_text_layout.py#L145-L188)）。成功 job [step 5 日志 L14](https://github.com/moxuan1121/OpenMinis/actions/runs/37912110126/job/113759474604#step:5:14) 确实有 `PASS: legacy UIKit text sizing and hosted message-list growth/collapse without overlap`。

**实际模拟器 iOS runtime 版本无法从该局部日志确认，也没有被脚本锁定。** 脚本只选所有 available devices 中第一个名称含 iPhone 的设备（L145–147），丢弃 runtime 分组且不打印 runtime；`15.6` target／MinimumOSVersion 是部署下限，不是运行时版本。脚本还将 `#available(iOS 16.0, *)` 改为 `if false`，强行走旧系统分支；顶部 L1–4 已明确说明新模拟器检查旧逻辑不能代替 iOS 15 设备测试（[脚本:L1–30](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/scripts/check_ios15_text_layout.py#L1-L30)）。因此不能把这次通过写成“iOS 15.6 模拟器／15.5 真机显示已验证”。

## 3. 回归检查确实针对换行、截断和高度更新，且曾捕获失败；不是自动截图验收

[脚本:L66–137](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/scripts/check_ios15_text_layout.py#L66-L137) 用 precondition 检查：长中文回复自动换行；288／568 宽度重排；追加正文后高度增大；字号增大后的高度；空文本；hosted 行高度与列表缓存一致；相邻消息不重叠；内容增长与收起后高度更新。它复用了生产 `MessageListLayout`／legacy hosting bridge，但替换了日志、item identity 和 SelfSizingCell 的缓存接口，展示内容为简化 SwiftUI Text，**不是完整聊天页、真实 Markdown／代码表格或真实网络流式会话的端到端验收**（L20–59）。

[前次 run 37911481906 的 step 5 日志 L15–24](https://github.com/moxuan1121/OpenMinis/actions/runs/37911481906/job/113757423431#step:5:15) 显示两次 `hosted=71.666667 cached=71.666667`，随后 `Precondition failed: Streaming growth was not committed to the list`，最终退出 1。前次提交为 `5bc23db8e19f5f145245682fbc4742cfb02174f1`；本地两次提交 diff 显示回归脚本未改，本次仅给 legacy hosting 的 apply 添加 `setNeedsLayout()`（[IOS15Compatibility.swift:L463–477](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/src/ios/Shared/IOS15Compatibility.swift#L463-L477)）。这提供了“同一断言先失败、改代码后通过”的有意义证据。

仓库另有截图／视觉抖动 UI 测试（[MessageListV3UITests.swift:L76–94](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/src/ios/MinisUITests/MessageListV3UITests.swift#L76-L94)、L182–202），但本次 CI 未执行这些 XCTest；layout probe 本身没有截图步骤，workflow 也没有上传截图。**可确认的是自动运行的几何断言，不是自动截图比对通过，更不是真机显示问题已全部解决。**

## 4. 当前产物最低要求 iOS 15.6，不能作为用户 iOS 15.5 可用包

主应用 Debug／Release 均设置 `IPHONEOS_DEPLOYMENT_TARGET = 15.6`（[project.pbxproj:L3622](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/src/ios/Minis.xcodeproj/project.pbxproj#L3622)、[L3676](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/src/ios/Minis.xcodeproj/project.pbxproj#L3676)）。打包校验还强制应用 `Info.plist.MinimumOSVersion == '15.6'`，检查 Mach-O minos、较新框架弱链接及 App Group entitlements（[check_ios15_app.py:L16–37](https://github.com/moxuan1121/OpenMinis/blob/1cda3b422369029fc026d84efc4d2da77962ae8b/scripts/check_ios15_app.py#L16-L37)）；成功 job 的 step 12 通过了该校验。

**iOS 15.5 低于明确的最低系统门槛，正常安装／运行不受支持。** 不能因为名称写“iOS 15”或模拟器逻辑回归通过就认定 15.5 可用；改 plist／重签也不构成二进制兼容保证。要支持 15.5，需要另行降低真实部署目标、审核依赖／API 并在 15.5 设备上验证，当前 CI 没有提供此证据。

说明：前次 run 的额外 REST 请求遇到公开 API rate limit，以上前次失败原因来自公开任务网页局部日志；成功 run／steps／artifact 信息均已取得公开 API 数据。未进行完整日志或大产物下载。
