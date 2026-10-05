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

## 4.8 ★★★ run#156 失败复盘 —— 「空测被当成通过」是判据体系最危险的缺陷

### 发生了什么

v63 推送后 CI **#156 失败**（前 12 步全绿，第三阶段注入成功）：

```
✗✗ 自检: 运行时补丁是否真的生效 (不通过则立即变红, 避免静默回归)   failure
  断言64: v61 整屏跳动修复必须就位
    ✅ BASE 基线                  基线通过
    ⚠ S1 摘 apply 快速路径          注入未生效(锚点缺失)，本条无效
    ✅ S2~S5 全拦
    v61 反向: 4 拦下, 1 漏过（共 5 条 sabotage）      ← 退出码 0，绿的
```

根因：v63 给 REUSE 快速路径的 `if let` 加了 config 身份判等，
`reverse_v61.py` 的 S1 锚点（旧形态裸串）落空。

### 真正可怕的不是锚点失效，是**失效被当成通过**

```python
if mutated == prod and not name.startswith('BASE'):
    print('  ⚠ ... 注入未生效(锚点缺失)，本条无效')
    passed += 1          # ★ 空测被计入「漏过」
    continue
...
return 0 if passed == 0 else 1
```

`passed` 的语义是「漏过」（判据没反应），结尾按 `passed == 0` 判成败。
于是 **「4 拦下 + 1 空测」= `passed==1`**，本该红，却因为前面 `caught + passed == 5`
看着「齐了」—— 实际输出 `4 拦下, 1 漏过` 后退出码是 0。

> **空测被当成了通过。** 判据链少一条守门，报表却全绿。
> 这比红危险得多：红会被人看见，全绿不会。

### 系统性排查：同类缺陷有 5 处

| 文件 | 状态 |
|---|---|
| `reverse_v53.py` | v63 已修（S5 锚点） |
| `reverse_v61.py` | **本轮修**（S1 锚点 + 空测计数） |
| `reverse_v58/v60/v62.py` | **本轮修**（空测计数；v62 另需适配新 guard 形态） |
| `reverse_v59.py` | **本轮退役**（见下） |

统一修法：空测独立计数 `voided`，`return 0 if (passed == 0 and voided == 0)`，
输出里显式列出「N 空测」。

### 三条元教训

1. **锚点不能锚死形态**。v63 加条件后，v61 的 S1 与 v62 的 S4 同时失效。
   修法不是改锚点字符串，而是**同时接受新旧两种形态**（`MD_GUARDS` 优先新形态）。
   锚死形态 = 给下一版埋同一个雷。
2. **修锚点时必须追问「新增的那条腿有没有被测到」**。改了 v61 的 S1 之后，
   要问 v63 加的 config 判等谁在测 —— 答案是 `reverse_v63.py` 的 S4，
   直调 `verify_intrinsic_gate_v63`。职责不丢。
3. **孤儿判据是假保护**。`reverse_v59.py` 自 v60 起就永久判红
   （它要求 `[V59-NOTRACK]` 存在，而 v60 明确要求它**必须为 0 处**），
   但它**从未被任何门禁调用**（workflow 0 次、regress_all_v 0 次），
   所以从 v60 至今没人发现。留着它会让维护者误以为 v59 受保护。
   已归档到 `scripts/ios15_verify/retired/reverse_v59.py.RETIRED` 并写明原因；
   **v59 的成果由 v60 判据接管保护**，退役的是这份**已失效的判据**，不是那个修复。

### 装机验证清单（判据全绿 ≠ 病治好）

```
[V63-PROBE] fast=N rebuild=M    ← N>0 才说明 REUSE 快速路径在跑
live=N                          ← N>0 才说明真实测量放行了（v62 装机时恒为 0）
```

---

## 4.9 ★★★★ run#157 失败复盘 —— 判据体系的**第二个盲区**：文本在位 ≠ 能编译

### 现象

run#156 的失败（v61 判据红）已修，全链本地 33/0/0、远端快照也 33/0/0 判据全绿，
结果 run#157 仍然失败 —— **但这次不是判据红，是编译红**：

```
iOS15Compat.swift:420:24: error: static stored properties not supported in generic types
iOS15Compat.swift:421:24: error: static stored properties not supported in generic types
iOS15Compat.swift:422:24: error: static stored properties not supported in generic types
（全文仅此 3 个错误 ⇒ xcodebuild exit 65）
```

### 根因

v63 探针的三个计数器被声明在**泛型类型**里：

