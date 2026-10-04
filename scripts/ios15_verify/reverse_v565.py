#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V565 探针的 sabotage 反向测试: 证明 verify_diag_codeblock_v565 真的能拦。

【为什么必须有这个脚本】
v46 探针的历史教训: 它装在 TableAttachment 里, 对同为 NSTextAttachment
子类的 CodeBlockAttachment **完全失明**, 而它的全部判据(标记唯一 / 段内
零赋值 / 括号平衡) 一直全绿。

⇒ 「判据全绿」与「探针在测正确的东西」是两件完全不同的事。
⇒ 所以 V565 除了常规判据, 必须额外做**覆盖范围**判据(宿主类名),
   而这一条本身也要被反向测试: 故意把探针挪到别的类里, 判据必须红。

本脚本注入 8 类 sabotage, 逐条确认判据拦下:
  S1 探针装到 TableAttachment 里(复刻 v46 的失败形态)  -> 覆盖范围判据
  S2 删掉 makeView 侧回写(attV565ViewH 永 -1)          -> 量的完整性判据
  S3 访问器带 setter                                     -> 只读判据
  S4 诊断段内改高度(height = ...)                        -> 零赋值判据
  S5 诊断段内 invalidateLayout()                         -> 禁用调用判据
  S6 去掉 0.5s 节流                                      -> 节流判据
  S7 do 块与 return CGRect 之间夹逻辑                     -> 紧贴判据
  S8 删掉整个日志点                                      -> 唯一性判据

用法: python3 reverse_v565.py <fallback脚本> <干净上游 src/ios>
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FB = os.path.join(os.path.dirname(HERE), "ios15_fallback.py")


