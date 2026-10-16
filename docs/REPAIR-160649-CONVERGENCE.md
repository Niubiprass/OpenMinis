# REPAIR-160649 主画面输出/发送后“疯狂闪跳”：同消息高度反复冲突修复

日期：2026-10-16（160648 装机器材，未装机验证）。分支 ios15-v64-repair。本文件只记录本修复，正文流式接线与自动压缩进入触发另见对应文档。

## 设备证据（何时、什么现象）

- 16:57 长消息（含工具卡等多块）发送后 16:57:47.210–49.326，约 2.1s 内：
  - `[CellSizing][V64-CONVERGE] item=3674100879148262446 idx=388` 同一上升路径出现 13 轮：
    持续 incoming=545 / super=raw=540 / tk=822 / final=822；穿插 `INVALIDATE est=822 → pref=540 cached=true`、`545 → 822 cached=false`，约 0.15–0.18s 一轮。
  - 高度在 540（SwiftUI 宿主）与 822（TextKit 权威）两套值之间反复，视觉上即“内容疯狂闪跳/上下跳动”。
- 17:01:48 / 17:02:14 另有 idx393/394/395 的 48↔186 反复（伴 footer 形态变化，非同因，未并入本轮）。
- 详细日志窗口：workspace 取证目录 send-time-window.txt / send-selected.txt（仅本机）。

## 根因（源码定位）

`SelfSizingCell.preferredLayoutAttributesFitting` 中：

1. 宿主（hosting）测量 `super.preferredLayoutAttributesFitting` 期间可能发生复用/重新配置（cell 实例变化、gen 世代 bump `configGeneration &+= 1`）。
2. 旧世代测量结果 `superAttrs`（540）在世代已变化后仍被当作“本次测量结果”回写，下一轮新世代又以 TextKit（822）校正 ⇒ 两个高度来源交替胜出，永不收敛。
3. 宽缓存命中分支只校验宽度接近，没有避开 `v53DebtIsRipe / v53SurplusIsRipe` 期间，放宽的 TextKit 校正结果会被旧缓存值（540）瞬间覆盖。

## 修复内容（src/ios/Agent/MessageList/MessageListInfrastructure.swift）

- 在宿主测量**之前**捕获 `gen = configGeneration`，并保留未测量的提议副本 `unmeasuredAttributes = layoutAttributes.copy()`。
- `super` 测量返回后立即守卫 `guard configGeneration == gen else { return unmeasuredAttributes }`——世代已变的旧 pass 不得发布任何结果（返回未修正提议，让新世代重新测量）。
- 正文测量汇合后的世代守卫同步改为返回 `unmeasuredAttributes`（而非已修正 attrs）。
- 宽缓存命中分支增加 `!v53DebtIsRipe, !v53SurplusIsRipe` 闸门：纠偏“ripe”期间不允许旧缓存值覆盖校正结果。
- TextKit 隐藏/嵌套视图的重复累加清理（宿主子树中的 SelectableMarkdownTextView 不再重复计入同一文本内容）。
- 未新增永久 max 锁、未禁用 self-size、未加全局限流守卫；合法收缩、宽度/身份隔离、工具/思考高度路径不受影响。

## 验证

- `python3 scripts/test_height_convergence_160649.py`：源契约断言（gen 快照、未测量提议返回、缓存命中查封、校正值写入与 memo）。
- 既有回归：scripts/test_host_stable_shrink.py、test_host_shrink_release.py、test_scroll_deferred_identity.py、test_text_measure_stability.py 等按仓库现有方式运行。
- 真实 Swift 编译仅能在 CI（macOS）验证；本机 iSH 无 Swift，源码契约不等于真机通过。

## 剩余风险 / 注意

- 世代守卫返回未测量提议的瞬间，若 UIKit 不立即重测，该帧可能短暂使用旧提议高度；预期由后续 invalidation 补测（与既有 4pt 空块保护一致），仍需装机滚动复验。
- “闪跳”还存在 App 前台被 SIGKILL/后台终止的用户侧现象（另见崩溃取证），本修复只针对高度不收敛路径。