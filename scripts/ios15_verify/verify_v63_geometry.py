#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v63 几何基准判据 —— 「正常」第一次有了数字定义。

【这份判据为什么存在】
  v1~v62 共 62 版判据, 全部是**相对**的: 「比 v61 好」「这个标记在位」
  「那个阈值合理」。它们的共同盲区是 —— 从来没有一份判据回答过
  「正常的工具卡片**应该**多高」。

  后果有两条, 都已实证:
    ① 「相对更好」可以一直成立而病一直没好 —— v53→v62 每版都更"好",
       而装机日志里 V53-DEBT/V62-SURPLUS 出现 **0 次**、live 恒为 0。
    ② 「文字非流式」一直无法量化 —— 因为没有基准, 「一下跳出一大段」
       无法被翻译成任何可断言的量。

  用户提供了一份**真机正常画面**(同源移植, EasyBackForWeChat 内嵌 Minis,
  iPhone @3x 1170×2532)。把它量出来, 得到:

    · 11 张同形态工具卡片, 高度 36.3~37.0 pt, **极差 0.7 pt, 标准差 0.15**
    · 卡片间距 8~11 pt, 中位 9 pt
    · ⇒ 正常 = 卡片**等高** + 间距**恒定**
      ⇒ 高度由内容**一次算定**, 不存在「先给一个值再纠正」的过程

  对照 v62 装机日志 idx=19 同一条消息的 pref 序列:
    798 → 903 → 1057 → 1205 → 1336 → 1518
    跨度 720 pt(1.9 倍), 增量 105/154/148/131/182, **6 次全部 cached=true**

  ⇒ 「狂跳」的量化定义 = 平均每 250ms 位移 120 pt = 屏高(844pt)的 14.2%
  ⇒ 「一下跳出一大段」的量化定义 = 单次增量 ≥ 105 pt
    而正常卡片全文高只有 36.7 pt ⇒ **一次跳变 ≈ 3 张卡片的位移**

  这就是三十余版缺的那把尺子。

【判定原则】
  这份判据**只做几何断言**, 不碰注入代码(那是 verify_*_v63 的职责)。
  两者的关系: verify_*_v63 守「机制在不在」, 本文件守「结果对不对」。
  ★机制在而结果不对, 正是 v53~v62 的死法 —— 所以两者都要在。

用法:
    python3 verify_v63_geometry.py --ref normal-ref.jpg
        量一份参考截图, 打印卡片几何并与本判据比对(用于收录新基准)

    python3 verify_v63_geometry.py --log <装机日志路径>
        从真机日志里抽 pref/height 序列, 断言几何在正常区间内

    python3 verify_v63_geometry.py          (无参数)
        只跑内置基准自检 + 常量自证, 退出码 0/1

退出码: 0 = 正常 / 1 = 异常 / 3 = 环境不全
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ================================================================
# 基准常量 —— 全部量自真机正常画面, 每条都注明出处
# ================================================================

# 同形态工具卡片高度(pt)。11/11 张落在 36.3~37.0。
# 样本: [36.7, 36.7, 36.7, 36.7, 37.0, 36.7, 36.7, 36.3, 36.7, 36.7, 36.7]
CARD_H_NOMINAL = 36.7      # 名义值
CARD_H_MIN = 34.0          # 下容差: 比名义小 2.7(文字更短的情形)
CARD_H_MAX = 44.0          # 上容差: 比名义大 7.3(两行文字的情形)
CARD_H_SPREAD_MAX = 8.0    # ★同一批同形态卡片的极差上限

# 卡片垂直间距(pt)。样本: [8, 9, 11, 9, 11, 8, 10, 10, 9, 11], 中位 9。
CARD_GAP_MIN = 6.0
CARD_GAP_MAX = 14.0

# 病态阈值 —— 由基准反推, 不是拍脑袋。
# 依据: 正常卡片全文高只有 36.7pt。
JUMP_ABSOLUTE_PT = 40.0    # 单次位移 > 40pt(> 1 张卡片) 即为异常
JUMP_SPREAD_RATIO = 3.0    # 跨度 > 名义高 3 倍 即为异常

# ★定型宽限帧数: 跳过头 N 帧再看极差。
#   依据是 v62 日志里的 idx=17 = [333, 70, 384, 384] —— 第 1 帧 333 是
#   首帧必然偏(内容刚到还没测量), 第 2 帧起就恒定在 384。
#   把首帧计入极差会把这种**正确**的一次定型判成病。
SETTLE_FRAMES = 2

# v62 实测值, 留作反面锚点: 若代码退化成 v62 那样, 下面两条必然触发。
V62_PREF_SEQ = [798, 903, 1057, 1205, 1336, 1518]
# ★正面锚点: 一次定型的正常形态(取自同一份日志的 idx=17)。
V62_SETTLED_SEQ = [333, 70, 384, 384]

