#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产物二进制级校验: 装机包里**真的**有守卫修复吗?
=====================================================

★ 本项目**第九次**「验证手段骗了自己」—— 判据根本没看最终产物。
★ 本项目**第十二次**「验证手段骗了自己」—— 判据**看了产物, 但只按一种编码看**。

【第九次: 判据只验原料】
  前八次都是「判据问错了问题」; 第九次是**判据全部作用在 `src/ios/**.m`
  源码上**, 而「装机包里到底有没有这段代码」从来没被问过。
  源码正确 + 编译成功 + 打包成功 ⇒ 三件事同时成立,
  仍不能推出「修复进了二进制」。
  ★判据必须验**交付物本身**, 而不是交付物的**原料**。

【第十次: 新判据自己把流水线掐死】
  本脚本被 local_all_gates.py 从 workflow 文本里正则抽出来重跑,
  抽取器只认 `VAR=字面量`、**不认 `${{ ... }}` 表达式**
  ⇒ FileNotFoundError ⇒ 门禁 exit 1
  ⇒ CI 37361069156 / 37361453374 **编译一步都没跑**。
  ⇒ §27: **新增判据必须先在本地全量门禁跑通再推**。

★【第十二次(本版修的): 判据只按 UTF-8 搜, 漏了 UTF-16 —— 假红】
  本脚本第一版在 CI 37367511487 上报:
      ❌ v68(1) NONPOSITIVE-STREAK      count=0
      ❌ v68(2) NONPOSITIVE-DOWNFREQ    count=0
      ❌ v65    FIXED-NONPOSITIVE       count=0
      ✅ v4     storm-breaker           count=1   ← 对照组
      ✅ v38-C  probe-height            count=1   ← 对照组
      ✅ v4     REJECT-NAN-INF          count=1   ← 对照组
  对照组全在、硬规则全缺 ⇒ 看起来铁证如山「修复没进包」。

  **但它错了。** 真实原因:
      clang 对 `@"..."` 字面量的存储编码**取决于字面量是否全 ASCII**:
        · 全 ASCII        → `__TEXT,__cstring`   (UTF-8)
        · 含非 ASCII 字符 → `__TEXT,__ustring`   (UTF-16LE)
  对照组的三条格式串**全是 ASCII**; 而 v65/v68 那三条的日志文本里
  带中文注释(`— 修正转发(旧版丢弃=卡字)`、`— 非正尺寸跨 tick 累加中`、
  `— 降频 1/%d 放行(保留上行通道)`) ⇒ 它们被存成 **UTF-16LE**。
  第一版判据只搜 UTF-8 字节 ⇒ 一律 count=0。

  实测(同一份 v68 主二进制, 121MB Mach-O arm64):

      串                        UTF-8 搜   UTF-16LE 搜
      ---------------------------------------------------
      FIXED-NONPOSITIVE (v65)      0          1
      NONPOSITIVE-STREAK (v68)     0          1
      NONPOSITIVE-DOWNFREQ (v68)   0          1
      storm-breaker (v4 对照)      1          0
      probe-height (v38C 对照)     1          0

  **完美互补** —— 不是「修复没进包」, 是「判据只看得见一半的包」。
  ⇒ 三份历史 IPA 交叉复核后全部自洽:
      v66 包: v65 utf16=1   (那时还没有 v68, 符合预期)
      v67b包: v65 utf16=1, v68 utf16=0 (同上)
      v68 包: v65 utf16=1, v68 两条 utf16=1
  ⇒ **v65 从 v66 起一直在包里; v68 也在。修复从未丢失。**

  ★这次与第九次是**同一类错误的两种形态**:
    第九次  问都没问「产物里有没有」;
    第十二次 问了, 但**只按一种编码问**, 于是「没有」是搜索方法的产物。
  ⇒ 纪律: 判据说「没有」时, 先自问「我有没有可能没看见」,
    尤其是**对照组恰好全在**的时候 —— 那正说明查对了文件、错了方法。
  ⇒ 判据的 self-test 必须包含**真实形态的样本**(本版已加:
    good_mixed = 硬规则 UTF-16 + 对照组 UTF-8), 否则同样的假红会再犯。

