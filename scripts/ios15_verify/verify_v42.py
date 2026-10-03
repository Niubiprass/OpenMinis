#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v42 正向验证器: 在真实产物上逐条核对 v42 注入的结构。

用法:
    python3 verify_v42.py [SelectableMarkdownView.swift 的路径]

判据纪律(见 verify_v41 的踩坑记录):
  - 标记计数锚`NSLog("[MARK]` 而不是裸字符串 —— 注释里出现的标记不能算。
  - 位置判据锚**真正执行的赋值/条件语句**, 不锚注释, 不锚 docstring 同名文本。
"""
import io
import os
import sys

DEFAULT = "/tmp/ci_v42b/src/ios/Views/Chat/SelectableMarkdownView.swift"
PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT

t = io.open(PATH, encoding="utf-8").read()
N = chr(10)

CHECKS = []


def ck(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


# ---------- 1. 四条诊断标记各恰好一次(锚 NSLog) ----------
for mk in ("V42-GATE", "V42-LATCH", "V42-THROTTLE", "V42-MISS"):
    n = t.count('NSLog("[' + mk + ']')
    ck(f"标记 {mk} 恰好 1 处", n == 1, f"实际 {n}")

# v41 的五条诊断不能被 v42 破坏
for mk in ("V41-KVOPRE", "V41-KVOHEIGHT", "V41-KVOPOST", "V41-KVOFIXH", "V41-DEBT"):
    n = t.count('NSLog("[' + mk + ']')
    ck(f"v41 标记 {mk} 仍在", n == 1, f"实际 {n}")

# ---------- 2. 闩锁声明: 四个字段各恰好一次 ----------
ck("闩锁 ios15LatchedNeedH 声明唯一",
   t.count("var ios15LatchedNeedH: CGFloat = 0") == 1)
ck("闩锁键 Len 声明唯一", t.count("var ios15LatchLen: Int = 0") == 1)
ck("闩锁键 W 声明唯一", t.count("var ios15LatchW: CGFloat = -1") == 1)
ck("闩锁键 Hash 声明唯一", t.count("var ios15LatchHash: Int = 0") == 1)

# ---------- 3. 闩锁**禁止取 max**(会造大片空白) ----------
ck("闩锁未取 max(无 _needH > ios15LatchedNeedH)",
   "if _needH > ios15LatchedNeedH" not in t)
ck("闩锁是直接覆盖赋值(带 self. 前缀)",
   N + "            self.ios15LatchedNeedH = _needH" in t)

# ---------- 4. 赋值点: 闩锁刷新必须在 needH 赋值之后, 且三键齐刷 ----------
i_set = t.index("ios15LastNeededH = _needH")
i_latch = t.index(N + "            self.ios15LatchedNeedH = _needH")
ck("闩锁刷新在 needH 赋值之后", i_latch > i_set, f"{i_latch} vs {i_set}")

i_len = t.index(N + "            self.ios15LatchLen = self.textStorage.length")
i_w = t.index(N + "            self.ios15LatchW = self.textContainer.size.width")
i_hash = t.index(N + "            self.ios15LatchHash = self.textStorage.mutableString.hash")
ck("赋值点刷新 Len 键", i_len > i_set)
ck("赋值点刷新 W 键", i_w > i_set)
ck("赋值点刷新 Hash 键", i_hash > i_set)

# ---------- 5. GATE 诊断必须在三道门入口 if 之前 ----------
i_g = t.index('NSLog("[V42-GATE]')
i_if = t.index("if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {")
ck("V42-GATE 在三道门入口之前", i_g < i_if, f"{i_g} vs {i_if}")
# 且 GATE 必须真的调了 findCollectionView(否则 cvNil/cvW 是假值)
i_gcv = t.index("let _gCV = self.findCollectionView()")
ck("V42-GATE 自己调 self.findCollectionView", i_gcv < i_g)

# ---------- 6. KVO 键判定: 三个键必须都在命中条件里 ----------
i_kvo = t.index("// [V42-FALLBACK] 闩锁(带键缓存) + 兜底自测")
seg = t[i_kvo:i_kvo + 4000]
ck("KVO 键判定含 Len",
   "self.ios15LatchLen == _v42Len" in seg)
ck("KVO 键判定含 W(带容差)",
   "abs(self.ios15LatchW - _v42TCW) < 0.5" in seg)
ck("KVO 键判定含 Hash",
   "self.ios15LatchHash == self.textStorage.mutableString.hash" in seg)
ck("KVO 键判定在命中分支里(不是赋值点)",
   seg.index("self.ios15LatchLen == _v42Len")
   < seg.index('_v42Need = self.ios15LatchedNeedH'))

# ---------- 7. 自测必须被 120ms 节流(否则加重卡顿) ----------
ck("自测有 120ms 节流条件", "_v42Now - _v42SelfLast < 0.12" in seg)
ck("节流基准走 static 托管(跨帧存活)",
   "struct _SelfLast { static var t: CFTimeInterval = 0 }" in seg
   and "let _v42SelfLast = _SelfLast.t" in seg)
ck("自测成功后刷新节流时刻", "_SelfLast.t = _v42Now" in seg)
ck("节流分支沿用旧高度而不是放弃",
   seg.count("_v42Need = self.ios15LatchedNeedH") == 2,
   f"实际 {seg.count('_v42Need = self.ios15LatchedNeedH')}")

# ---------- 8. 自测路径必须绕过三道门(用 textContainer 宽) ----------
ck("自测用 textContainer.size.width(排版实际宽)",
   "let _v42TCW = self.textContainer.size.width" in seg)
ck("自测调 sizeThatFits", "self.sizeThatFits(" in seg)
ck("自测传入 greatestFiniteMagnitude(测全高)",
   "height: .greatestFiniteMagnitude)).height" in seg)

# ---------- 9. 所有高度补齐路径统一用 _v42Need ----------
i_asg = t.index(N + "                _hFix.size.height = _v42Need")
i_poll = t.index("let _hDebt = _v42Need > 1")
ck("补齐在 polluted 判据之前", i_asg < i_poll, f"{i_asg} vs {i_poll}")
ck("_hDebt 用 _v42Need", "let _hDebt = _v42Need > 1 && f.size.height + 0.5 < _v42Need" in t)
ck("polluted 含 _hDebt",
   "let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt" in t)
ck("兜底补高用 _v42Need",
   "if _v42Need > 1, fix.size.height + 0.5 < _v42Need {" in t)
ck("兜底补高赋值用 _v42Need", "fix.size.height = _v42Need" in t)
ck("KVOPOST 用 _v42Need", "if _v42Need > 1, f.size.height + 0.5 >= _v42Need {" in t)
# 补齐段内不得再直接读 self.ios15LastNeededH
ck("补齐段已无裸读 ios15LastNeededH",
   "f.size.height + 0.5 < self.ios15LastNeededH" not in t)

# ---------- 10. Swift 正确性: 补齐必须先于使用, var 不是 let ----------
i_varf = t.index(N + "            var f = obj.frame")
ck("KVO 用 var f(补齐要交棒)", i_varf >= 0)
ck("_v42Need 声明为 var(分支里要赋值)",
   "var _v42Need = CGFloat(0)" in seg)
ck("_v42Need 初值用 CGFloat(0) 而非 0(Int 会类型冲突)",
   "var _v42Need = CGFloat(0)" in seg and "var _v42Need = 0" not in seg)

# ---------- 11. 重入保护仍在 ----------
ck("ios15KvoFixing 声明保留", t.count("var ios15KvoFixing = false") == 1)
# 注意: `self.ios15KvoFixing = false` 的匹配数会包含声明行 `var ios15KvoFixing = false`
# (子串匹配), 所以这里用"带 self. 前缀的置位/复位"做配对判据。
n_true = t.count("self.ios15KvoFixing = true")
n_false = t.count("self.ios15KvoFixing = false")
ck("ios15KvoFixing 置位/复位成对(补齐段 + 兜底段各一组)",
   n_true == 2 and n_false == 2, f"true={n_true} false={n_false}")
ck("KVO 开头仍有重入早退", "guard let self = self, !self.ios15KvoFixing else { return }" in t)

# ---------- 12. Swift 编译防御: trailing closure 坑(v42 首次推送的真实失败原因) ----------
# 【这条是补交的】v42 第一次推送时, V42-GATE 写成了裸 `{ ... }`, 被 Swift 吸成
# 上一个表达式的 trailing closure, 8 个编译错误:
#   - closure expression is unused
#   - call to method 'findCollectionView' in closure requires explicit use of 'self'
#   - reference to property 'xxx' in closure requires explicit use of 'self'
# 花括号平衡检查查不出来(do{} 与 {} 都是配平的), 正向/反向验证也全绿 —— 只有
# 真正的 swiftc 能抓到。所以判据必须直接盯源码形态。
i_gc = t.index("// [V42-GATE] 测量入口三道门的实际取值")
i_gif = t.index("if !isScrollEnabled, let rCv2 = findCollectionView()", i_gc)
seg_gc = t[i_gc:i_gif]
ck("V42-GATE 用 do { } 而非裸 { }", N + "            do {" in seg_gc)
ck("V42-GATE 未用裸 { } 起头", N + "            {" not in seg_gc)
ck("GATE 内用 self.findCollectionView()", "self.findCollectionView()" in seg_gc)
ck("GATE 内 isScrollEnabled 带 self.",
   "self.isScrollEnabled ? 0 : 1" in seg_gc)
for k in ("ios15LatchedNeedH", "ios15LatchLen", "ios15LatchW", "ios15LastNeededH"):
    ck(f"GATE 内 {k} 带 self. 前缀", "self." + k in seg_gc)

# 赋值点同样必须带 self.(与 GATE 同一段落, 同一防御口径)
i_ls = t.index("// [V42-LATCH-SET]")
i_lseg = t[i_ls:t.index(chr(10) + "            }", i_ls) if False else i_ls + 700]
for k in ("ios15LatchedNeedH = _needH",
          "ios15LatchLen = self.textStorage.length",
          "ios15LatchW = self.textContainer.size.width",
          "ios15LatchHash = self.textStorage.mutableString.hash"):
    ck(f"赋值点带 self.: {k}", ("self." + k) in i_lseg)

# ---------- 输出 ----------
ok = sum(1 for _, c, _ in CHECKS if c)
print(f"=== v42 正向验证: {PATH} ===")
for name, c, detail in CHECKS:
    if not c:
        print(f"  FAIL  {name}   {detail}")
print(f"结果: {ok}/{len(CHECKS)} 通过")
sys.exit(0 if ok == len(CHECKS) else 1)
