#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v46 正向验证: 抓"诊断段缺失"、"判据字段丢失"与"★纯诊断被写成修法"三类回归。

用法: python3 verify_v46.py [产物根目录]
默认 /tmp/ci_v46

背景 (minis-2026-10-03 15.log, v45 装机实测, 111 条 V44-TEXTFRAME):

  v45 修法**依然完全有效** —— `V45-TVHFIX debt` 全为 0.0(log14 71/71,
  log15 109 条无一例外), 跨帧 tvH 稳定(23 个 len 里只有 len=49 有多值,
  且是流式正常重测 182->236, 不是抖动)。假设 A 已彻底关闭。

  但用户报出两个**新现象**, log15 指向两条独立根因:

  现象一「终端框盖住上面的字 / 定时任务字一下有一下没有」= v44 **假设 C
  首次真实命中**。决定性现场:

      [V44-TEXTFRAME] tvH=304.3 svAfter=376.3 usedH=114.3 needH=304.3 len=29
      [invalidateCell][SKIP-DEDUPE] lastH=304.3 tableGen=4 — fingerprint match
      [table#0 CACHE UPDATE] rows=7 cols=2          <- 表格内容变了
      [UAV][SKIP-DEDUPE] tableGen=6                <- 代数变了但仍被去重跳过

  三个数字打架: needH=304.3 / usedH=114.3 / svAfter=376.3。**usedH 只有
  needH 的 1/3** —— 表格那个 7x2 附件占的 ~190pt 完全没进 usedRect。

  量化(本脚本第 5 组判据的立论依据): 111 条里 **71 条 needH-usedH > 8.5**
  (中位 55.6pt, 最大 190.0pt), 另 40 条 <= 8.5(纯文字, 差额就是
  textContainerInset 的 8.1~8.3)。**差额与"有没有附件"完全同构。**

  而"字一下有一下没有"是 len=49 那组: 唯一一组 **usedH 恒为 99.9 而
  needH 在 182<->236 之间跳**的样本 —— 附件高度反复切换, 文字跟着忽隐忽现。

  现象二「下面空白一片」= 脏宽(tcW=390 96/111 条, needH 按净宽 358 算),
  与附件链无关, 留待 v47。

本脚本最关键的一条是 `★纯诊断`: v46 的全部价值在于"装机数据能归因"。
链路上有四个候选根因(D1 缓存未失效 / D2 探针宽度 / D3 失效信号未消费 /
D4 容器被 TextContainerGuard 短路), 修法互相冲突 —— D1 要放宽缓存失效判据,
而那正是 HangFix 2026-05-14 治"流式每 token 全量重测致主线程卡死数秒"故意
保留的; D4 要放宽 guard, 而 guard 是治 fillLayoutHole 11918ms 卡死的。
**两处都是拿性能换正确性的历史 trade-off。** 所以 v46 一行几何都不碰,
只读 attachment / cachedLayout / 容器状态。任何写操作都会让归因失效:
分不清"修好了"还是"被诊断改坏了"。宁可让 CI 拦下。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v46"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

ok = 0
bad = []


def ck(name, cond):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(name)


if not os.path.exists(MD):
    print(f"产物不存在: {MD}")
    sys.exit(2)

t = open(MD, encoding="utf-8").read()
src = open("/workspace/OpenMinis/scripts/ios15_fallback.py", encoding="utf-8") \
    if os.path.exists("/workspace/OpenMinis/scripts/ios15_fallback.py") else None

# ============================================================
# 0. 共用工具: 剥注释与字符串, 只留可执行代码
#    (与 ios15_fallback._strip_swift_noise 同算法。判据必须基于**代码**,
#     否则注释里写 "缓存 = nil" 会被当成真赋值。)
# ============================================================


def strip_noise(src_text):
    out = []
    i = 0
    n = len(src_text)
    while i < n:
        c = src_text[i]
        if c == "/" and i + 1 < n and src_text[i + 1] == "/":
            j = src_text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src_text[i + 1] == "*":
            depth = 1
            i += 2
            while i < n and depth > 0:
                if src_text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif src_text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        if src_text.startswith('"""', i):
            j = src_text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append('""')
            i = j
            continue
        if c == '"':
            i += 1
            while i < n:
                if src_text[i] == "\\":
                    i += 2
                    continue
                if src_text[i] == '"':
                    break
                i += 1
            i += 1
            out.append('""')
            continue
        out.append(c)
        i += 1
    return "".join(out)


CODE = strip_noise(t)

# ============================================================
# 1. 段落存在性
# ============================================================
# ★定位必须用唯一标识串, 不能用 "// [V46-ATTACH]" —— 只读访问器的
# doc 注释里也有这个标记(它在 TableAttachment 里, 位置远早于诊断段),
# 用短标记会抓到访问器, 后面所有位置/切片判据全部错位。
M46 = "// [V46-ATTACH] 表格附件高度"
ck("v46 段存在", M46 in t)
ck("v46 NSLog 存在", 'NSLog("[V46-ATTACH]' in t)

# ============================================================
# 2. 核心判据字段 —— 少一个就有一个候选根因永远无法验证
# ============================================================
for fld, desc in [
    ("_v46AttN = 0", "attN(附件个数, 0 则本条无意义)"),
    ("_v46AttWant", "attWant(attachmentBounds 现在会返回多高)"),
    ("_v46AttCached", "attCached(缓存扣了多少)"),
    ("_v46AttCachedW", "cachedW(缓存是在哪个宽度下算的)"),
    ("_v46AttGen", "attGen(contentGeneration)"),
    ("_v46AttNVI", "attNVI(needsLayoutInvalidation 是否置位)"),
    ("_v46R = _t.attachmentBounds(", "直接调 attachmentBounds 取真值"),
    ("_v46AttWant += _v46R.height", "attWant 累加附件返回高度"),
    ("_v46Used = _v46Lm.usedRect(", "并列对照 usedH"),
    ("_v46Lm.numberOfGlyphs", "nGlyph(排版器真的排出几个字形)"),
    ("if _v46AttN > 0 {", "无附件时跳过(不刷无意义日志)"),
]:
    ck(f"判据字段 {desc}", fld in t)

# 日志格式串必须把上面所有字段都打出来, 否则字段在代码里却没进日志 = 白读
ck("NSLog 格式串含 attWant", "attWant=%.1f" in t)
ck("NSLog 格式串含 cachedW", "cachedW=%.1f" in t)
ck("NSLog 格式串含 attNVI", "attNVI=%d" in t)
ck("NSLog 格式串含 nGlyph", "nGlyph=%d" in t)

# ============================================================
# 3. 只读访问器 —— cachedLayout 是 private, 不加就读不到, D1 无法验证
# ============================================================
ck("访问器 attV46CachedTotalH 存在", "var attV46CachedTotalH" in t)
ck("访问器 attV46CachedWidth 存在", "var attV46CachedWidth" in t)
# 必须无 setter: 结构上保证只读, 且不给"从后门打开纯诊断防线"的机会
for name in ("attV46CachedTotalH", "attV46CachedWidth"):
    i = t.find(f"var {name}")
    line = t[t.rfind("\n", 0, i) + 1:t.find("\n", i)] if i >= 0 else ""
    ck(f"{name} 是只读 getter(有大括号)", "{" in line and "}" in line)
    ck(f"{name} 无 setter", "set" not in line)

# ============================================================
# 4. 位置: v46 必须在 v45 之后(同一闭包同帧, 三者并列对照)
# ============================================================
i45 = t.find("// [V45-TVHFIX]")
i46 = t.find(M46)
ck("找到 v45 段", i45 >= 0)
ck("找到 v46 段", i46 >= 0)
ck("v46 在 v45 之后 (v45 < v46)", (i45 >= 0 and i46 >= 0 and i45 < i46))

# v46 必须仍在 v44 之前(与 v45 同一插入点, 保持 v45->v44 的既有次序)
i44 = t.find("// [V44-TEXTFRAME] 见函数 docstring")
ck("找到 v44 段", i44 >= 0)
ck("v46 在 v44 之前 (v46 < v44)", (i46 >= 0 and i44 >= 0 and i46 < i44))

# ============================================================
# 5. ★纯诊断: 段内不得对已有状态赋值
#    局部计数器(_v46* / _V46Log)与可选绑定(guard let / if let)是收集
#    判据数据的必要步骤, 不是修法 —— 排除掉, 否则会逼着把 attNVI 这类
#    必需字段从诊断里删掉, 反而损失一个候选根因的判据。
# ============================================================
seg = ""
if i46 >= 0 and i44 >= 0 and i44 > i46:
    # 右边界用 V44 段头而非"第一个 }" —— v46 段内部有嵌套 do/闭包,
    # 按缩进找闭合会切错位置(v45 反向测试里就栽在"边界切到 NSLog(" 这类)。
    seg = t[i46:i44]
ck("v46 do 块可定位", bool(seg))
seg_code = strip_noise(seg) if seg else ""
import re as _re
assign_hits = []
for ln in seg_code.splitlines():
    s = ln.strip()
    if not s:
        continue
    if s.startswith(("let ", "var ", "struct ")):
        continue
    if "&+=" in s:
        continue
    if _re.match(r"^(guard|if|while)\s+(let|var)\b", s):
        continue
    m = _re.search(
        r"(?<![\w.\]\)])\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:\[[^\]]*\])?)\s*=(?!=)", s)
    if m and not s.startswith("=="):
        lhs = m.group(1)
        if not (lhs.startswith("_v46") or lhs.startswith("_V46Log")):
            assign_hits.append((lhs, s))
ck("★段内无对已有状态的赋值", not assign_hits)
for lhs, s in assign_hits:
    print(f"    ⚠️ 段内赋值: {lhs!r} <- {s[:70]!r}")

# ============================================================
# 6. ★硬禁危险调用: invalidate / 强制布局 / 缓存写入
#    这些是"修法"动作, 出现在诊断段里等于偷偷把 v47 的活干了。
# ============================================================
for danger in ["invalidateLayout", "invalidateDisplay", "invalidateIntrinsic",
               "invalidateSize", "ensureLayout", "invalidateCachedLayout",
               "cachedLayout =", "needsLayoutInvalidation =", "needsViewRebuild =",
               "textContainer.size =", ".frame =", "setNeedsDisplay",
               "computeLayout(", "contentGeneration &+="]:
    ck(f"★段内无危险调用 {danger!r}", danger not in seg)

# (注: 曾想加一条"v46 之后无 invalidate 族调用", 但文件后半部分本就有
#  invalidateCachedLayoutForWidthChange 的声明与源码固有调用, 与 v46 无关,
#  必然误报。危险调用的拦截已由上面"段内"判据覆盖 —— v46 的全部代码就在
#  seg 里, 不在 seg 里的调用不是 v46 干的。)

# ============================================================
# 7. 加法, 不是替换 —— v44 诊断与 v45 修法必须都还在
# ============================================================
ck("保留 v44 诊断", 'NSLog("[V44-TEXTFRAME]' in t)
ck("保留 v45 修法", 'NSLog("[V45-TVHFIX]' in t)
ck("保留 v41 补高", 'NSLog("[V41-KVOHEIGHT]' in t)

# ============================================================
# 8. 节流 0.5s —— 与 V41-KVOPRE/V44/V45 同周期, 否则主线程日志会被打爆
# ============================================================
ck("0.5s 节流", "_v46Now - _V46Log.last > 0.5" in t)

# ============================================================
# 9. 全文花括号平衡 —— v45 反向测试 F1 实跑教训:
#    在别处插一个永不闭合的函数, 前 7 条判据全过、编译才炸。
# ============================================================
depth = 0
low = 0
for c in CODE:
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth < low:
            low = depth
ck("全文花括号平衡", depth == 0)
ck("花括号中途不变负", low >= 0)
if depth != 0:
    print(f"    ⚠️ 花括号净 {depth:+d}")
if low < 0:
    print(f"    ⚠️ 花括号中途变负 {low}")

# ============================================================
# 10. 标记计数放最后当总兜底(判据被稀释的教训, 同 v44)
# ============================================================
ck("V46-ATTACH 标记唯一", t.count('NSLog("[V46-ATTACH]') == 1)

# ============================================================
print(f"\nv46 正向验证: {ok} 通过, {len(bad)} 失败")
if bad:
    for b in bad:
        print("  ❌", b)
    sys.exit(1)
print("✅ 全部通过")
