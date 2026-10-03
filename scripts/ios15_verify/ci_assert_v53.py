#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v53 判据(CI 入口): 滑动期高度短路三来源探针(P) + 死锁/放行/判据(C1+C2) + 首段专项(FIRST)。

跑法: ci_assert_v53.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49~v52 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core  = fallback 内三个 verify_*_v53
    scope = 编译级检查(跨文件可见性 / NSLog 变参可选类型 / 占位符配平 /
           段内零几何写 / 字段作用域)
    sab   = 判据自证 —— 14 条 sabotage 必须全被拦, 且基线不误伤

★本版归因(minis-2026-10-04 4.log, 装机 v52 后 + 录屏 116.6s 抽帧)的转折:

  用户原话三条症状:
    「每次重新开始新的对话第一段总是卡字」
    「所有卡字都会在滑动的时候卡一下显示」
    「滑动的时候一下卡字一下不卡字」

  ① **「卡字」是纵向整行缺失, 不是横向裁切 —— v51 的归因错了。**
     录屏 8fps 特写连续 5 帧 `halfBands`(半行裁切指纹) = 2/5/4/2/4,
     而 `c_048` 之后连续 **17 帧 halfBands=0**(滚动一停就恢复)。
     `f_010`(第一段第二行只剩上半)与**同一屏第二段三行完整**并存
     ⇒ 同一宽度下有的 cell 裁有的不裁 ⇒ 宽度不是主因, **高度**才是。

  ② **C-2(真凶): cell 高度欠账永久凝固。**
     同一 tick 两个探针读数打架 —— 这是全部铁证:
         [06:11:56.634] V44-TEXTFRAME tvH=1272.3 svAfter=1272.3 needH=1272.3
         [06:11:56.661] V52-DEBT    preSVH=1004.0 needH=1272.3 debt=268.3
     视图侧 `svAfter` 51/51 次都是 1272.3(**永远正确**),
     容器侧 `preSVH` 全程只有 1003.7/1004.0 两个值(**从头到尾没动过**)。
     欠 268.3pt ≈ 8 行字。

     空转链条: E 判据见欠账 → 置 flag → `invalidateCellSizeIfNeeded()` →
     走 `abs(newHeight - previousHeight) <= 1` 分支(视图自己的高确实没变)
     → 打印 `deferred debt CONSUMED`(宣告纠正完成)→ 清 flag。
     而真正的纠正动作 `applyCellCorrection()` 只做 `clearCachedHeight()` +
     `invalidateLayout()`, **返回 true 只证明调用成功, 不证明高度真改了**。

     ★关键证据: `deferred debt CONSUMED` 打印了 **105 次**, 而 preSVH 纹丝不动
     —— 这个「宣告成功但实际未落地」的谎言就是 C-2 的核心。
     根因再往下: `preferredLayoutAttributesFitting` 里有**三条高度短路**,
     A(dedup) 在**所有其它短路之前**无条件生效 ⇒ 真实测量永远走不到。

  ③ **「一下卡字一下不卡」的机制 = B 路短路的开关效应, 不是宽度拉锯。**
     滚动开始 → `deferSelfSizing=true` → B 路返回缓存 1004 → 尾部裁掉;
     滚动停止 → B 路失效 → 真实测量 → 高度修对 → 文字完整。
     ⇒ 用户的观感就是来回闪。**v51-A 的 `tvW=390`/`fvW=358` 逐帧交替确实存在**
     (`tvW=390` 占 89/95), 但它只影响横向, 降级为次要。

  ④ **C-1: v52-A 存在记忆位初始化死锁。**
     装机日志: `sane=1` **0/96**、`picked=358.0` 96/96、`edge=0` 96/96。
     死锁: 记忆位只在 `sane != 0` 时写, 而 358 要被认定放行必须先与记忆位
     比对, 记忆位初始 nil ⇒ 358 永比对失败 ⇒ 每帧回落 ⇒ sane 恒 0 ⇒
     记忆位**永远得不到第一次写入**。`375.7` 归零靠的是「无条件回落到
     cvW-32」这个硬编码, 不是记忆位 ⇒ 闸门退化成**常量 358 强制器**,
     气泡型 cell(真实净宽 326)会被误伤成 358 而超框。

  ⑤ **首段为什么「总是」卡。**
     `len=56`(新会话第一段)从第 1 帧到第 168 帧 `preSVH=61.3 needH=83.3
     debt=22.0` **恒定不变** —— 22pt ≈ 半行, 正是 `f_010` 里第二行只剩
     上半的原因。`consumeDeferredCorrectionIfNeeded` 原本第一行就是
     `guard deferredCorrectionPending else { return }`, 而 v52 的 CONSUMED
     判据只验「调用成功」就提前清了 flag ⇒ settle 时刻这个视图被挡在门外。

