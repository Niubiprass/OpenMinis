#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v44 正向验证: 抓"V44-TEXTFRAME 纯诊断缺失"与"诊断里混入写行为"两类回归。

用法: python3 verify_v44.py [产物根目录]
默认 /tmp/ci_v44

背景 (minis-2026-10-03 12.log, v43 装机实测):
  v41/v42/v43 三轮都在猜"高度够不够", 三轮全猜错。这一版**只测不改**, 用一条
  `V44-TEXTFRAME` 同时打三个假设:

    时刻             len   hDirty(390)  hNet(358)      dh
    18:06:12         1583        1960.7      1769.3   -191.3   <- 净宽反而更矮
    18:17:11          828     1384.3      1474.0     +89.7   <- 净宽更高

  143 条 V43-WIDTH 里 29 条 dh != 0 且**会正负翻转** —— v43-A 假设"两条测量链同源"
  则 dh 必恒为 0。符号翻转说明还有第三条测量链, 而 v43 猜的是"两条链同源"。
  同时 V41 补高循环跑到 n=138 永不收敛(debt 恒 156.3 / 447.7):
      18:17:11.252 V41-KVOHEIGHT fixed svH=1026.3 -> needH=1474.0 debt=447.7
      18:17:12.075 V41-KVOPRE    sv=(16,247.3,358.0,1026.3) needH=0.0  <- 又被写回

  而 V41-KVOPRE 抓的 `obj` 是被观察的 **superview**, 画字的是 UITextView 自己。
  补 superview 完全可能补不到画字的那个 —— 这就是三个假设的由来。

本脚本最关键的一条是 `V44 纯诊断`: 块内出现任何写行为, 这一版的结论就废了
(装机后无法区分"真修好了"和"看着好了")。宁可让 CI 拦下。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v44"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

N = "\n"
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

# ================= 一、诊断段存在性与三个判据字段 =================
MK = "// [V44-TEXTFRAME] 见函数 docstring"
ck("存在 V44-TEXTFRAME 标记", "V44-TEXTFRAME" in t)
ck("诊断段锚点存在", MK in t)

# 三个假设各自的判据字段, 一个都不能少 —— 少一个就有一条假设永远无法验证
ck("判据A tvH = UITextView 自身高", "_tfdTvH = self.frame.height" in t)
ck("判据B svAfter = 补高后立刻回读", "_tfdSvAfter = obj.frame.height" in t)
ck("判据C usedH = TextKit 真实占用",
   "_tfdUsed = self.layoutManager.usedRect(" in t and
   "self.textContainer).height" in t)
ck("V44-TEXTFRAME NSLog 唯一", t.count('NSLog("[V44-TEXTFRAME]') == 1)

# 诊断必须把三个判据都打出来, 否则装机后没法对照
for f in ("tvH=%.1f", "svAfter=%.1f", "usedH=%.1f", "needH=%.1f"):
    ck(f"日志格式含 {f}", f in t)
# usedH 只有一个, 不对照 needH 就看不出 attachment 有没有进排版
ck("日志打出长度 len 便于对齐 V41-KVOPRE", "len=%d" in t)
ck("节流计数器 n 存在", "n=%u" in t and "_TfdLog.n &+= 1" in t)

# ================= 二、结构: do { } / 位置 / 窗口 =================
# 【为什么必须用 do { }】裸 { } 会被吸成 trailing closure —— v42 首次推送就栽在
# 这, 当时正向 45/45 + 反向 31/31 + 花括号 depth=0 全绿, CI 照样 8 个 error。
_DO = N + "            do {"
ck("诊断用 do { }(裸块会被吸成 trailing closure)", _DO in t)

# ★位置必须在**补高之后**: 在补高前打, svAfter 与 svH 是同一个值, 假设 B
#   (补高被 ios15KvoFixing 重入挡掉)永远无法证伪。v43-B 第一版就栽在"插在写入
#   之前"上, 同一个坑不能再踩第二次。
i_need = t.find("self.ios15LastNeededH = _v42Need")
i_hit = t.find('NSLog("[V41-KVOHEIGHT]')
i_tfd = t.find(MK)
i_post = t.find("// [V41-KVOPOST]")
ck("诊断落在补高之后(否则 svAfter 无意义)",
   i_need >= 0 and i_hit > i_need and i_tfd > i_hit)
ck("诊断落在 [V41-KVOPOST] 之前(KVO 闭包内)", i_post > i_tfd > 0)