```swift
private final class _HostingContentCellView<Content: View>: UIView, UIContentView {
    private static var _v63FastHit: UInt = 0      // ← 硬错误
    private static var _v63RebuildHit: UInt = 0   // ← 硬错误
    private static var _v63ProbeLast: CFTimeInterval = 0  // ← 硬错误
```

Swift **禁止在泛型类型中声明静态存储属性**（泛型类型的 static 成员无法在
类型擦除后保持唯一性）。这不是「警告」而是编译期硬拒。

### ★ 为什么 66 条断言一条都没拦住 —— 这是判据体系的真实盲区

v1~v63 的全部判据（含 v63 新增的几何基准）验证的都是**文本与接线**：
标记在不在、锚点 count 对不对、guard 腿数够不够、sabotage 拦不拦得住。
**没有任何一条验证「这段 Swift 语法合法」。**

| 判据能证明的 | 判据不能证明的 |
|---|---|
| 改动注入到位了 | 改动**能编译** |
| 接线没被摘掉 | 类型/语法层面合法 |
| 规则没被写死 | 落地在合法的类型上下文里 |

所以会出现这种局面：**66 条断言全绿 + 编译 exit 65**。
这与 v60 的元教训（「v31~v59 从未被真机验证」）是同一个家族：
**判据是代理指标，代理指标全绿不等于目标达成。**

### 修法（两件事，缺一不可）

**① 代码：静态计数器搬到非泛型宿主**

```swift
// [V63-PROBE] 装机可观测性计数器。★必须是**非泛型**类型
private final class _V63Probe {
    static var fastHit: UInt = 0
    static var rebuildHit: UInt = 0
    static var lastPrint: CFTimeInterval = 0
    static func hitFast() { fastHit &+= 1; maybePrint() }
    static func hitRebuild() { rebuildHit &+= 1; maybePrint() }
    private static func maybePrint() { /* 0.5s 节流 + print */ }
}
```

只搬代码是不够的 —— 下一个人还会往泛型格里塞 static。
**② 判据：新增语法级判据 `verify_swift_static_v63`**

- 用花括号配平扫出**所有**泛型类型，逐个检查体内有无 `static var/let`；
- 报错带**字段名 + 行号**（run#157 的三个错误一网打尽）；
- 反向自证：造一份与 run#157 **完全一样**的坏产物，确认判据会红；
  同时确认正常产物（含非泛型类型里的 static）不误报；
- 新增 3 条 sabotage 守着它：
  - `S15` 把探针宿主改回泛型（**run#157 亲手犯过的错**）
  - `S16` 直接把 static 偷渡进泛型 cell（换个写法照样编译失败）
  - `S17` 摘掉非泛型宿主（计数器无处安放）

### 元教训：判据体系的第三代盲区

| 代 | 盲区 | 发现方式 | 补法 |
|---|---|---|---|
| 1 | 只验「标记在位」，锚点腐化看不见 | run#156 | 锚点双形态 + 空测独立计数 |
| 2 | 只验**文本**，不验**语法** | **run#157** | `verify_swift_static_v63` |
| 3 | 只验**产物**，不验**真机行为** | v60 起未解决 | 装机探针（v63 已带，待验） |

第三代仍未解决 —— v63 装机后必须确认 `[V63-PROBE] fast=N` 且 `N>0`。

### 附：读 CI 日志的通道（run#157 实测）

PAT 没有 `actions:read` 时：
- `GET /actions/runs/<id>/jobs` → **404**
- `GET /commits/<sha>/check-runs` → **403**
- `GET /actions/runs/<id>/logs`（zip，**不需要 actions:read**）→ **200** ✅
- `GET /actions/runs/<id>/artifacts` → 200 ✅，但 artifact 需单独再下一层 zip

★关键：xcodebuild 的输出被 `> build.log 2>&1` 重定向后**不在步骤日志里**，
只有 `failed-build.log` artifact 里才有。步骤日志只能看到
`Failed frontend command:` 和一堆 warning —— **拿不到 error 行**。
所以编译类失败必须下 artifact。

### 附 1：这条判据自己踩的两个坑（都靠四形态自证抓出来）

写完 `verify_swift_static_v63` 后，用「同一份代码、四种形态」逐一验证：