【v53 的三处修法, 与判据一一对应】
    P     : 三条短路各埋 `_v53Note`, 判读「到底哪一路在挡真实测量」
    C1    : `_v53memW` + `guard _v52ok` 打破记忆位死锁, 且拒绝污染宽度
             (375.7 的 dev=14.3 落在 [1, cvW*0.5] 区间内, 区间判据拦不住)
    C2    : 三条短路各加 `!v53DebtIsRipe` 守卫; CONSUMED 判据改成
             「cell 实际高达标」才算还清, 否则保持 pending 并打 [V53-HOLD]
    FIRST : settle 入口从 flag-only 改成 `flag || 仍欠账`
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
INFRA_REL = "src/ios/Agent/MessageList/MessageListInfrastructure.swift"


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


def root_of(md):
    """从 SelectableMarkdownView.swift 反推产物根目录。

    ★必须**向上逐级探测**, 不能用固定层数的 dirname。
      v50/v51/v52 的 ci_assert 都写了 3 层 `dirname` —— 而路径是
      `<root>/src/ios/Views/Chat/SelectableMarkdownView.swift`,
      从文件退到 `<root>` 要 **5** 层
      (Chat→Views→ios→src→<root>)。3 层只退到 `<root>/src/ios`,
      于是 `os.path.join(root, "scripts", "ios15_fallback.py")`
      永远指向一个不存在的路径。
      它没炸是因为 `_fallback_path` 的第二候选
      `HERE/../ios15_fallback.py` 恰好兜住了 —— 也就是这三个入口
      一直是**靠兜底活着**的: 判据跑的是判据文件旁边的 fallback,
      而不是产物树里那一份。一旦判据被拷到别处运行, 就会静默换掉
      被测对象。
      ⇒ 纪律: **反推根目录要靠「找得到已知锚点」判定, 不靠数层数**;
        层数一改就静默错位, 而静默错位在 CI 上表现为
        「莫名其妙的 SKIP / 跑错了文件」, 极难归因。
    """
    d = os.path.dirname(os.path.abspath(md))
    while True:
        if os.path.exists(os.path.join(d, INFRA_REL)):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def main():
    if len(sys.argv) < 2:
        print("用法: ci_assert_v53.py <产物根目录 或 SelectableMarkdownView.swift>")
        return 3
    target = sys.argv[1]
    md = resolve(target)
    if md is None:
        print("SKIP(找不到产物: %s)" % MD_REL)
        return 3
    root = root_of(md)
    if root is None:
        print("SKIP(从 %s 向上找不到 %s —— 产物树不完整)"
              % (os.path.basename(md), INFRA_REL))
        return 3
    infra = os.path.join(root, INFRA_REL)
    if not os.path.exists(infra):
        print("SKIP(找不到产物: %s)" % INFRA_REL)
        return 3

    t = open(md, encoding="utf-8").read()
    f = open(infra, encoding="utf-8").read()
    print("产物: %s (%d) + %s (%d)"
          % (os.path.basename(md), len(t), os.path.basename(infra), len(f)))

    ok = True

    # ---- core ----
    fb = _fallback_path(root)
    if not os.path.exists(fb):
        print("core=SKIP(找不到 scripts/ios15_fallback.py)")
        return 3
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v53", fb)
    fbv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbv)
    for name, attr, args in (
            ("P(短路三来源探针)", "verify_shortcircuit_probe_v53", (t, f)),
            ("C1+C2(死锁/放行/判据)", "verify_debtgate_release_v53", (t, f)),
            ("FIRST(首段专项)", "verify_first_para_settle_v53", (t,))):
        fn = getattr(fbv, attr, None)
        if fn is None:
            print("  core %-22s BAD(判据函数缺失: %s)" % (name, attr))
            ok = False
            continue
        try:
            fn(*args)
            print("  core %-22s OK" % name)
        except Exception as e:
            print("  core %-22s BAD %s" % (name, e))
            ok = False

    # ---- scope(编译级) ----
    sc = os.path.join(HERE, "scope_check_v53.py")
    if not os.path.exists(sc):
        print("  scope                  BAD(缺 scope_check_v53.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sc, root],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        print("  scope                  %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:80] if tail else ""))
        if r.returncode != 0:
            ok = False

    # ---- sab ----
    # ★必须有 `--no-sab` 开关: reverse_v53.py 的基线自检会调本文件里的
    #   core 判据函数, 而本入口默认又去跑 reverse_v53 --sab ⇒ 互相递归。
    #   v51 踩过这个坑(进程树指数膨胀, CI 挂死)。
    #   ⇒ 纪律: **调用关系是单向的**, CI 入口可主动降级为不跑 sab。
    sb = os.path.join(HERE, "reverse_v53.py")
    if "--no-sab" in sys.argv:
        print("  sab                    SKIP(--no-sab, 避免与 reverse_v53 递归)")
    elif not os.path.exists(sb):
        print("  sab                    BAD(缺 reverse_v53.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sb, root, "--sab"],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        print("  sab                    %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:80] if tail else ""))
        if r.returncode != 0:
            ok = False

    print("v53=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
