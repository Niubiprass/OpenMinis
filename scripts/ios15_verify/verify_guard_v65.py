#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_guard_fixsize_v65 —— v65/v66/v68/v76/v77 守卫判据（11 层）。

【为什么要有这一层】v65 是本项目第五次「判据全绿但药不治病」之后的产物，
历史教训(run#156/157/159 + v64初版)已经证明：查「标记在不在」的判据
必然漏掉「代码引用的东西不存在」「数据流顺序让它不生效」这类真错。

五层分别对应五种真错：
  ① 去丢弃      —— REJECT 分支不得再含 width<0/height<0 的整段丢弃
  ② 真的转发    —— 修正后不得 return，必须落到原始 IMP 调用
  ③ 熔断只对哨兵 —— 真实行高不得进风暴预算
  ④ 常量一致    —— 熔断判据的 2000 必须与 kProbeHeightCeiling 一致
  ⑤ 标识符存在  —— run#159 的教训：引用的东西必须真的声明了
  ⑥ 不依赖 category —— CI#162 的教训：CGRect.width 是 category 不是字段
"""
import re
import sys

PROBE = "2000.0"
SENTINEL_MIN = 2000.0


def verify_guard_fixsize_v65(src):
    if not src:
        raise RuntimeError("守卫源码为空 —— 判据自己跑没跑? 必须独立判空, 不计通过")

    # ★全程只在去注释后的文本上做结构检查: v65 的注释里就写着这些条件与
    #   标识符名, 不剥注释会让正则撞上注释 ⇒ 判据误报。
    #   (判据自己的误报比没有判据更贵 —— verify-discipline §15)
    code = _strip_comments(src)

    # ---------- 第 ① 层: 丢弃分支必须已消失 ----------
    # 旧形态: if (!isfinite(w) || !isfinite(h) || w < 0 || h < 0) { ... return; }
    # 新形态: NaN/inf 单独硬拒(保留), 非正尺寸走修正转发(不 return)
    hard_reject = re.search(
        r"if\s*\(\s*!isfinite\(newSize\.width\)\s*\|\|\s*!isfinite\(newSize\.height\)\s*\)\s*\{",
        code)
    if not hard_reject:
        raise RuntimeError(
            "① 未找到 NaN/inf 的硬拒分支。\n"
            "  期望形如 `if (!isfinite(newSize.width) || !isfinite(newSize.height)) {`。\n"
            "  若这层被整段删掉, NaN/inf 会直接进 TextKit => CoreText "
            "fillLayoutHole 病态循环(v4 实证 11918ms 主线程卡死)。")

    # 旧的合并式丢弃: 把 <0 混进同一个 if。出现即说明合并分支没拆开。
    merged = re.search(
        r"!isfinite\(newSize\.width\)\s*\|\|\s*!isfinite\(newSize\.height\)\s*\|\|"
        r"\s*newSize\.width\s*<\s*0\s*\|\|\s*newSize\.height\s*<\s*0", code)
    if merged:
        raise RuntimeError(
            "① 仍然是「NaN/inf 与负尺寸合并成一个 if」的旧形态。\n"
            "  这正是 v65 要拆的: 负尺寸被连带丢弃 => TextKit 保留过期几何 => 卡字。\n"
            "  必须拆成两段 —— NaN/inf 硬拒, 有限非正修正转发。")

    # ---------- 第 ② 层: 修正后必须真的转发 ----------
    fix = re.search(r"\[V65-FIXSIZE\]", src)
    if not fix:
        raise RuntimeError("① 未找到 [V65-FIXSIZE] 落点标记 —— 修正逻辑没注入。")

    # 进入条件在 if 的括号里, 不在花括号块内 —— 所以单独验条件本身。
    # 必须**同时**判两个分量: 只判一个会漏掉另一半形态
    # (装机 0.0x-8.0 / 0.0x-16.0 都是「宽 0 且高负」, 只修高度则宽度仍为 0)。
    _mi = src.index("[V65-FIXSIZE]")
    _mc = re.search(r"newSize\.width\s*<=\s*0\s*\|\|\s*newSize\.height\s*<=\s*0",
                    code[_mi:])
    if not _mc:
        raise RuntimeError(
            "② 修正分支的进入条件缺失。\n"
            "  必须同时判 width<=0 与 height<=0 —— 只判一个会漏掉另一半形态"
            "(装机日志 0.0x-8.0 是宽 0 高负, 0.0x-16.0 同; "
            "只修高度则宽度仍为 0, 排版依旧错行)。")
    # 两分量必须真的在**同一个** if 里(防止写成两个独立 if 的半吊子修法)
    body = _brace_block(code, code.index("{", _mi + _mc.end()))
    # 两分量必须真的在**同一个** if 里(防止写成两个独立 if 的半吊子修法)。
    # ★只看条件所在的那一行: 从标记起算会一路包含后面嵌套的所有 if。
    _ifstmt_start = code.rfind("if", _mi, _mi + _mc.end())
    if _ifstmt_start < 0:
        raise RuntimeError("② 找不到承载修正条件的 if 语句。")
    _ifopen = code.find("{", _mi + _mc.end())
    _ifhead = code[_ifstmt_start:_ifopen]
    if _ifhead.count("if") != 1:
        raise RuntimeError(
            "② 修正条件被拆到了多个 if 里(%s)。\n"
            "  两个分量必须在同一个 `if (width<=0 || height<=0)` 内 —— "
            "拆开会出现「只进一个分支、另一半没修」的空档。" % _ifhead.strip())

    # [v66] 负高修正: 不再要求"直接赋 fabs" —— 那个写法对 height==0 是
    # **空操作**(fabs(0.0)==0.0), 装机日志 size=0.0x0.0 -> 326.0x0.0 实锤。
    # 现在要求的是"对 fabs 结果做**下界钳制**", 由第 ⑦ 层进一步断言。
    # 本层只管"负高确实被取过绝对值"(装机 0.0x-8.0 / 0.0x-16.0 那批)。
    if not re.search(r"fabs\s*\(\s*newSize\.height\s*\)", body):
        raise RuntimeError(
            "② 负高修正缺失: 必须在修正分支里对 height 取 fabs。\n"
            "  装机 61 次里 43 次是 -8.0、18 次是 -16.0 —— 正好是 "
            "textContainerInset 的量级(上游把 inset 减了两遍)。"
            "不取绝对值则负高原样喂回 TextKit。\n"
            "  ★v66 起不再要求写成 `newSize.height = fabs(...)` —— 那个写法\n"
            "    对 height==0 是空操作, 改为 fabs + 下界钳制(见第 ⑦ 层)。")

    # ★关键: **从修正块起点**到原始 IMP 调用之间不得有 return ——
    #   一旦 return 就退回「丢弃」语义, 而丢弃正是卡字的直接原因。
    #   ★为什么从修正块起算(而不是从进入条件起算):
    #     NaN/inf 硬拒分支里有它**合法**的 return(必须硬拒, 不能修正)。
    #     那个分支在修正块之前, 不该被本检查覆盖。
    #   ★★但不能一棍子打尽: 熔断的 storm-breaker SKIP 分支里也有 return,
    #     而**那是合法的** —— 丢弃哨兵尺寸正是熔断的设计意图(v4 斩断
    #     fillLayoutHole 风暴)。本项目要禁的是"丢弃**非正尺寸**"。
    #     所以规则是: 从修正块起点到 IMP 调用之间, **不允许任何 return** ——
    #     因为修正块之后的代码处理的都是哨兵, 那些 return 由第③层的
    #     「门槛包住自增」来保证正确性, 不在本检查的射程内。
    #     换句话说: 修正块之后的 return 之所以合法, 是因为它们只在
    #     **哨兵已被识别**的分支里; 若修正值仍会流到那里(真实排版),
    #     门槛豁免已经放行了它 —— 此时不该再有任何 return。
    #     为避免误伤合法熔断, 这里只查「修正块内部到修正块结束」。
    _blk = code.index("{", _mi + _mc.end())
    _blkbody = _brace_block(code, _blk)
    _tail_wo_finally = re.sub(r"@\s*finally\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
                              "", _blkbody, flags=re.S)
    if re.search(r"\breturn\b", _tail_wo_finally):
        _first = _tail_wo_finally.index("return")
        raise RuntimeError(
            "② 修正块内出现了 return —— 等于退回旧的「丢弃」行为。\n"
            "  丢弃 = TextKit 保留过期几何 = 排版结果永远滞后 = 卡字。\n"
            "  修法必须是「就地改值后继续往下走, 照常转发给 TextKit」。\n"
            "  首次出现处上下文: %s"
            % _tail_wo_finally[max(0, _first - 60):_first + 40].replace("\n", " "))

    # 修正后必须仍能到达原始 IMP 调用 —— 用位置关系证明数据流通
    # [v66] 锚点从 `newSize.height = fabs` 改成 fabs 调用本身: 新写法是
    # `CGFloat _ah = fabs(newSize.height);` + 下界钳制, 旧的锚点已不存在。
    g = body.rfind("fabs")
    call = code.rfind("gOriginalSetSize)(self, _cmd, newSize)")
    if g < 0:
        raise RuntimeError("② 找不到负高修正语句(fabs 调用)。")
    if call < g:
        raise RuntimeError(
            "② 数据流断裂: 原始 setSize: 调用出现在修正语句**之前** —— "
            "修正的值永远传不到 TextKit, 等于白改。")

    # ---------- 第 ③ 层: 熔断只对哨兵计费 ----------
    st = re.search(r"\[V65-STORM\]", src)
    if not st:
        raise RuntimeError("③ 未找到 [V65-STORM] 落点 —— 熔断豁免没注入。")
    # ★条件在**外层** if 的括号里, 花括号块只是它的 body。
    #   所以不能用 _block_after(那会取到 body 而看不到条件)。
    #   正确做法: 在去注释副本上、标记之后搜门槛条件, 再取它的整块。
    _si = src.index("[V65-STORM]")
    m_gate = re.search(r"if\s*\(\s*newSize\.height\s*>=\s*%s\s*\)" % re.escape(PROBE),
                       code[_si:])
    if not m_gate:
        raise RuntimeError(
            "③ 熔断预算的哨兵门槛缺失。\n"
            "  必须形如 `if (newSize.height >= 2000.0)` —— 只有被哨兵钳位压过的"
            "高度才是风暴源。\n"
            "  少了门槛就等于把熔断整个废掉, v4 实证的 11918ms 卡死会回来。")
    gb = _brace_block(code, code.index("{", _si + m_gate.end()))

    # ★反向式: commitCount 的自增必须被门槛包住。若自增在门槛之外,
    # 真实行高照样计入预算 => 熔断照旧吞掉 358x19.0 / 358x41.0。
    if "s->commitCount += 1" not in gb:
        raise RuntimeError(
            "③ `s->commitCount += 1` 不在哨兵门槛的 if 块内。\n"
            "  这就是「数据流顺序让它不生效」那一类错(run#159 同族)。\n"
            "  门槛必须在自增**外面**包住, 否则真实排版照旧计入预算。")
    if "s->stormed = YES" not in gb:
        raise RuntimeError("③ 熔断置位 `s->stormed = YES` 不在哨兵门槛块内。")

    # ---------- 第 ④ 层: 常量一致性 ----------
    ceil = re.search(r"kProbeHeightCeiling\s*=\s*([0-9.]+)", code)
    if not ceil:
        raise RuntimeError("④ 找不到 kProbeHeightCeiling 的定义。")
    ceil_v = float(ceil.group(1))
    if abs(ceil_v - SENTINEL_MIN) > 0.5:
        raise RuntimeError(
            "④ 常量不一致: kProbeHeightCeiling=%.1f 但熔断门槛用 %.1f。\n"
            "  两者必须相等 —— 哨兵被压到 ceil, 门槛却按别的值判, "
            "会让真实排版重新落进风暴预算(v65 的两条改动互相抵消)。"
            % (ceil_v, SENTINEL_MIN))

    # ---------- 第 ⑤ 层: 标识符存在性 ----------
    for ident in ("gOriginalSetSize", "gShortCircuitCount", "gRunloopTick",
                  "kStormForwardLimit", "kProbeHeightCeiling"):
        if not re.search(r"\b%s\b" % re.escape(ident), code):
            raise RuntimeError(
                "④ 引用的 %r 在文件里**不存在** —— 会编译红。\n"
                "  这正是 run#159 的真实教训: 判据全绿, 编译器找不到符号。"
                % ident)

    # ★作用域检查(run#157/run#159 同族错误的第四次预防):
    # kProbeHeightCeiling 是在函数体内某段 {} 里声明的局部 const,
    # 若 V65-STORM 段落引用它就会出作用域错误。
    storm_ref = re.search(r"\[V65-STORM\].*?kProbeHeightCeiling\s*[;)\]]",
                          code, re.S)
    if storm_ref:
        raise RuntimeError(
            "⑤ V65-STORM 段落引用了 kProbeHeightCeiling —— 它是函数体内"
            "局部的 const, 不在该段落作用域内, **会编译失败**。\n"
            "  必须写字面量 2000.0。这是我本轮真实犯过一次并当场抓住的错误。")
    # ---------- 第 ⑥ 层: 不得依赖 CGRect 的 category 成员 ----------
    # ★★★ 这层是 CI#162(run 37275980272) 编译红的**唯一**防线。
    #   真实错误: NSTextContainerSetSizeGuard.m:153:51:
    #       error: no member named 'width' in 'struct CGRect'
    #   根因: CGRect 没有 width/height **字段**, 它们是 CoreGraphics 的
    #   `CGGeometry` **category**; 而 UIKit 的模块化导入**不 re-export**
    #   该 category ⇒ 光有 `#import <UIKit/UIKit.h>` 也不够。
    #   ★为什么之前没被抓住: 我自建的 clang 桩里给 CGRect **补了**这两个
    #     字段当"方便", 桩比真实 SDK 宽松 ⇒ 0 error 的**假绿**。
    #     ⇒ 判据必须**独立于任何桩**, 直接在源码上把这条禁令固化下来。
    cg = re.search(r"\.\s*(bounds|frame|size|origin)\s*\.\s*"
                   r"(width|height|minX|minY|maxX|maxY|midX|midY)\b", code)
    if cg:
        raise RuntimeError(
            "⑥ 用到了 CGRect 的 category 成员 `%s.%s` —— **会编译红**。\n"
            "  实测(CI#162): error: no member named '%s' in 'struct CGRect'\n"
            "  CGRect 没有 width/height 字段, 它们是 CoreGraphics `CGGeometry`\n"
            "  category 提供的, 而 UIKit 的模块化导入**不 re-export** 它。\n"
            "  ⇒ 改走 KVC: [[obj valueForKey:@\"bounds\"] CGSizeValue].width\n"
            "  ★注意 CGSize 的 width/height 是**真** struct 成员, 那个可以用。"
            % (cg.group(1), cg.group(2), cg.group(2)))
    # ---------- 第 ⑦ 层: 修正必须**真的**修正（防空操作）----------
    # ★★★ 这层是 v65 装机日志(8.log)直接指出的缺陷的防线。
    #   实测: size=0.0x0.0 -> 326.0x0.0  × 82507 条日志
    #        ⇒ 实际进入修正分支 2644129 次, 全部是 height **0.0**
    #   根因: 修正写的是 `newSize.height = fabs(newSize.height)`,
    #         而 **fabs(0.0) == 0.0** ⇒ 打印出的前后尺寸完全相同
    #         ⇒ 所谓"修正转发"对最常见的 0x0 形态是**空操作**。
    #   ⇒ 单容器 14 秒 264 万次: 内存 151.8→624.2MB(+470MB) ⇒ SIGKILL;
    #     同期主线程 6281ms 卡顿 ⇒ 抖动。抖/卡/崩**同一个根因**。
    #
    # 【为什么源码正则抓不到, 必须显式断言】
    # `fabs` 这个写法**语法完全合法**, 任何"看代码像不像修好了"的检查都会
    # 放行 —— 本项目前六代判据就是这么漏掉的。必须直接断言:
    #   高度分支里**不允许**出现把 fabs 结果直接赋回去的写法,
    #   且**必须**有一个把结果抬到 >0 的下界钳制。
    m = re.search(r"newSize\.height\s*=\s*fabs\s*\(\s*newSize\.height\s*\)", code)
    if m:
        raise RuntimeError(
            "⑦ 高度修正写成了 `newSize.height = fabs(newSize.height)` ——\n"
            "  **对 height==0 是空操作**(fabs(0.0)==0.0), 装机日志实测:\n"
            "      size=0.0x0.0 -> 326.0x0.0  (前后尺寸完全相同)\n"
            "    82507 条日志 / 实际 2644129 次 / 单容器 14 秒\n"
            "    ⇒ 内存 +470MB ⇒ SIGKILL; 同期主线程 6281ms 卡顿 ⇒ 抖动\n"
            "  ⇒ 抖、卡、闪退是**同一个根因**, 不是三个病。\n"
            "  必须把 0/-0/亚 1pt 抬到一个**正的**合法高度(如 1.0)。\n"
            "  ★本项目第七次「验证手段骗了自己」的前车之鉴:\n"
            "    这段代码**语法合法、编译通过、判据全绿**, 唯独装机不治病。")
    if not re.search(r"!\s*\(\s*_\w+\s*>\s*1\.0\s*\)", code):
        raise RuntimeError(
            "⑦ 高度修正缺少**下界钳制** —— 非正高度被修正后仍可能是 0。\n"
            "  装机日志: size=0.0x0.0 -> 326.0x0.0 (高度 0 → 还是 0)。\n"
            "  必须有一个形如 `if (!(_ah > 1.0)) { _ah = 1.0; }` 的钳制,\n"
            "  把 0 / -0 / 亚 1pt 抬到正的合法高度。")
    # 跨 tick 硬闸门: 止住 264 万次的那种机制必须存在且不被清零。
    if "kNonPositiveHardLimit" not in code:
        raise RuntimeError(
            "⑦ 缺少 `kNonPositiveHardLimit` 跨 tick 硬闸门。\n"
            "  per-tick 的 storm-breaker 每换 tick 就清零, 而上游 0x0 是\n"
            "  **每个 tick 都在喂** ⇒ 计数永远到不了 40 ⇒ 永远不熔断\n"
            "  ⇒ 实测单容器 14 秒 2644129 次 ⇒ +470MB ⇒ SIGKILL。\n"
            "  ⇒ 必须在 GuardState 里有**跨 tick 累加**的 nonPositiveStreak。")
    if re.search(r"nonPositiveStreak\s*=\s*0", code):
        raise RuntimeError(
            "⑦ `nonPositiveStreak` 被清零了 —— 它必须**跨 tick 累加**。\n"
            "  它存在的唯一意义是止住「每 tick 都喂 0x0」这种形态;\n"
            "  一旦按 tick 清零, 就退回 per-tick 熔断的老行为 ⇒ 永不熔断。")

    # ---------- 第 ⑧ 层 (v68): 累加必须在 per-tick 门槛**之外** ----------
    # ★★★ 本项目**第八次**「验证手段骗了自己」的防线。
    #
    # 【v66/v67b 装机的实测铁证】minis-2026-10-06.log:
    #     [V65] FIXED-NONPOSITIVE size=0.0x0.0 -> 326.0x1.0 total=1970881
    #     container=0x283da6f80  × 61584 条日志(每 32 打 1)
    #     ⇒ 实际进入修正分支 **197 万次 / 11 秒 / 单容器**
    #     内存 35.5MB → **1474.6MB**(+1.4GB) ⇒ SIGKILL(PID 28466→28473)
    # 而三条闸门日志**各 0 次**:
    #     storm-breaker SKIP / NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP
    #
    # 【v66 的病根 —— 累加被埋在 per-tick 门槛里, 是死代码】
    #     } else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {
    #         s->commitCount += 1;
    #         if (s->commitCount > kStormForwardLimit) {   // ← per-tick 门槛
    #             s->stormed = YES;
    #             s->nonPositiveStreak += 1;              // ← 死代码
    #         }
    #     }
    # commitCount 由 `if (_newTick) { s->commitCount = 0; }` **每 tick 清零**,
    # 而 0x0 是「每 tick 只喂一两次」的形态 ⇒ commitCount 永远到不了 40
    # ⇒ streak 永不增长 ⇒ 硬闸门永不触发。
    #
    # ★★ **为什么第 ⑦ 层全绿**: 它问的是"`nonPositiveStreak` 会不会被清零"
    #   (答案: 不会, 恒真) —— 而病根是"它会不会被**累加**"(答案: 不会, 恒假)。
    #   **问错了问题, 绿灯就是假的。** 判据必须直接问累加的位置。
    seg = _block_after(src, "} else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {", code)
    m_acc = re.search(r"s->nonPositiveStreak\s*\+=\s*1", seg)
    if not m_acc:
        raise RuntimeError(
            "⑧ 非正尺寸分支里**没有** `nonPositiveStreak += 1` —— "
            "跨 tick 硬闸门永远不会被触发。\n"
            "  装机实测(10-06.log): 197 万次修正 / 11 秒 / 单容器 /\n"
            "  内存 35.5MB → 1474.6MB ⇒ SIGKILL, 而\n"
            "  storm-breaker / NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP **各 0 次**。")
    # ★ 关键断言: 累加语句的**花括号深度**必须与 else-if 块本身同级,
    #   即不得位于任何 `if (...) {` 之内。v66 的形态是深度 +1(埋在门槛里)
    #   ⇒ 这条断言直接判它死代码。这就是"问对问题"。
    depth = _rel_depth(seg, m_acc.start())
    if depth > 0:
        raise RuntimeError(
            "⑧ `nonPositiveStreak += 1` 位于**嵌套 if 内部**(相对深度 +%d) ——\n"
            "  它被 per-tick 门槛 `commitCount > kStormForwardLimit` 挡住了,\n"
            "  而 commitCount **每 tick 清零**(`if (_newTick) { s->commitCount = 0; }`)。\n"
            "  0x0 是「每 tick 只喂一两次」的形态 ⇒ 永远到不了 40 ⇒\n"
            "  **这行是死代码**, 硬闸门永不触发。\n"
            "  装机实测: 197 万次 / 11 秒 / 内存 +1.4GB ⇒ SIGKILL,\n"
            "  而 NONPOSITIVE-HARDSTOP 日志 **0 次**。\n"
            "  ★v66 的第 ⑦ 层判据问的是「streak 会不会被清零」(恒真),\n"
            "    病根是「会不会被累加」(恒假) —— **问错问题, 绿灯就是假的**。\n"
            "  ⇒ 修法: 累加必须**无条件**执行, 移出 per-tick 门槛。"
            % depth)

    # ---------- 第 ⑨ 层 (v68): 硬闸门不得永久冻结, 修正值不得是活锁燃料 ----------
    # ⑨-1: 命中上限后必须是**降频放行**(有游标), 不是无条件 return。
    seg2 = _block_after_hardstop(code)
    if not ("nonPositiveSkipTick" in seg2 or "gGlobalSkipTick" in seg2):
        raise RuntimeError(
            "⑨ 跨 tick 硬闸门是**永久冻结**(命中即 return) —— 这是把内存问题\n"
            "  原地换成了空白问题:\n"
            "  · 一旦上游持续算崩, 该容器**再也收不到任何 setSize**\n"
            "  · 高度永久冻结在最后一个值 ⇒ 屏幕保留一整块旧几何 ⇒\n"
            "    **巨大空白**(v61 刚修掉的症状换个形态回来)\n"
            "  · 还把「上游万一自愈」的可能性一并删掉了\n"
            "  ⇒ 守卫的职责是让 App 活下去, **永久冻结是让它死得更快**。\n"
            "  必须改成: 命中上限后每 kNonPositiveSkipStride 次放行 1 次。")
    if "kNonPositiveSkipStride" not in seg2:
        raise RuntimeError(
            "⑨ 降频逻辑缺少 `kNonPositiveSkipStride` 步长常量 ——\n"
            "  必须有一个明确的放行步长(不能是裸数字, 否则无法反推降频比)。")
    # ⑨-1b (v69): 降频游标必须是**进程级** gGlobalSkipTick。
    #
    # 【为什么 per-container 游标不够 —— 第十三次「验证手段骗了自己」】
    # 装机 minis-2026-10-06 2.log: 「点击选择模型」11 秒 1,957,633 次,
    # 而 DOWNFREQ=0。原因: SwiftUI measure 时**每次新建一个 NSTextContainer**
    # ⇒ GuardState 每次全新 ⇒ per-container 游标恒为 0 ⇒ 每次都走到"放行"
    # ⇒ **降频等于没写**。判据若只查"游标在不在"就又是假绿 —— 必须查
    # "游标挂在哪一级": 容器级会在容器工厂形态下失效, 进程级不会。
    if "gGlobalSkipTick" not in seg2:
        raise RuntimeError(
            "⑨-1b 降频游标仍是**per-container** nonPositiveSkipTick ——\n"
            "  它在「容器工厂」形态下恒为 0 ⇒ 每次都放行 ⇒ 降频完全落空。\n"
            "  装机铁证(minis-2026-10-06 2.log): 点击「选择模型」11 秒\n"
            "  1,957,633 次, DOWNFREQ **0** 次 —— 语句全在、结构全对,\n"
            "  只因 SwiftUI 每次 measure 都新建一个 NSTextContainer,\n"
            "  GuardState 随之每次全新 ⇒ streak 恒 1、游标恒 0。\n"
            "  ⇒ 必须用**进程级** gGlobalSkipTick(v69③)。")
    # ⑨-1c (v69): 闸门判据必须有**进程级**一路, 否则容器重建时永不超限。
    if "gGlobalNonPositiveStreak" not in code:
        raise RuntimeError(
            "⑨-1c 缺进程级 gGlobalNonPositiveStreak —— 容器每次重建时,\n"
            "  per-container 的 streak 恒为 1, 永远到不了 400 ⇒ 闸门不开。\n"
            "  必须有一路与容器生命周期无关的计数(v69①)。")
    if "nonPositiveStreak" not in code or "lastGoodHeight" not in code:
        raise RuntimeError(
            "⑨ GuardState 缺 `lastGoodHeight` / `nonPositiveSkipTick` 字段 ——\n"
            "  lastGoodHeight 承载「上一次真实排版过的高度」, 是断活锁的关键。")
    # ⑨-3: lastGoodHeight 必须**有人写它**(§19 变体: 字段存在 != 被赋值)。
    #   ★这条是 S17 反向实测漏过之后补的: 只查"字段在不在 + 下界钳制块里
    #   有没有**读**它"是不够的 —— 一个永远为 0 的字段也能满足这两条,
    #   而非正高度的修正值正依赖它的值 ⇒ 每次都退回 1.0 ⇒ 活锁照旧。
    if not re.search(r"s->lastGoodHeight\s*=\s*newSize\.height", code):
        raise RuntimeError(
            "⑨ `lastGoodHeight` 从未被赋值 —— 字段存在但永远为 0。\n"
            "  这是 §19 的新变体: 「标识符存在 != 可见」变成「**字段存在 != 被赋值**」。\n"
            "  后果: 非正高度的修正值每次都退回 1.0 ⇒ 活锁照旧 ⇒\n"
            "  197 万次/11秒/内存+1.4GB ⇒ SIGKILL, 而所有「字段存在」类断言全绿。\n"
            "  必须有 `s->lastGoodHeight = newSize.height;`(且在高度为正有限时才记)。")

    # ⑨-2: 非正高度的修正值不得是**裸 1.0**(活锁燃料)。
    #   装机铁证: v66 把 0.0 抬到 1.0 **生效了**(日志 326.0x1.0),
    #   但 197 万次修正结果**全是同一个值 1.0** ⇒ 上游收到 1.0 与 0.0
    #   在它眼里是同一件事(都排不出任何东西, 1pt 装不下任何一行)
    #   ⇒ 自反馈回路一秒都没被改变 ⇒ 活锁。
    m_floor = re.search(r"if\s*\(\s*!\s*\(\s*_\w+\s*>\s*1\.0\s*\)\s*\)\s*\{([^}]*)\}", code)
    if not m_floor:
        raise RuntimeError(
            "⑨ 找不到高度下界钳制块 —— 非正高度仍可能被原样喂回。")
    floor_body = m_floor.group(1)
    if "lastGoodHeight" not in floor_body:
        raise RuntimeError(
            "⑨ 非正高度的修正值是**裸 1.0** —— 那是**活锁的燃料**。\n"
            "  装机实测(10-06.log): v66 的钳制**确实生效了*"
            "(size=0.0x0.0 -> **326.0x1.0**),\n"
            "  但 197 万次修正的结果**全是同一个值 1.0** ⇒ 上游拿到 1.0 "
            "和拿到 0.0\n"
            "  是同一件事(1pt 装不下任何一行, 排版回报 0 行) ⇒ 上游继续算崩 ⇒\n"
            "  **自反馈一秒都没被断掉** ⇒ 11 秒吃掉 1.4GB。\n"
            "  ★ v65 的病是「修正成和原来一样的值」(空操作);\n"
            "    v66 的病是「修正成**上游仍然不满意**的值」(活锁)。\n"
            "    两者断的位置不同: v65 改「修正成什么」, v66 改「还转不转发」。\n"
            "  ⇒ 必须优先用 `s->lastGoodHeight`(该容器上一次真实排版过的高度)。")

    # ---------- 第 ⑩ 层 (v77 横幅): 三位一体 ----------
    # ★V76 半升级: 注释 [V76-MARKER], 运行时仍是 _v75GuardLogged + build=V75。
    # ★V77 必须问运行时标识符: 只问注释键 = 假绿。
    if "[V77-MARKER]" not in src:
        raise RuntimeError(
            "⑩ 缺 [V77-MARKER] —— 装机确认横幅没注入, 日志无法核对版本。")
    if "_v77GuardLogged" not in code:
        raise RuntimeError(
            "⑩ 横幅 static 仍不是 `_v77GuardLogged`。\n"
            "  注释键升级了、NSLog 没升级 = 半升级。用户装机日志只看得见 NSLog。")
    if 'NSLog(@"[Minis-Guard] build=V77 ' not in src:
        raise RuntimeError(
            "⑩ NSLog 横幅不是 `build=V77`。\n"
            "  装机日志只看得见这一行。注释 V77 / 运行时 V76 = 半升级。")
    if "earlyNonPositiveReturn" not in src:
        raise RuntimeError(
            "⑩ V77 横幅缺 `earlyNonPositiveReturn` 能力串 ——\n"
            "  版本号改了、能力没写进日志, 装机仍无法确认本版修法在包里。")
    if ("_v76GuardLogged" in code or "_v75GuardLogged" in code
            or "_v74GuardLogged" in code or "_v72GuardLogged" in code):
        raise RuntimeError(
            "⑩ 运行时仍残留旧版 `_v7xGuardLogged` —— 半升级没切干净。")
    if re.search(r'NSLog\(@"\[Minis-Guard\] build=V7[0-6] ', src):
        raise RuntimeError(
            "⑩ NSLog 仍在打 `build=V7[0-6]` —— 半升级的运行时半边。")
    if "[V76-NONPOS-SHORTCIRCUIT]" not in src:
        raise RuntimeError(
            "⑩ 缺 [V76-NONPOS-SHORTCIRCUIT] —— 第二道防线(else-if 同级 return)\n"
            "  被摘掉。V77 入口短路是第一道, 这道仍要在。")
    seg76 = _block_after(
        src, "} else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {", code)
    m_ret = None
    for m in re.finditer(r"\breturn\s*;", seg76):
        if _rel_depth(seg76, m.start()) == 0:
            m_ret = m
            break
    if not m_ret:
        raise RuntimeError(
            "⑩ V76 非正短路的 `return;` 不在 else-if 同级 ——\n"
            "  要么被删, 要么埋进嵌套 if(死代码)。")

    # ---------- 第 ⑪ 层 (v77): 入口短路必须在 valueForKey 之前 ----------
    # ★V76 装机铁证(minis-2026-10-06 2.log PID 52989):
    #   build=V76 在跑, SHORT-CIRCUIT 0 次, FIXED-NONPOSITIVE 21084 条
    #   ⇒ 675425 次 0x0→326x307, 内存 48.5→2043.3MB / 9s ⇒ SIGKILL。
    # 根因: V76 的 return 写在 V65 KVC+NSLog 与 V74 重入哨兵**之后**。
    # 重入 setSize 先付完 V65 税, 再被 V74 return, V76 一次都看不见。
    # ⇒ 判据必须问「return 在 valueForKey 之前还是之后」, 只问「return 在不在」= 假绿。
    if "[V77-EARLY-NONPOS]" not in src:
        raise RuntimeError(
            "⑪ 缺 [V77-EARLY-NONPOS] —— 入口短路没注入。\n"
            "  V76 的 return 在 KVC 之后 = 重入仍先付 67 万次税再死。")
    if "EARLY-NONPOSITIVE-RETURN" not in src:
        raise RuntimeError(
            "⑪ 缺 EARLY-NONPOSITIVE-RETURN 日志串 —— 装机无法确认入口短路在跑。")
    i77 = src.index("[V77-EARLY-NONPOS]")
    kvc = src.find('valueForKey:@"size"')
    reent = src.find("_gSetSizeForwarding")
    if kvc < 0:
        raise RuntimeError("⑪ 找不到 valueForKey:@\"size\" —— 无法核对短路是否在 KVC 之前。")
    if i77 > kvc:
        raise RuntimeError(
            "⑪ [V77-EARLY-NONPOS] 在 valueForKey:@\"size\" **之后** ——\n"
            "  这正是 V76 装机的病: 短路写在 KVC 后面, 67 万次税先付完。\n"
            "  修法: height==0 必须在 KVC 之前 return。")
    if reent >= 0 and i77 > reent:
        raise RuntimeError(
            "⑪ [V77-EARLY-NONPOS] 在 `_gSetSizeForwarding` **之后** ——\n"
            "  重入哨兵先 return, 入口短路一次都看不见。")
    v65fix = src.find("[V65-FIXSIZE] 有限", i77)
    if v65fix < 0:
        v65fix = i77 + 1200
    early_code = code[i77:v65fix]
    if "newSize.height == 0.0" not in early_code:
        raise RuntimeError(
            "⑪ V77 入口条件不是 `newSize.height == 0.0`。\n"
            "  装机风暴是 0x0(675425 次); 0x-16 是正常首触, 必须仍走 V65 修正。")
    if not re.search(r"\breturn\s*;", early_code):
        raise RuntimeError(
            "⑪ V77 入口 if 里没有 `return;` —— 标记在、日志在、不 return = 空操作。")
    ret_at = i77 + early_code.find("return;")
    if ret_at > kvc:
        raise RuntimeError(
            "⑪ V77 入口 `return;` 落在 valueForKey 之后 —— 顺序让它不生效。")
    return True


def _block_after_hardstop(code):
    """取跨 tick 硬闸门 if 的整块 —— 按**语义**定位, 不锚定语句文本。

    ★为什么不能用 `_block_after(src, "if (s->nonPositiveStreak > "
      "kNonPositiveHardLimit) {", code)` 这种精确锚点 —— 第十四次「判据跟着代码跑」:

      v69 把闸门条件从
          if (s->nonPositiveStreak > kNonPositiveHardLimit) {
      扩展成
          if ((s->nonPositiveStreak > kNonPositiveHardLimit) ||
              (gGlobalNonPositiveStreak > kNonPositiveGlobalLimit)) {
      ⇒ 精确锚点立刻失配, 判据抛 `ValueError: substring not found`。

      ★这个错最坏的地方在于它**伪装成药坏了**: 看到 `❌` 会本能地去查
        v69 的注入逻辑, 而实际上药是对的、坏的是判据的锚点。
        历史同族: run#57(内联复制品没跟着改)、CI#161(shell 变量未求值)。
        三者的共同点: **判据锚定的是"代码长什么样", 而不是"这一步在判什么"**。

      ⇒ 锚点必须换成**不随写法变化的东西**: 这里用"含 kNonPositiveHardLimit
        的那个 if 条件" —— 无论是单个比较还是 OR 组合都能命中。
    """
    m = re.search(r"if\s*\([^{]*?kNonPositiveHardLimit", code)
    if not m:
        raise RuntimeError(
            "⑨ 找不到跨 tick 硬闸门(含 kNonPositiveHardLimit 的 if 条件)。\n"
            "  没有它 ⇒ 197 万次转发没有任何上限 ⇒ 内存 1.4GB ⇒ SIGKILL。")
    j = code.find("{", m.start())
    if j < 0:
        raise RuntimeError("⑨ 硬闸门 if 之后没有 `{`, 取不到块。")
    return _brace_block(code, j)


def _block_after(src, marker, code=None):
    """取 marker 之后第一个 `{` 起的整块(按花括号配平, 不按行数)。

    ★code 传去注释副本时, 在副本上找 `{` 与配平 —— 否则注释里出现的
      花括号会让配平跑偏(注释里写 `if (...) {` 就会多一层)。
      src 用来定位 marker(code 里 marker 可能已被剥掉)。
    """
    i = src.index(marker)
    target = code if code is not None else src
    j = target.find("{", i)
    if j < 0:
        return target[i:i + 2000]
    return _brace_block(target, j)


def _rel_depth(seg, upto):
    """seg[0:upto] 相对于 **seg 块自身** 的嵌套深度(块自身那层不算)。

    ★v68 注入后的正确形态 = 0(与 else-if 同级, 累加无条件执行);
      v66 的死代码形态 = 1(埋在 `if (commitCount > 40)` 里, 永不执行)。
    ★不用裸 `count("{") - count("}")`: 它对已闭合的兄弟块也恰好正确,
    纯属巧合; 遇到带 `}` 的字符串字面量或宏立刻跑偏。逐字符维护才是定义。
    """
    d = 0
    for ch in seg[:upto]:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
    return d - 1


def _strip_comments(src):
    """把注释替换成等长空格, 保留偏移 —— 正则只在真代码上匹配。

    ★为什么必须做: v65 的注释里就写着 `if (newSize.width <= 0 || ...)` 这句
      条件说明(写给未来的人看的)。不剥注释的话, 正则会先撞上**注释里的那句**,
      再往后找到 `{` 就取错了块 —— 判据自己误报(run#156 空测 / §15 误报那一族)。
    """
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':  # 字符串, 原样拷贝(不做完整转义解析, 守卫里没有复杂转义)
            out.append(c)
            i += 1
            while i < n:
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _block_after_if(src, code, marker, cond_re):
    """取 marker 之后**第一个匹配 cond_re 的 if 的整块**。

    ★src 与 code 必须成对传入: src 是原文(标记在注释里, 只有原文能定位),
      code 是同长度的去注释副本(正则只在这里跑, 否则会撞上注释里那句条件)。
      _strip_comments 等长替换, 所以两者偏移一一对应。

    ★为什么不能用 _block_after: 标记后面通常跟着大段注释, 而注释里或紧邻处
      的第一个 `{` 可能落在**内层** if 上, 导致取到的块只覆盖半个修正逻辑 ——
      判据自己就会误报。教训同 verify-discipline §15。

    ★cond_re 必须能唯一确定那个 **外层** if:
      对修正分支, 外层条件是 `width <= 0 || height <= 0`, 内层是
      `width <= 0` —— 只用 `width <= 0` 会先撞上内层。
    """
    i = src.index(marker)
    m = re.search(cond_re, code[i:])
    if not m:
        raise RuntimeError("找不到进入条件 %r (在 [%s] 之后)" % (cond_re, marker))
    j = code.find("{", i + m.end())
    if j < 0:
        raise RuntimeError("进入条件后没有 `{`, 取不到块。")
    return _brace_block(code, j)


def _brace_block(src, open_idx):
    """从 open_idx 处的 { 开始, 按配平取整块。"""
    depth = 0
    for k in range(open_idx, min(len(src), open_idx + 8000)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx:k + 1]
    return src[open_idx:open_idx + 8000]


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else \
        "src/ios/Shared/NSTextContainerSetSizeGuard.m"
    try:
        verify_guard_fixsize_v65(open(p, encoding="utf-8").read())
        print("✅ v65/v66/v68/v76/v77 守卫判据: 11 层全过"
              "(①弃丢弃已消失 ②负高取fabs ③块内无return ④哨兵门槛包住commitCount"
              " ⑤常量一致 ⑥标识符存在 ⑦禁CGRect category/防空操作/跨tick闸门"
              " ⑧累加在门槛外 ⑨降频放行+真实高度回填"
              " ⑩横幅三位一体+V76短路真return"
              " ⑪入口短路在 valueForKey 之前)")
    except Exception as e:
        print("❌ %s" % e)
        sys.exit(1)
