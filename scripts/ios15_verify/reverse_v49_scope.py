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

    # ================= E 类: TextKit 成员的**存在性**(run#37139821021) =================
    # 【为什么单列一类】S1~S6 全是"作用域/声明"问题, 而这一类是
    # **API 存在性**: 名字合法(UIView 确实有 bounds)、作用域合法(探针在
    # 宿主类内), 但挂在 textContainer 上不存在 ⇒ 编译照样失败:
    #     error: value of type 'NSTextContainer' has no member 'bounds'
    # 【为什么 E 层检查自己踩了两次坑, 记下来】
    #   ① 正则只写 `([a-z_]\w*)\.([a-z_]\w*)` ⇒ 只能看到两段链的第一跳,
    #      `self.textContainer.attachedRange` 里的 attachedRange 根本没被看到
    #      ⇒ 4 条 sabotage **全漏放**, 检查形同虚设。
    #   ② 链遍历写成"校验通过就 break" ⇒ `textContainer.layoutManager.xxx`
    #      里中间那一跳没查(它也是 TextKit 对象) ⇒ 三段链仍漏放。
    #   教训: **白名单检查必须沿链逐跳推进**, 且写完立刻反向证伪。

    # ★锚点改成 `textContainer.size.height` —— 它在 KVO 探针段里**只出现
    #   一次**, 且是编译器已验证存在的成员(整份文件 40+ 处在用)。
    #   原锚点 lineFragmentWidth 已被删除(见 S12 的说明)。
    def s7(x):
        return x.replace("self.textContainer.size.height",
                         "self.textContainer.bounds.height", 1)

    cases.append(("S7 回退成 textContainer.bounds(run#119/#120 真 bug)",
                  s7, "没有这个成员"))

    def s8(x):
        return x.replace("self.textContainer.size.height",
                         "self.textContainer.attachedRange", 1)

    cases.append(("S8 textContainer 读不存在的成员", s8, "没有这个成员"))

    def s9(x):
        i = x.find("// [V49-WWRITER-KVO]")
        j = x.find("// [V49-WWRITER-KVO-END]")
        if i < 0 or j < i:
            raise AssertionError("S9 定位不到 KVO 探针段")
        seg = x[i:j]
        _a = "self.layoutManager.usedRect(for: self.textContainer)"
        if _a not in seg:
            raise AssertionError("S9 探针段内没有 %s" % _a)
        return x[:i] + seg.replace(
            _a, "self.layoutManager.estimatedGlyphCount", 1) + x[j:]

    cases.append(("S9 layoutManager 读不存在的成员", s9, "没有这个成员"))

    def s10(x):
        # ★必须锚**探针段内**的那一次: `self.textStorage.length` 在整份文件里
        #   出现 5 次(v41/v44/v45/v46 的日志都打它), replace(..., 1) 改的是
        #   文件靠前那一处 —— 落在探针段外, sabotage 等于什么都没做,
        #   而反向测试只会报"★未被拦截"。教训与 v47 的 C3 同源:
        #   **sabotage 的替换点必须落在判据真正检查的区间内**。
        i = x.find("// [V49-WWRITER-KVO]")
        j = x.find("// [V49-WWRITER-KVO-END]")
        if i < 0 or j < i:
            raise AssertionError("S10 定位不到 KVO 探针段")
        seg = x[i:j]
        if "self.textStorage.length" not in seg:
            raise AssertionError("S10 探针段内没有 self.textStorage.length")
        seg2 = seg.replace("self.textStorage.length",
                           "self.textStorage.glyphCount2", 1)
        return x[:i] + seg2 + x[j:]

    cases.append(("S10 textStorage 读不存在的成员", s10, "没有这个成员"))

    def s11(x):
        i = x.find("// [V49-WWRITER-KVO]")
        j = x.find("// [V49-WWRITER-KVO-END]")
        if i < 0 or j < i:
            raise AssertionError("S11 定位不到 KVO 探针段")
        seg = x[i:j]
        _a = "self.layoutManager.usedRect(for: self.textContainer)"
        if _a not in seg:
            raise AssertionError("S11 探针段内没有 %s" % _a)
        return x[:i] + seg.replace(
            _a, "self.textContainer.layoutManager.estimatedGlyphCount", 1) + x[j:]

    cases.append(("S11 三段链中间跳(TextKit 对象)也要查", s11, "没有这个成员"))

    # ★★ S12: 本轮第二次编译失败的那个 API。写它进 E 层白名单时看着很
    #   "合理"(它确实是排版行宽), 但 Apple 文档确认 NSTextContainer
    #   **没有** lineFragmentWidth —— 它属于 TextKit2 的 NSTextLayoutManager。
    #   这条 sabotage 的意义是: 任何人再把"看起来对"的 API 塞进白名单,
    #   E 层会立刻指出它不在官方成员表里。
    def s12(x):
        return x.replace("self.textContainer.size.height",
                         "self.textContainer.lineFragmentWidth", 1)

    cases.append(("S12 再塞 lineFragmentWidth(run#120 真 bug)",
                  s12, "没有这个成员"))

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
