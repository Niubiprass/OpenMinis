#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v50 反向测试: sabotage 必须全被拦, 且基线不误伤。

★为什么必须有: v50 判据本轮被自己证伪过两次 ——
  ① R1 第一版只查"probe 判定在下游", 真让 probe 也用了钉宽净宽, 判据全绿;
  ② R3 第一版凭推算写 3, 实际 4。
两次都是"看起来在跑、实际没钉住"。每加一条判据, 都要有对应的 sabotage
证明它真会拦 —— 否则那条判据只是装饰。

跑法: reverse_v50.py <SelectableMarkdownView.swift>
"""
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_fb():
    cands = [os.path.normpath(os.path.join(HERE, "..", "ios15_fallback.py"))]
    for c in cands:
        if os.path.exists(c):
            spec = importlib.util.spec_from_file_location("fb_rev50", c)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise RuntimeError("找不到 scripts/ios15_fallback.py")


def _seg(t, begin, end):
    i = t.find(begin)
    j = t.find(end, i + 1)
    if i < 0 or j < 0:
        raise RuntimeError("段边界找不到: %s / %s" % (begin, end))
    return i, j


def s1(x):
    """R1: probe 路径也用钉宽净宽(判据第一版真的漏了这个)。"""
    return x.replace("let _v50Pinned = _v50IsProbe ? 0 : Self.ios15PinnedW",
                     "let _v50Pinned = Self.ios15PinnedW", 1)


def s2(x):
    """R2: 删掉 floor(_v50Pinned) - 1 的 -1 余量(会触发 fillLayoutHole)。"""
    return x.replace("? floor(_v50Pinned) - 1", "? floor(_v50Pinned)", 1)


def s3(x):
    """R2b: 删掉原式 floor(lineFrag.width) - 1 的回退路径。"""
    return x.replace(": floor(lineFrag.width) - 1", ": 0", 1)


def s4(x):
    """R2c: 删掉 -1 余量(回退路径那处)。"""
    return x.replace(": floor(lineFrag.width) - 1", ": floor(lineFrag.width)", 1)


def s5(x):
    """R1b: 把 probe 提前判定整行删掉(产物编译不过, 但 R1b 只查引用看不见)。"""
    i = x.find("let _v50IsProbe = lineFrag.width >= 100_000")
    if i < 0:
        raise RuntimeError("S5 锚点找不到")
    return x[:i] + x[i:].replace("let _v50IsProbe = lineFrag.width >= 100_000\n", "", 1)


def s15(x):
    """R1c: 提前取值的哨兵改成 200_000 —— 编译得过、判据本会全绿,
    但 100_000~200_000 的 probe 会静默走进钉宽净宽路径(末行被裁回来)。"""
    return x.replace("let _v50IsProbe = lineFrag.width >= 100_000",
                     "let _v50IsProbe = lineFrag.width >= 200_000", 1)


def s16(x):
    """R1c: 提前取值的声明被挪到读它那一行**之后**(Swift use before declaration)。

    ★缩进必须**从产物数出来**: 本函数第一版按 4 空格拼锚点, 产物里是 8 空格,
    报的是"锚点找不到" —— 跟 v50 注入函数那次锚点缩进错是同一类坑。"""
    decl = "        let _v50IsProbe = lineFrag.width >= 100_000\n"
    if decl not in x:
        raise RuntimeError("S16 声明锚点找不到")
    x = x.replace(decl, "", 1)
    anchor = "            : floor(lineFrag.width) - 1\n"
    j = x.find(anchor)
    if j < 0:
        raise RuntimeError("S16 落点找不到")
    j += len(anchor)
    return x[:j] + decl + x[j:]


def s6(x):
    """R3: 新增一处 textContainer 宽度写入(v13/v34 抢宽翻车形态)。"""
    a = "TableAttachment.ios15PinnedW = _realW2"
    return x.replace(a, a + "\n            textContainer.size.width = 999", 1)


def s7(x):
    """R3b: 把某处既有宽度写入改成另一形态, 让写入点数仍为 4 但语义变了。"""
    return x.replace("TableAttachment.ios15PinnedW = _realW2",
                     "textContainer.size.width = _realW2", 1)


def s8(x):
    """B: 跨类写入漏限定类名(裸 ios15PinnedW)。"""
    return x.replace("TableAttachment.ios15PinnedW = _realW2",
                     "ios15PinnedW = _realW2", 1)


def s9(x):
    """C1: ensureLayout 被提出 if 守卫(每帧无条件排版)。"""
    return x.replace(
        "            if _ios15WRegrabbed {\n"
        "                layoutManager.ensureLayout(for: textContainer)\n"
        "            }\n",
        "            layoutManager.ensureLayout(for: textContainer)\n", 1)


def s10(x):
    """C3(核心): 记忆赋值塞回 if 内 —— 滑动时依旧不写, 等于没修。"""
    i = x.find("            self.ios15LastLaidOutW = _realW2")
    if i < 0:
        raise RuntimeError("S10 锚点找不到")
    line = "            self.ios15LastLaidOutW = _realW2\n"
    j = x.find(line, i)
    x = x[:j] + x[j + len(line):]
    return x.replace(
        "            if _ios15WRegrabbed {\n"
        "                layoutManager.ensureLayout(for: textContainer)\n"
        "            }\n",
        "            if _ios15WRegrabbed {\n"
        "                layoutManager.ensureLayout(for: textContainer)\n"
        "                self.ios15LastLaidOutW = _realW2\n"
        "            }\n", 1)


def s11(x):
    """C2: 在 C 段里写高度(推翻 v45 成果)。"""
    i = x.find("// [V50-LAIDW]")
    j = x.find("// [IOS15-FIX-RELC v28]", i)
    seg = x[i:j].replace("self.ios15LastLaidOutW = _realW2",
                         "self.ios15LastLaidOutW = _realW2\n            self.frame.size.height = 1", 1)
    return x[:i] + seg + x[j:]


def s12(x):
    """A: 又塞一个 v49 式的假 API(编译级)。"""
    return x.replace("floor(_v50Pinned) - 1",
                     "self.textContainer.bounds.width - 1", 1)


def s13(x):
    """D: NSLog 没被 do 包住(trailing closure 陷阱, v42 实踩 8 个编译错误)。"""
    i = x.find("NSLog(\"[V50-LAIDW]")
    if i < 0:
        raise RuntimeError("S13 锚点找不到")
    j = x.rfind("do {", 0, i)
    k = x.rfind("}\n", 0, i)
    # 删掉包着它的那个 do { —— 让 NSLog 裸露在函数体里
    return x[:j] + x[j + 4:]


def s14(x):
    """诊断字段被删(装机后就看不到 laidW 是否真写进去了)。"""
    return x.replace("laidW=%.1f regrabbed=%d len=%d", "w=%.1f len=%d", 1)


CASES = [
    ("S1  probe 路径也用钉宽净宽(R1 首次真漏)", s1, "probe"),
    ("S2  钉宽宽漏 -1 余量", s2, "-1"),
    ("S3  回退路径被改成 width 0", s3, "回退"),
    ("S4  回退路径漏 -1 余量", s4, "-1"),
    ("S5  probe 判定声明被删(编译不过)", s5, "声明"),
    ("S6  新增一处容器宽写入", s6, "写入点"),
    ("S7  通道写入偷换成宽度写入", s7, "紧邻"),
    ("S8  跨类写入漏 TableAttachment. 限定", s8, "未限定"),
    ("S9  ensureLayout 被提出守卫", s9, "ensureLayout"),
    ("S10 记忆赋值塞回 if 内(C 等于没修)", s10, "仍关在"),
    ("S11 C 段里写高度", s11, "高度"),
    ("S12 塞入不存在的 API", s12, "bounds"),
    ("S13 诊断 NSLog 裸露(trailing closure)", s13, "do 块"),
    ("S14 诊断字段被删", s14, "缺诊断字段"),
    ("S15 提前取值哨兵改成 200_000", s15, "哨兵"),
    ("S16 提前取值声明挪到使用之后", s16, "use before declaration"),
]


def run_checks(t):
    """跑 v50 全部判据, 返回失败原因列表(空 = 全过)。"""
    fb = load_fb()
    errs = []
    for name, fn in (("verify_width_source_unify_v50", fb.verify_width_source_unify_v50),
                     ("verify_slide_relayout_v50", fb.verify_slide_relayout_v50)):
        try:
            fn(t)
        except Exception as e:
            errs.append("%s: %s" % (name, str(e)[:200]))
    import subprocess
    sc = os.path.join(HERE, "scope_check_v50.py")
    if os.path.exists(sc):
        import tempfile
        tf = tempfile.NamedTemporaryFile("w", suffix=".swift", delete=False, encoding="utf-8")
        tf.write(t)
        tf.close()
        r = subprocess.run([sys.executable, sc, tf.name], capture_output=True, text=True)
        os.unlink(tf.name)
        if r.returncode != 0:
            lines = [l.strip("  ★ ") for l in (r.stdout + r.stderr).split("\n")
                     if l.strip().startswith("★")]
            errs.append("scope: " + ("; ".join(lines[:3]) if lines else "BAD"))
    return errs


def main():
    if len(sys.argv) < 2:
        print("用法: reverse_v50.py <SelectableMarkdownView.swift>")
        return 3
    md = sys.argv[1]
    if not os.path.isfile(md):
        print("找不到产物: %s" % md)
        return 3
    base = open(md, encoding="utf-8").read()

    # ---- 基线不误伤 ----
    base_errs = run_checks(base)
    if base_errs:
        print("❌ ★基线本身就不通过 —— 反向测试无从谈起(判据有 bug):")
        for e in base_errs:
            print("   ", e[:220])
        return 1
    print("基线: 全部判据通过 ✅")

    caught, missed = 0, []
    for name, fn, want in CASES:
        try:
            mutated = fn(base)
        except Exception as e:
            print("  ⚠️  %-38s 构造失败: %s" % (name, str(e)[:70]))
            missed.append(name + "(构造失败)")
            continue
        if mutated == base:
            print("  ⚠️  %-38s ★sabotage 没改动文件 —— 锚点失效" % (name, ""))
            missed.append(name + "(锚点失效)")
            continue
        errs = run_checks(mutated)
        if errs:
            caught += 1
            print("  ✅ %-38s 拦下" % name)
        else:
            missed.append(name)
            print("  ❌ %-38s ★未被拦截" % name)

    print("\n%d/%d 条 sabotage 全被拦截" % (caught, len(CASES)))
    if missed:
        print("★未被拦: %s" % ", ".join(missed))
        return 1
    print("✅ 基线不误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
