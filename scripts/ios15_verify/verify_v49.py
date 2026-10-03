#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v49 正向验证 —— **纯诊断**探针: 钉死「谁把 tcW 推回 390」。

【log18 归因 —— v49 的立论基础, 首次打破 log17 的「tcW 与 gap 完全同构」】
                 条数   gap最小  gap最大
    tcW=358.0      10      8.1      8.5     ← 全部正常
    tcW=390.0      49      8.2     97.6     ← ★18 帧正常 + 31 帧残缺(混合!)
`len=122` 在 tcW=390 下 gap=8.2(**正常**) —— 前两版从未有过这个组合。
⇒ **v48 的钉宽确实生效了, 但只治好轻文本**; 重文本(len=1013, 含 1 个表格)
   仍残缺。

决定性对照(同构关系被打破的铁证):
    n=9  cachedW=357.0 tcW=358.0 tcH=2000.0 usedH=1727.6 gap=8.1  ✅
    n=10 cachedW=389.0 tcW=390.0 tcH=1727.7 usedH=1638.1 gap=97.6 ❌
`cachedW` 与 `tcW` **完全同构(35/36 零例外)** ⇒ 推宽者与 cachedW 同源。

逐毫秒铁证(00:07:42):
    .672 [V42-GATE]    cvW=390.0 latched=0.0 raw=0.0 storageLen=1013
         [V41-KVOPRE]  sv=(16,202.7,358.0,1377.7) needH=0.0 cvW=390.0
    .676 [V43-WIDTH]   dirtyW=390.0 netW=358.0 hDirty=1646.3 hNet=1735.7 dh=89.3
    .678 [V42-MISS]    selfMeasured needH=1735.7 **tcW=358.0**  ← 此刻排版是对的
         [V41-KVOHEIGHT] svH 1377.7→1735.7 debt=358.0
    .679 [V46-ATTACH]  usedH=1638.1 **tcW=390.0** cachedW=389.0 ← ★2ms 后被推回
         [V44-TEXTFRAME] tcW=390.0 usedH=1638.1
⇒ **1 毫秒内被推回**。而 v48 的钉宽写在 v18 段内(缩进 12, layoutSubviews 内),
  **早于**表格附件测量链跑完 ⇒ 纠偏追不上。
其它量化: debt=358.0 × 29 条; TextContainerGuard 熔断 219/220 次,
358x2000.0 被熔 109 次(2000 是 v25/v26 遗留的临时放开高度);
`RND tables>=1` 占 146 条里的 73 条 ⇒ 表格渲染是主触发路径。

【为什么纯诊断不盲修】候选写入者至少三个, 修法互相冲突:
    · V46 attachmentBounds 测量链 —— 放宽它动 v16 表格渲染
    · v37 probe 钳位链 —— 动它动那套 9 处泄漏防护
    · SwiftUI 自己的布局 pass —— 抢它是 v13/v34 闪屏翻车的老路
    · (D4) TextContainerGuard 熔断那条 —— 治 fillLayoutHole 11918ms 卡死的
先探针把「谁最后写的 tcW、值从哪来」打出来, 装机一次定位到**行**。

【探针设计】两处构成**同帧差分**:
    v18 段末尾(v48 钉宽**之后**, 记 v18W + v18Tick)
    v41 KVO 抢帧器(记 kvoW + kvoTick + 来源指纹 cvW/laidW/fragW/tcH)
同 tick 内读到不同值 ⇒ 中间有人写过; 跨 tick ⇒ SwiftUI pass 之间写的。

用法: verify_v49.py [产物根目录 或 swift 文件]
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
if os.path.isfile(ROOT):
    SWIFT = ROOT
else:
    SWIFT = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

if not os.path.exists(SWIFT):
    print("产物不存在:", SWIFT)
    sys.exit(1)

t = open(SWIFT, encoding="utf-8").read()
_pf = []


def ck(name, cond, extra=""):
    _pf.append(bool(cond))
    print("  %s %-58s %s" % ("✅" if cond else "❌", name[:58], extra))
    return bool(cond)


def seg(a, b):
    i = t.find(a)
    if i < 0:
        return ""
    j = t.find(b, i)
    return t[i:j] if j > i else ""


def code_of(s):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", s, flags=re.S))


V18, V18E = "// [V49-WWRITER-V18]", "// [V49-WWRITER-V18-END]"
KVO, KVOE = "// [V49-WWRITER-KVO]", "// [V49-WWRITER-KVO-END]"

