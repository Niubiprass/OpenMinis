# OpenMinis iOS 15 移植 —— 工作上下文

> 生成时间：2026-10-05
> 仓库：`Niubiprass/OpenMinis`（**private**）· 本地：`/workspace/OpenMinis`
> 上游锚点：`OpenMinis/OpenMinis` tag `1.14`（commit `3fe0f6c3`）

---

## 1. 仓库现状

| 项 | 值 |
|---|---|
| 可见性 | private（未认证访问返回 404，属正常） |
| 默认分支 | `main` |
| 分支 | `main`（311 commits）、`ios15-clean`（领先 273，与 main 已 diverged，差异 300 文件） |
| 最后推送 | 2026-10-05 00:09 |
| 语言 / 许可 | Swift / GPL-3.0 |
| 体积 | 51.5 MB，2148 文件 |
| Releases / Tags | **0 / 0** |
| CI 运行总数 | 194（最近 20 次：成功 14 / 失败 6） |
| 我的权限 | admin |

**注意**：`src/ios/` 在仓库里是**已注入的产物树**，不是干净上游。全链验证必须另备干净上游。

---

## 2. 改造架构：三层 + 五道防线

### 2.1 三个被注入的文件

| 文件 | 承载版本 | 职责 |
|---|---|---|
| `src/ios/iOS15Compat.swift` | V61-MONO / V61-REUSE | hosting 层：就地更新 + 高度单调锁 |
| `src/ios/Agent/MessageList/MessageListInfrastructure.swift` | V53 欠账体系 + V62 镜像 | cell 层：高度欠账/盈余检测与记忆 |
| `src/ios/Views/Chat/SelectableMarkdownView.swift` | V52 / V53-FIRST / V62 settle | 渲染层：settle 时纠正与债务上报 |

改造链条（当前 HEAD = v62）：
```
iOS15Compat (V61 就地更新+单调锁)
      ↓
Cell (V53 欠账两拍 / V62 盈余两拍 —— 互斥)
      ↓
settle (V53-FIRST + V62 _v62oversized 触发 invalidate)
```

### 2.2 注入脚本

- `scripts/ios15_fallback.py` — **822 KB / 13659 行**，72 个 `fix_*` / `verify_*` 函数，是改造的核心
- `scripts/ios15_port_v2.py`（91 KB）、`ios15_runtime_fixes.py`、`autofix.py` 等辅助脚本
- `scripts/ios15_verify/` — 58 个校验脚本

---

## 3. 判据体系（本项目最资产）

### 3.1 核心原则（见 `docs/verify-discipline.md` 14 条）

1. 每加一版，**必须重跑全部历史判据**（`regress_all_v.py`）—— 只跑本版看不见"本版弄坏了历史保护"
2. **先计数锁死集合，再用 `find()` 取位置** —— 顺序反了会切错段
3. 白名单要**按接收者类型**建表，沿链**逐跳**推进，不能只验名字
4. **只允许使用编译器已验证存在的 API** —— 写注释不能代替查证
5. 判据输出文案**本身也是判据**（它会塑造后来人的修法）
6. 判据必须能被证伪；**退出码 3 = SKIP，SKIP 绝不能算通过**
7. 环境路径不许硬编码
8. workflow 的 `paths` 必须包含判据目录
9. 同一逻辑只能有一处实现
10. 段右边界不许硬编码版本号（用正则现场扫）
11. 判据与产物冲突时，先问"这条红线当初为了防什么"
12. 反向测试锚点失效**必须自己报错**（`str.replace` 静默失败是陷阱）
13. 查数据流要连"声明"一起查
14. 提交用 git data API **单次提交**（多次 PUT 会触发多个 20 分钟 CI run）

### 3.2 回归测试

```bash
python3 scripts/ios15_verify/regress_all_v.py <产物根目录>
```
退出码：0=通过 / 1=失败 / **3=无法检查(SKIP)**

