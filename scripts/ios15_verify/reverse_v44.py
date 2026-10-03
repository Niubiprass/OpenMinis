#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v44 反向证伪: 逐条重现 v44 诊断段的三种失效, 证明判据真的能抓住它们。

用法: python3 reverse_v44.py [产物根目录]
默认 /tmp/ci_v44

【为什么 v44 尤其需要反向】v44 是**纯诊断**版, 它不改任何行为, 所以"能编过"
不代表"测得出"。三个假设各对应一个判据字段, 只要有一个被删/被改, 那一整条
假设就永远无法验证 —— 而这版唯一的产出就是这三条结论。所以每条 sabotage 都在
证明"少了它, 判据会亮红灯"。

【与前几版的差别】v42 的第一版 sabotage 全军覆没, 因为破坏完又调注入函数, 它会
在锚点处再注入一份崭新的、完好的诊断。所以这里**只跑判据, 不重新注入**。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v44"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
N = "\n"

base = open(MD, encoding="utf-8").read()

# 诊断块的 do { 行(12 空格缩进)。提到模块级: judge() 里是局部变量, sabotage 侧
# 也要用它做锚点限定, 局部变量在这里不可见。
_DO = N + "            do {"

caught = 0
missed = []


def judge(t):
    """与 verify_v44 同源的判据, 返回失败原因列表。空 = 全绿。"""
    r = []
    MK = "// [V44-TEXTFRAME] 见函数 docstring"
    if MK not in t:
        r.append("诊断段整段缺失")
    if "_tfdTvH = self.frame.height" not in t:
        r.append("缺判据A tvH")
    if "_tfdSvAfter = obj.frame.height" not in t:
        r.append("缺判据B svAfter")
    if "_tfdUsed = self.layoutManager.usedRect(" not in t:
        r.append("缺判据C usedH")
    if "self.textContainer).height" not in t:
        r.append("usedH 未取 textContainer")
    if t.count('NSLog("[V44-TEXTFRAME]') != 1:
        r.append("NSLog 标记数≠1")
    _DO2 = N + "            do {"
    if MK in t:
        c = t.index(MK)
        k = t.find("// [V41-KVOPOST]")
        k = k if k > c else len(t)
        if _DO2 not in t[c:k]:
            r.append("未用 do { }")
        # 位置: 必须在补高之后
        i_need = t.find("self.ios15LastNeededH = _v42Need")
        i_hit = t.find('NSLog("[V41-KVOHEIGHT]')
        if not (i_need >= 0 and i_hit > i_need and c > i_hit):
            r.append("诊断不在补高之后")
        # 纯诊断
        s = t.find(_DO2, c)
        seg = ""
        if s >= 0:
            try:
                e = t.index(N + "            }", s)
                seg = t[s:e]
            except ValueError:
                seg = ""
        for w in ("self.frame =", "obj.frame =", "textContainer.size =",
                  "self.ios15LastNeededH =", "self.ios15LatchedNeedH ="):
            if w in seg:
                r.append(f"混入写操作 {w}")
    if "_tfdNow - _TfdLog.last > 0.5" not in t:
        r.append("节流周期不对")
    # 花括号平衡
    depth = mind = 0
    i = 0
    n = len(t)
    st = None
    while i < n:
        ch = t[i]
        nx = t[i + 1] if i + 1 < n else ""
        if st is None:
            if ch == "/" and nx == "/":
                st = "line"; i += 2; continue
            if ch == "/" and nx == "*":
                st = "block"; i += 2; continue
            if ch == '"':
                st = "str"; i += 1; continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                mind = min(mind, depth)
            i += 1
        elif st == "line":
            if ch == "\n":
                st = None
            i += 1
        elif st == "block":
            if ch == "*" and nx == "/":
                st = None; i += 2
            else:
                i += 1
        else:
            if ch == "\\":
                i += 2
            elif ch == '"':
                st = None; i += 1
            else:
                i += 1
    if depth != 0 or mind < 0:
        r.append(f"花括号不平衡({depth}/{mind})")
    return r


