#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v43 反向证伪: 逐条重现 v43 修掉的 bug, 证明 42 条判据真的能抓住它们。

用法: python3 reverse_v43.py [产物根目录]
默认 /tmp/ci_v43

【为什么必须做反向】正向全绿只能证明"补丁在", 证明不了"检查有效"。
v42 首次推送的教训是: 正向 45/45 + 反向 31/31 + 花括号 depth=0 全绿,
结果 CI 编译失败 8 个 error —— 静态检查全漏, 只有 swiftc 抓得到。
所以每条判据都要有对应的 sabotage 证明它会亮红灯。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v43"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
MLL = os.path.join(ROOT, "src/ios/Agent/MessageList/MessageListLayout.swift")
N = "\n"

base_md = open(MD, encoding="utf-8").read()
base_mll = open(MLL, encoding="utf-8").read()

caught = 0
missed = []


def run(name, path, old, new, expect_md=None, expect_mll=None):
    """把 old 换成 new, 跑一遍判据, 必须报 FAIL。"""
    global caught
    src = base_md if path == "md" else base_mll
    if old not in src:
        missed.append(f"{name} :: 锚点失配(产物里找不到待破坏的原文)")
        return
    t = src.replace(old, new, 1)
    # 判据(与 verify_v43 同源, 逐条重跑)
    reasons = []
    if path == "md":
        if "V43-NETW" not in t:
            reasons.append("NETW标记")
        if "V43-WIDTH" not in t:
            reasons.append("WIDTH标记")
        if "V43-LATCHW" not in t:
            reasons.append("LATCHW标记")
        if "let _v42TCW = _v43NetW" not in t:
            reasons.append("自测宽度未用净宽")
        if "let _v43NetW = max(200.0, cvW - 32)" not in t:
            reasons.append("净宽公式")
        if "let _v42TCW = self.textContainer.size.width" in t:
            reasons.append("又用回脏宽当测量宽")
        if "self.ios15LatchW = _realW2" not in t:
            reasons.append("闩锁键未存净宽")
        if "self.ios15LatchW = self.textContainer.size.width" in t:
            reasons.append("闩锁键又存回脏宽")
        if t.count('NSLog("[V43-WIDTH]') != 1:
            reasons.append("WIDTH诊断数")
        # 诊断必须**同时**用两种宽各测一次, 打出 dh。缺任一条 -> 诊断失去意义
        # (A10 就是在破坏这条: 把 _hNet 也改成脏宽, 于是 dh 恒为 0, 白测)。
        if "let _hNet = self.sizeThatFits(" not in t:
            reasons.append("净宽自测缺失")
        if "let _hDirty = self.sizeThatFits(" not in t:
            reasons.append("脏宽自测缺失")
        if "CGSize(width: _v43NetW, height: .greatestFiniteMagnitude)).height" not in t:
            reasons.append("hNet 未用净宽(诊断退化成恒等比较)")
        if "CGSize(width: _v43DirtyW, height: .greatestFiniteMagnitude)).height" not in t:
            reasons.append("hDirty 未用脏宽(诊断失去对照)")
        if "_hNet - _hDirty" not in t:
            reasons.append("未打高度差 dh")
    else:
        if "V43-BURST" not in t:
            reasons.append("BURST标记")
        if "_v43Now - _v43Prev < 0.25" not in t:
            reasons.append("节流窗口")
        if "heightCache[index] != nil, delta > 100" not in t:
            reasons.append("拦截条件")
        if "private static var v43BurstAt: [Int: CFTimeInterval] = [:]" not in t:
            reasons.append("静态存储")
        if "Self.v43BurstAt[index] = _v43Now" not in t:
            reasons.append("窗口基准写入")
        if "suppressed — 距上次突增" not in t:
            reasons.append("窗口内拦截")
        if "Self.v43BurstAt.count > 64" not in t:
            reasons.append("陈旧清理")
        if "private static var v31MaxH: [Int: CGFloat] = [:]" not in t:
            reasons.append("V31被破坏")

    # ---- 编译防御(v42 首次推送真实栽过的地方: 静态检查全漏, 只有 swiftc 抓得到) ----
    # 只对 md 生效: GATE 块与闩锁声明都在 SelectableMarkdownView 里。
    if path == "md":
        # GATE 块必须用 do { }(独立语句), 裸 { } 会被吸成 trailing closure -> 8 个 error
        _g = t.find("// [V42-GATE]")
        if _g >= 0:
            _gseg = t[_g:_g + 2000]
            if N + "            do {" not in _gseg:
                reasons.append("GATE 块未用 do { }(会编译失败)")
            if N + "            {" + N + "                struct _GateLog" in _gseg:
                reasons.append("GATE 块是裸 { }(重现 v42 编译失败)")
            # 块内所有引用必须带 self.
            if "let _gCV = self.findCollectionView()" not in _gseg:
                reasons.append("GATE 内 findCollectionView 缺 self.")
            if "self.isScrollEnabled ? 0 : 1" not in _gseg:
                reasons.append("GATE 内 isScrollEnabled 缺 self.")
            for _k in ("ios15LatchedNeedH", "ios15LatchLen", "ios15LatchW"):
                if "self." + _k not in _gseg:
                    reasons.append(f"GATE 内 {_k} 缺 self. 前缀")
        else:
            reasons.append("V42-GATE 标记消失")

        # 花括号必须平衡(词法扫描, 正确跳过注释与字符串)
        _depth = _mind = 0
        _i = 0
        _n = len(t)
        _st = None
        while _i < _n:
            _c = t[_i]
            _nx = t[_i + 1] if _i + 1 < _n else ""
            if _st is None:
                if _c == "/" and _nx == "/":
                    _st = "line"; _i += 2; continue
                if _c == "/" and _nx == "*":
                    _st = "block"; _i += 2; continue
                if _c == '"':
                    _st = "str"; _i += 1; continue
                if _c == "{":
                    _depth += 1
                elif _c == "}":
                    _depth -= 1
                    _mind = min(_mind, _depth)
                _i += 1
            elif _st == "line":
                if _c == "\n":
                    _st = None
                _i += 1
            elif _st == "block":
                if _c == "*" and _nx == "/":
                    _st = None; _i += 2
                else:
                    _i += 1
            else:
                if _c == "\\":
                    _i += 2
                elif _c == '"':
                    _st = None; _i += 1
                else:
                    _i += 1
        if _depth != 0 or _mind < 0:
            reasons.append(f"花括号不平衡(final={_depth}, min={_mind})")
    if reasons:
        caught += 1
    else:
        missed.append(f"{name} :: 判据没反应(改坏了但全绿)")


