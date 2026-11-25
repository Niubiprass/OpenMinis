# Current: OpenMinis daily-action local candidate (2026-11-25; not pushed)

- User approved local-only changes for varied everyday pet animation, independent of roaming; preserve lyrics/music logic, existing movement, drag/chat/sleep/interactions and legacy imports.
- Baseline HEAD `0157569ac11b95a6f1393fc3b46f12f04e24dc99` (OpenMinis 1.16/build382). Release candidate target is build383; candidate is uncommitted in this isolated copy; no push, GitHub CI run, IPA, install, device action, audio capture, respring or reboot.
- The existing GitHub Actions App workflow now includes the portable daily-action test; its YAML and local test invocation were checked. This workflow edit is local only; GitHub has not run it. Existing `--require-native` gates remain fail-closed for the authorized macOS runner.
- App-side portable daily-action test ran 7/7; existing importer source/synthetic checks passed. Apple SDK/ImageIO/UIKit, CI/build/package, app runtime and phone visuals are not verified.
- Local host-C/path, parser/importer static, source-mirror and package checks passed. Apple SDK/ImageIO/UIKit, CI/build/package, app runtime and phone visuals are not verified.
- Artwork source terms are non-commercial; do not publish/package the assets for public or commercial distribution without resolving those terms.
- Detailed evidence: `/var/minis/shared/openminis/local-reviews/pet-lively-reuse-20261125/local-candidate/LOCAL-RESULT.md`. Stop at local-check gate; push/build and install each need separate approval.

---
# Historical records (not current authorization)

# 当前：桌宠歌词与音乐真实走跳本地修复（2026-11-23，未推送）

- 当前App源码HEAD501c227、手机1.16/build378；本轮仅本地同步歌词及音乐身体移动必要共享实现。插件HEAD26bf301、实装0.8.50；新候选插件0.8.51。主版本继续1.16，build不手改。
- 用户已确认重启整图/贴边范围/开启桌宠App闪退三项修好；本轮两项是自动歌词没有显示，以及音乐时固定角落仅局部姿态，需要真正走动/跳到别处。最新目标覆盖旧仅原地要求。
- 日间波浪调整已被用户暂停。开始时ComposerEffects.swift及test_composer_effects_20261123.py两个dirty完整冻结，不可掺入本轮修复或未来推送。
- **本地已完成（未推送）：** 两端19套最终回归零失败；双端真实中心走跳与音乐→拖动→甩抛→落地→恢复闭环、旧回调围栏及5项动作负例通过，歌词463生产C断言与8项负例通过，32保护及16项SDK15.5仅语法检查通过。新route枚举已镜像到设置日志reader。
- Foundation/NSURLSession/UIKit/Swift原生和真机仍未验证，没有真实歌曲查询，不能保证词库收录全部歌曲。最终证据在`../local-reviews/pet-music-local-repair-20261123/RESULT.md`及FINAL-AUDIT.json。
- 当前仅本地，无stage/commit/push/CI/设备操作/播放控制/麦克风/安装/注销/重启。**停在推送前闸门**；若获批发版，隔离提交共享修正，明确排除两个暂停日间草稿，不可提交整个worktree。

---
# 历史：三项修复续作，本地收齐（2026-11-22）

- 用户最新停止提问系统通知排查，明确续修波浪、桌宠摔倒/原地音乐、歌词获取到显示；只本地，不含提交、推送、CI、设备操作、安装、注销、重启、真实音频/歌曲查询。
- 当前实际 HEAD `b6eef3f425c0867cfb8ca8bcfbfc71c71fc15603`；实装记录为 App 1.15 / 固定 CFBundleVersion160652 / MinisBuildNumber358。旧下文版本与已通过测试仅作历史，不是本批完成态。
- 开始时20个已有dirty文件原件与diff冻结，当前范围、检查和并行结果以 `../local-reviews/three-repairs-resume-20261122/STATUS.md` 为准。输入框布局/控件、原手势/素材/录屏/权限/旧设置不动。
- 恢复首次波浪检查发现最后新增center参数未同步测试，8项中1ERROR；正在收齐并重新整体检查，不能沿用早先8/8或把模拟当真机验收。