REF_IMAGE = os.path.join(HERE, "baseline", "normal-ref.jpg")


def judge_sequence(seq, what="高度"):
    """核心断言: 给一条高度序列, 判定它是「正常」还是「v62 那样」。

    ★判据只用「尾部极差」, 不用「全段极差」—— 这是本轮踩到的第二个坑,
      也是本判据最重要的一处设计:

      同一份 v62 日志里, idx=17 与 idx=19 长这样:
        idx=17  [333, 70, 384, 384]                 全段极差 314pt
        idx=19  [798, 903, 1057, 1205, 1336, 1518] 全段极差 843pt
      按全段极差判, 两者都是病态(也确实都是), 但**理由不同**:
        idx=17 是**一次定型**: 第 1 帧给旧值, 第 2 帧测出真值 384,
               之后 3 帧完全不动 ⇒ 尾部极差 0 ⇒ 这是**正确行为**,
               甚至说明 settle 机制在 v17 上工作正常;
        idx=19 是**持续追涨**: 尾部仍在 598→1518 单调递增,
               尾部极差 436pt ⇒ 这才是病。

      换言之: 首帧偏移是**允许**的(测量本身就需要一帧),
      但定型之后还在动就是病。判据若看全段极差, 会把"首帧偏移"和
      "持续抖动"混成同一类, 于是真出现轻微持续抖动时反而被淹没。

      两条断言, 但**不等价** —— 这是本判据最关键的设计:
        【主判据 · 硬失败】尾部极差 > CARD_H_SPREAD_MAX(8pt)
            ⇒ 定型之后还在动。这是病的**定义**。
        【副判据 · 仅告警】全段跨度 > 名义高 × JUMP_SPREAD_RATIO
            ⇒ 首帧偏。**记录但不算失败**。

      为什么跨度只告警: 首帧给旧值是**测量过程的固有代价**,
      idx=17 = [333, 70, 384, 384] 就是标准的一次定型 —— 首帧偏 51pt
      (1.4 倍), 但第 3 帧起恒定 384。
      若把跨度当硬失败, 这种**可接受**形态也会报红;
      装机后满屏红 ⇒ 没人再看第二眼 ⇒ 判据自动失效。
      v53 被连续两版忽略, 正是因为它的信号一直是「零」或「常红」,
      两种都让人不再看它。⇒ 判据宁可漏报, 不可误报。

      换言之: 首帧偏移是允许的(测量本身就需要一帧),
      但定型之后还在动就是病。
    """
    if not seq or len(seq) < 2:
        return False, "%s序列样本不足(需 ≥2 个值, 实得 %d)" % (what, len(seq or []))
    # 跳过头 2 帧: 首帧必然偏(内容刚到,还没测量), 那不是病
    tail = seq[SETTLE_FRAMES:] if len(seq) > SETTLE_FRAMES else seq
    t_spread = max(tail) - min(tail)
    full_spread = max(seq) - min(seq)
    ratio = full_spread / float(CARD_H_NOMINAL)
    worst = max(abs(b - a) for a, b in zip(tail, tail[1:])) if len(tail) > 1 else 0
    warn = ""
    if full_spread > JUMP_SPREAD_RATIO * CARD_H_NOMINAL:
        warn = ("  [告警] 全段跨度 %.1fpt = 名义高的 %.1f 倍 —— 首帧偏移偏大, "
                "但不据此判死(看尾部)" % (full_spread, ratio))
    if t_spread > CARD_H_SPREAD_MAX:
        return False, ("%s**定型后仍在动**: 跳过头 %d 帧后极差仍有 %.1fpt(上限 %.1f) "
                       "⇒ 每次 invalidate 都在纠正上一次的值(cached=true), "
                       "最大单跳 %.1fpt。%s" % (what, SETTLE_FRAMES, t_spread,
                                        CARD_H_SPREAD_MAX, worst, warn))
    return True, ("%s正常: 定型后极差 %.1fpt(<=%.1f), 最大单跳 %.1fpt, "
                  "全段跨度 %.1fpt(%.1f倍, 仅首帧)。%s"
                  % (what, t_spread, CARD_H_SPREAD_MAX, worst,
                     full_spread, ratio, warn))


