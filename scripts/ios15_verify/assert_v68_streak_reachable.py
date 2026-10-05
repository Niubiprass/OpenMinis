#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assert_v68_streak_reachable.py —— CI 断言71 的核心检查。

★ 为什么这条要单独成文件(而不是塞进 workflow 的内联 python):
  GitHub Actions 的内联 heredoc 会被 YAML 折行规则撕碎(实测报
  "expected <block end>"), 而且这类断言必须能在本地逐字复现。
  v67b 已经因为「基线解析散落 11 处」吃过一次亏: 判据要能独立执行。

【它断言的是一件 v66 从没被断言过的事】
  `nonPositiveStreak += 1` 这行**不在任何嵌套 if 之内**。

  v66 的形态(装机 197 万次 / 内存 +1.4GB / SIGKILL 的元凶):

      } else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {
          s->commitCount += 1;
          if (s->commitCount > kStormForwardLimit) {   // ← per-tick 门槛
              s->nonPositiveStreak += 1;              // ← 死代码, 永不执行
          }
      }

  commitCount 由 `if (_newTick) { s->commitCount = 0; }` 每 tick 清零,
  而 0x0 是「每 tick 只喂一两次」的形态 ⇒ 永远到不了 40 ⇒ streak 永不增长
  ⇒ 跨 tick 硬闸门永不触发。

  ★ 本项目**第八次**「验证手段骗了自己」:
    第 ⑦ 层判据问的是「nonPositiveStreak 会不会被**清零**」(恒真),
    病根是「它会不会被**累加**」(恒假) —— **问错了问题, 绿灯就是假的**。
    所以这里不问"清零", 直接数花括号深度。

用法: python3 assert_v68_streak_reachable.py <guard.m>
"""
import re
import sys


def _strip_comments(src):
    """去注释 —— 注释里出现的花括号会让配平跑偏(§15: 判据误报比没判据更贵)。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _rel_depth(seg, upto):
    """seg[0:upto] 相对于 **seg 块自身** 的嵌套深度(块自身那层不算)。

    ★v68 注入后的正确形态 = 0(与 else-if 同级);
      v66 的死代码形态 = 1(埋在 `if (commitCount > 40)` 里)。
    逐字符维护深度, 不用裸 count 差值 —— 后者对已闭合的兄弟块也恰好正确,
    纯属巧合; 遇到带 `}` 的字符串字面量或宏立刻跑偏。
    """
    d = 0
    for ch in seg[:upto]:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
    return d - 1


def brace_block(src, i):
    """从 src[i]=='{' 起用花括号配平取整块。"""
    depth, j = 1, i + 1
    while j < len(src) and depth > 0:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    return src[i:j]


