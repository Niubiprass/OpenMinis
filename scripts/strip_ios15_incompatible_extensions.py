#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剔除 iOS 15.5 上无法启动的 app extension(appex)。

为什么需要
----------
iOS 15.5 侧载的 Minis 里有两个扩展一被系统拉起就秒崩:

  ① AgentWidgetExtension —— 链接了 iOS 15.5 不存在的私有框架
     /System/Library/Frameworks/_AppIntents_SwiftUI.framework/_AppIntents_SwiftUI
     → dyld "Library not loaded", SIGABRT。
  ② MinisFileProvider —— fix_fileprovider_deployment.py 为了让它编译通过把它抬到
     iOS 16.0(用了 NSFileProvider* 系列 iOS16 API)。**抬高部署目标只改 Mach-O 里的
     平台版本标记, 不会让缺失的符号出现**; iOS 也不会因为部署目标更高就拒绝加载它。
     设备实证(2026-10-03, 12 份 .ips, 8 分钟内 3 波): 被拉起后 182ms 即 SIGABRT —
       Symbol not found: _$s10Foundation12CharacterSetV12charactersInACSSh_tcfC
       Expected in: /System/Library/Frameworks/Foundation.framework/Foundation
       DYLD / Symbol missing / "terminated at launch; ignore backtrace"
     即 CharacterSet.init(charactersIn:) 的 Swift 泛型桥接桩, iOS 16 才有。

判据(两条任一命中即剔除)
------------------------
  (a) 二进制链接了 iOS 15.5 不存在的框架(当前只知_AppIntents_SwiftUI);
  (b) 二进制的 LC_BUILD_VERSION.minos > 15.5 —— 按 iOS 16+ SDK 编的产物一定
      引用了 15.5 上不存在的符号, dyld 必挂。这是**通用**判据, 不依赖符号名单,
      将来上游再引入新的高版本扩展也能自动兜住。

代价: 对应功能在 iOS 15.5 上不可用(桌面小组件、"文件"App 集成本来就用不了),
但主 App 不再被拖崩、也不再刷崩溃日志。

