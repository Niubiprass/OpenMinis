#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ci_assert_v64 —— v64「切断自我播种」判据(CI 入口)。

v64 的判据本体在 ios15_fallback.verify_deseed_v64(与注入同源, 避免两处
各写一份判据而漂移)。本文件只做三件事: 造产物、跑判据、跑反向。

跑法: ci_assert_v64.py <产物根目录>
     产物根目录须含 src/ios/Agent/MessageList/MessageListInfrastructure.swift
     (约定与 ci_assert_v63.py 一致: 产物由 verify_v63.sh / CI 前置步骤生成,
      本脚本只验产物, 不自己建 —— 两套建产物流程迟早会漂)

退出码约定(与 v49~v63 一致, **SKIP 绝不算通过**):
    0 = 真通过   1 = 真失败   3 = 无法检查(环境不全)

层次:
    core  = fallback.verify_deseed_v64(形状+数据流) + verify_swift_static_v63(语法)
    probe = 装机可观测性(去播种/收敛闸打点是否在位 —— 判据全绿 ≠ 病治好)
    sab   = reverse_v64.py 的 9 条 sabotage, 全部问**实质**而非「标记在不在」

★为什么 v64 换了判据骨架
  v64 初版是「同宽幂等锁」, 判据是 verify_idempotent_v64(五层, 配 reverse_v64
  9 条 sabotage, 自证 9 拦下 0 漏过)。它全绿, 但随后被**装机日志时间戳证伪**:
  idx=9 六拍间隔 0.183/0.192/0.392/0.212/0.599s, 0.35s 时间窗只能拦下 3 拍,
  剩下 3 照样累加 ⇒ 那把锁拦不住病, 却被判据和 9 条 sabotage 一起放过。

  这是本项目第三次撞上「判据全绿但药不治病」:
    run#156  空测被计入通过   —— 判据自己没跑
    run#157  只验文本不验语法   —— 编译红而判据全绿
    v64 初版  只验标记在位     —— 锁在位但锁不住病(9 条 sab 全部围绕"锁在不在",
                 没有任何一条问"这把锁拦不拦得住 0.4s/0.6s 那两拍")

  换判据后, 新的 sabotage 全部改成**问实质**:
    闸门在不在?        → S1
    闸门算不算?        → S2
    闸门改不改写?      → S3
    闸门会不会误杀真实增长? → S4
    播种值真不取上一轮?   → S5/S6/S7
    闸门在写回之前?     → S8
    闸门会不会退化成 v53 式无条件锁死? → S9
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
COMPAT_REL = os.path.join("src", "ios", "iOS15Compat.swift")
MD_REL = os.path.join("src", "ios", "Views", "Chat",
                      "SelectableMarkdownView.swift")


def _log(m):
    print(m, flush=True)


def _load_fb():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_ci_v64", FB)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def _base_dir(root):
    """接受产物根目录(含 src/ios)或 src/ios 本身。"""
    if os.path.isfile(root):
        root = os.path.dirname(os.path.dirname(os.path.dirname(root)))
    return root if os.path.isdir(os.path.join(root, "src", "ios")) \
        else os.path.dirname(root)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "src")
    _log("v64 判据(切断 self-sizing 自我播种)")
    base = _base_dir(root)
    infra_p = os.path.join(base, INFRA_REL)
    if not os.path.isfile(infra_p):
        _log("  产物不全, 需 %s" % INFRA_REL)
        _log("  生成: bash scripts/verify_v63.sh")
        _log("v64=SKIP")
        return 3

    infra = io.open(infra_p, encoding="utf-8").read()
    _log("  产物: MessageListInfrastructure.swift (%d 字节)" % len(infra))

    fb = _load_fb()
    rc = 0

    # ── core: 判据本体 ──
    try:
        fb.verify_deseed_v64(infra)
        _log("    core  deseed(不播种+收敛闸)      OK")
    except Exception as e:
        _log("    core  deseed(不播种+收敛闸)      ✗ %s" % e)
        _log("::error::v64 判据未通过: %s" % str(e).replace("\n", " "))
        rc = 1

    # 语法级判据顺带跑一遍(run#157 的教训: 编译红而判据全绿)
    try:
        compat = io.open(os.path.join(base, COMPAT_REL), encoding="utf-8").read()
        md = io.open(os.path.join(base, MD_REL), encoding="utf-8").read()
        fb.verify_swift_static_v63(compat)
        _log("    core  swift-static(泛型禁static)  OK")
    except Exception as e:
        _log("    core  swift-static(泛型禁static)  ✗ %s" % e)
        _log("::error::v64 语法判据未通过: %s" % str(e).replace("\n", " "))
        rc = 1

    # ── 装机可观测性: 判据全绿 ≠ 病治好, 必须留痕 ──
    _log("    probe 装机可观测性")
    obs = [
        ("去播种打点(否则装机日志看不出断没断)", "[V64-DESEED]"),
        ("收敛闸打点(hold 计数)", "[V64-CONVERGE]"),
        ("收敛闸真的改写 _ios15Reconciled", "_ios15Reconciled = _v64est"),
    ]
    for desc, needle in obs:
        if needle in infra:
            _log("      ✓ %s" % desc)
        else:
            _log("      ✗ %s —— 缺 %r" % (desc, needle))
            _log("::error::v64 装机将零输出, 病治没治无法判别")
            rc = 1

    # ── 反向: sabotage 必须被拦住 ──
    _log("    sab")
    p = subprocess.run([sys.executable, os.path.join(HERE, "reverse_v64.py"), base],
                       cwd=REPO, capture_output=True, text=True)
    for line in (p.stdout + p.stderr).strip().splitlines():
        if line.strip():
            _log("      " + line.strip())
    if p.returncode == 0:
        _log("      OK v64 反向: 全部拦下")
    elif p.returncode == 3:
        _log("      ✗ 空测 —— 反向判据自己没跑起来, 不计入任何结论")
        rc = 1
    else:
        rc = 1

    _log("  v64=%s" % ("OK" if rc == 0 else "BAD"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
