# 160651 功能开发候选：状态与验收门槛

日期：2026-10-17。基线 `b113f88f0d6035e15e16533af825fe250052d578`（160650）。开发分支 `ios15-160651-features-wip`，不替换稳定分支 `ios15-v64-repair`。本记录更新之前“仅按钮候选、记忆草稿停用”的历史状态；此前调研和归档继续保留。

## 真实实现来源

- 模型多选工具栏逐字复用本仓库历史 `255a24feac02ab02ab24535bceee3207d0204112` 的 iOS15 兼容结构，保留原提交和持久化链。
- 继续使用官方 ChatStore / SkillStore / SoulStore / MinisFsRouter / ISH 执行器及 MinisShareSheet。现有会话技能、MCP 全部启停未重复重写。
- 分组配置、运行时作用域、MemoryDocumentStore、范围记忆列表/编辑接线、环境变量启停是本轮新增 Swift / ObjC / Python 适配。不是提取的 App Store1.15 源码，不是现成 Kelivo Swift 工程。源码检索与许可证记录见 `GITHUB-CODE-REUSE-160651.md`。
- REA 没有运行；Android1.15-beta.4 只作为有官方哈希的跨平台参考，不证明 iOS1.15 行为。

## 已接入候选源码（不是已装可用）

| 功能 | 作用与场景 | 当前实现/限制 |
|---|---|---|
| 首页 ChatFolder 设置 | 将开发、写作、生活会话按用途设置默认值 | 使用稳定文件夹 ID；不是模型分组。独立草稿保存/取消，配置 SQL CAS 冲突检查。本机保存，未扩展云端同步格式 |
| 分组默认技能与会话覆盖 | 组内共用技能默认，特殊会话再覆盖 | 会话显式覆盖 > 分组默认 > 全局；恢复继承删除覆盖；接入真实请求技能目录 |
| 分组/会话灵魂正文 | 各分组使用不同角色及风格 | 继承/替换/追加/清空人格正文；会话可显式覆盖。名称/图标等全局 metadata 不变；下一轮请求生效；本机配置 |
| 分组记忆 | 同组共享，其他独立组不自动读取 | 组 ID 哈希目录；提示注入、memory_get/write、普通文件工具、会话 URL 路由及 shell fs_context 接线。子会话沿父链解析，异常拒绝而非回退全局 |
| 读取全局记忆（只读） | 保留通用偏好但项目新增只留本组 | 独立组默认关闭；开启时仅加入全局读取/提示根。组内新增仍只写本组；管理页全局根不可保存 |
| 记忆查看/全文搜索/编辑 | 查找规则、修正失效结论 | 同一存储与编辑器服务全局/分组页面；保存/取消分离，原始字节快照及 CAS 冲突提示；外部未协调写入不保证绝对原子 |
| 单篇/多选分享 | 手动交接或归档已选记忆 | 复用官方系统分享封装，多选导出合并 Markdown，包含来源/文件标题，只导出已保存快照；不自动上传、不改变跨组权限 |
| 默认模型组添加按钮 | 选中模型后有明确添加/取消入口 | 恢复历史左右独立工具栏结构，不自动改用户模型配置；iOS15.5 UI 验收待做 |
| 本机环境变量启停 | 暂停变量而不删除 Keychain 值 | 新 shell 过滤停用 key，同名变量按 key 联动；新 $$ 引用拒绝停用值；MCP 按非秘密 epoch 分池。旧进程/旧 shell/已保存服务商凭据不被撤销 |
| 技能来源复制 | 追溯 URL 导入技能来源 | 仅已有 URL 来源提供长按菜单；本机剪贴板 5 分钟过期；原始 URL 若含敏感查询参数仍需用户留意 |

## 本轮修正的具体问题

1. `file_write` 快速路径仅用于外部 mounts，显式传 `fsSessionId`；memory 路径统一先刷新分组配置、规范化并检查所属根，不使用最近挂载会话。
2. 执行协调器 `hostURL` 的 memory 分支必须显式 session，缺少已解析路由返回 nil，不回落静态全局挂载。
3. execute 的 in-flight 清理 defer 在任何新增可抛错的解析/建目录操作前注册，异常不遗留状态。
4. 交互终端在打开前解析组目录，启动时捕获 fs_context 与环境快照，不在后台读取可变全局快照。
5. provider 新的 $$NAME 解析仅读取启用值；保留原 loadValueSync 的备份/同步/脱敏语义。
6. 新 shell 的 MCP CLI 使用当前环境 epoch 的独立 daemon PID/port/lock，避免复用停用前的进程池；旧在途调用按原生命周期结束。

