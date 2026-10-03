#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v48 正向验证 —— 排版宽钉回目标宽。

log17 实测归因（决定性证据，零例外）：

                 tcW=390   tcW=358   gap最小  gap最大   gap<1 的条数
  log16 (v46)      69         8       8.1     75.2          0
  log17 (v47)      48         8       8.0    117.5          0

两点结论：

1) `tcW` 与 `tvH - usedH` **完全同构**：
     tcW=358.0 → gap 恒 8.0~8.3（= textContainerInset 上下之和，正常态）
     tcW=390.0 → gap 30.5（len=229）/ 117.5（len=839，连续 26 条一模一样）
   len=229 那组最直接：同一段文字，tcW=358 时 gap=8.1，tcW=390 时 gap=30.5。

2) tcW=390 的帧 69→48，说明 **v47 的重排确实触发了**，但没根治 ——
   因为 v47 只调 `invalidateLayout`、**不写 `textContainer.size.width`**，
   而 TextKit 的 `ensureLayout` 只在当前容器宽下重排。容器还是 390 时，
   重排出来的仍是 390 宽的行数，与按 358 算的 `_needH` 依旧不同源。

v48 修法：碎片与目标宽不一致时，连容器宽一起钉回 `_realW2`。

用法：verify_v48.py [产物根目录]
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v48run"
SWIFT = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

if not os.path.exists(SWIFT):
    print("产物不存在:", SWIFT)
    sys.exit(1)

t = open(SWIFT, encoding="utf-8").read()
_pf = []


def ck(name, cond, extra=""):
    _pf.append(cond)
    print("  %s %s%s" % ("OK " if cond else "XX ", name,
                         ("  << " + extra) if (extra and not cond) else ""))


print("v48 正向验证（根=%s）" % ROOT)
print()

# ============ 1. 注入点存在 ============
print("--- 1. 注入点 ---")
i_pin = t.find("// [V48-PIN]")
ck("V48-PIN 注入点存在", i_pin > 0)
ck("V48-PIN 只出现一次", t.count("// [V48-PIN]") == 1,
   "count=%d" % t.count("// [V48-PIN]"))

# ============ 2. 段边界 ============
print("--- 2. 段边界（判据范围只到本版新增块）---")
# 段右边界必须选在**sabotage 改不到的地方**。
# 【踩坑 —— 这条判据曾形同虚设, 15/20 条 sabotage 全漏放】第一版用
# t.find("\n            }", i_pin) 当右边界。但 v48 的 if 块只有一层,
# 那个闭合花括号恰好紧跟在唯一写入行之后 —— 段切片在写入行处就截断了,
# 反向测试往写入行**后面**追加的 frame.size.width / bounds.size.width /
# 高度写入全部落在段外, 一条都扫不到。于是"写入白名单"与"禁高度/几何"
# 两组判据同时失效, 却看起来全绿。
# 教训: 锚点选在被测代码自己的闭合花括号上, 等于把判据的视野关在
# 被测对象里 —— 只能证明"第一行没问题", 证明不了"后面几行没问题"。
# 与 v47 的"二次切割"同源: 都在用代码自身结构当边界。
i_end = t.find("// [IOS15-FIX-RELC v28]", i_pin)
ck("段尾稳定锚点存在(// [IOS15-FIX-RELC v28])", i_end > i_pin > 0,
   "i_pin=%d i_end=%d" % (i_pin, i_end))
blk = t[i_pin:i_end]
ck("段切片非空且不含 ensureLayout 回写", len(blk) > 0 and "ios15LastLaidOutW" not in blk,
   "len=%d" % len(blk))

# ============ 3. 剥注释后做写入白名单 ============
print("--- 3. ★写入白名单（只许 textContainer.size.width = _realW2）---")
code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", blk, flags=re.S))


def _lhs(line):
    m = re.match(r"\s*([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", line)
    return m.group(1) if m else None


writes = []
for line in code.split("\n"):
    tgt = _lhs(line)
    if tgt:
        writes.append((tgt, line.strip()))

ck("段内确有 1 处写入（不多不少）", len(writes) == 1,
   "writes=%s" % [w[0] for w in writes])
for tgt, line in writes:
    ck("写入目标是 textContainer.size.width", tgt == "textContainer.size.width",
       "实际=%s" % tgt)
    m_val = re.search(r"=\s*([^=].*?)\s*$", line)
    ck("写入值恰为 _realW2（不引入第三方宽度）",
       bool(m_val) and m_val.group(1).strip() == "_realW2",
       "实际=%s" % (m_val.group(1).strip() if m_val else "<无>"))

