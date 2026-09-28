#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 MinisFileProvider 扩展的部署目标强制设为 iOS 16.0。

原因：
  MinisFileProvider 扩展使用了 NSFileProviderRequest / NSFileProviderItemVersion /
  NSFileProviderItemFields / NSFileProvider*Options / NSFileProviderDomain.trashContainer
  等 iOS 16 专属 API，无法在 iOS 15.5 上编译。
  把该扩展单独抬到 iOS 16.0 后：
    - 主 App（Minis）仍以 15.5 编译、可在 iOS 15.5 安装运行；
    - 该扩展在 iOS 15.5 上不会被系统加载（仅“文件 App 集成”失效），不影响主程序。
  只对 pbxproj「新增」一条设置，不删除任何引用，避免破坏工程结构。
"""
import re
import sys

PBX_PATH = "src/ios/Minis.xcodeproj/project.pbxproj"
TARGET = "MinisFileProvider"
TARGET_DEPLOY = "16.0"


def find_block(text, uuid):
    """返回以 `uuid /* ... */ = {` 开头的整块（含配对花括号）的 [start, end)。"""
    pat = re.compile(re.escape(uuid) + r"\s*/\*.*?\*/\s*=\s*\{")
    m = pat.search(text)
    if not m:
        return None, None
    start = m.end() - 1  # 定位到 '{'
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return m.start(), i + 1
        i += 1
    return m.start(), len(text)


def main():
    try:
        text = open(PBX_PATH).read()
    except FileNotFoundError:
        print("⚠️  未找到 %s，跳过（请确认工作流在仓库根目录执行）。" % PBX_PATH)
        sys.exit(0)

    # 1) 找到 MinisFileProvider 的 buildConfigurationList UUID
    m = re.search(
        r"(\w+)\s*/\*\s*Build configuration list for PBXNativeTarget \"%s\"\s*\*/"
        % re.escape(TARGET),
        text,
    )
    if not m:
        print("⚠️  未找到 %s 的 buildConfigurationList，跳过（请确认目标名正确）。" % TARGET)
        sys.exit(0)
    list_uuid = m.group(1)

    # 2) 在该 XCConfigurationList 中找到 buildConfigurations 的 UUID 列表
    ls, le = find_block(text, list_uuid)
    if ls is None:
        print("⚠️  未找到配置列表块，跳过。")
        sys.exit(0)
    list_block = text[ls:le]
    cfg_uuids = re.findall(r"(\w+)\s*/\*\s*(?:Debug|Release)\s*\*/", list_block)
    print("📦 %s 的配置 UUID: %s" % (TARGET, cfg_uuids))

    changed = 0
    for cu in cfg_uuids:
        cs, ce = find_block(text, cu)
        if cs is None:
            print("⚠️  未找到配置块 %s" % cu)
            continue
        block = text[cs:ce]
        if "buildSettings" not in block:
            print("⚠️  配置 %s 中没有 buildSettings，跳过。" % cu)
            continue
        # 删除该配置块内已有的 IPHONEOS_DEPLOYMENT_TARGET 行
        block = re.sub(
            r"\n\s*IPHONEOS_DEPLOYMENT_TARGET\s*=\s*[0-9.]+\;\n", "\n", block
        )
        # 在 buildSettings = { 之后插入 16.0
        block = re.sub(
            r"(buildSettings\s*=\s*\{)",
            r"\1\n\t\t\t\tIPHONEOS_DEPLOYMENT_TARGET = %s;" % TARGET_DEPLOY,
            block,
            count=1,
        )
        text = text[:cs] + block + text[ce:]
        changed += 1
        print("✅ 已将 %s 部署目标设为 iOS %s（配置 %s）" % (TARGET, TARGET_DEPLOY, cu))

    open(PBX_PATH, "w").write(text)
    print("🎉 完成，共修改 %d 个配置。" % changed)


if __name__ == "__main__":
    main()
