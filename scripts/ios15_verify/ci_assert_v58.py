#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v58 判据(CI 入口): 纠偏之后**必须重排** —— 卡字/掉帧的总闸门。

跑法: ci_assert_v58.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49~v565 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core = fallback 内 verify_kvo_reflow_v58 的 6 层
    scope= 外部独立判据(reverse_v58.py 的 judge) + 编译级快检
    sab  = reverse_v58.py 的 8 条 sabotage 必须全被拦, 且基线不误伤

【为什么 core 与 scope 要**两份**判据】
  core 直接 import fallback 的 verify。若只有它, 那 verify 里的锚点串一旦与
  注入串一起被改坏, 两边一起绿 —— 自己验自己。
  scope 这份**刻意不 import fallback**: 从干净上游重跑 fallback 拿产物,
  再用手写在 reverse_v58.py 里的字面量去判。
  本版实测: core 最初有 4 个洞(F1/F2/F3 分不开、复合赋值 `+=` 溜过、
  白名单 endswith 放行 frame.height、切片越过整个诊断块), 全部是
  **靠 scope 的 8 条 sabotage 抓出来的** —— 只跑 core 的话这四条会一路绿到 CI。

【CI 上 sab 的特殊约束】
  reverse_v58.py 需要**干净上游**当基线(fallback 跑过之后产物已被移植,
  自己拷自己当基线等于永远绿)。CI 里干净上游在第 153 行那步另存为
  .upstream-ios, 本入口靠 OPENMINIS_UPSTREAM_IOS 拿; 拿不到判 SKIP
  (退出码 3)并显式报出, **绝不假装通过**。
