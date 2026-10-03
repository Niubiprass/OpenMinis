#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v46 反向证伪: 逐条破坏 v46, 确认 verify_attachment_v46 的判据真的能抓住。

用法: python3 reverse_v46.py [产物根目录]
默认 /tmp/ci_v46

## 为什么必须有反向测试

正向全绿只能证明"判据在正常产物上成立", **不能证明"判据有效"**。
v44 第一版防御测试全军覆没(11 条 sabotage 全部漏放), 两个根因:
  1) sabotage 之后又去调注入函数, 而它会在锚点处**再注入一份崭新的、完好的**
     代码 —— 等于每次都在测一份没被破坏的代码;
  2) sabotage 在 base 上替换 SEG, 而 SEG 是从 injected 切出来的, base 里根本
     不存在这个子串 —— str.replace 原样返回, 12 条 case 全退化成"校验未注入的
     base", 报错像拦住了, 实则零判据被验到。

本脚本因此: (a) 只调用 `verify_attachment_v46` 这个**纯校验**函数, 绝不碰
注入函数; (b) 所有 sabotage 一律在 **INJECTED** 文本上做(不回到干净 base)。

## 每条 case 抓什么

  A 类(段落缺失)      —— 整段删 / NSLog 删 / 关键判据字段删
  B 类(★纯诊断被写坏) —— 段内偷偷写 frame / 写缓存 / 调 invalidate / 改 accesssor 带 setter
  C 类(位置错)        —— 搬到 v45 之前 / v44 之后
  D 类(节流破坏)      —— 去掉 0.5s 节流
  E 类(结构破坏)      —— 插一个永不闭合的函数(编译才炸, 前判据应拦)
  F 类(加法被替换)    —— 删掉 v44/v45, 诊断变成替换而非加法