# ============ 一、宽度同源: 逐条重现 log11 那个 84pt 差 ============

# 1. **原始 bug**: 自测宽度退回脏宽 tcW —— 这就是 v42 的写法
run("A1 自测宽度退回脏宽(重现 log11 84pt 差)", "md",
    "let _v42TCW = _v43NetW",
    "let _v42TCW = self.textContainer.size.width")

# 2. 净宽公式写错(漏掉 max 下限, 窄屏时 clamp 失效)
run("A2 净宽公式去掉 max 下限", "md",
    "let _v43NetW = max(200.0, cvW - 32)",
    "let _v43NetW = cvW - 32")

# 3. 净宽公式抄成 v18 的旧硬编码(漏 max)
run("A3 净宽漏 max", "md",
    "let _v43NetW = max(200.0, cvW - 32)",
    "let _v43NetW = max(0.0, cvW - 32)")

# 4. 闩锁键退回存脏宽 -> 键在"抢回前/后"反复失效
run("A4 闩锁键退回脏宽", "md",
    "self.ios15LatchW = _realW2",
    "self.ios15LatchW = self.textContainer.size.width")

# 5. 闩锁键完全不刷新(键失效, 退化成每次自测)
run("A5 闩锁键不刷新", "md",
    "self.ios15LatchW = _realW2",
    "self.ios15LatchW = -1")