# 切片取诊断块本体: 从 do { 到同缩进的闭合
seg = ""
if _DO in t and i_tfd >= 0:
    _s = t.index(_DO, i_tfd)
    try:
        _e = t.index(N + "            }", _s)
        seg = t[_s:_e]
    except ValueError:
        seg = ""
ck("诊断块可被完整切出(do 块闭合存在)", bool(seg))

# ================= 三、★纯诊断: 块内零写行为 =================
# 【本断言存在的理由】v44 的唯一价值是归因。诊断里顺手补个 textView.frame.height,
# 装机后就没法区分"真的修好了"还是"只是看着好了" —— 这一版的结论全部作废。
# 所以行为改动必须另起一版, 由 verify/reverse 单独盯。
for w in ("self.frame =", "obj.frame =", "textContainer.size =",
          "self.ios15LastNeededH =", "self.ios15LatchedNeedH =",
          "self.invalidate", "setNeedsLayout", "layoutIfNeeded"):
    ck(f"★纯诊断: 块内无写操作 {w}", w not in seg)

# 节流必须与 V41-KVOPRE / V43-WIDTH 同为 0.5s, 三条日志才能并列对照
ck("节流周期 0.5s(与 V41-KVOPRE/V43-WIDTH 同周期)",
   "_tfdNow - _TfdLog.last > 0.5" in t)

# ================= 四、v41/v42/v43 语义未被破坏 =================
ck("v42 闩锁四字段仍存在",
   all(k in t for k in ("var ios15LatchedNeedH: CGFloat = 0",
                        "var ios15LatchLen: Int = 0",
                        "var ios15LatchW: CGFloat = -1",
                        "var ios15LatchHash: Int = 0")))
ck("v42 闩锁仍禁止取 max", "max(ios15LatchedNeedH" not in t)
ck("v42 节流仍在(0.12)", "_v42Now - _v42SelfLast < 0.12" in t)
ck("v41 补齐仍用 _v42Need", "_hFix.size.height = _v42Need" in t)
ck("v41 补高写入仍在", "_hFix.size.height = _v42Need" in t)
ck("v43-A 净宽公式仍在", "let _v43NetW = max(200.0, cvW - 32)" in t)
ck("v43-A 自测仍用净宽", "let _v42TCW = _v43NetW" in t)
ck("V43-WIDTH 诊断仍在", 'NSLog("[V43-WIDTH]' in t)
ck("V41-KVOPRE 诊断仍在", "V41-KVOPRE" in t)
ck("V41-DEBT 诊断仍在", "V41-DEBT" in t)

# ================= 五、Swift 编译防御 =================
# v42 首次推送的教训: 静态检查全漏, 只有 swiftc 抓得到。这里继续盯。
_g = t.find("// [V42-GATE]")
if _g >= 0:
    _gseg = t[_g:_g + 2000]
    ck("GATE 块未被改成裸 { }", N + "            {" not in _gseg)
    ck("GATE 内仍用 self.findCollectionView()", "self.findCollectionView()" in t)
else:
    ck("V42-GATE 标记仍在", False)

# CACurrentMediaTime 需要 QuartzCore; 用 layoutManager.usedRect 需要 available
ck("用了 CACurrentMediaTime", "CACurrentMediaTime()" in t)
ck("节流状态放在局部 struct 里(闭包内静态存储)",
   "struct _TfdLog { static var last: CFTimeInterval = 0" in t)

# 花括号平衡(词法扫描, 正确跳过注释与字符串)
depth = mind = 0
i = 0
n = len(t)
state = None
while i < n:
    c = t[i]
    nxt = t[i + 1] if i + 1 < n else ""
    if state is None:
        if c == "/" and nxt == "/":
            state = "line"; i += 2; continue
        if c == "/" and nxt == "*":
            state = "block"; i += 2; continue
        if c == '"':
            state = "str"; i += 1; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            mind = min(mind, depth)
        i += 1
    elif state == "line":
        if c == "\n":
            state = None
        i += 1
    elif state == "block":
        if c == "*" and nxt == "/":
            state = None; i += 2
        else:
            i += 1
    else:
        if c == "\\":
            i += 2
        elif c == '"':
            state = None; i += 1
        else:
            i += 1
ck(f"花括号平衡 (final={depth}, min={mind})", depth == 0 and mind == 0)

print(f"产物检查: {ok}/{ok + len(bad)} 通过")
if bad:
    print("\n失败:")
    for b in bad:
        print(f"  ✗ {b}")
    sys.exit(1)
print("✅ v44 纯诊断 V44-TEXTFRAME 就位 (三判据齐全 / 位置在补高后 / 块内零写操作)")
