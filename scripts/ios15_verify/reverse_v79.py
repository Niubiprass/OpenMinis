#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_v79 —— v79 反向判据(问实质, 禁空测)。

每条 sabotage 对应一种「看起来改了、流式仍吃缓存 / 非流式被误伤」的形态。

    S1 摘 A 路 !_v79streaming          —— 流式仍走 dedup
    S2 摘 C 路 !_v79streaming          —— 流式仍走 seededHeight
    S3 摘 broad !_v79streaming         —— super 后同宽缓存仍吞流式
    S4 B-precalc 改回 return           —— 高度锁在 heightCache
    S5 摘 _v53Note(.none)              —— live 恒 0(v64 装机原样)
    S6 _v53Note(.none) 挪到 A 路之前   —— 短路也记 live, 探针撒谎
    S7 _v79streaming 恒 false          —— 豁免死代码
    S8 _v79streaming 声明挪到 A 路后   —— 顺序错, A 仍先吃缓存
    S9 改守卫串(加 !_v79streaming)     —— 弄坏 v53/v62 计数
    S10 摘非流式 A 路 copy.height=cached —— 非流式每帧重测
    S11 _v79streaming 恒 true          —— 非流式也被豁免
    S12 赋值改成 hasActiveStreaming    —— 所有可见 cell 当流式
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import ios15_fallback as fb  # noqa: E402

INFRA_REL = os.path.join("src", "ios", "Agent", "MessageList",
                         "MessageListInfrastructure.swift")


def _read(base):
    if os.path.isfile(base):
        base = os.path.dirname(os.path.dirname(os.path.dirname(base)))
    if not os.path.isdir(os.path.join(base, "src", "ios")):
        base = os.path.dirname(base)
    p = os.path.join(base, INFRA_REL)
    if not os.path.isfile(p):
        raise SystemExit("产物缺失: %s" % p)
    with open(p, encoding="utf-8") as f:
        return f.read()


def s1_drop_a_exempt(t):
    """S1 摘 A 路 !_v79streaming —— 流式仍走 dedup。"""
    old = "           abs(layoutAttributes.size.width - cachedW) < 1,\n           !_v79streaming,"
    assert t.count(old) == 1, "S1 前置失败: 次数=%d" % t.count(old)
    return t.replace(old, "           abs(layoutAttributes.size.width - cachedW) < 1,", 1)


def s2_drop_c_exempt(t):
    """S2 摘 C 路 !_v79streaming。"""
    old = "           abs(cv.bounds.width - sw) < 1,\n           !_v79streaming,"
    assert t.count(old) == 1, "S2 前置失败: 次数=%d" % t.count(old)
    return t.replace(old, "           abs(cv.bounds.width - sw) < 1,", 1)


def s3_drop_broad_exempt(t):
    """S3 摘 broad !_v79streaming。"""
    old = ("           abs(layoutAttributes.size.width - attrs.size.width) < 1,"
           "\n           !_v79streaming {")
    assert t.count(old) == 1, "S3 前置失败: 次数=%d" % t.count(old)
    return t.replace(
        old,
        "           abs(layoutAttributes.size.width - attrs.size.width) < 1 {",
        1)


def s4_precalc_returns(t):
    """S4 B-precalc 改回 return —— 流式高度锁在 precalc。"""
    old = ('                Self.sizingLogger.info("[CellSizing][V79-STREAM] '
           'skip-precalc h=\\(String(format: "%.1f", precalc))")')
    assert t.count(old) == 1, "S4 前置失败: 次数=%d" % t.count(old)
    return t.replace(
        old,
        "                let copy = layoutAttributes.copy() as! UICollectionViewLayoutAttributes\n"
        "                copy.size.height = precalc\n"
        "                return copy",
        1)


def s5_drop_live_note(t):
    """S5 摘 _v53Note(.none) —— live 恒 0, v64 装机原样。"""
    old = ("        Self._v53Note(.none, height: lastComputedHeight ?? layoutAttributes.size.height,\n"
           "                       width: layoutAttributes.size.width,\n"
           "                       pendingDebt: v53PendingHeightDebt)\n")
    assert t.count(old) == 1, "S5 前置失败: 次数=%d" % t.count(old)
    return t.replace(old, "", 1)


def s6_note_before_a(t):
    """S6 把 _v53Note(.none) 挪到 A 路之前 —— 短路也记 live。"""
    old = ("        Self._v53Note(.none, height: lastComputedHeight ?? layoutAttributes.size.height,\n"
           "                       width: layoutAttributes.size.width,\n"
           "                       pendingDebt: v53PendingHeightDebt)\n")
    assert t.count(old) == 1, "S6 前置失败"
    t = t.replace(old, "", 1)
    anchor = "        var _v79streaming = false\n"
    assert t.count(anchor) == 1, "S6 锚点失败"
    return t.replace(anchor, old + anchor, 1)


def s7_streaming_false(t):
    """S7 _v79streaming 恒 false —— 豁免死代码。"""
    old = ("            _v79streaming = _v79layout.hasActiveStreaming\n"
           "                && _v79layout.isStreamingCell(layoutAttributes.indexPath.item)")
    assert t.count(old) == 1, "S7 前置失败: 次数=%d" % t.count(old)
    return t.replace(old, "            _v79streaming = false", 1)