**当前状态（本地，未设干净上游）**：21 通过 / 0 失败 / 5 跳过
跳过的 5 项（v565~v568 反向 + 产物级幂等）需设 `OPENMINIS_UPSTREAM_IOS` 才能跑。

---

## 4. 版本演进脉络（症状 → 根因）

| 版本 | 症状 | 根因 |
|---|---|---|
| v53 | 新会话第一段卡字 | `deferredCorrectionPending` flag 被提前清，欠账永不偿还 |
| v56-v57 | 每行右端被竖直切断 / 只剩上半 | KVO 同值抑制把欠账帧永久跳过 |
| v58 | 纠偏后位置对了但不重排 | 缺"写完要排" |
| v59 | 宽跟随方案断裂 | 关闭主视图容器宽跟随 |
| v60 | v59 方案断源 | 改用 zhaoxiufei 3ccdff6 已验证方案 |
| v61 | 整屏跳动 / 流式跳出 | `_HostingContentCellView.apply()` 每次 tick 全删重建，高度 333↔490 漂移 |
| v62 | 工具卡片间 ~250pt 空白终态留存 | v53 欠账体系只有"太矮"半边，`debt <= 1` 把 -290 吞掉，盈余零动作 |
| **v63（待做）** | 工具卡片空白 + 文字突现 + 整屏狂跳 | **v62 未生效**：欠账/盈余通道运行时从未通电（见下） |

**核心洞察**：v53 是**单极欠账**体系（只治裁字），v62 补上了**盈余**半边（治空白）。二者互斥计数。

---

## 4.5 ★ v63 诊断结论（2026-10-05 装机实证）

**用户症状**：工具卡片间空白一大片、文字一下跳出一大段（非流动输出）、整屏疯狂闪跳、不连贯。

**关键反常识发现**：v62 的修复代码**根本没进入运行路径**。
日志中 `V53-DEBT` / `V62-SURPLUS` 出现 **0 次**。

### 三条铁证

| 铁证 | 值 | 含义 |
|---|---|---|
| `live=` 唯一取值 | `live=0` | 真实测量**全程 0 次**，三条短路从未放行 |
| `debt=` 唯一取值 | `debt=0.0` | 欠账恒 0，盈余镜像无数据可吃 |
| 帧差（80.7s / 4200 帧） | 30% 帧跳变 >15%，静止仅 16% | 整块内容重排 |

### 根因：循环依赖

v53/v62 的"两拍放行"设计成：连续观测两拍才放行真实测量。但：

```
要放行测量 → 需要 debt 熟 → debt 熟需要 settle → settle 要先放行测量
```

`debt` 只在 `consumeDeferredCorrectionIfNeeded()`（settle 时刻）上报，
而 settle 的 guard 又依赖欠账是否成立 ⇒ `v53DebtSeenCount` 永远停在 1。

### 高度跳变实证（idx=19，1.5 秒内 6 次 invalidate）

```
pref=798  cached=true  est=200
pref=903  cached=true  est=798
pref=1057 cached=true  est=903
pref=1205 cached=true  est=1057
pref=1336 cached=true  est=1205
pref=1518 cached=true  est=1409
```
6 次全部 `cached=true` ⇒ 每次返回**上一次的旧高度**，`est` 一路追着 `pref` 跑，
真实需求在涨但测量管道被锁死在旧值 ⇒ 文字"一下跳出一大段"。

高度取值分布：`46.7 / 36 / 337 / 33 / 384 / 1557 / 1544 / 1160` —— 跨数量级跳变。

### 为什么 v62 判据没抓到

`reverse_v62` 的 7 条 sabotage 全在**静态文本层**做文章（摘分支/改阈值/删守卫）。
本次故障是**运行时数据流断了** —— `debt` 恒 0 使 `debt < -40` 分支在任何输入下都不进。
形状判据对此完全无感。

> ⇒ 需要一层**运行时闭环判据**：模拟输入序列，断言
> `debt 上报 → 计数成熟 → 短路放行` 这条链真的能走通（`live > 0`）。
> 这是 verify-discipline 第 4 条「结构判据查不出运行时故障」的同类。

