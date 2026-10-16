# 160648：文字测量窄修复（尚待 UIKit 验证）

相对 `240bebf` 的生产修改仅 `SelectableMarkdownView.swift`；不修改输入框、不修改等待提示、淡入生命周期及属性前缀比较。

## 源码确认的缺陷及修补

1. `SelectableMarkdownTextView.sizeThatFits` 保存 `oldWidth` 却未恢复；异宽测量会影响后续从 `textContainer.size.width` 推导的 intrinsic 高度。用 `defer` 恢复宽高两轴，覆盖空文本分支，避免同值 setter。
2. `layoutSubviews` 在同宽同需求高度的重复布局里无条件调用 `invalidateIntrinsicContentSize`。改为宽度/重新捕获/实际需求高度差 >0.5 才失效，避免不变内容反复参与协商。内容提交仍有显式失效信号。
3. 长度相同的内容替换、换行/样式改变无法靠旧 `lastSizedStorageLen` 识别；实际 textStorage 提交后清内容相关测量 key 与 Coordinator 尺寸缓存，但不清历史实际高度/纠偏债，不拿旧高做 floor。

## 测试范围

`scripts/test_text_measure_stability.py` 从生产文件提取 `sizeThatFits`、`intrinsicContentSize`、key-reset 方法和需求变化判断表达式；macOS 使用 Foundation/UITextView 桩执行，不是另写 Python 实现。CI `V64R_REQUIRE_SWIFT=1` 无 Swift 必失败。本地源码 4 项通过，真实 Swift 项因无 Swift 跳过；完整 Xcode 编译另由 CI 验证。

覆盖异宽来回探测、父高变化、空文本、同值 setter、同长度替换/换行/样式及清 key 后重测。Foundation 桩不模拟 UIKit 字形、排版器和主线程真实回流，所以不能将测试通过当作跳字/闪屏已解决。

未采用超时审查中提到的输入框 inset 建议：该项本轮没有完整补丁/证据，不能记为已修。
