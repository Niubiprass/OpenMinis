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

### 4.10.9 ★★★★ run#159 失败复盘 —— 第四次「判据全绿」，也是最贵的一次

推送 v64 后 CI #159 失败。本地全链是 **35 通过 / 0 失败 / 0 跳过**、幂等连跑
3 轮逐字节相同、v64 判据 9 拦下 0 漏过 —— 然后编译红：

```
MessageListInfrastructure.swift:762:27: error: cannot find '_v64found' in scope
```

**全文仅此一个错误**。我写的收敛闸引用了 `_v64found`，真名是 `_ios15Found`。

#### 为什么 35 条判据一条都没拦住

它们全都只查**文本在不在**：

| 判据层 | 查什么 | 为什么漏 |
|---|---|---|
| `verify_deseed_v64` ①~④ | 标记、表达式、数据流顺序 | `_v64found` 出现在闸门里，条件“在位”成立 |
| `verify_swift_static_v63` | 泛型禁 static | 与本错误无关 |
| `reverse_v64` 9 条 sab | 锁/闸门在不在、改没改写 |  sabotage 都是「破坏已存在的东西」，**没有一条制造一个「引用不存在的标识符」** |
| 幂等门 | 连跑 3 轮逐字节相同 | 错误是**稳定的**，每轮都一样 |
| Swift 插值门禁 | C 风格转换 | 无关 |

⇒ 这不是判据松，是**判据的种类缺失**：没有任何一条在问
「这段代码引用的东西存在吗」。

#### 修法：判据加第 ⑤ 层（标识符存在性）

```python
for ident in ("_v64est", "_v64tk", "_v64grew", "_v64tkFresh",
              "_ios15Reconciled", "_ios15TkSum", "_ios15Found"):
    # 声明行(let/var X = ...)才算定义; 纯引用不算
    if not re.search(r"(?:let|var)\s+%s" % re.escape(ident), infra):
        raise RuntimeError("... 引用的 %r 在产物里**没有声明** ...")
# 反向: 闸门里不得出现未在其内部声明的 _v64* 变量
declared = set(re.findall(r"(?:let|var)\s+(_v64\w+)", gate))
unknown = set(re.findall(r"(_v64\w+)", gate)) - declared
```

反向那条尤其重要：它**不依赖我维护标识符清单** ——
任何人往闸门里新写一个 `_v64xxx` 而忘了 `let`，都会被抓。

#### S10 sabotage：把 run#159 的真实错误固化成回归

```python
def s10_bad_identifier(t):
    """收敛闸引用不存在的标识符 —— run#159 的真实错误。"""
    return t.replace("let _v64tkFresh = _ios15Found && ...",
                     "let _v64tkFresh = _v64found && ...", 1)
```

自证：**10 拦下 / 0 漏过 / 0 空测**。

> ★为什么这条值得留（而不是「这种错谁也不会写」）：
> 前三次「判据全绿」浪费的是时间，这次浪费的是**一整次 CI run**（约 8 分钟 +
> 一次 Actions 额度 + 一轮装机等待）。而且它揭示了一类**系统性**盲区：
> 任何靠正则检查文本的判据，都查不出「引用未定义」。

#### 附：本次还踩了两个环境坑

1. **幂等短路掩盖修复**：修完 `ios15_fallback.py` 后直接对旧产物重跑，
   `if "[V64-DESEED]" in t: return t` 让它不重新注入，产物里**仍是错的**。
   ⇒ 验证修复**必须从干净上游重建**（verify-discipline 第 1 条）。
2. **三阶段脚本的下载会卡死整条链**：`ios15_port_v2.py` 默认从 codeload 重下
   tag 1.14，慢网下进程 CPU 0%、`wchan=do_poll`、卡满 `timeout=180`；
   `reverse_v62.py` 内部也会调它 ⇒ **整条回归卡住**。
   ⇒ 加 `OPENMINIS_UPSTREAM_LOCAL`（本地全复用，CI 不设）+ 回归显式传 env。

#### 四次「判据全绿」汇总

