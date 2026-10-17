# 160650：默认模型分组添加成员时缺少提交按钮

> 当前候选（2026-10-17更新）：用户要求复用GitHub现成代码，工具栏已改为逐字恢复本仓库历史提交`255a24feac02ab02ab24535bceee3207d0204112`的iOS15兼容块（左右ToolbarItem＋Group）；此前cancellationAction/confirmationAction方案仅保留为下文历史记录。4项源码检查通过，真实Swift编译SKIP，尚未提交或装机。详见`GITHUB-CODE-REUSE-160651.md`。

## 用户范围
用户接受160650现状，暂停其他布局和旧问题修复。本次仅调查“添加默认分组”选模型后不保存、是否缺少保存按钮；不修改源码或配置，不推送。

## 实测（2026-10-17约11:54–11:58）
通过越狱MCP打开 `minis://settings/model-groups`。
- 当前默认主分组为 `Default Models`，成员数0。
- 进入分组 → 添加模型。导航栏标题“添加模型”，右侧仅“取消”。
- 临时点选第一个模型，AX显示“已选择”，截图清楚显示蓝色勾选；导航栏仍只有“取消”，没有“添加(1)”或其他提交入口。
- 截图：本地 `evidence/group-picker-selected.jpg`（390×844）。
- 取消测试后返回分组列表，Default Models仍是0 models；随后退出设置回到原会话“完善 OpenMinis 并修复缺陷”，模型未变。
- 没有执行保存、创建/删除分组、默认模型调整、安装或重启。

## 源码定位（HEAD b113f88）
`src/ios/Views/Providers/UnifiedModelPicker.swift`：
- 267：多选保存在局部 `@State selectedEntryIds`。
- 1383–1390、1455–1460：点击行只增删临时勾选，不调用持久化。
- 795–809：`ToolbarItem(placement: .topBarTrailing)` 内同时放 Cancel 和 Add 两个 Button。只有 Add 调用 `config.onAddMulti?(selectedEntryIds)`，再关闭；取消/下滑关闭不提交。
- 真机iOS15.5已复现此结构下只显示Cancel，Add在AX和视觉中均缺失；不是用户没有成功勾选，也不是没有写保存代码。尚未对拆分toolbar后的候选进行编译/设备A-B验证。

提交链本身存在：
- `ModelGroupDetailView.swift:381–391` 的onAddMulti追加成员并调用 `store.updateGroup`。
- `GroupSlotPicker.swift:101–111` 的onAddMulti创建含成员的新组并分配默认槽位。
- `ProviderConfigStore.swift:1895–1931` 的addGroup/updateGroup最后均调用save。
- 目前没有证据指向磁盘写失败或配置被同步覆盖；无需修改Store或数据库。

## 最小修复建议（尚未实施）
仅拆分UnifiedModelPicker的多选工具栏：左侧独立cancellationAction的Cancel，右侧独立confirmationAction的Add(N)；单选Done保留独立工具栏项。保留现有onAddMulti、空选择禁用和dismiss语义，不引入自动保存，不改其他界面/布局/模型配置。修复后应验证勾选→Add可见可点→成员保存→重开仍在，以及取消不保存。

上述为最初只读诊断时的状态；当前可用160650未变。

## 2026-10-17 用户要求同轮合入，最小候选已实施
- 用户明确：默认分组模型选择修复必须与记忆管理/分组功能更新一起加入，不能漏掉或另推下一轮。
- `UnifiedModelPicker.toolbarContent`拆成独立`.cancellationAction`取消和`.confirmationAction`添加计数；单选Done仍在原`.topBarTrailing`独立项，条件放进各项的ViewBuilder内容，避免引入新的旧系统ToolbarContentBuilder条件能力要求。
- 保留`onAddMulti?(selectedEntryIds)`、空选择禁用、回调后关闭语义。除该工具栏外，整个选择器逐字保持b113f88基线一致；未改Store/默认绑定/模型配置。
- `scripts/test_model_group_picker_toolbar_160651.py`的3项源码契约通过；可选从实际候选抽取工具栏，在macOS用真实SwiftUI和iPhoneOS SDK、`arm64-apple-ios15.5`进行typecheck。本机无Xcode，该项明确SKIP；设置`V64R_REQUIRE_SWIFT=1`时缺编译器会失败，不把SKIP当通过。
- 尚未提交、推送、生成IPA或安装A-B，不能称真机已修好。待实测：0项时Add禁用→勾选1/多项时Add可见且计数正确→点击提交→重开仍有成员；取消无保存；单选Done和语音/视觉组原入口不回归。
