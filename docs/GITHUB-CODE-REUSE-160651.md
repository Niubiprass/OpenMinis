# 160651：GitHub现成代码检索与复用结果

日期：2026-10-17。用户要求先找GitHub现成实现，避免继续独立编写功能。当前HEAD为`b113f88f0d6035e15e16533af825fe250052d578`（160650）；本轮未提交、推送、构建或安装。

## 已落实到本地候选

### 1. 默认模型组添加按钮：原样复用本仓库历史代码

- 来源：[Niubiprass/OpenMinis，255a24f，UnifiedModelPicker.swift](https://github.com/Niubiprass/OpenMinis/blob/255a24feac02ab02ab24535bceee3207d0204112/src/ios/Views/Providers/UnifiedModelPicker.swift)。提交日期2026-09-29，说明为iOS15 ToolbarContentBuilder条件兼容修复。沿用项目GPL-3.0许可证。
- 当前`toolbarContent`整个代码块与该提交逐字一致：左侧独立`.topBarLeading`取消，右侧`.topBarTrailing`添加/单选完成；条件放在各项的`Group`中。
- [官方1.14源码](https://github.com/OpenMinis/OpenMinis/blob/b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c/src/ios/Views/Providers/UnifiedModelPicker.swift)也将多选取消/添加分成独立ToolbarItem；官方整个工程最低系统为16，故只恢复本仓库已有的iOS15兼容块，不整文件覆盖。
- 用途：多选后有明确的添加入口，回调仍走现有保存链。默认组、新建组、已有组加成员共用此选择器。没有改ProviderConfigStore或用户配置。
- 当前源码生产差异只剩此文件，17行新增、9行删除。此前独立写的cancellationAction/confirmationAction候选已由历史实现替代。

### 2. 记忆查看/编辑：恢复原有官方实现及160650兼容修订

- 来源：[官方MemoryManagementView.swift](https://github.com/OpenMinis/OpenMinis/blob/b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c/src/ios/Views/Settings/MemoryManagementView.swift)与[SessionMemoryView.swift](https://github.com/OpenMinis/OpenMinis/blob/b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c/src/ios/Views/Chat/SessionMemoryView.swift)，GPL-3.0。
- 当前两页已与160650的同名文件逐字一致，保留已有iOS15兼容改动。继续使用原`MemoryFileEditView`、`MemoryContentView`及保存链，不接入本轮独立写的新编辑器。
- 用途：查看已注入/召回的记忆、手动纠正全局或日记正文。现有功能不等于新分组管理已完成。

### 3. 文件分享：优先复用原项目组件

- [官方MinisShareSheet.swift](https://github.com/OpenMinis/OpenMinis/blob/b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c/src/ios/Views/Chat/MinisShareSheet.swift)，GPL-3.0。当前文件与官方逐字一致，包装单URL系统分享并带原有UTI处理。
- 当前基线`FileBrowserView.swift:892`已有`DocumentExportView`，暂存文件后调用系统分享；不是新写导出引擎。
- 上述均为单文件分享组件；基线`ContentView.ShareSheet`也只有单URL，不能称已有多选分享。记忆页面的新按钮/多选内容选择仍需接线，本轮没有把完整新UI伪装成原有代码。

## 查到但尚未接入的Swift组件

下载的固定提交源码、许可证和SHA256保存在`evidence/github-reuse-20261017/`及`reuse-sources.json`。最低版本是仓库声明，不代表本轮真实编译通过。

| 来源/固定提交 | 许可证、声明最低系统 | 实际功能 | 决定 |
|---|---|---|---|
| [marmelroy/FileBrowser @ b03284f](https://github.com/marmelroy/FileBrowser/tree/b03284f584d2bcf6325ce5a0352658be4f8848d0) | MIT；iOS8，Swift4 | 文件名搜索、预览；allowEditing控制删除，未查到正文编辑和多选分享 | 不整库引入，避免重复现有浏览器；不能当正文搜索或只读存储 |
| [SwiftUI-Plus/ActivityView @ a53e1f0](https://github.com/SwiftUI-Plus/ActivityView/tree/a53e1f09254f9280f04a6b14c05865c702d2d5eb) | MIT；iOS13，Swift工具5.3 | ActivityItem接收多个文件URL，系统分享及popover处理 | 多文件分享可复用候选；没有列表多选、编辑、权限控制，未接入 |
| [kyle-n/HighlightedTextEditor @ 759d7b4](https://github.com/kyle-n/HighlightedTextEditor/tree/759d7b4bd2c10d0bbe93bc62d68572a3702049e3) | MIT；iOS13，Swift工具5.3 | UITextView绑定、语法高亮、中文marked text处理 | 已有普通编辑器足够；不为新增高亮替换稳定编辑链，未接入 |

MIT源码若后续复制，须保留作者版权和许可；本轮仅作为调研证据保存，未添加依赖或纳入App编译。

## 分组技能/灵魂/独立记忆/全局只读：未找到可直接接入的整套实现

本次检索不证明全网不存在实现。核查了官方/本仓库历史、公开代码搜索命中的派生项目与若干Swift记忆方案，尚未取得满足当前ChatFolder数据结构、iOS15.5和完整工具执行边界的整套源码。

- 官方`ChatFolder`现有id/name/icon等字段；技能解析是会话覆盖→全局默认，SoulStore是全局，memory_get/write与系统提示仍读同一全局目录。不能通过复制普通编辑器解决组策略。
- [Moriefy/minis_advanced @ 1fbae1c](https://github.com/Moriefy/minis_advanced/tree/1fbae1c991ea4bc1a299eb64e9fd9d4ec6f43034)，GPL-3.0，检索命中ChatFolder/memoryEnabled；该命中本身不是分组独立记忆证据，未取得完整组策略实现。
- [Chevey339/kelivo @ a5900da](https://github.com/Chevey339/kelivo/tree/a5900dac44bdc2653674ae5f1b024499eaf5b31b)，AGPL-3.0，Dart/Flutter，按assistantId组织；默认写全局记忆，不能直接复制为本项目的Swift分组隔离。
- [thibautrey/multivibe @ 20e2d81](https://github.com/thibautrey/multivibe/tree/20e2d819978b2730d90789291c00cf55d81d01d8)，Apache-2.0。`CloudAgentState.swift`的memoryWriteScopes是云端状态操作的本地授权来源，不是OpenMinis文件目录路由；根SDK包要求iOS18/Swift6，整包不适用于15.5。
- [JamieScanlon/SwiftAgentHarness @ 461ccda](https://github.com/JamieScanlon/SwiftAgentHarness/tree/461ccdabb17f7eb5791076259435a4df2ecc42cd)，AGPL-3.0，Package.swift要求iOS18/Swift6；不能整包作为15.5替换。
- [nvwalj/ai-memory-reader @ 06311ae](https://github.com/nvwalj/ai-memory-reader/tree/06311aebe635e480a01c50993a693c1dba6683ac)的MarkdownEditorView被`#if os(macOS)`包裹，依赖AppKit/NSTextView，不能直接复制为iPhone编辑器；LICENSE自述GPL3，API未识别标准许可不能替代原文核查。

因此上述组功能及记忆正文搜索/多选管理本轮保持未完成。若继续实现，需要明确哪些是来源代码、哪些是本项目必要适配；“来自GitHub”也不能保证编译或运行绝对无bug。本次没有继续独立编写缺失的生产实现。

## 草稿保留和恢复范围

- 两份独立草稿`MemoryDocumentStore.swift`、`ScopedMemoryLibraryView.swift`仍在原位置，内容SHA256与修改前一致；未删除源码文件。
- 两页入口、Xcode项目和本地化已恢复到160650原字节；草稿退出编译/页面入口。
- 修改前15文件的完整备份：`evidence/github-reuse-20261017/160651-before-source-reuse-20261017.zip`。ZIP CRC及15文件SHA256验证通过；ZIP SHA256为`35222c1e14b1808295c7b49f18789b38a85a31a1d5f39033eac5404e144582c0`。不含凭据或用户记忆内容。
- 保留旧草稿的存储/SwiftUI检查脚本供历史追踪，其通过与否不代表当前App接入；接线脚本已改为验证草稿停用、基线完整和原版分享保持一致。

## 实际验证

- 模型选择器检查：4项源码检查PASS；额外真实iOS15.5 SwiftUI typecheck因无Xcode为SKIP。包括历史toolbar逐字一致、其余选择器与160650一致、现有提交链保留。
- 基线/保留检查：3项PASS。两记忆页面、Xcode项目、本地化逐字等于b113f88；两份草稿SHA256等于备份且未被项目/页面引用；MinisShareSheet逐字等于官方b4c0661。没有执行用户记忆读写或设备操作。
- `git diff --check`已通过；本轮生产差异只涉及UnifiedModelPicker工具栏。
- 未commit/push/CI/安装/重启，手机160650、仓库私密均未改变；本轮没有通过MCP操作手机。