def main():
    if len(sys.argv) < 2:
        print("用法: assert_v68_streak_reachable.py <guard.m>")
        return 2
    path = sys.argv[1]
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("::error::读不到 %s (%s)" % (path, e))
        return 2
    if not raw.strip():
        print("::error::守卫源码为空 —— 判据自己都没跑起来, 不计通过")
        return 2

    code = _strip_comments(raw)

    # ---- ① 定位非正尺寸的 else-if 分支 ----
    m = re.search(r"\}\s*else\s*if\s*\(\s*_v65orig_h\s*<=\s*0", code)
    if not m:
        print("::error::找不到非正尺寸 else-if 分支 —— v68 注入没生效")
        print("   (上游/兼容层结构可能变了, 或 [V68-STREAK] 未注入)")
        return 1
    seg = brace_block(code, code.index("{", m.start()))

    # ---- ② 累加语句必须存在 ----
    a = re.search(r"s->nonPositiveStreak\s*\+=\s*1", seg)
    if not a:
        print("::error::非正分支里没有 `nonPositiveStreak += 1` —— 跨 tick 硬闸门永不触发")
        print("   装机实测: 197 万次修正 / 11 秒 / 单容器 / 内存 35.5→1474.6MB ⇒ SIGKILL")
        print("   而 NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP 日志**各 0 次**")
        return 1

    # ---- ③ ★核心: 累加语句的花括号深度必须为 0 ----
    depth = _rel_depth(seg, a.start())
    if depth > 0:
        print("::error::`nonPositiveStreak += 1` 位于嵌套 if 内(花括号深度 +%d)" % depth)
        print("   它被 per-tick 门槛 `commitCount > kStormForwardLimit` 挡住了,")
        print("   而 commitCount 由 `if (_newTick) { s->commitCount = 0; }` **每 tick 清零**。")
        print("   0x0 是「每 tick 只喂一两次」的形态 ⇒ 永远到不了 40 ⇒ **这行是死代码**。")
        print("   ★ v66 的第 ⑦ 层判据问的是「streak 会不会被清零」(恒真),")
        print("     病根是「会不会被累加」(恒假) —— **问错问题, 绿灯就是假的**。")
        return 1

    print("✅ streak 累加在 per-tick 门槛之外(花括号深度 0) —— 跨 tick 硬闸门可达")

    # ---- ④ 降频放行游标必须在硬闸门块内(不许退回永久冻结) ----
    # ★锚点按**语义**定位(含 kNonPositiveHardLimit 的那个 if), 不锚定语句文本。
    #   v69 把条件扩展成 `if ((s->nonPositiveStreak > kNonPositiveHardLimit) ||
    #   (gGlobalNonPositiveStreak > kNonPositiveGlobalLimit)) {`, 精确锚点会失配
    #   ⇒ 报 `substring not found`, 而**药其实是对的**(第十四次判据跟着代码跑)。
    g = re.search(r"if\s*\([^{]*?kNonPositiveHardLimit", code)
    if not g:
        print("::error::找不到跨 tick 硬闸门(含 kNonPositiveHardLimit 的 if)")
        print("   ⇒ 197 万次转发没有任何上限 ⇒ 内存 1.4GB ⇒ SIGKILL")
        return 1
    gate = brace_block(code, code.index("{", g.start()))
    if not ("nonPositiveSkipTick" in gate or "gGlobalSkipTick" in gate):
        print("::error::硬闸门是**永久冻结**(命中即 return) —— 把内存问题换成了空白问题:")
        print("   · 上游持续算崩时该容器再也收不到 setSize ⇒ 高度永久冻结")
        print("   · 屏幕保留一整块旧几何 ⇒ **巨大空白**(v61 刚修掉的症状换个形态回来)")
        print("   · 还把「上游万一自愈」的可能性一并删掉了")
        print("   ⇒ 必须降频放行(每 kNonPositiveSkipStride 次放 1 次)")
        return 1

    # ---- ⑤ 降频步长常量必须存在(不能是裸数字) ----
    if "kNonPositiveSkipStride" not in raw:
        print("::error::缺 `kNonPositiveSkipStride` 常量 —— 降频步长不可考据")
        return 1

    # ---- ⑥ lastGoodHeight 必须既被读取也被记录 ----
    #    §19 变体: 「字段存在」不等于「有人写它」。两处都要查。
    if "lastGoodHeight" not in raw:
        print("::error::GuardState 缺 `lastGoodHeight` —— 非正高度仍靠猜(1.0 是活锁燃料)")
        return 1
    if not re.search(r"s->lastGoodHeight\s*=\s*newSize\.height", code):
        print("::error::`lastGoodHeight` 从未被赋值 —— 字段存在但永远为 0")
        print("   ⇒ 非正高度每次都退回 1.0 ⇒ 活锁照旧, 而「字段存在」类断言全绿")
        print("   ★ §19 的变体: 「标识符存在 != 可见」在这里变成「字段存在 != 被赋值」")
        return 1

    print("✅ 降频放行游标在闸门内 / 步长常量存在 / lastGoodHeight 既读又写 —— v68 三处修法齐全")
    return 0


if __name__ == "__main__":
    sys.exit(main())
