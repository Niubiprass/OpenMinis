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

【本地该用哪个基线 —— 这是本测试最实用的一条】
仓库里的 `src/ios` 存的是**干净未打补丁的上游源码**（不含 V41-KVOHEIGHT /
V42-LATCH / V43-NETW 任何标记）。把它整个复制到临时目录, 塞进
scripts/ios15_fallback.py, 按 main() 顺序跑一遍, 才是 CI 的真实条件。
`/tmp/ci_v4x` 那些上一版流水线产物**不能用**: 它们已经打过 v41/v42/v43,
任何登记顺序都找得到锚点, 恰好精确掩盖顺序依赖这一类 bug。
"""
import os
import sys
import re

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v44_pre"
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "ios15_fallback.py")
SCRIPT = os.path.normpath(SCRIPT)
# 干净上游源码的SelectableMarkdownView（未打任何补丁）
CLEAN_MD = os.path.join(os.path.dirname(SCRIPT), "..", "src", "ios",
                        "Views", "Chat", "SelectableMarkdownView.swift")
CLEAN_MD = os.path.normpath(CLEAN_MD)

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

# ---- 3. 在**干净上游源码**上按 main() 顺序真跑一遍 ----
# 这才是 CI 的真实条件。run#37118226923 之前所有本地验证都用的旧产物,
# v42 早被打过, 于是无论登记顺序都找得到锚点 —— 顺序依赖被完整掩盖。
# 这里换成干净源码: 先打 v41, 再打 v42, 最后打 v44, 三步必须全部成功。
if os.path.exists(CLEAN_MD):
    import importlib.util
    import tempfile
    import shutil
    spec = importlib.util.spec_from_file_location("fb_order2", SCRIPT)
    m2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m2)
    clean = open(CLEAN_MD, encoding="utf-8").read()
    # 前置: 干净源码里不该有**v42 特有的**痕迹, 否则基线选错了。
    # 【别查错字段】ios15LastNeededH 是**上游自带**的(上游 v18 就用它在记needH,
    #   声明在 5391 行 `var ios15LastNeededH: CGFloat = 0`), 不是我们补丁引入的。
    #   真正的判据是 v42 注入的那个**带 self. 的 KVO 内赋值点**:
    #   `self.ios15LastNeededH = _v42Need` —— 上游是 `ios15LastNeededH = _needH`(无 self.)。
    ck("基线是干净上游(不含 V41-KVOHEIGHT)", "V41-KVOHEIGHT" not in clean,
       "这个文件已经打过补丁了, 不能当顺序回归的基线")
    ck("基线是干净上游(不含 v42 的 KVO 赋值点)",
       "self.ios15LastNeededH = _v42Need" not in clean,
       "v42 已经打过, 顺序回归会失去意义")

    steps = []
    t = clean
    try:
        t = m2.fix_kvo_height_clamp_v41(t)
        steps.append("v41")
        t = m2.fix_needh_latch_v42(t)
        steps.append("v42")
        t = m2.fix_diag_textframe_v44(t)
        steps.append("v44")
        ck("干净源码上按 v41→v42→v44 顺序注入成功", True)
    except Exception as e:  # noqa: BLE001
        ck("干净源码上按 v41→v42→v44 顺序注入成功", False,
           "卡在 %s: %s: %s" % (steps[-1] if steps else "起点",
                                type(e).__name__, str(e)[:120]))
    if len(steps) == 3:
        # 位置必须正确: v42赋值 < v41补高日志 < v44诊断 < KVOPOST
        a = t.find("self.ios15LastNeededH = _v42Need")
        b = t.find('NSLog("[V41-KVOHEIGHT]')
        c = t.find("// [V44-TEXTFRAME] 见函数 docstring")
        d = t.find("// [V41-KVOPOST]")
        ck("干净源码上位置正确 v42 < v41 < v44 < KVOPOST",
           -1 not in (a, b, c, d) and a < b < c < d,
           "a=%d b=%d c=%d d=%d" % (a, b, c, d))
        ck("干净源码上诊断块只有一段",
           t.count('NSLog("[V44-TEXTFRAME]') == 1)
else:
    ck("干净上游源码存在(跳过实测)", False, CLEAN_MD)

print("顺序回归检查: %d/%d 通过" % (ok, ok + len(bad)))
if bad:
    print("\n失败:")
    for b in bad:
        print("  ✗ " + b)
    sys.exit(1)
print("✅ v44 登记顺序正确, 干净源码上可完整注入")