| 次数 | 现象 | 判据缺的那一类 | 修法 |
|---|---|---|---|
| run#156 | 空测被计入通过 | 判据**自己跑没跑** | BASE 独立计数、不计入 passed |
| run#157 | 编译红（泛型 static） | **语法合法性** | `verify_swift_static_v63` |
| v64 初版 | 药不治病（时间窗拦不住） | **行为实质**（不是标记在位） | 反向改问实质、S6 防换名 |
| **run#159** | 编译红（标识符不存在） | **引用完整性** | 第 ⑤ 层 + S10 |

⇒ 一条规律贯穿四次：**判据只查「我写下的东西在不在」，从不查「它引用的、依赖的、声称成立的，实际是不是真的」**。

---

## 4.11 ★★★★★★ v65 —— 累加治好了，但病在另一层（2026-10-05 13:21 装机）

### 4.11.1 v64 装机结论：那条线**确实修好了**

用户反馈「解决了一点点，还是闪屏/抖/卡字」。装机日志（`minis-2026-10-05.log` 13:21）证实 v64 生效：

| 指标 | v63 装机（11:07） | v64 装机（13:21） |
|---|---|---|
| `est→pref` 累加 | `236→380→555→809→971→1272`，恒 +170/拍 | **0 次** |
| FIRST-MEASURE 自旋 | 反复纠偏 | **13 对，每对只 1 次，无自旋** |
| `[V64-CONVERGE]` | （不存在） | 触发 176 次，**est==recomputed 176/176** |

⇒ **累加彻底消失**。`est==recomputed` 100% 相同说明断掉播种后 SwiftUI 一字不差地返回上一轮 est —— **它根本没重测**，但也**不再变大**。v64 的目标达成了。

### 4.11.2 但真根因在**守卫那一层**，日志指得死死的

```
[TextContainerGuard] short-circuited setSize: REJECT-NAN-INF-NEG
    size=0.0x-8.0   × 43
    size=0.0x-16.0  × 18        合计 61 次
```

**宽度 0、高度负数**，全部被守卫 `return` **丢弃**。

```
[TextContainerGuard] short-circuited setSize: size=358.0x19.0  × 39   ← 一行，真实行高
                                            size=358.0x41.0  × 46   ← 两行，真实行高
```

这两个**不是哨兵**（哨兵是 ≥3000 被压到 2000），是**真正的行高**，也被同 tick 熔断连带丢掉。

### 4.11.3 三条排除法：为什么 30 余版没治好

| # | 假设 | 排除依据 |
|---|---|---|
| ① | self-sizing 反馈环 | `est==recomputed` 176/176，累加已消失 |
| ② | 宽度污染 | v34/v47/v48/v51 已钉 358，日志 `tcW` 恒 358 |
| ③ | v64 闸门锁死 | 闸门只在「两侧都没更新信息」时收紧，Tk 有值时放行 |
| ⇒ | **剩下的唯一还在丢东西的环节，就是守卫本身** |

旁证链完全闭合：`tk=27.0 ×83` / `est=31.0 ×96` —— **31pt 就是一行**。用户看到的「卡字」不是布局算错，是**排版压根没跑**。

### 4.11.4 v65 两条（同版落地，缺一不可）

| 标记 | 位置 | 做什么 |
|---|---|---|
| `V65-FIXSIZE` | 守卫 `REJECT` 分支 | **就地修正后转发**，不再丢弃。宽 ≤0 → 取容器自身宽（KVC），兜底屏宽-32；高 ≤0 → `fabs` |
| `V65-STORM` | 守卫 `commitCount` 自增处 | 风暴预算**只对哨兵**（≥2000）计费，真实行高永不参与 |

★**为什么必须同版**：只做① → 排版能跑但一帧内被熔断吞掉，仍抖；只做② → 排版不丢但脏尺寸（宽 0）仍让 TextKit 排错，仍卡字。两条分开做，症状互相掩盖，又变成"看不出哪条有效"。

★**为什么「修正」而不是「丢弃」**：丢弃看起来安全（不把脏值喂给 TextKit），但**丢弃 = 保留过期几何 = 排版结果永远滞后**，这正是卡字的直接原因。这些值是**有限**的，数值上完全可以变成合法尺寸，不存在喂进去会病态循环的风险（那是 inf/NaN 的问题，已单独硬拒）。