# 6. 删掉整个 V43-NETW 段(退回 v42 原样)
# 【锚点设计】动态切片: 从净宽声明行到 [V42-THROTTLE] 之前, 整段抹掉。
_j0 = base_md.index("            let _v43NetW = max(200.0, cvW - 32)")
_j1 = base_md.index("            // [V42-THROTTLE]", _j0)
run("A6 整段删掉 V43-NETW(退回 v42)", "md", base_md[_j0:_j1],
    "            let _v42TCW = self.textContainer.size.width" + N)

# 7. 诊断标记消失
run("A7 V43-WIDTH 诊断消失", "md",
    'NSLog("[V43-WIDTH] dirtyW=%.1f netW=%.1f', 'NSLog("[V42-WIDTH] dirtyW=%.1f netW=%.1f')

# 8. 闩锁刷新标记消失
run("A8 V43-LATCHW 标记消失", "md",
    "[V43-LATCHW]", "[V42-LATCHW]")

# 9. 净宽标记消失
run("A9 V43-NETW 标记消失", "md", "[V43-NETW]", "[V42-NETW]")

# 10. 诊断失去对照: 把 hNet 也改成用脏宽 -> dh 恒为 0, 诊断白测
# 【v43 上轮的真实教训】这条最初写成"把 hNet 改成脏宽", 结果判据没反应 ——
# 因为原来的判据只检查"脏宽没进 sizeThatFits", 而诊断里**本来就该**用脏宽
# 测一次做对照(否则 dh 恒为 0, 拿不到两条链的高度差)。改坏的是"两宽对照"。
run("A10 诊断两宽对照被改成一宽", "md",
    "let _hNet = self.sizeThatFits(" + N +
    "                    CGSize(width: _v43NetW, height: .greatestFiniteMagnitude)).height",
    "let _hNet = self.sizeThatFits(" + N +
    "                    CGSize(width: _v43DirtyW, height: .greatestFiniteMagnitude)).height")

# ============ 二、涌入节流: 逐条重现那 5 次重排 ============

# 11. **原始 bug**: 整段节流消失 -> 1.08 秒 5 次全表重排回来
# 【锚点设计】用动态切片而不是硬编码整段: 注释一改就失配。第二轮把锚点从
# "V43-BURST → return shouldInvalidate" 换成 "V43-BURST → pendingFooterReflow = true",
# 因为节流点已从 shouldInvalidateLayout 迁到 invalidationContext 的 reflow 条件内。
_i0 = base_mll.index("            // [V43-BURST] 涌入型突增的**全表重排**节流")
_i1 = base_mll.index("            pendingFooterReflow = true", _i0)
run("B1 整段删掉 V43-BURST(重现 5 次全表重排)", "mll", base_mll[_i0:_i1], "")

# 12. 节流窗口放大到 5s -> 表格长时间不长
run("B2 节流窗口放大到 5s", "mll",
    "_v43Now - _v43Prev < 0.25",
    "_v43Now - _v43Prev < 5.0")

# 13. 窗口改成 0 -> 永不生效
run("B3 节流窗口改成 0(永不生效)", "mll",
    "_v43Now - _v43Prev < 0.25",
    "_v43Now - _v43Prev < 0.0")

# 14. 静态存储声明删掉(编不过)
run("B4 静态存储声明删掉", "mll",
    "    private static var v43BurstAt: [Int: CFTimeInterval] = [:]" + N,
    "")

# 15. 窗口基准不写入 -> 每次都成"第一次", 永不触发节流
run("B5 窗口基准不写入", "mll",
    "Self.v43BurstAt[index] = _v43Now",
    "Self.v43BurstAt[index] = _v43Now - 10.0")

# 16. 拦截条件去掉高度门 -> 小抖动也触发全表重排(等于没节流)
run("B6 拦截条件去掉高度门", "mll",
    "            if abs(delta) > 100 {",
    "            if abs(delta) > 2 {")

# 17. 高度门整个删掉 -> 节流只挂在 v43BurstAt 上, 变成无条件全表节流
#     (首次测量也会被拦, 新 cell 高度停在估计值)
run("B7 高度门整个删掉(首测也被全表节流)", "mll",
    "            if abs(delta) > 100 {",
    "            if true {")

