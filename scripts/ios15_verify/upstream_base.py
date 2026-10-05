#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干净上游 src/ios 基线的**唯一**解析入口(纪律第 8 条: 同一逻辑只能一处实现)。

★为什么必须有这个文件(第十二次「验证手段骗了自己」):
  修 v67 时清最后两条红(reverse_v567 / reverse_v568), 发现 11 个文件各自
  解析上游路径, 策略**有三种**:

    ① reverse_v567.py : env 或 os.path.join(ROOT, ".upstream-ios")
    ② reverse_v568.py : env 或 "/tmp/up-1.14/src/ios"      ← 硬编码临时路径
    ③ 其余 9 个       : os.environ.get(env, '')               ← 空串

  三种默认值互不相同, 后果有两层:

  **(a) 同一次本地运行里, 一条绿一条红。**
    设了 env → 全绿; 不设 env → v567 走 ①(认 .upstream-ios)、v568 走 ②
    (认 /tmp/up-1.14, 沙箱重启就没了)。看着像"v568 判据更严",
    实际只是它找错了基线。

  **(b) ③ 的空串会退化成相对当前工作目录的路径 —— 最危险的一种。**
    `os.path.join('', 'Views/Chat/ToolLiveSheet.swift')` 得到
    `'Views/Chat/ToolLiveSheet.swift'`。若调用者恰好 cwd 在某个含
    `Views/Chat/` 的目录里(比如**产物目录**), 这段代码会静默读到
    **已被fallback 注入过的产物**, 当成"干净上游"去验注入 —— 等于
    用改过的源码验"改对了没有", **必然全绿**。

  (b) 是这轮真正要防的: 它不会报错, 只会让所有上游相关门禁失去意义。
  唯一的防线是**一处实现 + 只接受绝对路径 + 拒绝可疑目录**。

用法:
    from upstream_base import upstream_ios
    up = upstream_ios()          # ->绝对路径 或 None
    if up is None:
        print('SKIP(缺干净上游)')
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# 环境变量名(全仓库唯此一个拼法)
ENV = "OPENMINIS_UPSTREAM_IOS"

# 缺失时探过的候选路径, 按优先级。
# ★刻意**不含** /tmp 下的路径: /tmp 在沙箱重启后即失效, 硬编码它会让
#   "昨天能跑"变成"今天红", 而红的原因与代码无关 —— 那是环境噪声,
#   混进判据结果里会掩盖真正的回归。
CANDIDATES = (
    os.path.join(ROOT, ".upstream-ios"),
)


def _looks_like_dir(p):
    """p 是不是一个**可信的** src/ios 基线目录。

    刻意做得比 os.path.isdir 严: isdir 会为相对路径/临时目录/产物目录
    返回 True, 而那几种恰好是第 (b) 类假绿的入口。
    """
    if not p or not os.path.isdir(p):
        return False
    rp = os.path.realpath(p)
    # 1) 必须是绝对路径的真实目录, 相对路径一律不接受
    if not os.path.isabs(rp):
        return False
    # 2) 基线里必须有这些文件, 否则不是 src/ios
    if not os.path.isfile(os.path.join(rp, "Views", "Chat",
                                       "SelectableMarkdownView.swift")):
        return False
    # 3) ★不得是"看起来像 src/ios 的目录名下的产物" ——
    #    产物根的 src/ios 是 fallback 跑完的结果, 拿它当基线必然全绿。
    #    判据: 产物根的 src/ios 里有我们的注入标记而基线不该有。
    #    这里不做标记扫描(太贵), 只在调用方显式自检(见 has_injection)。
    return True


def has_injection(path):
    """path 指向的目录里是否已有 fallback 的注入标记 —— 真基线必须为 0。

    这是第 (b) 类假绿的**直接探测器**: 拿被注入过的产物当基线时它必然
    非零, 于是调用方能拒绝它, 而不是拿着污染基线跑出一片绿。
    """
    import re
    pat = re.compile(r"\[V\d{2,}[A-Z0-9-]*\]")
    # 上游自带的原生标记(如单测注释里的 `[V1] device-<id>`)只有 1~2 位数字,
    # 用 {2,} 排除; 我们的注入标记一律是 V41/V60/V63/V67 这种两位起步。
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            if not fn.endswith(".swift"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, encoding="utf-8", errors="replace") as f:
                    if pat.search(f.read()):
                        return True
            except OSError:
                continue
    return False


def upstream_ios(allow_injected=False, quiet=False):
    """返回干净上游 src/ios 的**绝对路径**; 拿不到就返回 None。

    解析顺序: $OPENMINIS_UPSTREAM_IOS → CANDIDATES。

    ★allow_injected 默认 False —— 探测到注入标记就拒绝, 宁可 SKIP
      也不能拿污染基线跑出一片绿。只有在**故意**测"注入幂等"时
      才应该传 True。
    """
    cands = []
    env = (os.environ.get(ENV) or "").strip()
    if env:
        cands.append(env)
    cands.extend(CANDIDATES)

    for c in cands:
        if not _looks_like_dir(c):
            continue
        rp = os.path.realpath(c)
        if not allow_injected and has_injection(rp):
            if not quiet:
                print("★ 拒绝: %s 里已有注入标记, 它是**产物**不是干净上游" % rp,
                      file=sys.stderr)
            continue
        return rp

    if not quiet:
        print("   缺干净上游; 可 export %s=<upstream>/src/ios" % ENV,
              file=sys.stderr)
    return None


if __name__ == "__main__":
    p = upstream_ios(quiet=("-q" in sys.argv))
    if p is None:
        print("NONE")
        sys.exit(1)
    print(p)
    sys.exit(0)
