#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v565 判据(CI 入口): 终端框 [V565-CODEBLOCK] 探针 —— 含本项目第一条**覆盖范围**判据。

跑法: ci_assert_v565.py <产物根目录 或 SelectableMarkdownView.swift 路径>

退出码约定(与 v49~v53 一致, **SKIP 绝不算通过**):
    0 = 真通过
    1 = 真失败
    3 = 无法检查(环境不全)

层次:
    core = fallback 内 verify_diag_codeblock_v565(9 类判据)
    scope= 编译级检查(只读量类型 / 诊断段零副作用 / NSLog 变参实参个数与类型)
    sab  = reverse_v565.py 的 9 条 sabotage 必须全被拦, 且基线不误伤

【本入口为什么必须存在 —— 一条判据都跑不出来的探针比没有探针更坏】
  v46 的 [V46-ATTACH] 在 TableAttachment 里, 对同为 NSTextAttachment 子类的
  CodeBlockAttachment **完全失明**, 而它的全部判据(标记唯一 / 段内零赋值 /
  花括号平衡)一直全绿。
  ⇒ 「判据全绿」≠「探针在测正确的东西」。这两件事没有任何蕴含关系。
  ⇒ 所以 v565 的第 2 条判据**正向钉死宿主类名**: 日志点必须落在
    `final class CodeBlockAttachment` 与下一个顶层 `final class` 之间。
  ⇒ 而这一条本身也要被反向测试(SA1 故意把探针挪进 TableAttachment,
    判据必须红) —— 否则「覆盖范围判据」也可能只是又一条自说自话的绿。

【S2 补出来的真洞: 声明 ≠ 写入】
  最初第 3 条只查 `"attV565ViewH" in t`(出现过即可)。反向测试 S2 删掉
  makeView 里那两行**赋值**后, 字段声明与诊断段里的**读**都还在, 判据照样全绿,
  而 viewH 恒 -1 等于探针没测到东西。
  ⇒ 补 3b: 查**赋值语句** `attV565ViewH =` 且必须落在 container.frame 之后。
  ⇒ 纪律: 判据要查**赋值点**, 不是查名字出现过。

【CI 上 sab 的特殊约束】
  reverse_v565.py 需要**干净上游**当基线(fallback 跑过之后产物已被移植,
  自己拷自己当基线等于永远绿)。CI 里干净上游在第 153 行那步被 fallback
  覆盖掉了, 所以本入口靠 OPENMINIS_UPSTREAM_IOS 环境变量拿;
  拿不到就判 SKIP(退出码 3)并显式报出, **绝不假装通过**。
"""
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

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
    """从 SelectableMarkdownView.swift 反推产物根目录(锚点探测, 不数层数)。

    ★沿用 v53 的教训: 固定 3 层 dirname 只会退到 <root>/src/ios,
      于是 fallback 路径永远不存在, 三个入口一直是靠兜底候选活着的 ——
      一旦判据被拷到别处运行, 就会静默换掉被测对象。
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
# scope: 编译级检查(v565 专属)
# ---------------------------------------------------------------
# v565 在产物里注入的东西只有三类:
#   1) 两个 var 字段 (attV565ViewH / attV565ViewW)
#   2) 一个只读访问器 (attV565CachedRaw) + 一个只读计算量 (attV565LineCount)
#   3) attachmentBounds 里一个 do { ... } 诊断块 + makeView 里两行赋值
# 编译风险点全在这三类上, 不在别处。

# 注入的只读量必须是这些精确类型 —— 类型写错(如 Int vs CGFloat)会让
# Double(...) 转换或比较运算符解析失败。
SCOPE_TYPES = (
    ("var attV565ViewH: CGFloat = -1", "attV565ViewH 字段类型/初值"),
    ("var attV565ViewW: CGFloat = -1", "attV565ViewW 字段类型/初值"),
    ("var attV565CachedRaw: CGFloat {", "attV565CachedRaw 必须是 CGFloat"),
    ("var attV565LineCount: Int {", "attV565LineCount 必须是 Int"),
)

# 诊断段里绝对不允许出现的调用/赋值 —— 它们会改变排版行为,
# 于是「诊断」本身成了变量, 装机读数全部不可信。
FORBIDDEN_IN_PROBE = (
    ("invalidateLayout", "触发重新布局"),
    ("setNeedsLayout", "触发重新布局"),
    ("setNeedsDisplay", "触发重绘"),
    ("layoutIfNeeded", "触发立即布局"),
    ("invalidateIntrinsicContentSize", "改变内在尺寸"),
    ("attachmentBounds", "递归调用自身"),
    ("measureCodeHeight", "调用测高(诊断段应只读缓存)"),
)

# NSLog 的格式串里声明了 %d 的槽位, 每个都必须有对应的实参,
# 且类型要能过 CVarArg —— 少一个就是编译错(多一个也是)。
# 这里查的是「格式串槽位数 == 实参个数」这一条最容易错的关系。
FMT_TAGS = ("%.1f", "%d", "%u")


