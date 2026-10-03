#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v50 判据(CI 入口): 宽度同源(A') + 滑动重排记忆(C)。

跑法: ci_assert_v50.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49 判据一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core  = fallback 内的 verify_width_source_unify_v50 + verify_slide_relayout_v50
    scope = 编译级检查(API 存在性 / 作用域 / 段内零危险写)
    sab   = 判据自证 —— sabotage 必须全被拦

★为什么 sab 必��: 本轮判据自己被证伪过两次 ——
  ① R1 第一版只查"probe 判定在下游", 结果首版真让 probe 也用了钉宽净宽, 判据全绿;
  ② R3 第一版凭推算写 3, 实际是 4, 判据自己报红纠正了我。
两次都是"判据看起来在跑、实际没钉住"。sab 就是防这件事再发生。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"


def _fallback_path(root):
    """定位 ios15_fallback.py —— 产物根目录优先, 退回本判据所在仓库。"""
    cands = [
        os.path.join(root, "scripts", "ios15_fallback.py"),
        os.path.normpath(os.path.join(HERE, "..", "ios15_fallback.py")),
    ]
    for p in cands:
        if os.path.exists(p):
            return p
    return cands[0]


def resolve(target):
    if os.path.isfile(target):
        return os.path.abspath(target)
    p = os.path.join(target, MD_REL)
    if os.path.exists(p):
        return p
    return None


def main():
    if len(sys.argv) < 2:
        print("用法: ci_assert_v50.py <产物根目录 或 SelectableMarkdownView.swift>")
        return 3
    target = sys.argv[1]
    md = resolve(target)
    if md is None:
        print("SKIP(找不到产物: %s)" % MD_REL)
        return 3
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(md))))

    t = open(md, encoding="utf-8").read()
    print("产物: %s (%d 字节)" % (md, len(t)))

    ok = True

    # ---- core ----
    fb = _fallback_path(root)
    if not os.path.exists(fb):
        print("core=SKIP(找不到 scripts/ios15_fallback.py)")
        return 3
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v50", fb)
    fbv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbv)
    for name, fn in (("A'(宽度同源)", getattr(fbv, "verify_width_source_unify_v50", None)),
                     ("C(滑动重排记忆)", getattr(fbv, "verify_slide_relayout_v50", None))):
        if fn is None:
            print("  core %-16s BAD(判据函数缺失)" % name)
            ok = False
            continue
        try:
            fn(t)
            print("  core %-16s OK" % name)
        except Exception as e:
            print("  core %-16s BAD %s" % (name, e))
            ok = False

    # ---- scope(编译级) ----
    sc = os.path.join(HERE, "scope_check_v50.py")
    if not os.path.exists(sc):
        print("  scope              SKIP(缺 scope_check_v50.py)")
    else:
        import subprocess
        r = subprocess.run([sys.executable, sc, md], capture_output=True, text=True)
        print("  scope              %s %s" % ("OK" if r.returncode == 0 else "BAD",
                                              (r.stdout + r.stderr).strip().split("\n")[-1][:90]))
        if r.returncode != 0:
            ok = False

    # ---- sab ----
    sb = os.path.join(HERE, "reverse_v50.py")
    if not os.path.exists(sb):
        print("  sab                SKIP(缺 reverse_v50.py)")
    else:
        import subprocess
        r = subprocess.run([sys.executable, sb, md], capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().split("\n")
        print("  sab                %s %s" % ("OK" if r.returncode == 0 else "BAD",
                                              tail[-1][:90] if tail else ""))
        if r.returncode != 0:
            ok = False

    print("v50=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