def s8_decl_after_a(t):
    """S8 把流式判定块挪到 A 路 return 之后 —— A 仍先吃缓存。"""
    start = t.find("        // [V79-STREAM] 流式判定必须早于 A 路。")
    assert start >= 0, "S8 找不到判定块"
    end = t.find("        if let cached = lastComputedHeight,\n           let cachedW = lastComputedWidth,", start)
    assert end > start, "S8 找不到 A 路"
    block = t[start:end]
    rest = t[:start] + t[end:]
    ret = rest.find("            return copy\n        }", rest.find("copy.size.height = cached"))
    assert ret > 0, "S8 找不到 A 路 return"
    eol = rest.find("\n", ret)
    return rest[:eol + 1] + block + rest[eol + 1:]


def s9_mutate_guard_string(t):
    """S9 改守卫串 —— v53/v62 计数不再是 3。"""
    old = "!v53DebtIsRipe, !v53SurplusIsRipe {"
    n = t.count(old)
    assert n == 3, "S9 前置失败: 守卫串次数=%d" % n
    return t.replace(old, "!v53DebtIsRipe, !v53SurplusIsRipe, !_v79streaming {", 1)


def s10_drop_cached_write(t):
    """S10 摘非流式 A 路 copy.size.height = cached。"""
    old = "            copy.size.height = cached\n            // [V53-PROBE] A 路"
    assert t.count(old) == 1, "S10 前置失败: 次数=%d" % t.count(old)
    return t.replace(old, "            // sabotage: 非流式也不写缓存高\n            // [V53-PROBE] A 路", 1)


def s11_streaming_true(t):
    """S11 _v79streaming 恒 true —— 非流式也被豁免。"""
    old = ("            _v79streaming = _v79layout.hasActiveStreaming\n"
           "                && _v79layout.isStreamingCell(layoutAttributes.indexPath.item)")
    assert t.count(old) == 1, "S11 前置失败"
    return t.replace(old, "            _v79streaming = true", 1)


def s12_only_has_active(t):
    """S12 赋值只看 hasActiveStreaming —— 所有可见 cell 当流式。"""
    old = ("            _v79streaming = _v79layout.hasActiveStreaming\n"
           "                && _v79layout.isStreamingCell(layoutAttributes.indexPath.item)")
    assert t.count(old) == 1, "S12 前置失败"
    return t.replace(old, "            _v79streaming = _v79layout.hasActiveStreaming", 1)


SABOTAGE = [
    ("S1 摘 A 路流式豁免", s1_drop_a_exempt),
    ("S2 摘 C 路流式豁免", s2_drop_c_exempt),
    ("S3 摘 broad 流式豁免", s3_drop_broad_exempt),
    ("S4 B-precalc 改回 return", s4_precalc_returns),
    ("S5 摘 _v53Note(.none)", s5_drop_live_note),
    ("S6 live 探针挪到 A 路前", s6_note_before_a),
    ("S7 _v79streaming 恒 false", s7_streaming_false),
    ("S8 流式判定挪到 A 路后", s8_decl_after_a),
    ("S9 改守卫串(弄坏 v53/v62)", s9_mutate_guard_string),
    ("S10 摘非流式 A 路写缓存高", s10_drop_cached_write),
    ("S11 _v79streaming 恒 true", s11_streaming_true),
    ("S12 赋值只看 hasActiveStreaming", s12_only_has_active),
]


def _judge(t):
    try:
        fb.verify_stream_live_v79(t)
        return None
    except Exception as e:
        return e


def main():
    base_arg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "src")
    base = _read(base_arg)

    berr = _judge(base)
    if berr is not None:
        print("基线本身不通过 —— 反向判据无法工作")
        print("  基线报错: %s" % berr)
        return 1
    print("基线: OK(不计入 passed)")

    if "[V79-STREAM]" not in base:
        print("基线缺 [V79-STREAM] —— v79 注入没生效, 空测")
        return 3

    passed = 0
    voided = 0
    missed = []
    for name, fn in SABOTAGE:
        try:
            t = fn(base)
        except (SystemExit, AssertionError) as e:
            print("  void %-40s 空测(%s)" % (name, e))
            voided += 1
            continue
        if t == base:
            print("  void %-40s 空测(sabotage 什么也没改)" % name)
            voided += 1
            continue
        err = _judge(t)
        if err is None:
            print("  MISS %-40s 漏过" % name)
            missed.append(name)
        else:
            print("  CATCH %-40s 拦下" % name)
            passed += 1

    total = len(SABOTAGE)
    print("v79 反向: %d 拦下, %d 漏过, %d 空测(共 %d 条 sabotage)"
          % (passed, len(missed), voided, total))
    if voided:
        print("::error::v79 反向有 %d 条空测 —— 空测不是通过" % voided)
    for m in missed:
        print("::error::v79 反向漏过: %s" % m)
    return 1 if (missed or voided) else 0


if __name__ == "__main__":
    sys.exit(main())
