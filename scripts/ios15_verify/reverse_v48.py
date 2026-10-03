#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v48 反向证伪 —— 重点是**防闪屏专项**。

为什么 v48 的反向测试要单独强调防闪屏:
v13/v34 当初就是因抢宽引起**闪屏**与**整体缩小**翻的车。v48 恰好是主动
抢宽(`textContainer.size.width = _realW2`), 所以"这次抢宽会不会重演"
就是本版唯一真正要验的东西。

与反向测试的通则:
  · 只调 `verify_width_pin_v48`, **绝不在 sabotage 之后调注入函数** ——
    否则会把"注入本身出错"混进"判据没拦住"。
  · 每条sabotage 都必须**被拦住**; 漏放一条即视为判据失效。

防闪屏专项的判据思路(与一般 sabotage 不同, 不是"塞一行坏代码",
而是**模拟 v13/v34 的翻车形态**):
  F1 常驻钳宽      —— 无条件每帧写 358(与 SwiftUI 竞争)
  F2 抢到第三方宽度 —— 写 `min(bounds.width, _cvW) - inset` 之类新算的宽
  F3 抢 frame/bounds —— 整体缩小事故的直接写法
  F4 抢高度        —— 推翻 v45 成果
  F5 另起抢宽时机  —— 不复用 _ios15WRegrabbed
  F6 删掉幂等门    —— 让写入无条件生效
  F7 改接收者      —— 别的 view 抢宽
  F8 写 setSize     —— 用 TextKit 的 setSize 绕过 size 赋值(语义不同)
  F9 值用 ==伪装   —— 比较运算不应被当成写入
  F10 破坏 v47 回写 —— 碎片记忆失效 -> 每帧都判据成立 -> 持续重排(闪屏)

用法: reverse_v48.py [产物根目录]
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v48run"
SWIFT = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ios15_fallback import (verify_width_pin_v48,  # noqa: E402
                           verify_width_reflow_v47)

if not os.path.exists(SWIFT):
    print("产物不存在:", SWIFT)
    sys.path.exit(1)

INJECTED = open(SWIFT, encoding="utf-8").read()

# 段内真实的写入行（用作 sabotage 的定位锚）
#
# ★【踩坑 —— 锚点必须在文件里唯一】曾用裸串
#     "textContainer.size.width = _realW2"
# 做锚点，但这个串在文件里有**两处**：
#     @425145  v18 自己的既有钳宽（if abs(tcW-_realW2)>0.5 { ... }）
#     @427366  v48 的写入（守卫多了 `_ios15WRegrabbed, ` 前缀）
# `str.replace(..., 1)` 抓的是**第一个** —— 于是全部 sabotage 都在篡改
# v18 的既有代码，v48 那段一动没动。后果很典型：判据"全绿"、反向测试
# 却报十几条"漏放"，两边都在说谎。
# 教训：定位锚点必须带**上下文**做到唯一，不能用裸子串 + replace(...,1)。
PIN = "// [V48-PIN]"
WRITE_LINE = "                textContainer.size.width = _realW2"
GUARD_LINE = ("            if _ios15WRegrabbed, "
              "abs(textContainer.size.width - _realW2) > 0.5 {")
# 带 v48 守卫前缀的整块：唯一定位 v48 的写入行，sabotage 一律改这个块。
V48_BLOCK = GUARD_LINE + "\n" + WRITE_LINE

if PIN not in INJECTED:
    print("产物里没有 V48-PIN, 不是 v48 产物")
    sys.exit(1)
if V48_BLOCK not in INJECTED:
    print("产物里没有预期的 v48 写入块(V48_BLOCK), sabotage 定位会失效")
    print("  期望:", repr(V48_BLOCK[:80]))
    sys.exit(1)
# 唯一性自检: 写入串在文件里应恰好出现在 V48_BLOCK 内一次
if INJECTED.count(WRITE_LINE) != 2:
    print("★锚点不唯一: 写入串在文件里出现 %d 次(期望 2: v18 既有 + v48)"
          % INJECTED.count(WRITE_LINE))
    sys.exit(1)

_caught = []


