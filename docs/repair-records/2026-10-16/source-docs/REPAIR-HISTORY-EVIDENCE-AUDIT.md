# OpenMinis 修复历史与实测证据审计

审计日期：2026-10-15。仓库：[Niubiprass/OpenMinis](https://github.com/Niubiprass/OpenMinis)。本报告是历史证据审计，不是新版本验收。

## 1. 先给结论

1. **用户最新明确反馈应作为当前症状边界：纯文本感觉问题不大，卡字、文字消失、打字闪屏现在不再出现；主要仍是卡片、操作框、思考框、工具框异常。** 这证明当前组合在用户实际使用中改善了纯文本，不证明每个历史补丁单独有效，更不代表长文、IME、所有模型和宽度均通过。
2. **160645 真机失败；160646 只能称候选。** 160645 有用户反馈及同 item 的 raw/locked 高度差、停稳锚点漂移证据。160646 的 `0960b07` 只针对宿主收缩、旧缓存和锚点链路；查询时 CI 仍在运行，未获得真机通过证据。
3. 历史不是“都没用”：应保护 `a091b0c` 的 iOS15 禁用文字 alpha 渐显、旧 storage 替换前取消 fade、属性前缀完整比较、稳定宿主身份与一致全宽；保护 v64 的 compressed/zero-height 输入防自播种、160643 活跃助手身份、160644 已提交内容刷新链。不能为修卡片把这些整体回滚。
4. **反复叠加的高度真相最可疑**：TextKit floor/限高、宿主 high-water、cell cache/seed、layout precalc/memo、V31 反向锁、V64-CONVERGE ceiling、deferred heights 和 offset 恢复并存。日志已证明旧高覆盖较小正测量；但 raw 小不等于必然正确，仍需设备同身份闭环验证。
5. main 的 V71 模型选择上限与 V72 输入框闪屏补丁，不在修复分支祖先链。**不能把 main 的成功或补丁名自动算作当前包已经采用或通过。** 当前输入框本身有 setter 同值保护，须按实际代码而不是版本口号判断。

## 2. 检索范围、数量与限制

- 原工作树 `/var/minis/workspace/OpenMinis-push`，分支 `ios15-v64-repair`；开始/结束 HEAD 均以 `0960b075448a8879d37bdc16c9d53cd312624af0` 为审计基点。生产代码未修改，无 checkout/reset/push、CI dispatch 或手机操作。仅新增本报告。
- 原工作树起初为 shallow，仅见 4 个提交；只读 unshallow fetch 遇到 `shallow file has changed since we read it` 并发错误。因此另建**无工作树的 bare 历史镜像** `/var/minis/workspace/OpenMinis-history-audit.git`，不以浅历史假装完整历史。
- GitHub 分支 API 返回 **3 个分支、0 个 tag**：`main=ce7a229`、`ios15-clean=495ff38`、`ios15-v64-repair=0960b07`。完整镜像全部 refs 共 **413 个唯一可达提交**；main 共 **380 个**；`f017c76..ios15-v64-repair` 为 **13 个**；`f017c76..main` 为 **61 个**。后两项不是互斥集合，不能相加当总数。
- 全量索引了 413 个提交的可达历史；重点逐项核对修复分支 13 个提交的说明/改动文件统计，抽查核心生产 diff；向前检索 main 的 v31、v38、v42、v47～64、v65～80、搜索/压缩/闪屏等相关记录，实读 v64、V31、V71/V72、160641～646 的关键差异。**没有逐行审完全部 413 个提交、所有第三方依赖或每一版生成结果。** `ios15-clean` 仅纳入可达历史及分支索引，未独立验收其全部差异。
- GitHub Actions API 分 3 页获取 **268/268 次仍可见运行**，创建时间范围 `2026-09-28T11:29:03Z`～`2026-10-15T13:18:29Z`；状态快照 **131 success、125 failure、11 cancelled、1 in_progress**。其中含上游监听等非构建任务，**不能把 131 次当作 131 次修复成功**。重点额外读取最近 11 次 repair workflow 的 job/step 状态；未下载全部历史日志、全部 artifacts 或逐包核验 Mach-O。已删除/过期 Actions 不在 API 可见范围。
- 实读当前 docs 中版本说明、160644/645 真机记录、主会话滚动审查、thinking、自动压缩、container-cap、集成和交接记录；main 的 `CONTEXT.md` 及相关提交说明用于补历史。旧文档中的“本目录无 .git”“尚未安装”等是当时快照，后续证据优先。
- 授权仅引用 `$OPENMINIS`，未输出或写入令牌。API 入口：[branches](https://api.github.com/repos/Niubiprass/OpenMinis/branches?per_page=100)、[runs](https://api.github.com/repos/Niubiprass/OpenMinis/actions/runs?per_page=100)、[workflows](https://github.com/Niubiprass/OpenMinis/actions)。工作流状态会变化，下文为查询时证据。

## 3. 证据等级

- **代码**：提交 diff 能证明改了什么，不能证明症状消失。
- **CI**：同 SHA 的实际 build/package/测试步骤；Python 源码断言、抽取 Swift helper、完整 target build、UIKit XCTest、真机是不同层级。
- **实测**：用户最新明确反馈与已保存设备证据。设备版本号仍不自动等于源码/IPA 指纹已独立复核。
- **未知**：没找到该项验证证据，不写成成功，也不把未测一律写成失败。历史提交中的“根治/真凶/全绿”只当作者当时判断。

## 4. 按问题分类矩阵

| 问题 | 历史 SHA / 文件 / 实际改动 | CI 与代码证据 | 用户/设备结果、未知与防回退 |
|---|---|---|---|
| 卡字、文字消失、输出闪屏 | `a091b0c`：`SelectableMarkdownView.swift`、`TextFadeAnimator.swift`，iOS15 不播 alpha 渐显；替换 storage/复用/销毁/失活先取消旧 fade，清 deferred replay；属性比较遍历新旧 run 边界并集。`iOS15Compat.swift` 同完整 item/block 身份复用宿主，一致全宽、实宽变化重设。 | 首次 `a091b0c` CI 失败，不等于逻辑无效；后续修复构建/打包后 `68728ea` 同链成功。后续 160642～645 CI 成功。 | 用户最新称这些现象现在不再出现：**当前组合有正向反馈，单 patch 贡献不可分离**。必须保护 alpha/fade 生命周期、属性差异与身份宽度，不能整体退回最新 main 或原始 v64。 |
| 输入框打字闪屏（不同于输出 fade） | main `c637768` V72：`scripts/ios15_fallback.py` 的 `fix_chat_input_bar`，intrinsic 查询中仅在 `isScrollEnabled` 真改变时写 setter，避免重入。 | 该 SHA **不在当前修复分支祖先链**，不能称当前包继承 V72。现有 `ChatInputBar.swift` 的 `layoutSubviews` 及其他更新处已有同值保护。 | 用户现称打字闪屏消失，但没有 V72/current 包独立 A/B；保护现有输入框同值保护，不为输出问题搬整套生成器。IME marked text、中英多行、超过 maxHeight 仍应专项回归。 |
| 长文截断、末段消失 | v38 `b61ce53` 引入容器探测高度规则，最终 `NSTextContainerSetSizeGuard.m` 将 `>=3000` 压到 `2000`；`c4dfa8d` 160644 增加 committed text/thinking 高度信号仍治不了上游限高。`a58d63d` 删除 V38C 规则，保留 100000 有限上界与风暴防护，新增 `LongTextContainerLayoutTests.swift`。 | `a58d63d` 完整 App build 成功但 package 失败；`5da5b4a` 仅修 checksum 文件名后整条成功。新增 3 项 XCTest **不在 workflow 实际执行**；Python 注册/源码检查不是 UIKit 通过。 | 160643 持久化 4767 字/40 段，UI 只到15；160644 持久化2804字/40段，UI只到22，重进不恢复，TextKit约2007pt/宿主2058pt。**旧包明确失败**。160645/646 未找到独立长文通过证据；纯文本最新改善不能代替 >3000pt 验收。禁止重新生成时恢复 `>=3000→2000`。 |
| 卡片/工具/thinking 错位、重叠、半截、留白 | v31 `9014f73` 最大高度反向锁；v61 `bf5a253` MONO 高度锁；v64 `650adb0`/生成源码 `f017c76` 防 self-sizing 自播种，但叠加 V64-CONVERGE；`a8ab70b` 把 V31 改为同稳定 Markdown 的实际 DOWN→UP bounce，不再首个收缩即锁；`788ba15` 停稳修 TextKit surplus；`a58d63d` deferred heights 按快照 item 重映射、内容新测量取消旧 parked 高度。 | 160641～645 多次构建成功，仍不是几何正确证据。`0960b07` 160646 再统一 fitting 入口、稳定收缩确认、清缓存/seed/precalc/memo、去 super-fit ceiling、按 item 屏幕锚点补偿。查询时 CI 在运行。 | 160641 历史记录491→267被锁造成224pt空白；160644 measured202被锁314；160645 同item326被锁505、455被锁679、679被锁1015，停稳screenΔ=-31.3/-13/-26。**用户明确160645失败、当前主要仍为框异常**。raw可能稳定但错误，不能只以“无 hold 日志”判通过。 |
| thinking 等待、内容不见 | `c4dfa8d` 订阅 thinking 内容；`a58d63d` `ChatModels.swift` 空 text 块仍保留等待，`AssistantBlockView.swift` 有界文本固有尺寸+overlay、block.id 隔离、尾换行不裁空；V3 合并 content/expanded 订阅，不重放旧 snapshot，刷新 footer。 | `5da5b4a` CI成功；helper/source 不等于真实 provider reasoning 或 UIKit运行。 | 160644 无reasoning模型仅见等待不能算思考内容通过；另一真实reasoning会话1593/243字已有40↔340、40→262高度与正文位移对应，472字历史块也展开并保持。**局部历史路径有效不等于全部框通过**；不要删掉已有展开通知/统一失效路径，也不要把内滚动全文AX rect当视觉重叠。 |
| 自动压缩 | `a091b0c` 全局 opt-in 软预算256000、85%=217600，原生低窗口优先，raw-history边界/未完tool pair保护；`a58d63d` `ContextPolicy`/`AIChatViewModel+Compaction`/`AIChatViewModel`/`ChatStore` 修中文估算、滚动摘要、失败取消闸门、多队列保留、marker取消检查提交点。 | 当前 `5da5b4a` 构建成功；Foundation预算/preferences提取测试有覆盖，但不覆盖真实provider、SQLite、取消和队列并发。 | 160644未包含本轮压缩补丁；**未获得160645/646压缩真机验收证据**。不能写成功或失败已定；保留 min(nativeWindow,budget)、原始历史、tool配对和失败不自动消费队列，禁止为了通CI删除这些保护。 |
| 搜索崩溃 | `a58d63d` `ChatStore.keywordSnippet`：不拿 lowercased 副本的 String.Index 索引原文；在原文 caseInsensitive 搜索并对齐 Character 边界，过滤空关键词和非正maxLength。另 main `0923fe0` V71 是**模型选择列表**截断至150，属另一问题。 | 搜索 snippet补丁随160645成功构建；未发现专门Unicode Swift运行/设备搜索验收。V71不在当前修复分支祖先链。 | 160644未包含搜索补丁；没有160645搜索通过证据。需区分聊天搜索与模型搜索，不能用picker构建成功抵消snippet崩溃。验 `İ`、组合音标、emoji/ZWJ、中文、多关键词与空输入，搜索结果进入后还要验卡片布局。 |

## 5. 原版160v64至当前：版本/CI/设备对照

基线：`f017c76cae19053a86236112544c4185c9e94783`，原 port 脚本 `650adb0`，原 run [37265888866](https://github.com/Niubiprass/OpenMinis/actions/runs/37265888866)，run_number=160。`docs/ios15-v64-repair.md` 记载原装机与原IPA的 Mach-O UUID及text段匹配；本审计未重新计算。产品 build 160641～646、workflow run_number 与run ID是三套编号。

| SHA/版本 | 改动与CI证据 | 实际结论 |
|---|---|---|
| `a091b0c` 160641起步 | streaming/host/fade/prefix/压缩；[38637659020](https://github.com/Niubiprass/OpenMinis/actions/runs/38637659020) build失败。 | 不是可验收产物。 |
| `bbee41e` | 部署目标覆盖修复；[38639589426](https://github.com/Niubiprass/OpenMinis/actions/runs/38639589426) build仍失败。 | 不能因提交标题说“fix”记为通过。 |
| `806de79` | localized format修复；[38642830857](https://github.com/Niubiprass/OpenMinis/actions/runs/38642830857) build成功、package失败。 | App能编译与能打包必须分开。 |
| `51eb0f4`、`68728ea` | 记录原VAD framework minOS15.6例外、收窄validator，补workflow触发；[38648163380](https://github.com/Niubiprass/OpenMinis/actions/runs/38648163380) success。 | 是包校验边界调整，不证明VAD在iOS15.5可用。 |
| `a8ab70b` / 160641 | V31真bounce限定；[38656540004](https://github.com/Niubiprass/OpenMinis/actions/runs/38656540004) success。 | 有历史锁高反证及代码修正，无整体验收通过结论。 |
| `788ba15` / 160642 | TextKit surplus停稳回修；[38664156654](https://github.com/Niubiprass/OpenMinis/actions/runs/38664156654) success。 | 交接记录仍未验收；记有该版后台异常，不能混记到160643。 |
| `26e5bbc` / 160643 | 排队用户前活跃助手继续live、后续行重排；[38705128486](https://github.com/Niubiprass/OpenMinis/actions/runs/38705128486) success。 | 40段存储完整但UI只到15；**失败**。 |
| `c4dfa8d` / 160644；`3e27786`文档 | committed文本/thinking批次刷新；[38714599848](https://github.com/Niubiprass/OpenMinis/actions/runs/38714599848) success。 | UI只到22，重进不恢复；**失败**。局部thinking/滑动无新crash不等于整体通过。 |
| `a58d63d` / 160645代码 | 快滑、长文限高、thinking、压缩、搜索；[38728149722](https://github.com/Niubiprass/OpenMinis/actions/runs/38728149722) build成功、package失败。 | 是校验文件名故障，不应误报Swift编译失败。 |
| `5da5b4a` / 160645产物 | 只改workflow checksum文件名；[38731133930](https://github.com/Niubiprass/OpenMinis/actions/runs/38731133930) success。 | `workspace/test-160645/app-info.json`核对version160645；用户及fast-log仍异常：**真机失败**。 |
| `0960b07` / 160646候选 | 稳定宿主回缩+缓存失效+锚点；[38741580820](https://github.com/Niubiprass/OpenMinis/actions/runs/38741580820) 查询时in_progress，native完成、App build运行。 | **没有CI完成/真机通过证据，不得假报成功。** 后续CI完成也只改变CI列。 |

## 6. main 历史说明了什么，不说明什么

- v31 `9014f73` 用最大高锁防欠测；v42 `b131517` 反而已写明“max会把短文本复用造出大片空白”，引入带长度/宽/hash键的需求高度缓存。历史自身已经反复显示：**最大高度只可作有释放条件的暂态保护，不可永久作内容真相。**
- v47 `3603c6e`、v48 `4b64352`、v50 `b48ba6a`、v57 `ee002bd`/`2e8166e`、v58 `94e248a`、v59 `582455c`、v60 `d2afc09` 反复调整测宽/渲染宽/容器宽及纠偏顺序；提交名“根治”之后仍有后续修复。因此要保护当前全宽与内容自有padding契约，不能机械按“历史最高版”覆盖。
- v56.7 `ada10ea` 修lastLines全量切分与Timer泄漏；v56.2 `2d6aad6` 记录v56-B装机主线程卡死8.1s、CrashLoop并回滚。这里是历史文档/提交记载，未重新读取原crash文件，不能把该记录当所有卡顿均同一根因。
- v61 `bf5a253` MONO、v62 `1264324` surplus、v63 `60b45e6` invalidate/高度上报、v64 `650adb0` de-seed/converge连续演进。v64提交说明给出 `H(n+1)=H(n)+170`、1.58秒内六拍证据，故**应保留输入断反馈与内容尺寸变化通知，不应把旧ceiling也当不可碰的正确性公理**。
- v65～80是在 main 后续路径：0尺寸风暴、守卫递归、模型选择/watchdog、入口节流等。`c637768` V72 和 `0923fe0` V71经merge-base确认不是当前修复分支祖先；`9014f73`与`ada10ea`是祖先。必须区分生成器脚本变化和生成后的Swift/ObjC生产源码。
- main `972bfb0` 对 reverse_v53 的V79形态兼容修复后 [37718168130](https://github.com/Niubiprass/OpenMinis/actions/runs/37718168130) success，而 `913dc3d` [37716701845](https://github.com/Niubiprass/OpenMinis/actions/runs/37716701845) failure；这是门禁/构建证据，**不能推导V79所有设备症状通过，更不能覆盖160645失败**。

## 7. 防回退清单与下一步定点验证

### 必须保留的契约

1. 文字颜色/alpha立即可见；旧fade不能写新storage；属性比较不能只采样run起点；后台、复用、拆卸清旧任务。
2. 同完整item身份才复用宿主；换身份/宽度清测量状态；host全宽与内容padding不双减。
3. 不把上一轮cell高当新测量seed；保留compressed拟合、有效几何防御和真实内容高度上报；不得恢复通用“无TextKit就不许长高”ceiling。
4. 既有活跃助手、最终批次、thinking内容/展开、footer刷新统一按ID失效；deferred按快照身份迁移，新测量取消旧值。
5. 不恢复V38C 3000→2000；保留100000有限界及风暴防御；generator再跑后也必须验产物。不要为“修半截”删除所有ObjC守卫。
6. thinking长内容300pt是**内滚动viewport上限**，不是全文高度；保留真实内容、手动展开与冻结阅读，不伪造reasoning。
7. 保留压缩原始历史、native窗口上限、tool配对及失败队列保护；搜索不得跨字符串使用Unicode索引。

### 候选160646的优先验收（本审计不执行设备操作）

**P0 框布局闭环**：先核对实际安装build、候选SHA/IPA指纹。在同主会话、同批tool/thinking/操作卡做冷进入、展开→收起、运行中→完成、离屏复用返回、快滑后停稳。参考既有20次85ms/440pt压力序列，同时记录稳定item UUID、raw/accepted host、cell/cache/precalc/memo、row frame及screenY。重点复核326↔505、455↔679、679↔1015类型，不复用index当身份。

通过条件：合法稳定收缩会释放，新的增长不会被旧super ceiling拦掉；外行不相交、不掉行、不截半、无持续旧高空白；停稳锚点按item保持。**仅raw变小、无hold、日志无crash或截图AX内层相交，均不足单独定通过/失败。** 已知异步附件后续变化、锚点本体内部变高、删除与clamp另列边界。

**P0 纯文本保护对照**：同候选测试中英逐token、同/跨行、stop/resume、最终token后idle、前后台、会话切换，确认用户已消失的三类症状不回归。再单独验40段+END+排队消息、>3000pt、完成/重进仍全文；先在Apple环境真正运行长文XCTest，不能用源码PASS替代。

**P1 thinking**：分别用不返回reasoning和真实reasoning模型；验空text start等待、首真实字符撤等待、短/长/尾换行、2K/8K边界、展开收起后邻行位置、复用不串块；读AX时区分内scroll内容与viewport。

**P1 独立功能**：搜索Unicode/空关键词/结果进入；压缩85%边界、低native window、中文usage校准、tool未完成、失败/取消多队列保留、Resume、marker提交。分别记录结果，不搭便车记“框修好了所以都好了”。

**发布规则**：一行对应一个问题、一个安装版本和一份证据，列代码/CI/设备三栏；160646若CI绿仍标“待真机”，若只修框则不能抹掉搜索/压缩未知。禁止无新证据写“全部根治”。

## 8. 主要出处与可追溯链接

- [修复分支提交](https://github.com/Niubiprass/OpenMinis/commits/ios15-v64-repair)、[main提交](https://github.com/Niubiprass/OpenMinis/commits/main)、[原v64源码](https://github.com/Niubiprass/OpenMinis/commit/f017c76cae19053a86236112544c4185c9e94783)。表内短SHA均为该仓库唯一前缀，可用 `https://github.com/Niubiprass/OpenMinis/commit/<SHA>` 定位。
- [160641核心补丁](https://github.com/Niubiprass/OpenMinis/commit/a091b0c)、[V31修正](https://github.com/Niubiprass/OpenMinis/commit/a8ab70b)、[160645生产补丁](https://github.com/Niubiprass/OpenMinis/commit/a58d63d)、[160646候选](https://github.com/Niubiprass/OpenMinis/commit/0960b07)。
- 当前commit固定文档基址：`https://github.com/Niubiprass/OpenMinis/blob/0960b075448a8879d37bdc16c9d53cd312624af0/docs/`；重点 `ios15-v64-repair.md`、`OPENMINIS-IOS15-HANDOFF.md`、`DEVICE-160644-RESULTS.md`、`DEVICE-160645-REPAIR.md`、`MAIN-SESSION-SCROLL-AUDIT.md`、`ios15-160644-container-cap.md`、`THINKING-VISIBILITY-CURRENT-REPAIR.md`、`auto-compaction-current-status.md`、`CURRENT-REPAIR-INTEGRATION.md`。
- 本地原始设备资料：`workspace/test-160643/`、`workspace/test-160644/`、`workspace/test-160645/app-info.json`及`fast-log.json`。这些不是本次新采集，且包含用户会话内容，不上传公开仓库。审计只复核了160645版本元数据，设备日志数值主要引用已提交诊断文档；未伪称重新进行了截图/OCR或真机操作。