print("=== 1. 标记在位 ===")
ck("v18 侧探针标记 1 处", t.count(V18) == 1, "实为 %d" % t.count(V18))
ck("v18 侧 END 标记 1 处", t.count(V18E) == 1, "实为 %d" % t.count(V18E))
ck("KVO 侧探针标记 1 处", t.count(KVO) == 1, "实为 %d" % t.count(KVO))
ck("KVO 侧 END 标记 1 处", t.count(KVOE) == 1, "实为 %d" % t.count(KVOE))
ck("类型级 WSTATE 标记 1 处", t.count("/// [V49-WSTATE]") == 1,
   "实为 %d" % t.count("/// [V49-WSTATE]"))
ck("V49-WWRITER 日志标记 1 处",
   t.count('NSLog("[V49-WWRITER]') == 1,
   "实为 %d" % t.count('NSLog("[V49-WWRITER]'))

s1, s2 = seg(V18, V18E), seg(KVO, KVOE)
ck("两段切片非空", bool(s1) and bool(s2),
   "seg1=%d seg2=%d 字符" % (len(s1), len(s2)))

print("=== 2. 探针位置: v18 侧紧邻 v48 钉宽之后 ===")
PIN = "// [V48-PIN]"
i_pin, i_v18 = t.find(PIN), t.find(V18)
ck("V48-PIN 存在", i_pin >= 0)
ck("v18 探针在 V48-PIN 之后", i_pin >= 0 and i_v18 > i_pin,
   "pin@%d probe@%d" % (i_pin, i_v18))
# ★以探针为起点往前找最近的 _realW2 写入 —— 必然是 v48 钉宽行,
#   v18 那处远在几千行之外。这样判据与绝对行号无关(三次错位教训)。
WRITE = "textContainer.size.width = _realW2"
_up = t.rfind(WRITE, 0, i_v18) if i_v18 > 0 else -1
ck("探针上游最近的 _realW2 写入存在", _up >= 0, "@%d" % _up)
if _up >= 0:
    _c = re.sub(r"\s+", "", code_of(t[_up:i_v18]))
    _e = re.sub(r"\s+", "", WRITE + "}")
    ck("钉宽行与探针之间只有闭合花括号", _c == _e,
       "得到 %r" % _c[:56])

print("=== 3. 探针状态声明 ===")
for k in ("var ios15V18W: CGFloat = -1",
          "var ios15V41CvW: CGFloat = -1",
          "var ios15V46LaidOutW: CGFloat = -1"):
    ck("属性 %s" % k.split(":")[0].replace("var ", ""), k in t)
ck("_V49W 是类型级 struct(4 空格缩进)",
   "\n    struct _V49W {\n" in t,
   "★函数内局部 struct 跨函数不可见, 会编译失败")
ck("_V49W 声明恰为 1 处", len(re.findall(r"^\s*struct _V49W\b", t, re.M)) == 1)
for f in ("static var v18W: CGFloat = -1", "static var v18Tick: UInt = 0",
          "static var kvoW: CGFloat = -1", "static var kvoTick: UInt = 0",
          "static var tick: UInt = 0", "static var last: CFTimeInterval = 0",
          "static var n: UInt = 0"):
    ck("静态字段 %s" % f.replace("static var ", "").split(":")[0], f in t)

print("=== 4. ★段内零赋值(纯诊断的硬底线) ===")
OKW = {"last", "n", "v18W", "v18Tick", "kvoW", "kvoTick", "tick"}
bad = []
for c, nm in ((code_of(s1), "v18 侧"), (code_of(s2), "KVO 侧")):
    for ln in c.split("\n"):
        m = re.match(r"\s*(?:let\s+|var\s+)?([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", ln)
        if not m:
            continue
        last = m.group(1).split(".")[-1]
        if last in OKW or last.startswith("ios15V") or last.startswith("_v49"):
            continue
        bad.append("%s: %s" % (nm, ln.strip()[:48]))
ck("两段内无越界赋值", not bad, "; ".join(bad) or "只有记忆位")

print("=== 5. 段内零函数式写操作 ===")
for bad_f in ("invalidateLayout", "invalidateDisplay", "invalidateSize",
              "ensureLayout", "setNeedsLayout", "setNeedsDisplay",
              "setSize", "computeLayout", "invalidateCachedLayout"):
    ck("无 %s" % bad_f, bad_f not in code_of(s1) + code_of(s2))

print("=== 6. 日志字段齐全(装机后靠它定位) ===")
for f in ("v18W=", "kvoW=", "fragW=", "cvW=", "laidW=", "tcH=",
          "sameTick=", "dtick=", "usedH=", "needH=", "len=", "n="):
    ck("字段 %s" % f, f in s2)