def run(name, mutant, why):
    """sabotage 注入后, 校验必须抛错; 抛不出 = 漏放。"""
    try:
        verify_width_pin_v48(mutant)
    except Exception:
        _caught.append((name, True))
        print("  ✅ %s: 已拦截" % name)
        return
    _caught.append((name, False))
    print("  ❌ %s: ★漏放 —— %s" % (name, why))


print("v48 反向证伪（根=%s）" % ROOT)
print()
print("=" * 60)
print("A 类: 摘判据 / 删写入 / 删标记")
print("=" * 60)

run("A1 整段删掉 V48-PIN 注入",
    INJECTED.replace(PIN, "// [X]", 1),
    "整段防闪屏逻辑消失")

run("A2 删掉唯一的宽度写入行",
    INJECTED.replace(V48_BLOCK, "// removed", 1),
    "钉宽消失 -> 回到 v47 治不好的状态")

run("A3 写入行改成 setSize",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + "                textContainer.setSize(CGSize(width: _realW2, height: textContainer.size.height))", 1),
    "setSize 语义与 size 赋值不同(TextKit 内部路径), 不受本判据的白名单保护")

# ============================================================
print()
print("=" * 60)
print("B 类: ★防闪屏专项(v13/v34 翻车形态)")
print("=" * 60)

# B1 常驻钳宽: 去掉 if 守卫, 无条件每帧写 358
run("B1 ★常驻钳宽(无 if 守卫, 与 SwiftUI 竞争)",
    INJECTED.replace(GUARD_LINE,
                     "            if true {", 1),
    "v13/v34 翻车的直接形态: 每帧无条件抢宽")

# B2 抢到第三方宽度
run("B2 ★抢到新算的宽度(绕过 v18 的 _realW2)",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + "                textContainer.size.width = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)", 1),
    "引入第三方宽度 -> 排版宽与测高宽再次分叉, 正是 v34 翻车的语义")

# B3 抢 frame / bounds(整体缩小事故)
run("B3 ★抢 frame.width(整体缩小事故形态)",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + WRITE_LINE + "\n                frame.size.width = _realW2", 1),
    "改 frame 会触发整棵 cell 重新布局 -> 闪屏")

run("B4 ★抢 bounds.width",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + WRITE_LINE + "\n                bounds.size.width = _realW2", 1),
    "改 bounds 同样触发父级重排")

run("B5 ★抢 origin(几何漂移)",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + WRITE_LINE + "\n                frame.origin.x = 0", 1),
    "动 origin 会让整段内容位移")

# B4 抢高度(推翻 v45)
run("B6 ★抢 tvH/高度(推翻 v45 成果)",
    INJECTED.replace(V48_BLOCK,
                     GUARD_LINE + "\n" + WRITE_LINE + "\n                self.frame.size.height = _realW2", 1),
    "v45 已实测 debt 全 0, 这里动高度会把成果推翻")

# B5 另起抢宽时机
run("B7 ★另起抢宽时机(不复用 _ios15WRegrabbed)",
    INJECTED.replace(GUARD_LINE,
                     "            if abs(textContainer.size.width - _realW2) > 0.5 {", 1),
    "不看碎片是否一致就抢宽 = 与布局 pass 竞争")

# B6 删幂等门: 守卫条件改成永真
#注意: 必须改 v48 段内那处守卫, 不能用裸 replace —— 同样的串在 v18 段
# 也有一份, 裸 replace(...,1) 抓的是 v18 的, v48 段根本没被篡改(同 A1教训)。
run("B8 ★删幂等门(把 v48 段内>0.5 阈值改成 > -999)",
    INJECTED.replace(
        V48_BLOCK,
        GUARD_LINE.replace("> 0.5 {", "> -999 {") + "\n" + WRITE_LINE, 1),
    "阈值失效 -> 每次都写 -> 持续重排 = 闪屏")

# B7 换接收者
run("B9 ★换接收者(textView.size.width)",
    INJECTED.replace(V48_BLOCK,
                     "                textView.size.width = _realW2", 1),
    "别的 view 抢宽, 不在本版意图内")

