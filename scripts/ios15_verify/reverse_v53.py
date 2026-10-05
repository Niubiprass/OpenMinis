#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v53 反向测试(sabotage)—— 判据自证。

判据本身可能写错。所以每一条判据都要被**故意破坏的产物**验证:
破坏后判据必须报失败; 不破坏时必须报通过(无误伤)。

★v53 特有的自证重点(前几版没踩过的坑, 本版一次踩了两个):

  ① **跨文件 sabotage**。v53 第一次改两个文件, 于是 sabotage 也必须
     能改对文件。v52 轮的教训是「锚点写错 ⇒ 测试全绿 ⇒ 白测」,
     本版每条都断言「锚点必须命中」, 未命中直接算失败。

  ② **假通过要当场识破**。第一版跑 10 条 sab 时 S5/S6/S7 全绿,
     但绿的原因是 `verify_first_para_settle_v53() takes 1 positional
     argument but 2 were given` —— **TypeError 而非判据失败**。
     ⇒ 纪律: **sab 结果必须检查异常类型**; 判据只抛 RuntimeError,
       任何其他异常类型都算「测试自身坏了」, 不算「拦住」。
       这条已写进 `_run_sab`。

用法:
    reverse_v53.py <产物根目录 或 swift 路径> [--sab]
        无 --sab : 跑基线自检(确认未改动产物全绿)
        有 --sab : 跑全部 sabotage, 要求 100% 被拦且基线无误伤
退出码: 0 = 通过, 1 = 失败, 3 = 环境不全
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
INFRA_REL = "src/ios/Agent/MessageList/MessageListInfrastructure.swift"
FB_REL = "scripts/ios15_fallback.py"


def _load_fb(root):
    for c in (os.path.join(root, FB_REL),
              os.path.normpath(os.path.join(HERE, "..", "..", "ios15_fallback.py"))):
        if os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- sabotage
# (编号, 名称, 目标文件 T/I, 原串, 替换串, 判据键)
# ★原串必须与产物**逐字一致**(含缩进), 由 `_check_anchors` 在开跑前逐条断言。
SABS = [
    ("S1", "三条短路只改两条(留一退化)", "I",
     # ★v62 适配: 守卫形态扩为盈余镜像 `!v53DebtIsRipe, !v53SurplusIsRipe {`
     "!v53DebtIsRipe, !v53SurplusIsRipe {", "!v53DebtIsRipe || false {", "C2"),
    ("S2", "CONSUMED 又改回只信返回值", "T",
     "let _settled = _cellH > 1 && _cellH >= newHeight - 1",
     "let _settled = true", "C2"),
    ("S3", "记忆位不挡污染宽度(375.7 会进记忆位)", "T",
     "guard _v52ok else { return nil }",
     "// sabotage: 无污染守卫", "C2"),
    ("S4", "欠账清掉不复位计数(短路永久失效)", "I",
     # ★v62 适配: note 函数里 `v53DebtSeenCount = 0` 有两处(盈余分支 +
     #   欠账复位), 裸串会错破坏盈余分支 → 用欠账复位分支特有上下文精确定位
     "if debt <= 1 {\n            v53DebtSeenCount = 0",
     "if debt <= 1 {\n            // sabotage: 不复位", "C2"),
    ("S5", "settle 入口改回 flag-only(首段被挡)", "T",
     # ★v62 适配: guard 形态扩为盈余感知
     # ★v63 适配: guard 再扩为「打破循环依赖」形态, 末尾多了 || _v63drift。
     #   这不是简单改锚点 —— v63 加的是**第四条腿**(drift 兜底, 不依赖 debt
     #   计数), 而 S5 的语义是"把放行条件砍回只剩 flag"。若照旧用 v62 锚点,
     #   find() 落空 ⇒ 本条变空测(判据自己会报"锚点未命中")。
     #   纪律第 10 条: 锚点失效必须自己报错, 不许静默跳过;
     #   修的时候要问一句"新加的那条腿有没有被测到" ⇒ 见 S15/S16。
     "guard deferredCorrectionPending || _stillOwing || _v62oversized || _v63drift else { return }",
     "guard deferredCorrectionPending else { return }", "FIRST"),
    ("S6", "首段欠账阈值放到 0(亚像素噪声也算欠账)", "T",
     "_debt > 1", "_debt > -1", "FIRST"),
    ("S7", "首段不把欠账报给 cell(新入口空转)", "T",
     # ★v62 适配: 上报形态扩为盈余感知
     "_v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)",
     "_ = _stillOwing", "FIRST"),
    ("S8", "B 路探针错标成 A 路(装机日志来源错乱)", "I",
     "// [V53-PROBE] B 路", "// [V53-PROBE] A 路", "P"),
    ("S9", "C1 探针字段缺失(判读依据丢失)", "T",
     "memHit=%llu mem=%.1f", "x=%llu", "C2"),
    ("S10", "E 判据处不上报欠账(cell 永远不知道欠账)", "T",
     "_v53ReportDebtToCell(_needH - _v52PreSVH)",
     "_ = _needH", "C2"),
    ("S11", "记忆位根本不写入(死锁没打破)", "T",
     "ios15LastSaneContentW = _mw", "// sabotage: 不写", "C2"),
    ("S12", "欠账上报函数不调 cell 入口", "T",
     "cell.v53NotePendingDebt(debt)", "_ = debt", "C2"),
    ("S13", "探针改动返回值(诊断影响被测对象)", "I",
     "copy.size.height = cached\n            // [V53-PROBE] A 路",
     "copy.size.height = cached * 1.5\n            // [V53-PROBE] A 路", "P"),
    ("S14", "两条短路的 if 头被合并(守卫只算一处)", "I",
     "abs(cv.bounds.width - sw) < 1,\n           // [V53-C2] 同 A/B 路",
     "abs(cv.bounds.width - sw) < 1 {\n           // [V53-C2] 同 A/B 路", "C2"),
]