---
# 历史：App 0.8.49 双端修复候选，本地检查完成待推送（2026-11-19）

- 基于本地 App HEAD `57b62fbdede841798f01607946b58d64c2d3d019`，候选版本 `0.8.49`；目标远端分支 `ios15-160652-four-features` 当前指向此前已发布 `96dfff6c7b07dc4a21d624a8b4ff76c5377d4495`。
- 本地验证通过：媒体姿态/物理 C 实际策略与三个编译负例，音乐轨道身份/回调源码契约，唤醒退役与手动语音保护，歌词/atlas/effects/liveliness/settings/shown/permissions 源码或便携检查，集成检查 `ISSUES 0`，共享文件和 `git diff --check` 一致通过。App 首轮 CI `44556127300` 在 `test_minisight_local_repairs_20261107.py` 因两条过时断言失败，未开始编译；更新为检查手动语音保留、旧名字请求拒绝及映射姿态行后，单项与完整本地 source/portable 矩阵均通过，追加修正待推送并由 CI 重验。
- 原生限制：当前 Linux/iSH 无 `xcrun`、`xcodebuild`、`swiftc`。Foundation 日志读写、UIKit/ImageIO 行为、App 编译、最终 IPA 与真机均未验证；严格 CI 原生门槛保留，结果待 CI。音乐反馈是 verified sprite row 的 2.5D，不是 3D；仓库无可用三维模型资产。
- 待推送差异含跨进程歌词阶段脱敏日志、媒体身份冲突切歌保护、重落地分阶段姿态与硬冲击吸收、受限音乐姿态/2.5D、退役名字监听与 Sherpa target。手动 ChatPanel 录音入口保留；无安装、开麦、设备操作、注销或重启授权。推送需使用 `$GITHUB_TOKEN`，CI 后另行报告。

---
# 历史：MiniSight0.8.47 本地整合通过，待授权推送执行（2026-11-18）

- 本轮用户问答卡 `local_repair: 可以`，批准本地处理歌词、名字唤醒、重启后素材整图背景及贴边活动范围；`storage_scan: 暂时不用`，余额/10.58GB均暂停。用户随后另行明确“这几个问题修复了，就推送”，批准本批完成本地检查后的双端提交/推送/CI，不再重复询问本批推送。设备/MCP、开麦、安装、注销、重启及整IPA下载仍未授权。
- 实际源码基线 `a9e3d7e833aa1377b0ef34a5fc97e704a950904d`；对应 build323 attempt2 已完整CI、最终IPA门槛与发布成功，证据见 `../local-reviews/wake-ort-crash-20261117/FINAL-CI-EVIDENCE.json`。下方旧“没有新包/未CI”记录已是历史。本轮实装 App/插件版本未补读，不能把323当手机实装或功能验收。
- 本地模块候选 `0.8.47-local.1`：双端去除 UIImageView 整图 getter、用当前布局恢复单帧，保动作海报及旧图集；音乐符号滑移定位改用 Apple dyld 的 __TEXT 基点，仍保代码/数据权限检查。均为源码机制修复，不是手机症状根因闭环。
- 普通桌宠改为身体完整在屏幕内且可贴边，UI安全区/气泡不再永久压缩活动范围；渲染层边缘适配保旋转四角不出屏，不移动命中区域；胶囊和审批仍保旧边界。原生Swift/UIKit、注销/重启真实画面未验。
- 首轮独审R1/R2/R3已取得两份真实补修FINAL：正常权限UI inactive与真实后台分离；后台/锁定/受保护数据/样式改变使pending事务失效；共用Speech权限仅增加三个协作取消guard。普通文本保存逻辑尺寸并重新布局，不用旧bounds/中心缓存误判，审批权限和按钮行为逐字保留。父已核11权限文件和18显示文件SHA；最终独立整合审查已确认LOCAL_READY_NATIVE_PENDING/blockers=[]，父核42个审查快照SHA均匹配。
- 既有 ORT隔离/旧VAD/固定模型、余额/Key/签到/视频、手动音频、OFF/锁屏/草稿/权限安全都受保护；App与插件差异不整覆盖。工程测试入口已本地登记，但未触发CI。
- 最终本地58入口：47普通退出0（36项含Apple/native SKIP）、9严格因缺Apple环境退出1并拒放、2个diffcheck通过；不是47原生通过。真实边界C449462+3编译后行为负例、旧布局1600029和相邻7便携入口通过。保护检查全部通过，源码差异/完整测试/未验项见 `docs/minisight-four-repairs-20261118.md`。
- 证据/范围/审计：`../local-reviews/pet-four-repairs-20261118/`。仍未stage/commit/push/CI；最终只读整合审查闭合后冻结精确SHA、按已获本批授权推送。手机歌词/名字实际根因及效果、冷启动和移动表现未验，不能称已真机修好。