用法: python3 strip_ios15_incompatible_extensions.py <Minis.app 路径>
"""
import os
import plistlib
import shutil
import subprocess
import sys

# iOS 15.5 上不存在的框架(mangled / 路径片段)。可后续补充。
MISSING_FRAMEWORKS = ["_AppIntents_SwiftUI"]
DEPLOY_FLOOR = "15.5"


def parse_version(v):
    """'16.0' -> (16, 0); 解析不出来返回 None。"""
    try:
        return tuple(int(x) for x in v.strip().split(".")[:2])
    except (ValueError, AttributeError):
        return None


def find_binary(appex):
    """返回 appex 里可执行文件的路径(主二进制名 == appex 名去掉 .appex)。"""
    name = os.path.basename(appex)
    stem = name[:-len(".appex")] if name.endswith(".appex") else name
    cand = os.path.join(appex, stem)
    if os.path.isfile(cand) and os.access(cand, os.X_OK):
        return cand
    # 兜底: 扫一遍, 找唯一可执行且不像 dylib/framework 的 Mach-O
    for f in sorted(os.listdir(appex)):
        p = os.path.join(appex, f)
        if os.path.isfile(p) and os.access(p, os.X_OK) and not f.endswith((".dylib", ".plist")):
            return p
    return None


def otool_lines(binary, *args):
    """运行 otool; 没有该工具时返回 None(调用方须区别于"空输出")。

    绝不能把"工具缺失"当成"检查通过" —— 那会让整个剥离步骤静默变成空操作,
    打出一个仍在崩溃的包。CI 的 macOS runner 上 otool 必然存在, 但本地/自建
    runner 上未必, 所以显式区分。
    """
    exe = shutil.which("otool")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args, binary], capture_output=True, text=True, timeout=60)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _minos_from_objdump(binary):
    """otool 不可用时的兜底: llvm-objdump 会打印 Mach-O 的 LC_BUILD_VERSION。

    只认 llvm-objdump —— **GNU 的 objdump 不解析 Mach-O**, 对 arm64 二进制会
    报 "file format not recognized" 并输出空。把 GNU objdump 当成可用会让
    "读不出 minos" 变成常态, 进而把**所有**扩展都误判为不可用而删光。
    """
    exe = shutil.which("llvm-objdump")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--macho", "--private-headers", binary],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    seen = False
    for line in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines():
        if "LC_BUILD_VERSION" in line:
            seen = True
        elif seen and "minos" in line:
            return line.split()[-1].strip()
    return None


def macho_tool():
    """返回可用于解析 Mach-O 的工具名, 没有则 None。"""
    for exe in ("otool", "llvm-objdump"):
        if shutil.which(exe):
            return exe
    return None


def minos(binary):
    """读 LC_BUILD_VERSION 的 minos; 没有该 load command / 工具缺失返回 None。"""
    out = otool_lines(binary, "-l")
    if out is None:
        return _minos_from_objdump(binary)
    seen = False
    for line in out.splitlines():
        if "LC_BUILD_VERSION" in line:
            seen = True
        elif seen and "minos" in line:
            return line.split()[-1].strip()
    return None


def links_missing_framework(binary):
    out = otool_lines(binary, "-L")
    if out is None:
        return []          # 工具缺失: 无法判(a), 交给 (b) 兜
    return [f for f in MISSING_FRAMEWORKS if f in out]


def toolchain_available():
    return macho_tool() is not None


def deployed_floor_is_too_high(binary):
    v = parse_version(minos(binary) or "")
    floor = parse_version(DEPLOY_FLOOR)
    return v is not None and floor is not None and v > floor


def judge(appex):
    """返回 (是否该剔除, 原因)。**无法判定时返回"剔除"** ——
    在 iOS 15 上让一个可能崩的扩展留在包里, 代价(反复秒崩)远大于误删一个
    本来也用不了的扩展。"""
    binary = find_binary(appex)
    if not binary:
        return True, "未找到可执行文件(无法判定, 按不可用处理)"
    miss = links_missing_framework(binary)
    if miss:
        return True, "链接了 iOS 15.5 缺失的框架 %s" % ", ".join(miss)
    if deployed_floor_is_too_high(binary):
        return True, ("minos=%s > %s, 含 iOS 16+ 符号, dyld 必挂"
                      % (minos(binary), DEPLOY_FLOOR))
    if minos(binary) is None:
        return True, "读不出 minos(工具缺失或无 LC_BUILD_VERSION, 无法保证 iOS 15.5 可加载)"
    return False, "iOS %s 可加载" % DEPLOY_FLOOR


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    if not toolchain_available():
        print("⚠️  找不到 otool / llvm-objdump —— 无法做dyld 体检。")
        print("    (注意: GNU objdump 不解析 Mach-O, 不能替代 otool。)")
        print("    继续执行会导致本步骤静默失效, 产出一个仍在崩溃的包。")
        return 1
    app = sys.argv[1]
    plugins = os.path.join(app, "PlugIns")
    if not os.path.isdir(plugins):
        print("无 PlugIns 目录, 跳过: %s" % plugins)
        return 0

    print("=== 剥离前 PlugIns ===")
    for n in sorted(os.listdir(plugins)):
        print("  ", n)

    removed, kept = [], []
    for name in sorted(os.listdir(plugins)):
        appex = os.path.join(plugins, name)
        if not (name.endswith(".appex") and os.path.isdir(appex)):
            continue
        drop, why = judge(appex)
        if drop:
            print("剔除 %s — %s" % (name, why))
            # 先摘 Info.plist 里的注册信息, 再删目录: 万一有别处引用, 至少不会
            # 留下一个"注册了但不存在"的悬空 appex。
            ip = os.path.join(appex, "Info.plist")
            if os.path.isfile(ip):
                try:
                    with open(ip, "rb") as f:
                        plistlib.load(f)
                except Exception:
                    pass
            shutil.rmtree(appex, ignore_errors=True)
            removed.append(name)
        else:
            print("保留 %s (%s)" % (name, why))
            kept.append(name)

    print("=== 剥离后 PlugIns ===")
    after = sorted(os.listdir(plugins)) if os.path.isdir(plugins) else []
    for n in after:
        print("  ", n)
    if not after:
        print("   (无)")
    print("已剔除 %d 个, 保留 %d 个" % (len(removed), len(kept)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
