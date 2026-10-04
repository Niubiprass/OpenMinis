#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产物级幂等门: 同一份产物连跑三遍 fallback, 结果必须逐字节相同。

★为什么需要这个脚本(★这是 v56.4 最值钱的收获):
  幂等这件事, 历代判据都是**逐个函数静态看**的(ci_assert_v48 查 v48 段内
  阈值, reverse_v48 查幂等门被删), 从来没有**在产物层面真跑一遍**。
  于是 20261004 撞上一个一直存在的洞:

    fix_markdown_layout_reconcile() 的锚点是
        OLD = "attrs.size.height = fittingSize.height"
    而它注入出去的 NEW 段**末尾仍然含这一行**(这行就是最终赋值,
    去掉它整段就没意义了)。于是:
        第 1 次跑: OLD in t 为真 -> 注入
        第 2 次跑: OLD 仍在 t 里 -> 又注入一份
    结果产物里 `var _ios15TkSum` 声明了两次 ⇒ Swift 立刻
        error: invalid redeclaration of '_ios15TkSum'
    ⇒ 编译失败。而 CI 每次都是**干净上游重建 + 只跑一遍**,
      所以这个洞从来没在 CI 上炸过 —— 是本地为了验幂等而复跑才暴露。

  ⇒ 纪律: **判据必须能只靠「跑」就成立, 不能只靠「读代码」成立。**
    逐个函数静态论证幂等, 永远漏「锚点被自己包含」这一类 ——
    因为它在每个函数里单看都"有判据"(v48 那种), 只是判错了对象。

用法: python3 check_idempotent_reapply.py <fallback脚本> <干净上游src/ios> [轮数]
      不传上游路径时跳过(需要一份未被移植过的 ios 源做基线)。
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FB = os.path.join(os.path.dirname(HERE), "ios15_fallback.py")


def tree_equal(a, b):
    """递归比对两棵目录树, 返回首个差异的相对路径(无差异返回 None)。"""
    def relfiles(root):
        out = set()
        for dp, _, fns in os.walk(root):
            for fn in fns:
                out.add(os.path.relpath(os.path.join(dp, fn), root))
        return out

    ra, rb = relfiles(a), relfiles(b)
    only_a, only_b = ra - rb, rb - ra
    if only_a or only_b:
        return "文件集合不同: 仅A=%s 仅B=%s" % (sorted(only_a)[:3], sorted(only_b)[:3])
    for rel in sorted(ra):
        pa, pb = os.path.join(a, rel), os.path.join(b, rel)
        if not filecmp.cmp(pa, pb, shallow=False):
            return rel
    return None


def main():
    if len(sys.argv) < 3:
        sys.stderr.write(__doc__)
        return 1
    fb = sys.argv[1] if os.path.exists(sys.argv[1]) else DEFAULT_FB
    upstream = sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if not os.path.exists(fb):
        sys.stderr.write("找不到 fallback 脚本: %s\n" % fb)
        return 1
    if not os.path.isdir(upstream):
        sys.stderr.write("找不到干净上游 src/ios: %s\n" % upstream)
        return 1

    work = tempfile.mkdtemp(prefix="idem_")
    target = os.path.join(work, "ios")
    shutil.copytree(upstream, target)
    snaps = []
    bad = []
    try:
        for i in range(1, rounds + 1):
            p = subprocess.run([sys.executable, fb, target],
                               capture_output=True, text=True)
            if p.returncode != 0:
                print("❌ check_idempotent_reapply: 第 %d 轮 fallback 退出码 %d"
                      % (i, p.returncode))
                print("   " + (p.stderr or p.stdout)[-800:])
                return 1
            snap = os.path.join(work, "snap%d" % i)
            shutil.copytree(target, snap)
            snaps.append(snap)

        for i in range(1, len(snaps)):
            d = tree_equal(snaps[i - 1], snaps[i])
            if d:
                bad.append("第%d轮 → 第%d轮 产物不同: %s" % (i, i + 1, d))

        # 双保险: 即使逐轮比对漏了, 直接查「重复声明」这个具体症状 ——
        # Swift 里同一作用域内 `var x` 同名两次就是 invalid redeclaration。
        # ★只查**我们注入的变量名**(前缀 _ios15 / _vNN), 不查全文件:
        #   全文件粗查会误报爆表 —— 上游到处是不同函数/闭包各自声明
        #   `var body` / `let f` / `let font`, 缩进相同但作用域不同,
        #   Swift 完全合法。误报会让判据变成噪声, 久了就没人看。
        for rel in _swift_files(snaps[-1]):
            dup = _dup_var_decl(os.path.join(snaps[-1], rel))
            if dup:
                bad.append("%s: 注入变量 `%s` 重复声明 ⇒ Swift invalid redeclaration"
                           % (rel, dup))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if bad:
        print("❌ check_idempotent_reapply: %d 处问题" % len(bad))
        for b in bad:
            print("  - " + b)
        print()
        print("   修法: 判据要认**插入物自身**的标记, 不能认锚点 ——")
        print("        注入段末尾若仍含自己的锚点, 「锚点仍在」恒为真,")
        print("        等于没有判据, 第二次跑就会重复注入。")
        return 1

    print("✅ check_idempotent_reapply: 通过")
    print("   连续 %d 轮 fallback 产物逐字节相同, 且无重复 var 声明" % rounds)
    return 0


def _swift_files(root):
    out = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".swift"):
                out.append(os.path.relpath(os.path.join(dp, fn), root))
    return sorted(out)


# 我们注入的局部变量一律带这些前缀(与 ios15_fallback.py 的命名一致)
INJECT_PREFIX = ("_ios15", "_v4", "_v5")


def _dup_var_decl(path):
    """只查**我们注入的**变量名: 同缩进层内同名出现两次。

    ★为什么必须限定前缀: 上游到处是不同函数各自 `var body` / `let f`,
      缩进一样但作用域不同, Swift 完全合法。全文件粗查会误报几十上百条,
      判据一旦变成噪声就等于不存在。
    ★为什么同缩进就够: 注入段是整段复制的, 两份必然**逐行对齐**,
      缩进完全相同。真正合法的同名声明几乎不可能在同一缩进层重复出现
      而又在同一作用域内 —— 撞上就报, 宁可多报一次让人看一眼。
    """
    try:
        lines = open(path, encoding="utf-8").read().split("\n")
    except Exception:
        return None
    seen = {}
    for ln in lines:
        s = ln.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("///"):
            continue
        m = __import__("re").match(r"^(?:var|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", s)
        if not m:
            continue
        name = m.group(1)
        if not name.startswith(INJECT_PREFIX):
            continue
        indent = len(ln) - len(ln.lstrip())
        key = (indent, name)
        if key in seen:
            return name
        seen[key] = 1
    return None


if __name__ == "__main__":
    sys.exit(main())
