#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v43 正向验证: 抓"两条测量链宽度不同源"与"涌入型重排未节流"两类回归。

用法: python3 verify_v43.py [产物根目录]
默认 /tmp/ci_v43

背景 (minis-2026-10-03 11.log):
  v42 让 KVO 抢帧器用 `textContainer.size.width` 自测, 但那一刻 tcW 是
  SwiftUI 刚写下的脏宽 390; 而 v18 在 layoutSubviews 里抢回净宽 358 并
  **用 358 测高**。同一段文本被量出两个高度:

      len=51    79.3  vs  79.3    差 0.0
      len=336  356.7  vs 440.7    差 84.0   <-- 裁掉整段
      len=533  857.7  vs 897.0    差 39.3

  短文本 0 差、长文本差整行 —— 精确对应用户说的"只有第一段卡字"。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v43"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
MLL = os.path.join(ROOT, "src/ios/Agent/MessageList/MessageListLayout.swift")

N = "\n"
ok = 0
bad = []


def ck(name, cond):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(name)


for p in (MD, MLL):
    if not os.path.exists(p):
        print(f"产物不存在: {p}")
        sys.exit(2)

t = open(MD, encoding="utf-8").read()
m = open(MLL, encoding="utf-8").read()

# ================= 一、宽度同源 (v43-A, 治字被裁) =================
ck("存在 V43-NETW 标记", "V43-NETW" in t)
ck("存在 V43-WIDTH 标记", "V43-WIDTH" in t)
ck("存在 V43-LATCHW 标记", "V43-LATCHW" in t)

# 核心: KVO 自测宽度必须来自净宽, 不能是 textContainer.size.width
ck("KVO 自测宽度改用 _v43NetW", "let _v42TCW = _v43NetW" in t)
ck("净宽公式与 v18 同源 max(200, cvW-32)",
   "let _v43NetW = max(200.0, cvW - 32)" in t)

# 净宽之后、节流之前不再拿 tcW 当测量宽
i_net = t.find("let _v43NetW = max(200.0, cvW - 32)")
i_throttle = t.find("// [V42-THROTTLE]", i_net if i_net >= 0 else 0)
if i_net < 0 or i_throttle < 0:
    ck("KVO 段结构完整(净宽声明 + 节流锚点)", False)
    seg = ""
else:
    ck("KVO 段结构完整(净宽声明 + 节流锚点)", True)
    seg = t[i_net:i_throttle]
ck("净宽之后、节流之前不再拿 tcW 当测量宽",
   "let _v42TCW = self.textContainer.size.width" not in seg)
ck("脏宽只用于诊断(命名 _v43DirtyW)",
   "let _v43DirtyW = self.textContainer.size.width" in seg)
# 脏宽只能出现在诊断里, 不能进 sizeThatFits 的宽度位置
ck("脏宽未进 sizeThatFits",
   "sizeThatFits(CGSize(width: _v43DirtyW" not in t)
ck("sizeThatFits 仍用 greatestFiniteMagnitude 高度",
   "height: .greatestFiniteMagnitude)).height" in seg)

# 闩锁键的宽度必须是净宽
ck("闩锁键存净宽 _realW2", "self.ios15LatchW = _realW2" in t)
ck("闩锁键不再存 tcW", "self.ios15LatchW = self.textContainer.size.width" not in t)

# 诊断必须能算出高度差
ck("V43-WIDTH 打 dirtyW/netW", 'NSLog("[V43-WIDTH] dirtyW=%.1f netW=%.1f' in t)
ck("V43-WIDTH 打高度差 dh", "dh=%.1f" in t)
ck("V43-WIDTH 各 1 处", t.count('NSLog("[V43-WIDTH]') == 1)

# ================= 二、涌入型重排节流 (v43-B, 治终端框卡画面) =================
# 【v43-B 位置在第二轮被纠正】第一版把节流插在 shouldInvalidateLayout 里
# `return shouldInvalidate` 之前、窗口内 return false, 那是**净亏**:
#   shouldInvalidateLayout 返回 false → UIKit 根本不调 invalidationContext
#   → `heightCache[index] = newHeight` 不执行 → prepare() 读旧高度 → 内容被裁。
# log11 里 `est` 恒等于上次 `pref`(29→159→303→408→518→612→742) 就是
# "每次都被采纳"的铁证。正确节流点是 invalidationContext 末尾那次**全表**
# invalidateLayout() —— 高度照旧每次落地, 只拦 O(items) 的全表重排。
ck("MLL 存在 V43-BURST 标记", "V43-BURST" in m)
ck("V43-BURST 标记 3 处(节流注释+日志+静态声明)", m.count("V43-BURST") == 3)
ck("节流窗口 0.25s", "_v43Now - _v43Prev < 0.25" in m)
ck("只拦大突增 delta > 100", "if abs(delta) > 100 {" in m)
ck("静态存储声明", "private static var v43BurstAt: [Int: CFTimeInterval] = [:]" in m)
ck("窗口基准写入", "Self.v43BurstAt[index] = _v43Now" in m)
ck("窗口内 return ctx(只重排本 cell, 不动全表)",
   m.count("full-reflow suppressed") == 1)
ck("陈旧条目清理", "Self.v43BurstAt.count > 64" in m)
ck("陈旧清理用 filter 而非 removeAll", "Self.v43BurstAt = Self.v43BurstAt.filter" in m)

