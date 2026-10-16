# REPAIR-160649 正文流式定时尾沿接线（160648 装机器材，未装机验证）

日期：2026-10-16。分支 ios15-v64-repair（HEAD 00c0c3a，工作树未提交）。
本文件只记录本修复；主画面高度收敛见 REPAIR-160649-CONVERGENCE.md，自动压缩见
REPAIR-160649-AUTOCOMPACT.md / REPAIR-SCOPE-TEXT-AUTOCOMPACT.md。

## 设备证据（何时、什么现象）

docs/DEVICE-160648-TEXT-STREAM-FIRST-PASS.md：同一模型 286 字回复，约 1.84s 内
屏幕只增 5 字，随后 0.9s 集中蹦出 82 字——纯文本输出"不流动、停顿后成批蹦出"。

## 根因（源码现状）

`src/ios/Agent/Chat/AIChatViewModel+SSEStream.swift` 的 `.textDelta` 分支原先
是**纯增量驱动**的分档节流：只在「下一条 delta 到达时」检查 `elapsed >= throttle`
（<500 字 0.20s 起）。它没有任何"安静期定时尾沿"：

1. provider 停顿多久，已到文本就憋多久——停顿本身就是最长的提交延迟；
2. 干净结束（流终止/`.done`）后，正文尾沿只靠 CancellationError 路径补提交，
   StreamResult 正常返回路径本身没有尾沿提交（依赖调用方的 FINAL FLUSH，但那在
   整个 agent 循环收尾时才会跑）；
3. 此前代理留下的 `actor StreamTextDelivery`（enqueue/drain/stop/finish，
   interval 表 0.06/0.10/0.20/1.00/1.50/2.00s）只有定义、无任何调用点，是死代码。

## 修复内容（仅 src/ios/Agent/Chat/AIChatViewModel+SSEStream.swift）

### 1. 接线：worker 成为 textDelta 的唯一提交者（定时尾沿）

- `.textDelta` 分支删除原内联 throttle 提交（0.20/0.30/0.50/1.00/1.50/2.00s
  表 + newline fast-path + `lastTextDeltaFlush*` 记账），改为每次 delta 调用
  `await textDelivery.enqueue(result.assistantText, block: blockIdx)`：
  最新快照进 pending，worker 按自己的分档 interval 提交（首次无 lastDelivery 时
  立即提交，与旧代码"首条 delta 立即刷"一致）。
- 效果：**安静期尾沿在短文本 ≤0.06s（<500 utf16）/≤0.10s（<2000）/≤0.20s
  （<32k）内提交，即使 provider 不再发事件**；连续流按同表分档合并提交，
  提交节奏 = interval 表（模拟验证：5ms delta 连续流最小提交间隔 0.061s），
  不存在逐 chunk 全量 markdown 重解析风暴。
- **长文本（≥32k）节流从缓**：64k/128k/∞ 档 1.00/1.50/2.00s 与旧 throttle
  完全一致，32k–64k 档反而从 0.50s 放宽到 1.00s；0x8BADF00D 的 O(N²) 全量
  markdown 风暴（每 chunk ~30ms 全量重解析）在结构上不可能重开——单 worker
  至多每档一次提交，且纯 off-main 解析 + MainActor 一次性写入。
- TTS 语义不变：首次 delta 的 `stopSpeechForThisSession`（本轮清旧回复语音）、
  `extractNewSentences`/`feedDynamicTTS` 句子抽取全部保留在 delta 分支原位置。
- sink 提交语义与旧代码逐项对齐：非最终 → `cacheAttributedString: false,
  requestScroll: true`（即旧的 flush 行为，滚动由 setStreamingTextBlockContent
  内部 isNearBottom 判断）；最终 → `cacheAttributedString: true, requestScroll:
  false`。
- sink 携带 enqueue 时刻的 `blockIdx`（Sink 签名改为 `(Int, String, Bool)`），
  提交永不落到之后新开的块上。

### 2. 干净结束立即提交完整正文尾沿

StreamResult 返回路径（TTS 尾部抽取/强制 flush 之后、`return result` 之前）：
`await textDelivery.finish(with: result.assistantText, block: currentTextBlockIdx
?? -1)` —— stop worker（join，杜绝旧快照盖掉最终文本）后立即以 isFinal 提交
完整正文。调用方（AIChatViewModel.swift，禁改文件）的 FINAL FLUSH 随后检测到
`content == assistantText` 走 SKIP 分支，幂等。

