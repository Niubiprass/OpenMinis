#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Swift 字符串插值里的「类型名打印」专项检查。

★为什么需要这个脚本:
  run#138 在第 16 步「编译 App」失败(exit 65), 报错:
      SelectableMarkdownView.swift:6703:52: error: expected member name following '.'
  起因是这一行(我为了打印 superview 链的类型名写的):
      chain += "\\(depth):\\(type(of: cur).(String(describing:))) "

  `type(of: cur)` 的返回类型是**元类型**(Any.Type / UIScrollView.Type)。
  Swift 词法器在元类型后面接 `.` 时, 会把它当成**元类型的成员访问**,
  于是 `.(` 不是合法的「构造器调用」而是「成员」⇒ expected member name。

  正确形式是 `String(describing: type(of: cur))` —— 把整个元类型包进
  `String(describing:)`, 让它成为普通实参而不是「取元类型的成员」。

  ⇒ 教训与 v56.1 的 `UInt64` 那次同源, 但性质更糟:
     UInt64 是**语法形式**照抄了已验证代码就能避免;
     本次这个是**凭空想出来的**表达式, 没有任何已编译代码可照抄。
  ⇒ 因此需要**机器检查**, 而不是靠下次小心。

  本脚本查的正是这一类: 字符串插值里 `\\(type(of: X).( ... ))` 这种形态。
  同理还有 `\\(Int.self.( ... ))` / `\\(Foo.self.( ... ))` 等。

用法: python3 check_swift_interp_syntax.py <SelectableMarkdownView.swift>
      python3 check_swift_interp_syntax.py <根目录>     # 自动定位产物
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
if os.path.isdir(ROOT):
    MD = os.path.join(ROOT, "src", "ios", "Views", "Chat", "SelectableMarkdownView.swift")
else:
    MD = ROOT

if not os.path.exists(MD):
    sys.stderr.write("产物不存在: %s\n" % MD)
    sys.exit(1)

src = open(MD, encoding="utf-8").read()
raw = src


def strip_comments_only(text):
    """只剥掉 Swift 注释, **保留字符串字面量**, 并保持行号不变。

    ★上一版把字符串也剥了, 结果规则 1 彻底失效 ——
      因为 run#138 要抓的错 `\\(type(of: cur).(String(describing:)))`
      **本身就活在字符串插值里面**。剥掉字符串等于把案发现场清空,
      检查脚本变成永远绿的废品。

    ★为什么必须剥注释: v56 的 KVO 段注释里正写着 `(unsigned long long)x`
      这个反例(说明为什么不能这么写)。不剥注释的话, 本脚本会把自己
      写下的**反例**当成**正例**报出来, 每次跑都失败, 久了就没人看了。

    ★为什么必须保留字符串: 本脚本查的绝大多数形态(插值里对元类型
      接构造器、NSLog 格式串里夹 C 风格转换)全都只出现在字符串里。
      剥注释不剥字符串, 才是这套检查真正要覆盖的战场。

    关键实现: 用 in_string 状态位, 让 `//` 与 `/*` 只在**代码区**生效;
    字符串区内 `//`(`https://` 之类)不算注释。注释一律替换成等量换行,
    保证 `count("\\n")` 算出来的行号与原文件一致。
    """
    out, i, n = [], 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            if j < 0:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        if text.startswith("/*", i):
            depth, start = 1, i
            i += 2
            while i < n and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                elif text[i] == "\n":
                    out.append("\n")
                    i += 1
                else:
                    i += 1
            if depth:
                sys.stderr.write("块注释未闭合, 从行%d 开始 —— 产物可能不完整\n"
                                 % (text.count("\n", 0, start) + 1))
                return None
            continue
        out.append(c)
        i += 1
    return "".join(out)


stripped = strip_comments_only(raw)
if stripped is None:
    sys.exit(1)
src = stripped
bad = []

# ---- 1. 插值里 `type(of: X).(` / `X.self.(` 这类「元类型后接构造器」----
# 形如:  \(type(of: cur).(String(describing:)))
#      \(Int.self.(foo))
#      \(type(of: v).(bar))
PAT_TYPE_OF = re.compile(r"\\\(\s*type\s*\(\s*of\s*:[^)]*\)\s*\.\s*\(")
PAT_SELF = re.compile(r"\\\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*\.\s*self\s*\.\s*\(")

for name, pat in (("type(of:).(  元类型后接构造器", PAT_TYPE_OF),
                  ("X.self.(             元类型后接构造器", PAT_SELF)):
    hits = [(m.start(), m.group(0)) for m in pat.finditer(src)]
    if hits:
        for off, txt in hits[:5]:
            line = src.count("\n", 0, off) + 1
            bad.append("行%d: %s —— 命中 `%s`\n"
                       "        修法: 改成 `String(describing: type(of: x))`, "
                       "即把元类型整个包进 String(describing:), 别在它后面接 `.`"
                       % (line, name, txt))

# ---- 2. C 风格转换 (run#135 的教训, 顺带一起守) ----
# Swift 侧从无 C 风格转换; 只有 .m 文件(ObjC)里有。出现即为错。
CSTYLE = re.compile(r"\(\s*(?:unsigned\s+long\s+long|unsigned\s+int|long\s+long|"
                    r"unsigned\s+short|uint64_t|NSUInteger|CGFloat)\s*\)\s*[A-Za-z_]")
for m in CSTYLE.finditer(src):
    off = m.start()
    line = src.count("\n", 0, off) + 1
    bad.append("行%d: C 风格转换 `%s` —— Swift 侧禁用(run#135 编译失败)\n"
               "        修法: 用 UInt64(...) / Int(...) 等 Swift 形式"
               % (line, m.group(0).strip()))

# ---- 3. 字符串插值里 NSLog/print 用 %@ 但传了非对象 ----
# (只报明确可疑的: 插值里出现 C 风格三元或位运算) —— 这条留给未来扩展,
# 目前不引入误报源, 故不启用。

if bad:
    print("❌ check_swift_interp_syntax: %d 处问题" % len(bad))
    for b in bad:
        print("  - " + b)
    sys.exit(1)

print("✅ check_swift_interp_syntax: 通过")
print("   (1) 插值内无 `type(of:).( / X.self.(` 元类型后接构造器")
print("   (2) 全文件无 C 风格转换(run#135 那类)")