### 4.11.5 本轮真实犯的一次编译红（第四次同族）

写 v65 时在 `V65-STORM` 里引用了 `kProbeHeightCeiling` —— 它是**函数体内某段 `{}` 里的局部 const**，作用域外 ⇒ **编译必红**。当场抓住并改成字面量 `2000.0`。

⇒ 写入 `verify-discipline` 的判据第 ⑤ 层：**作用域也要查**，不只是「标识符存不存在」。固化方式：
* 判据第 ⑤ 层加作用域自证（V65-STORM 段落引用局部 const 即报错）
* 反向 **S9** 固化「引用 `kProbeHeightCeiling`」
* 反向 **S10** 固化「引用不存在的 `kV65SentinelFloor`」（run#159 原型）

### 4.11.6 v65 判据与反向

**判据 5 层**（`scripts/ios15_verify/verify_guard_v65.py`）：

| 层 | 查什么 | 防哪类错 |
|---|---|---|
| ① | 丢弃分支已拆开（NaN/inf 单独硬拒，负尺寸不共处一个 if） | 旧形态 = 61 次丢弃 |
| ② | 修正后**没有 return**（就地改值继续往下走） | 改回丢弃语义 |
| ③ | 门槛**包住** `commitCount += 1` 与 `stormed = YES` | 顺序让它不生效 |
| ④ | 门槛字面量 == `kProbeHeightCeiling` | 两条改动互相抵消 |
| ⑤ | 标识符存在 + **作用域**自证 | run#159 / 本轮编译红 |

★判据自身踩了两个坑（已写进 `verify-discipline` §15）：
1. 标记在**注释**里，正则撞上注释里的条件表达式 ⇒ 加 `_strip_comments`（等长替换，偏移一一对应）
2. 条件在 `if (...)` 的**括号**里，不在花括号块内 ⇒ 取块只能取到 body，判据误报
3. 熔断 SKIP 分支里的 `return` 是**合法的**（丢哨兵正是熔断本意）⇒ 不能一棍子打尽

**反向 10 条**：10 拦下 / 0 漏过 / 0 空测。

★S2 第一次设计成「把 return 插在修正块**之外**」，结果判据为它误伤了风暴 SKIP 的合法 return ⇒ 改成插在块内。教训：**反向 sabotage 自己也可能设计错**，必须确认它破坏的语义与判据声称的一致。

**全量回归：37 通过 / 0 失败 / 0 跳过**（含幂等 3 轮 704 文件逐字节相同）。

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

## §4.12 CI#161 失败定位：坏的不是判据，是**门禁的抽取器**（2026-10-05）

v65 已推送（`main@49f8007926`），CI #161 红了一项。日志里最显眼的一行是：

```
❌ script ios15_verify/verify_guard_v65.py
     ❌ [Errno 2] No such file or directory: '"$GUARD_V65"'
```

**这行字具有很强的误导性** —— 它长得很像「v65 守卫判据坏了」。
但同一份日志里，全版本回归是 **37 通过 / 0 失败 / 0 跳过**，
其中 `v65 守卫判据(5层含作用域自证)` 与 `v65 反向(10条)` **都绿**。
⇒ 判据没坏，坏的是**把判据拉起来的那段代码**。

### 4.12.1 根因

`scripts/ios15_verify/local_all_gates.py`（CI 断言 52b「本地全量门禁自检」的主体）
用一个正则从 workflow 里抽判据调用的参数：

```python
pat = re.compile(r'python3 "\$SCRIPT_DIR/(ios15_verify/...\.py)"((?:\s+[^\s;\\]+)*)')
```

而 v65 断言 69 里参数写的是 **shell 变量**：

```bash
GUARD_V65="src/ios/Shared/NSTextContainerSetSizeGuard.m"
if python3 "$SCRIPT_DIR/ios15_verify/verify_guard_v65.py" "$GUARD_V65" ; then
```

正则把 `"$GUARD_V65"` **原样**抽成字面量 `'"$GUARD_V65"'`（连引号一起），
`args.split()` 后递下去，于是脚本 `open('"$GUARD_V65"')` → `[Errno 2]`。