【为什么这个判据不能靠 grep 源码代替】
  grep 源码查的是「我有没有写这段代码」; 本脚本查的是
  「链接器有没有把它放进 App」。两者之间隔着编译器与链接器。
  这是**结构性缺口**, 不是某一步写错了 —— 所以它必须独立存在。

【实跑验证记录(本版)】
  三份历史 IPA 各自解包、对真实 `Payload/Minis.app/Minis` 跑本脚本:

      v66 包 (run 37291520517): v65 ✅ / v68 两条 ❌  ⇒ rc=1
           —— v66 那年还没写 v68, 报红是**正确的**, 说明判据分得清版本
      v67b包 (run 37347279503): 同上
      v68 包 (run 37357375487): 六条全 ✅            ⇒ rc=0

  ★关键在于「v66 报 v68 红」这条: 它证明判据不是「永远放行」。
    若三份都全绿, 反而要怀疑判据没有鉴别力。

【CI 侧待确认: 两次 job 未启动】
  修完判据后连推两次(`eb6883c` → run 37370184926、`922c2a5` → run 37370465099),
  两次都是 `completed / failure`, 但:
    · job 的 steps 列表**为空**
    · 日志 zip 只有 22 字节(空)
    · 一次 7 秒结束、一次 5 分 15 秒结束
  ⇒ **不是本仓库任何步骤失败**(步骤一个都没跑), 是 runner 没能启动。
  高度怀疑 Actions 分钟配额(macOS runner 按 10 倍计费, 本仓库已 212 次 run),
  需在 GitHub Billing 页确认。PAT 无权查 billing 也无权重跑, 只能靠推送触发。
  ★这与判据无关: 判据已在本地和三份真实 IPA 上验证过(见上)。

【怎么用】
    python3 verify_binary_guard_markers.py <Minis.app 目录>  或  <Mach-O 文件>
    python3 verify_binary_guard_markers.py --self-test

★`--self-test` 为什么必须存在（本脚本第一版就栽在这里）:
  `local_all_gates.py` 会**从 workflow 文本里正则抽取**所有
  `python3 "$SCRIPT_DIR/ios15_verify/*.py" <参数>` 调用并**逐条重跑**。
  而它在参数里只认 shell 变量(`"$VAR"`), **不认 `${{ ... }}` 表达式** ——
  断言 72 写的是 `"$IPA"`, `IPA="Minis-iOS${{ env.DEPLOY_TARGET }}.ipa"`,
  于是抽取器把 `${{ env.DEPLOY_TARGET }}` **原样**传下来, 脚本拿到
  一个字面文件名 `Minis-iOS${{ env.DEPLOY_TARGET }}.ipa`
  ⇒ FileNotFoundError ⇒ 门禁红, 而**编译一步都没跑**。
  ⇒ 本脚本若无参, 门禁里必红; 所以无参时走 self-test:
  **造已知的好/坏样本, 验判据既能报红也不误报**。
