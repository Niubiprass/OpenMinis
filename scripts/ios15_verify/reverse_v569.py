#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v56.9 反向测试 —— 证明 verify_kvo_debt_v569 真的能抓住错误。

★这个版本为什么必须有反向测试:
  v56.9 的修法是「在抑制条件上加一个几何判据」。这类修改最危险的形态是
  **声明了判据却没接进 if** —— 代码看起来修好了, 行为一字未变,
  而判据若只查「`_v56noDebt` 这个符号在不在」就会全绿放过。
  S3 专门钉这一条。

用法:
    python3 reverse_v569.py
退出码 0 = 全部 sabotage 都被拦下且基线无误伤。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FALLBACK = os.path.join(HERE, os.pardir, "ios15_fallback.py")


def load_fallback():
    src = open(FALLBACK, encoding="utf-8").read()
    src = src.replace(
        "\n    verify_kvo_debt_v569(t)\n    return t",
        "\n    return t",
    )
    head = src.split("if __name__")[0]
    g = {}
    exec(compile(head, "fallback", "exec"), g)
    return g


def build_baseline(g):
    """当前产物(已被 v56.9 改过)就是基线。

    ★与 v568 的区别: v568 的 baseline 要从干净上游重新注入, 因为要证明
      「注入函数本身可用」。v569 的改动落在 SelectableMarkdownView 上,
      而那个文件被 v30/v32~v53/v56.1 等**十几个版本**反复改过 ——
      从干净上游跑一遍会丢掉全部历史改动, 得到的不是本项目的真实产物。
      ⇒ 直接用 src/ios 下的产物做基线。
    """
    p = os.path.join(HERE, os.pardir, os.pardir,
                     "src/ios/Views/Chat/SelectableMarkdownView.swift")
    return open(p, encoding="utf-8").read()


# ----------------------------------------------------------------------
# sabotage
# ----------------------------------------------------------------------
def _s1_undo(t):
    """完全退回 v56.1: 去掉几何判据, 抑制条件回到只看 dup。"""
    t = t.replace("            if _v56dup && _v56noDebt {",
                  "            if _v56dup {", 1)
    t = t.replace("            let _v56noDebt = f.size.height + 0.5 >= _v42Need\n",
                  "", 1)
    return t


def _s2_declare_not_wired(t):
    """★最危险的形态: 声明了 _v56noDebt 但**不接进 if**。

    行为与 v56.1 完全相同, 但代码里确实有那个符号 ——
    只查「符号在不在」的判据会全绿放过。
    """
    t = t.replace("            if _v56dup && _v56noDebt {",
                  "            if _v56dup {", 1)
    return t


def _s3_inverted(t):
    """判据取反: 变成「几何欠着才跳过」—— 语义正好反了。"""
    return t.replace(
        "let _v56noDebt = f.size.height + 0.5 >= _v42Need",
        "let _v56noDebt = f.size.height + 0.5 < _v42Need", 1)


def _s4_wrong_geometry_source(t):
    """几何判据用错了量: 拿 svH 而不是 f.size.height。"""
    return t.replace(
        "let _v56noDebt = f.size.height + 0.5 >= _v42Need",
        "let _v56noDebt = f.size.height + 0.5 >= 1000.0", 1)


def _s5_drop_skip_counter(t):
    """把抑制分支的计数器删掉 —— 本版只该改条件, 不该掏空分支。"""
    return t.replace("                _V56KVOW.skipped &+= 1\n", "", 1)


def _s6_drop_skip_log(t):
    """把 skipSame 的日志删掉。"""
    return t.replace('NSLog("[V56-KVO] skipSame svH=%.1f needH=%.1f n=%u",',
                     'NSLog("[V56-KVO] other svH=%.1f needH=%.1f n=%u",', 1)


def _s7_strip_mark(t):
    """标记被摘掉。"""
    return t.replace("[V569-DEBT]", "[T-debt]")


def _s8_delete_branch(t):
    """整个 skipSame 分支被删 —— 退化成「每帧都写」。"""
    i = t.find("if _v56dup && _v56noDebt {")
    assert i > 0, "S8 锚点失效: 找不到 skipSame 分支头"
    # 找该分支的 else if 起点(它是本 if 的 `} else if` 结构)
    j = t.find("} else if _v42Need > 1, f.size.height + 0.5 < _v42Need {", i)
    assert j > 0, "S8 锚点失效: 找不到分支尾的 else if"
    # 删掉 if 体, 保留 else if(即让欠账分支变成无条件)
    return t[:i] + "if true {" + t[j:]


SABOTAGES = [
    ("S1", "完全退回 v56.1", _s1_undo, "抑制条件又只看值是否重复"),
    ("S2", "声明 _v56noDebt 但不接进 if", _s2_declare_not_wired,
     "★最危险: 代码看着修了, 行为一字未变"),
    ("S3", "几何判据取反", _s3_inverted, "语义反了: 欠账时才跳过"),
    ("S4", "几何判据用错量", _s4_wrong_geometry_source, "阈值写死, 不表达「已达标」"),
    ("S5", "删掉 skipped 计数", _s5_drop_skip_counter, "抑制分支被掏空"),
    ("S6", "改掉 skipSame 日志", _s6_drop_skip_log, "抑制分支被掏空"),
    ("S7", "标记被摘掉", _s7_strip_mark, "无法证明注入到位"),
    ("S8", "整个 skipSame 分支被删", _s8_delete_branch, "退化成每帧都写"),
]


def main():
    g = load_fallback()
    verify = g["verify_kvo_debt_v569"]
    base = build_baseline(g)

    try:
        verify(base)
        print("✅ BASE                                     基线无误伤")
    except Exception as e:
        print("❌ BASE                                     基线被误伤: %s" % e)
        return 1

    blocked = 0
    missed = []

    for name, desc, fn, why in SABOTAGES:
        try:
            sabotaged = fn(base)
        except Exception as e:
            print("❌ %-4s  %-38s sabotage 自身失败: %s" % (name, desc, e))
            missed.append(name)
            continue

        if sabotaged == base:
            print("❌ %-4s  %-38s 锚点失效, 白测" % (name, desc))
            missed.append(name)
            continue

        try:
            verify(sabotaged)
        except Exception as e:
            blocked += 1
            print("✅ %-4s  %-38s → %s" % (name, desc, str(e)[:50]))
            continue

        print("❌ %-4s  %-38s **判据没报红** (应命中: %s)" % (name, desc, why))
        missed.append(name)

    print()
    print("v569 反向: %d 拦下, %d 漏过" % (blocked, len(missed)))
    if missed:
        print("❌ 漏过: %s" % ", ".join(missed))
        return 1
    print("✅ 全部 sabotage 都被拦下, 且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