⇒ **CI#161 是「判据体系里第一次出现用 shell 变量传参的判据」**，
抽取器此前只处理过字面量参数（`NEEDS_ARGS` 那两条是硬编码的），从来没遇到过 `$`。

### 4.12.2 修法（两处，同族）

| 缺陷 | 现象 | 修法 |
|---|---|---|
| ① shell 变量未求值 | `'"$VAR"'` 被当文件名递下去 | 收整份 workflow 的 `VAR=value`（`parse_shell_vars`），`expand_args` 先求值再传；**求不出就抛「抽取故障」并由 main() 记成独立红项**，绝不静默传字面量 |
| ② 管道/重定向吞进参数 | `regress_all_v.py . 2>&1 \| tee f` 的 `2>&1 \| tee f` 也被当参数 | 按 **token** 判：含 `\| & ; < > ( ) \` 或**纯数字**（FD）即截断 |

★ ② 是顺手发现的同族隐患：它当前**无害**（`regress_all_v.py` 只用 `argv[1]`），
但只要哪天哪个判据多读一个 `argv`，就会拿到 `|` 当文件名。
★ ① 的正则修法踩了一次坑：先按**字符**截断，结果 `2>&1` 的 `2` 留了下来变成 `['.', '2']`。
**FD 是独立 token，必须单独判 `^\d+$`**。

### 4.12.3 为什么把抽取器也纳入反向测试

「判据全绿」这个前提，一直是靠**人相信判据被正确调用**支撑的。
CI#161 证明这个前提也会悄悄失效。所以新增：

* `scripts/ios15_verify/reverse_local_all_gates.py` —— 9 条 sabotage，
  S1 就是 CI#161 的原样故障；已进 `regress_all_v.py` 的 `CHECKS`（mode=`self`，不依赖产物）
  与 `MANDATORY`。
* workflow **断言 70**：单列一条，不与其它判据混在一起。
* `docs/verify-discipline.md §22`：写下这一整类错误的教训。

★ 这条反向测试**自己也翻了三次车**（monkeypatch 改不到被 exec 的模块、
`exec` 的 dict 当模块用导致 8 条假绿、观测点够不着被改的路径），
三条都写进 §22.4 —— 「崩溃暴露了故障」不等于「测到了那一处能力」。

### 4.12.4 本地验证口径

| 场景 | 结果 |
|---|---|
| `regress_all_v.py /tmp/v65check`（带干净上游） | **38 通过 / 0 失败 / 0 跳过**（比 v64 轮多 1 项：门禁抽取器反向） |
| `reverse_local_all_gates.py` | **9 拦下 / 0 漏过 / 0 空测** |
| `local_all_gates.py`（v65check 树 + `.upstream-ios`） | 修正前 63/3（1 条真红 + 2 条环境），**修正后需复跑确认** |
| `bash_syntax_check.py` | 21 个 run 块 0 语法错 |
| `yaml.safe_load` | OK |

## §4.13 CI#162 编译红：**我的 clang 桩骗了我**（本项目第六次「验证手段骗了自己」）

CI#161 修好门禁后推送（`main@2fc6ff9020`），CI #162 编译红：

```
NSTextContainerSetSizeGuard.m:153:51: error: no member named 'width' in 'struct CGRect'
  153 |   _w = [UIScreen mainScreen].bounds.width - 32.0;
```

而 v65 推送前我做过**真实的 clang 语法+类型检查**（自建 UIKit/Foundation/objc 桩），
结果 **0 error**。⇒ 判据全绿、clang 也绿，**只有真编译器红**。

### 4.13.1 根因：一行桩代码

```c
// /tmp/v65syn/stub.h:19  —— 我写的桩：
typedef struct CGRect { CGPoint origin; CGSize size; CGFloat width; CGFloat height; } CGRectRec;
                                                                  ^^^^^^^^^^^^^^^^^^^^ 我加的
```

真实 SDK 里 `CGRect` **没有** `width`/`height` 字段 —— 它们是 CoreGraphics
`CGGeometry` 这个 **category** 提供的。而 **UIKit 的模块化导入不 re-export
该 category**，所以文件顶部有 `#import <UIKit/UIKit.h>` 也不管用。