| 形态 | 期望 | 结果 |
|---|---|---|
| 合法产物（含 `static var defaultValue: T? { nil }`） | 通过 | ✅ |
| run#157 原样（`private static var` 进泛型 cell） | 拦住 | ✅ |
| S15 探针宿主改回泛型 | 拦住 | ✅ |
| S17 摘掉计数器字段 | 拦住 | ✅ |

**坑一 —— 误报：把 computed property 当成存储属性**

产物里本来就有合法的一处（`IOS15GeometryValueKey`，协议要求）：

```swift
private struct IOS15GeometryValueKey<T: Equatable>: PreferenceKey {
    static var defaultValue: T? { nil }     // ← computed, Swift 完全合法
    static func reduce(...) { ... }
}
```

初版正则只匹配 `static var` 开头 ⇒ 把它判成违规，而它**编译一直通过**。
Swift 禁止的只是 `static stored properties`。

> ⇒ 修法：存储属性必然带 `=` 初始化，computed 必然带 `{` 实现体。**按 `=` 判，零误报。**
> 这就是纪律第 14 条「宁可漏报不可误报」的具体应用 —— 一条会误报的判据比没有判据更坏，
> 因为它会训练人忽略红。

**坑二 —— 漏过：只查「宿主在不在」，不查「计数器在不在」**

第一版 S17 sabotage 故意「摘字段、留类名」，结果判据放过了。
这与 run#156 的「锚点缺失被计入通过」是**同一个病根**：检查了容器，没检查内容。

> ⇒ 修法：花括号配平取出 `_V63Probe` 的类型体，逐个确认
> `static var fastHit / rebuildHit` 都在里面。
> 一般规律：**判据要检查被保护对象的「实质」，而不是「存在性」。**

---

## 4.10 ★★★★★ v64 —— 「自我播种」：三十余版底层 bug 的真面目（2026-10-05）

### 4.10.1 症状：v63 修好通道后，病第一次完整显形

v63 装机实证（本项目三十余版第一次拿到「代码真在跑」的证据）：

```
[V63-PROBE] fast=1412 rebuild=0     （88 次输出）
live=21/26/32/34/45                  （不再是恒 0）
```

但几何判据同时报红：

```
idx=9  尾部极差 717.0pt（上限 8.0）   v62 时 436pt  ← 反而更大
最大单跳 301.0pt    全段跨度 1036.0pt = 名义高的 28.2 倍
v63geom=BAD
```

**病态形态变了**——这是本轮最重要的发现：

| 时期 | 形态 | 证据 |
|---|---|---|
| v30-A | 双引擎测高互相**翻转** | 1176 ⇄ 850，est/pref 交叉 |
| v63 | **单调累加，只涨不跌** | 见下 |

```
11:07:52.403  INVALIDATE idx=9 delta=205 est=31   → pref=236
11:07:52.586  INVALIDATE idx=9 delta=144 est=236  → pref=380
11:07:52.778  INVALIDATE idx=9 delta=175 est=380  → pref=555
11:07:53.170  INVALIDATE idx=9 delta=166 est=643  → pref=809
11:07:53.382  INVALIDATE idx=9 delta=162 est=809  → pref=971
11:07:53.981  INVALIDATE idx=9 delta=202 est=1070 → pref=1272
```

### 4.10.2 ★ 决定性观察：`est_{n+1}` 严格等于 `pref_n`

把上表竖着看，两条规律立刻跳出来：

1. **`est` 恒等于上一拍的 `pref`**（236/380/555/809/971 逐项对齐）
2. **`pref − est` 恒定 ≈ +170pt**（20pt 行高下 = 8~9 行）

`est` 就是 UIKit 下一轮递回来的 `layoutAttributes.size.height`，也就是**我们上一轮亲手写进 `heightCache` 的那个值**。

⇒ 高度不是「被谁算大了」，是**被自己上一轮的答案累加出来的**：

```
H_{n+1} = H_n + 170     H_n = 31 + 170n
```

**v53/v62 的三条短路（欠账/盈余/settle 门）一直在掩盖这个底层 bug** —— 它们让高度锁死在旧值，看起来「稳定」，其实是冻结。v63 修通 invalidate 通道后，底层的错误测量第一次能真正执行，于是露了出来。典型「修好上层，下层塌出来」。

### 4.10.3 根因代码：一句自相矛盾的播种

`MessageListInfrastructure.swift` · `preferredLayoutAttributesFitting`：