---
# 历史：build316 ORT隔离修复候选，本地门槛闭合待冻结（2026-11-17）

- 根因以三份IPS与发布build316/UUID精确对应为准：名字Sherpa请求ORT API28，实际主程序的OrtGetApiBase却绑定旧VAD，仅支持1–20，空接口后Env+24崩溃。没有再查设备、复现或重启。
- 生产候选采用固定ORT1.28.2私有动态Sherpa框架和构造前兼容预检；不改旧VAD、手动语音、后台名字、OFF/锁屏/取消、歌词动作、额度消费或设置持久化。
- B1修订前checker `a0104d5b0e15e434a9726d2adaeb587a0dde3bc92935ab5fbe0c7d79343c72fe` 已由独立审计LOCAL_B1_PASS；最新工作树checker另加VM bind、zero-fill slot以及Apple ULEB64解码处理。Apple dyld-955证实传统bind以虚拟段地址计算、按uint64解码ULEB且pointer bind必须可写/不可执行。零填充bind仅作VM事件，不可通过关键函数的文件槽门槛；chained仍限文件槽。最新本地便携136例通过，加数/同槽及部分覆盖仍拒绝。
- B2固定旧VAD loader基线从真实build316 VAD生成，SHA `6bedabc71b689910bb12918561483ee3edd26c74507809c25d7571cb8d310aac`。真实库42项静态/便携检查通过；成品门槛用真实旧VAD配合合成新App入口，原库通过，libc++依赖、实际malloc链及OrtGetApiBase地址三种改动均拒绝。不是最终App。
- 已推送修复提交 `88012c8` 的build317和VM绑定修订 `70c022f` 的build318均在Mac runner编完253个依赖目标并链接后、被新framework实际bind解析拦截，未完成完整依赖proof/App编译/签名/IPA。build318精确反例为 `_OBJC_CLASS_$_NSProcessInfo` 的10字节ULEB编码被Python任意精度错误解析成 `0x10000000000000fa8`；Apple dyld 64位实际结果是段内 `0xfa8`。当前本地checker已按uint64截断修正，并加端到端legacy流正例。两个run的完整CRC日志分别在 `logs-44090041391.zip`、`logs-44116160899.zip`。
- 最新本地复核：136便携bind正反例通过（含BSS、权限及ULEB64端到端），24普通入口退出0，7严格缺Apple/产物门槛均精确拒绝，受保护源码和PBX仍与基线匹配。最新修订仍未stage/commit/push、未CI。Apple VAD重签、host dyld、完整iOS App及IPA/真机未通过或运行。没有新可安装版本。
- 两份新上传IPS仍为1.15/build160652、旧UUID：一份复现ORT `EXC_BAD_ACCESS` 于0x18；另一份是独立主线程 SwiftUI `ChildEnvironment.updateValue()` / `___chkstk_darwin` 探测失败，运行约2小时40分，具体业务触发和根因未证，未并入ORT修复。未查设备、不安装、不重启、不下载IPA。
- 根因与验收分层见 `docs/minisight-316-wake-runtime-crash-20261117.md`；长期证据目录 `shared/openminis/local-reviews/wake-ort-crash-20261117/`。