# ============================================================
print()
print("=" * 60)
print("C 类: 值伪装与比较运算(不得误伤)")
print("=" * 60)

# B8 用 == 伪装: 判据不能把这个当写入放过去
run("B10 ★用 == 伪装赋值",
    INJECTED.replace(V48_BLOCK,
                     "                _ios15WRegrabbed == _realW2", 1),
    "比较运算不是写入")

# 反向: 合法代码不该被误伤(误伤也是失败)
_legal = INJECTED.replace(
    V48_BLOCK,
    V48_BLOCK + "\n                // 合法: 读取宽度做判断\n"
    "                let _probe = textContainer.size.width", 1)
try:
    verify_width_pin_v48(_legal)
    _caught.append(("B11 合法读取不误伤", True))
    print("  ✅ B11 合法读取不误伤: 通过")
except Exception as e:
    _caught.append(("B11 合法读取不误伤", False))
    print("  ❌ B11 合法读取不误伤: ★误伤 —— %s" % e)

# ============================================================
print()
print("=" * 60)
print("D 类: 破坏 v47 / 前版(加法保护)")
print("=" * 60)

# ★缩进 12 而不是 16 —— v50-C 把回写提出了 `if _ios15WRegrabbed`。
#   锚点若还写 16, replace 静默不命中 ⇒ sabotage 成了 no-op ⇒
#   报"漏放", 而真相是"锚点失效"。这里显式自检。
_D1_OLD = "            self.ios15LastLaidOutW = _realW2"
if _D1_OLD not in INJECTED:
    raise SystemExit(
        "★D1 锚点失效: 回写行不在产物里(缩进变了?) ⇒ sabotage 根本没构造出来, "
        "不是判据漏放。目标: %r" % _D1_OLD)

run("D1 删 v47 的 ios15LastLaidOutW 回写",
    INJECTED.replace(_D1_OLD, "// removed", 1),
    "碎片记忆失效 -> 判据每帧成立 -> 持续重排 = 闪屏源头")

# D2/D3 破坏的是 **v47**, 不在 v48 段的判据范围内 —— v48 的段判据理应
# 放行(它只管 v48 自己那一段)。这两条必须由**v47 的判据**拦住, 所以改成
# 交叉验证: 确认 verify_v47 能拦。这比硬塞给 v48 更能反映真实的分层职责。
def _run_v47(name, mutant, why):
    try:
        verify_width_reflow_v47(mutant)
    except Exception:
        _caught.append((name, True))
        print("  ✅ %s: 已拦截（由 v47 判据）" % name)
        return
    _caught.append((name, False))
    print("  ❌ %s: ★漏放 —— %s" % (name, why))


_run_v47("D2 删 v47 的重排判据（应由 v47 判据拦）",
         INJECTED.replace(
             "if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {",
             "if false {", 1),
         "v47 判据被破坏, 且 v48 段判据按分层职责不该管它")

_run_v47("D3 删 v47 属性声明（应由 v47 判据拦）",
         INJECTED.replace("    var ios15LastLaidOutW: CGFloat?",
                          "    var _x: CGFloat?", 1),
         "v47 状态丢失")

run("D4 删 V45 诊断日志",
    INJECTED.replace('NSLog("[V45-TVHFIX]', 'Log("[V45-TVHFIX]', 1),
    "v48 吃掉了 v45 的诊断能力")

run("D5 多插一个 V48-PIN 标记",
    INJECTED.replace(PIN, PIN + "\n" + PIN, 1),
    "标记计数应为 1")

# ============================================================
print()
print("=" * 60)
print("E 类: 编译期破坏")
print("=" * 60)

run("E1 段尾插未闭合函数",
    INJECTED + "\nfunc _v48Broken() {\n",
    "编译不过")

print()
print("=" * 60)
caught = sum(1 for _, ok in _caught if ok)
missed = len(_caught) - caught
print("v48 反向证伪: %d 条拦住, %d 条漏放" % (caught, missed))
if missed:
    print("★漏放项:")
    for n, ok in _caught:
        if not ok:
            print("   -", n)
print("OK" if missed == 0 else "XX 有漏放")
sys.exit(0 if missed == 0 else 1)
