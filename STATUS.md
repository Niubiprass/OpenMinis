# MiniSight App + 附件修复状态（2026-11-08）

## 2026-11-10 审批中文化候选（本地未推送）
- App 审批卡改为调用与桌宠相同的有界中文摘要桥接；移除工具名、截断命令和原始 Shell 命令展示。
- 共享解析核心覆盖 `run_command --input`、管道、重定向、`find`、`grep`、`sort/uniq`、常用 MCP 工具及写入/删除/执行负例。
- App 工程已加入 Objective-C 摘要桥接和共享核心；只做源码/工程静态检查，未 Swift 编译、未 CI、未安装、未真机验收。

- 阶段：本地改码与静态检查完成，准备推送 CI。未安装、未注销、未重启。
- 基线：`Niubiprass/OpenMinis` / `ios15-160652-four-features` / `f6e65c8`。本轮在其上追加。
- 保留 245 已有修复：附件暂存改 Application Support、失效附件容错、DSML 工具解析、更新下载暂存。

## 本轮范围

1. 视频附件先解析成真实 `file://` 再交给 AVPlayer；播放器保留第二层兜底。修 17:57 黑屏 0:00。
2. 12:13 的 8×9 图集恢复单角色动作：渲染按 `列/8、状态行/9` 取单帧，不再切 64×81 碎片；整图静态照片仍整张显示。
3. 旧记录一次性迁移：245 把照片写成 v3、把图集当 72 外格；现按尺寸纠正为整图（1）或动画图集（3）。
4. 删除设置里的配色入口；插件不再叠加染色。
5. 删除 AI 页人设输入区（底层字段保留供连接保存）。
6. WAV `fmt` 块长度改为 16（原来误用 `frames*2=2800`），检查初始化/播放失败并可重试。
7. 设置全部实时：App 手势改读设置；插件每 0.5s 盯 revision/shown，大小与显隐即时应用。
8. 动作节奏按参考优化：拖动锁一个跑步动作到松手，摇晃不重置帧；徂移/跳跃才响，点击不再响。
9. 设置页缩略图翻正，不改存储方向；气泡改为随字数变大的面板，最长 42% 屏高后滚动。
10. 测试：视频必须 `isFileURL` 且经 session 解析；图集动画/整图断言；可解析 WAV 头；实时设置与拖动断言。

## 证据

- `python3 scripts/test_minisight_local_repairs_20261107.py` PASS
- `python3 scripts/test_attachment_preview_160651.py` 14/14 OK
- `python3 scripts/test_minisight_blip_wav.py` PASS
- `python3 scripts/test_minisight_settings_contract.py` 45/45
- CI 前置脚本批量运行通过；本地无 swiftc
- 真机素材分类复算：768×936 透明 PNG 为 57 帧，新的比例判定走 layout 3

## 未验证

- 未 Swift 编译、未 CI、未安装、未真机。
- 视频黑屏修复只到代码链；未读 AVPlayerItem 运行时 error。
- 动画帧是否完整、音效是否可闻、配色/人设是否真正消失，都要装机后看。
- 插件端 `MSLoadAtlas` 已区分照片/图集透明处理，但未编译。

## 授权

- 用户 2026-11-08：“赶紧修复，然后推送” = 修完允许推送。安装/注销/重启另问。

## 2026-11-11 桌宠灵动与错误中文化（待 App 推送）
- 用户明确同意按参考视频改造桌宠并要求推送 App 与插件；又明确允许成功构建后按原工作流替换公开 `beta-latest` 测试入口。
- App 目标远端 `ios15-160652-four-features` 基线 `44d96368dd24b45a56887c5b605f4c02a30e2fea`，远端未变；App 改动尚未提交/推送。
- 桌宠改为近邻漫步/跨行跳跃和边界限高，恢复眨眼、睡眠、唤醒与回应；输入编辑不再锁宠物，面板随宠物同步，宽度缓存分离限制值以防回摆。
- FriendlyErrorText 接聊天横幅/历史错误、Provider 模型读取/OAuth 登录展示；Provider 策略对象未修改。错误中文化本机静态用例 10、Provider digest 7、错误副本 6 通过；真实 Foundation 执行受本机无 swiftc 限制，macOS CI 负责。
- App 本地门禁：live-settings、MiniSight repair locks、工程引用/集成、设置诊断、审批安全、MCP/workflow 检查通过；C11 宠物 27433、布局 110336、跟随 5732、几何 1600001、重力 40015、聊天核心 233 通过。未 Swift 编译、未 CI、未验 IPA、未安装、未真机。
- CI 成功会替换 `beta-latest`；用户已在 2026-11-11 明确“可以”允许该行为。安装/卸载/注销/重启仍未授权。

## 2026-11-11 桌宠灵动与错误中文化（App，本地已检查）
- 用户已确认按参考视频改造整只桌宠并要求推送 App。App 目标分支 `ios15-160652-four-features` 远端仍为 `44d96368dd24b45a56887c5b605f4c02a30e2fea`；本地改动尚未提交/推送。
- 桌宠核心调整：邻近路线漫步、带水平位移且受边界约束的跨行跳跃、恢复眨眼/睡眠/唤醒帧逻辑，编辑时不再锁宠物；面板跟随刷新同步加快，防止面板宽度缓存交替重算。
- App 错误展示对聊天横幅、历史错误、模型获取和登录失败接入中文摘要。明确分类/清理 HTTP、JSON/SSE、取消、HTML；未知英文使用中文兜底。未改 `LLMError.swift`、`ProviderMultiKeys.swift` 策略逻辑。
- 本机静态/主机测试：live settings、MiniSight local repairs、PBX 集成、审批门禁、FriendlyErrorText 10、provider digest 7、error copy 6 均通过；C11 宠物 27433、聊天布局 110336、layout-follow 5732、screen geometry 1600001、gravity 40015、chat core 233 通过。Foundation 行为测试由实际 Swift 源码提取，但因 iSH 无 `swiftc`，编译执行待 CI 验证。
- App CI 成功后会删除并重建公开 `beta-latest` release。用户已明确允许这次替换；这不改手机已安装 App 或手头的旧包，只替换测试更新入口。安装、卸载、注销、重启均未授权。
- 未完成：App 尚未提交/推送/CI；App 与插件尚未 Apple 工具链构建或验包；桌宠动作、键盘跟随与面板稳定性尚未真机验证。