```swift
// :531  声明了「我要压缩语义（从内容重算）」
let targetSize = CGSize(width: ..., height: UIView.layoutFittingCompressedSize.height)
...
// :561  却用 super 刚返回的、已经膨胀过的 attrs.size.height 当测量初值
var fittingSize = CGSize(width: targetSize.width, height: attrs.size.height)
...
// :567  压缩优先级在 iOS 15 上不遵守 ⇒ 播种值胜出
fittingSize = contentView.systemLayoutSizeFitting(targetSize, ..., verticalFittingPriority: .fittingSizeLevel)
// :717-725  写回缓存, 成为下一轮的 est
fittingSize.height = _ios15Reconciled
lastComputedHeight = fittingSize.height
```

**`:561` 与 `:531` 自相矛盾**：声明压缩优先级，却把上一轮结果喂回去。
iOS 16+ 上 SwiftUI 遵守 `.fittingSizeLevel`，从内容重算 ⇒ 无害；
**iOS 15 上不遵守，播种值胜出** ⇒ 写回缓存 ⇒ 下一轮 est 更大 ⇒ 再播种 ⇒ 发散。

### 4.10.4 为什么 v63 让它显形，而不是 v63 改坏了

时间线必须说清，否则容易误判：

| 版本 | intrinsicContentSize 高度 | 播种值 | 表现 |
|---|---|---|---|
| v60 | `noIntrinsicMetric`（v60 为治**宽度**污染，把高度也关了 —— **误伤**） | 恒为死的 0 | 环转不起来，但高度永远锁死（v53/v62 看到的「稳定」） |
| v63 | **恢复上报**（`V63-INTSIZE`） | 变成「活的膨胀值」 | 自激环第一次真正跑起来 |

v63 的恢复是**必须保留的正确修复** —— iOS 15 感知 SwiftUI 内容尺寸变化的唯一通道就是 `intrinsicContentSize` + `invalidateIntrinsicContentSize()`（`sizingOptions` 是 iOS 16 才有的；外部四来源交叉验证见 §4.6）。

⇒ **病不是 v63 引入的，是 v63 让一个存在了 30 余版的底层 bug 显形。**
⇒ v64 只断反馈，**不动 v63 的高度上报**。

### 4.10.5 ★ v64 初版被自己的装机数据证伪（推翻重做）

v64 初版设计是「同宽幂等锁」：宽度不变时 0.35s 窗口内不许重复 settle。
判据 `verify_idempotent_v64` 五层 + `reverse_v64` 9 条 sabotage，**自证 9 拦下 0 漏过**。

**然后被上表的时间戳直接推翻**：

- 6 拍间隔 0.183 / 0.192 / 0.392 / 0.212 / 0.599s
- 0.35s 窗口只能拦下 3 拍，**0.392 与 0.599 两拍在窗外照常放行** ⇒ 累加幅度不减
- 更糟：那是**全局单例**，消息列表里多个 cell 通常同宽 ⇒ cell 1 settle 后 cell 2 被误拦
  ⇒ **内容截断，比抖动更糟**

> 这是本项目**第三次**「判据全绿但药不治病」：
> run#156（空测当通过）→ run#157（只验文本不验语法）→ **v64 初版（只验标记在位）**。
> 9 条 sabotage 全部在问「锁在不在」，**没有任何一条问「这把锁拦不拦得住 0.4s/0.6s 那两拍」**。

### 4.10.6 v64 正式方案：切断自我播种

两条，全部落在 `SelfSizingCell.preferredLayoutAttributesFitting` 一个函数里：

| 标记 | 位置 | 做什么 |
|---|---|---|
| `V64-DESEED` | `:561` | 播种值不再取 `attrs.size.height`，改用 `UIView.layoutFittingCompressedSize.height`（与 `:531` 的声明对齐） |
| `V64-CONVERGE` | `:717` 前 | **收敛闸**：若重算结果 ≥ 上一轮 est 且 Tk 没有更新的实测 ⇒ 判定「没真重算，只是旧值回来」⇒ 保留 est，阻断累加 |

**为什么不用「限流」而用「断反馈」**：限流是症状层补丁，它假设「重排太频繁」于是数次数。但病根是「每次重排的输入里混进了上一次的输出」—— 就算只重排一次，那一次也可能返回偏大的值并永久留在缓存里。**断反馈，一次都不需要限。**

**为什么收敛闸不会误杀真实增长**：闸门只在上报值 ≥ est 时收紧，且要求「Tk 实测没有超出 est」。Tk（TextKit）那一路是权威实测，若它给出更高的值，说明这次**真的重算了** ⇒ 放行。

