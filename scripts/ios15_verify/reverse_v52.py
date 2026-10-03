#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v52 反向证伪: sabotage 必须**全被拦下**, 且基线不误伤。

跑法: reverse_v52.py <产物根目录 或 SelectableMarkdownView.swift> [--sab]

★为什么必须 sab(v50/v51 两次判据自己被证伪的教训):
  v50 那一轮, 判据 R1 第一版只查"probe 判定在下游", 结果首版真让 probe
  也用了钉宽净宽, 判据却全绿 —— "看起来在跑、实际没钉住"。
  ⇒ 本版每条红线都配了对应的破坏法, 破坏后判据必须变红。

本版的红线与它的破坏法:

  A  闸门只回落不改几何     → S1 在闸门段写 textContainer / S2 写 frame
  A2 三处判据齐全          → S3 删贴边容差 / S4 删记忆位对照 / S5 删全宽白名单
  A3 记忆位只记放行过的值  → S6 去掉 `sane != 0` 前提
  A4 记忆位回落而非回落全屏 → S7 回落改成 `_cvW`
  B  `_svW` 改读闸门结果    → S8 把旧 bounds 那一行留着
  C  诊断七字段齐全         → S9 删 picked / S10 删 sane
  D  快照在测高之前         → S11 把快照挪到测高之后(撑高已改过高度)
  E  判据用快照而非当前高   → S12 判据改回读当前高度(= v38-A 原始死法)
  F  记忆位声明形态         → S13 声明成 static / S14 删声明
  G  借用 flag 机制保留     → S15 删 invalidateCellSizeIfNeeded 调用
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"


def resolve(target):
    if os.path.isfile(target):
        return os.path.abspath(target)
    p = os.path.join(target, MD_REL)
    return os.path.abspath(p) if os.path.exists(p) else None


def assert_replaced(src, old, new, name):
    """做一次**会自检**的替换: 锚点没命中就直接炸, 不许静默返回原文。

    ★v49 H1/H2 踩过: 锚点写死缩进, 结构一变 `str.replace` 静默返回原串
      ⇒ sabotage 变 no-op ⇒ 判据全绿 ⇒ 输出"未被拦截"。
      真相是"锚点失效", 两者输出相同但修法完全相反。
    ⇒ 纪律: **锚点失效必须自己报错**, 且和"漏放"用不同的措辞。
    """
    if old not in src:
        raise AssertionError("★锚点失效: %s 的替换目标不在产物里 "
                             "(缩进变了? 形态变了?)\n  目标=%r"
                             % (name, old[:90]))
    out = src.replace(old, new, 1)
    if out == src:
        raise AssertionError("★锚点失效: %s 替换后产物未变" % name)
    return out


# ---- 探针: 调 fallback 的 verify + scope_check, 看是否变红 ----
def _load_fb():
    for c in (os.path.join(os.path.dirname(HERE), "ios15_fallback.py"),
              os.path.normpath(os.path.join(HERE, "..", "..", "ios15_fallback.py"))):
        if os.path.exists(c):
            import importlib.util
            spec = importlib.util.spec_from_file_location("fb_v52r", c)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    return None


FB = _load_fb()


def _core_ok(path, text):
    if FB is None:
        return False, "找不到 ios15_fallback.py"
    hits = []
    for nm, fn in (("宽度闸门", getattr(FB, "verify_width_sane_gate_v52", None)),
                   ("欠账自愈", getattr(FB, "verify_debtguard_snapshot_v52", None))):
        if fn is None:
            return False, "判据函数缺失"
        try:
            fn(text)
        except Exception as e:
            hits.append("%s: %s" % (nm, str(e)[:60]))
    if hits:
        return True, "; ".join(hits)
    return False, ""


def _scope_ok(path, text):
    sc = os.path.join(HERE, "scope_check_v52.py")
    r = subprocess.run([sys.executable, sc, path], capture_output=True, text=True)
    if r.returncode == 0:
        return False, ""
    lines = [l for l in (r.stdout + r.stderr).strip().split("\n") if "★" in l]
    return True, (lines[0][:70] if lines else "scope 非零退出")


PROBES = (_core_ok, _scope_ok)