"""

import os
import sys

# (文本串, 人类可读描述, 最小出现次数)
# ★用**文本**而不是字节: 编码由 _count() 展开, 见下方 ENCODINGS。
RULES = [
    # ---- v68: 非正尺寸风暴的真闸门 (格式串含中文 ⇒ UTF-16) ----
    # ★前缀务必与源码逐字对齐: v68 这两条带 [WARN], v65 那条不带。
    #   第一版把 [WARN] 漏掉了 ⇒ 自证里的真实形态样本当场报红(它拦住了)。
    ("[TextContainerGuard] [WARN] [V68] NONPOSITIVE-STREAK",
     "v68(1) streak 跨 tick 累加(必须无条件执行, 不在 per-tick 门槛内)", 1),
    ("[TextContainerGuard] [WARN] [V68] NONPOSITIVE-DOWNFREQ",
     "v68(2) 降频放行(硬闸门不得退回「命中即 return」的永久冻结)", 1),
    ("[TextContainerGuard] [WARN] [V76] NONPOSITIVE-SHORT-CIRCUIT",
     "v76     非正尺寸直接短路不转发(斩断 V65 修正转发引发的 layout 活锁)", 1),
    ("[TextContainerGuard] [WARN] [V78] EARLY-NONPOSITIVE-RETURN",
     "v78     入口短路: height==0 在 associated 分配之前 return(零堆分配)", 1),
    ("[Minis-Guard] build=V78",
     "v78     装机确认横幅(注释键升级了、NSLog 仍打 V77 = 半升级)", 1),
    # ---- v65: 非正尺寸就地修正转发, 不再丢弃 (含中文 ⇒ UTF-16) ----
    ("[TextContainerGuard] [V65] FIXED-NONPOSITIVE",
     "v65     非正尺寸就地修正后转发(旧版丢弃 => 排版停在上一帧 => 卡字)", 1),
    # ---- v4 / v38-C: 基线熔断(这三段历史上一直在包里, 当对照组; 全 ASCII ⇒ UTF-8) ----
    ("storm-breaker SKIP",
     "v4      setSize 风暴熔断(对照组: 它若也不在, 说明查错了二进制)", 1),
    ("probe-height",
     "v38-C   intrinsic 哨兵高度钳制(对照组)", 1),
    ("REJECT-NAN-INF",
     "v4      NaN/inf 硬拒(对照组)", 1),
]

# ★第十二次的修法: 同一个字面量在 Mach-O 里可能是 UTF-8(__cstring),
#   也可能是 UTF-16LE(__ustring) —— 取决于它是否全 ASCII。
#   两条都要搜, 命中任一即算「在」。
ENCODINGS = ("utf-8", "utf-16-le")

_BIN_SUFFIXES = ("", ".app")


def _encodings(s: str):
    out = []
    for enc in ENCODINGS:
        try:
            b = s.encode(enc)
        except Exception:
            continue
        if b not in out:
            out.append(b)
    return out


def _count(blob: bytes, s: str) -> int:
    """任一编码命中即算命中; 返回**最大**的那一档计数(便于人读)。"""
    return max((blob.count(b) for b in _encodings(s)), default=0)


def _is_hard_rule(s: str) -> bool:
    """硬规则 = v65/v68(要修的那几段); 其余是对照组。

    ★按**版本标记**判断, 不按前缀: v68 两条带 `[WARN]`、v65 那条不带,
      用前缀判会把 v68 误当成对照组 ⇒ 坏样本里它们"在" ⇒ 漏报。
    """
    return ("[V65]" in s or "[V68]" in s or "[V76]" in s or "[V77]" in s
            or "[V78]" in s or "build=V78" in s)


def _find_binary(target: str):
    """定位 Mach-O 可执行文件。接受 .app 目录 / .ipa / 直接的二进制路径。"""
    if os.path.isdir(target):
        # .app 目录: 读 Info.plist 的 CFBundleExecutable, 退回同名文件
        exe = os.path.basename(target.rstrip("/"))
        if exe.endswith(".app"):
            exe = exe[:-4]
        plist = os.path.join(target, "Info.plist")
        if os.path.isfile(plist):
            try:
                import plistlib
                with open(plist, "rb") as f:
                    got = plistlib.load(f).get("CFBundleExecutable")
                if isinstance(got, str) and got:
                    exe = got
            except Exception:
                pass
        cand = os.path.join(target, exe)
        if os.path.isfile(cand):
            return cand
        # 退回: 目录里唯一 Mach-O
        for name in sorted(os.listdir(target)):
            p = os.path.join(target, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                with open(p, "rb") as f:
                    if f.read(4) in (b"\xfe\xed\xfa\xce", b"\xcf\xfa\xed\xfe",
                                     b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                        return p
        return None
    if os.path.isfile(target):
        return target
    return None


def _write_sample(path, enc_by_rule):
    """按 {规则文本: 编码} 写一份样本; 值为 None 表示不写(缺失)。"""
    with open(path, "wb") as f:
        for s, _d, _n in RULES:
            enc = enc_by_rule.get(s)
            if enc is None:
                continue
            f.write(s.encode(enc) + (b"\x00" if enc == "utf-8" else b"\x00\x00"))


def _self_test():
    """自证: 判据对**已知的好样本**放行、对**已知的坏样本**报红。

    ★为什么必须双向:
      只验「坏样本报红」⇒ 判据可能是「永远报红」, 那它没有鉴别力。
      只验「好样本放行」⇒ 判据可能是「永远放行」, 那它是个废品。
      ★反向漏过(永远放行) 是判据的信息, 不是噪音(§25 附三)。

    ★★第十二次的直接产物 —— 三种「好」形态都要放行:
      good_utf8   : 六条全 UTF-8      (纯 ASCII 世界的形态)
      good_utf16  : 六条全 UTF-16LE
      good_mixed  : 硬规则 UTF-16 + 对照组 UTF-8   ← **真实产物就是这个形态**
      只测 good_utf8 时, 第一版全绿, 一上真机产物就假红 ——
      ⇒ **自证样本必须包含交付物的真实形态**, 否则自证是自欺。
    """
    import contextlib
    import io
    import tempfile
    ok = True
    print("=== 断言72 判据自证 (双向 + 双编码) ===")

    all_utf8 = {s: "utf-8" for s, _d, _n in RULES}
    all_utf16 = {s: "utf-16-le" for s, _d, _n in RULES}
    mixed = {s: ("utf-16-le" if _is_hard_rule(s) else "utf-8")
             for s, _d, _n in RULES}
    bad_map = {s: ("utf-8" if not _is_hard_rule(s) else None)
               for s, _d, _n in RULES}   # 硬规则全缺, 对照组在

    n_hard = sum(1 for s, _d, _n in RULES if _is_hard_rule(s))

    samples = [
        # (标签, 样本, 期望 rc, 期望报红条数)
        ("坏样本(硬规则全缺)", bad_map, 1, n_hard),
        ("好样本(全 UTF-8)", all_utf8, 0, 0),
        ("好样本(全 UTF-16LE)", all_utf16, 0, 0),
        ("好样本(真实形态: 硬规则UTF-16+对照UTF-8)", mixed, 0, 0),
    ]

    tmps = []
    try:
        for label, mapping, want, want_bad in samples:
            t = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
            tmps.append(t.name)
            _write_sample(t.name, mapping)
            print("")
            print("--- %s (期望 rc=%d, 报红 %d 条) ---" % (label, want, want_bad))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main([t.name])
            sys.stdout.write(buf.getvalue())
            # ★不只验 rc: 坏样本必须**恰好**报红 n_hard 条。
            #   只验 rc 时, 漏掉两条硬规则也照样 rc=1 —— 自证会睁一只眼闭一只眼。
            got_bad = sum(1 for ln in buf.getvalue().splitlines()
                          if ln.startswith("  ❌"))
            if rc != want:
                print("❌ %s: 期望 rc=%d, 实际 rc=%d" % (label, want, rc))
                ok = False
            elif got_bad != want_bad:
                print("❌ %s: 期望报红 %d 条, 实际 %d 条 —— 规则归类可能错了"
                      % (label, want_bad, got_bad))
                ok = False
            else:
                print("✅ %s: rc=%d, 报红 %d 条, 均符合期望"
                      % (label, rc, got_bad))

        print("")
        if ok:
            print("✅ 判据自证通过: 双向都有鉴别力, 且 UTF-8/UTF-16 两种编码都认得")
        else:
            print("❌ 判据自证失败")
        return 0 if ok else 1
    finally:
        for p in tmps:
            try:
                os.unlink(p)
            except OSError:
                pass


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--self-test":
        return _self_test()
    if not argv:
        # ★无参 = 门禁抽取器把表达式原样传下来了 ⇒ 走自证, 不猜、不凑。
        print("!(无参数) 门禁抽取器未求值 `${{ ... }}` 表达式 ⇒ 转入自证模式")
        return _self_test()
    target = argv[0]

    # 支持直接传 .ipa: 解出主 App 二进制
    if target.endswith(".ipa"):
        import zipfile
        import tempfile
        with zipfile.ZipFile(target) as z:
            names = [n for n in z.namelist()
                     if n.startswith("Payload/") and "/MacOS/" in n
                     and not n.endswith((".appex/", ".framework/"))]
            if not names:
                names = [n for n in z.namelist()
                         if n.startswith("Payload/") and n.endswith("/Minis")]
            if not names:
                print("❌ IPA 里找不到主 App 可执行文件")
                return 1
            names.sort(key=len, reverse=True)
            tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
            with z.open(names[0]) as src, open(tmp.name, "wb") as dst:
                dst.write(src.read())
            print("(从 %s 取出 %s)" % (os.path.basename(target), names[0]))
            target = tmp.name

    path = _find_binary(target)
    if not path:
        print("❌ 找不到 Mach-O 二进制: %s" % target)
        return 1

    size = os.path.getsize(path)
    print("=== 二进制级守卫校验: %s (%.1f MB) ===" % (path, size / 1048576.0))
    print("(搜索编码: %s —— 含中文的字面量在 Mach-O 里是 UTF-16)" %
          " + ".join(ENCODINGS))
    with open(path, "rb") as f:
        blob = f.read()

    # Mach-O 是 0xCAFEBABE(BE) 时说明是 fat/多架构二进制, 切片扫一遍
    # ★chunks 必须是**纯 bytes 列表**: 早先写成 [("", blob)], _count() 收到的是
    #   tuple, tuple.count(bytes) 恒返回 0 —— 自证里所有样本一律 count=0,
    #   当场被 self-test 抓住(这正是自证存在的意义)。
    chunks = [blob]
    if blob[:4] == b"\xca\xfe\xba\xbe":
        import struct
        narch, = struct.unpack(">I", blob[4:8])
        pos, slices = 8, []
        for _ in range(narch):
            _cpu, _sub, off, _size, _align = struct.unpack(">IIIII", blob[pos:pos + 20])
            slices.append(blob[off:off + _size])
            pos += 20
        chunks = slices
        print("(多架构二进制, %d 个切片)" % narch)

    bad = []
    for pat, desc, need in RULES:
        total = sum(_count(chunk, pat) for chunk in chunks)
        if total >= need:
            print("  ✅ %-62s count=%d" % (desc[:62], total))
        else:
            print("  ❌ %-62s count=%d (要求 >=%d)" % (desc[:62], total, need))
            bad.append((pat, desc, total))

    print("")
    if not bad:
        print("✅ 二进制里 v65/v68/v76/v78 修复全部就位 —— 装机包确实带上了")
        return 0

    print("❌❌❌ 装机包里**缺**这些守卫修复 (上面 %d 条报红) ❌❌❌" % len(bad))
    print("")
    print("★ 这意味着: 源码判据全绿、编译成功、IPA 打出来了,")
    print("  但**修复没进二进制**。装机后跑的还是旧守卫 ——")
    print("  症状会与「没打这个补丁」完全一致, 而 CI 全绿。")
    print("")
    print("★★ 先排除「判据自己没看见」(第十二次假绿的教训):")
    print("  0. 对照组(v4/v38-C)是不是全绿?")
    print("     全绿  ⇒ 查对了二进制, 问题在**搜索方法**或**代码真没进包**;")
    print("             先确认这些串的编码: 含中文的字面量是 UTF-16(__ustring),")
    print("             ASCII 的才是 UTF-8(__cstring)。本脚本两种都搜。")
    print("     也红  ⇒ 查错了二进制(架构/文件路径), 先修定位。")
    print("")
    print("排查顺序(每步都要看, 别跳):")
    print("  1. 注入是否真生效: grep 编译用的 .m 是否含这些标记")
    print("  2. 编译的 .m 是否就是被注入的那份(路径/文件名大小写)")
    print("  3. 该 .m 是否真在 target 的 Sources 里 (pbxproj)")
    print("  4. 打包的 .app 是否就是本次编译的 .app (DerivedData 复用?")
    print("     多个 -derivedDataPath? 产物级幂等门有没有覆盖 src/ios?)")
    print("  5. 是否有 #if / #ifdef 把那段代码编译掉了")
    print("")
    print("★ 纪律: 判据必须验**交付物本身**, 不能只验交付物的原料。")
    print("  grep 源码查的是「我有没有写这段代码」;")
    print("  本脚本查的是「链接器有没有把它放进 App」。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
