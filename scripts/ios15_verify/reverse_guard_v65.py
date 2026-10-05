#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_guard_v65.py —— v65 反向验证（10 条 sabotage）。

纪律（docs/verify-discipline.md §16/§17）：
  §16 sabotage 必须**自己证明"它真的破坏了什么"** —— 破坏后 base==改后
       的，必须独立计为空测(voided)，不能算漏过。
  §17 反向必须覆盖"换个名字继续错" —— 只逐字匹配一种写法的判据是假的。

BASE 独立计数，不计入 passed。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run_verify(root):
    env = dict(os.environ)
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "verify_guard_v65.py"),
         os.path.join(root, "src/ios/Shared/NSTextContainerSetSizeGuard.m")],
        capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------- 10 条 sabotage ----------------
def s1_restore_merged_reject(t):
    """把拆开的两段合回「NaN/inf/负 尺寸一个 if 全部丢弃」。

    问: 只做熔断豁免、不拆丢弃分支 —— 判据拦得住吗?
    这正是旧版代码的形态(61 次丢弃 = 卡字)。
    """
    old = re.search(
        r"    if \(!isfinite\(newSize\.width\) \|\| !isfinite\(newSize\.height\)\) \{"
        r".*?\n    \}\n", t, re.S)
    if not old:
        raise AssertionError("锚点1: NaN/inf 硬拒分支没找到")
    merged = ("    if (!isfinite(newSize.width) || !isfinite(newSize.height) ||\n"
              "        newSize.width < 0 || newSize.height < 0) {\n"
              "        gShortCircuitCount += 1;\n"
              "        return;\n"
              "    }\n")
    return t[:old.start()] + merged + t[old.end():]


def s2_put_back_return(t):
    """修正分支内加 return —— 改回「丢弃」语义。

    ★为什么插在修正块**内部**而不是块外:
      插在块外(修正块与 IMP 调用之间)会与合法的风暴熔断 SKIP 分支里的
      return 混在一起, 判据无法区分二者 —— 那不是判据该管的射程。
      插在块内语义完全等价(TextKit 同样收不到修正值), 且无歧义。
    """
    old = "            newSize.height = fabs(newSize.height);"
    if old not in t:
        raise AssertionError("锚点2: fabs 修正语句没找到")
    new = ("            newSize.height = fabs(newSize.height);\n"
           "            return;  /* sabotage: 修正后仍丢弃 */")
    t = t.replace(old, new, 1)
    return t


def s3_storm_no_gate(t):
    """熔断退回无条件 —— 恢复「真实排版也计入预算」。"""
    old = ("    if (newSize.height >= 2000.0) {\n"
           "        s->commitCount += 1;\n"
           "        if (s->commitCount > kStormForwardLimit) {\n"
           "            s->stormed = YES;\n"
           "        }\n"
           "    }")
    if old not in t:
        raise AssertionError("锚点3: 哨兵门槛块没找到")
    new = ("    s->commitCount += 1;\n"
           "    if (s->commitCount > kStormForwardLimit) {\n"
           "        s->stormed = YES;\n"
           "    }")
    return t.replace(old, new)


def s4_drop_fabs(t):
    """去掉负高取绝对值 —— 负高原样喂回 TextKit。"""
    old = "            newSize.height = fabs(newSize.height);"
    if old not in t:
        raise AssertionError("锚点4: fabs 没找到")
    return t.replace(old, "            newSize.height = newSize.height;")


def s5_gate_after_commit(t):
    """门槛挪到 commitCount 自增**之后** —— 东西都在位，但顺序让它不生效。

    ★这是 §17「换个写法继续错」的变体: 判据若只查"门槛存在",
      查不出"门槛在自增之后于是拦不住"。
    """
    old = ("    if (newSize.height >= 2000.0) {\n"
           "        s->commitCount += 1;\n"
           "        if (s->commitCount > kStormForwardLimit) {\n"
           "            s->stormed = YES;\n"
           "        }\n"
           "    }")
    new = ("    s->commitCount += 1;\n"
           "    if (s->commitCount > kStormForwardLimit) {\n"
           "        s->stormed = YES;\n"
           "    }\n"
           "    if (newSize.height >= 2000.0) {\n"
           "        /* sabotage: 门槛在自增之后, 已经来不及了 */\n"
           "    }")
    if old not in t:
        raise AssertionError("锚点5: 哨兵门槛块没找到")
    return t.replace(old, new)


def s6_rename_ceiling_literal(t):
    """把 2000.0 换成 2001.0 —— 注释改了常量没同步。"""
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点6: 哨兵门槛字面量没找到")
    return t.replace(old, "    if (newSize.height >= 2001.0) {")