def _cases(t):
    cases = []

    # ---------- A: 闸门只回落不改几何 ----------
    def s1(x):
        old = """            if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {
                ios15LastSaneContentW = _v52w
            }"""
        new = """            if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {
                ios15LastSaneContentW = _v52w
            }
            textContainer.size.width = _v52w"""
        return assert_replaced(x, old, new, "S1")
    cases.append(("S1 闸门段内写 textContainer 宽(自己抢宽)", s1))

    def s2(x):
        old = "            let _svW = _v52w"
        new = """            var _rf52 = frame
            _rf52.size.width = _v52w
            frame = _rf52
            let _svW = _v52w"""
        return assert_replaced(x, old, new, "S2")
    cases.append(("S2 闸门段内写 frame 宽(与 SwiftUI 争布局)", s2))

    # ---------- A2: 三处判据必须齐全 ----------
    def s3(x):
        old = "if abs(_v52w - (_cvW - 32)) > 2 {"
        return assert_replaced(x, old, "if false {", "S3")
    cases.append(("S3 删贴边分支的容差判据", s3))

    def s4(x):
        old = "if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {"
        return assert_replaced(x, old, "if !_v52ok {", "S4")
    cases.append(("S4 删记忆位对照判据", s4))

    def s5(x):
        # ★v53 起锚点改了形态: v52 原本是「声明即判据」
        #     var _v52ok = abs(_v52w - _cvW) <= 2
        # v53-C1 为了把判别结论暴露给记忆位写入, 拆成了
        #     var _v52ok = true            ← 声明
        #     _v52ok = abs(_v52w - _cvW) <= 2  ← 判据(仍要打头, 少一次判定)
        # ⇒ 锚点必须跟着换成**赋值**形式, 否则 sabotage 报「锚点失效」——
        #   而锚点失效是假绿: 它只说明串变了, 不代表被测代码变好了。
        # ⇒ 纪律: **跨版共存的老 sabotage, 锚点要选语义锚(那一行判据),
        #   不要锚整块声明**; 声明形态会随版本拆/合, 判据行不会消失。
        old = "                _v52ok = abs(_v52w - _cvW) <= 2"
        new = "                _v52ok = true"
        return assert_replaced(x, old, new, "S5")
    cases.append(("S5 删全宽白名单判据", s5))

    # ---------- A3: 记忆位只记放行过的值 ----------
    def s6(x):
        old = "if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {"
        new = "if _v52w > 100, abs(_v52w - _cvW) > 2 {"
        return assert_replaced(x, old, new, "S6")
    cases.append(("S6 记忆位写入去掉 sane 前提(污染值进记忆)", s6))

    # ---------- A4: 回落目标是记忆位而非全屏宽 ----------
    def s7(x):
        old = "_v52w = ios15LastSaneContentW ?? (_cvW - 32)"
        return assert_replaced(x, old, "_v52w = _cvW", "S7")
    cases.append(("S7 回落改成全屏宽(v13/v34 超框翻车形态)", s7))

    # ---------- B: _svW 必须改读闸门结果 ----------
    def s8(x):
        old = "            let _svW = _v52w"
        new = """            let _svW = superview?.bounds.width ?? 0
            _ = _v52w"""
        return assert_replaced(x, old, new, "S8")
    cases.append(("S8 _svW 仍读 bounds(B 没生效)", s8))

    # ---------- C: 诊断字段 ----------
    def s9(x):
        old = '_edgeTouch ? 1 : 0, _v52sane, _v52w, self.textStorage.length)'
        new = '_edgeTouch ? 1 : 0, _v52w, self.textStorage.length)'
        return assert_replaced(x, old, new, "S9")
    cases.append(("S9 诊断删 sane 字段(看不出闸门是否放行)", s9))

    def s10(x):
        old = "rawW=%.1f frmW=%.1f cvW=%.1f edge=%d sane=%d picked=%.1f len=%d"
        return assert_replaced(x, old, "rawW=%.1f frmW=%.1f cvW=%.1f edge=%d picked=%.1f len=%d", "S10")
    cases.append(("S10 诊断删 sane 占位符", s10))

    # ---------- D: 快照必须在测高之前 ----------
    def s11(x):
        old = """            let _v52PreSVH = superview?.frame.size.height ?? 0
            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height"""
        new = """            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height
            let _v52PreSVH = superview?.frame.size.height ?? 0"""
        return assert_replaced(x, old, new, "S11")
    cases.append(("S11 快照挪到测高之后(拿到的是撑过的高度)", s11))

    # ---------- E: 判据必须用快照 ----------
    def s12(x):
        old = """               _v52PreSVH > 1,
               _v52PreSVH < _needH - 0.5 {"""
        new = """               let _svH = superview?.frame.size.height, _svH > 1,
               _svH < _needH - 0.5 {"""
        return assert_replaced(x, old, new, "S12")
    cases.append(("S12 判据改回读当前高度(= v38-A 原始死法)", s12))

    # ---------- F: 记忆位声明形态 ----------
    def s13(x):
        old = "    var ios15LastSaneContentW: CGFloat?"
        return assert_replaced(x, old, "    static var ios15LastSaneContentW: CGFloat?", "S13")
    cases.append(("S13 记忆位声明成 static(跨气泡污染)", s13))

    def s14(x):
        old = "    var ios15LastSaneContentW: CGFloat?"
        return assert_replaced(x, old, "", "S14")
    cases.append(("S14 删掉记忆位声明(引用不存在的标识符)", s14))

    # ---------- G: 借用 flag 的机制必须保留 ----------
    def s15(x):
        # ★v53-C2 在这两行之间插了 3 行欠账上报注释, 原三行连锚失效。
        #   改成**锚两处单行**: 只要求「置 flag」与「恢复 flag」都还在,
        #   中间夹什么(注释、诊断、上报)都不断言 —— 那不是本条要测的东西。
        #   本条测的是「自愈动作 `invalidateCellSizeIfNeeded()` 不能消失」。
        # ⇒ 纪律: **sabotage 锚点只锚被测语义的那几行**;
        #   把相邻的注释/新逻辑一起锚进去, 下一次加版本就会假报失效。
        o1 = "                deferredCorrectionPending = true\n"
        o2 = "                deferredCorrectionPending = _v38WasPending"
        if o1 not in x or o2 not in x:
            raise AssertionError("★锚点失效: S15 置/复 flag 两行不在产物里")
        n1 = "                deferredCorrectionPending = true\n"
        # 从 o1 起到 o2 之间, 删掉第一次出现的 invalidateCellSizeIfNeeded()
        i = x.find(o1)
        j = x.find(o2, i)
        mid = x[i + len(n1):j]
        if "invalidateCellSizeIfNeeded()" not in mid:
            raise AssertionError("★锚点失效: S15 两行之间没有 invalidateCellSizeIfNeeded()")
        mid2 = mid.replace("invalidateCellSizeIfNeeded()", "", 1)
        y = x[:i + len(n1)] + mid2 + x[j:]
        if y == x:
            raise AssertionError("★S15 破坏后文本没变")
        return y
    cases.append(("S15 删掉 invalidateCellSizeIfNeeded(自愈退化成空动作)", s15))

    return cases


