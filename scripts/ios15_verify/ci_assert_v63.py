#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v63 判据(CI 入口): hosting 层 invalidate + config 身份判等 + settle drift 兜底。

跑法: ci_assert_v63.py <产物根目录>
     产物根目录须含 src/ios/iOS15Compat.swift 与
     src/ios/Views/Chat/SelectableMarkdownView.swift

退出码约定(与 v49~v53 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core  = fallback 内三个 verify_*_v63(形状: 代码在不在、接线对不对、语法合不合法)
    probe = 探针自证能力(装机能否分辨「这段跑没跑」)
    sab   = reverse_v63.py 的 17 条 sabotage, 守的是**判据本身会不会失灵**

★为什么 v63 要单独开一个 CI 入口, 而不是把判据塞进 v53 的:
  v63 修的是 v60 引入的伤 —— v60 把 intrinsicContentSize 的**高度**也改成
  noIntrinsicMetric(为了治宽度污染), 而 iOS 15 上它是 SwiftUI 内容变化的
  唯一信号源(iOS 16 起才有 sizingOptions)。这条与 v53 的三条短路无关,
  塞进 v53 会让 v53 判据的边界变得无法陈述。
  外部交叉验证: Mozilla Firefox iOS 的 HostingTableViewCell.host() 每次
  rootView 赋值后都跟 invalidateIntrinsicContentSize();
  StackOverflow 77027194(36k 赞)明确说 setNeedsLayout/layoutIfNeeded 都无效;
  vbat.dev 与 Apple FB9641883 社区解法同结论。
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FB = os.path.join(ROOT, "scripts", "ios15_fallback.py")
COMPAT_REL = os.path.join("src", "ios", "iOS15Compat.swift")
MD_REL = os.path.join("src", "ios", "Views", "Chat", "SelectableMarkdownView.swift")


def _load_fb():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_ci_v63", FB)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def _resolve(root):
    """接受产物根目录(含 src/ios)或 src/ios 本身。返回 (compat, md) 或 None。"""
    if os.path.isfile(root):
        root = os.path.dirname(os.path.dirname(os.path.dirname(root)))
    base = root if os.path.isdir(os.path.join(root, "src", "ios")) else \
        os.path.dirname(root)
    cp = os.path.join(base, COMPAT_REL)
    mp = os.path.join(base, MD_REL)
    if not (os.path.exists(cp) and os.path.exists(mp)):
        return None
    return (io.open(cp, encoding="utf-8").read(),
            io.open(mp, encoding="utf-8").read())


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "src")
    print("v63 判据(invalidate 通道 + config 判等 + drift 兜底)")
    got = _resolve(root)
    if got is None:
        print("  产物不全, 需 %s 与 %s" % (COMPAT_REL, MD_REL))
        print("  生成: bash scripts/verify_v63.sh")
        print("v63=SKIP")
        return 3
    compat, md = got
    print("  产物: iOS15Compat.swift (%d) + SelectableMarkdownView.swift (%d)"
          % (len(compat), len(md)))
    fb = _load_fb()
    ok = True

    # ---- core ----
    for name, fn, args in (
            ("gate(invalidate+判等+高度)", fb.verify_intrinsic_gate_v63, (compat, md)),
            ("uncouple(drift 兜底)",         fb.verify_uncouple_v63,      (md,)),
            # ★run#157 新增。文本判据证明「改到位」, 证明不了「能编译」:
            #   v63 首版把 static 计数器放进泛型的 _HostingContentCellView,
            #   66 条断言全绿, Release 编译 exit 65。
            ("swift-static(泛型禁static)",   fb.verify_swift_static_v63,  (compat,))):
        try:
            fn(*args)
            print("  core  %-26s OK" % name)
        except Exception as e:
            ok = False
            print("  core  %-26s BAD %s" % (name, str(e)[:150]))

    # ---- probe ----
    # ★这不是"再检查一遍代码在不在"(那属于 core), 而是检查**装机可观测性**:
    #   v53/v62 连续两版栽在"零输出被忽略"上 —— 代码在, 但装机日志一个字都没有,
    #   于是没人知道它没跑。判据全绿反而成了掩盖。
    #   这里要求探针必须同时具备「计数」与「打印」两半, 且两条路径都计数 ——
    #   只会打数字但从不自增, 等于永远打印 0, 与没有探针等价。
    print("  probe 装机可观测性")
    if compat.count("_v63ProbeIncr()") < 3:
        ok = False
        print("    ✗ 缺: 探针调用点 —— 应 3 处(声明 + fast + rebuild), "
              "实测 %d 处; 少一处就有一类路径在装机日志里隐身"
              % compat.count("_v63ProbeIncr()"))
    else:
        print("    ✓ 探针调用点齐全: %d 处(声明 + fast + rebuild)"
              % compat.count("_v63ProbeIncr()"))
    # 每项写成「在位时读什么」而不是「缺失时读什么」——
    #   BAD 分支直接复用同一句, 若句子是「不会打印」这种坏消息,
    #   印在 OK 行上就是反的(犯过一次)。所以这里用陈述句 + 前缀区分。
    for key, what in (
            # ★锚点已随 run#157 修复改名: 计数器从泛型宿主搬到非泛型 _V63Probe,
            #   字段名 _v63FastHit -> fastHit。若这里不跟着改, 判据会红,
            #   而红的原因是「判据腐化」不是「注入缺失」—— 最难查的那类假红。
            ("fastHit &+= 1", "快速路径计数器在自增"),
            ("rebuildHit &+= 1", "重建路径计数器在自增"),
            ("print(\"[V63-PROBE] fast=",
             "探针打印在位(否则装机日志零输出 —— v53/v62 就死在这)")):
        if key not in compat:
            ok = False
            print("    ✗ 缺: %s —— 找不到 %r" % (what, key))
        else:
            print("    ✓ %s" % what)

    # ---- sab ----
    sb = os.path.join(HERE, "reverse_v63.py")
    if "--no-sab" in sys.argv:
        print("  sab                     SKIP(--no-sab, 避免与 reverse_v63 递归)")
    elif not os.path.exists(sb):
        print("  sab                     BAD(缺 reverse_v63.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sb, root, "--sab"],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        print("  sab                     %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:80] if tail else ""))
        if r.returncode != 0:
            ok = False

    print("v63=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
