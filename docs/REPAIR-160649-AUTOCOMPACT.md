# REPAIR-160649 自动压缩：进入/恢复会话自动触发

日期：2026-10-16。分支 ios15-v64-repair（HEAD 00c0c3a）。本文件只记录「进入/恢复会话自动压缩」这一项；高度守卫与正文流式是并行落盘改动，见对应文档。

## 用户诉求（原话）

> 进入会话后若已达阈值，不应弹确认让人点，应自己压缩；"自动压缩应该就是要它自己压缩，而不是要我点一下确认"。

现状事实（修复前）：发送前分支（AIChatViewModel.swift 2925–2954）仅在 `autoCompactEnabled` 读为 false 时才弹确认窗，true 则直接 `compactAndSend()`；该开关是全局实时读（`AutoCompactionPreferences.enabled`，键 `autoCompactOnThreshold`），默认关。16:09:57 弹窗是因为彼时开关读到 false（开关随后被开启，或点了弹窗内"压缩并开启自动压缩"；当前 plist=1）；16:12:30 压缩成功；17:12:33 新 marker 691DE71E 建立（compactedCount=106，summary≈24700 字），走的是自动路径——但「进入会话即触发」此前没有实现，本次补上。

## 修改文件与要点

| 文件 | 改动 |
|---|---|
| `src/ios/Agent/Chat/AIChatViewModel.swift` | 新增一次性闸门 `didCheckAutoCompactOnEntry`；在 `send()` / `resume()` / `retry()` 用户发起新一轮时重武装 |
| `src/ios/Agent/Chat/AIChatViewModel+Compaction.swift` | 新增 `autoCompactOnEntryIfNeeded()`：入口自动压缩的唯一判定函数 |
| `src/ios/Agent/Chat/AIChatViewModel+Persistence.swift` | 两个历史加载完成点挂钩：`loadSession()` 末尾（全量 DB 重建）、`reloadMessagesFromDB` 的 SKIP-LOAD 分支（缓存 VM 重进无 DB diff） |
| `src/ios/Agent/Chat/ContextPolicy.swift` | 未改动 |

### 入口判定（autoCompactOnEntryIfNeeded）闸门链（按序）

1. `activeSessionId == sessionId`：仅前台会话。`activeSessionId` 只有 AIChatView onAppear/sessionId 变更会写，后台 loadSession 调用方（任务/意图/其他会话的同步重载）永不触发。
2. `autoCompactEnabled`：全局实时读同一开关；关 = 行为与以前完全一致，不消耗闸门。
3. `!isProcessing, !isCompacting`：单飞，压缩中不重复触发。
4. `!isQueueBlockedByCompaction`：失败/取消后的队列闸门未解（只有 marker 提交成功才解）时，入口不自动重试——失败必须走显式 Resume//compact。
5. `!didCheckAutoCompactOnEntry`：同一次进入至多评估并启动一次；sync 触发的重复 loadSession 不会无限重试。
6. `checkContextBeforeSend(site: "entry") == .needsCompact`：与发送前完全同一 ContextPolicy 判定与窗口感知（resolveCurrentEntry + resolvedContextWindow + 校准后的 outbound 测量）。`.exhausted` 刻意不触发（与发送前自动分支一致：只有 `.needsCompact` 自动压）。
7. 有效消息 > 1（避免 compactAll 的"Not enough messages"状态行噪音）。
8. 消耗闸门 → `compactAll()`（与 resume() 队列阻塞时完全同一入口：不排队、不发送，无新建压缩状态机）。成功/失败语义全部沿用现有 compactBefore：成功提交 marker + 状态行 + post-compact drain（入口无排队物，drain 为空转）；失败保留内容 + 显式失败行 + 队列闸门。

### 交互对照（改动后）

| 场景 | 开关开（autoCompactOnThreshold=1） | 开关关（默认） |
|---|---|---|
| 进入/恢复会话（历史加载完成） | 达阈值 → 自动压缩，无弹窗、无需先发消息；未达阈值 → 不动 | 不动作（与以前完全一致） |
| 发送前（现有 2925–2954） | `.needsCompact` → 自动 compactAndSend | `.needsCompact` → 手动确认弹窗（"压缩并发送" / "压缩并开启自动压缩"） |
| 代理循环内（现有 in-loop guard） | 每轮迭代自动判定，`.needsCompact` 原地压缩后继续 | 同左（循环内本就无弹窗，不依赖开关） |
| 压缩失败/取消后 | 队列闸门置起：入口/自动路径不重试，内容保留；显式 Resume / /compact 才重试 | 同左 |

另：每次进入只触发一次（失败不无限重试）；用户新发消息/resume/retry 后重新武装，下次进入重新判定；空会话/无历史（loadSession 空会话早退）与低于阈值均不触发。

## 测试

```sh
python3 scripts/test_autocompact_entry_160649.py        # 本修复源契约
python3 scripts/test_v64r_autocompress.py               # 既有自动压缩回归
```

结果（iSH，无 Swift）：

```
Entry auto-compaction source contracts: PASS (not device tests)
Automatic compression source contracts: PASS (not device tests)
SKIP production Swift tests: no Swift here; mandatory on GitHub macOS
```

新测试覆盖（纯 Python 源契约）：① 两处挂钩位置与顺序（SKIP-LOAD 分支、loadSession TOTAL 日志之后 = 历史加载完成后）；② 入口闸门顺序（前台限定 → 开关 → 单飞 → 失败闸门 → 每访一次 → 同一阈值 → 消耗 → compactAll）；③ 入口不新建任务、不碰 pendingSendText/promptQueue/弹窗、不调用 send()；④ 开关默认值 `?? false` 未改、发送前手动/自动分支原样保留；⑤ 失败文案、队列闸门 `compactionQueueBlockedSessionId = sessionId`、marker 提交先于闸门解除与 drain（成功 marker 后顺序）；⑥ send/resume/retry 三处重武装。

## 为何此前弹窗（结论）

- 源码里弹窗只发生在 `sessionSource == "shortcut" || autoCompactEnabled` 为假时——即开关在**决策那一刻**读到 false 才弹；开关开着时接近阈值会自动压缩，不是每次都要确认。
- 该开关默认关（UserDefaults 缺键 `?? false`），安装新版不会自动开启；16:09:57 弹窗 = 当时开关读到 false（随后被开启，或点了弹窗内开启按钮），16:12:30 压缩成功，17:12:33 新 marker 691DE71E 走自动路径即佐证。
- 弹窗内"压缩并开启自动压缩"按钮始终显示，不能仅凭按钮/事后 plist=1 倒推决策时已开。

## 剩余限制

- iSH 无 Swift/Xcode：actor 隔离与完整 target 编译只能在 CI（macOS）验证；源契约通过 ≠ 真机通过。
- 主动 revert 压缩后，若同一 visit 内未消耗闸门、上下文再次达阈值，下一次加载完成可能自动重压（revert 的"看全量历史"意图与自动模式语义冲突，属预期取舍）。
- 未装机验证：进入时真实触发、失败状态展示、marker 提交后时序需真机滚动复验；未改默认值/模型/用户设置，未操作手机、未提交。