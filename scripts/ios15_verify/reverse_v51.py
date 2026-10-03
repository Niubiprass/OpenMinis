#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v51 反向证伪: sabotage 必须**全被拦下**, 且基线不误伤。

跑法: reverse_v51.py <产物根目录 或 SelectableMarkdownView.swift> [--sab]

★为什么必须 sab(本轮判据自己被证伪过的教训):
  v50 那一轮, 判据 R1 第一版只查"probe 判定在下游", 结果首版真让 probe
  也用了钉宽净宽, 判据却全绿 —— "看起来在跑、实际没钉住"。
  本版每条红线都配了对应的破坏法, 破坏后判据必须变红;
  若破坏后仍绿, 说明那条红线是空转的。

本版的红线与它的破坏法:

  A1 只写 size.width        → S1 加 origin / S2 改 height / S3 改 bounds
  A2 判据单调(>)            → S4 改成 `<` / S5 改成无条件
  A3 在 v48 钉宽行之后同段    → S6 挪到 v48 钉宽行之前
  B  NSLog 变参无 Optional    → S7 传 Optional(真死因) / S8 三元里藏 Optional
  C  探针不在补高 if 里       → S9 把探针重新包进 if
  D  段标记计数为 1           → S10 复制 END 标记 / S11 删 END 标记
  E  落点不越 v49 判定区间    → S12 把 v51 塞进 v50 通道写入行之上
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

    ★本轮第三次踩「锚点失效」与「漏放」输出同形的问题(v49 H1/H2):
      锚点写死 24 空格, 而 v51 把探针挪到 16 空格 ⇒ `str.replace` 静默
      返回原串 ⇒ sabotage 变 no-op ⇒ 判据全绿 ⇒ 输出"未被拦截"。
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


