# 自动压缩与队列保护状态（本轮）

## 已完成

- `ContextPolicy` 的硬窗口判定仍优先于软预算；用户 cap 使用 `min(budget, nativeWindow)`，不会把 217600 误报为模型原生窗口。软预算只在 native window 安全时触发。
- `ContextSizeMeter` 对非 ASCII scalar 提高初次估算权重（中文不再按 `count/4` 类似比例低估）；首个真实 provider usage 仍会按同一请求校准。
- 分段摘要递归将 `summary1` 作为第二段的 `previousSummary`，避免递归分段丢失此前摘要；最终采用滚动摘要，不再以未保护的第三次合并请求丢弃结果。
- 压缩失败/取消设置会话级队列闸门：idle drain、统一 drain、尾递归和循环内注入均不会消费队列；不会因失败自动无限重试。显式 Resume/重试入口才重新尝试。
- 压缩成功提交 marker 后解除闸门并按原有路径 drain；排队消息在取消时保留，不再只恢复最后一条而丢弃前面文本/附件。
- 分段错误仍区分网络/取消/限流等不可由切分修复的错误与可切分 provider 错误，切分深度有界。

## 验证边界

已运行：

```sh
python3 scripts/test_v64r_autocompress.py
```

结果：`Automatic compression source contracts: PASS (not device tests)`；生产 Swift budget/preferences 测试因当前 iSH 无 Swift 而 SKIP（GitHub macOS 必须运行）。

本轮未构建、未推送、未操作手机。源码合同/静态回归通过不等于 Swift 编译通过，也不等于真机 provider、断网、取消和多队列时序测试通过。

## 遗留风险

- iSH 没有 Swift/Xcode，无法在本地确认 actor 隔离、Swift 语法和完整 target 编译。
- 中文权重是保守估算，不是 tokenizer；首个 provider usage 校准前仍可能有误差。
- 队列闸门依赖显式 Resume/compact UI 的可达性；真机需验证失败状态与排队气泡的展示，以及成功 marker 提交后 drain 的时序。
- SSL/TLS 用户主动断网属于不可重试网络失败，不作为“未及时触发自动压缩”的根因。

## 160648 手动确认弹窗核查（2026-10-16；基线 00c0c3a）

### 源码触发链

- `AIChatViewModel.send()`（2925–2954）：`skipCompactCheck` 未设置时先调用 `checkContextBeforeSend()`。结果 `.needsCompact` 且 `sessionSource == "shortcut" || autoCompactEnabled` 为真，会直接调用 `compactAndSend()`；只有这个条件为假才设置 `showCompactBeforeSendPrompt = true` 并记录 `Near capacity — prompting user to compact before send`。
- `AIChatView`（937–955）：绑定上述标志显示弹窗；“压缩并开启自动压缩”按钮**始终显示**，不能仅凭该按钮推断当前开关。点它才会先写 `vm.autoCompactEnabled = true`，再执行压缩发送；“压缩并发送”不修改全局偏好。
- `autoCompactEnabled`（VM 1250–1256）和全局设置（`ContentView` 8782）共用 `AutoCompactionPreferences.enabledKey = "autoCompactOnThreshold"`（`ContextPolicy` 215–224）。VM 每次决策重新读取 UserDefaults，无会话级副本；缺键默认 false，安装新版不会自行 opt-in。预算缺键默认 256000；85% 是 `min(预算,真实窗口)` 的软目标，不是修改模型窗口。
- 软预算位于代理循环内（VM 6400 起），只在真实窗口安全且有可保护当前轮次的旧历史锚点时触发。发送前的真实窗口保护先运行；若它已经进入手动弹窗，本次尚未进入循环，循环内软预算不会替它取消确认。128000 窗口的原生 compactThreshold 为 108000，而默认软预算目标为 108800，两者不是同一阈值。

### 主助手提供的真机证据与有限结论

- 当前安装 160648；16:16 起只读偏好得 `autoCompactOnThreshold=1`，无预算键。这证明读取时已开，**不证明 16:09:57 决策时也已开**。
- 同 PID 的 16:09:57 日志：window=128000、measured=277301、compactThreshold=108000、marker=nil、history=350，判定 `.needsCompact`；并有明确 `Near capacity — prompting user to compact before send`。结合本版源码，证明当时走了交互会话的 no-auto 分支，而非“开关已开仍强制确认”的分支；可能在随后弹窗首次启用，但缺少当时设置写入记录，不能断言是谁何时开启。
- 16:10:04 开始压缩原主会话、anchorIdx=349；16:12:30 提交 v2 marker 8ADBD892，随后 `Draining 2 queued prompt(s)`。此证据支持该次压缩和提交后队列消费已实际执行，不支持将网络/取消恢复风险当成此次弹窗根因。
- 当前 17% / 21.1k / 128k 是后续状态，不能倒推弹窗时预算读数。16:20 后 effective history 的 marker/349锚点仍与上述提交一致；marker=nil/history=30 的旁支不可混入主会话。

### 恢复边界与本轮处置

- 已有失败/取消队列闸门和 marker 提交后解锁（`+Compaction` 1082、1320）；Resume 在队列阻塞时走 `compactAll()`（VM 3666），loadSession 重置弹窗/压缩瞬态但不会替用户打开开关（`+Persistence` 237–250）。这些路径不写 true、不另行置位手动确认弹窗。
- 独立压缩失败的 canResume 展示、Stop 后显式重试的旧取消标志和 queued draft 跨 reload 仍需专门时序复测；本轮没有失败/取消的受控复现，不将其认定为截图已证实缺陷。
- **最终仅更新本文件；生产源码无改动。** 审查期间的恢复候选已撤回，避免在本次首次开启时序尚不确定时扩大修复面。未改默认值、模型、用户设置、布局或“Minis正在思考…”等待提示；未操作手机、推送或触发 CI。

### 本轮验证与下一次取证

`python3 scripts/test_v64r_autocompress.py`：源码合同 PASS；生产 Swift 预算/偏好执行因本机无 Swift 而 SKIP。它不等于 Xcode 编译或真机自动模式验收通过；本轮未新增生产回归，因为没有保留生产改动。

下一次若重现，需同一主会话、**弹窗出现之前**的开关读值、决策时 global enabled 与 sessionSource（只记布尔与来源，不记正文/密钥）、measured/window/budget/marker、开关写入时刻及压缩 outcome。不要只拿事后 enabled=1 或始终显示的按钮断言已开启时失效。只有显式同意后才测失败/Stop/Resume和多队列附件保留，勿为验收擅自关闭开关或清聊天。
