#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v45 反向证伪: 逐条破坏 v45, 确认 verify_v45 的判据真的能抓住。

用法: python3 reverse_v45.py [产物根目录]
默认 /tmp/ci_v45

## 为什么必须有反向测试

正向全绿只能证明"判据在正常产物上成立", 不能证明"判据有效"。第一版 v44
防御测试全军覆没(11 条 sabotage 全部漏放), 根因是:
  1) sabotage 之后又去调注入函数, 而它会在锚点处**再注入一份崭新的、完好的**
     代码 —— 等于每次都在测一份没被破坏的代码;
  2) sabotage 在 base 上替换 SEG, 而 SEG 是从 injected 切出来的, base 里根本
     不存在这个子串 —— str.replace 原样返回, 12 条 case 全退化成"校验未注入的
     base", 报错像拦住了, 实则零判据被验到。

本脚本因此: (a) 只调用 verify_v45 这个**纯校验**函数, 绝不碰注入函数;
         (b) 所有 sabotage 一律在 **injected** 文本上做(不回到干净 base)。

## 每条 case 抓什么

  A 类(段落缺失)   —— 整段删/ NSLog 删/ 字段删
  B 类(★越界改宽度) —— 偷偷改 width / origin, 判据必须亮红灯
  C 类(位置错)     —— 搬到 v41 补高之前 / v44 之后
  D 类(幂等破坏)   —— 判据改成 <=, 死循环