我当初为了"让桩好写"给 `CGRect` 补了这两个字段 ⇒ **桩比真实 SDK 宽松** ⇒
编译检查成了一盏永远绿的灯。★ 讽刺的是 `CGSize` 的 `width/height` **是真的**
struct 成员，两者只有 `R` 一个字母之差。

### 4.13.2 修法与防复发

**代码**：`.bounds.width` 改走 KVC（与同段 `[... valueForKey:@"size"]` 一致，纯运行期）：

```objc
NSValue *_bv = [[UIScreen mainScreen] valueForKey:@"bounds"];
if (_bv) _w = (CGFloat)[_bv CGSizeValue].width;
...
if (!(_w > 1) || !isfinite(_w) || _w > 1e5) { _w = 358.0; }   // 358 = 屏宽-32
_w -= 32.0;
```

顺手扫全文件：`origin/size/minX/midX/...` 真代码**一处都没有**（只用 `CGSize` 真成员），
所以这是**唯一**一处 category 依赖。

**判据**：`verify_guard_v65.py` 加**第 ⑥ 层**（纯源码检查，不依赖任何桩）——
禁 `.bounds/.frame/.size/.origin` 后接 `.width/.height/minX/...`。

**反向**：`reverse_guard_v65.py` 加 **S11 = 原样还原 CI#162 那行**。
★ S11 第一版把整段 KVC 换成一行 `bounds.width`，虽然拦下了，但报的是
「② 负高修正缺失」—— 先撞上第②层，**没测到第⑥层本身**。改成只改兜底那一行，
KVC 探测段与 fabs 修正全留，于是精确报「⑥ 用到了 CGRect 的 category 成员」。
（同 §21/§22.4：拦下 ≠ 测到。）

**桩本身修正**：`stub.h` 的 `CGRect` 去掉 width/height 字段，并写明
「桩只允许比真实 SDK 严格，不允许更宽松」。

### 4.13.3 验证顺序（这次做对了）

1. **先证明桩能抓坏形态**：用**旧的已知坏**代码跑修正后的桩
   ⇒ 恰好复现 CI 那一行 `error: no member named 'width' in 'struct CGRect'`；
2. 再用**新**代码跑 ⇒ 0 error。

跳过第 1 步的话，"0 error" 只说明"桩没意见"，不说明代码对 —— 上一轮就栽在这。

### 4.13.4 本地验证口径

| 场景 | 结果 |
|---|---|
| clang 严格桩（旧代码） | 1 error，**与 CI 逐字一致**（证明桩已变严） |
| clang 严格桩（新代码） | **0 error** |
| `verify_guard_v65.py` | **6 层全过** |
| `reverse_guard_v65.py` | **11 拦下 / 0 漏过 / 0 空测**（S11 精确命中 ⑥） |
| `regress_all_v.py`（干净树重建） | **38 通过 / 0 失败 / 0 跳过** |
| `bash -n` / YAML | 21 个 run 块 0 错 / OK |

★ 顺带记一个本地操作坑：`ios15_fallback.py` 的参数是 **`src/ios`**（相对仓库根），
传 `.` 会让它去 `./Views/...` 找文件 ⇒ 全部 SKIP ⇒ 26 项判据集体变红。
看起来像"炸了一大片"，实则是"一个文件都没改"。判红时先看**红项覆盖面**：
连历史判据全红，通常是产物树本身没生成对，而不是判据坏了。

## §4.14 v65 装机日志：**抖/卡/闪退三者是同一个根因**（第七次「验证手段骗了自己」）

用户装机 v65（iOS 15.5 / iPhone13,2），反馈"还是有一点点闪、会抖动，还闪退一次"，
给了 8.log（88990 行）+ crash report。**这一节的结论全部来自装机日志的实测数字，
没有一个字是推断。**

### 4.14.1 闪退：SIGKILL，与我们的代码无关但被我们触发

crash report 关键行：

