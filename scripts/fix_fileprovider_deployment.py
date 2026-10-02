#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 MinisFileProvider 扩展的部署目标强制设为 iOS 16.0。

原因：
  MinisFileProvider 扩展使用了 NSFileProviderRequest / NSFileProviderItemVersion /
  NSFileProviderItemFields / NSFileProvider*Options / NSFileProviderDomain.trashContainer
  等 iOS 16 专属 API，无法在 iOS 15.5 上编译。
  把该扩展单独抬到 iOS 16.0 后：
    - 主 App（Minis）仍以 15.5 编译、可在 iOS 15.5 安装运行；
    - 编译能通过（这是本脚本存在的唯一目的）。

⚠️ 重要更正（2026-10-03，设备实证）：
  本脚本原注释写"该扩展在 iOS 15.5 上不会被系统加载，不影响主程序" —— **这是错的**。
  iOS 不会因为扩展的部署目标高于系统版本就拒绝加载它；系统会照常拉起、照常 dyld，
  然后因为二进制里用到的 iOS 16 符号在 15.5 上不存在而直接 SIGABRT：

    Symbol not found: _$s10Foundation12CharacterSetV12charactersInACSSh_tcfC
    Referenced from: Minis.app/PlugIns/MinisFileProvider.appex/MinisFileProvider
    Expected in:     /System/Library/Frameworks/Foundation.framework/Foundation
    DYLD / Symbol missing / SIGABRT / "terminated at launch; ignore backtrace"

  （该符号是 CharacterSet.init(charactersIn:) 的 Swift 泛型桥接桩，iOS 16 才有。）

  设备侧在 8 分钟内记录到 12 次同样的秒崩（3 波，每波 3–4 个 incident），
  说明有东西在反复拉起这个扩展（大概率是 Files App 枚举已注册的 File Provider）。

  真正的处置不在本脚本，而在打包阶段：workflow 的「剥离 iOS 15 不可启动的扩展」
  步骤会按 otool 实测结果把部署目标 >15.5 或链接了缺失框架的 appex 从包里剔除，
  使"文件"App 集成在 iOS 15.5 上不可用（本来就用不了），但不再产生崩溃。

  抬高部署目标只改 Mach-O 里的平台版本标记，**不会**让缺失的符号出现。
  只对 pbxproj「新增」一条设置，不删除任何引用，避免破坏工程结构。
"""
import re
import sys

PBX_PATH = "src/ios/Minis.xcodeproj/project.pbxproj"
# 各扩展 target -> 部署目标。这些扩展依赖主 App 用不到的新系统 API,
# 抬高部署目标后它们在 iOS 15.5 上不被系统加载(对应功能失效), 但主 App 不受影响。
TARGETS = {
    "MinisFileProvider": "16.0",     # NSFileProvider* 系列 iOS16 API
    "AgentWidgetExtension": "17.0",  # LiveActivityIntent / 灵动岛按钮 iOS17
}


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


def process_target(TARGET, TARGET_DEPLOY):
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
    print("🎉 %s 完成，共修改 %d 个配置。" % (TARGET, changed))


def main():
    for t, d in TARGETS.items():
        process_target(t, d)


if __name__ == "__main__":
    main()
