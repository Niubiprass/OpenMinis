#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v52 判据(CI 入口): 宽度合理性闸门(A+B) + 宽度来源探针(C) + 欠账自愈快照(E)。

跑法: ci_assert_v52.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49/v50/v51 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core  = fallback 内的 verify_width_sane_gate_v52 + verify_debtguard_snapshot_v52
    scope = 编译级检查(API 存在性 / NSLog 变参可选类型 / 段内零危险写 / 判据段边界)
    sab   = 判据自证 —— sabotage 必须全被拦, 且基线不误伤

★本版归因(minis-2026-10-04.log, 装机 v51 后)的三条转折:

  ① **v51-A 生效了, 但不是根因。**
     `V51-FRAMEPIN fvW=tcW=svW=358` 占 **143/146 零例外**
     ⇒ v50 那个「画字视图比父容器宽 32pt」彻底消失
     ⇒ 而用户症状**一字未改** ⇒ 换靶。

  ② **新靶是宽度 375.7。**
     v50 日志 0 次 / v51 日志 **61 次**, 全集中在 `len=57` 那一个 cell。
     v18 段 `min(_svW, _cvW)`(_cvW 恒 390)把 375.7 **当成净宽**;
     该宽下排 1 行(tcH=18.7), 按 358 排需 2 行(needH=49.0)
     ⇒ `V41-DEBT svH=26.7 needH=49.0 debt=22.3 hits=6` 反复欠账
     ⇒ 屏幕上就是「一段话的最后一行被裁」。旁证: `size=358.0x18.7` 23 次。

     三条排除法确认它是过渡态而非合法布局宽:
       · `insetL` 全日志 **102 条恒 0.0** ⇒ 不是内边距算出来的
       · `390 - 375.7 = 14.3` ⇒ 不是任何整数边距
       · 首次出现前 5ms 恰有 `REJECT-NAN-INF-NEG size=0.0x-8.0`(全日志 77 次)
         ⇒ 那一瞬 superview 几何是脏的

  ③ **v38-A 是一次都没跑过的死代码(本版头号发现)。**
     装机日志三条零命中: `deferred debt CONSUMED` 0 / `deferred debt HELD` 0 /
     `DeferDebt OWED` 0。而 v38-A 自己不打日志 ⇒ 「一次没跑」在日志里是**静默**的。
     代码结构给出原因 —— v18 段里两个 `if` 用**同一个判据**, 且**撑高在前、自愈在后**:
         撑高(v18 原有):  `_sv.frame.size.height < _needH - 0.5`
         自愈(v38-A):     `_svH = superview?.frame.size.height; _svH < _needH - 0.5`
     ⇒ 判据成立时高度**已被撑到 _needH**, 自愈判据必然为假
     ⇒ 判据不成立时自愈判据也必然为假
     ⇒ **两个分支都指向「永不执行」**

     ★这一条同时解释了用户说的「大部分都是**新的会话第一段**就卡」:
       首段定型之后, 唯一可能纠正欠账的那道自愈门**从来就没开过**。

★本轮两次自我纠正(都留了痕, 因为它们都是"看起来很像因果"的假关系):

  (1) **B 的理由是错的。** 我最初说「frame 恒 358 而 bounds 偶发 375.7」——
      装机日志核对后不成立: `V41-DEBT` 读的正是 `frame.size.width`, 也报 375.7
      ⇒ frame 同样被污染, B 单独做无效。
      B 保留的价值是**同源**: 与 `_svf0`(superview?.frame)读同一字段。
      ⇒ 纪律: 一个修法若建立在某个读数差异上, **先确认那两个读数来自不同字段**。

  (2) **「v38-A 被 SKIP-DEDUPE 吞了」是错的。**
      `storageLen=57 measureW=358 tcW=358 lastH=49.0` 那 11 条 SKIP-DEDUPE
      是**别的调用者**(流式增量/复用链/settle hook)在打, 与 v38-A 无关:
      它根本没走到借 flag 那一步, 没资格产生任何日志。
      ⇒ 纪律: **「某段代码看起来该被调用」不等于「它被调用过」**;
        判据要落到**它自己会产生的那条日志**上; 找不到那条日志,
        就该怀疑它没跑, 而不是去查它下游的机制。
"""
import os
import subprocess
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
        print("用法: ci_assert_v52.py <产物根目录 或 SelectableMarkdownView.swift>")
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
    spec = importlib.util.spec_from_file_location("fb_v52", fb)
    fbv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbv)
    for name, fn in (
            ("A+B+C(宽度闸门)", getattr(fbv, "verify_width_sane_gate_v52", None)),
            ("E(欠账自愈快照)", getattr(fbv, "verify_debtguard_snapshot_v52", None))):
        if fn is None:
            print("  core %-18s BAD(判据函数缺失)" % name)
            ok = False
            continue
        try:
            fn(t)
            print("  core %-18s OK" % name)
        except Exception as e:
            print("  core %-18s BAD %s" % (name, e))
            ok = False

    # ---- scope(编译级) ----
    sc = os.path.join(HERE, "scope_check_v52.py")
    if not os.path.exists(sc):
        print("  scope                SKIP(缺 scope_check_v52.py)")
    else:
        r = subprocess.run([sys.executable, sc, md], capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().split("\n")
        print("  scope                %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:90] if tail else ""))
        if r.returncode != 0:
            ok = False

    # ---- sab ----
    # ★必须有 `--no-sab` 开关: reverse_v52.py 的基线自检要跑本入口做"通过"
    #   判定, 而本入口默认会去跑 reverse_v52 --sab ⇒ 两个脚本互相递归,
    #   进程树指数膨胀, CI 直接挂死(v51 踩过这个坑)。
    #   ⇒ 纪律: **调用关系是单向的**, CI 入口可主动降级为不跑 sab。
    sb = os.path.join(HERE, "reverse_v52.py")
    if "--no-sab" in sys.argv:
        print("  sab                  SKIP(--no-sab, 避免与 reverse_v52 递归)")
    elif not os.path.exists(sb):
        print("  sab                  SKIP(缺 reverse_v52.py)")
    else:
        r = subprocess.run([sys.executable, sb, md, "--sab"],
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().split("\n")
        print("  sab                  %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:90] if tail else ""))
        if r.returncode != 0:
            ok = False

    print("v52=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
