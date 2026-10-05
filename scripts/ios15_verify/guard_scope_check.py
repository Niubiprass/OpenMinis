#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""guard_scope_check.py —— NSTextContainerSetSizeGuard.m 的**作用域结构**自检。

【为什么需要它(而不是等 Xcode 编译报红)】
  v66 在这一段踩了两次编译红, 都不是语法错, 而是**作用域**错:
    ① `_v65orig_w/_h` 声明写在 if 块内 ⇒ 下面兄弟块 "use of undeclared identifier"
    ② 注释里说"引用 kProbeHeightCeiling" ⇒ 它是函数内局部 const, 作用域外 ⇒ 编译红
  本项目 §19「标识符存在 != 标识符**可见**」同族已经发生 **5 次**。
  v68 又动同一段(把 holder/s 提升到函数体开头), 所以必须有本地预检。

【它验什么(全部是"真会编译红"的结构问题)】
  1. 花括号全文件配平
  2. 非正高度修正段里用到的 `s->xxx` 必须在该段**之前**有 `GuardState *s` 声明
     —— v68⓪ 的存在意义就在这里; 一旦 hoist 失效, 这条立刻报红
  3. streak 累加语句的花括号深度为 0(不在嵌套 if 内) —— 复用 CI 断言71 的判据,
     本地先跑一遍, 免得把"CI 才发现"当成常态
  4. GuardState 里 v68 新增的三个字段都存在
  5. kNonPositiveSkipStride 常量已定义且被降频逻辑引用
  6. **holder/s 只声明一次** —— hoist 后原处若忘删, 会是重复声明 ⇒ 编译红
     (v66 提交说明记过 4 处 "use of undeclared identifier", 这里反向防重复声明)

★ 纪律(§15): 判据自己的误报比没有判据更贵。
  所以每一处都只在**确认命中该形态**时才报错, 不做"风格建议"。