"""
import sys
import os
import importlib.util

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v46"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
FB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                  "..", "ios15_fallback.py")

if not os.path.exists(MD):
    print(f"产物不存在: {MD}")
    sys.exit(2)

# ★纪律: 只加载校验函数, 绝不在这里调任何注入函数(否则会在锚点处再注入
# 一份完好代码, sabotage 直接失效 —— v44 第一版就是这么废的)。
spec = importlib.util.spec_from_file_location("fb_v46", FB)
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)

INJECTED = open(MD, encoding="utf-8").read()
M46 = "// [V46-ATTACH] 表格附件高度"

# 切出 v46 段本体(诊断段头 -> V44 段头), 供精准替换
_i46 = INJECTED.find(M46)
_i44 = INJECTED.find("// [V44-TEXTFRAME] 见函数 docstring")
assert _i46 > 0 and _i44 > _i46, "产物里找不到 v46 段, 先跑注入"
V46_SEG = INJECTED[_i46:_i44]

caught = 0
missed = []


def run(name, mutated, expect_substr):
    """跑一次 verify, 看是否按预期报错。"""
    global caught
    try:
        fb.verify_attachment_v46(mutated)
        # 没报错 = 判据漏放
        missed.append((name, f"未拦截(期望报 {expect_substr!r})"))
        print(f"  ❌ {name}: 漏放")
    except RuntimeError as e:
        msg = str(e)
        if expect_substr and expect_substr not in msg:
            # 报错了但原因不对 —— 也算没真正验到这条判据
            missed.append((name, f"报错但原因不符(期望 {expect_substr!r}, 实得 {msg[:60]!r})"))
            print(f"  ⚠️ {name}: 报错但原因不符 -> {msg[:70]}")
        else:
            caught += 1
            print(f"  ✅ {name}: 已拦截")


# 健全性: 原样必须通过(否则下面全是噪音)
try:
    fb.verify_attachment_v46(INJECTED)
    print("原样 verify 通过 ✅\n")
except RuntimeError as e:
    print(f"❌ 原样就报错, 注入本身有问题: {e}")
    sys.exit(1)

print("=== A 类: 段落缺失 ===")
run("A1 整段删除",
    INJECTED.replace(V46_SEG, ""), "整段缺失")
run("A2 删 NSLog 行",
    INJECTED.replace('NSLog("[V46-ATTACH]', 'Log("[V46-ATTACH]'), "缺少判据字段")
run("A3 删 attWant 累加",
    INJECTED.replace("_v46AttWant += _v46R.height", "// removed"), "缺少判据字段")
run("A4 删 attachmentBounds 调用",
    INJECTED.replace("_v46R = _t.attachmentBounds(", "// removed"), "缺少判据字段")
run("A5 删 attNVI 声明",
    INJECTED.replace("var _v46AttNVI = false", "// removed"), "缺少判据字段")
run("A5b 删 attNVI 赋值语句",
    INJECTED.replace("if _v46AttNVI == false, _t.needsLayoutInvalidation { _v46AttNVI = true }",
                     "// removed"), "缺少判据字段")
run("A5c 删 attNVI 进日志",
    INJECTED.replace("_v46AttNVI ? 1 : 0", "0"), "缺少判据字段")
run("A6 删无附件跳过门",
    INJECTED.replace("if _v46AttN > 0 {", "if true {"), "缺少判据字段")
run("A7 删 cachedW 字段",
    INJECTED.replace("_v46AttCachedW = _t.attV46CachedWidth", "// removed"), "缺少判据字段")
run("A8 删访问器",
    INJECTED.replace("var attV46CachedTotalH: CGFloat { cachedLayout?.totalHeight ?? -1 }",
                     "// removed"), "只读访问器")

print("\n=== B 类: ★纯诊断被写坏 ===")
# B1: 段内偷偷写 self.frame —— 正是 v47 该干的事, 绝不能出现在 v46
run("B1 段内写 self.frame",
    INJECTED.replace("_v46AttWant += _v46R.height",
                     "_v46AttWant += _v46R.height\n"
                     "                    if _v46R.height > 0 { self.frame.size.height = _v46R.height }"),
    "纯诊断违规")
# B2: 段内调 invalidate —— 同样是修法动作
run("B2 段内调 invalidateLayout",
    INJECTED.replace("_v46AttWant += _v46R.height",
                     "_v46AttWant += _v46R.height\n"
                     "                    self.layoutManager.invalidateLayout(for: self.textContainer)"),
    "危险调用")
# B3: 段内写缓存(被"段内赋值"判据拦下 —— 赋值判据比危险调用清单更早命中)
run("B3 段内写 cachedLayout",
    INJECTED.replace("_v46AttWant += _v46R.height",
                     "_v46AttWant += _v46R.height\n"
                     "                    _t.cachedLayout = nil"),
    "纯诊断违规")
# B4: 段内写 needsLayoutInvalidation
run("B4 段内写 needsLayoutInvalidation",
    INJECTED.replace("_v46AttNVI = false", "_v46AttNVI = false\n                _t.needsLayoutInvalidation = true"),
    "纯诊断违规")
# B5: 段内写 textContainer.size
run("B5 段内写 textContainer.size",
    INJECTED.replace("_v46AttWant += _v46R.height",
                     "_v46AttWant += _v46R.height\n"
                     "                    self.textContainer.size = CGSize(width: 358, height: 2000)"),
    "纯诊断违规")
# B6: 段内调 computeLayout(会重算并**持久化**缓存, 改变被诊断的状态)
run("B6 段内调 computeLayout",
    INJECTED.replace("_v46AttWant += _v46R.height",
                     "_v46AttWant += _v46R.height\n"
                     "                    _ = _t.computeLayout(for: _v46W)"),
    "纯诊断违规")
# B7: 访问器带 setter —— 从后门打开纯诊断防线
run("B7 访问器加 setter",
    INJECTED.replace("var attV46CachedTotalH: CGFloat { cachedLayout?.totalHeight ?? -1 }",
                     "var attV46CachedTotalH: CGFloat {\n"
                     "        get { cachedLayout?.totalHeight ?? -1 }\n"
                     "        set { cachedLayout = nil }\n    }"),
    "只读 getter")

print("\n=== C 类: 位置错 ===")
# C1: 把 v46 段搬到 v45 之前
_i45 = INJECTED.find("// [V45-TVHFIX]")
i_end_seg = INJECTED.find("// [V44-TEXTFRAME] 见函数 docstring")
seg_moved = INJECTED[_i46:i_end_seg]
without = INJECTED[:_i46] + INJECTED[i_end_seg:]
run("C1 v46 搬到 v45 之前",
    without[:_i45] + seg_moved + without[_i45:], "v45 之后")
# C2: 把 v46 搬到 v44 之后
_v44nslog = INJECTED.find('NSLog("[V44-TEXTFRAME]')
_v44block_end = INJECTED.find("\n            }\n", _v44nslog) + len("\n            }\n")
without2 = INJECTED[:_i46] + INJECTED[i_end_seg:]
run("C2 v46 搬到 v44 之后",
    without2[:_v44block_end] + seg_moved + without2[_v44block_end:], "v44 之前")

print("\n=== D 类: 节流破坏 ===")
run("D1 去掉 0.5s 节流",
    INJECTED.replace("_v46Now - _V46Log.last > 0.5", "_v46Now - _V46Log.last > 0.0"),
    "0.5s 节流")
run("D2 删节流判断整行",
    INJECTED.replace("if _v46Now - _V46Log.last > 0.5 {", "if true {"),
    "0.5s 节流")

print("\n=== E 类: 结构破坏(编译才炸) ===")
# E1: 在文件末尾插一个永不闭合的函数 —— 前面的判据全过, 只有全文平衡能拦
run("E1 末尾插未闭合函数",
    INJECTED + "\n\nfunc v46BrokenSentinel() {\n    let a = 1\n",
    "花括号")

print("\n=== F 类: 加法被替换 ===")
# F1: 删掉 v45 修法 —— 诊断不能把已有修法顶掉
run("F1 删 v45 修法",
    INJECTED.replace('NSLog("[V45-TVHFIX]', 'Log("[V45-TVHFIX]'), "保留")
# F2: 删掉 v44 诊断
run("F2 删 v44 诊断",
    INJECTED.replace('NSLog("[V44-TEXTFRAME]', 'Log("[V44-TEXTFRAME]'), "保留")

print("\n" + "=" * 60)
print(f"v46 反向证伪: {caught} 条拦住, {len(missed)} 条漏放")
if missed:
    for n, why in missed:
        print(f"  ❌ {n}: {why}")
    sys.exit(1)
print("✅ 全部 sabotage 都被拦下")