### v63 修法方向

1. **打破循环依赖**：settle 入口 guard 不再依赖 debt 熟，改为「cell 高 vs 真实测量差 > 阈值」直接放行
2. **短路让位真实测量**：dedup 命中时若内容已变（generation 递增）强制重测
3. **补运行时闭环判据**：断言 `live` 计数会 > 0（当前恒 0 即红）
4. **v61 REUSE 缺 config 判等**：快速路径只判 `host != nil`，跨消息类型会用错 host

---

## 4.6 ★★ v63 落地（已完成，全链 28/0/0）

### 外部研究：为什么 v31~v62 三十余版都没治好

四个**独立来源**交叉验证，结论一致 —— iOS 15 上 `UIHostingController` **没有** `sizingOptions`
（iOS 16 才有），SwiftUI 内容尺寸变化的**唯一**通道是
`intrinsicContentSize` + `invalidateIntrinsicContentSize()`：

| 来源 | 结论 |
|---|---|
| Mozilla Firefox iOS `HostingTableViewCell.host()` | 每次 `rootView` 赋值后都跟 `invalidateIntrinsicContentSize()` |
| StackOverflow 77027194（36k 赞） | 明确说 `setNeedsLayout` / `layoutIfNeeded` **都无效** |
| vbat.dev（UIHostingController 调试） | 同结论 |
| Apple FB9641883 社区解法 | iOS 15 给 hosting view 加多余 padding，iOS 16 才修 |

**关键交叉发现**：v60 采用 zhaoxiufei 的已验证方案时，把 `intrinsicContentSize` 的**高度**
也改成了 `noIntrinsicMetric`（原意只是治宽度污染）。那个理由对**宽度**成立，
但把高度一并关掉是**误伤** —— 它正是 iOS 15 唯一的更新信号源。

> ⇒ 这解释了为什么三十余版都没治好：所有人默认 `intrinsicContentSize` 是
> 「宽度污染源」把它当病灶切了，而它其实是**信号源**。

### 五处改动（`scripts/ios15_fallback.py` +368 行）

| 标记 | 文件 | 作用 |
|---|---|---|
| `V63-UPDATE` | iOS15Compat.swift | rootView 换完后显式 `invalidateIntrinsicContentSize()` |
| `V63-CFG` | iOS15Compat.swift | apply 世代号 + host 身份戳，fast path 加 `_v63ConfigGen == _ios15ApplyGen` 判等 |
| `V63-PROBE` | iOS15Compat.swift | fast/rebuild 双路计数，每 0.5s 打印一行 |
| `V63-INTSIZE` | SelectableMarkdownView.swift | `intrinsicContentSize` 恢复**高度**上报（宽仍 `noIntrinsicMetric`） |
| `V63-UNCYCLE` | SelectableMarkdownView.swift | guard 加 `_v63drift`（实测差 > 8pt 直接放行，不等计数成熟） |

### 判据链：第一次把「判据自己」列为承重墙

| 文件 | 作用 |
|---|---|
| `verify_intrinsic_gate_v63` | 六层：探针 / 世代号 / fast 判等 / invalidate / intrinsic 高度 / 声明早于使用 |
| `verify_uncouple_v63` | 四层：drift 定义 / guard 接线 / 阈值合理 / 不重绑 debt |
| `ci_assert_v63.py` | CI 入口 = core + **probe（装机可观测性）** + sab |
| `reverse_v63.py` | 14 条 sabotage，**judge 直调上面两条真实判据**（纪律第 8 条：不另写副本） |
| `verify_v63.sh` | 一条命令跑完三阶段 + 落点核对 + 判据链 + 全回归 + 幂等 |

> ★ 为什么 `reverse_v63` 的 judge 要直调真实判据：
> 若另写一份形状检查副本，后人改了判据忘了改副本，就会「判据红了而反向测试还绿」。
> 直调之后，**谁把判据改松让 CI 过，reverse_v63 立刻红**。

