#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v47 反向证伪 —— 证明 verify_width_reflow_v47 不是空判据。

用法: python3 reverse_v47.py

【为什么必须有反向测试】
v47 是**修法**, 判据若漏放, 后果是"看起来绿、装机更糟"。而 v47 恰好踩在
最危险的雷区上(v13/v34 都因抢宽引起过闪屏与整体缩小)。所以判据必须能拦住:
  · 把重排判据改回旧的条件(等于白改)
  · 往 v47 段里塞高度写入(推翻 v45 成果)
  · 往 v47 段里塞宽度写入(回退到 v13/v34 老路)
  · 删掉排版宽回写(退化成每帧重排 → 主线程卡死)

【反向测试纪律】
只调 `verify_width_reflow_v47` 这一个**纯校验**函数, 绝不在 sabotage 之后
调注入函数 —— 否则注入会重新写回, 掩盖破坏。同 v46 的做法。

【本轮实踩的三类自伤, 已固化成判据(见 ios15_fallback.py 注释)】
  A. 段右边界取上游锚点 IOS15-FIX-RELC → 实际在注入点**之前** → find 返回 -1
     → 回退到 i47+4000 → 把 v45/v46 的段圈进来 → 误判"v47 写高度"。
  B. `"eight" in _lhs` 子串匹配 → 误伤既有变量 `_ios15WRegrabbed`(r-EIGHT-grabbed)。
  C. 属性声明与代码段**共用**一个标记 → find() 抓到文件前部的声明 → 切片错位。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "ios15_fallback.py"))

spec = importlib.util.spec_from_file_location("fb47", SCRIPT)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

# 与 verify_v46 同法: 剥注释与字符串, 否则注释里提一句错名字就自我误伤。
def strip_noise(src):
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            out.append('""')
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if src.startswith("/*", i):
                    depth += 1
                    i += 2
                elif src.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)

# ---- 造一份"已注入 v47"的合法产物当基线 ----
BASE_MD = "/tmp/v47run/src/ios/Views/Chat/SelectableMarkdownView.swift"
if not os.path.exists(BASE_MD):
    print("❌ 找不到 v47 产物, 请先跑注入:", BASE_MD)
    sys.exit(1)
INJECTED = open(BASE_MD, encoding="utf-8").read()

# 基线自检: 正向必须先通过, 否则下面的 sabotage 结果不可信
try:
    fb.verify_width_reflow_v47(INJECTED)
    print("基线自检: ✅ 未改动的 v47 产物通过校验")
except Exception as e:  # noqa: BLE001
    print("❌ 基线自检就失败, sabotage 结果不可信:", e)
    sys.exit(1)

passed = 0
missed = []


def run(name, mutated, expect_kw=None):
    """跑一次 sabotage; 被拦住=好, 漏放=判据失效。"""
    global passed
    try:
        fb.verify_width_reflow_v47(mutated)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if expect_kw and expect_kw not in msg:
            missed.append("%s: 拦下了但措辞不符(期望含 %r, 实际 %r)"
                          % (name, expect_kw, msg[:110]))
            print("  ⚠️ %s: 拦下但措辞不符" % name)
            return
        passed += 1
        print("  ✅ %s: 已拦截" % name)
        return
    missed.append("%s: ★漏放" % name)
    print("  ❌ %s: 漏放!" % name)


print()
print("=== A 类: 判据被摘掉(等于白改) ===")
run("A1 删掉重排判据整块",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "            }", "", 1),
    "未找到重排判据")

run("A2 把判据改回旧条件(等��白改)",
    INJECTED.replace(
        "if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {",
        "if abs(textContainer.size.width - _realW2) > 0.5 {", 1),
    "未找到重排判据")

run("A3 删掉排版宽回写",
    INJECTED.replace("self.ios15LastLaidOutW = _realW2", "", 1),
    "未找到排版宽回写")

