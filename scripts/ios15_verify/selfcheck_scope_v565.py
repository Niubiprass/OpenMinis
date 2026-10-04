#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_assert_v565.py 里 scope 层的 sabotage 自证。

【为什么必须单独证】
  v46 探针的教训: 全部判据一直全绿, 而探针装在 TableAttachment 里,
  对 CodeBlockAttachment 完全失明。
  ⇒ 「判据全绿」不等于「判据在测对的东西」。
  ⇒ scope 层是 v565 **新写**的, 若不做反向测试, 它和 v46 那些绿一样
    不可信 —— 甚至更不可信, 因为它连历史包袱都没有。

本脚本对 scope 层注入 6 类破坏, 逐条确认**必须报红**:
  B1 改字段类型 (CGFloat -> Double 声明错乱, 或直接删字段)
  B2 诊断段内塞 invalidateLayout()
  B3 诊断段内给 height 赋值
  B4 NSLog 删一个实参 (槽位 11 / 实参 10)
  B5 NSLog 删一个 %.1f 槽位 (槽位 10 / 实参 11)
  B6 把 %.1f 的实参从 Double(height) 换成裸 height (CGFloat 过 CVarArg 编译错)
  BASE 未改动产物必须通过

★纪律: 新写的判据, 先证明它会红, 再相信它的绿。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "ci_assert_v565.py")

MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


# ---- B1 类型/字段缺失 ----
@case("B1 删掉 attV565ViewH 字段声明")
def b1(t):
    return t.replace("var attV565ViewH: CGFloat = -1\n", "", 1)


@case("B2 诊断段内塞 invalidateLayout()")
def b2(t):
    anchor = "do {\n            struct _V565Log"
    return t.replace(
        anchor,
        "do {\n            self.invalidateLayout()\n            struct _V565Log",
        1)


@case("B3 诊断段内给 height 赋值")
def b3(t):
    anchor = "do {\n            struct _V565Log"
    return t.replace(
        anchor,
        "do {\n            height = height - 1\n            struct _V565Log",
        1)


@case("B4 删一个 NSLog 实参")
def b4(t):
    return t.replace("Double(self.attV565CachedRaw), _V565Log.n)",
                     "_V565Log.n)", 1)


@case("B5 删一个格式串槽位")
def b5(t):
    return t.replace("viewW=%.1f ", "viewW=%.0f ", 1)


@case("B6 %.1f 实参去掉 Double() 包装")
def b6(t):
    return t.replace("Double(attV565ViewH), Double(attV565ViewW)",
                     "attV565ViewH, attV565ViewW)", 1)


def run_scope(t):
    """直接调 scope_check —— 只测 scope 层, 不牵扯 core/sab。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cav565", TARGET)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.scope_check(t)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    md = os.path.join(root, MD_REL)
    if not os.path.exists(md):
        sys.stderr.write("找不到产物: %s\n" % md)
        return 3
    base = open(md, encoding="utf-8").read()

    ok, bad = [], []
    # BASE
    b = run_scope(base)
    if b:
        bad.append(("BASE 未改动产物必须通过", b[0]))
    else:
        ok.append(("BASE 未改动产物必须通过", "基线无误伤"))

    for name, fn in CASES:
        t2 = fn(base)
        if t2 == base:
            bad.append((name, "sabotage 没改动任何字节 —— 锚点已失效, 白测"))
            continue
        b = run_scope(t2)
        if b:
            ok.append((name, b[0][:90]))
        else:
            bad.append((name, "scope 判据没报红 —— 判据是废的"))

    print("=" * 68)
    for n, m in ok:
        print("✅ %-38s %s" % (n, m))
    for n, m in bad:
        print("❌ %-38s %s" % (n, m))
    print("=" * 68)
    print("scope 层自证: %d 拦下, %d 漏过" % (len(ok), len(bad)))
    if bad:
        print("⇒ scope 层有洞, 别信它的绿。")
        return 1
    print("✅ scope 层全部 sabotage 都被拦下, 且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())