### 4.10.7 判据：反向 9 条全部改成「问实质」

`verify_deseed_v64` 四层 + `reverse_v64.py` 9 条 sabotage：

| # | sabotage | 问的是什么 |
|---|---|---|
| S1 | 摘整个收敛闸（花括号配平） | 只断播种就收工？（不，iOS 15 可能把旧值赢回来） |
| S2 | 闸门只算不改写 | 算出来不用 = 没拦（v53 当年的原样病） |
| S3 | 闸门退化成无条件 | 变成 v53/v62 式锁死，高度永远不更新 |
| S4 | 去掉 Tk 豁免分支 | 会连真实增长一起拦（误杀） |
| S5 | 播种改回取上一轮 | 注释改了代码没改 |
| S6 | **播种换属性名**（`lastComputedHeight`） | **判据不能只逐字匹配一种写法** |
| S7 | 播种不用压缩语义 | 与 `targetSize` 声明不一致 |
| S8 | 闸门挪到写回之后 | 东西都在位，但顺序让它不生效 |
| S9 | 去掉 `est > 4` 下限 | 首帧高度被锁成 0 ⇒ 整格空白 |

**自证结果：9 拦下 / 0 漏过 / 0 空测。**
**负向自检**：拿「只跑阶段①②、未经 fallback」的产物跑判据 ⇒ 退出码 1，报
`播种语句仍取 attrs.size.height(上一轮的结果) —— 这就是自激环本身` ⇒ 判据有分辨力，不是空测。

#### 写这条判据时自己踩的两个坑

1. **判据把自己的基线判红**：我加了一条正则检查「闸门是否被写成无条件」，
   正则假设了缩进形态，结果对**正确的注入**也报错。
   ⇒ 判据自身误报比没有判据更贵 —— 它会让人开始不信判据。
   修法：删掉那条冗余正则（条件检查已覆盖），无条件形态交给 S3 专门测。

2. **sabotage 自己没破坏任何东西**：S8 第一版把闸门插到写回点**之前**，
   而基线里闸门本来就在写回之前 ⇒ 相对顺序根本没变 ⇒ sabotage 空转，
   判据「漏过」了一个**根本没被破坏**的形态。
   ⇒ 这类情况必须被发现，不能算判据的错。修法：插到写回点**之后**
   （那才是「顺序错」的真实形态），并在 sabotage 文档里记下这个坑。

### 4.10.8 装机验证要看什么

```bash
python3 scripts/ios15_verify/verify_v63_geometry.py --log <新装机日志>
```

| 指标 | 病治没治 |
|---|---|
| `idx` 尾部极差 | 从 **717pt** 降到 **≤ 8pt**（`CARD_H_SPREAD_MAX`） |
| `INVALIDATE` 相邻 `est` | 不再满足 `est_{n+1} == pref_n` |
| `[V64-CONVERGE] hold` | 出现该行 = 收敛闸在拦（iOS 15 确实把旧值赢了回来，兜底生效） |
| `[V64-DESEED]` | 出现该行 = 断点已过 |

> ⚠ **判据全绿 ≠ 病治好**（第三代盲区）。v64 至今**未经真机验证**。

---

## 5. 已知风险

1. **令牌泄露**（已处理：仅只读查询，未落盘；但对话中明文出现，**用户需自行撤销**）
2. **v63 未经真机验证**：判据全绿 + 14 条 sabotage 全拦，但 v60 的元教训是
   「v31~v59 从未被真机验证」⇒ **本版必须装机看日志**（清单见 §4.6 末）
3. **★ v64 未经真机验证，且是第三代盲论的直接对象**：v64 判据 9 拦下 0 漏过
   且**负向自检有分辨力**，但它仍然是「验产物」而非「验真机行为」。
   历史对照：v64 初版也是 9 拦下 0 漏过，却被装机时间戳证伪。
   ⇒ 装机后必须看 `[V64-CONVERGE] hold` 与几何尾部极差（清单见 §4.10.8）
4. **★ v64 的兜底闸门在 iOS 15 上的行为无法编译期确认**：`V64-DESEED` 断掉
   播种后，理论上重算只能来自内容；但 iOS 15 的 SwiftUI 是否真遵守
   `.fittingSizeLevel` 只能真机见分晓。若不遵守，`V64-CONVERGE` 是唯一防线。
   ⇒ 这是**有意保留的不确定性**，不是遗漏。
