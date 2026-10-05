#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_guard_fixsize_v65 —— v65/v66 守卫判据（七层）。

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
    return True


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
        print("✅ v65/v66 守卫判据: 7 层全过")
    except Exception as e:
        print("❌ %s" % e)
        sys.exit(1)