用法: python3 guard_scope_check.py <guard.m>
"""
import re
import sys


def _strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _rel_depth(seg, upto):
    """seg[0:upto] 相对于 **seg 块自身** 的嵌套深度。

    ★为什么要减去块自身那一层(§15: 判据自己的误报比没有判据更贵):
      seg 是从 else-if 的 `{` 开始取的, 所以 seg[0] 那个 `{` 就是块自身,
      深度基准应为 1。而我们要问的是"累加语句**是否还在某个嵌套 if 内**",
      判据是 depth - 1: 块自身的 1 层不算嵌套。
      v68 注入后的正确形态算出来是 0(与 else-if 同级);
      v66 的死代码形态算出来是 1(埋在 `if (commitCount > 40)` 里)。
    ★不用裸 `count("{") - count("}")`: 它对已闭合的兄弟块也正确,
      纯属巧合; 一旦上游出现带 `}` 的字符串字面量或宏, 立刻跑偏。
      逐字符维护深度才是定义。
    """
    d = 0
    for ch in seg[:upto]:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
    return d - 1


def brace_block(src, i):
    depth, j = 1, i + 1
    while j < len(src) and depth > 0:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    return src[i:j], j


def main():
    if len(sys.argv) < 2:
        print("用法: guard_scope_check.py <guard.m>")
        return 2
    path = sys.argv[1]
    raw = open(path, encoding="utf-8", errors="replace").read()
    fails = []

    # ---- 1. 花括号配平 ----
    code = _strip_comments(raw)
    bal = code.count("{") - code.count("}")
    if bal != 0:
        fails.append("① 花括号不配平(差 %d) —— 注入把块结构改坏了" % bal)

    # ---- 2. 非正修正段用 s-> 之前必须已声明 GuardState *s ----
    m = re.search(r"if\s*\(\s*newSize\.width\s*<=\s*0\s*\|\|\s*newSize\.height\s*<=\s*0\s*\)",
                  code)
    if not m:
        fails.append("② 找不到非正尺寸修正段(if (newSize.width <= 0 || newSize.height <= 0))"
                     " —— v68 注入可能没生效")
    else:
        seg_start = m.start()
        # 该段用到 s-> 的所有字段
        seg, _ = brace_block(code, code.index("{", seg_start))
        used = set(re.findall(r"s->(\w+)", seg))
        decl = code.rfind("GuardState *s = &holder->state;")
        if not used:
            fails.append("③ 非正修正段里没有任何 s-> 引用 —— v68⓪/③ 没生效?"
                         "(预期它读 s->lastGoodHeight)")
        elif decl < 0:
            fails.append("④ 全文件找不到 `GuardState *s = &holder->state;` —— 守卫状态未取")
        elif decl > seg_start:
            fails.append("⑤ ★`GuardState *s` 声明(%d) 在非正修正段(%d)**之后** —— "
                         "修正段里读 s->lastGoodHeight 会 \"use of undeclared identifier\""
                         "\n     §19 同族第五次。v68⓪ 的 hoist 必须生效"
                         % (decl, seg_start))
        else:
            print("✅ 非正修正段(idx=%d) 引用的 %s 都在 s 声明(idx=%d) 之前可见"
                  % (seg_start, sorted(used), decl))

    # ---- 3. streak 累加必须在门槛之外(深度 0) ----
    m2 = re.search(r"\}\s*else\s*if\s*\(\s*_v65orig_h\s*<=\s*0", code)
    if not m2:
        fails.append("⑥ 找不到非正尺寸 else-if 计费分支 —— v68① 没生效")
    else:
        seg, _ = brace_block(code, code.index("{", m2.start()))
        a = re.search(r"s->nonPositiveStreak\s*\+=\s*1", seg)
        if not a:
            fails.append("⑦ 非正分支里没有 nonPositiveStreak += 1 —— 跨 tick 闸门永不触发"
                         "\n     装机实测: 197 万次/11秒/单容器/内存+1.4GB ⇒ SIGKILL")
        else:
            d = _rel_depth(seg, a.start())
            if d > 0:
                fails.append("⑧ ★streak 累加在嵌套 if 内(相对深度 +%d) —— v66 死代码原样"
                             "\n     ★第八次假绿: ⑦层问「会不会被清零」(恒真), "
                             "病根是「会不会被累加」(恒假)" % d)
            else:
                print("✅ streak 累加在门槛之外(深度 0)")

    # ---- 4. GuardState 新字段 ----
    for f in ("lastGoodHeight", "nonPositiveSkipTick", "nonPositiveStreak"):
        if not re.search(r"\b%s\b\s*;" % re.escape(f), raw):
            fails.append("⑨ GuardState 缺字段 `%s`" % f)
    print("✅ GuardState 字段: lastGoodHeight / nonPositiveSkipTick / nonPositiveStreak")

    # ---- 5. 降频步长常量 ----
    if "static const NSInteger kNonPositiveSkipStride" not in raw:
        fails.append("⑩ 缺 `static const NSInteger kNonPositiveSkipStride` 定义")
    if "kNonPositiveSkipStride" not in code:
        fails.append("⑪ 降频逻辑未引用 kNonPositiveSkipStride(步长写成了裸数字?)")
    else:
        print("✅ kNonPositiveSkipStride 已定义并被降频逻辑引用")

    # ---- 6. holder/s 只声明一次(防 hoist 后重复声明) ----
    n_decl = len(re.findall(r"GuardState \*s = &holder->state;", code))
    n_holder = len(re.findall(r"_NSTextContainerGuardState \*holder = objc_getAssociatedObject", code))
    if n_decl > 1:
        fails.append("⑫ ★`GuardState *s` 声明了 **%d 次** —— hoist 后原处忘删 ⇒ 重复定义编译红"
                     % n_decl)
    if n_holder > 1:
        fails.append("⑬ ★`holder = objc_getAssociatedObject` 出现 **%d 次** —— 同上"
                     % n_holder)
    if n_decl <= 1 and n_holder <= 1:
        print("✅ holder/s 各只声明一次(声明 %d / 赋值 %d)" % (n_decl, n_holder))

    # ---- 7. 赋值而非仅声明: lastGoodHeight 必须有人写 ----
    if not re.search(r"s->lastGoodHeight\s*=\s*newSize\.height", code):
        fails.append("⑭ ★`lastGoodHeight` 从未被赋值 —— 字段存在但永远为 0 ⇒ "
                     "非正高度仍退回 1.0 ⇒ 活锁照旧\n     §19 变体: "
                     "「标识符存在」变成「字段存在 != 被赋值」")
    else:
        print("✅ lastGoodHeight 有赋值语句")

    print()
    if fails:
        for f in fails:
            print("❌ " + f)
        print("\n=== %d 处结构问题 ===" % len(fails))
        return 1
    print("=== guard 作用域结构自检: 全部通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