### 3. 取消 / 错误 / 一轮结束：停止 worker，旧快照不得覆盖最终文本

- `catch is CancellationError`：原内联 flush 改为 `finish(...)` 后 rethrow
  （并 join 掉可能尚在途中的 worker，防止 throw 之后旧快照落盘）。
- `catch { isStreamInterrupted }` 错误路径：新增同样的 `finish(...)` 再 throw
  ——中途失败也把已到达文本交付（与取消路径对齐；此前该路径不提交）。
- 新一轮不残留：`textDelivery` 是 `processStreamEvents` 的局部量，每次都新建，
  函数返回即结束生命周期；不存在跨轮 worker。
- mid-stream 边界（`.contentBlockStart(.toolUse)`，append 工具块之前）：
  `await textDelivery.settle()` —— cancel + join + 清 pending，**但不 closed**，
  之后新文本块的 enqueue 可重新武装。顺序保持：正文 flush（step-1）→ 工具块
  append（step-2）→ 工具块发布 `publishUnlessTransitioning` 不变。
- `finish` 对空文本只 stop 不提交；blockIdx 为 -1 时 sink 侧守卫直接返回。

### 4. actor 语义调整说明（任务点 3）

原死代码的 `Sink (String, Bool)` 不能表达"提交到哪个块"，`stop()` 的永久
closed 语义也不能用于 mid-stream 工具边界（否则后续文本块失去尾沿）。因此：
- Sink 增加 block 参数 `(Int, String, Bool) async -> Void`；
- 新增 `settle()`：可再武装的 mid-stream join（cancel+await+清 pending，
  不置 closed）；
- 新增 `noteExternalCommit` 未采用（单提交者设计下无外部提交可去重）；
- drain 循环、interval 表、stop/finish 的"先 closed 再 cancel/join"顺序保持
  原样。死代码已全部消解：actor 每个公开入口都有真实调用点。

## 验证

- `python3 scripts/test_stream_delivery_160649.py`：11 项源契约全过
  （接线点存在、interval 单调且等于 0.06/0.10/0.20/1.00/1.50/2.00、六个档位
  阈值顺序、settle 先于工具块 append、取消/错误/干净结束三路径 finish 均在
  throw/return 之前、TTS/scroll 语义保留、`setStreamingTextBlockContent` 调用
  收敛为 2 处、无 lastTextDeltaFlush* 残留）。
- 负向对照 `--ref 00c0c3a`（未接线基线）失败 ⇒ 断言有区分度。
- 语义模拟（asyncio 复刻 actor 时序，本机运行）：安静尾沿在最后 delta 后
  ≤0.11s 提交；finish 后 0.3s 无过期提交；settle 后无提交且可再武装；
  5ms delta 连续流最小提交间隔 0.061s（无风暴）。
- 既有回归全过：test_stream_text_fade_source.py / test_height_convergence_160649.py
  / test_autocompact_entry_160649.py / test_host_* / test_scroll_* /
  test_longtext_container_layout.py / test_text_measure_stability.py 等
  （`python3 scripts/test_*.py`）。

## 未真机验证声明

- 本机（iSH/Alpine）无 Swift 工具链：**未编译、未装真机、未实测真实流**。
  源契约测试 + 逻辑模拟 ≠ SwiftUI/TextKit 主线程行为。真实编译与 iOS 15 真机
  流式手感验证必须在 CI（macOS Xcode）与装机后完成。
- 主要待装机观察项：短文本 0.06s 档比旧 0.20s 档加密了提交节奏（~3x），
  小文本的 SwiftUI diff 与滚动信号频率升高；若旧机型出现主线程压力，优先把
  <500 档调回 0.10–0.12s（表内唯一可调点，测试会随之断言）。
- 32k–64k 档由 0.50s 放宽到 1.00s：长文本中途批量感可能略明显，换取
  O(N²) 风暴不重开；如手感不可接受，可单独放回 0.50s（不违反"≥32k 从缓"）。

## 剩余限制 / 后续

- CI 工作流（.github/workflows/ios15-v64-repair.yml）不在本轮可改文件清单内，
  需要由 CI 维护者追加一行 `python3 scripts/test_stream_delivery_160649.py`
  （与 test_stream_text_fade_source.py 同列）。
- 上游 provider 长时间（>stall timeout 120s）静默仍由既有 stall watchdog 处理，
  不在本轮范围。
- 并行代理正在改 AIChatViewModel.swift / Compaction / Persistence（自动压缩）
  与 MessageList 高度守卫——均与本文件无交集，工作树内未互相触碰。