def _fmt_slots(fmt):
    """按顺序列出格式串里的每个转换说明符(排除 %%)。

    ★v565 scope 层的 B5 sabotage 逼出来的教训:
      **只数槽位个数不够** —— `%.0f` 换成 `%.1f` 槽位数不变,
      但打印出来的高度会丢掉小数, 而 v565 存在的全部意义就是读小数高度账。
      ⇒ 必须把每个槽位的**种类和类型**一起对齐到实参。
    """
    out = []
    i = 0
    while i < len(fmt):
        if fmt[i] == "%":
            j = i + 1
            while j < len(fmt) and fmt[j] in "+-# 0123456789.*":
                j += 1
            if j < len(fmt) and fmt[j] in "diouxXfeEgGcsp@%":
                if fmt[j] != "%":
                    out.append(fmt[i:j + 1])
                i = j + 1
                continue
        i += 1
    return out


def _fmt_args(call):
    """把 NSLog 的实参按**本调用的括号内**顶层逗号切开, 返回 [实参...]。

    ★两个都是实际踩过的坑:
      1) 格式串是**跨行拼接**的(`"..." + "..."`), 所以第一个「实参区域」里
         夹着 `+ "..."` 续行。不能按「第一个字面量的闭合引号」当实参起点
         —— 那样续行被算成第一个实参, 实参数虚高 1(基线直接误报红)。
      2) 切分深度要相对 **NSLog 自己那层括号**: call 以 `NSLog(` 开头时,
         那层括号已被消耗, `Double(x)` 里的括号是下一层, 其内部逗号不切;
         只有深度 1 上的逗号才是实参分隔。
    """
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
    out = []
    for c in chunks[1:]:
        out.append(c.strip())
    return out


