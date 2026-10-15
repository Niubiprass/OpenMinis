# OpenMinis iOS 15 修复交接

更新时间：2026-10-15（北京时间）。接手时先核对远端、CI 和手机实际版本，本文件是此时快照，不代表后续构建结果。

## 用户目标与约束

修复 iOS 15.5 聊天中的文字截断、不显示、思考内容空白、正文/工具行重叠、滑动后大段留白和闪退。必须以已装机实证对应的 160v64 源码 f017c76 为基线，不盲搬最新版全部布局守卫。用户授权通过越狱 MCP 操作 App、读文件和日志、测试、修改源码及推送 CI；不要自动安装、注销或重启手机。编译通过不等于运行通过。用户要求写文档、留记录供后续 AI 接手；上下文不足时允许自行新开会话续接。

## 仓库和凭据

- GitHub：Niubiprass/OpenMinis，修复分支 `ios15-v64-repair`；不要修改 main。
- 工作区：`/var/minis/workspace/OpenMinis-v64`。
- 当前修复提交：`c4dfa8dacbada30bf91847d7c50b130998584781`（160644）。
- 凭据变量是 **OPENMINIS**，不是 GITHUB。只引用环境变量，不打印/落盘凭据值。
- 安全助手：`/var/minis/workspace/openminis-ci.py`，支持 push / runs / status RUN / artifacts RUN / artifact ID FILE / logs RUN FILE。
- 构建工作流：`.github/workflows/ios15-v64-repair.yml`，macOS 真实 Swift/Xcode 构建。

## 版本事实，禁止混淆

- 160642 / 788ba15：修滚动停稳时 TextKit 内层过高；仍未达到验收。
- **手机当前已安装、已复测：160643 / 26e5bbc**。最新实测有明确异常，不能再说修好。
- **160644 / c4dfa8d：源码已提交推送，尚未安装或真机验收。**
- CI `38714599848`：https://github.com/Niubiprass/OpenMinis/actions/runs/38714599848 。本次记录时 in_progress，源码验证步骤 success，Build native libraries in_progress，Swift App 编译、打包、IPA 上传未完成。必须重新查询。
- 用户录屏时仍是 160643；工作区补丁不会改变已安装 App。此前回复把源码修改说得像已修复，用户已指出，后续必须清楚报告状态。

## 真机复现与证据

设备档案 iPhone 12、iOS15.5、RootHide。App bundle `com.openminis.app`。本轮 PID50283，仅为历史值。

MCP：`minis-mcp-cli tools 越狱mcp`；调用格式 `minis-mcp-cli call 越狱mcp TOOL --input '{...}'`，工具参数必须先查 schema，不猜。`run_command` 可用于只读日志查询。本地 helper `/var/minis/workspace/logquery.py` 将 @LOG@ 替换为日志路径。

本轮 App 数据容器（接手须重新核对，不保证永远不变）：
`/var/mobile/Containers/Data/Application/171D410E-956A-4299-9A36-1A9AE157EB7F`
日志 `Library/Logs/minis-2026-10-15.log`；数据库 `Library/MinisChat/minis.db`。不要写原始数据库。

测试会话 `CA9B8FF5-53D4-470E-8B64-535F72752CF6`，标题“iOS聊天列表高度缓存”，测试模型 aotera GPT6 Sol。40 个编号段落、约每段100字，生成中加入 `Q160643` 用户消息。

- 17:04:05 成功加入队列；连续 live1/2/3 UI 都停在第15段，约百字末段 accessibility 高度63pt。
- 17:05:08 FINAL FLUSH text4767/block4764；17:05:22 排队答复“收到。”完成。
- **后续已用 sessions CLI 读持久化全文确认：4767字符、编号到40均保存。** 因此不是模型只写15段，也不是后25段丢失。
- 退出重入仍显示到15段且63pt，紧随排队气泡（y542,h57）。这是显示/布局异常，具体根因需以补丁装机效果验证。
- 原长会话八轮上下滑动仍响应；swipe-5 OCR提示正文/工具行挤在一起，不能仅凭OCR断言所有交叠坐标。
- 本轮未观察新崩溃；16:34:48 crash属于160642后台异常，不归到160643。

本地证据 `/var/minis/workspace/test-160643/`：`persisted.json` 完整40段；`queue-live1/2/3.json`；`queue-final-before.json`；`queue-final-reenter.json`；`final-screen.jpg`；`contact.jpg`；各轮截图。含用户会话内容，仅本地诊断，不上传公开仓库。
用户追加：`/var/minis/attachments/uploads/photo_624F285F.jpg`（Thinking…内容不显示）；`video_8A3BDC05.mp4`（47MB，用户称与之前一样）。录像分析任务 5C35B06E 在运行，输出预计 `workspace/video-160643/`；接手核对任务结果，不预先声称分析完成。

## 160644 修了什么

文件：AIChatViewModel.swift、CollectionViewMessageListV3.swift、MessageListLayout.swift。

1. AssistantBlock.content 的 @Published 不会自动变为 ChatMessage.objectWillChange；旧列表观察 message 和 blocks.count，可能漏持续文本更新。新增 textBlockLayoutSignal，在文本/markdown/attributed缓存提交后发出，包括最终批次。
2. Coordinator 收集稳定 MessageListItem 身份，经原有节流刷新，按ID丢弃 index/precalc/cell 缓存，刷新估高并定点 reconfigure。
3. 思考块独立缓冲并发布 content，新增 block.$content 订阅；展开/折叠 discardPrecalc、清块 memo 并触发统一刷新。
4. 挂起/加载期间保留 dirty；恢复、加载完成后排空；rebind取消旧timer和订阅。按 block ID 前缀失效全部长度及 render-qualified memo，避免用过滤后的 messageIndex 索引原始 vm.messages。
5. 仍存在需关注的成本：最多每0.1s刷新一个批次，可能触发全量估高循环及变化行hosting替换；必须实测性能，不声称已优化完。

`isStreamingCell` 明确范围、latest assistant 选择、retry绑定等已在160643，不能当本次新修复重复报告。

## 验证和交付下一步

1. 查询 CI；失败则下载 build evidence/logs，定位真实 Swift 错误后修改再推送，不把源码正则检查当编译成功。
2. 新增 `scripts/test_v64r_text_layout.py` 为源码契约检查；既有7项布局/14项淡入通过；Swift host测试应以CI结果为准，UIKit布局仍需真机。
3. CI成功才下载 IPA，核对 build160644、bundle、最低15.5及 Mach-O/CodeDirectory页哈希。原版 VAD framework15.6 是既有精确例外，不改其字段，不承诺15.5语音可用。
4. 交付目录 `/var/minis/attachments/OpenMinis-160644-Repair4/`；预期IPA `Minis-160644-Repair4-iOS15.5.ipa`、完整干净Source.zip、Verification.json、SHA256SUMS、状态说明。
5. `/var/minis/workspace/package-openminis-160644.py` 和 `verify-openminis-160644.py` 已由160643脚本适配。源码脚本运行曾工具60秒超时；现有Source.zip可能是未完整归档，**务必重新运行到结束并逐文件核验，不因文件存在就算成功**。源码只包含主仓库跟踪文件，依赖gitlink列表在SOURCE-SUBMODULES.txt。
6. 用户自行安装后，再MCP核对新版本；重跑40段+生成中排队，逐段检查40都可读、展开思考正文、滑动/退回重入，不重叠不大段留白；对照V64R-TEXT-BATCH日志。当前没有160644真机通过证据。

完整交接应同时保存在仓库、可点击的本地文档及每日记忆。每次推进后更新这里的状态，避免下一位AI反复重做已确认的调查。