---
以下保留上一批记录，不是当前实装版本或本批授权。

# 历史：App304／MiniSight0.8.44 回归修复，本地0.8.45候选（2026-11-16）

- 用户最新“推送”已独立批准本批App／插件分别提交、推送与GitHub CI；不沿用下方旧授权。当前准备提交，尚无新CI结果；**未安装、开麦、设备设置、注销或重启**。App用GITHUB_TOKEN到Niubiprass/OpenMinis的ios15-160652-four-features，插件另用GITHUB_TOKEN_QQ到HGFdel-dav/theos-ci的minisight-0.8.45-20261116。基线b0bec05／8d433c1；此前已实装304／0.8.44并出现名字/余额/歌词反馈。
- 名字：生产BOOL writer与真实Swift reader严格旧整数兼容；缺失/过期状态不报假锁屏，可信锁/OFF仍立即停。原后台、有界3秒已授权被动交接、正常语音草稿和手动流程保留，不改音频生产源码。
- 余额：当前最后成功可用Key、默认主Key；2秒合并/30秒节流/前台查询/后台dirty/15分钟兜底。异步选择、key/row绑定、手动停用行、在途延期、新owner晚包围栏和带身份磁盘缓存已接。
- 音乐：真实shown文件有界读回/写反馈/新事务解除hide；设置与资源尾合并收敛，App快照路径保留、SB不重复显示。BOOL/v1镜像一致，不换私有媒体ABI、不把无词当停止播放；19:28根因仍未证。
- 新真实生产往返/异步/Foundation摘录/负例均已登记严格CI门槛，但本机Apple native明确SKIP，不当Swift/手机通过。候选模块0.8.45-local.1／插件0.8.45，尚无新build号或新包。详情`docs/minisight-304-regression-local-20261116.md`，检查证据`workspace/minisight-304-local-20261116/`。
- 既有未参与签到与真实待发送队列视频修复、所有素材/动作/录屏/语音/审批/Key轮询规则均保留。本批推送已另获批准，编译失败仅按实际日志修本批入口/类型/测试适配，不新增功能或跳过门槛；App GITHUB_TOKEN／插件GITHUB_TOKEN_QQ不可混，安装等仍另问。

---
以下上一批状态仅是历史记录；实际304和0.8.44构建已成功并由用户自行安装，不代表这批功能已通过。

# 历史：0.8.44 三功能＋签到/待发送队列视频修复（2026-11-16，当批已获推送及CI授权）

- 用户明确授权全部本地完成后App/插件分别推送、分别监控，失败可修复重推；App用GITHUB_TOKEN，插件用GITHUB_TOKEN_QQ。用户只需编译成功通知，自行安装；本次不安装/注销/重启/开麦/真实签到。
- 新目标修正：名字开关开启后离开App也要有效，不能收窄前台。现已接App真实后台input＋SB安全状态/回应/短语音；normal final与关面板分开，未发送草稿保留。主进程观察者不随UI卸载而关闭。App/插件需配套更新，强杀/系统回收后仍须打开App，真实效果未验。
- 待发送队列视频根因证据：录屏中是聊天区虚线消息，而旧GitHub修复d62e9a9等只改底部chip，QueuedAttachmentPreview.video自46373e8无点击入口。已补真实Button→V3显式转发→稳定播放器及独立文件租约，不触发发送或撤回。旧底部预览保留。
- 不可签账号：资格在任何尝试前，不可签不建持久记录/不计successfailureunsigned，旧未完成错记只清该身份；不明拒绝静默内存节流，真实成功/去重保留。build297实际第4号业务码未取得，不冒称根因码；不改余额/Key/账号。
- 原三项素材动作/在线当前歌词保留，版本同步0.8.44。新增微型通信/Audiopulse纳入实际编译目标，默认名字开关关闭。新原生测试在CI必须执行，本机明确SKIP。
- 唤醒许可前次实际Eigen来源无法证完，改CI固定源码受控构建：依赖SHA/CMake/Ninja原头/源匹配和实际链接门禁；正确OR T FAT→ar解析亲测1对象。本地不构建；编译后须实际证据通过方可发布。完整MPL源码/JSON通知已归档。
- 本地29入口、另受控构建源码守卫通过(新原生SKIP)，插件62源码协议/14497C、面板4100C/2变异负例。尚未运行新原生/手机验收；推送/CI结果另写。详见docs/minisight-batch-delivery-20261116.md。