def scope_check(t):
    bad = []

    for sig, desc in SCOPE_TYPES:
        if sig not in t:
            bad.append("缺少或类型不对: %s  (期望 `%s`)" % (desc, sig))

    # ---- 诊断段切片: 从 do 块起, 花括号配平到闭合 ----
    i_log = t.find('NSLog("[V565-CODEBLOCK]')
    if i_log < 0:
        bad.append("找不到 [V565-CODEBLOCK] 日志点")
        return bad

    i_do = t.rfind("do {", 0, i_log)
    if i_do < 0:
        bad.append("日志点之前没有 do { 包裹")
        return bad

    # 花括号配平(跳过字符串内的括号 —— 日志格式串里没有花括号, 但严谨些)
    depth = 0
    end = -1
    in_str = False
    i = t.find("{", i_do)
    while i >= 0:
        c = t[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1
    if end < 0:
        bad.append("do 块花括号不配平")
        return bad
    seg = t[i_do:end]

    for kw, why in FORBIDDEN_IN_PROBE:
        if kw in seg:
            bad.append("诊断段内出现 %s (%s) —— 诊断必须零副作用" % (kw, why))

    # 诊断段内不得对高度做任何赋值
    for ln in seg.split("\n"):
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("let ") or s.startswith("var "):
            continue
        if "=" in s and "==" not in s and "!=" not in s and ">=" not in s \
                and "<=" not in s and s.startswith(("height", "totalHeight",
                                                    "scrollHeight", "contentHeight",
                                                    "maxCodeHeight", "width")):
            bad.append("诊断段内改了排版量: %s" % s[:70])

    # ---- 格式串槽位数 == 实参个数 ----
    # ★必须从**本日志点自己的 NSLog(** 起做括号配平, 不能用
    #   `t.find("NSLog(", i_log - 40)` —— 文件里 NSLog 有几十处,
    #   向前找到的必然是某个无关的调用, call 抓飞 ⇒ 实参数虚高。
    #   同理也不能用 `t.find(");")` 收尾: 跨行拼接的实参里可能带 `);`。
    k = t.find("NSLog(", i_log)
    if k < 0:
        bad.append("日志点处找不到 NSLog(")
        return bad
    op = t.find("(", k)
    depth2 = 0
    in_s2 = False
    end_call = -1
    i = op
    while i < len(t):
        c = t[i]
        if in_s2:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_s2 = False
        else:
            if c == '"':
                in_s2 = True
            elif c == "(":
                depth2 += 1
            elif c == ")":
                depth2 -= 1
                if depth2 == 0:
                    end_call = i
                    break
        i += 1
    if end_call < 0:
        bad.append("NSLog( 括号不配平")
        return bad
    call = t[k:end_call + 1]

    # 抽出所有顶层字符串字面量拼成完整格式串(编译器把相邻字面量合并)
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
                cur = []
                i += 1
                continue
            cur.append(c)
        else:
            if c == '"':
                in_s = True
        i += 1

    fmt = "".join(lits)
    slots = _fmt_slots(fmt)
    args = _fmt_args(call)
    if len(slots) != len(args):
        bad.append("NSLog 格式串有 %d 个槽位但传了 %d 个实参 —— 编译会失败"
                   % (len(slots), len(args)))
    else:
        # ---- 逐槽位类型对齐 ----
        # %.1f 只接受 Double(...) / Float(...) 包装过的实参;
        # %d/%u 只接受整数; 精度不是 .1f 的浮点槽位一律拒绝(读数会丢小数)。
        for idx, (sl, ar) in enumerate(zip(slots, args)):
            base = sl.lstrip("%-+ #0123456789.*")
            if base in ("f", "e", "E", "g", "G"):
                if sl != "%.1f":
                    bad.append("第 %d 个槽位 `%s` 精度不是 %%.1f —— "
                               "v565 要读的就是小数高度, 丢精度等于探针白写"
                               % (idx + 1, sl))
                if not (ar.startswith("Double(") or ar.startswith("Float(")
                        or ar.endswith(".0") or ar.endswith(".0)")):
                    bad.append("第 %d 个槽位 `%s` 的实参 `%s` 未包 Double() —— "
                               "CGFloat/Int 过 NSLog 的 %%.1f 会编译错"
                               % (idx + 1, sl, ar[:40]))
            elif base in ("d", "i", "u", "x", "X", "o"):
                if ar.startswith("Double(") or ar.startswith("Float("):
                    bad.append("第 %d 个槽位 `%s` 是整数格式, 实参却是 %s —— "
                               "编译错" % (idx + 1, sl, ar[:30]))

    return bad


def main():
    if len(sys.argv) < 2:
        print("用法: ci_assert_v565.py <产物根目录 或 SelectableMarkdownView.swift>")
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

    t = open(md, encoding="utf-8").read()
    print("产物: %s (%d)" % (os.path.basename(md), len(t)))

    ok = True

    # ---- core ----
    fb = _fallback_path(root)
    if not os.path.exists(fb):
        print("core=SKIP(找不到 scripts/ios15_fallback.py)")
        return 3
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v565", fb)
    fbv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fbv)
    fn = getattr(fbv, "verify_diag_codeblock_v565", None)
    if fn is None:
        print("  core 覆盖范围+结构         BAD(判据函数缺失: verify_diag_codeblock_v565)")
        ok = False
    else:
        try:
            fn(t)
            print("  core 覆盖范围+结构         OK  (含本项目第一条覆盖范围判据)")
        except Exception as e:
            print("  core 覆盖范围+结构         BAD %s" % e)
            ok = False

    # ---- scope ----
    bad = scope_check(t)
    if bad:
        ok = False
        print("  scope 编译级               BAD")
        for b in bad:
            print("        · %s" % b)
    else:
        print("  scope 编译级               OK  (类型/零副作用/逐槽位对齐)")

    # ---- scope 自证(scope 层是新写的, 必须先证明它会红) ----
    # ★v46 的教训: 判据全绿不代表它在测对的东西。scope 层是 v565 新写的,
    #   没有任何历史包袱, 但那不代表它就可信 —— 不做反向测试, 它和 v46
    #   那些一直全绿的判据是同一种东西: 没人证明它拦得住任何东西。
    # ★实测已经证明这个担心是对的: 第一版只数槽位个数, B5(`%.1f`→`%.0f`)
    #   直接漏过 —— 槽位数不变, 但打印出来的高度会丢小数, 而 v565 存在的
    #   全部意义就是读小数高度账。逐槽位类型对齐就是被它逼出来的。
    sc = os.path.join(HERE, "selfcheck_scope_v565.py")
    if not os.path.exists(sc):
        print("  scope自证(7条)             BAD(缺 selfcheck_scope_v565.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sc, root],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        line = [l for l in tail if "自证:" in l]
        print("  scope自证(7条)             %s %s"
              % ("OK" if r.returncode == 0 else "BAD",
                 line[-1][:70] if line else ""))
        if r.returncode != 0:
            ok = False
            for l in tail[-10:]:
                print("        · %s" % l[:100])

    # ---- sab ----
    up = upstream_ios(quiet=True)
    sb = os.path.join(HERE, "reverse_v565.py")
    if "--no-sab" in sys.argv:
        print("  sab 反向(9条)              SKIP(--no-sab)")
    elif not up or not os.path.isdir(up):
        print("  sab 反向(9条)              SKIP(缺干净上游, 设 OPENMINIS_UPSTREAM_IOS)")
        print("     ★SKIP 不等于通过 —— 反向测试没跑 = 没人证明判据拦得住")
    elif not os.path.exists(sb):
        print("  sab 反向(9条)              BAD(缺 reverse_v565.py)")
        ok = False
    else:
        r = subprocess.run([sys.executable, sb, fb, up],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
        print("  sab 反向(9条)              %s %s"
              % ("OK" if r.returncode == 0 else "BAD",
                 [l for l in tail if "反向:" in l][-1][:70] if
                 [l for l in tail if "反向:" in l] else ""))
        if r.returncode != 0:
            ok = False
            for l in tail[-12:]:
                print("        · %s" % l[:100])

    print("v565=%s" % ("OK" if ok else "BAD"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())