def _cases(t):
    cases = []

    # ---------- A1: 只写 size.width ----------
    def s1(x):
        old = """            if frame.size.width > _realW2 + 1 {
                var _v51f = frame
                _v51f.size.width = _realW2
                frame = _v51f
            }"""
        new = """            if frame.size.width > _realW2 + 1 {
                var _v51f = frame
                _v51f.size.width = _realW2
                _v51f.origin.x = 16
                frame = _v51f
            }"""
        return assert_replaced(x, old, new, "S1")
    cases.append(("S1 顺带写 origin.x(几何漂移=v34 翻车)", s1))

    def s2(x):
        old = "                _v51f.size.width = _realW2"
        new = ("                _v51f.size.width = _realW2\n"
               "                _v51f.size.height = 585.3")
        return assert_replaced(x, old, new, "S2")
    cases.append(("S2 顺带写 height(推翻 v45 补高成果)", s2))

    def s3(x):
        old = """                _v51f.size.width = _realW2
                frame = _v51f"""
        new = """                _v51f.size.width = _realW2
                frame = _v51f
                var _v51b = bounds
                _v51b.origin.x = 0
                bounds = _v51b"""
        return assert_replaced(x, old, new, "S3")
    cases.append(("S3 顺带写 bounds(绕过 frame 钳宽)", s3))

    # ---------- A2: 判据单调 ----------
    def s4(x):
        old = "if frame.size.width > _realW2 + 1 {"
        new = "if frame.size.width < _realW2 - 1 {"
        return assert_replaced(x, old, new, "S4")
    cases.append(("S4 判据反向成 `<`(会缩小=整棵 cell 重布局)", s4))

    def s5(x):
        old = """            if frame.size.width > _realW2 + 1 {
                var _v51f = frame
                _v51f.size.width = _realW2
                frame = _v51f
            }"""
        new = """            {
                var _v51f = frame
                _v51f.size.width = _realW2
                frame = _v51f
            }"""
        return assert_replaced(x, old, new, "S5")
    cases.append(("S5 去掉判据改成无条件(v13/v34 抢宽翻车形态)", s5))

    # ---------- A3: 必须在 v48 钉宽行之后 ----------
    def s6(x):
        # 把 v51 的写入整块挪到 v48 钉宽 if **之前** —— 破坏「同一帧」前提
        i_pin = x.find("            if frame.size.width > _realW2 + 1 {")
        if i_pin < 0:
            raise AssertionError("★S6 锚点失效: 找不到 v51 写入 if")
        j_end = x.find("\n            }", i_pin)
        if j_end < 0:
            raise AssertionError("★S6 锚点失效: 找不到该 if 的收尾")
        j_end += len("\n            }")
        block = x[i_pin:j_end]
        x = x[:i_pin] + x[j_end:]
        i_tc = x.find("            if _ios15WRegrabbed, "
                      "abs(textContainer.size.width - _realW2) > 0.5 {")
        if i_tc < 0:
            raise AssertionError("★S6 锚点失效: 找不到 v48 钉 textContainer 的 if")
        return x[:i_tc] + block + "\n" + x[i_tc:]
    cases.append(("S6 挪到 v48 钉宽行之前(破坏 A3 同一帧)", s6))

    # ---------- B: NSLog 变参 ----------
    def s7(x):
        # 真死因: `?? -1` 被去掉 ⇒ Optional 进 C 变参 ⇒ 编译失败
        old = """                          superview?.frame.size.width ?? -1, self.textStorage.length)"""
        new = """                          superview?.frame.size.width, self.textStorage.length)"""
        return assert_replaced(x, old, new, "S7")
    cases.append(("S7 NSLog 变参去掉 ?? 解包(run#37146140252 真死因)", s7))

    def s8(x):
        # 同族换写法: 三元表达式里藏 Optional
        old = """                    _V51FLog.last = _v51n
                    NSLog("[V51-FRAMEPIN] fvW=%.1f tcW=%.1f svW=%.1f len=%d",
                          self.frame.size.width, self.textContainer.size.width,
                          superview?.frame.size.width ?? -1, self.textStorage.length)"""
        new = """                    _V51FLog.last = _v51n
                    NSLog("[V51-FRAMEPIN] fvW=%.1f tcW=%.1f svW=%.1f len=%d",
                          self.ios15LastLaidOutW, self.textContainer.size.width,
                          superview?.frame.size.width ?? -1, self.textStorage.length)"""
        return assert_replaced(x, old, new, "S8")
    cases.append(("S8 NSLog 变参传 Optional(换写法藏同一个错)", s8))

    # ---------- C: 探针不得回到补高 if 里 ----------
    def s9(x):
        # ★要把**探针入口**包进去才对 —— 只包 `let _v49Now` 那段的话,
        #   `_V49W.tick`(读数与登记)仍在无条件路径上, 判据当然不红:
        #   那恰好是"v51 要修的病没修"。本版 sabotage 必须模拟**真正的回退**。
        # ★包进 if 后必须给**探针体每一行**加一级缩进 —— 只插 if 不动缩进的
        #   话, `_V49W.tick` 的缩进不变, 判据当然不红。那是 sabotage 自己
        #   没构造到位(第三次踩"看起来改了、实际没钉住")。
        old = """                // [V49-WWRITER-KVO] KVO 侧读数(与 v18 侧同帧比对)
                _V49W.tick &+= 1"""
        new = """                // [V49-WWRITER-KVO] KVO 侧读数(与 v18 侧同帧比对)
                if _v42Need > 1, f.size.height + 0.5 < _v42Need {
                    _V49W.tick &+= 1"""
        out = assert_replaced(x, old, new, "S9")
        # 相应闭合那个 if(在探针段结束标记之前), 保持语法合法
        old2 = "                // [V49-WWRITER-KVO-END]"
        return assert_replaced(out, old2, "                }" + "\n" + old2,
                               "S9-closer")
    cases.append(("S9 探针重新包进补高 if(恢复 v51-C 要修的病)", s9))

    # ---------- D: 段边界标记 ----------
    def s10(x):
        old = "            // [V49-WWRITER-V18-END] 段结束标记 —— 见 v49 判据第 3 组。\n"
        new = old + "            // [V49-WWRITER-V18-END] 段结束标记 —— 见 v49 判据第 3 组。\n"
        return assert_replaced(x, old, new, "S10")
    cases.append(("S10 复制 v49 END 标记(计数 2, v49 struct 应红)", s10))

    def s11(x):
        old = "                // [V49-WWRITER-KVO-END] 段结束标记 —— 见 v49 判据第 3 组。\n"
        new = "                // 探针段结束(标记被删)\n"
        return assert_replaced(x, old, new, "S11")
    cases.append(("S11 删 v49 KVO-END 标记(三层应报段未闭合)", s11))

    # ---------- E: 落点不许越界到 v50 判定区间 ----------
    def s12(x):
        # 把 v51 的写入块挪到 v50 通道写入行**之上** ⇒ 落进 v50 scope 的
        # seg_w 区间(begin=V50-PINW-WRITE / end=V49-WWRITER-V18)
        i_pin = x.find("            if frame.size.width > _realW2 + 1 {")
        if i_pin < 0:
            raise AssertionError("★S12 锚点失效: 找不到 v51 写入 if")
        j_end = x.find("\n            }", i_pin)
        j_end += len("\n            }")
        block = x[i_pin:j_end]
        x = x[:i_pin] + x[j_end:]
        i_w = x.find("            TableAttachment.ios15PinnedW = _realW2")
        if i_w < 0:
            raise AssertionError("★S12 锚点失效: 找不到 v50 通道写入行")
        return x[:i_w] + block + "\n" + x[i_w:]
    cases.append(("S12 落点挪进 v50 判定区间(v50 scope 应红)", s12))

    return cases