---
以下为旧前台候选历史，不再代表最新范围和授权。

# 历史：MiniSight 0.8.43 直接名字唤醒接入稿（2026-11-16，仅本地）

- 用户接受原 App 前台本地边界后明确舍弃“嘿 Siri”路线，选择直接喊可配置名字。本地新增名字页/本机关键词检测/回应/既有短语音交接；不能认为当前安装版已有入口。未 commit / push / CI / 安装 / 开麦 / 注销 / 重启 / 系统Siri操作。
- 两端 HEAD 仍 `82f9fb1` / `1e816aa`，此前动作/歌词0.8.43候选与原dirty保留。默认关闭，2–8汉字＋读音确认；第一版仅 App 内显示端和前台，隐藏/锁定/通话/录屏/旧音频意图退让，未做后台/锁屏永驻。
- 直接调用固定sherpa v2.0.1 C API；4份模型/词表4733039字节已校验，资源/模型双重固定SHA，无示例词/音频或持续云识别。用户主动开启才允许申请麦克风；开发没有开麦。名字和读音配对保存，日志脱敏；51设置源码链路对齐。
- 声音所有权：wakeWord最低优先级，旧四配置和编号保留；原Speech入口归协调器.capture，拒抢VAD。列表/Key/签到/额度与VoiceBridge逐字同基线，录屏及审批未改权限。
- 取消保护：真实宠物锚点就绪才回应；同一面板代次交接；关闭/重开/键盘或发送接管拒绝旧回应续录，只有新增名字语音取消回写，原手动语音路径保留。无自动聊天发送或操作审批。
- 本地27定向入口通过，新原生明确SKIP；4100真实C门槛＋2行为变异负例通过。5强制缺SDK/许可负例拒绝放行。新原生行为及真实iOS15.5接口检查已登记待授权CI，未运行，不当真机证明。
- 发布阻断：预构建库Eigen对应源码/传递头许可及部分bundled版权未闭环。已归档通知；打包上传前新增必须闭环的闸门。编译/链接、真实识别、歌声误唤醒、耗电、音乐/蓝牙/录屏/通话/锁屏效果未验。此时不请求推送安装。
- 详见 `docs/minisight-name-wake-20261116.md`；证据 `workspace/pet-three-features/wake/checks-final/`。

---
以下为接入名字前的历史状态，不延续旧授权或未验证结论。

# 历史：MiniSight 通用动作与在线歌词 0.8.43 本地候选（2026-11-16）

- 授权：用户批准通用素材原动作+补充反馈和平滑衔接，后明确接受自动LRCLIB歌名/歌手/时长匹配；本批仅本地实施。未 commit / push / CI / 安装 / 注销 / 重启，未开启麦克风或查询真实歌曲。
- App基线 `82f9fb1` / build297，插件基线 `1e816aa` / 源码0.8.42；此前实装0.8.41。候选插件与App内模块升为0.8.43，不表示已构建或已装。
- 已接入：有界动作库、GIF/显式JSON动作文件夹、首帧就位后换画面、缺动作和失败回退、连续拖拽/轻晃/甩出/碰边/收势；只角色图层变形，原件/旧静态/Petdex保留。
- 在线歌词：多播放器共用私有系统进度+LRCLIB精确匹配，只当前行，暂停/无词/不匹配清空；默认关闭，独立歌词/音乐开关。观察仅可见且已解锁；系统API缺失失败关闭。媒体代次/单在途/同源三段复核/邮箱写盘与读回已接。
- 音乐动作仅平滑播放联动，无精准节拍数据；没有宣称各播放器最新版真机通过。第三项名字唤醒仍只有选型，不在这批源码里，须确认接入边界后继续。
- 本地：24个定向检查入口通过；新原生项目明确跳过。生产便携C动作40498检查+4行为变异负例及旧宠物/重力/布局/抛飞/聊天/录屏规则通过。Swift/UIKit/Foundation/ImageIO未编译/执行，11组原生动作夹具及新原生检查已接待授权CI，不当手机证明。
- 普通路径/取消/相邻：拖动取消不抛不存；切歌旧词不回写；短互动不循环重播；坏动作有限回海报；关闭/锁屏不取词。列表、Key、签到、额度、原语音桥接与音频协调文件等同基线。
- 未验证：真机灵动感、真实动作素材、低电量和内存、各播放器进度/在线匹配/暂停/切换/恢复。详见 `docs/minisight-liveliness-media-20261116.md`；证据工作目录 `workspace/pet-liveliness-local/checks/final`。