# ============ 4. ★禁高度/几何（防"整体缩小"与推翻 v45）============
print("--- 4. ★禁高度与几何 ---")
FORBID = ("height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
          "ios15LastNeededH", "frame", "bounds", "origin", "_hf", "_needH",
          "_needH39", "sizeToFit", "ios15LastSaneSVFrame")
bad = [tgt for tgt, _ in writes
       if tgt in FORBID or tgt.split(".")[-1] in FORBID]
ck("段内零高度/几何写入", not bad, "违规=%s" % bad)
# 段内代码里不该出现 frame./bounds./origin 的赋值
ck("段内无 frame/bounds/origin 赋值",
   not re.search(r"\b(frame|bounds|origin)\b\s*(?:\.|\w)*\s*=", code))

# ============ 5. 幂等门（防与 SwiftUI 竞争）============
print("--- 5. ★幂等门（抢宽翻车防线）---")
ck("写入前有 abs(tcW-_realW2)>0.5 把门",
   "abs(textContainer.size.width - _realW2) > 0.5" in blk)
ck("复用 v47 的 _ios15WRegrabbed（不另起抢宽时机）",
   "_ios15WRegrabbed" in blk)
ck("不是常驻钳宽（写入被 if 包住而非裸执行）",
   re.search(r"if\s+_ios15WRegrabbed\s*,\s*abs\(textContainer", blk) is not None
   or re.search(r"if\s+abs\(textContainer", blk) is not None)

# ============ 6. 位置：v48 在 v47 判据之后 ============
print("--- 6. 位置顺序 ---")
i47_chk = t.find("if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {")
i47_set = t.find("self.ios15LastLaidOutW = _realW2")
i47_decl = t.find("var ios15LastLaidOutW: CGFloat?")
ck("v48 在 v47 判据之后", min(i47_chk, i_pin) > 0 and i_pin > i47_chk,
   "v47chk=%d v48=%d" % (i47_chk, i_pin))
ck("v48 在 v47 回写之前或之后均可，但 v47 回写仍在", i47_set > 0)
ck("v47 属性声明仍在", i47_decl > 0)

# ============ 7. 加法保留 ============
print("--- 7. 加法保留（v48 不能吃掉任何前版）---")
for tag, label, want in (("// [V47-REWRAP]", "v47 代码段标记", 2),
                         ("/// [V47-WSTATE]", "v47 声明标记", 1),
                         ("// [V42-LATCH-SET]", "v42 闩锁", 1)):
    # V47-REWRAP 天然是 2 处（v47 有判据处 + ensureLayout 回写处两个注入点）
    ck("%s 保留且计数=%d" % (label, want), t.count(tag) == want,
       "count=%d" % t.count(tag))
for tag in ("[V44-TEXTFRAME]", "[V45-TVHFIX]", "[V46-ATTACH]"):
    ck("诊断日志 %s 保留" % tag, ('NSLog("' + tag) in t)

# ============ 8. 净深度 0（段自身括号配平）============
print("--- 8. 结构：段自身括号配平 ---")
depth = 0
for ch in code:
    if ch in "{([":
        depth += 1
    elif ch in "})]":
        depth -= 1
# 只数**花括号**, 不数圆括号/方括号 —— 段内注释里成对的`()`
# （如 "在 358 时" 这类括号、以及 `(t.contentW == 0.0 && tcH == 100000.0)` )
# 会被算进深度, 但它们与"段结构是否配平"无关。
# 段右边界是下游的 v28 标记, 段内**包含** v48 那个 if 的闭合花括号, 故应为 0。
# 判据必须真的消费算出来的值 —— 写成 depth >= 0 会恒为真, 变成废判据
# （与 v45 反向测试 F1、v47 第 9 组同一个教训）。
_brace = code.count("{") - code.count("}")
ck("段花括号配平（段内含 v48 if 的闭合）", _brace == 0, "brace=%d" % _brace)

# ============ 9. Swift 符号存在性 ============
print("--- 9. Swift 符号存在性 ---")
for n, c in (("abs", "abs" in t),
             ("_realW2 是同作用域局部量", "let _realW2 = _realW" in t),
             ("textContainer 可访问", "textContainer.size.width" in t),
             ("CGFloat 可用", "CGFloat" in t)):
    ck(n, c)

print()
ok = sum(1 for x in _pf if x)
bad_n = len(_pf) - ok
print("v48 正向验证: %d 通过, %d 失败" % (ok, bad_n))
print("OK" if bad_n == 0 else "XX 有失败项")
sys.exit(0 if bad_n == 0 else 1)
