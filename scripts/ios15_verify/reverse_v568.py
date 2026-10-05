#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v56.8 反向测试 —— 证明 verify_capsule_shimmer_v568 真的能抓住错误。

★为什么必须有这个文件:
  v56.5~v56.7 连续三版「判据全绿但装错对象」。判据全绿只能证明
  「代码按我写的执行了」, 不能证明「我写的是对的」。反向测试是唯一的
  对冲手段: 故意破坏一处, 判据必须报红。

★与 reverse_v567 的差别:
  v567 换了实现, 所以有 11 组输入的等价性自证。
  v568 **不改任何行为**(只把 offset 目标从「乘布局量」改成「乘常量」,
  视觉上亮条照旧从左扫到右), 所以这里没有等价性可证 ——
  判据盯的是**耦合是否真的解开了**, 以及**动画有没有被顺手删掉**。

★这个文件自己的第一版被自己的 S1/S4/S5/S6 抓出了 4 个缺陷(见文末「反向
  测试抓到的真洞」)。那些洞不是判据的, 是 sabotage 设计的。

用法:
    python3 reverse_v568.py
退出码 0 = 全部 sabotage 都被拦下且基线无误伤。
"""

import importlib.util
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

HERE = os.path.dirname(os.path.abspath(__file__))
FALLBACK = os.path.join(HERE, os.pardir, "ios15_fallback.py")


def load_fallback():
    """载入 fallback 里的工具函数, 但**摘掉 main 里的自检调用**。

    ★必须摘掉: 否则 sabotage 后的产物会因为内部 verify 先报错而
    根本落不了地, 外层判据就没机会独立判定 —— 变成自己判自己。
    (这是 reverse_v567 里已经踩过并修好的坑, 沿用。)
    """
    src = open(FALLBACK, encoding="utf-8").read()
    src = src.replace(
        "\n    verify_capsule_shimmer_v568(t)\n    return t",
        "\n    return t",
    )
    head = src.split("if __name__")[0]
    g = {}
    exec(compile(head, "fallback", "exec"), g)
    return g


# ----------------------------------------------------------------------
# 基线: 干净上游 + v56.8 注入 = 应该判绿
# ----------------------------------------------------------------------
def build_baseline(g):
    up = upstream_ios(quiet=True)
    t = open(os.path.join(up, "Views/Chat/AssistantBlockView.swift"),
             encoding="utf-8").read()
    return g["fix_capsule_shimmer_v568"](t)


# ----------------------------------------------------------------------
# sabotage 定义
# ----------------------------------------------------------------------
# ★S1 第一版写成「原样上游」直接当 baseline 的对照 —— 那不是 sabotage,
#  那是另一个合法输入(未改动), 它当然和 baseline 不同(锚点失效),
#  但「不同」不等于「 sabotage 后判据会报红」。
#  正确做法: S1 应该在**已注入的产物上**把 v568 的两处改动**逐字退回**,
#  模拟「改了但只改了一半 / 完全没改」, 这样才是真正的破坏。
def _s1_undo_all(t):
    """完全退回 v568: offset 换回乘 geo.size.width 且删掉 travel 声明。"""
    t = t.replace(".offset(x: offsetX * Self.travel)",
                  ".offset(x: offsetX * geo.size.width)", 1)
    t = t.replace("    private static let travel: CGFloat = 600\n", "", 1)
    return t


def _s2_move_coupling(t):
    """耦合换地方: 改成乘 geo.size.height。"""
    return t.replace(".offset(x: offsetX * Self.travel)",
                     ".offset(x: offsetX * geo.size.height)", 1)


def _s3_travel_to_var(t):
    """travel 从编译期常量变成 var。"""
    return t.replace("private static let travel: CGFloat = 600",
                     "private var travel: CGFloat = 600", 1)


def _s4_drop_repeat_forever(t):
    """删掉 ShimmerOverlay 的 repeatForever(假修复: 不卡了但没动画了)。

    ★必须精确删 ShimmerOverlay 内部那处。该文件另有两处 repeatForever
      (:416 弹跳点 dotsActive, :1126), 所以「删第一处 repeatForever」会
      误伤 dotsActive —— 那样测的就不是「Shimmer 动画被删」了。
    """
    i0 = t.find("struct ShimmerOverlay")
    assert i0 > 0
    i1 = t.find("\nstruct ", i0 + 1)
    body = t[i0:i1]
    newbody = body.replace(".repeatForever(autoreverses: false)", "", 1)
    assert newbody != body, "S4 锚点失效: 没在 ShimmerOverlay 里找到 repeatForever"
    return t[:i0] + newbody + t[i1:]


def _s5_drop_with_animation(t):
    """删掉 ShimmerOverlay 的 withAnimation。"""
    i0 = t.find("struct ShimmerOverlay")
    assert i0 > 0
    i1 = t.find("\nstruct ", i0 + 1)
    body = t[i0:i1]
    newbody = body.replace("withAnimation(", "if false { //", 1)
    assert newbody != body, "S5 锚点失效"
    return t[:i0] + newbody + t[i1:]


def _s6_drop_capsule_frame(t):
    """只改 ShimmerOverlay, 漏掉 capsule 高度钉死(范围不全)。"""
    # ★逐字对齐产物: 标记两行 + 紧跟其后的 .frame(height: 36)。
    #   第一版这里凭记忆写了两种措辞, 结果一个都没命中 —— 锚点失效, 白测。
    #   教训与 v55.2 / reverse_v566 S1 完全同类(见 MSG_V568 铁律)。
    lines = t.split("\n")
    hit = [k for k, l in enumerate(lines) if "[V568-SHIMMER]" in l
           and "固定 36pt 已是上游既有约定" in l]
    assert hit, "S6 锚点失效: 找不到 capsule 高度钉死处的标记"
    k = hit[0]
    # 该标记占 3 行: 标记行 + 「这里只**显式钉住高度**…」+ 「稳定尺寸…」
    # 紧跟其后的第 4 行才是新增的 .frame(height: 36)。
    # ★第一版按 2 行算, 拿到的还是注释行 —— 于是 assert 拦下, 白测。
    #   教训: 行数假设必须用 assert 兜住, 不能凭印象(与 v55.2 同类)。
    for skip in (3, 2, 4):
        if k + skip < len(lines) and \
                lines[k + skip].strip() == ".frame(height: 36)":
            del lines[k:k + skip + 1]
            return "\n".join(lines)
    raise AssertionError(
        "S6 锚点失效: 标记后 2/3/4 行都不是 .frame(height: 36), 实际是 %r"
        % [lines[k + i].strip()[:40] for i in (2, 3, 4) if k + i < len(lines)])


def _s7_strip_marks(t):
    """标记全被摘掉(代码对但没标记)。"""
    return t.replace("[V568-SHIMMER]", "[T-shimmer]")


def _s8_reintroduce_old_coupling(t):
    """覆盖失控: 在文件别处再引入一处同类耦合(旧代码从 0 处变成 1 处)。"""
    # ★必须逐字含 `offsetX * geo.size.width` 这个 needle ——
    #   第一版写成 `x * geo.size.width`(换了变量名), 结果覆盖失控判据
    #   压根没被触发, S8 白测。这正是「判据只认字面量」的双刃:
    #   判据抓不到语义等价的耦合, 所以 sabotage 也必须用字面量,
    #   否则测的就不是判据想测的那件事。
    return t.replace(
        "    private var peakOpacity: CGFloat {",
        "    private func legacyOffset(_ geo: GeometryProxy) -> CGFloat {\n"
        "        offsetX * geo.size.width\n"
        "    }\n\n"
        "    private var peakOpacity: CGFloat {",
        1,
    )


def _s9_delete_shimmer_entirely(t):
    """对象没了: 整个 ShimmerOverlay 被删。

    ★这条是「范围失控」的最狠形态: 判据必须报红而不是静默放过。
      旧判据只查 `offsetX * Self.travel` 存在与否, 一旦整个函数被删,
      那条 needle 也一起消失, 判据会报「没有 offsetX * Self.travel」
      —— 恰好也能报红, 但那条消息会误导人去查 offset, 而真因是函数没了。
      所以判据里加了 i0 < 0 的前置检查, 专门报「对象本身没了」。
    """
    i0 = t.find("struct ShimmerOverlay")
    assert i0 > 0
    i1 = t.find("\n// MARK: - Tool Capsule View", i0)
    assert i1 > 0, "S9 锚点失效: 找不到 ShimmerOverlay 段尾"
    return t[:i0] + t[i1 + 1:]


SABOTAGES = [
    ("S1", "两处改动完全退回上游", _s1_undo_all,
     "旧耦合回来, 动画重新被 body 重算打断"),
    ("S2", "耦合换地方(改乘 geo.size.height)", _s2_move_coupling,
     "等于没解耦"),
    ("S3", "travel 从 static let 改成 var", _s3_travel_to_var,
     "不再是编译期常量"),
    ("S4", "删 ShimmerOverlay 的 repeatForever", _s4_drop_repeat_forever,
     "假修复: 动画被删"),
    ("S5", "删 ShimmerOverlay 的 withAnimation", _s5_drop_with_animation,
     "假修复: 动画被删"),
    ("S6", "漏掉 capsule 高度钉死(范围不全)", _s6_drop_capsule_frame,
     "标记行数不足"),
    ("S7", "标记全被摘掉", _s7_strip_marks,
     "无法证明注入到位"),
    ("S8", "别处再引入一处同类耦合", _s8_reintroduce_old_coupling,
     "覆盖失控判据"),
    ("S9", "整个 ShimmerOverlay 被删", _s9_delete_shimmer_entirely,
     "对象本身没了"),
]


def main():
    g = load_fallback()
    verify = g["verify_capsule_shimmer_v568"]
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
            print("❌ %-4s  %-42s sabotage 自身失败: %s" % (name, desc, e))
            missed.append(name)
            continue

        if sabotaged == base:
            print("❌ %-4s  %-42s 锚点失效, 白测" % (name, desc))
            missed.append(name)
            continue

        try:
            verify(sabotaged)
        except Exception as e:
            blocked += 1
            print("✅ %-4s  %-42s → %s" % (name, desc, str(e)[:52]))
            continue

        print("❌ %-4s  %-42s **判据没报红** (应命中: %s)" % (name, desc, why))
        missed.append(name)

    print()
    print("v568 反向: %d 拦下, %d 漏过" % (blocked, len(missed)))
    if missed:
        print("❌ 漏过: %s" % ", ".join(missed))
        return 1
    print("✅ 全部 sabotage 都被拦下, 且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