```
Type:    ⚠️ FOREGROUND CRASH (SIGKILL — app was in use)
Memory:  128 MB   /  System free: 1969 MB  /  Memory pressure: normal
--- MetricKit Call Stack ---
(none — SIGKILL has no stack)
⚠️ Injected: Choicy.dylib, Crane.dylib, libellekit.dylib, CopylogXHelper.dylib,
             MUtoolCapture.dylib, MUtoolRefresh.dylib, ScreenCoreHelper.dylib,
             Speedster.dylib, SquidExtender.dylib, genesisstatusbar.dylib
Hang: 6281ms repeat=1
```

⇒ SIGKILL **无栈**（不是崩溃，是被系统杀）；设备注入 **11 个第三方 tweak**
（报告自己都提示「crashes may originate there, not in Minis」）；
当时压力 normal ⇒ **不是 jetsam 内存杀**。
★ 关键线索是那份 **6281ms 的 hang 栈**（满屏 UIKitCore/QuartzCore/UIFoundation）
与 8.log 里 17:20:41-55 的风暴窗口**完全对得上** ⇒ 主线程被卡到系统放弃。

### 4.14.2 ★★ 根因：`fabs(0.0) == 0.0` —— "修正"是个空操作

8.log 里 93%（82583/88990）的行都是 guard 日志。按尺寸分类：

```
82507  size=0.0x0.0   -> 326.0x0.0     ← 前后高度**完全相同**
  25   size=0.0x-8.0  -> 200.0x8.0
  17   size=0.0x2000.0 -> 358.0x2000.0
   1   size=0.0x<1.797e308> -> 326.0x<1.797e308>   (Double.greatestFiniteMagnitude)
```

**第一行就是病根。** v65 的高度修正是：

```objc
if (newSize.height <= 0) { newSize.height = fabs(newSize.height); }
```

`fabs(0.0) == 0.0` ⇒ 打印出来的前后尺寸**完全一样** ⇒
**对装机日志里 99.9% 的形态（0x0）而言，"就地修正后转发"是空操作**：
高度 0 原样喂给 TextKit，排版出 0 行，下一帧还是 0。

日志是每 32 次打一条（`& 0x1F == 1`），`total=` 计数器给出真相：

```
实际进入修正分支 = 2644129 次   (约 264 万)
其中 0x0 占比 = 82507×32 ≈ 264 万  →  几乎 100%
集中在**同一个容器** 0x2802b8820:  82501 / 82507
时间跨度: 17:20:41.765 → 17:20:55  (14 秒)
```

**一个容器 14 秒被喂 264 万次 `0x0`。**

### 4.14.3 为什么 v65 的熔断没拦住它 —— 豁免规则漏了最毒的形态

v65 的熔断豁免规则是「**只有哨兵（高 ≥2000）才计入风暴预算**」，
理由是"真实排版高度不该被熔断吞掉"。但 `0x0`
**既不是哨兵、也不是正常高度，而是上游算崩的产物** —— 恰恰最该熔断，却被豁免。

更糟：per-tick 熔断**每换一次 tick 就清零**，而上游 `0x0` 是**每个 tick 都在喂**
⇒ 计数永远到不了 `kStormForwardLimit=40` ⇒ **永远不熔断**。

### 4.14.4 ★ 抖 / 卡 / 崩是同一个根因（内存数据闭合）

风暴窗口内的内存曲线（8.log 的 MemMonitor）：

| 时刻 | 内存 | Δ |
|---|---|---|
| 17:20:39 | 151.8 MB | — |
| 17:20:42 | 296.2 MB | +144.5 |
| 17:20:43 | 472.5 MB | +176.2 |
| 17:20:44 | **624.2 MB** | +151.8 |

**14 秒涨 470MB。** 每次转发都要 `KVC 取 NSValue → CGSizeValue → 装箱 → 修正 → 转发`，
264 万次 ⇒ 内存暴涨 ⇒ 内存压力 ⇒ SIGKILL（闪退）；
同期主线程 6281ms 卡顿（抖动）。

⇒ **用户报的"闪 + 抖 + 崩"三个症状，是一个根因的三个表现。**
前六代一直把它们当三个病在治，这是**症状级**思维，不是根因级。

### 4.14.5 我在这一轮差点犯的第七次错（**已当场抓住**）