"""
import io
import os
import re
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

HERE = os.path.dirname(os.path.abspath(__file__))
MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
INFRA_REL = "src/ios/Agent/MessageList/MessageListInfrastructure.swift"


def _fallback_path(root):
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
    """从 SelectableMarkdownView.swift 反推产物根目录(锚点探测, 不数层数)。

    ★沿用 v53 的教训: 固定 3 层 dirname 只会退到 <root>/src/ios,
      于是 fallback 路径永远不存在, 入口会静默换掉被测对象。
    """
    d = os.path.dirname(os.path.abspath(md))
    while True:
        if os.path.exists(os.path.join(d, INFRA_REL)):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


# ---------------------------------------------------------------
# NSLog 格式串/实参拆解(从 ci_assert_v565.py 借来的**已验证**实现)
# ---------------------------------------------------------------
# ★两个已实测的坑, 照抄时不要"简化"★:
#   1) 格式串是**跨行拼接**的(`"..." + "..."`), 所以第一个「实参区域」里
#      夹着 `+ "..."` 续行。不能按「第一个字面量的闭合引号」当实参起点
#      —— 那样续行被算成第一个实参, 实参数虚高 1(基线直接误报红)。
#   2) 切分深度要相对 **NSLog 自己那层括号**: call 以 `NSLog(` 开头时,
#      那层括号已被消耗, `Double(x)` 里的括号是下一层, 其内部逗号不切;
#      只有深度 1 上的逗号才是实参分隔。
def refind_literals(call):
    """抽出所有顶层字符串字面量的内容并拼成完整格式串。"""
    lits = []
    in_s = False
    cur = []
    i = 0
    while i < len(call):
        c = call[i]
        if in_s:
            if c == "\\" and i + 1 < len(call):
                cur.append(call[i + 1])
                i += 2
                continue
            if c == '"':
                in_s = False
                lits.append("".join(cur))
            else:
                cur.append(c)
        else:
            if c == '"':
                in_s = True
        i += 1
    return lits


def fmt_args(call):
    op = call.find("(")
    if op < 0:
        return []
    depth = 0
    in_s = False
    chunks = []
    cur = []
    i = op
    while i < len(call):
        c = call[i]
        if in_s:
            if c == "\\":
                cur.append(call[i:i + 2])
                i += 2
                continue
            if c == '"':
                in_s = False
            cur.append(c)
        else:
            if c == '"':
                in_s = True
                cur.append(c)
            elif c == "(":
                depth += 1
                cur.append(c)
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
                cur.append(c)
            elif c == "," and depth == 1:
                chunks.append("".join(cur))
                cur = []
            else:
                cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail:
        chunks.append(tail)
    # chunks[0] 是格式串区域(含 `+ "..."` 续行), 不是实参
    return [c.strip() for c in chunks[1:]]


# ---------------------------------------------------------------
# scope: 编译级快检(v58 专属, 与 core/sab 都不同)
# ---------------------------------------------------------------
# v58 诊断里必须保持 %.1f 的三个几何槽标签。
# ★标签用元组逐个列出, 不在源码里拼成格式串★ —— 纪律54 的教训:
#   判据源码里的字面量同样会被别的判据的 `find`/`replace` 当成锚点。
#   而 "netW=%.1f" 这种串一旦写死, 改它就等于改判据自身的锚点。
_GEOM_TAGS = ("netW", "tcW", "needH")


def _geom_slot_idxs(fmt, args):
    """返回落在几何标签上的槽索引集合。

    做法: 逐槽扫描格式串, 记下每个槽**前面最近的** `标签=`(NSLog 的标签与
    槽一一对应, 所以向前找最近的 `xxx=` 就是该槽的标签)。
    ★真的从 fmt 读标签, 不用固定索引★ —— 固定索引会在有人调整槽序后
    静默错位, 变成一条"看着在管、其实管的是别的槽"的假判据。
    """
    idxs = set()
    slot_no = -1
    last_tag = None
    i = 0
    while i < len(fmt):
        c = fmt[i]
        if c == '%':
            m = re.match(r"%[-+ #0-9.]*[a-zA-Z]", fmt[i:])
            if m:
                slot_no += 1
                if last_tag in _GEOM_TAGS:
                    idxs.add(slot_no)
                i += m.end()
                continue
            i += 1
            continue
        # 标签形如 `netW=` / `tcW=`
        m2 = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", fmt[i:])
        if m2:
            last_tag = m2.group(1)
            i += m2.end()
            continue
        i += 1
    return idxs


def scope_check(t):
    """只做**编译会失败**级别的检查 —— 判据超范围报红比不报更坏。"""
    bad = []

    # ① invalidateLayout 的实参里每个槽都要有对应实参(v28 段已验证的形态)
    i = t.find('NSLog("[V58-REFLOW]')
    if i < 0:
        bad.append("找不到 [V58-REFLOW] 日志点")
        return bad
    k = t.find("NSLog(", i)
    op = t.find("(", k)
    depth = 0
    end = -1
    for j in range(op, len(t)):
        if t[j] == "(":
            depth += 1
        elif t[j] == ")":
            depth -= 1
            if depth == 0:
                end = j
                break
    if end < 0:
        bad.append("v58 的 NSLog( 括号不配平 —— 编译会失败")
        return bad
    call = t[k:end + 1]
    lits = refind_literals(call)
    fmt = "".join(lits)
    slots = re.findall(r"%[-+ #0-9.]*[a-zA-Z]", fmt)
    args = fmt_args(call)
    if len(slots) != len(args):
        bad.append("v58 日志格式串 %d 个槽位但传了 %d 个实参 —— 编译会失败"
                   % (len(slots), len(args)))
    else:
        geom = _geom_slot_idxs(fmt, args)
        # ★槽位类型对齐: 只拦**确定的编译错**, 不做风格要求★
        #   实测依据: 本文件里 v50 段([V50-UNIFY] used=%.1f …)与 v58 段一样
        #   直接把 CGFloat 变量喂给 %.1f, 连包 20 多版都编译通过 ⇒ CGFloat
        #   在 64 位上与 Double 同布局, Swift 的 CVarArg 桥接吃得下。
        #   ⇒ 纪律: 判据只拦"真编译不过"的, 风格统一由 code review 负责。
        #     判据超范围报红比不报更坏 —— 一次假红就会让人整体不信这个门。
        for idx, (sl, ar) in enumerate(zip(slots, args)):
            base = sl.lstrip("%-+ #0123456789.*")
            if base in ("d", "i", "u", "x", "X", "o"):
                # 整数槽收浮点: Double 实参过 %d 在 Swift 里是**确定的编译错**
                if ar.startswith("Double(") or ar.startswith("Float("):
                    bad.append("第 %d 个槽位 `%s` 是整数格式, 实参却是 %s —— 编译错"
                               % (idx + 1, sl, ar[:30]))
            elif base in ("f", "e", "E", "g", "G"):
                if sl not in ("%.1f", "%.0f"):
                    bad.append("第 %d 个槽位 `%s` 精度不是 %%.1f —— v58 要读的"
                               "就是净宽与高度, 丢精度等于探针白写" % (idx + 1, sl))
                elif sl == "%.0f" and idx in geom:
                    bad.append("第 %d 个槽位落在几何标签上却是 %%.0f —— "
                               "358.0 与 358 会被混为一谈, 纠偏到 358.4 时"
                               "日志显示 358 ⇒ 误判「已到位」" % (idx + 1))
    # ② CACurrentMediaTime 必须在 QuartzCore 可用范围(已随 UIKit 链引入)
    if "CACurrentMediaTime()" not in t:
        bad.append("v58 诊断用 CACurrentMediaTime 但产物里没有该调用 —— "
                   "节流器失效(每帧都打日志 ⇒ 掉帧)")
    # ③ 节流间隔必须是常量 0.5, 不能是 0(否则每帧打日志)
    mthr = re.search(r"_v58Now - _V58Log\.last > ([0-9.]+)", t)
    if not mthr:
        bad.append("找不到 v58 的节流阈值比较")
    else:
        try:
            v = float(mthr.group(1))
        except ValueError:
            v = -1.0
        if v <= 0:
            bad.append("v58 节流阈值 = %s ≤ 0 ⇒ 每帧打日志 ⇒ 掉帧" % mthr.group(1))
        elif v < 0.1:
            bad.append("v58 节流阈值 = %s 过小(建议 ≥0.1s) ⇒ 日志本身成为掉帧源"
                       % mthr.group(1))
    return bad


def main():
    if len(sys.argv) < 2:
        print("用法: ci_assert_v58.py <产物根目录 或 SelectableMarkdownView.swift>")
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

    t = io.open(md, encoding="utf-8").read()
    print("产物: %s (%d)" % (os.path.basename(md), len(t)))

    ok = True

    # ---- core: fallback 内的 6 层 ----
    fb = _fallback_path(root)
    if not os.path.exists(fb):
        print("core=SKIP(找不到 scripts/ios15_fallback.py)")
        return 3
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v58", fb)
    try:
        fbv = importlib.util.module_from_spec(spec)
        # 禁掉 __main__ 副作用: 只想拿函数, 不想让它跑注入
        spec.loader.exec_module(fbv)
    except Exception as e:
        print("  core 6层 BAD(fallback 加载失败: %s)" % e)
        return 1
    fn = getattr(fbv, "verify_kvo_reflow_v58", None)
    if fn is None:
        print("  core 6层               BAD(判据函数缺失: verify_kvo_reflow_v58)")
        ok = False
    else:
        try:
            fn(t)
            print("  core 6层               OK  (标记/块内重排/全量实参/"
                  "诊断零副作用/纪律54/纪律55)")
        except Exception as e:
            print("  core 6层               BAD %s" % e)
            ok = False

    # ---- scope: 编译级 ----
    bad = scope_check(t)
    if bad:
        ok = False
        print("  scope 编译级            BAD")
        for b in bad:
            print("        · %s" % b)
    else:
        print("  scope 编译级            OK  (槽位对齐/节流阈值 ≥0.1s)")

    # ---- sab: 8 条 sabotage ----
    up = upstream_ios(quiet=True)
    sb = os.path.join(HERE, "reverse_v58.py")
    if "--no-sab" in sys.argv:
        print("  sab 反向(8条)           SKIP(--no-sab)")
    elif not up or not os.path.isdir(up):
        print("  sab 反向(8条)           SKIP(缺干净上游, 设 OPENMINIS_UPSTREAM_IOS)")
        print("     ★SKIP 不等于通过 —— 反向测试没跑 = 没人证明判据拦得住")
    elif not os.path.exists(sb):
        print("  sab 反向(8条)           BAD(缺 reverse_v58.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sb], capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        summ = [l for l in tail if "v58 反向:" in l]
        print("  sab 反向(8条)           %s %s"
              % ("OK" if r.returncode == 0 else "BAD",
                 summ[-1][:70] if summ else ""))
        if r.returncode != 0:
            ok = False
            for l in tail[-12:]:
                print("        · %s" % l[:100])

    # ---- scope 自证(scope 层是本版新写的, 必须先证明它会红) ----
    # ★v46 的教训: 判据全绿不代表它在测对的东西。scope 层没有任何历史包袱,
    #   但那不代表它可信 —— 不做反向测试, 它和 v46 那些一直全绿的判据是
    #   同一种东西: 没人证明它拦得住任何东西。
    # ★v565 已经吃过一次亏: 它的 scope 层第一版只数槽位个数, 把 %.1f 改成
    #   %.0f 直接漏过(槽位数不变) —— 逐槽位类型对齐就是被它逼出来的。
    sc = os.path.join(HERE, "selfcheck_scope_v58.py")
    if not os.path.exists(sc):
        print("  scope自证(5条)            BAD(缺 selfcheck_scope_v58.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sc, target],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        line = [l for l in tail if "自证:" in l]
        print("  scope自证(5条)            %s %s"
              % ("OK" if r.returncode == 0 else "BAD",
                 line[-1][:70] if line else ""))
        if r.returncode != 0:
            ok = False
            for l in tail[-10:]:
                print("        · %s" % l[:100])

    print("v58=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