def _run(cmd_list):
    return subprocess.run(cmd_list, capture_output=True, text=True, timeout=300)


def _core_ok(p, t):
    """直接跑 v51 的 core + scope, **不经过 ci_assert_v51.py**。

    ★★ 本轮第一条写完直接把 CI 卡死了: `_sabotage` 里调
       `ci_assert_v51.py`, 而 ci_assert_v51 又会去调 `reverse_v51.py --sab`
       ⇒ 两个脚本互相递归调对方, 进程树指数爆炸, 命令无输出挂死。
    ⇒ 纪律: **CI 入口 → 各层 → 反向测试 必须是单向的**;
       反向测试只能调更底层的判据, 不许回调 CI 入口。
    """
    # ---- scope ----
    sc = os.path.join(HERE, "scope_check_v51.py")
    if os.path.exists(sc):
        r = _run([sys.executable, sc, p])
        if r.returncode != 0:
            return True, "scope: " + ((r.stdout + r.stderr).strip().split("\n")[-1])[:70]
    # ---- core(fallback 内的两个 verify) ----
    fb = _fallback_path_for(p)
    if os.path.exists(fb):
        import importlib.util
        spec = importlib.util.spec_from_file_location("fb_v51_sab", fb)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        for fn in (getattr(m, "verify_view_frame_pin_v51", None),
                   getattr(m, "verify_probe_unhook_v51", None)):
            if fn is None:
                continue
            try:
                fn(t)
            except Exception as e:
                return True, "core %s: %s" % (fn.__name__, str(e)[:70])
    return False, ""


def _fallback_path_for(md_path):
    """sabotage 的临时文件在某个临时目录里, 回不到产物树 ——
    必须退回本判据所在仓库才能找到 ios15_fallback.py。"""
    return os.path.normpath(os.path.join(HERE, "..", "ios15_fallback.py"))


def _v50_scope_ok(p, t=None):
    """落点类破坏(S12)由 **v50 的 scope** 负责判红 ——
    本轮的真相: v51 若插进 v50 的段里, 红的是 v50 而不是 v51。"""
    r = _run([sys.executable, os.path.join(HERE, "scope_check_v50.py"), p])
    return r.returncode != 0, (
        "v50 scope: " + ((r.stdout + r.stderr).strip().split("\n")[-1])[:70])


def _v49_struct_ok(p, t=None):
    """段标记计数类破坏(S10/S11)由 **v49 struct** 负责判红 ——
    那对标记是 v49 判据的切段契约, v51 动过它们就得由 v49 来定对错。"""
    r = _run([sys.executable, os.path.join(HERE, "verify_v49.py"), p])
    return r.returncode != 0, (
        "v49 struct: " + ((r.stdout + r.stderr).strip().split("\n")[-1])[:70])


def _sabotage(t, md):
    """每条破坏法逐层跑判据, 只要有**任何一层**变红就算被拦。

    ★为什么要分派给不同层(v51 core / v51 scope / v50 scope / v49 struct):
      本版是"往既有代码里插一段", 破坏它有多种方式 —— 有的改动触发 v51
      自己的红线, 有的则是**踩进前版的判定区间**(落地位置类)。
      只跑 v51 自己的判据会把后一类全判成"未被拦截", 而实际上前版判据
      是会红的。⇒ 纪律: **反向测试要跑全链, 不能只跑本版。**
    """
    bad = 0
    tot = 0
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
            for probe in (_core_ok, _v50_scope_ok, _v49_struct_ok):
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
        print("用法: reverse_v51.py <产物根目录 或 SelectableMarkdownView.swift> [--sab]")
        return 2
    md = resolve(sys.argv[1])
    if md is None or not os.path.exists(md):
        print("SKIP(找不到产物)")
        return 3
    t = open(md, encoding="utf-8").read()

    # ---- 基线: 判据在**未破坏**的产物上必须全绿, 否则 sabotage 无意义 ----
    # ★只跑 ci_assert_v51 **一次**, 且入口要有 `--no-sab` 开关避免回调本脚本
    #   (本轮第一条版本就是 ci_assert_v51 ↔ reverse_v51 互相递归, 挂死)。
    r = _run([sys.executable, os.path.join(HERE, "ci_assert_v51.py"), md,
              "--no-sab"])
    if r.returncode != 0:
        print("★基线就不通过, 后续 sabotage 无意义:")
        print((r.stdout + r.stderr).strip()[-600:])
        return 1
    print("══ v51 基线 ══")
    print("✅ 未破坏的产物上 v51 判据全绿(判据自证的第一步)")

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
