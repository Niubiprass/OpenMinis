# 首页 ChatFolder 配置第一阶段（160651 候选）

2026-10-17，基线 `b113f88`。本记录仅覆盖本次配置层工作，不代表主代理并行实现的运行时链路已经通过测试。旧来源报告中“没有分组配置实现”的描述属于此次授权前状态。

## 修改范围与来源

- `src/ios/Agent/Chat/ChatStore.swift`：新增配置值类型、可选 `ChatFolder.configuration`、SQLite 可空列与幂等迁移、读取/条件保存 API、有界父链运行时上下文解析 API。
- `src/ios/Views/ContentView.swift`：原首页分组菜单新增“分组配置（本机候选）”，打开独立草稿编辑弹层；保存成功刷新首页；手机/宽屏两处导航按草稿 ID 传入目标分组。
- `src/ios/Views/Chat/AIChatView.swift`：扩展兼容默认 nil 的 `initialFolderId` 参数，在 CachedViewModel 创建草稿后立即设置 VM 初值；没有修改 AIChatViewModel 文件。
- `scripts/test_chat_folder_configuration_160651.py`：本次新增 Python 源码契约与抽取 SQL 的 SQLite 测试。
- 本文为本次新增文档。没有修改 Xcode 工程，新增 Swift 声明放在已编译的原文件中。

上述 Swift 配置模型、SQL 保存逻辑和弹层为此次 AI 新写实现，不是官方 1.15 或 Kelivo 源码移植。复用当前树的 ChatStore/ChatFolder/分组菜单结构、SkillStore.skills/reload 和 SoulStore.tokenCount/isOverLimit/bodyTokenLimit；未引入第三方代码、依赖或许可证变更。没有删除源码或重要文件。没有提交、push、构建、安装或操作手机。

## 固定接口

```swift
enum ChatFolderMemoryPolicy: String, Codable, Hashable {
    case global
    case folder
}
// ChatFolderConfiguration: Codable, Hashable
// 可用 ChatFolderConfiguration() 或 .default 创建后修改字段。
var skillDefaults: [String: Bool]  // 默认 [:]
var soulPrompt: String?           // 默认 nil
var memoryPolicy: ChatFolderMemoryPolicy // 默认 .global
var readsGlobalMemory: Bool       // 默认 false

// actor ChatStore
func getFolderConfiguration(_ id: String) throws -> ChatFolderConfiguration
func resolveFolderRuntimeContext(for sessionId: String) throws
    -> (folderId: String?, configuration: ChatFolderConfiguration)
@discardableResult
func saveFolderConfiguration(_ id: String,
    configuration: ChatFolderConfiguration,
    expected: ChatFolderConfiguration) throws -> ChatFolderConfiguration
// 既有接口未改：getSession(_ id: String) -> ChatSession?，含 folderId。
```

- 读取调用是 `try await ChatStore.shared.getFolderConfiguration(folderID)`；找不到分组、SQL 失败、损坏 JSON/未知记忆策略会抛错。
- `try await ChatStore.shared.resolveFolderRuntimeContext(for: sid)` 最多检查 16 个会话节点，子会话总是沿 parentSessionId 继承根会话，不采用子会话自行设置的 folderId。根无组或分组已删除返回 `(nil, .default)`；会话/父级缺失、循环或超深抛 `invalidSessionHierarchy`，配置读取/解码错误原样抛出，不静默回全局。
- 保存时 `expected` 必须是打开编辑器时读取的原值。先比较值，再以原 JSON 的精确内容作 SQL CAS。并发配置变更、分组删除或读写失败均不报成功；成功返回规范化后的配置。
- `ChatFolder.configuration` 可选，旧 Codable 缺字段仍能解码；`effectiveConfiguration` 提供默认值。SQL NULL 保持未配置语义。
- 首页列表对坏 JSON 容错，不因单个配置损坏而无法显示；设置页使用抛错读取，不静默用默认值覆盖损坏配置。

## 行为

- 用 ChatFolder UUID，不使用分组名或 ModelGroup ID。同名分组互不覆盖；重命名、置顶、远端旧格式重命名不会改本地配置列。
- 技能每项支持“继承全局 / 分组启用 / 分组禁用”。缺键继承，`false` 是显式禁用；恢复继承删除键。未安装的技能键保留，全部恢复继承会清空全部键。优先级契约：会话覆盖 > 分组默认 > 全局默认；本页不修改现有全局/会话开关。
- 灵魂正文空白保存为 nil，语义为继承全局；非空用于替换人格正文，不覆盖全局身份元数据或 SOUL.md。长度在 UI 和保存接口两层复用 SoulStore 的 2000-token 规则。
- 记忆默认 `.global`；`.folder` 可选择，不永久禁用。“读取全局记忆（只读）”默认 false，仅在 `.folder` 模式可改；切回 `.global` 保留但不使用该偏好。
- 编辑仅改值类型草稿；取消/下滑关闭不调用保存。保存期间禁用输入/关闭；失败显示错误并保留草稿，可显式重新载入。成功后才刷新并关闭。
- 文案标明本机候选、运行时负责实际生效、需独立测试且不是安全沙箱；没有声称配置保存等于记忆隔离已经验证。

## 运行时与持久化边界

本子任务没有修改 AIChatViewModel*、SkillStore、UnifiedModelPicker、记忆 UI 或同步代码。按主代理追加要求，仅扩展 ChatStore 的父链解析和 AIChatView 的草稿分组参数；VM 的 `initialFolderId: String?` 属性及 ensureSession 先 `setFolderIfUnfiled` 再运行由主代理实现。首页归组通知保留作 UI/旧路径补充，不能依靠该异步通知保证首条请求作用域。主代理另行负责技能继承解析、Soul 注入、目录/记忆工具/URL/普通文件/shell、子代理和定时入口作用域；本报告不替其结果背书。

配置保存不创建/迁移/复制/删除任何记忆，不改变会话 memoryEnabled。没有配置通知，运行时需要按请求重读或自行失效缓存；坏配置抛错后的运行时降级策略须由消费者明确决定，不能把列表的容错 nil 当安全保证。

此阶段仅本机 SQLite 持久化：不更新 FolderV2 的 updated_at，不 markDirty，不把配置加入 SyncedFolder。远端 upsert 保留已存在行的本地列；跨设备不传配置，远端删除仍按原逻辑删除文件夹行。

备份边界：现有 BackupExporter 序列化 ChatFolder，因新增 Codable 字段会带出配置；现有 BackupImporter 调 applyRemoteFolder，尚不会恢复该字段。不能宣称已完成配置备份往返；需后续显式实现与测试。原始数据库整库备份是否包含该列取决于既有备份方式，本轮未变更。

## 验证

```sh
cd /var/minis/shared/OpenMinis-160649
python3 scripts/test_chat_folder_configuration_160651.py
git diff --check -- src/ios/Agent/Chat/ChatStore.swift src/ios/Views/ContentView.swift
```

当前结果：7 项通过。包含 3 项源码契约及 4 项执行抽取 SQL 的 SQLite 测试：默认/旧库幂等迁移、同名 UUID 隔离、不改变分组更新时间、CAS 拒绝旧快照/已删除行、远端重命名保留本机配置。`git diff --check` 无错误。

未执行 Swift 编译、Apple-framework typecheck、App 构建或设备测试（遵守本次限制；环境亦无 swiftc）。上述测试不证明 SwiftUI 可编译、页面实机可用或运行时隔离已完成；下一阶段必须独立验收保存/取消/重开、技能优先级、灵魂正文和所有记忆入口。