def _resolve(target):
    if os.path.isfile(target):
        md = os.path.abspath(target)
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(md))))
        return md, root
    md = os.path.join(target, MD_REL)
    if os.path.exists(md):
        return md, os.path.abspath(target)
    return None, None


def _run_sab(fb, key, t, f, expect_fail=True):
    """跑一个判据。返回 (ok, 说明)。

    ★异常类型必须核对: 判据只应抛 RuntimeError。其他类型(TypeError /
    AttributeError / IndexError…)说明**测试自身坏了**(调用签名错、
    判据函数名拼错), 不算「拦住」。
    """
    fn = {"P": fb.verify_shortcircuit_probe_v53,
          "C2": fb.verify_debtgate_release_v53,
          "FIRST": fb.verify_first_para_settle_v53}[key]
    try:
        if key == "FIRST":
            fn(t)
        else:
            fn(t, f)
    except RuntimeError as e:
        return (True, "✓ 拦住: %s" % str(e)[:70])
    except Exception as e:
        return (False, "✗ ★测试自身坏了* —— 抛的是 %s 而非 RuntimeError: %s"
                % (type(e).__name__, str(e)[:70]))
    else:
        if expect_fail:
            return (False, "✗ 未被抓住(判据失效)")
        return (True, "✓ 通过(无误伤)")


def main():
    if len(sys.argv) < 2:
        print("用法: reverse_v53.py <产物根目录 或 swift 路径> [--sab]")
        return 3
    md, root = _resolve(sys.argv[1])
    if md is None:
        print("SKIP(找不到产物: %s)" % MD_REL)
        return 3
    infra = os.path.join(root, INFRA_REL)
    if not os.path.isfile(infra):
        print("SKIP(找不到产物: %s —— v53 跨文件改动, 必须有它)" % INFRA_REL)
        return 3
    fb_path = _load_fb(root)
    if not fb_path:
        print("SKIP(找不到 %s)" % FB_REL)
        return 3
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v53", fb_path)
    fb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fb)

    T0 = open(md, encoding="utf-8").read()
    I0 = open(infra, encoding="utf-8").read()
    print("产物: %s(%d) + %s(%d)" % (os.path.basename(md), len(T0),
                                    os.path.basename(infra), len(I0)))

    # ---- 基线自检: 未改动的产物必须全绿 ----
    print("\n[基线] 未改动产物必须通过(否则说明判据误伤了正确实现)")
    ok = True
    for key, name in (("P", "P(三来源探针)"),
                      ("C2", "C1+C2(死锁/放行/判据)"),
                      ("FIRST", "FIRST(首段专项)")):
        good, msg = _run_sab(fb, key, T0, I0, expect_fail=False)
        print("   %-24s %s" % (name, msg))
        if not good:
            ok = False
    if not ok:
        print("\n★ 基线就不绿 —— 判据误伤或环境不全, **不要看 sabotage 结果**。")
        return 1

    if "--sab" not in sys.argv:
        print("\nreverse_v53=OK(基线自检通过; 加 --sab 跑破坏性测试)")
        return 0

    # ---- 锚点逐条断言 ----
    print("\n[锚点] 逐条确认 sabotage 用的原串在产物里逐字存在")
    bad_anchor = []
    for sid, name, which, old, new, key in SABS:
        src = T0 if which == "T" else I0
        if old not in src:
            bad_anchor.append("%s %s (原串未命中)" % (sid, name))
            print("   %-4s %-38s ✗ 未命中" % (sid, name))
        else:
            print("   %-4s %-38s ✓" % (sid, name))
    if bad_anchor:
        print("\n★ 有 %d 条锚点未命中 —— 这些 sabotage 是**空测**, "
              "结果不作数。修锚点或修产物。" % len(bad_anchor))
        return 1

    # ---- 跑 sabotage ----
    print("\n[sab] 破坏后判据必须报失败(异常类型必须是 RuntimeError)")
    caught = 0
    for sid, name, which, old, new, key in SABS:
        T, I = T0, I0
        if which == "T":
            T = T.replace(old, new, 1)
        else:
            I = I.replace(old, new, 1)
        good, msg = _run_sab(fb, key, T, I, expect_fail=True)
        print("   %-4s %-38s %s" % (sid, name, msg))
        if good:
            caught += 1

    print("\n" + "─" * 60)
    print("sabotage: %d/%d 被拦" % (caught, len(SABS)))
    if caught != len(SABS):
        print("★ 有 %d 条漏网 —— 对应判据是无效的, 装机后无法判读。"
              % (len(SABS) - caught))
        return 1
    print("✅ 全部被拦且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