---
以下是历史状态，不延续旧授权。

# 历史：build296 后续三项修复（2026-11-16，已获推送授权）

- 授权：用户先以“可以”批准本地修改，随后明确“推送”，批准本批提交并运行 CI。基线为 `a1af951`；本条记录于提交前，构建与验包结果另记。未安装 / 注销 / 重启，设备操作仍须单独授权。
- 已核实基线：实装 1.15 / 160652 / build296，普通浏览截图多处缺分隔线；多 Key 编辑只加载了缩略文本；未知资格被当作签到失败。该账号资格日志未取得，已拒绝的日志读取不重试。
- 分隔线：保留普通真 Section 与原生侧滑，普通/排序共用 `ProviderRowSeparator`，只画非末成员底部一个物理像素；标题和组尾无横线。没有添加整行裁剪、没有改 `moveRows`、`providerLink`、`InstanceRow`。
- Key：编辑页加载完整原值，用多行编辑器查看/复制；列表仍遮罩。仅保存时写入，取消不写；空白或原值不替换，不重置原 Key 错误/冷却状态；重复替换继续阻止。
- 签到：明确可签 / 明确不可签 / 未知分开；`enable` 缺失不再默认可签，奖励字段异常不抹掉明确资格。不可签、未知、旧 pending 不进成功/失败计数，不提醒。只有同日明确资格 + 真正派发领取 + 明确业务拒绝才记录失败；结果丢失与取消不能伪造失败。发送前再校验资格，跨日/变更直接中止；已签静默、按账号去重、两小时重查保持。
- 并发与保存：旧 JSON 缺新字段按未知兼容；资格/领取/失败日记录持久化读回；慢到的未知查询按旧快照比对，不能抹掉新结果。清上一轮领取结果只在持有账号锁后执行。
- 检查：列表 4 项源码通过 / 4 Swift 项跳过；多 Key 34 项、签到 8 项源码、账单 5 项源码、分组 7 项、附件 14 项、每 Key 额度 21 项、Key 持久化 5 项通过；余额/换号/刷新相邻检查通过，diff-check 通过。
- 新增 CI 检查已接现有强制 Swift 入口：真实 Key Save 闭包、iOS15.5 编辑页+两态列表类型检查；真实签到策略/账本/接口/自动汇总，覆盖四号三成功一不可签、未知、真实领取失败、重复、取消、旧 JSON、跨日和并发。iSH 无 swiftc，以上 Swift 行为未本地编译/执行，不能把 fixture 或源码断言当真机证明。
- 未验证：iOS15.5 侧滑首末行圆角、复用/滚动/编辑切换后的分隔线；完整 Key 查看/复制/取消；第 4 个账号实际资格回包与提醒。未猜测新业务错误码；尚不能声称该账号已经实机修好。

---
以下是历史阶段记录，不延续旧推送/安装授权。

# 历史：多账号 / 签到 / 综合额度 / 分组排序（2026-11-14 本地）

