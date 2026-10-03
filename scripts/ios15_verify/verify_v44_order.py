#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v44 登记顺序回归 —— CI run#37118226923失败的真实死因。

用法:
    python3 verify_v44_order.py [产物根目录]
默认 /tmp/ci_v44_pre

【这个测试为什么存在】
v44 第一次登记时被放在了 v42 **前面**, CI 从干净上游跑, v44 先执行, 此时
v42 注入的那行 `self.ios15LastNeededH = _v42Need` 还不存在, verify 里
t.index(...) 抛 ValueError, ios15_fallback 整个崩在第三阶段:
编译、编译依赖、打包、提交全部没跑, 一步都没走到。

**本地为什么全绿** —— 这是最值得记的地方: 本地验证用的是 /tmp/ci_v43c,
那是 v43 完整流水线的产物, v42 **早就被打过了**。所以无论登记顺序如何,
锚点都找得到。用旧产物当基线, 恰好精确掩盖了"顺序依赖"这一类 bug。

⇒ 往后凡是"注入锚点依赖前序补丁产物"的, 登记顺序本身就是一条判据:
  必须在一个**只含 v41、不含 v42** 的中间产物上验一次 v44 会不会崩。
"""
import os
import sys
import re

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v44_pre"
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "ios15_fallback.py")
SCRIPT = os.path.normpath(SCRIPT)

ok = 0
bad = []


def ck(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(name + ((" :: " + detail) if detail else ""))


# ---- 1. main() 里v44 必须排在 v42 之后(静态判据, 最直接) ----
src = open(SCRIPT, encoding="utf-8").read()
main_blk = src[src.index("def main()"):]
i42 = main_blk.find('edit("Views/Chat/SelectableMarkdownView.swift", fix_needh_latch_v42')
i44 = main_blk.find('edit("Views/Chat/SelectableMarkdownView.swift", fix_diag_textframe_v44')
ck("main() 里两个登记都存在", i42 >= 0 and i44 >= 0, "i42=%d i44=%d" % (i42, i44))
ck("★v44 登记排在 v42 之后(顺序依赖, run#371 就是栽在这)",
   i42 >= 0 and i44 > i42, "i42@%d i44@%d" % (i42, i44))

# v44 也必须在 v41 之后: 诊断块插在 V41-KVOHEIGHT 之后、KVOPOST 之前
i41 = main_blk.find('edit("Views/Chat/SelectableMarkdownView.swift", fix_kvo_height_clamp_v41')
ck("★v44 登记排在 v41 之后(诊断块插在 v41 的 KVO 块里)",
   i41 >= 0 and i44 > i41, "i41@%d i44@%d" % (i41, i44))

# ---- 2. verify 里所有 index 都不得裸奔(run#371 的 ValueError 就是裸 t.index) ----
# 【判据怎么写才不是自欺】第一版写成"不许出现任何 `x = t.index(...)`",
# 结果把**前面已判过存在**的 5 处也报出来 —— 那不是缺陷, 那是正常写法。
# 真正要防的是"没判存在就直接 index"。这里改成**行距判据**: 每处 index 赋值
# 必须在往上 12 行内出现过 `in t` 的存在性检查(或在 _NEED_ANCHORS 循环里)。
vstart = src.index("def verify_textframe_v44(t):")
vsrc = src[vstart:]
vsrc = vsrc[:vsrc.index("\ndef ")]
vlines = vsrc.split("\n")
unguarded = []
for _i, _ln in enumerate(vlines):
    m = re.match(r"\s*(\w+)\s*=\s*(?:t\.index|.*\.index)\(", _ln)
    if not m:
        continue
    # 往上找 12 行, 看有没有存在性检查
    ctx = "\n".join(vlines[max(0, _i - 12):_i + 1])
    guarded = (" not in t" in ctx or "in t:" in ctx
               or "_NEED_ANCHORS" in _ln or "_a in t" in ctx)
    if not guarded:
        unguarded.append("%s@行%d" % (m.group(1), _i))
ck("verify 里没有未经存在性检查的 index(run#371 的死因)",
   not unguarded, "未守卫: %s" % unguarded)
ck("补高锚点用 _NEED_ANCHORS 循环查找",
   "for _a in _NEED_ANCHORS:" in vsrc)
ck("补高锚点缺失时给出可读错误(点名登记顺序)",
   "多半是 main() 里 v44 登记排在了 v42" in vsrc)
ck("KVOPOST 锚点缺失时给出可读错误",
   "找不到 // [V41-KVOPOST] 锚点" in vsrc)
ck("V41-KVOHEIGHT 锚点缺失时给出可读错误",
   "找不到 V41-KVOHEIGHT 补高日志" in vsrc)

# ---- 3. 在"只含 v41、不含 v42"的中间产物上跑一次 ----
# 构造法: 从干净上游拿 SelectableMarkdownView, 只打 v41, 然后直接调 v44。
# 若登记顺序有依赖, 这里就会以 ValueError/RuntimeError 崩掉。
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")
if os.path.exists(MD):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_order", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    t = open(MD, encoding="utf-8").read()
    # 剥掉 v42 留下的痕迹, 模拟"v42 还没注入"的中间态
    stripped = t.replace("self.ios15LastNeededH = _v42Need", "self.ios15LastNeededH = _vXXNeed")
    if stripped == t:
        # 该产物本来就没有 v42 痕迹(干净上游), 直接可用
        stripped = t
    try:
        m.fix_diag_textframe_v44(stripped)
        ck("在'缺 v42 赋值点'的产物上, v44 给出可读错误而非裸 ValueError", False,
           "竟然注入成功了 —— 说明 v44 不依赖 v42, 顺序判据过严?")
    except RuntimeError as e:
        msg = str(e)
        ck("缺 v42 赋值点时抛 RuntimeError(不是裸 ValueError)", True)
        ck("错误消息点明是登记顺序问题", "登记排在了 v42" in msg, msg[:90])
    except ValueError as e:
        ck("缺 v42 赋值点时抛 RuntimeError(不是裸 ValueError)", False,
           "仍是裸 ValueError: %s" % e)
else:
    ck("产物存在(跳过顺序实测)", False, MD)

print("顺序回归检查: %d/%d 通过" % (ok, ok + len(bad)))
if bad:
    print("\n失败:")
    for b in bad:
        print("  ✗ " + b)
    sys.exit(1)
print("✅ v44 登记顺序正确, 且缺锚点时报可读错误")