def run(name, old, new):
    """把 old 换成 new, 判据必须报 FAIL。"""
    global caught
    if old not in base:
        missed.append(f"{name} :: 锚点失配(产物里找不到待破坏的原文)")
        return
    t = base.replace(old, new, 1)
    r = judge(t)
    if r:
        caught += 1
        print(f"  ✓ {name.ljust(44)} -> {r[0]}")
    else:
        missed.append(f"{name} :: 判据没反应(改坏了但全绿)")


MK = "// [V44-TEXTFRAME] 见函数 docstring"
i0 = base.index(MK)
# 诊断段整段: 从标记到 [V41-KVOPOST] 之前
i1 = base.index(N + "            // [V41-KVOPOST]", i0)
SEG = base[i0:i1]

print("=== 一、三个判据字段: 少一个就有一条假设永远无法验证 ===")
# 1. 删掉 tvH -> 假设 A(UITextView 自己矮了没人补)彻底失明
run("A1 删掉 tvH 判据(假设A失明)",
    "                let _tfdTvH = self.frame.height" + N, "")

# 2. 删掉 svAfter -> 假设 B(补高被重入挡掉)失明
#    【v41 补完从不回读】所以"补上了没有"至今没有任何日志能回答, svAfter 是
#    v44 唯一的新信息, 删了它这一版就退化成 v43 的重复。
run("A2 删掉 svAfter 判据(假设B失明)",
    "                let _tfdSvAfter = obj.frame.height" + N, "")

# 3. 删掉 usedH -> 假设 C(attachment 没进排版)失明
run("A3 删掉 usedH 判据(假设C失明)",
    "                let _tfdUsed = self.layoutManager.usedRect(" + N +
    "                        for: self.textContainer).height" + N, "")

# 4. usedH 改成量 textView 自身高度 -> 与 tvH 重复, 假设 C 退化成 A
run("A4 usedH 改成量 textView 高(与 tvH 重复, 假设C失明)",
    "                let _tfdUsed = self.layoutManager.usedRect(" + N +
    "                        for: self.textContainer).height",
    "                let _tfdUsed = self.frame.size.height" + N + "                _ = self.textContainer")

# 5. svAfter 改成读补高**之前**的值 -> 假设 B 永远为真(恒等于 svH), 白测
#    【易犯且极隐蔽】svAfter 与 svH 同值时, 假设 B 就永远无法证伪。
run("A5 svAfter 改成读旧值(假设B退化成恒真)",
    "                let _tfdSvAfter = obj.frame.height",
    "                let _tfdSvAfter = _hFix.size.height")

print()
print("=== 二、纯诊断: 混入写行为则结论作废 ===")
# 6. ★最危险的一条: 有人顺手在这里补 textView 高度, 装机后无法区分
#    "真修好了"和"看着好了"。这正是本版存在的意义, 必须拦住。
run("B1 ★混入 self.frame = 写行为",
    "                let _tfdTvH = self.frame.height",
    "                self.frame = _hFix" + N +
    "                let _tfdTvH = self.frame.height")

run("B2 ★混入 obj.frame = 写行为",
    "                let _tfdSvAfter = obj.frame.height",
    "                obj.frame = _hFix" + N +
    "                let _tfdSvAfter = obj.frame.height")

run("B3 ★混入 textContainer.size 写行为",
    "                let _tfdUsed = self.layoutManager.usedRect(",
    "                textContainer.size = _v42Need" + N +
    "                let _tfdUsed = self.layoutManager.usedRect(")

# 7. ★改闩锁 —— 这是 v42/v43 反复出问题的地方, 在诊断里改等于把行为改动伪装成诊断
run("B4 ★混入 ios15LastNeededH 改写",
    "                let _tfdTvH = self.frame.height",
    "                self.ios15LastNeededH = _v42Need" + N +
    "                let _tfdTvH = self.frame.height")

run("B5 ★混入 ios15LatchedNeedH 改写",
    "                let _tfdTvH = self.frame.height",
    "                self.ios15LatchedNeedH = _v42Need" + N +
    "                let _tfdTvH = self.frame.height")