# 18. 窗口内不拦(只打日志) -> 注释与实现不符, 5 次全表重排回来
# 【锚点必须按产物实际缩进】节流段在 reflow 条件内一层 if, 窗口内 return ctx
# 位于 20 空格缩进。早先按 16 空格写锚 -> 静默失配, 证伪报告显示"抓到 24"
# 实际这条根本没跑。静默跳过比失败更危险。
run("B8 窗口内只打日志不拦", "mll",
    "                    return ctx" + N + "                }" + N + "                Self.v43BurstAt[index] = _v43Now",
    "                }" + N + "                Self.v43BurstAt[index] = _v43Now")

# 19. 陈旧清理删掉 -> 长会话字典无限涨
run("B9 陈旧清理删掉", "mll", "                if Self.v43BurstAt.count > 64 {", "                if false {")

# 19b. 陈旧清理改成 removeAll -> 把还没过窗口的 idx 一起清掉, 节流退化成"隔次生效"
run("B9b 陈旧清理改成 removeAll(误清未过期条目)", "mll",
    "Self.v43BurstAt = Self.v43BurstAt.filter { $0.value > _v43Cut }",
    "Self.v43BurstAt = [:]")

# 19c. ★ 把节流搬到 heightCache 写入**之前** —— 这正是 v43-B 第一版的错:
#      拦在高度落地之前, prepare() 读到旧高度, 内容被裁, 比原症状更糟。
#      判据"★节流点晚于 heightCache 写入"必须抓住它。
#      锚点用「heightCache 写入 → 紧随的 SettleJitter 注释」这一对,
#      中间整段换成节流代码 —— 语义稳定(注释文字一改就失配)。
_hc0 = base_mll.index("        heightCache[index] = newHeight" + N)
_seg0 = base_mll.index("            // [V43-BURST] 涌入型突增的**全表重排**节流")
_seg1 = base_mll.index("            pendingFooterReflow = true", _seg0)
_seg = base_mll[_seg0:_seg1]
_tail0 = base_mll.index("        // [SettleJitter] Evidence log (H2)", _hc0)
run("B9c ★节流搬到 heightCache 写入之前(v43-B 第一版的错, 内容被裁)", "mll",
    base_mll[_hc0:_tail0],
    "        heightCache[index] = newHeight" + N + N + _seg + N)

# 20. 破坏 V31-FLIPLOCK(反振荡被连带弄坏) —— 仅当基线含该补丁
if "V31-FLIPLOCK" in base_mll:
    run("B10 V31-FLIPLOCK 被破坏", "mll",
        "if shouldInvalidate, !deferSelfSizing, heightCache[index] != nil, delta > 100 {",
        "if shouldInvalidate, heightCache[index] != nil, delta > 100 {")

    # 21. v31MaxH 声明删掉
    run("B11 v31MaxH 声明删掉", "mll",
        "    private static var v31MaxH: [Int: CGFloat] = [:]" + N, "")

# ============ 三、编译防御(v42 教训: 只有 swiftc 抓得到) ============

# 22. GATE 退回裸 { }(v42 首次推送的真实失败)
i0 = base_md.index(N + "            do {" + N + "                struct _GateLog")
run("C1 GATE 退回裸 { }(重现 v42 编译失败)", "md",
    N + "            do {" + N + "                struct _GateLog",
    N + "            {" + N + "                struct _GateLog")

# 23. GATE 内去掉 self.
run("C2 GATE 内 findCollectionView 去掉 self.", "md",
    "let _gCV = self.findCollectionView()",
    "let _gCV = findCollectionView()")

# 24. 花括号不平衡
run("C3 花括号不平衡", "md", "    var ios15LatchHash: Int = 0", "    var ios15LatchHash: Int = 0\n    func _v43 unbalanced() {")

print(f"反向证伪: {caught}/{caught + len(missed)} 抓到")
if missed:
    print("\n漏掉:")
    for m in missed:
        print(f"  ✗ {m}")
    sys.exit(1)
print("✅ 每条 sabotage 都被判据抓住 —— 判据本身有效")