### 本轮踩的三个坑（都已写进注释）

1. **判据锚点不能选注释**：`verify_intrinsic_gate_v63` 原以 `[V63-UPDATE]` 注释行起算切片窗口，
   而身份判等写在**上一行**的 `if let` 条件里 → 判据在自己写的窗口外找东西，报假红。
   改为以 `if let existing = host`（代码结构，产物里 count=1）为锚，并先断言计数。
2. **旧版反向测试被新版锚点顶掉**：v63 给 guard 加了第四条腿，`reverse_v53` 的 S5 锚点落空。
   纪律第 10 条要求锚点失效必须自己报错 —— 它确实报红了。修锚点时同时追问
   「新增的腿有没有被测到」，于是补了 `reverse_v63` 的 S9~S12。
3. **Python 源码里的 Swift 插值转义**：`'\('` 在 Python 里不是转义序列（解析为 `\` + `(`），
   但写 `'\\_'` 就变成 `\` + `_` → 静默不命中。此坑连踩三轮，已在
   `reverse_v63.py` 加模块级 `assert` 自检。

### 装机验证清单（判据全绿 ≠ 病治好）

```
[V63-PROBE] fast=N rebuild=M    ← N>0 才说明 REUSE 快速路径在跑
live=N                          ← N>0 才说明真实测量放行了（v62 装机时恒为 0）
```

- `fast=0` ⇒ 快速路径没被执行，问题在别处
- `fast>0` 但 `live` 仍恒 0 ⇒ invalidate 通道修好了但测量仍被挡，需带日志再定位

---

## 4.7 ★★★ 几何基准 —— 62 版判据第一次有了绝对标尺

### 为什么这是本项目最缺的东西

v1~v62 共 62 版判据，**全部是相对的**：「比 v61 好」「标记在位」「阈值合理」。
从来没有一份回答过「正常的工具卡片**应该**多高」。

后果有两条，都已实证：

1. **「相对更好」可以一直成立而病一直没好** —— v53→v62 每版都更「好」，
   而 v62 装机日志里 `V53-DEBT`/`V62-SURPLUS` 出现 **0 次**、`live` 恒为 0。
2. **「文字非流式」一直无法量化** —— 没有基准，「一下跳出一大段」
   无法翻译成任何可断言的量，于是每版都只能定性描述。

### 基准（用户提供的真机正常画面：同源移植，iPhone @3x 1170×2532）

| 指标 | 实测值 |
|---|---|
| 同形态工具卡片高度（11 张） | 36.3 ~ 37.0 pt，**极差 0.7 pt**，标准差 0.15 |
| 卡片垂直间距 | 7 ~ 10 pt，中位 9 pt |
| 结论 | 正常 = 卡片**等高** + 间距**恒定** = 高度由内容**一次算定** |

对照 v62 装机日志的 `pref` 序列：

| | v62（病） | 正常 |
|---|---|---|
| 序列 | 798→903→1057→1205→1336→1518 | 36.7×11 |
| 跨度 | 720 pt（1.9 倍） | 0.7 pt |
| 单次跳变 | 105~182 pt | ≤0.3 pt |

⇒ **「狂跳」的量化定义** = 平均每 250 ms 位移 120 pt = 屏高（844 pt）的 14.2%
⇒ **「一下跳出一大段」的量化定义** = 单次增量 ≥105 pt，而正常卡片全文高仅 36.7 pt
   ⇒ **一次跳变 ≈ 3 张卡片的位移**

### ⚠ 最关键的一处设计：主判据是「定型后极差」，不是「全段跨度」

同一份 v62 日志里：

```
idx=17  [333, 70, 384, 384]                 全段极差 314pt  尾部极差 0pt   ← 正常（一次定型）
idx=19  [798, 903, 1057, 1205, 1336, 1518] 全段极差 843pt  尾部极差 436pt  ← 病（持续追涨）
```

- `idx=17` 首帧偏 51 pt（内容刚到还没测量），第 3 帧起恒定 384 ⇒ **这是正确行为**，
  甚至说明 settle 机制在那条消息上工作正常
- `idx=19` 尾部仍在单调递增 ⇒ 这才是病

**首帧偏移是测量的固有代价，不是病。** 按全段跨度一刀切会把「一次定型」也判红，
装机后满屏红 ⇒ 没人再看第二眼 ⇒ 判据自动失效。
v53 被连续两版忽略，正是因为它的信号一直是「零」或「常红」，两种都让人不再看它。

> ⇒ **判据宁可漏报，不可误报。** 这是本项目从 v53 的失败里换来的。

### 落地

| 文件 | 作用 |
|---|---|
| `scripts/ios15_verify/verify_v63_geometry.py` | 几何判据（含常量自证 + 正反锚点自检） |
| `scripts/ios15_verify/baseline/normal-ref.jpg` | 基准图，是判据的**输入**（已加进 workflow `paths`） |
| `regress_all_v.py` | 注册为 MANDATORY 项 |
| `port-and-build.yml` | 断言67：判据自证 + 基准图在位 |

三条用法：

```bash
python3 verify_v63_geometry.py                    # 常量自证（CI 跑这个）
python3 verify_v63_geometry.py --ref              # 量基准图 itself
python3 verify_v63_geometry.py --log <装机日志>   # 按 idx 分组判定真机几何
```

**★ 必须按 idx 分组判，不能把全日志混成一条** —— 不分组时 77 个样本算出跨度
1605 pt（名义高的 43.7 倍），看着像「一条消息在疯长」；分组后真相是
**多条消息各自在疯长**。混算会把「组内跳变」误读成「组间差异」，
真出现单条消息小幅波动时反而被淹掉。

在 v62 日志上的实测结果：**10 个 idx 中 8 个病态**，仅 idx=8、idx=17
（尾部极差 0）判为定型后稳定。

---

## 5. 已知风险

1. **令牌泄露**（已处理：仅只读查询，未落盘；但对话中明文出现，**用户需自行撤销**）
2. **v63 未经真机验证**：判据全绿 + 14 条 sabotage 全拦，但 v60 的元教训是
   「v31~v59 从未被真机验证」⇒ **本版必须装机看日志**（清单见 §4.6 末）
3. **`ios15-clean` 与 main 分叉**：273 commits / 300 文件差异，长期会失控
4. **零 Release / 零 Tag**：CI 产物无法追溯
5. **CI 失败率 30%**，无稳定发布门禁
6. **`port-and-build.yml` 205 KB / 2472 行**：移植逻辑内联在 YAML，维护隐患
7. **9 个判据依赖 `HERE/..` 兜底**找 `ios15_fallback.py`
   （`ci_assert_v50~v53/v565/v58` + `reverse_v47/v50/v51`）。
   v63 链已修掉同类问题（`verify_v63.sh` 把仓库版 fallback 复制进产物树，
   否则 v53 的 sab 层会静默换被测对象），但这 9 个历史判据的隐患仍在。
8. **无 topics**

---

## 6. 提交纪律

- 一次改动 = **一个 commit**（git data API 单次提交）
- 提交前本地自检：
  ```bash
  # 1) 从干净上游跑完整全链注入（不是从上一版产物叠加）
  cd /tmp && rm -rf vXXfull && cp -a up_1_14 vXXfull
  python3 scripts/ios15_fallback.py /tmp/vXXfull/src/ios
  # 2) 跑全版本回归（目标 0 跳过）
  python3 scripts/ios15_verify/regress_all_v.py /tmp/vXXfull
  ```
- 回归输出 `0 跳过` 才是真通过

---

## 7. 干净上游位置

`/tmp/up_1_14/src/ios`（从 tag 1.14 经 API 下载）
设置：`export OPENMINIS_UPSTREAM_IOS=/tmp/up_1_14/src/ios`
