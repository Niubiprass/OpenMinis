#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产物二进制级校验: 装机包里**真的**有守卫修复吗?
=====================================================

★ 本项目**第九次**「验证手段骗了自己」—— 而且是最隐蔽的一次。
  前八次都是「判据问错了问题」; 这一次是**判据根本没看最终产物**。

【装机铁证】CI run 37357375487 (commit e72f6b6, v68) 全绿:
    - 编译成功, IPA 71MB, dyld 体检通过
    - 断言 71 真跑了: "v68 判据就位(累加在门槛外 + 降频游标 + 步长常量
      + lastGoodHeight 既读又写)"
    - 反向 17 条逐条拦下(S14 死代码复现 / S15 永久冻结 / S16 裸1.0
      / S17 字段没人写)
  而从该 run 的 artifact 里挖出主 App 二进制(121MB Mach-O arm64),
  逐字节搜 NSLog 格式串:

    源码里应有 8 条            二进制里
    ----------------------------------------------------------------
    ... REJECT-NAN-INF ...        在   (v4)
    [V65] FIXED-NONPOSITIVE       ❌ 缺失
    [V38C] probe-height           在   (v38-C)
    [WARN] storm-breaker SKIP     在   (v4)
    ... short-circuited setSize:  在   (v4)
    [V68] NONPOSITIVE-STREAK      ❌ 缺失
    [V68] NONPOSITIVE-DOWNFREQ    ❌ 缺失
    [INFO] installed (threshold   在   (v4)

  ⇒**装机包里是 v38-C 那一代的守卫, v65 与 v68 都不在。**
  同 run 的产物级幂等门、bash 语法门、9 层判据、17 条反向**全绿**。

★为什么前八次都没抓到: 判据全部作用在 `src/ios/**.m` **源码**上,
  而「装机包里到底有没有这段代码」这件事**从来没被问过**。
  源码正确 + 编译成功 + 产物打包成功 ⇒ 三件事同时成立,
  仍不能推出「修复进了二进制」。
  ★判据必须验**交付物本身**, 而不是交付物的**原料**。

【第十次(紧随其后): 本脚本第一版自己把流水线掐死了】
  它被 local_all_gates.py 从 workflow 文本里正则抽出来重跑,
  而抽取器只认 `VAR=字面量`、**不认 GitHub Actions 的模板表达式**
  ⇒ IPA 变量被原样传入 ⇒ FileNotFoundError ⇒ 门禁 exit 1
  ⇒ CI 37361069156 / 37361453374 **编译一步都没跑**。
  ★讽刺: 加判据是为了查「产物里没有 v68」,
    结果判据自己先把构建堵住, 那个答案一个也没拿到。
  ⇒ §27: **新增判据必须先在本地全量门禁跑通再推**。
    门禁是绿的, 只因为那时还没这个脚本 —— 加完必须重跑。
    把「我加了判据」当成「门禁因此更严」是错的:
    实际可能是「门禁因此挂了, 而挂着的时候它一条都不验」。

【为什么这个判据不能靠 grep 源码代替】
  grep 源码查的是「我有没有写这段代码」; 本脚本查的是
  「链接器有没有把它放进 App」。两者之间隔着编译器与链接器。
  这是**结构性缺口**, 不是某一步写错了 —— 所以它必须独立存在。

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
  ⇒ FileNotFoundError ⇒ 门禁红, 而**编译一步都没跑**(CI 37361069156 /
  37361453374 都是这样失败的)。
  ⇒ 本脚本若无参, 门禁里必红; 所以无参时走 self-test:
  **造一份已知的坏样本, 验「判据能报红」, 并造一份好样本, 验「判据不误报」**。
  这比「凑一个能过的参数」强得多 —— 它验的是判据的有效性本身,
  而不是判据在某个环境里恰好不报错(§16 的反面)。
"""

import os
import sys

# (字节串, 人类可读描述, 最小出现次数)
RULES = [
    # ---- v68: 非正尺寸风暴的真闸门 ----
    (b"[TextContainerGuard] [V68] NONPOSITIVE-STREAK",
     "v68(1) streak 跨 tick 累加(必须无条件执行, 不在 per-tick 门槛内)", 1),
    (b"[TextContainerGuard] [V68] NONPOSITIVE-DOWNFREQ",
     "v68(2) 降频放行(硬闸门不得退回「命中即 return」的永久冻结)", 1),
    # ---- v65: 非正尺寸就地修正转发, 不再丢弃 ----
    (b"[TextContainerGuard] [V65] FIXED-NONPOSITIVE",
     "v65     非正尺寸就地修正后转发(旧版丢弃 => 排版停在上一帧 => 卡字)", 1),
    # ---- v4 / v38-C: 基线熔断(这三段历史上一直在包里, 当对照组) ----
    (b"storm-breaker SKIP",
     "v4      setSize 风暴熔断(对照组: 它若也不在, 说明查错了二进制)", 1),
    (b"probe-height",
     "v38-C   intrinsic 哨兵高度钳制(对照组)", 1),
    (b"REJECT-NAN-INF",
     "v4      NaN/inf 硬拒(对照组)", 1),
]

# __PAGEZERO / __TEXT 等段名, 用于跳过 Mach-O 头 (只影响报错的可读性)
_BIN_SUFFIXES = ("", ".app")


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


def _self_test():
    """自证: 判据对**已知的好样本**放行、对**已知的坏样本**报红。

    ★为什么必须双向:
      只验「坏样本报红」⇒ 判据可能是「永远报红」, 那它没有鉴别力。
      只验「好样本放行」⇒ 判据可能是「永远放行」, 那它是个废品。
      ★反向漏过(永远放行) 是判据的信息, 不是噪音(§25 附三)。
    """
    import tempfile
    ok = True
    print("=== 断言72 判据自证 (双向) ===")

    # ---- 好样本: 六条规则全在 ⇒ 必须放行 ----
    good = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    with open(good.name, "wb") as f:
        for pat, _d, _n in RULES:
            f.write(pat + b"\x00")
    # 反向样本
    bad = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    with open(bad.name, "wb") as f:
        # 只写对照组(v4/v38-C), 三条硬规则全缺 —— 复现装机包的真实形态
        for pat, _d, _n in RULES:
            if pat.startswith(b"[TextContainerGuard] [V65]") \
               or pat.startswith(b"[TextContainerGuard] [V68]"):
                continue
            f.write(pat + b"\x00")

    try:
        r_bad = main([bad.name])
        print("")
        print("--- 判定 ---")
        if r_bad != 1:
            print("❌ 对「缺 v65/v68」的样本判据**没有报红** ⇒ 判据没有鉴别力")
            ok = False
        else:
            print("✅ 对「缺 v65/v68」的样本正确报红 (rc=1)")

        print("")
        r_good = main([good.name])
        print("")
        print("--- 判定 ---")
        if r_good != 0:
            print("❌ 对「六条齐备」的样本判据**误报** ⇒ 规则写错了")
            ok = False
        else:
            print("✅ 对「六条齐备」的样本正确放行 (rc=0)")

        print("")
        if ok:
            print("✅ 判据自证通过: 双向都有鉴别力(能报真问题, 也不误报)")
        return 0 if ok else 1
    finally:
        for p in (good.name, bad.name):
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
            target = tmp.name
            print("(从 %s 取出 %s)" % (os.path.basename(target), names[0]))

    path = _find_binary(target)
    if not path:
        print("❌ 找不到 Mach-O 二进制: %s" % target)
        return 1

    size = os.path.getsize(path)
    print("=== 二进制级守卫校验: %s (%.1f MB) ===" % (path, size / 1048576.0))
    with open(path, "rb") as f:
        blob = f.read()

    # Mach-O 是 0xCAFEBABE(BE) 时说明是 fat/多架构二进制, 切片扫一遍
    chunks = [("", blob)]
    if blob[:4] == b"\xca\xfe\xba\xbe":
        import struct
        narch, = struct.unpack(">I", blob[4:8])
        pos, slices = 8, []
        for _ in range(narch):
            _cpu, _sub, off, _size, _align = struct.unpack(">IIIII", blob[pos:pos + 20])
            slices.append(("slice@%d" % off, blob[off:off + _size]))
            pos += 20
        chunks = slices
        print("(多架构二进制, %d 个切片)" % narch)

    bad = []
    for pat, desc, need in RULES:
        total = sum(chunk.count(pat) for _n, chunk in chunks)
        if total >= need:
            print("  ✅ %-62s count=%d" % (desc[:62], total))
        else:
            print("  ❌ %-62s count=%d (要求 >=%d)" % (desc[:62], total, need))
            bad.append((pat, desc, total))

    print("")
    if not bad:
        print("✅ 二进制里 v65/v68 修复全部就位 —— 装机包确实带上了")
        return 0

    print("❌❌❌ 装机包里**缺**这些守卫修复 (上面 %d 条报红) ❌❌❌" % len(bad))
    print("")
    print("★ 这意味着: 源码判据全绿、编译成功、IPA 打出来了,")
    print("  但**修复没进二进制**。装机后跑的还是旧守卫 ——")
    print("  症状会与「没打这个补丁」完全一致, 而 CI 全绿。")
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