def s7_only_one_component(t):
    """只判高度不判宽度 —— 0.0x-8.0 的宽度 0 得不到修正。"""
    old = "    if (newSize.width <= 0 || newSize.height <= 0) {"
    if old not in t:
        raise AssertionError("锚点7: 修正进入条件没找到")
    return t.replace(old, "    if (newSize.height <= 0) {")


def s8_split_into_two_ifs(t):
    """两个分量拆到两个独立 if —— 半吊子修法。"""
    old = "    if (newSize.width <= 0 || newSize.height <= 0) {"
    if old not in t:
        raise AssertionError("锚点8: 修正进入条件没找到")
    return t.replace(old, "    if (newSize.width <= 0) {\n    }\n    if (newSize.height <= 0) {")


def s9_scope_ref_ceiling(t):
    """★引用 kProbeHeightCeiling —— 本轮真实犯过并当场抓住的编译红。

    kProbeHeightCeiling 是函数体内局部 const，V65-STORM 段落引用它
    会编译失败。这条把那个错误固化下来。
    """
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点9: 哨兵门槛没找到")
    return t.replace(old, "    if (newSize.height >= kProbeHeightCeiling) {")


def s10_missing_identifier(t):
    """★引用不存在的标识符 —— run#159 的真实错误形态。

    判据全绿（文本在位）但编译红（符号不存在）。
    """
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点10: 哨兵门槛没找到")
    return t.replace(old, "    if (newSize.height >= kV65SentinelFloor) {")


SABS = [
    ("S1", "恢复合并式丢弃(NaN/inf/负一个if全丢)", s1_restore_merged_reject),
    ("S2", "修正分支末尾加 return(改回丢弃)", s2_put_back_return),
    ("S3", "熔断退回无条件(真实排版也计费)", s3_storm_no_gate),
    ("S4", "去掉 fabs(负高原样喂回)", s4_drop_fabs),
    ("S5", "门槛挪到自增之后(顺序让它不生效)", s5_gate_after_commit),
    ("S6", "哨兵字面量改 2001(常量与注释不同步)", s6_rename_ceiling_literal),
    ("S7", "只判高度不判宽度(0 宽不修)", s7_only_one_component),
    ("S8", "两分量拆成两个独立 if", s8_split_into_two_ifs),
    ("S9", "引用 kProbeHeightCeiling(作用域外,编译红)", s9_scope_ref_ceiling),
    ("S10", "引用不存在的 kV65SentinelFloor(编译红)", s10_missing_identifier),
]


def main():
    src_root = sys.argv[1] if len(sys.argv) > 1 else "."
    guard_rel = "src/ios/Shared/NSTextContainerSetSizeGuard.m"
    base = os.path.join(src_root, guard_rel)
    if not os.path.isfile(base):
        print("✗ 找不到 %s" % base)
        return 2
    orig = open(base, encoding="utf-8").read()

    rc, out = run_verify(src_root)
    print("BASE: rc=%d  %s" % (rc, out.splitlines()[-1] if out else ""))
    if rc != 0:
        print("✗ BASE 未通过, 反向无意义(判据自己坏了)")
        return 2
    print("BASE 通过(独立计数, 不计入 passed)\n")

    passed = 0
    caught = 0
    voided = []
    tmp = tempfile.mkdtemp(prefix="v65rev")
    try:
        for name, desc, fn in SABS:
            # --- sabotage 自己必须证明"真的破坏了什么" ---
            try:
                bad = fn(orig)
            except AssertionError as e:
                print("  %-4s ⚠️ 空测(sabotage 自身失败): %s" % (name, e))
                voided.append(name)
                continue
            if bad == orig:
                print("  %-4s ⚠️ 空测(sabotage 没有改动任何东西)" % name)
                voided.append(name)
                continue
            # 独立计数: sabotage 后判据必须失败
            d = os.path.join(tmp, name)
            os.makedirs(os.path.join(d, "src/ios/Shared"), exist_ok=True)
            shutil.copytree(os.path.join(src_root, "src/ios"),
                            os.path.join(d, "src/ios"), dirs_exist_ok=True)
            with open(os.path.join(d, guard_rel), "w", encoding="utf-8") as f:
                f.write(bad)
            rc2, out2 = run_verify(d)
            if rc2 == 0:
                print("  %-4s ❌ 漏过  %s" % (name, desc))
            else:
                caught += 1
                passed += 1
                last = out2.splitlines()[0] if out2 else ""
                print("  %-4s ✅ 拦下  %s" % (name, desc))
                print("        └─ %s" % last[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n反向: %d 拦下 / %d 漏过 / %d 空测" %
          (caught, len(SABS) - caught - len(voided), len(voided)))
    if voided:
        return 3
    if caught != len(SABS):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