- 阶段：本地改码与静态检查完成。未 Swift 编译、未推送、未触发 CI、未安装、未注销、未重启。
- 隔离树：`/var/minis/shared/openminis/minisight-workbuddy-trae-20261112`，分支 `local/workbuddy-trae-20261112`。
- 已通过：110 个脚本中 109 个（`test_ish_jit_fault_recovery.py` 需本机 RPC 脚本，环境不具备，非本轮回归）；
  另新增/更新：额度协议、订阅账单、签到日记录、分组排序、额度优先级、每键用户 ID、旧选择器白名单。
- 未验证：本机无 swiftc，新增 Swift 逻辑（账号界面、签到策略、额度分类文本）尚未编译与真机运行。

## 本轮修掉的阻断项（静态发现）
1. 账号区块要求 3 个回调但详情页只传实例，且同一区块出现两次 → 接通并去重。
2. 三个新文件未登记 pbxproj → 已加构建条目/文件引用/分组/编译阶段。
3. `hasOutput` 漏掉 `AssistantBlock.fallback` → 补齐穷尽分支。
4. 选择器里“上次使用供应商置顶”被整段删除（超出批准范围）→ 恢复，仅把基准顺序换成自定义组顺序。
5. 新增签到/额度测试未进 CI 清单 → 已加入 `ios15-v64-repair.yml`。

## 行为约定
- 多账号：共用一套模型；当前账号发请求；额度不足且尚未输出时自动顶号（默认开）；可手动切换。
- 签到：前台运行，每天每账号一次；只有服务端确认已签才记完成；未成功每 2 小时重试；轻提示不弹窗。
- 额度：账户余额 / Key 额度 / 套餐余量分开标注，不合并求和；失败原因单独显示。
- 账号数据只存 Keychain 与 extras_json；后台不变动订阅账号，不重放不确定写。

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
- App 已推送至 `ios15-160652-four-features`：首提交 `4799aa96b6726cdf542fd339eaded5d294e48435`，补桥接提交 `089f0121a55e1fc5484f5ef483c29a71c141f549`。首轮 CI run `42985110218` 因验证脚本沿用旧绝对路径失败；补桥接后的 run `42987278213` 因错误测试误要求显示服务商符号码而失败，已将行为断言改为验证该符号码不泄露。**仍需再推送一个仅修正测试的提交并重跑 CI**，不得称 App 构建成功。
- 插件 0.8.42 分支 `minisight-0.8.42-20261111` 提交 `1e816aa16e972b63718ed01e798ac3bba78b7c3f`，roothide 与 rootless CI 均成功；尚未下载 DEB/验包。App 与插件仍未 Apple 工具链同时验收；桌宠动作、键盘跟随与面板稳定性未真机验证。

## 2026-11-17 build308 模型选择卡死：本地候选与扩查收口（未推送）
- 用户反馈最新版点模型选择卡死，已退回上一版；3份IPS与308执行文件UUID一致。主cachedQuota等quota NSLock，后台store在持该锁的UserDefaults.set中等待；304同处先unlock后保存，本批回归已证。具体系统下游互等未精确符号化，不宣称锁闭环对象已全明。
- 用户“修的同时检查一下还有没有其他问题”仅授权本地修与扩查，不含本批提交、推送、CI、安装、开麦、设备、注销或重启。HEAD仍5fb44c26a4b79265f435068a614f04d14a7b567e；插件及Factory/轮转/音频生产未改。
- 本地quota候选：UI锁仅内存快照/围栏；row/current/retire共享utility串行writer与epoch/version顺序。JSON/Defaults、冷恢复、投影移锁外；恢复锁内复查epoch/version/identity/successAt。普通失效保有效durable，reset仅有序屏障，不扫全Defaults删盘。同owner的新成功保护防旧ticket删除其current；current代表/2s合并/30s自动/15min前台/disabled手动/轮转统计保持。
- 真实生产存储夹具新增：门控暂停保存+真实Defaults main通知，非空余额UI仍读；FIFO/current/row/owner定向删除、旧writer失效、合法冷恢复、同owner旧删、新内存挡迟到磁盘。变异重放持UI锁保存必须拒绝。8源码守卫通过，3Swift/native本机无工具明确SKIP；V64R_REQUIRE_SWIFT=1退出1硬拒（3缺工具失败），未原生运行。
- 父最终重跑29相邻入口exit0，其中16入口含Swift/Apple SKIP；不是29项全部原生通过。旧音频test_minisight_wake_audio_20261116仍3失败/4错误/1跳过（旧API/预期漂移），保留不删门槛。git diff --check及Python语法通过。
- 两份独立扩查有真实final：普通单Key消费入口缺失、成功回调乱序可选错代表、失效后dirty调度搁置、详情快照不随revision/阈值且缺UIgeneration；shown缺失非法App/插件读法分叉、设置页退出旧ON可覆盖菜单OFF、屏幕未知/熄屏混成锁事实。均源码条件推演、非当前IPS根因，未native/真机；额外路径尚未修改，须用户确认范围。ProviderPricing并无HEAD持锁set，此类推断已纠正，原类字节保持。
- 长期证据：shared/openminis/local-reviews/model-picker-watchdog-20261117/{QUOTA-LOCAL-REPAIR.md,ADJACENT-QUOTA-REVIEW.md,ADJACENT-NAME-MUSIC-REVIEW.md,other-issues-summary.md,adjacent-checks/RESULTS.json}。本地摘要docs/build308-quota-watchdog-local-20261117.md。当前待结果确认，推送与安装各另问。

