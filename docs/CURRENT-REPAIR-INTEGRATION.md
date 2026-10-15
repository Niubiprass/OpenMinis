# Current repair integration — 2026-10-15

## 结论与版本边界

**可提交到同一候选版本进行 macOS 集成编译；不可宣称编译/设备验收已通过。** 本轮同目录保留并联合审查思考 C019D937、自动压缩 1CA2A723、快滑 deferred 身份 E79EB16B，以及既有长文容器修复。以上短 ID 是交接标识，不是本无 .git 工作树可证明的 commit SHA。没有回滚、重新移植或重写布局。

只读 GitHub API 查询（2026-10-15 11:21 UTC 前后）：

- 仓库/分支：Niubiprass/OpenMinis / ios15-v64-repair。
- 最新远端 SHA：`3e27786d8e8e0724fad03ad2f9c9894e5d1d4296`。
- 最近该 workflow：run_number **8**，run ID **38714599848**，attempt 1，success；实际 head 为 `c4dfa8dacbada30bf91847d7c50b130998584781`，不是当前远端 SHA。
- 远端及本地 workflow 当前 IPA build 为 **160644 / Repair4**。建议下一唯一产品 build **160645 / Repair5**；若没有新运行，workflow 下次预计 run_number 9，但这不是产品 build 号，也不是可提前保留的编号。
- 本审查未修改产品号，避免擅自发布；正式候选必须把 CURRENT_PROJECT_VERSION、zip、校验、上传路径及 artifact 名中的 160644/Repair4 一次同步为 160645/Repair5。发布前须再查远端避免并发占号。

## 实际审查与依据

已读取 workflow、三项说明及测试，逐项读取/对比当前远端到本地九个核心 Swift 文件的增量，并补查 ChatStore、AgentProvider、ContextPolicy、Xcode 工程及共享 scheme。

1. **CollectionViewMessageListV3**：content/expanded 两路 publisher 均映射为 Void，Failure 均为 Never，可用于 Publishers.Merge；主队列 receive 位于 sink 前，使 @Published willSet 之后读取已提交值。UUID 脏集合与 diffable MessageListItem 类型一致；footer 分支实际存在；刷新仍沿用 discardPrecalc、block memo、cell cache 失效及 reconfigureItems，未改布局策略。thinking 通知不再 apply flush 前旧 snapshot。Combine 主队列不是语言层 actor 注解，但此处沿用既有 Coordinator/UIKit 主线程链，不引入 detached task。
2. **ChatModels / AssistantBlockView**：kind 支持 Equatable 文本比较；生产占位 getter 的空 text 判断可类型对齐。thinkingBody 为 ViewBuilder 内局部 View 值，可同时供隐藏测量与 ScrollView 使用；fixedSize、hidden、accessibilityHidden、overlay(alignment:content:)、textSelection 在 iOS 15 可用。String.Index 的 Optional.map/flatMap 返回同一 Index 类型；末尾换行回退 startIdx，未添加虚构 reasoning。隐藏测量副本不是运行效果证明，长短文本和选择性能仍需设备验收。
3. **MessageListInfrastructure / iOS15Compat / MessageListLayout**：FNV reduce 为 UInt64，字面量与 wrapping 乘法范围合理；AnyHashable.base、Unmanaged.toOpaque 与 UInt(bitPattern:) 为真实 API；host-owned identity 与 cell identity 分别记录，不以 index 充当身份。日志各 CGFloat/Bool/整数值在所在作用域存在。deferred 缓存通过旧 item→新 index 重映射，并在更新测量/失效/清空时撤销旧值；不改变 diffable 身份或正文布局。
4. **AIChatViewModel / Compaction / ChatStore**：VM 为 @MainActor，扩展压缩及队列闸门沿同一 actor；compactBefore 的新返回类型存在且返回路径显式 success/skipped/cancelled/failed，旧忽略结果调用由 @discardableResult 兼容。budget target 的 uiId/rawId 为 UUID/String，与调用点一致；toolResult 模式匹配为生产九关联值。ChatStore 为 actor，新 insertCompactMarkerUnlessCancelled 确实存在，调用使用 await；取消检查和 SQLite 插入之间没有悬挂点。成功提交后才解除闸门与调度 drain。
5. **发现并最小修正 actor 注解错位**：新增 CompactionOutcome 被插入到原 compactBefore 的 @MainActor 和方法之间，导致注解/文档实际挂到 enum。把 enum 移到文档前，@MainActor 归回 compactBefore；不改方法语义，不声称原来一定编译失败（VM 自身已有 actor 隔离），消除不必要 enum 隔离及跨工具链疑点。
6. **工程入口**：相关生产文件均在应用 target 的 Sources 链；Minis 主应用为 Swift 5 模式、iOS 15.5（工程中其他 target 的 Swift 6 不应误当本应用设置）。真实编译仍是 macos-15 + latest-stable Xcode 的 xcodebuild Minis Release / iphoneos / generic iOS build；Python 源码断言不是该入口的替代品。

## 本审查实际改动