# 格式符与实参配平 —— 不配平则装机即崩, 崩了就拿不到日志, 整版白测
_spec = len(re.findall(r"%[-0-9.]*[a-z]", s2))
ck("格式符数 == 实参数(不配平则装机崩)", _spec == 12, "格式符 %d" % _spec)

print("=== 7. 同帧差分机制 ===")
ck("v18 侧自增 tick", "_V49W.tick &+= 1" in code_of(s1))
ck("KVO 侧自增 tick", "_V49W.tick &+= 1" in code_of(s2))
ck("v18 侧记 v18Tick", "_V49W.v18Tick = _V49W.tick" in code_of(s1))
ck("KVO 侧记 kvoTick", "_V49W.kvoTick = _V49W.tick" in code_of(s2))
ck("同帧比较 sameTick", "_v49SameTick = _V49W.v18Tick == _V49W.kvoTick"
   in code_of(s2))
ck("跨 tick 差值 dtick", "kvoTick &- _V49W.v18Tick" in code_of(s2))

print("=== 8. 来源指纹都是真实读数 ===")
ck("cvW 来自 KVO 闭包局部量", "self.ios15V41CvW = cvW" in code_of(s2))
ck("laidW 来自 v47 的 ios15LastLaidOutW",
   "self.ios15V46LaidOutW = self.ios15LastLaidOutW ?? -1" in code_of(s2))
ck("v18 侧读的是 textContainer.size.width",
   "textContainer.size.width" in code_of(s1))
ck("不读 TableAttachment 的 attV46CachedWidth(跨类访问编译失败)",
   "attV46CachedWidth" not in code_of(s1) + code_of(s2))
ck("IOS 侧不读其它类成员(仅本类型属性)",
   "self.attV" not in code_of(s1) + code_of(s2))

print("=== 9. 节流与惰性读取(重文本防线) ===")
ck("0.5s 节流闸门存在", re.search(
   r"if\s+_v49Now\s*-\s*_V49W\.last\s*>\s*0\.5\s*\{", code_of(s2)))
_c2 = code_of(s2)
_m = re.search(r"if\s+_v49Now\s*-\s*_V49W\.last\s*>\s*0\.5\s*\{", _c2)
if _m:
    _g = _m.start()
    ck("usedRect 只在节流内读(惰性属性, 每帧读会触发排版)",
       all(x.start() > _g for x in re.finditer("usedRect", _c2)),
       "★重文本(len=1013)下每帧重排 = 新卡顿")
    ck("size.height 只在节流内读",
       all(x.start() > _g for x in
           re.finditer(re.escape("textContainer.size.height"), _c2)))
    ck("lineFragmentWidth 只在节流内读",
       all(x.start() > _g for x in
           re.finditer(re.escape("textContainer.lineFragmentWidth"), _c2)))
    ck("★不得出现 textContainer.bounds(NSTextContainer 无此属性, 编译失败)",
       "textContainer.bounds" not in t,
       "run#37139821021 就死在这一行上")
ck("节流周期与 V44/V45/V46/V41 同为 0.5s", "> 0.5 {" in _c2)

print("=== 10. 加法: v44~v48 一个都不能少 ===")
# ★期望值从**干净上游跑完的完整链产物**上数(v48 基线 581354 字节):
#   这些标记在产物里各出现多次 —— 段首 // [Vn-...] 与段内 NSLog("[Vn-...]
#   各一次; V46-ATTACH 另有第二处段, 共 4 次。
#   凭印象数判据就成了假故障(v48 那次就是这样差点改坏真修法)。
for tag, want in (("// [V48-PIN]", 1), ("// [V47-REWRAP]", 2),
                  ("/// [V47-WSTATE]", 1), ("[V44-TEXTFRAME]", 2),
                  ("[V45-TVHFIX]", 2), ("[V46-ATTACH]", 4)):
    ck("保留 %s = %d" % (tag, want), t.count(tag) == want,
       "实为 %d" % t.count(tag))
ck("v48 钉宽写入点仍在(V48-PIN 段内)",
   bool(re.search(r"textContainer\.size\.width\s*=\s*_realW2\b",
                  seg(PIN, "// [IOS15-FIX-RELC v28]"))))
ck("v47 ensureLayout 重排仍在",
   "layoutManager.ensureLayout(for: textContainer)" in t)

print()
ok = sum(1 for x in _pf if x)
bad_n = len(_pf) - ok
print("v49 正向验证: %d 通过, %d 失败" % (ok, bad_n))
print("OK" if bad_n == 0 else "XX 有失败项")
sys.exit(0 if bad_n == 0 else 1)
