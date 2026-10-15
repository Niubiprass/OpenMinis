# Thinking visibility current repair

## 范围与结论

本轮实际修改等待占位、已有 thinking 内容的展示和按消息身份刷新的视图链路；未修改 AIChatViewModel、ChatStore、摘要管理器，未推送、构建、安装或操作手机。现有 160644 textBlockLayoutSignal、本地长文容器/滚动身份补丁均保留。本目录没有 .git 元数据，不能用 git diff 证明全树差异；下述清单为本任务定点修改记录。

不能声称真机通过：DEVICE-160644-RESULTS.md 明确记录 160644 未通过，且当时模型 thinking 关闭，只有等待标签出现过，不能据此认定真实 reasoning 可见。当前修改仍需 Apple Swift 编译与 iOS 15 设备验收。

## 确证与假设

1. **源码确证：首个空 text 块会提前撤掉等待占位。** SSEStream 在 contentBlockStart 清除 isAwaitingModelResponse，再创建空 text 块；旧 shouldShowTypingIndicator 只认 blocks.isEmpty 或 awaiting，因此在实际文字提交前可能两者皆 false。占位不是隐藏 reasoning，只代表等待响应。
2. **源码确证：thinking 内嵌垂直 ScrollView 只有 maxHeight: 300，没有文本固有高度参与父 cell 测量。** iOS 15 hosting/self-sizing 在零或旧 proposal 下能否复现消失仍是假设；不能由源码宣称这就是用户每次不显示的唯一根因。
3. **源码确证：展开状态仅有 SwiftUI onChange/通知兜底。** 原 thinkingLayoutSubs 只观察 content，不观察模型 isThinkingExpanded；离屏视图/同轮 onChange 不可靠已有源码注释与历史诊断支持。
4. **源码确证：展开通知中 flushStreamingLayout 后又 apply 捕获的旧 snapshot。** flush 可重建当前块列表，再应用旧副本存在回退新行/复活旧行的逻辑窗口；具体快滑症状因果未经设备证明。
5. **源码确证：尾窗换行裁剪能把非空内容切为空串。** 长单行末尾只有一个换行时，firstIndex 指向最后字符，index(after:) 等于 endIndex，旧分片为空。
6. **需防御的复用风险：** ThinkingBlockView 保留 frozenThinkingContent 等 @State，父容器复用时必须以 block.id 隔离。不得把旧 thinking 冻结文本显示到新块。

## 实际修改

- `src/ios/Agent/Chat/ChatModels.swift`：shouldShowTypingIndicator 对“全部为尚无内容的 text 块”继续显示等待。thinking/tool/info 已有可见标题，不制造第二个等待行；完成态仍由视图 isActiveMessage 门控。模型不返回 reasoning 时不创建 thinking 块、不合成推理文字。
- `src/ios/Views/Chat/AssistantBlockView.swift`：ThinkingBlockView 增加 block.id 身份隔离；把现有真实窗口文本抽为 thinkingBody，隐藏测量副本提供固有高度（不参与 accessibility），最大 300pt 的同内容 ScrollView overlay 负责实际显示/滚动。无异步 GeometryReader 高度回写、无强塞 300pt 的短文本空白。保留 2K streaming / 8K finished 窗口、手动展开收起和冻结阅读语义；尾换行不能再裁为空。
- `src/ios/Agent/MessageList/CollectionViewMessageListV3.swift`：thinking 内容与 isThinkingExpanded 合并订阅，主队列在 @Published 提交后按稳定 UUID 加脏；继续使用既有节流、缓存清理、memo/precalc 失效和重配置。首个真实文字提交同时比对页脚形状，形状变化时将 assistantFooter 身份加入同一刷新队列，避免等待撤去后旧高度保留。脏队列过滤明确允许仍存在的 assistantFooter。展开通知不再在 flush 后 apply 旧快照。
- `scripts/test_v64r_text_layout.py`：原单 content 订阅契约更新为 content + expanded 双订阅，保留旧批次高度测试。
- `scripts/test_thinking_visibility.py`：新增实际生产占位 getter 的 Swift 提取测试（13 个场景，需 Swift host），以及思考固有尺寸/复用身份/双订阅/页脚清理/旧快照/尾换行的源码契约和 Python 边界 oracle。
- `docs/THINKING-VISIBILITY-CURRENT-REPAIR.md`：本记录。

没有修改 ChatMessageViews.swift：审查确认其 legacy assistantRow 已使用同一个 message.shouldShowTypingIndicator，并以 isActiveMessage 门控，修改共享谓词即覆盖；不复制一套条件。未修改 MessageListLayout/SelfSizingCell：已有 discardPrecalc、invalidateBlockMemos 和稳定身份刷新链已可复用，避免与本轮长文/快滑布局修复冲突。

## 已执行验证

- `python3 scripts/test_thinking_visibility.py`：源码契约通过；尾换行 Python oracle 通过。13 个生产 Swift getter 运行用例 **SKIP**，环境没有 swift。
- `python3 scripts/test_v64r_text_layout.py`：通过，仅源码契约。
- `python3 scripts/test_v64r_live_assistant.py`：源码契约通过，Swift helper 执行 **SKIP**。
- `python3 scripts/test_scroll_deferred_identity.py`：12 项通过（Python 模型/源码测试，非 UIKit）。
- `python3 scripts/test_longtext_container_layout.py`：3 项通过（源码）。
- `python3 scripts/test_v64r_render_contracts.py`：7 项通过。
- AssistantBlockView.swift 分隔符 sanity 通过；这不是 Swift 解析或编译证明。

## 必须区分的验收条件与未验证范围

1. 无 reasoning 模型：首请求等待及工具后下一请求等待应可见；空 text start 不应使页面静默；首批实际文字后等待撤去，完成/取消/错误后不残留。不能要求出现模型没发送的 thinking 内容。
2. 有真实 reasoning 数据：确认持久化/接收层确有非空 thinking content，再验标题、字符数、默认自动展开开关、手动展开/收起、流结束自动收起与用户手动状态。测试短/长、多段、长单行末尾换行、2K/8K 窗口边界。
3. iOS 15 高度：展开时真实文字可读且不截半，短内容不强留 300pt，长内容内滚动不超过 300pt；收起后无旧展开高度空白。
4. 复用/刷新：流中排队多个用户、快滑离屏再返回、在旧块暂停阅读后复用到新块、前后台/会话重进。不得串块、重叠、掉行、半截或持续大片空白。展开通知与新增块同时发生不能回退快照。
5. Swift/iOS 编译、实际 reasoning provider、UIKit/SwiftUI 渲染、选择文本 overlay 性能、快滑压力与真机无崩溃仍未验证。hidden 测量副本与 overlay 都只使用现有窗口文本，会增加一次有界布局工作，须在长 thinking 实机观察成本。源码通过不能替代上述验收。
6. 自动压缩和全局快滑长文问题由同轮其他代理处理；本记录仅对已列展示补丁负责，不能把这些源码测试等同于全问题已真机修复。