## 2026-11-17 本批额外修复最终本地收口（最新）

- 用户后来批准一起修复，并独立明确“推送”；上段“额外路径尚未改/推送许可未获”仅为首轮历史。当前许可覆盖本批双端提交/推送/GitHub CI，不含设备、安装、注销、重启、开麦或完整IPA下载。
- 原余额UI内存锁与有序writer候选保留；失效后dirty有限补查、当前未落盘代表验证、后台与owner/epoch/running围栏已落。详情一个后台worker/一个pending，revision/阈值只投影，generation拒旧结果；取消/实例切换/手动结果/登录回调均纳入围栏。
- 单Key成功消费、实际main身份/请求epoch/真实完成Date冻结已接Agent/QuickTest/Offload。正常multi不双报；LLM具体类型、失败冷却/计数/取消路径保留，lastUsed采用max防乱序。
- shown双端严格读写，有关开关显式写入才交付，无关设置退出不写旧ON；运行端晚ON复核文件身份。schema2分离trusted lock与screenKnown/screenOff，可信锁/熄屏硬停，未知安全关闭不误称锁定。App模块0.8.46-local.1配插件0.8.46。
- 四任务真实final与所属文件冻结完成。父最终34个普通回归入口全部exit0，其中21入口含native SKIP，不能称34项native通过。6个required入口均因缺Swift/Apple工具非零硬拒；不算运行成功。新消费、详情、shown/name、旧音频及现行背景音频strict均登记CI。
- 旧audio测试按当前真实五单元摘录适配，15 source PASS/2 native SKIP；现行background原测试和四音频生产字节保持。最终矩阵还发现旧额度“按钮内必须3个detached”和旧shown“退出必须写cachedON”两项过时断言，仅test精确升级为有界worker/权威读回，4个临时缺陷负控全部被拒，没有倒改生产或删测试。
- 共享state/20新fixture/2音频镜像逐字一致，Resources平台差异保留。Pricing整类字节与基线一致，实际插件Tweak/Pet仅升版本、Panel/Music与App音频保持基线。两端diffcheck通过。插件旧host129/repairs/name60/guards3/approval13与新shown普通门槛通过，native仍未执行。
- 提交前状态：App基线5fb44c26a4b79265f435068a614f04d14a7b567e、P基线fd321d3a374cfce99aafb652830b9d63ad998f6d。当前准备按新授权stage/commit/push；CI结果待实际执行。未安装、未加载/真机验收；编译、安装、功能验收分开报告。
- 长期证据同目录四REPAIR报告、FROZEN-INTEGRATION.json、LEGACY-GATE-MUTANTS.json、extra-repair-checks/RESULTS.json；新发布记录shared/openminis/releases/Minis-0.8.46-20261117。