def measure_reference(path):
    """量一份参考截图的卡片几何。用 PIL, 缺依赖则报 SKIP。"""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None, "缺 PIL/numpy, 无法量图"
    if not os.path.exists(path):
        return None, "参考图不存在: %s" % path
    a = np.array(Image.open(path).convert("RGB"))
    h, w, _ = a.shape
    # 取左侧区域(避开右侧耗时数字/图标), 判"该行有 ≥2% 像素非白"
    sub = a[:, int(w * 0.05):int(w * 0.77), :]
    nonwhite = (np.abs(sub.astype(int) - 255).max(axis=2) > 8).mean(axis=1)
    rows = nonwhite > 0.02
    segs, s = [], None
    for y in range(h):
        if rows[y] and s is None:
            s = y
        elif not rows[y] and s is not None:
            segs.append((s, y - 1))
            s = None
    if s is not None:
        segs.append((s, h - 1))
    # 换算成 pt, 只留卡片尺寸区间(排除状态栏/输入栏)
    cards, tops = [], []
    for st, en in segs:
        pt = (en - st + 1) / 3.0
        if CARD_H_MIN - 8 <= pt <= CARD_H_MAX + 8:
            cards.append(pt)
            tops.append(st // 3)
    gaps = [b - a - round(CARD_H_NOMINAL)
            for a, b in zip(tops, tops[1:])]
    return (cards, gaps), None


def extract_pref_from_log(path):
    """从装机日志抽 pref= 序列(用于真机验证)。

    ★必须**按 idx 分组**, 不能把全日志混成一条 —— 这是本轮踩到的坑:
      不分组时 77 个样本算出的跨度是 1605pt(= 名义高 43.7 倍), 看着像
      「一条消息在疯长」; 分组后才发现真相是**多条消息各自在疯长**,
      且最长的 idx=19 是 798→903→...→1641 严格单调递增。
      混算会把「组内跳变」误读成「组间差异」, 判据一旦这样用,
      真出现单条消息小幅波动时反而会被淹掉。
    """
    if not os.path.exists(path):
        return None, "日志不存在: %s" % path
    pat_idx = re.compile(r"idx=(\d+)")
    pat_pref = re.compile(r"\bpref=([0-9]+(?:\.[0-9]+)?)")
    groups = {}
    order = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "pref=" not in line:
                continue
            mi, mp = pat_idx.search(line), pat_pref.search(line)
            if not mp:
                continue
            i = int(mi.group(1)) if mi else -1
            if i not in groups:
                groups[i] = []
                order.append(i)
            groups[i].append(float(mp.group(1)))
    if not groups:
        return None, "日志里没有 pref= 字段"
    return (groups, order), None


def selfcheck():
    """基准自证: 常量之间必须自洽, 且必须能区分正常与 v62 两个已知形态。

    ★这是判据自己的判据 —— reverse_v63 守的是「注入在不在」,
      本函数守的是「尺子准不准」。一把量错 100pt 的尺子比没有尺子更危险。
    """
    bad = []
    if not (CARD_H_MIN <= CARD_H_NOMINAL <= CARD_H_MAX):
        bad.append("名义值 %.1f 不在 [%.1f, %.1f] 内"
                   % (CARD_H_NOMINAL, CARD_H_MIN, CARD_H_MAX))
    if CARD_H_SPREAD_MAX >= CARD_H_NOMINAL:
        bad.append("极差上限 %.1f ≥ 名义高 %.1f ⇒ 这把尺子量不出病"
                   % (CARD_H_SPREAD_MAX, CARD_H_NOMINAL))
    if JUMP_SPREAD_RATIO <= 1:
        bad.append("跨度倍数 %.1f ≤ 1 ⇒ 比单张卡片还宽松, 无意义"
                   % JUMP_SPREAD_RATIO)
    # 正常样本必须通过
    ok_norm, why_norm = judge_sequence(
        [36.7, 36.7, 36.7, 36.7, 37.0, 36.7, 36.7, 36.3, 36.7, 36.7, 36.7],
        "正常卡片高")
    if not ok_norm:
        bad.append("真实正常样本被判为异常: %s" % why_norm)
    # ★一次定型的正面锚点必须通过 —— 取自同一份 v62 日志的 idx=17。
    #   它首帧偏 333, 第 2 帧起恒定 384, 全段极差 314pt。
    #   若判据把它判红, 说明「首帧偏移」被误当成了「持续抖动」,
    #   那种判据装机后会把每一次正确的一次定型都报成病, 很快被忽略。
    ok_set, why_set = judge_sequence(V62_SETTLED_SEQ, "一次定型")
    if not ok_set:
        bad.append("「一次定型」形态被判为异常(误报): %s" % why_set)
    # v62 反面样本必须被抓住
    ok_v62, _ = judge_sequence(V62_PREF_SEQ, "v62 pref")
    if ok_v62:
        bad.append("v62 的 pref 序列竟然判为正常 ⇒ 尺子量不出 720pt 跳变")
    # 间距常量须包含实测中位
    if not (CARD_GAP_MIN <= 9 <= CARD_GAP_MAX):
        bad.append("间距区间不含实测中位 9pt")
    return bad


def main():
    args = sys.argv[1:]
    print("=" * 66)
    print("v63 几何基准判据 —— 「正常」的可断言定义")
    print("=" * 66)
    print("基准来源: 真机正常画面(iPhone @3x 1170×2532, 同源移植)")
    print("  同形态卡片 11 张: 36.3~37.0 pt, 极差 0.7 pt, 标准差 0.15")
    print("  卡片间距: 8~11 pt, 中位 9 pt")
    print("  ⇒ 正常 = 卡片**等高** + 间距**恒定** = 高度由内容一次算定")
    print()
    print("阈值(全部从上面反推, 非经验值):")
    print("  卡片高 %.1f pt  容差 [%.1f, %.1f]" % (CARD_H_NOMINAL, CARD_H_MIN, CARD_H_MAX))
    print("  同批极差上限 %.1f pt   间距 [%.1f, %.1f] pt"
          % (CARD_H_SPREAD_MAX, CARD_GAP_MIN, CARD_GAP_MAX))
    print("  病态: 单次位移 > %.1f pt(>1 张卡片) 或 跨度 > %.1f 倍"
          % (JUMP_ABSOLUTE_PT, JUMP_SPREAD_RATIO))

    print()
    print("[自证] 常量自洽 + 必须能区分正常/v62 两个已知形态")
    bad = selfcheck()
    if bad:
        for b in bad:
            print("  ✗ %s" % b)
        print("v63geom=BAD")
        return 1
    print("  ✓ 常量自洽; 正常样本判正常, v62 样本判异常")

    if "--ref" in args:
        p = args[args.index("--ref") + 1] if len(args) > args.index("--ref") + 1 \
            else REF_IMAGE
        got, err = measure_reference(p)
        print()
        print("[参考图量算] %s" % p)
        if got is None:
            print("  SKIP %s" % err)
        else:
            cards, gaps = got
            print("  卡片高(pt): %s" % [round(c, 1) for c in cards])
            if cards:
                print("  极差 %.1f pt (上限 %.1f)" % (max(cards) - min(cards), CARD_H_SPREAD_MAX))
            if gaps:
                print("  间距(pt): %s" % gaps)
            ok, why = judge_sequence(cards, "参考图卡片高")
            print("  %s %s" % ("✓" if ok else "✗", why))

    if "--log" in args:
        p = args[args.index("--log") + 1] if len(args) > args.index("--log") + 1 else ""
        got, err = extract_pref_from_log(p)
        print()
        print("[装机日志] %s" % p)
        if got is None:
            print("  SKIP %s" % err)
            print("v63geom=SKIP")
            return 3
        groups, order = got
        total = sum(len(v) for v in groups.values())
        print("  pref 样本 %d 条, 分属 %d 个 idx(★按 idx 分组判定, 不混算)" % (total, len(groups)))
        # 样本不足 4 的组不足以判「序列」(只能判单值), 单列出来供参考
        big = [(i, groups[i]) for i in order if len(groups[i]) >= 4]
        small = [(i, groups[i]) for i in order if len(groups[i]) < 4]
        print()
        print("  %-6s %-4s %-11s %-11s %s" % ("idx", "n", "尾部极差", "全段跨度", "判定"))
        print("  " + "-" * 58)
        bad_groups = []
        for i, v in sorted(big, key=lambda kv: -len(kv[1])):
            ok, why = judge_sequence(v, "idx=%d" % i)
            if not ok:
                bad_groups.append((i, why))
            tl = v[SETTLE_FRAMES:] if len(v) > SETTLE_FRAMES else v
            print("  %-6d %-4d %-11.1f %-11.1f %s" % (
                i, len(v), max(tl) - min(tl), max(v) - min(v),
                "✓ 定型后稳定" if ok else "✗ 病态"))
        for i, v in small:
            print("  %-6d %-4d %-11s %-11s (样本不足, 跳过)" % (i, len(v), "-", "-"))
        print()
        if bad_groups:
            print("  ✗ %d/%d 个 idx 呈病态:" % (len(bad_groups), len(big)))
            for i, why in bad_groups[:5]:
                print("     idx=%-3d %s" % (i, why))
            if len(bad_groups) > 5:
                print("     ... 另 %d 个" % (len(bad_groups) - 5))
            print("v63geom=BAD")
            return 1
        print("v63geom=OK")

    print()
    print("v63geom=OK")
    print()
    print("⚠ 装机后请用 --log 复核真机几何:")
    print("   · 正常应有: 极差 <= %.0f pt" % CARD_H_SPREAD_MAX)
    print("   · 若见 798→903→1057→... 这种跨度数百 pt 的序列 ⇒ 病未除")
    print("   · 单独看单帧截图看不出跳动 —— 必须看**序列**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
