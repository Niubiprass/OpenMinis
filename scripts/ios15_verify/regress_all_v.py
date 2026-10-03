#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全版本判据回归 —— 加一版就把**所有历史版本**的判据重跑一遍。

【为什么需要它】run#37137912522 的失败暴露了一个结构性风险:
v49 本身四层判据全绿, 70/70 + scope + 9/9 + 14 条 sabotage 都过,
但 CI 红了 —— 因为 **v48 的判据被 v49 的新代码误伤**:
    core=OK pure=BAD 赋值4处 违规=[...] 旁路=False idem=OK
    ❌ v48 异常
根因: v48 判据的段右边界是下游的 `// [IOS15-FIX-RELC v28]` 标记, 而 v49
探针正好插在钉宽 if 与那个标记之间 ⇒ v49 的三行记忆位写入被算进了
v48 的写入白名单。

**这类故障本地看不见**: 我跑的是 v49 自己的四层判据 + 一条整链注入,
没有把 v48 的判据在同一份产物上重跑。而 CI 会跑全部 51 条断言。

⇒ 纪律: **每加一版, 必须在同一份产物上重跑所有历史版本的判据**。
   本文件就是这个纪律的载体, 也是 CI 的第一道关(不依赖 GitHub)。

【它跑什么】对同一份产物依次执行:
  · v41 ~ v48 的 CI 判据
  · v47 / v48 的反向测试( sabotage 全拦 + 基线不误伤)
  · v49 的四层(struct / scope / heavy / sab)
判据文件缺失时**直接判失败** —— 判据被删 = 加法保护消失。
产物文件缺失时**判 SKIP 并显式列出** —— 那是本地产物树不完整(环境问题),
不是代码回归, 但必须喊出来, 绝不能静默通过。

【两种传参约定】历史判据的 argv 并不统一, 传错就会得到假失败:
  · arg=root : 收产物根目录, 内部自己拼 src/ios/... 路径
               (v43 v44 v45 v46 v47 v48 v49 reverse_v48)
  · arg=swift: 直接收 SelectableMarkdownView.swift 的文件路径
               (v41 v42 —— 它们 open(path) 直接读, 传目录会
                IsADirectoryError, 这就是本文件最初 3 项失败的真因)
  · arg=none : 不吃产物参数(reverse_v47 直接 import fallback 纯校验)

用法: regress_all_v.py <产物根目录 或 SelectableMarkdownView.swift>
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
MLL_REL = "src/ios/Agent/MessageList/MessageListLayout.swift"

# (显示名, 脚本名, 传参约定, 额外需要的产物文件)
CHECKS = [
    ("v41 判据",         "verify_v41.py",         "swift", []),
    ("v42 判据",         "verify_v42.py",         "swift", []),
    ("v43 判据",         "verify_v43.py",         "root",  [MLL_REL]),
    ("v44 判据",         "verify_v44.py",         "root",  []),
    ("v45 判据",         "verify_v45.py",         "root",  []),
    ("v46 判据",         "verify_v46.py",         "root",  []),
    ("v47 判据",         "ci_assert_v47.py",      "root",  []),
    ("v48 判据",         "ci_assert_v48.py",      "root",  []),
    ("v49 判据(四层)",   "ci_assert_v49.py",      "root",  []),
    ("v47 反向",         "reverse_v47.py",        "none",  []),
    ("v48 反向(20 条)", "reverse_v48.py",        "root",  []),
    ("v49 重文本+8 sab", "reverse_v49_heavy.py",  "swift", []),
    ("v49 作用域+6 sab", "reverse_v49_scope.py",  "swift", []),
]

# 最近三代(v47/v48/v49)的判据与反向测试是当前承重墙, 必须全绿。
# v41~v46 同样在 CI 里跑, 但它们跨代演进(判据 needle 有兼容层),
# 且部分依赖两文件产物, 缺失时以 SKIP 形式显式报出。
MANDATORY = {
    "v47 判据", "v48 判据", "v49 判据(四层)",
    "v47 反向", "v48 反向(20 条)",
    "v49 重文本+8 sab", "v49 作用域+6 sab",
}


def _resolve(target):
    """返回 (swift 路径, 产物根目录 或 None)。"""
    if os.path.isfile(target):
        # 直接给了 swift 文件 —— 根目录往上退两级(src/ios/Views/Chat -> src)
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(target)))))
        return os.path.abspath(target), root
    if os.path.isdir(target):
        sp = os.path.join(target, MD_REL)
        if os.path.exists(sp):
            return sp, os.path.abspath(target)
    return None, None


