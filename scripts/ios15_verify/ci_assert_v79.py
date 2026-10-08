#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_assert_v79 —— v79「流式 cell 走 live measure」判据(CI 入口)。

跑法: ci_assert_v79.py <产物根目录>
退出码: 0 通过 / 1 失败 / 3 SKIP(产物不全)。SKIP 不算通过。

层次:
    core  = fallback.verify_stream_live_v79(顺序+行为)
    probe = 装机可观测性(_v53Note(.none) / skip-precalc 打点)
    sab   = reverse_v79.py; `--no-sab` 避免与 reverse 递归
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FB = os.path.join(REPO, "scripts", "ios15_fallback.py")
INFRA_REL = os.path.join("src", "ios", "Agent", "MessageList",
                         "MessageListInfrastructure.swift")


def _log(m):
    print(m, flush=True)


def _load_fb():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_ci_v79", FB)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def _base_dir(root):
    if os.path.isfile(root):
        root = os.path.dirname(os.path.dirname(os.path.dirname(root)))
    return root if os.path.isdir(os.path.join(root, "src", "ios")) \
        else os.path.dirname(root)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "src")
    _log("v79 判据(流式 cell 走 live measure)")
    base = _base_dir(root)
    infra_p = os.path.join(base, INFRA_REL)
    if not os.path.isfile(infra_p):
        _log("  产物不全, 需 %s" % INFRA_REL)
        _log("v79=SKIP")
        return 3

    infra = io.open(infra_p, encoding="utf-8").read()
    _log("  产物: MessageListInfrastructure.swift (%d 字节)" % len(infra))

    fb = _load_fb()
    rc = 0

    try:
        fb.verify_stream_live_v79(infra)
        _log("    core  stream-live                     OK")
    except Exception as e:
        _log("    core  stream-live                     BAD %s" % e)
        rc = 1

    _log("    probe 装机可观测性")
    for desc, needle in (
            ("流式判定打点", "[V79-STREAM]"),
            ("live 探针接线(_v53Note(.none))", "_v53Note(.none"),
            ("B-precalc 放行打点", "[V79-STREAM] skip-precalc"),
    ):
        if needle in infra:
            _log("      OK %s" % desc)
        else:
            _log("      BAD %s —— 缺 %r" % (desc, needle))
            rc = 1

    if "--no-sab" in sys.argv:
        _log("    sab                    SKIP(--no-sab, 避免与 reverse_v79 递归)")
    else:
        p = subprocess.run(
            [sys.executable, os.path.join(HERE, "reverse_v79.py"), base],
            cwd=REPO, capture_output=True, text=True)
        for line in (p.stdout + p.stderr).strip().splitlines():
            if line.strip():
                _log("      " + line.strip())
        if p.returncode == 0:
            _log("      OK v79 反向: 全部拦下")
        elif p.returncode == 3:
            _log("      BAD 空测 —— 反向判据自己没跑起来")
            rc = 1
        else:
            rc = 1

    _log("  v79=%s" % ("OK" if rc == 0 else "BAD"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