5. **`ios15-clean` 与 main 分叉**：273 commits / 300 文件差异，长期会失控
6. **零 Release / 零 Tag**：CI 产物无法追溯
7. **CI 失败率 30%**，无稳定发布门禁
8. **`port-and-build.yml` 205 KB / 2472 行**：移植逻辑内联在 YAML，维护隐患
9. **9 个判据依赖 `HERE/..` 兜底**找 `ios15_fallback.py`
   （`ci_assert_v50~v53/v565/v58` + `reverse_v47/v50/v51`）。
   v63 链已修掉同类问题（`verify_v63.sh` 把仓库版 fallback 复制进产物树，
   否则 v53 的 sab 层会静默换被测对象），但这 9 个历史判据的隐患仍在。
10. **无 topics**
11. **★ 三阶段脚本用「相对当前目录」定位产物**（`ios15_port.py` 的
    `TARGET_DIR = sys.argv[1] or "src/ios"`）：在仓库根直接跑
    `python3 scripts/ios15_port.py /tmp/x` 会**扫到仓库自己的 src/**
    并就地注入 —— 我踩过一次，已 `git checkout -- src/` 还原。
    ⇒ 正确姿势：`cd <产物树> && python3 scripts/ios15_port.py`。
    建议后续给三个脚本加「产物树必须在仓库外」的断言。

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

### 6.1 `git push` 不可达时的 Git Data API 流程（含两个必踩的坑）

沙箱内 `github.com:443` 常连不上（135 s 超时），但 `api.github.com` 通。
此时走 Git Data API，**必须是四步，不能跳步**：

| 步 | 端点 | 关键点 |
|---|---|---|
| 1 | `POST /git/blobs` | **每个文件一次**，内容 base64。**不可跳过** ↓ |
| 2 | `POST /git/trees` | `base_tree` = 远端当前 sha；`tree[]` 填步骤 1 返回的 sha |
| 3 | `POST /git/commits` | `parents` = 远端当前 sha（单亲即快进） |
| 4 | `PATCH /git/refs/heads/main` | `force: false`（只允许快进） |

**坑 1 —— `422 Invalid tree info`（错误信息完全误导）**

Git Data API 的 tree 只能引用**已存在于远端对象库**的 blob。
本地 `git hash-object` 算出的 sha 在远端 `GET /git/blobs/<sha>` 一律 404，
直接拿去建树就报 `422 Invalid tree info` —— 报错只说「tree info 无效」，
**完全不提「blob 不存在」**。必须先把 8 个 blob 全部 `POST /git/blobs` 上传完。

> 防御手段：上传时对每个文件重算 `sha1("blob %d\0" + content)` 与本地 sha 比对。
> 本轮就靠这道校验抓到我手抄 sha 时多打一个字符（`fe9da837be21` vs `fe9da837be22`），
> 否则会静默推上去一份坏文件。

**坑 2 —— `git mv` 的重命名不会自动生效**

`base_tree` 之上只写新路径 = **复制**，旧路径仍在远端。
必须显式补一条 `{"path": 旧路径, "mode": "100644", "type": "blob", "sha": null}`（`sha: null` = 删除）。
验证方式：`GET /contents/<旧路径>` 应 404，且提交里 GitHub 自己把该文件标成 `renamed` 而非 `added`。

**推完必做：在远端快照上跑判据，而不是在本地工作区跑**

```bash
curl -sL -u "x-access-token:$PAT" -o om.tar.gz \
  https://codeload.github.com/Niubiprass/OpenMinis/tar.gz/refs/heads/main
tar xzf om.tar.gz && cd OpenMinis-main && bash scripts/verify_v63.sh
```

私有仓库的 `codeload` **必须带认证**（不带直接 404，不是 401）。
本轮验证结论：远端快照 `verify_v63.sh` 退出码 0，33 通过 / 0 失败 / 0 跳过，
幂等 704 文件逐字节相同 —— 这才能证明 CI 会绿。

> 顺带记一个测量陷阱：`python3 x.py | tail -40; echo $?` 拿到的是 **`tail` 的退出码**，
> 会把红判据显示成 `EXIT=0`。判据自身的退出码约定（0/1/3）是对的，
> 是观测方式骗人。**量退出码必须重定向到文件再读**：`python3 x.py >log 2>&1; echo $?`。

---

## 7. 干净上游位置

`/tmp/up_1_14/src/ios`（从 tag 1.14 经 API 下载）
设置：`export OPENMINIS_UPSTREAM_IOS=/tmp/up_1_14/src/ios`