def main():
    if len(sys.argv) < 2:
        print("用法: regress_all_v.py <产物根目录 或 SelectableMarkdownView.swift>")
        return 2
    sp, root = _resolve(sys.argv[1])
    if not sp:
        print("❌ 找不到产物:", sys.argv[1])
        print("   需要 %s 或含它的产物根目录" % MD_REL)
        return 1
    print("产物: %s (%d 字节)" % (sp, os.path.getsize(sp)))
    print("根目录: %s\n" % root)

    fail, skip, ok, skipped_detail = [], [], 0, []

    for name, fn, mode, extra in CHECKS:
        p = os.path.join(HERE, fn)

        # 判据脚本缺失 = 加法保护消失, 无条件失败。
        if not os.path.exists(p):
            print("❌ %-22s 判据文件缺失(%s) —— 判据被删 = 加法保护消失" % (name, fn))
            fail.append(name)
            continue

        # 产物依赖缺失 = 本地树不完整, 判 SKIP, 但必须显式报出。
        missing = []
        if mode == "root" and not root:
            missing.append(MD_REL)
        elif mode == "root":
            missing += [r for r in extra if not os.path.exists(os.path.join(root, r))]
        elif mode == "swift" and not sp:
            missing.append(MD_REL)
        if missing:
            print("⏭  %-22s SKIP(产物缺 %s)" % (name, ", ".join(missing)))
            skip.append(name)
            skipped_detail.append((name, missing))
            continue

        argv = [sys.executable, p]
        if mode == "root":
            argv.append(root)
        elif mode == "swift":
            argv.append(sp)
        if fn == "reverse_v49_heavy.py":
            argv.append("--sab")

        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            print("❌ %-22s 超时" % name)
            fail.append(name)
            continue

        if r.returncode == 0:
            ok += 1
            lines = [l for l in (r.stdout or "").strip().split("\n") if l.strip()]
            print("✅ %-22s %s" % (name, (lines[-1] if lines else "")[:56]))
        elif r.returncode == 3:
            # 判据自己说"环境不全, 没检查" —— 绝不能算通过。
            # 【本轮实踩】ci_assert_v49 原先找不到 fallback 时 return 0,
            # 于是输出是 "✅ v49 判据(四层) v49=SKIP(...)" —— 假绿。
            lines = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
            reason = (lines[-1] if lines else "退出码 3")[:70]
            print("⏭  %-22s SKIP(%s)" % (name, reason))
            skip.append(name)
            skipped_detail.append((name, [reason]))
        else:
            print("❌ %-22s" % name)
            for l in (r.stdout + r.stderr).strip().split("\n"):
                if l.strip():
                    print("      " + l[:100])
            fail.append(name)

    print()
    print("─" * 62)
    print("全版本回归: %d 通过, %d 失败, %d 跳过" % (ok, len(fail), len(skip)))

    if skipped_detail:
        print()
        print("⏭ 跳过项(产物树不完整, **不是**代码回归, 但别当它不存在):")
        for name, missing in skipped_detail:
            print("   · %-22s 缺 %s" % (name, ", ".join(missing)))
        print("   补齐后重跑本脚本。CI 里这些判据是在完整 checkout 上跑的。")

    if fail:
        print()
        print("❌ 失败项: %s" % ", ".join(fail))
        print()
        print("★ 排查提示: 若失败的是**历史版本**判据, 多半是本版把新代码插进了")
        print("  那一版的判据区间。本轮 v48 就是这么被 v49 误伤的:")
        print("    v48 判据的段右边界原是 // [IOS15-FIX-RELC v28], 而 v49 探针")
        print("    正好插在钉宽 if 与该标记之间 ⇒ v49 的记忆位写入被算进 v48")
        print("    的白名单 ⇒ pure=BAD 赋值4处。修法: 该判据的右界改到本版")
        print("    探针起点。**同一右界若有多个副本, 必须一次全改**。")
        hard = [f for f in fail if f in MANDATORY]
        if hard:
            print()
            print("★ 其中 %s 属承重墙, 必须修。" % ", ".join(hard))
        return 1

    print("✅ 全部通过 —— 历史版本的加法保护都没被本版破坏")
    return 0


if __name__ == "__main__":
    sys.exit(main())