run("A4 删掉属性声明",
    INJECTED.replace("    var ios15LastLaidOutW: CGFloat?", "", 1),
    "未找到 ios15LastLaidOutW 声明")

run("A5 属性改成非可选 CGFloat(失去'没排过版'语义)",
    INJECTED.replace("var ios15LastLaidOutW: CGFloat?",
                     "var ios15LastLaidOutW: CGFloat = 0", 1),
    "未找到 ios15LastLaidOutW 声明")

print()
print("=== B 类: ★把修法改成新的破坏(最关键) ===")
run("B1 v47 段内写高度(推翻 v45 成果)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "            }",
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "                frame.size.height = 9999\n"
        "            }", 1),
    "高度写入")

run("B2 v47 段内新增宽度写入点(v13/v34 老路)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "            }",
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                textContainer.size.width = 390\n"
        "                _ios15WRegrabbed = true\n"
        "            }", 1),
    "宽度写入")

run("B3 回写处偷写高度",
    INJECTED.replace(
        "                self.ios15LastLaidOutW = _realW2",
        "                self.ios15LastLaidOutW = _realW2\n"
        "                self.ios15LastNeededH = 9999", 1),
    "高度写入")

run("B4 v47 段内塞局部计数器(诊断体混入修法)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "            }",
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _v47Count += 1\n"
        "                _ios15WRegrabbed = true\n"
        "            }", 1),
    "局部赋值")

run("B5 用别的接收者写高度(textView.size.height)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                _ios15WRegrabbed = true\n"
        "            }",
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {\n"
        "                textView.size.height = 9999\n"
        "                _ios15WRegrabbed = true\n"
        "            }", 1),
    "高度写入")

run("B6 用 == 伪装赋值(判据不得误伤比较运算)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {",
        "            if ((self.ios15LastLaidOutW ?? -1) == _realW2) {", 1),
    "未找到重排判据")

print()
print("=== C 类: 结构破坏 ===")
run("C1 删掉整个 V47-REWRAP 标记",
    INJECTED.replace("// [V47-REWRAP]", "// [X]", 2),
    "未找到 V47-REWRAP 标记")

run("C2 删掉 V47-WSTATE 声明标记",
    INJECTED.replace("/// [V47-WSTATE]", "/// [X]", 1),
    "V47-WSTATE 声明标记必须恰好 1 处")

run("C3 多插一个 V47-REWRAP 标记",
    INJECTED.replace("            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {",
                     "            // [V47-REWRAP]\n            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {", 1),
    "必须恰好 2 处")

run("C4 v47 塞了诊断日志(归因已完成, 不该走诊断路线)",
    INJECTED.replace(
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {",
        '            NSLog("[V47-REWRAP] x")\n'
        "            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {", 1),
    "不得含诊断日志")

print()
print("=== D 类: 加法被破坏(v47 不能吃掉 v44/v45/v46) ===")
for tag, kw in (('NSLog("[V44-TEXTFRAME]', "必须保留"),
                ('NSLog("[V45-TVHFIX]', "必须保留"),
                ('NSLog("[V46-ATTACH]', "必须保留")):
    run("D%s 删掉 %s" % (len(tag), tag[:18]),
        INJECTED.replace(tag, tag.replace("V", "W", 1), 1), kw)

print()
print("=== E 类: 编译期破坏 ===")
run("E1 末尾插未闭合函数",
    INJECTED + "\nfunc _v47Broken() {\n    return\n", None)
run("E2 改坏 invalidateLayout 签名",
    INJECTED.replace(
        "layoutManager.invalidateLayout(forCharacterRange: NSMakeRange(0, textStorage.length), actualCharacterRange: nil)",
        "layoutManager.invalidateLayout()", 1),
    "invalidateLayout 签名")

print()
print("=" * 60)
print("v47 反向证伪: %d 条拦住, %d 条漏放" % (passed, len(missed)))
if missed:
    for x in missed:
        print("  ★", x)
    sys.exit(1)
print("✅ 全部 sabotage 都被拦下")