def _sabotage(t, md):
    tot = bad = 0
    for name, fn in _cases(t):
        tot += 1
        try:
            b = fn(t)
        except AssertionError as e:
            print("❌ %-48s ★sabotage 自身失败: %s" % (name[:48], e))
            bad += 1
            continue
        if b == t:
            print("❌ %-48s ★未改动任何内容(锚点 no-op)" % name[:48])
            bad += 1
            continue
        fd, p = tempfile.mkstemp(suffix=".swift")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(b)
            hits = []
            for probe in PROBES:
                red, why = probe(p, b)
                if red:
                    hits.append(why)
            if hits:
                print("✅ %-48s 被判红: %s" % (name[:48], "; ".join(hits)[:60]))
            else:
                print("❌ %-48s ★未被拦截" % name[:48])
                bad += 1
        finally:
            os.unlink(p)
    return tot, bad


def main():
    if len(sys.argv) < 2:
        print("用法: reverse_v52.py <产物根目录 或 SelectableMarkdownView.swift> [--sab]")
        return 2
    md = resolve(sys.argv[1])
    if md is None or not os.path.exists(md):
        print("SKIP(找不到产物)")
        return 3
    t = open(md, encoding="utf-8").read()

    # ---- 基线: 判据在**未破坏**的产物上必须全绿, 否则 sabotage 无意义 ----
    # ★只跑 ci_assert_v52 **一次**, 且入口有 `--no-sab` 开关避免回调本脚本
    #   (v51 踩过 ci_assert ↔ reverse 互相递归, 进程树指数膨胀, CI 挂死)。
    r = subprocess.run([sys.executable, os.path.join(HERE, "ci_assert_v52.py"),
                        md, "--no-sab"], capture_output=True, text=True)
    if r.returncode != 0:
        print("★基线就不通过, 后续 sabotage 无意义:")
        print((r.stdout + r.stderr).strip()[-600:])
        return 1
    print("══ v52 基线 ══")
    print("✅ 未破坏的产物上 v52 判据全绿(判据自证的第一步)")

    if "--sab" not in sys.argv:
        return 0

    print("══ sabotage(逐条破坏, 每条都必须被拦) ══")
    tot, bad = _sabotage(t, md)
    print()
    if bad:
        print("❌ %d/%d 条 sabotage 未被拦截" % (bad, tot))
        return 1
    print("✅ %d/%d 条 sabotage 全被拦截" % (tot, tot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