def _product(fb, upstream, tag):
    """跑一遍 fallback 拿产物(忽略它自身的 verify —— 要留给 sabotage 触发)。"""
    d = os.path.join(tag, "ios")
    shutil.copytree(upstream, d)
    # 先把 verify 调用摘掉, 否则 S1~S8 会在生成阶段就被判死,
    # 我们就测不到"判据能不能拦住"而只能测到"注入会不会炸"。
    src = open(fb, encoding="utf-8").read()
    patch = os.path.join(tag, "fb_noverify.py")
    open(patch, "w", encoding="utf-8").write(
        src.replace("    verify_diag_codeblock_v565(t)\n", "", 1))
    p = subprocess.run([sys.executable, patch, d], capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write("生成产物失败(干净基线都跑不通):\n%s\n"
                         % (p.stderr or p.stdout)[-1500:])
        return None
    return d


def _mutate_and_check(name, product, mutate, expect_kw, workdir):
    """把产物改坏, 单独跑 verify 段, 确认它报出含 expect_kw 的错。

    ★每个 case 必须用**自己的一份干净副本** ——
      共用同一份产物时, 前一个 case 的破坏会留在文件里, 后面的 case
      全部报同一个错。本脚本第一版就这么写的, 结果 8 个 case 里 7 个
      「报错了但不是预期的错」, 看起来像判据有洞, 其实是测试自己污染了自己。
      ⇒ **反向测试的每个 case 必须自隔离**, 否则测的不是判据, 是残留。
    """
    import shutil as _sh
    case_dir = os.path.join(workdir, "case_" + re.sub(r"\W+", "_", name)[:40])
    _sh.copytree(product, case_dir)
    md = os.path.join(case_dir, "Views/Chat/SelectableMarkdownView.swift")
    t = open(md, encoding="utf-8").read()
    t2 = mutate(t)
    if t2 == t:
        return (name, False, "★ sabotage 没改成 —— 判据白测了(锚点已变)")
    open(md, "w", encoding="utf-8").write(t2)
    # 只跑 verify_diag_codeblock_v565
    check = os.path.join(os.path.dirname(product), "only_verify.py")
    open(check, "w", encoding="utf-8").write(
        "import sys\n"
        "sys.path.insert(0, %r)\n" % os.path.dirname(fb_path_global)
        + "import importlib.util\n"
          "spec = importlib.util.spec_from_file_location('fb', %r)\n" % fb_path_global
        + "m = importlib.util.module_from_spec(spec)\n"
          "spec.loader.exec_module(m)\n"
          "t = open(%r, encoding='utf-8').read()\n" % md
        + "try:\n"
          "    m.verify_diag_codeblock_v565(t)\n"
          "    print('NO-ERROR')\n"
          "except RuntimeError as e:\n"
          "    print('RUNTIME-ERROR:', e)\n")
    p = subprocess.run([sys.executable, check], capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if "NO-ERROR" in out:
        return (name, False, "判据**没拦住**(应该报错却放行了)")
    if expect_kw in out:
        return (name, True, out.strip().split("\n")[0][:110])
    return (name, False, "报错了但不是预期的错, 期望含 %r, 实际: %s"
            % (expect_kw, out.strip()[:160]))


fb_path_global = None


def main():
    global fb_path_global
    if len(sys.argv) < 3:
        sys.stderr.write(__doc__)
        return 1
    fb = sys.argv[1] if os.path.exists(sys.argv[1]) else DEFAULT_FB
    upstream = sys.argv[2]
    fb_path_global = os.path.abspath(fb)
    if not os.path.isdir(upstream):
        sys.stderr.write("找不到干净上游: %s\n" % upstream)
        return 1

    base = tempfile.mkdtemp(prefix="v565rev_")
    ok, bad = [], []
    try:
        prod = _product(fb_path_global, upstream, base)
        if not prod:
            return 1
        md = os.path.join(prod, "Views/Chat/SelectableMarkdownView.swift")
        if "V565-CODEBLOCK" not in open(md, encoding="utf-8").read():
            print("❌ 干净基线里根本没有 V565 探针 —— 本脚本的锚点已失效")
            return 1

        # ---- S1 覆盖范围: 把日志点挪进 TableAttachment ----
        def s1(t):
            # ★必须按**行**切, 不能 rfind("NSLog(") ——
            #   NSLog 的实参是跨行拼接的字符串, 它前面一行是 "+" 的续行,
            #   rfind 找到的是**文件开头某个无关的 NSLog**, j 变 -1,
            #   整段被切飞。sabotage 脚本自己切错 = 白测。
            lines = t.split("\n")
            li = next(k for k, l in enumerate(lines)
                      if 'NSLog("[V565-CODEBLOCK]' in l)
            # 语句从 "NSLog(" 所在行起(该行以 + 续行, 往前找到以 NSLog 开头的行)
            lj = li
            while lj > 0 and not lines[lj].lstrip().startswith("NSLog("):
                lj -= 1
            le = li
            while ");" not in lines[le]:
                le += 1
            stmt = "\n".join(lines[lj:le + 1])
            rest = lines[:lj] + lines[le + 1:]
            t2 = "\n".join(rest)
            k = t2.find("final class TableAttachment")
            anchor = t2.find("    var needsViewRebuild: Bool = false", k)
            return t2[:anchor] + stmt + "\n" + t2[anchor:]

        # ---- S2 makeView 侧回写被删 ----
        def s2(t):
            # 删掉 makeView 侧的两行回写, viewH/viewW 字段声明留着(否则
            # 判据会先报"缺少 attV565ViewH"而不是这条, 报错方向不对)
            out = re.sub(r"[ \t]*attV565ViewH = [^\n]*\n", "", t, count=1)
            return re.sub(r"[ \t]*attV565ViewW = [^\n]*\n", "", out, count=1)

        # ---- S3 访问器带 setter ----
        def s3(t):
            return t.replace(
                "var attV565CachedRaw: CGFloat { cachedContentHeight?.height ?? -1 }",
                "var attV565CachedRaw: CGFloat = -1\n    var attV565CachedRawDidSet: CGFloat {\n"
                "        get { attV565CachedRaw }\n"
                "        set { attV565CachedRaw = newValue }\n    }", 1)

        # ---- S4 诊断段内改高度 ----
        def s4(t):
            i = t.find('NSLog("[V565-CODEBLOCK]')
            j = t.rfind("do {", 0, i)
            return t[:j + 4] + "\n            let _v565Bad = 1\n            height = _v565Bad" + t[j + 4:]

        # ---- S5 诊断段内 invalidateLayout ----
        def s5(t):
            i = t.find('NSLog("[V565-CODEBLOCK]')
            j = t.rfind("do {", 0, i)
            return t[:j + 4] + "\n                invalidateLayout()" + t[j + 4:]

        # ---- S6 去掉节流 ----
        def s6(t):
            return t.replace("_v565now - _V565Log.last > 0.5", "true", 1)

        # ---- S7 do 块与 return 之间夹逻辑 ----
        def s7(t):
            return t.replace("\n\n        return CGRect(x: 0, y: 0, width: width, height: height)",
                             "\n\n        let _v565Probe = 1\n\n"
                             "        return CGRect(x: 0, y: 0, width: width, height: height)", 1)

        # ---- S8 删掉整个日志点 ----
        def s8(t):
            # 整段(含 do 块)删掉, 只留注释 —— 注释里也有 "V565-CODEBLOCK",
            # 所以判据的日志点查找必须靠 'NSLog("[V565-CODEBLOCK]' 这个
            # **完整形态**; 只查裸标记名会被注释里的自述骗过。
            lines = t.split("\n")
            li = next(k for k, l in enumerate(lines)
                      if 'NSLog("[V565-CODEBLOCK]' in l)
            lj = li
            while lj > 0 and not lines[lj].lstrip().startswith("NSLog("):
                lj -= 1
            le = li
            while ");" not in lines[le]:
                le += 1
            return "\n".join(lines[:lj] + lines[le + 1:])

        cases = [
            ("S1 探针装进 TableAttachment(复刻 v46 失败形态)", s1, "不在 CodeBlockAttachment"),
            ("S2 删掉 makeView 侧回写(viewH 永 -1)", s2, "必须回写 attV565ViewH ="),
            ("S3 访问器带 setter", s3, "attV565CachedRaw"),
            ("S4 诊断段内改高度", s4, "纯诊断违规"),
            ("S5 诊断段内 invalidateLayout()", s5, "禁用项"),
            ("S6 去掉 0.5s 节流", s6, "0.5s 节流"),
            ("S7 do 块与 return 之间夹逻辑", s7, "紧贴 return CGRect"),
            ("S8 删掉整个日志点", s8, "未找到 V565 日志点"),
        ]
        for name, fn, kw in cases:
            r = _mutate_and_check(name, prod, fn, kw, base)
            (ok if r[1] else bad).append(r)

        # ---- 反向基准: 未改动的产物必须通过 ----
        base_dir = os.path.join(base, "case_BASE")
        shutil.copytree(prod, base_dir)
        md = os.path.join(base_dir, "Views/Chat/SelectableMarkdownView.swift")
        check = os.path.join(base, "only_verify_ok.py")
        open(check, "w", encoding="utf-8").write(
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location('fb', %r)\n" % fb_path_global
            + "m = importlib.util.module_from_spec(spec)\n"
              "spec.loader.exec_module(m)\n"
              "t = open(%r, encoding='utf-8').read()\n" % md
            + "m.verify_diag_codeblock_v565(t)\nprint('OK')\n")
        p = subprocess.run([sys.executable, check], capture_output=True, text=True)
        if "OK" in (p.stdout or ""):
            ok.append(("BASE 未改动的产物必须通过", True, "基线无误伤"))
        else:
            bad.append(("BASE 未改动的产物必须通过", False,
                        (p.stdout + p.stderr).strip()[:160]))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 64)
    for n, good, msg in ok:
        print("✅ %-44s %s" % (n, msg))
    for n, good, msg in bad:
        print("❌ %-44s %s" % (n, msg))
    print("=" * 64)
    print("V565 反向: %d 拦下, %d 漏过" % (len(ok), len(bad)))
    if bad:
        print("⇒ 判据有洞, 别信它的绿。")
        return 1
    print("✅ 全部 sabotage 都被拦下, 且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())
