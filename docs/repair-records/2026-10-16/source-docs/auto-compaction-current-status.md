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
