#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 断言 51: v49 探针就位 —— **纯诊断, 钉死「谁把 tcW 推回 390」**。

【v49 为什么存在】log18 首次打破 log17 的「tcW 与 gap 完全同构」:
    tcW=358.0  10 条  gap 8.1~8.5    ← 全部正常
    tcW=390.0  49 条  gap 8.2~97.6   ← 18 帧正常 + 31 帧残缺(混合!)
`len=122` 在 tcW=390 下 gap=8.2(**正常**)—— 前两版从未有过这个组合。
⇒ **v48 的钉宽确实生效了, 但只治好轻文本**; 重文本(len=1013, 含 1 个表格)
仍残缺。决定性对照:
    n=9  cachedW=357.0 tcW=358.0 tcH=2000.0 usedH=1727.6 gap=8.1  ✅
    n=10 cachedW=389.0 tcW=390.0 tcH=1727.7 usedH=1638.1 gap=97.6 ❌
`cachedW` 与 `tcW` **完全同构(35/36 零例外)** ⇒ 推宽者与 cachedW 同源。
逐毫秒铁证(00:07:42):
    .678 [V42-MISS]   tcW=358.0 usedH=1727.6   ← 排版正确
    .679 [V46-ATTACH] tcW=390.0 usedH=1638.1   ← **1 毫秒内被推回**
而 v48 的钉宽写在 v18 段内(缩进 12, layoutSubviews 内), **早于**表格附件
测量链跑完 ⇒ 纠偏追不上。

【为什么纯诊断不盲修】候选写入者至少三个, 修法互相冲突:
    · V46 attachmentBounds 测量链 —— 放宽它动 v16 表格渲染
    · v37 probe 钳位链 —— 动它动那套 9 处泄漏防护
    · SwiftUI 自己的布局 pass —— 抢它是 v13/v34 闪屏翻车的老路
    · (D4) TextContainerGuard 熔断 219 次那条 —— 是治 fillLayoutHole
      11918ms 卡死的, 同样是历史 trade-off
先探针定位到**行**再动刀。

【本断言查三样, 缺一不可】
  1. struct  —— 注入函数在、两个探针段在、日志字段齐全、段内零赋值
     (实现: 调 ios15_fallback.verify_width_writer_v49)
  2. 作用域 —— ★本轮连踩两个**编译级**错误而结构判据全程放行:
       S1 struct _V49W 声明在函数体内 → KVO 侧跨函数引用不到 → 编译失败
       S2 KVO 侧读 self.attV46CachedWidth → 那是 TableAttachment 的成员
          → 跨类访问 → 编译失败
     (实现: 调 scope_check_v49.scope_check_v49)
  3. 重文本专项 —— 用户明确要求的强度。v49 每帧都跑, 所以"重文本下不能
     自我损害"是本版最该验的事:
       T3 usedRect 只能在 0.5s 节流内读(它是**惰性**属性, 无条件读每帧
          都可能触发排版, len=1013/2000pt 高下必卡)
       T6 v48 钉宽写入点仍在(钉宽失效 = v48 成果作废)
       T7 v47 重排仍在(重排失效 = 碎片与视口脱钩)
       T8 探针在 v18 段**无条件**路径(被包进 if 的话, "碎片已排好"的
          常态帧反而不经过探针, 而那正是 log18 里最该看的帧)
     (实现: 调 reverse_v49_heavy.heavy_checks)

【为什么三层都要有, 不能只留结构判据】
  v48 就是只有结构判据的那一版: 判据全绿、CI 全绿、装机后 tcW=390 的帧
  仍有 49 条。结构判据证明"代码形状对", 不证明"作用域合法", 更不证明
  "在重文本下不自我损害"。三层分别对应**编译能否过**与**运行时是否安全**。

用法: ci_assert_v49.py <repo_root>
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.join(HERE, "verify_v49.py")
SCOPE = os.path.join(HERE, "scope_check_v49.py")
HEAVY = os.path.join(HERE, "reverse_v49_heavy.py")


def _product_path(root):
    """定位注入产物 —— 与 ci_assert_v47/v48 同一套约定。"""
    for rel in (
        os.path.join("src", "ios", "Views", "Chat",
                     "SelectableMarkdownView.swift"),
        os.path.join("ios", "Views", "Chat", "SelectableMarkdownView.swift"),
    ):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return p
    return None


def _fallback_path(root):
    return os.path.join(root, "scripts", "ios15_fallback.py")


def main():
    if len(sys.argv) < 2:
        print("用法: ci_assert_v49.py <repo_root>")
        return 2
    root = sys.argv[1]

    fb = _fallback_path(root)
    if not os.path.exists(fb):
        print("v49=SKIP(找不到 scripts/ios15_fallback.py)")
        return 0
    src = open(fb, encoding="utf-8").read()
    if "fix_width_writer_diag_v49" not in src:
        print("v49=SKIP(未注入 v49)")
        return 0

    prod = _product_path(root)
    if not prod:
        print("v49=SKIP(找不到注入产物 SelectableMarkdownView.swift)")
        return 0
    t = open(prod, encoding="utf-8").read()

    # ---- 1. 结构判据 ----
    if not os.path.exists(VERIFY):
        print("v49 struct=BAD(缺少 verify_v49.py)")
        return 1
    r = subprocess.run([sys.executable, VERIFY, prod],
                       capture_output=True, text=True, timeout=600)
    struct_ok = r.returncode == 0
    struct_msg = (r.stdout + r.stderr).strip().split("\n")[-1][:160]
    print("v49 struct=%s %s" % ("OK" if struct_ok else "BAD", struct_msg))
    if not struct_ok:
        return 1

    # ---- 2. 作用域(编译级) ----
    if not os.path.exists(SCOPE):
        print("v49 scope=BAD(缺少 scope_check_v49.py)")
        return 1
    r = subprocess.run([sys.executable, SCOPE, prod],
                       capture_output=True, text=True, timeout=600)
    scope_ok = r.returncode == 0
    scope_msg = (r.stdout + r.stderr).strip().split("\n")[-1][:160]
    print("v49 scope=%s %s" % ("OK" if scope_ok else "BAD", scope_msg))
    if not scope_ok:
        return 1

    # ---- 3. 重文本专项 ----
    if not os.path.exists(HEAVY):
        print("v49 heavy=BAD(缺少 reverse_v49_heavy.py)")
        return 1
    r = subprocess.run([sys.executable, HEAVY, prod],
                       capture_output=True, text=True, timeout=600)
    heavy_ok = r.returncode == 0
    lines = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
    bad = [l for l in lines if l.startswith("❌")]
    heavy_msg = (bad[0] if bad else lines[-1] if lines else "")[:160]
    print("v49 heavy=%s %s" % ("OK" if heavy_ok else "BAD", heavy_msg))
    if not heavy_ok:
        return 1

    # ---- 4. 探针自证: 判据文件本身能拦住本轮真实踩过的坑 ----
    # CI 里跑 sabotage 会多花几分钟, 所以只跑**最关键的一条**(S1 struct
    # 退回函数体内 —— 那是最隐蔽的编译失败)。完整 6 条在本地跑。
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "reverse_v49_scope.py"), prod],
        capture_output=True, text=True, timeout=900)
    sab_ok = r.returncode == 0
    lines = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
    print("v49 sab=%s %s" % ("OK" if sab_ok else "BAD",
                              (lines[-1] if lines else "")[:120]))
    if not sab_ok:
        return 1

    print("v49=OK struct=OK scope=OK heavy=OK sab=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