"""
import sys
import os
import importlib.util

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v45"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
FB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "ios15_fallback.py")

N = "\n"
if not os.path.exists(MD):
    print(f"产物不存在: {MD}")
    sys.exit(2)

# 关键纪律: 只加载校验函数, 不在这里调用任何注入函数(否则会在锚点处
# 再注入一份完好代码, sabotage 直接失效 —— v44 第一版就是这么废的)。
spec = importlib.util.spec_from_file_location("fb", FB)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

INJECTED = open(MD, encoding="utf-8").read()
ORIG = INJECTED

# 切出 v45 的 do 块本体, 供精准替换
DO = N + "            do {"
_i = INJECTED.find("// [V45-TVHFIX]")
_i_do = INJECTED.find(DO, _i)
_i_close = INJECTED.find(N + "            }", _i_do)
SEG = INJECTED[_i_do:_i_close]          # 含 do { ... 到闭合前
BLOCK_START = _i                        # 段落首个标记的位置

caught = 0
missed = []


def judge(txt):
    """跑 verify_tvh_debt_v45, 返回错误信息列表(空 = 通过)。"""
    try:
        fb.verify_tvh_debt_v45(txt)
        return []
    except RuntimeError as e:
        return [str(e)]


def run(title, old, new, expect_kw=None, count=1):
    """在 injected 文本上做一次破坏, 期望 verify 报错。

    expect_kw: 报错信息里应当出现的关键词, 用于确认"是因为正确的原因
               被抓住", 而不是因为别的判据偶然拦下。
    """
    global caught
    if old not in INJECTED:
        print(f"  ✗ {title} :: sabotage 基底错误 —— 待替换串在 injected 里不存在 "
              f"(这条 case 测不到任何判据, 等于静默通过)")
        missed.append(f"{title} :: 基底错误, 待替换串不存在于 injected")
        return
    t2 = INJECTED.replace(old, new, count)
    if t2 == INJECTED:
        print(f"  ✗ {title} :: sabotage 未生效(replace 原样返回)")
        missed.append(f"{title} :: sabotage 未生效")
        return
    res = judge(t2)
    if not res:
        print(f"  ✗ {title} :: 判据没反应(破坏后仍全绿 —— 判据无效!)")
        missed.append(f"{title} :: 判据没反应")
        return
    if expect_kw and not any(expect_kw in x for x in res):
        print(f"  ✗ {title} :: 被拦下了但原因不对 -> {res}")
        missed.append(f"{title} :: 原因不对({res})")
        return
    caught += 1
    print(f"  ✔ {title.ljust(46)} -> {res[0][:66]}")


print(f"反向证伪 (基线: {MD})\n")

# ============ A 类: 段落缺失 ============
run("A1 整段删除",
    INJECTED[BLOCK_START:_i_close + len(N + "            }")], "",
    expect_kw="整段缺失")

run("A2 NSLog 标记消失",
    'NSLog("[V45-TVHFIX]', 'NSLog("[V45-XX]',
    expect_kw="标记数不符")

run("A3 判据条件整行删",
    "if _v42Need > 1, self.frame.size.height + 0.5 < _v42Need {",
    "if false {",
    expect_kw="缺少关键字段")

run("A4 写入语句删",
    "_tvf.size.height = _v42Need",
    "// 已删除",
    expect_kw="缺少关键字段")

run("A5 提交语句删",
    "self.frame = _tvf",
    "// 已删除",
    expect_kw="缺少关键字段")

# ============ B 类: ★越界改宽度/位置 ============
# 这一类是 v45 最要紧的: 碰了 width 就绕过了 v18/v34 的状态机,
# 装机后一旦闪屏无法归因是 v45 引起还是老问题复发。
run("B1 ★偷偷改宽度 _tvf.size.width",
    "_tvf.size.height = _v42Need",
    "_tvf.size.height = _v42Need; _tvf.size.width = 100000",
    expect_kw="只准动高度")

run("B2 ★改 self.frame 的宽度",
    "self.frame = _tvf",
    "self.frame.size.width = 390; self.frame = _tvf",
    expect_kw="只准动高度")

run("B3 ★改 origin.x",
    "_tvf.size.height = _v42Need",
    "_tvf.size.height = _v42Need; _tvf.origin.x = -88",
    expect_kw="只准动高度")

run("B4 ★改 bounds(语义不同, 会连带改滚动内容)",
    "_tvf.size.height = _v42Need",
    "_tvf.size.height = _v42Need; self.bounds.size.height = 99999",
    expect_kw="只准动高度")

# ============ C 类: 位置错 ============
# 搬到 v41 补高之前 —— 与 v41 的写入顺序纠缠, 装机后无法归因。
_t2 = INJECTED
_i_hit = _t2.find('NSLog("[V41-KVOHEIGHT]')
_block_start = _t2.index("// [V45-TVHFIX]")
_block_end = _t2.find(N + "            }", _t2.find(DO, _block_start)) \
    + len(N + "            }")
_moved = _t2[_block_start:_block_end]
if _moved in _t2 and _i_hit > 0:
    _t2b = _t2.replace(_moved, "", 1)
    _t2b = _t2b[:_i_hit] + _moved + _t2b[_i_hit:]
    _r = judge(_t2b)
    if any("补高之后" in x for x in _r):
        caught += 1
        print(f"  ✔ {'C1 ★搬到v41补高之前(与v41写入顺序纠缠)'.ljust(46)} -> {_r[0][:66]}")
    else:
        missed.append(f"C1 搬到补高之前 :: 判据没反应({_r})")
        print(f"  ✗ C1 搬到补高之前 :: {_r}")
else:
    missed.append("C1 基底错误: v45 段或 v41 补高日志找不到")
    print("  ✗ C1 基底错误")

# 搬到 v44 之后 —— 位置判据要求 v45 在 v44 之前。
_t3 = INJECTED
_b_start = _t3.index("// [V45-TVHFIX]")
_b_end = _t3.find(N + "            }", _t3.find(DO, _b_start)) \
    + len(N + "            }")
_blk = _t3[_b_start:_b_end]
_i44 = _t3.index("// [V44-TEXTFRAME] 见函数 docstring")
_i44end = _t3.find(N + "            }", _t3.find(DO, _i44)) \
    + len(N + "            }")
if _blk in _t3:
    _t3b = _t3.replace(_blk, "", 1)
    _t3b = _t3b[:_i44end] + _blk + _t3b[_i44end:]
    _r = judge(_t3b)
    if _r:
        caught += 1
        print(f"  ✔ {'C2 搬到v44之后(破坏窗口边界)'.ljust(46)} -> {_r[0][:66]}")
    else:
        missed.append("C2 搬到 v44 之后 :: 判据没反应")
        print(f"  ✗ C2 搬到 v44 之后 :: 判据没反应(全绿)")
else:
    missed.append("C2 基底错误: v45 段找不到")
    print("  ✗ C2 基底错误")

# ============ D 类: 幂等破坏 ============
run("D1 判据改成 <= (死循环)",
    "if _v42Need > 1, self.frame.size.height + 0.5 < _v42Need {",
    "if _v42Need > 1, self.frame.size.height + 0.5 <= _v42Need {",
    expect_kw="缺少关键字段")

# ============ E 类: 节流与编译 ============
run("E1 节流被去掉(每帧都打, 加重排版开销)",
    "if _tvhNow - _TvhLog.last > 0.5 {",
    "if true {",
    expect_kw="0.5s 节流")

run("E2 裸块(会被吸成 trailing closure 编译失败)",
    DO + N + "                if _v42Need > 1",
    N + "            " + "{" + N + "                if _v42Need > 1",
    expect_kw="do { }")

# ============ F 类: 花括号平衡 ============
run("F1 花括号不平衡",
    "    var ios15LatchHash: Int = 0",
    "    var ios15LatchHash: Int = 0" + N + "    func _v45unbalanced() {",
    expect_kw="花括号不平衡")

print()
print(f"反向证伪: {caught}/{caught + len(missed)} 抓到")
if missed:
    print("\n漏掉:")
    for m in missed:
        print(f"  ✗ {m}")
    sys.exit(1)
print("✅ 每条 sabotage 都被判据抓住 —— 判据本身有效")
