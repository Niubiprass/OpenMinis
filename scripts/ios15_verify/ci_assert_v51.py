#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v51 判据(CI 入口): 钉 textView 自身 frame 宽(A) + 探针挪出补高 if(C)。

跑法: ci_assert_v51.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49/v50 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core  = fallback 内的 verify_view_frame_pin_v51 + verify_probe_unhook_v51
    scope = 编译级检查(API 存在性 / NSLog 变参可选类型 / 段内零危险写 /
           `_realW2` 可达性 / 占位符个数)
    sab   = 判据自证 —— 12 条 sabotage 必须全被拦, 且基线不误伤

★为什么 A 是本版的关键(v50 装机实测的硬教训):

    v50 的两条判据在装机后**全部达标** ——
        V50-UNIFY  36/36 used=357        (A' 生效)
        V50-PINW   62/62 tcW=358         (钉宽每帧成功)
        V50-LAIDW  62/62 laidW=358        (C 生效)
    而用户的三个症状一字未改 ⇒ **v50 修的不是根因**。

    根因在 v18 段的覆盖面之外。V44-TEXTFRAME 实测:
        svW (父容器宽)      = 358.0   **153/153 零例外**
        tvW (textView 自己) = 390.0   占 50/59
        tcW 与 tvW 完全同构(全局 164 条 358 / 81 条 390)
    v18 段从 v32 到 v48 一路钉的全是 `textContainer.size.width`,
    **从来没有一处写 `self.frame.size.width`**。而画字的是 UITextView 自己,
    它的 bounds 是 390 而父容器只有 358 ⇒ 右侧 32pt 恒被自己的 bounds 裁掉。
    量化: V43-WIDTH 的 dh(脏宽测高-净宽测高)= **22.3 出现 18 次**
    (hDirty=1297.0 vs hNet=1319.3)—— 那就是排不下的那几行。

    第 8128 行那道钳制(`if !_edgeTouch, ... frame.size.width = _realW`)
    救不回来: 它带 `!_edgeTouch` 前缀, 贴边态(x<=0.5 && w>=cvW-1)整段跳过
    ⇒ tvW 在 390/358 之间**逐帧交替**(len=392: n=3/5/6/7 是 390, n=4 是 358)
    ⇒ 每个交替帧 TextKit 全量重排 = 用户说的「滑动整体动卡闪」。

★为什么 C 必做(判读日志时被自己的探针骗了):

    V49-WWRITER 的 laidW 出现两个值(358 五条 / -1 五十一条), 而 V50-LAIDW
    恒为 358。逐行查代码才发现**两个探针不在同一个函数里**:
        V49-WWRITER 在 `ios15ApplyFrameFix()` 的 KVO 抢帧闭包内, 且关在
        `if _v42Need > 1, f.size.height + 0.5 < _v42Need` 里(补高才打);
        V50-LAIDW   在 `layoutSubviews()` 的 v18 段内, 无条件。
    ⇒ laidW=-1 不是数据异常, 是**探针的触发条件**与另一个不同。
    ★真正的坑: `kvoW=390 ⇔ laidW=-1` **完全同构(51/51)** ——
      看起来像因果, 实际两者被**同一个 if 门**一起控住。
    ⇒ 纪律: **看到两个读数完美相关时, 先确认它们不是被同一个条件门控的。**
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
        print("用法: ci_assert_v51.py <产物根目录 或 SelectableMarkdownView.swift>")
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
    spec = importlib.util.spec_from_file_location("fb_v51", fb)
    fbv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbv)
    for name, fn in (("A(钉 frame 宽)", getattr(fbv, "verify_view_frame_pin_v51", None)),
                     ("C(探针挪出 if)", getattr(fbv, "verify_probe_unhook_v51", None))):
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
    sc = os.path.join(HERE, "scope_check_v51.py")
    if not os.path.exists(sc):
        print("  scope              SKIP(缺 scope_check_v51.py)")
    else:
        r = subprocess.run([sys.executable, sc, md], capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().split("\n")
        print("  scope              %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:90] if tail else ""))
        if r.returncode != 0:
            ok = False

    # ---- sab ----
    # ★必须有 `--no-sab` 开关: reverse_v51.py 的基线自检要跑本入口做"通过"
    #   判定, 而本入口默认会去跑 reverse_v51 --sab ⇒ 两个脚本互相递归,
    #   进程树指数膨胀, CI 直接挂死(本轮第一条版本就这么卡住的)。
    #   ⇒ 纪律: **调用关系是单向的**, CI 入口可主动降级为不跑 sab。
    sb = os.path.join(HERE, "reverse_v51.py")
    if "--no-sab" in sys.argv:
        print("  sab                SKIP(--no-sab, 避免与 reverse_v51 递归)")
    elif not os.path.exists(sb):
        print("  sab                SKIP(缺 reverse_v51.py)")
    else:
        r = subprocess.run([sys.executable, sb, md, "--sab"],
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().split("\n")
        print("  sab                %s %s"
              % ("OK" if r.returncode == 0 else "BAD", tail[-1][:90] if tail else ""))
        if r.returncode != 0:
            ok = False

    print("v51=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