- `src/ios/Agent/Chat/AIChatViewModel+Compaction.swift`：仅纠正上述 enum / @MainActor 的相邻次序。
- `.github/workflows/ios15-v64-repair.yml`：既有 autocompress、attribute_prefix、live_assistant 已以 V64R_REQUIRE_SWIFT=1 运行；render_contracts、text_layout、stream fade 也原已存在。新增 scroll_deferred_identity、longtext_container_layout，以及 **V64R_REQUIRE_SWIFT=1 thinking_visibility**；补齐这三项和既有 stream fade 脚本的 push paths，避免只改测试不触发工作流。没有重复跑已存在的 autocompress/render 测试。
- `docs/CURRENT-REPAIR-INTEGRATION.md`：本记录。

未把旧 `scripts/test_compact_orphan_toolcall.swift` 塞进 CI：它的 AgentContentPart 测试桩仍是八关联值，生产已为九值，且实现为历史粘贴而非本轮新增测试；不应因无关旧桩增加失败或虚假覆盖。

## 实际执行结果（同一工作目录）

| 测试 | 本地结果 | 边界 |
| --- | --- | --- |
| test_scroll_deferred_identity.py | 12 PASS | Python transition oracle / source |
| test_v64r_render_contracts.py | 7 PASS | source |
| test_longtext_container_layout.py | 3 PASS | source / XCTest 注册检查 |
| test_thinking_visibility.py | source + tail oracle PASS | 13 Swift getter 场景 SKIP，无 swift |
| test_v64r_autocompress.py | source PASS；actor 次序修改后再次 PASS | Swift budget/preferences SKIP |
| test_v64r_text_layout.py | PASS | source |
| test_stream_text_fade_source.py | 14 PASS | source |
| test_v64r_attribute_prefix.py | source PASS | Swift deferred |
| test_v64r_live_assistant.py | source PASS | Swift SKIP |

本机 `swift`/Xcode 不存在，未假报 Swift 解析、类型检查、完整编译或 UIKit runtime 结果。CI 的 REQUIRE_SWIFT 测试会在缺 Swift 时失败，不静默跳过。workflow YAML 已解析并核对测试/路径条目。

## 阻塞与剩余风险

1. **完整 Apple 编译未执行**：新增 Combine/SwiftUI 泛型和 actor 代码必须通过同一 SHA 的真实 xcodebuild；最新远端 workflow 成功不是本地三补丁的编译证据。
2. **Swift helper 覆盖有限**：thinking 是抽取生产 getter + Foundation 桩；autocompress 是抽取 budget/preferences，不覆盖真实队列、SQLite 和递归 provider。真正 target build 才检查全部生产 Swift API/actor。
3. **LongTextContainerLayoutTests.swift 未在现工作流运行**：文件由同步 MinisTests 组收录，但 workflow 仅 `build`，没有 simulator `test`。本次新增其 Python source 入口，不冒充三个 XCTest 已执行。该 XCTest 依赖 UIKit、应用 swizzle 及真实 SelectableMarkdownTextView；现有测试 target 尚有历史编译风险，不能只加 -only-testing 就假定其他测试不会编译。独立安排 simulator 测试/修复测试 target 后，方可解除长文运行验收阻塞。
4. **设备验收仍阻塞发布结论**：iOS 15 短/长 thinking 展开收起、无 reasoning 等待、离屏复用、流中新增块快滑、长文超过 2007pt、失败/取消压缩后的多队列保留和显式 Resume、marker 提交边界均未验证。保留现有布局；不以本轮源码通过宣称彻底修复。
5. **版本唯一性**：尚未把本地三补丁绑定到一个可发布 commit 或更新 build；应合成一个候选 SHA，用唯一 160645 完整验证，不能三份分别通过后混装不同产物。

## 同一版本文件指纹（SHA-256）

- AIChatViewModel.swift：`8fbc64e3ef98d1b2dcb2a6a5f97563f38f16cc36bc4c9270ac38e869c0008474`
- AIChatViewModel+Compaction.swift（actor 归位后）：`9f976ef0e47223ce7f0728653fe1fdcbd5f6453f86dce6679b6edacf10922fa5`
- ChatStore.swift：`1249959ab6329431b5e7a23aaf12ec216677864e1c2b54a1c7ab129685861a0d`
- ChatModels.swift：`fbc05e13043e853088fbc1e06fa7a69c4d2508d70e44fab1f731d1f10c35715c`
- AssistantBlockView.swift：`e8f8faf989899ba6f117529a96fd8f8d9c6b49885b4091131f24e41b69780adb`
- CollectionViewMessageListV3.swift：`9a959970d5b941ce0d5eb07e538bf956a038c038ca320e2ef7c3bcb642cdc08d`
- MessageListInfrastructure.swift：`e5f3a717fba47711dbdbf1b02d3fd1d3ab17ce566d9a88cc897451de96fbe241`
- MessageListLayout.swift：`511258fde55a27d02ac5cf9639bd3dc10a54927a5e0511134059838a1e67f5b2`
- iOS15Compat.swift：`47918c5ff3748a88f603227a68768803fddb97924f38e86cb15c956d261c808a`

未推送、未 dispatch、未重跑 CI、未安装或操作手机；GitHub 仅 GET，令牌不输出。
