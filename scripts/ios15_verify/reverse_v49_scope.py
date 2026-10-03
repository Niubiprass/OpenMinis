#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope_check_v49 的反向测试 —— 一个从不失败的检查等于没检查。

【为什么必须有】本轮 v49 连踩两个**编译级**错误, 而结构判据
verify_width_writer_v49 全程放行:
  1. `struct _V49W` 声明在函数体内 → KVO 侧跨函数引用不到 → 编译失败
  2. KVO 侧读 `self.attV46CachedWidth` → 那是 TableAttachment 的成员
     → 跨类访问 → 编译失败

判据只查"struct 存在""字段齐全", 查不出"声明在哪一层""这个属性能不能
在这儿读"。所以拿**真实踩过的这两个坑** + 同族坑做 sabotage。

用法: reverse_v49_scope.py <SelectableMarkdownView.swift>
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "scope_check_v49.py")


def run(t):
    fd, p = tempfile.mkstemp(suffix=".swift")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(t)
        r = subprocess.run([sys.executable, CHECK, p],
                           capture_output=True, text=True, timeout=180)
        return r.returncode, (r.stdout + r.stderr).strip()
    finally:
        os.unlink(p)


def main():
    if len(sys.argv) < 2:
        print("用法: reverse_v49_scope.py <SelectableMarkdownView.swift>")
        return 2
    t = open(sys.argv[1], encoding="utf-8").read()

    rc, out = run(t)
    if rc != 0:
        print("❌ 基线就不通过, 后续 sabotage 无意义:\n   %s" % out)
        return 1
    print("✅ 基线通过")
    print("══ v49 作用域 sabotage ══")

    cases = []

    # ---- S1 ★本轮实踩 #1: struct 退回函数体内 ----
    def s1(x):
        m = re.search(r"\n[ \t]*/// \[V49-WSTATE\].*?\n[ \t]*\}\n", x, re.S)
        if not m:
            raise AssertionError("S1 定位不到 [V49-WSTATE] 块")
        block = m.group(0)
        inner = "\n".join(("    " + ln) if ln.strip() else ln
                          for ln in block.strip("\n").split("\n"))
        x = x[:m.start()] + "\n" + x[m.end():]
        i = x.find("            // [V49-WWRITER-V18]")
        if i < 0:
            raise AssertionError("S1 定位不到 v18 探针锚点")
        return x[:i] + inner.lstrip("\n") + "\n" + x[i:]

    cases.append((
        "S1 struct _V49W 退回函数体内(局部类型跨函数不可见)",
        s1, "跨函数|缩进"))

    # ---- S2 ★本轮实踩 #2: 跨类读 TableAttachment 的成员 ----
    def s2(x):
        old = "self.ios15V46LaidOutW = self.ios15LastLaidOutW ?? -1"
        new = "self.ios15V46LaidOutW = self.attV46CachedWidth"
        assert old in x, "S2 锚点失效"
        return x.replace(old, new, 1)

    cases.append((
        "S2 KVO 侧读 TableAttachment.attV46CachedWidth(跨类访问)",
        s2, "不可见|跨类"))

    # ---- S3 struct 声明重复两份 ----
    def s3(x):
        m = re.search(r"\n[ \t]*struct _V49W \{.*?\n[ \t]*\}\n", x, re.S)
        if not m:
            raise AssertionError("S3 定位不到 struct _V49W")
        return x[:m.end()] + "\n" + m.group(0).lstrip("\n") + x[m.end():]

    cases.append(("S3 struct _V49W 声明重复两份(后者遮蔽前者)",
                  s3, "遮蔽|恰为 1"))

    # ---- S4 引用宿主类里不存在的成员 ----
    def s4(x):
        old = "self.ios15V41CvW = cvW"
        new = "self.ios15V41CvW = self.ios15NeverDeclaredMember"
        assert old in x, "S4 锚点失效"
        return x.replace(old, new, 1)

    cases.append(("S4 KVO 侧引用不存在的成员 ios15NeverDeclaredMember",
                  s4, "不可见"))

    # ---- S5 类型限定名访问别的类 ----
    def s5(x):
        old = "_V49W.v18W = textContainer.size.width"
        new = "_V49W.v18W = MinisLayoutManager.sharedLineHeight"
        assert old in x, "S5 锚点失效"
        return x.replace(old, new, 1)

    cases.append(("S5 v18 侧用类型限定名访问 MinisLayoutManager",
                  s5, "跨类|另一个类型"))

    # ---- S6 把 struct 改成 enum(类型声明形态漂移) ----
    def s6(x):
        m = re.search(r"\n[ \t]*struct _V49W \{", x)
        if not m:
            raise AssertionError("S6 定位不到 struct _V49W")
        i = m.start() + 1
        return x[:i] + "    enum _V49W {" + x[m.end():]

    cases.append(("S6 struct _V49W 改成 enum(声明形态漂移)",
                  s6, "恰为 1"))

    fail = 0
    for name, fn, kw in cases:
        try:
            bad = fn(t)
        except AssertionError as e:
            print("❌ %-52s sabotage 自身失败: %s" % (name[:52], e))
            fail += 1
            continue
        if bad == t:
            print("❌ %-52s sabotage 未改动任何内容(锚点失效)" % name[:52])
            fail += 1
            continue
        rc, out = run(bad)
        first = out.split("\n")[0]
        if rc == 0:
            print("❌ %-52s ★未被拦截*" % name[:52])
            fail += 1
        else:
            star = "★" if (kw and kw in out) else " "
            print("✅%s %-52s %s" % (star, name[:52], first[:74]))

    print()
    if fail:
        print("❌ %d/%d 条 sabotage 未被拦截" % (fail, len(cases)))
        return 1
    print("✅ %d/%d 条 sabotage 全被拦截, 基线不误伤" % (len(cases), len(cases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