print()
print("=== 三、结构: 编译与位置 ===")
# 8. do { } 退回裸 { } —— v42 首次推送真实栽过的地方, 静态检查全漏只有 swiftc 抓得到
#    【两个坑叠在一起, 都已踩到】
#    (a) 锚点不能只写 `N + "            do {"`: 文件里这一串**多处出现**(v42 的
#        GATE 块也是), replace(..., 1) 会改掉**第一处**——v42 的 GATE 块。判据当然
#        全绿, 因为它压根没动到 v44。这个与 v43 的 B8/B9c 锚点失配同型: 静默跳过
#        比失败更危险。
#    (b) 所以这里不用 run(), 改成**按位置切片重建**: 诊断块那一处换成裸 {,
#        其余原样。改的是它, 判据才验得到。
_i_do = base.index(_DO, i0)
_t_c1 = base[:_i_do] + N + "            {" + base[_i_do + len(_DO):]
_r = judge(_t_c1)
if _r:
    caught += 1
    print(f"  {'C1 do 退回裸 { }(重现 v42 trailing closure 失败)'.ljust(44)} -> {_r[0]}")
else:
    missed.append("C1 do 退回裸 { } :: 判据没反应(改坏了但全绿)")

# 9. 删掉整个诊断段
run("C2 整段删掉(退回到 v43, 无任何新信息)", SEG, "")

# 10. 节流周期改成 0.05s -> 与 V41-KVOPRE(0.5s)/V43-WIDTH 不同周期, 无法并列对照
run("C3 节流周期改成 0.05s(三日志不同周期无法对照)",
    "_tfdNow - _TfdLog.last > 0.5", "_tfdNow - _TfdLog.last > 0.05")

# 11. 节流整个删掉 -> 每帧都打, 主日志被刷爆, 且与另两条不同周期
run("C4 节流整个删掉",
    "                if _tfdNow - _TfdLog.last > 0.5 {",
    "                if true {")

# 12. ★诊断搬到补高**之前** —— 在补高前打, svAfter 与 svH 同值, 假设 B 无法证伪。
#     这正是 v43-B 第一版的错(插在写入之前), 同一个坑不能再踩第二次。
#     【必须是"移动"而不是"复制"】第一版把 SEG **插到**补高前, 原位置那份还在,
#     结果文件里变成两份诊断, 判据报的是"标记数≠1"——虽然拦住了, 但报的
#     不是位置这条判据, 等于位置判据本身没被验证过。这里改成先摘后插。
#     【两条判据都验到了才叫证明】移动之后: 标记数仍为 1, 但 i_tfd < i_hit,
#     必须由"诊断不在补高之后"这条抓住。
def _move_before_fix(t):
    seg = t[i0:i1]
    rest = t[:i0] + t[i1:]
    anchor = "                self.ios15LastNeededH = _v42Need"
    j = rest.index(anchor)
    return rest[:j] + seg + N + rest[j:]


_t_moved = _move_before_fix(base)
if _t_moved.count('NSLog("[V44-TEXTFRAME]') != 1:
    missed.append("C5 ★诊断搬到补高之前 :: sabotage 自身构造有误(移动后标记数应仍为 1)")
else:
    _r = judge(_t_moved)
    if any("补高之后" in x for x in _r):
        caught += 1
        print(f"  {'C5 ★诊断搬到补高之前(假设B退化成恒真)'.ljust(44)} -> 诊断不在补高之后")
    else:
        missed.append(
            "C5 ★诊断搬到补高之前 :: 判据没反应(移动后位置判据应亮红灯, 实际报 "
            + (str(_r) if _r else "全绿") + ")")

# 13. NSLog 被删(诊断存在但打不出东西)
run("C6 NSLog 标记消失",
    'NSLog("[V44-TEXTFRAME]', 'NSLog("[V44-TF]')

# 14. 花括号不平衡
run("C7 花括号不平衡", "    var ios15LatchHash: Int = 0",
    "    var ios15LatchHash: Int = 0" + N + "    func _v44unbalanced() {")

print()
print(f"反向证伪: {caught}/{caught + len(missed)} 抓到")
if missed:
    print("\n漏掉:")
    for m in missed:
        print(f"  ✗ {m}")
    sys.exit(1)
print("✅ 每条 sabotage 都被判据抓住 —— 判据本身有效")