我第一眼看 `0.0x<1.797e308>` 那一行，立刻判"哨兵值没被 `kProbeHeightCeiling` 压到 2000，
穿过了守卫"—— **这是误读**：
`FIXED-NONPOSITIVE` 日志打在**修正后、继续下走之前**，
而 `kProbeHeightCeiling` 的压位在**更下面的行**（227-237）⇒ 它其实被处理了。

★ **"看到穿过去了"和"验证了穿过去了"是两回事。**
同 §21/§22.4「拦下 ≠ 测到」，这次是它的镜像：**看似抓到 ≠ 真抓到**。
若我据此判"哨兵闸门失效"并去改它，就会又一次改错地方。

### 4.14.6 v66 三处修法

| # | 修法 | 治的是 |
|---|---|---|
| ① | 高度修正 `fabs` 后**加下界钳制** `if (!(_ah > 1.0)) { _ah = 1.0; }` | 直接根因：`0x0` 不再空转 |
| ② | `GuardState` 加 `nonPositiveStreak`，**非正宽高跨 tick 累加**计费 | 264 万次风暴（per-tick 拦不住） |
| ③ | 转发前加**跨 tick 硬闸门** `nonPositiveStreak > kNonPositiveHardLimit(400)` | 止住 14 秒 264 万次 |

★ ③ 为什么 `return` 是安全的、且**不与"丢弃=卡字"矛盾**：
v65 之前靠"丢弃坏尺寸"止风暴，代价是 TextKit 保留过期几何 ⇒ 卡字。
现在非正高度**先被修正成合法尺寸**（高度抬到 1.0），
连续命中到上限才停止转发 ⇒ 此时容器**已经拿到过一个合法几何**，
保留它 ≠ "从未更新过的过期几何"。

### 4.14.7 判据第 ⑦ 层与反向 S12/S13

**为什么前 6 层全放过了它**：`fabs` 那个写法**语法完全合法、编译通过、
看代码"像不像修好了"一律放行** ⇒ 本项目第七次「验证手段骗了自己」的第 7 号形态。

⇒ 第 ⑦ 层（3 条断言，全部**不依赖桩**）：
1. 禁 `newSize.height = fabs(newSize.height)`（空操作）；
2. 必须有下界钳制 `if (!(_x > 1.0))`；
3. 必须有 `kNonPositiveHardLimit`，且 `nonPositiveStreak` **不得被任何清零**。

⇒ 反向 **S12**（还原 `fabs` 空操作）/ **S13**（把跨 tick 累加退回 per-tick）。
★ 两条都**精确命中第 ⑦ 层**，没先撞上 ②/③（拦下 ≠ 测到）。

### 4.14.8 本轮又一次踩到 §19「标识符存在 ≠ 可见」

`_v65orig_w/_v65orig_h` 我先声明在修正分支的 `if` 块内，熔断段在其后 ⇒
clang 报 4 处 `use of undeclared identifier`。
**C 的块作用域：块内声明只到块尾可见。** ⇒ 提到函数体开头声明、块内只赋值。
★ 这是该同族第四次（§19 记的是 v65 三次 + 此次）。

### 4.14.9 验证（本轮口径）

| 项 | 结果 |
|---|---|
| clang 严格桩（新代码） | **0 error** |
| clang 桩有效性自检 | 还原 CI#162 那行 ⇒ **逐字复现** `no member named 'width' in 'struct CGRect'` |
| v65/v66 判据 | **7 层全过** |
| v65/v66 反向 | **13 拦下 / 0 漏过 / 0 空测**（S12/S13 精确命中 ⑦） |
| 全量回归（干净树重建） | **38 通过 / 0 失败 / 0 跳过** |
| bash -n / YAML | 21 个 run 块 0 错 / OK |

### 4.14.10 ★ 装机效果**仍然未知**

这三处是**从日志数字推出来的因果链**，不是装机验证过的结论。
装机后必须看：
- `NONPOSITIVE-STORM` / `NONPOSITIVE-HARDSTOP` 是否出现（出现 = 闸门在起作用）；
- 修正后是否还出现 `size=0.0x0.0 -> 326.0x0.0`（应该变成 `-> 326.0x1.0`）；
- 内存曲线是否还在 14 秒内涨几百 MB；
- 抖动与闪退是否消失。
