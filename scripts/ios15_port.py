#!/usr/bin/env python3
"""
OpenMinis → iOS 15 自动移植脚本 (纯就地改写，不新增文件，避免改 pbxproj)

处理体检报告命中的两类 iOS 16 API：
  1. NavigationStack { / NavigationStack(path: )  ->  NavigationView (iOS 15 原生)
  2. .presentationDetents([...])                   ->  整行删除 (iOS 15 无对应 API，用默认 sheet 高度)

防御性处理(体检未命中但可能存在)：
  - .symbolEffect(...)  iOS 17 专属，整行删除

幂等：已在文件头部写入标记 // >>>IOS15PORTED>>>，重复运行不会二次改写。
"""
import os
import re
import sys

TARGET_DIR = sys.argv[1] if len(sys.argv) > 1 else "src/ios"
MARK = "// >>>IOS15PORTED>>>"

# 不做移植的目录：AgentWidget 是 iOS 17 的 Live Activity / 灵动岛扩展，
# iOS 15 设备根本用不上，改写它零收益，历史上还被误删过多层尾随闭包。
SKIP_DIRS = {"AgentWidget", "AgentWidgetExtension"}


def port_file(path: str) -> bool:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if MARK in src:
        return False
    original = src

    # 1) NavigationStack(...) / NavigationStack {  ->  NavigationView
    src = re.sub(r"\bNavigationStack(\s*[\(\{])", r"NavigationView\1", src)

    # 2) 删除独立的 .presentationDetents([...]) 行 (iOS 16 专属)
    src = re.sub(
        r"^\s*\.presentationDetents\(\[[^\]]*\]\)\s*$\n",
        "",
        src,
        flags=re.MULTILINE,
    )

    # 3) 防御：删除独立的 .symbolEffect(...) 行 (iOS 17 专属)
    src = re.sub(
        r"^\s*\.symbolEffect\([^)]*\)\s*$\n",
        "",
        src,
        flags=re.MULTILINE,
    )

    if src != original:
        src = MARK + "\n" + src
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        return True
    return False


def main() -> None:
    if not os.path.isdir(TARGET_DIR):
        print(f"[ios15_port] 目录不存在: {TARGET_DIR}", file=sys.stderr)
        sys.exit(1)

    count = 0
    scanned = 0
    for dp, dirs, files in os.walk(TARGET_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".swift"):
                scanned += 1
                if port_file(os.path.join(dp, fn)):
                    count += 1
    print(f"[ios15_port] 扫描 {scanned} 个 .swift 文件，改写 {count} 个。")


if __name__ == "__main__":
    main()