## 仍未完成，不能称完整交付

- 提问/确认卡、独立长图/PDF 导出、聊天搜索新 UI/跳转、定时详情快捷操作、服务商额度、朗读音量、模型目录、常亮调暗等其他1.15项没有在本候选中全量复现。
- 高风险的工具折叠、原位高亮、语音切换、上下文裁剪、AOJIT 未合入；语音 VAD 原预编译框架最低15.6风险保留。Live Activities (16.1+) 和 BGContinuedProcessingTask (26+) 不可原样用于15.5。
- 分组配置/灵魂/记忆没有新跨设备同步或全量备份格式，不借用全局记录 ID 上传私有组记忆。
- 共享 rootfs 中是逻辑作用域，不是针对恶意任意 shell 的安全沙盒。历史消息/已读模型信息不随开关清除；组归属中途变化及多个会话并发操作仍需实测。
- 不自动迁移、复制、删除旧全局记忆，不删除源码/重要文件，不自动安装或重启。

## 验证结果

本地最终检查（含最后的终端及路由修订后）：
- 7 份新增功能脚本共 57 项：**53 通过、4 跳过**。跳过项是 Foundation 分组策略运行、Foundation 记忆存储运行、真实 SwiftUI 记忆页及模型工具栏 typecheck；Linux 没有 swiftc/Xcode。
- 原16份稳定基线回归脚本全部 exit 0；其中需要真实 Swift 的部分仍可本机跳过，不等于全部执行过 UIKit。
- 新 Python AST、MCP CLI AST、本地化 JSON 及 `git diff --check` 通过。
- 上述本机检查主要是源码契约、提取 SQL 和有限 Python 行为检查；真实 Swift 和完整 App 编译的结果以本节下方的成功 CI 为准，仍不等于真机验收。

CI 已加入上述测试的 `V64R_REQUIRE_SWIFT=1` 强制门槛和完整 App 编译，产物命名 `Minis-160651-FeaturesWIP-iOS15.5`。用户明确授权后，仓库已公开；公开分支的 macOS runner 已真实启动。

## 实际提交与云构建结果

- 功能代码提交：`8e3502d0536b4dab87a37b92da639b89d5f82dae`，46 文件，3287 行新增 / 360 行移除；是修改行数，不存在删除源码文件的提交条目。
- 分支 `ios15-160651-features-wip` 已成功推送；用户本人完成 GitHub sudo 验证后，匿名 API 200、`private:false`，仓库改为公开。旧版私有 run [39017629361](https://github.com/Niubiprass/OpenMinis/actions/runs/39017629361) 因付款/额度限制仅 6 秒失败，job 未启动。
- 按用户要求，只用 **git push 自动触发**后续构建，不在网页点重跑：提交 `75eaa3e` 的 [run 39018852274](https://github.com/Niubiprass/OpenMinis/actions/runs/39018852274) 真实启动，在 `Verify fixed source` 失败：`MemoryDocumentStore.Failure.unsafePath`，未进入 App 编译。
- 用阶段标记提交 `74cdc3a` 的 [run 39020478351](https://github.com/Niubiprass/OpenMinis/actions/runs/39020478351) 将故障收敛至缺失记忆根目录的首个 `store.list()`；`6128750` 保留 symlink 安全检查并将目录 URL 规范化、增添回归断言。
- [成功 run 39021064234](https://github.com/Niubiprass/OpenMinis/actions/runs/39021064234)：commit `612875010b65e7e426dcde0cfd99563e6cb9b71d`、`completed/success`，真实 Swift 测试、原生依赖、完整 iOS App 编译、打包和上传步骤均为 success；两个未过期 Artifacts：`Minis-160651-FeaturesWIP-iOS15.5`（72,882,266 字节，artifact 12096784894）及 `Minis-v64r-build-evidence`（148,362 字节）。仅核验 API 中产物记录，尚未逐文件检查下载 IPA 的 Info.plist/Mach-O/校验值或安装。
- 稳定远端 `ios15-v64-repair` 仍在旧基线 `b113f88f0d6035e15e16533af825fe250052d578`；未安装、重启或替换手机160650。公开仓库的源码、提交历史及 Actions 日志现在对所有人可见。

**构建成功不等于运行成功或 1.15 功能全量复现。** 本候选尚未真机验收；其他 1.15 未完成项仍是原同版目标，本分支只是开发候选，不能冒充正式发布。