# ★ 核心判据: 节流点必须晚于 heightCache 写入。
# 插到前面 == 拦掉高度落地 == 内容被裁, 比原症状更糟。这一条钉死了 v43-B 第一版的错。
_hc = m.find("heightCache[index] = newHeight")
_v43 = m.find("// [V43-BURST] 涌入型突增的**全表重排**节流")
ck("★节流点晚于 heightCache 写入(否则内容被裁)", _hc >= 0 and _v43 > _hc)

# ★ 节流必须落在 invalidationContext 的 reflow 触发条件**内部**, 且是唯一命中。
# 命中多处会把节流塞进 prepare()/applySnapshot() 的同名条件里。
_anchor = "if abs(delta) > 0.5, !isStreamingCell(index), !pendingFooterReflow {"
ck("reflow 锚点唯一(不多处盲插)", m.count(_anchor) == 1)
if _anchor in m and _v43 > 0:
    _a = m.index(_anchor)
    _b = m.index("pendingFooterReflow = true", _a)
    ck("节流嵌在 reflow 触发条件内(锚点之后、置位之前)", _a < _v43 < _b)
    ck("窗口内不置位 pendingFooterReflow(置位会另起一次全表重排)",
       "return ctx" in m[_v43:_b])
else:
    ck("节流嵌在 reflow 触发条件内(锚点之后、置位之前)", False)
    ck("窗口内不置位 pendingFooterReflow(置位会另起一次全表重排)", False)

# 不能动 V31-FLIPLOCK 的既有判据(那是治振荡的, 与本条正交)
# 【两代兼容】不能断言 V31-FLIPLOCK 一定存在: 本仓库的 CI 基线 MLL 是
# v30-A 之前的版本(1049 行, `return shouldInvalidate` 后面直接接
# `private static var invIdxCounts`), V31 是另一条线上的补丁, 不保证已应用。
# 判据只盯"v43 不许破坏它" —— 存在就验它没被动过, 不存在就算过。
_v31 = "if shouldInvalidate, !deferSelfSizing, heightCache[index] != nil, delta > 100 {"
if _v31 in m:
    ck("V31-FLIPLOCK 判据未被改动", True)
    ck("v31MaxH 声明仍在",
       "private static var v31MaxH: [Int: CGFloat] = [:]" in m)
else:
    ck("V31-FLIPLOCK 判据未被改动(本基线无此补丁, 跳过)", True)
    ck("v31MaxH 声明仍在(本基线无此补丁, 跳过)", True)

# v43 的静态存储声明在 reflowCount 之后(与既有存储区一致, 便于对照排查)
ck("v43BurstAt 声明在 reflowCount 之后",
   m.index("private static var v43BurstAt")
   > m.index("private static var reflowCount"))

# ================= 三、v42 语义未被破坏 =================
ck("v42 闩锁四字段仍存在",
   all(k in t for k in ("var ios15LatchedNeedH: CGFloat = 0",
                        "var ios15LatchLen: Int = 0",
                        "var ios15LatchW: CGFloat = -1",
                        "var ios15LatchHash: Int = 0")))
ck("v42 闩锁仍禁止取 max", "max(ios15LatchedNeedH" not in t)
ck("v42 节流仍在(0.12)", "_v42Now - _v42SelfLast < 0.12" in t)
ck("v42 GATE 仍用 do { }", N + "            do {" in t)
ck("v42 自测兜底仍用 _v42TCW", "CGSize(width: _v42TCW, height: .greatestFiniteMagnitude)" in t)
ck("v41 补齐仍用 _v42Need", "_hFix.size.height = _v42Need" in t)
ck("v41 polluted 含高度维度", "_hDebt" in t)
ck("v41 KVOFIXH 诊断仍在", "V41-KVOFIXH" in t)
ck("V41-DEBT 诊断仍在", "V41-DEBT" in t)

# ================= 四、Swift 编译防御 =================
# v42 首次推送就是栽在 trailing closure, 这里继续盯
_gate = t.split("[V42-GATE]")
ck("GATE 块未被改成裸 { }",
   len(_gate) > 1 and N + "            {" not in _gate[1][:1200])
ck("GATE 内仍用 self.findCollectionView()", "self.findCollectionView()" in t)
ck("KVO 段属性引用带 self.", "self.ios15LatchedNeedH" in t)

# 花括号平衡(词法扫描, 正确处理注释与字符串)
depth = 0
mind = 0
i = 0
n = len(t)
state = None
while i < n:
    c = t[i]
    nxt = t[i + 1] if i + 1 < n else ""
    if state is None:
        if c == "/" and nxt == "/":
            state = "line"
            i += 2
            continue
        if c == "/" and nxt == "*":
            state = "block"
            i += 2
            continue
        if c == '"':
            state = "str"
            i += 1
            continue
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
            state = None
            i += 2
        else:
            i += 1
    else:  # str
        if c == "\\":
            i += 2
        elif c == '"':
            state = None
            i += 1
        else:
            i += 1
ck(f"花括号平衡 (final={depth}, min={mind})", depth == 0 and mind == 0)

print(f"产物检查: {ok}/{ok + len(bad)} 通过")
if bad:
    print("\n失败:")
    for b in bad:
        print(f"  ✗ {b}")
    sys.exit(1)
print("✅ v43 宽度同源 + 涌入节流就位")
