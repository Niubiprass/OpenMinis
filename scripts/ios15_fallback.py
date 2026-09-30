#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iOS 15 兜底修复脚本 (钉版本移植第二阶段补充)
==========================================

运行时机: 在 ios15_port_v2.py / ios15_runtime_fixes.py 之后, xcodebuild 之前。
作用: 解决 autofix 的"加 @available 注解"策略收敛不了的**真实 iOS 16/17 依赖**。
      这些依赖要么用了 iOS 16 才有的类型/API, 要么需要真实兜底, 机械注解解决不了。

所有变换**幂等**, 可重复运行不破坏; 尽量不依赖 @available 注解(避免被其它步骤改掉)。

设计原则 (对齐"大版本才同步、死功能不保"的用户策略):
  1. 核心 UI (UnifiedModelPicker 选模型) -> 改写 body 成 iOS 15 兼容版, 调用点零改动。
  2. iOS 15 上框架根本不存在的功能 (AlarmKit / AppIntents / Siri) -> 整类型/整方法标记
     @available(iOS 16, *), 在 iOS 15 上直接编译掉(本来也是死功能)。
  3. 调用点守卫 / 兜底 -> NotificationNavigationStore 用垫片隔离、forceSyncMemory 用
     #available 守卫、可选解包补链、缺失符号补桩。
"""
import sys
import os
import re

ROOT = sys.argv[1] if len(sys.argv) > 1 else "src/ios"


def edit(relpath, func, label=None):
    """对 ROOT 下的文件做幂等变换。func(old_text)->new_text。"""
    p = os.path.join(ROOT, relpath)
    if not os.path.isfile(p):
        print("  SKIP (文件不存在):", relpath)
        return
    t = open(p, encoding="utf-8", errors="replace").read()
    n = func(t)
    if n != t:
        open(p, "w", encoding="utf-8").write(n)
        print("  EDIT ✅", relpath, ("(" + label + ")") if label else "")
    else:
        print("  no-op  ", relpath, ("(" + label + ")") if label else "")


# ---------------------------------------------------------------------------
# 1) UnifiedModelPicker: 改写 body 成 iOS 15 兼容版 (NavigationView / 无抽屉 / 无 detents)
# ---------------------------------------------------------------------------
def fix_unified_model_picker(t):
    # 去掉 struct 上方可能由其它步骤加的 @available(iOS 16/17)
    t = re.sub(
        r"\n[ \t]*@available\(iOS\s+1[67][^\n]*\n(struct UnifiedModelPicker: View \{)",
        r"\n\1", t)
    # NavigationStack -> NavigationView (该文件内仅出现在 .sheet 内容里, iOS 15 可用)
    t = t.replace("NavigationStack {", "NavigationView {")
    # .searchable 的 placement: .navigationBarDrawer(displayMode:) 是 iOS 16 专属 -> 去掉 placement
    t = re.sub(
        r'\.searchable\(text: \$searchText, placement: \.navigationBarDrawer\(displayMode: \.always\), prompt: "Search"\)',
        r'.searchable(text: $searchText, prompt: "Search")', t)
    # .presentationDetents([.medium, .large]) 是 iOS 16 -> 整行删除
    t = re.sub(r"\n[ \t]*\.presentationDetents\(\[[^\]]*\]\)", "", t)
    return t


# ---------------------------------------------------------------------------
# 2) 整类型标记 @available(iOS 16, *): 死功能在 iOS 15 上编译掉
#    (AlarmKit 桥接、AppIntents 实体 —— 在 iOS 15 巨魔上框架本就不存在)
# ---------------------------------------------------------------------------
TOP_TYPE_RE = re.compile(
    r"^(?P<ind>[ \t]*)(?:(?:public|private|internal|fileprivate|open|final|indirect|"
    r"static|class|@\w+(?:\([^)]*\))?)\s+)*(?P<kw>struct|class|enum|protocol|extension|actor)\b")

def mark_toplevel_types_available(t, avail="iOS 16, *"):
    lines = t.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = TOP_TYPE_RE.match(line)
        if m and m.group("ind") == "":
            # 看上一非空行是否已有 @available
            prev = ""
            for k in range(i - 1, -1, -1):
                if lines[k].strip():
                    prev = lines[k]
                    break
            if "@available" not in prev:
                out.append("@available(%s)" % avail)
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 3) 标记"包含某子串的方法"为 @available(iOS 16, *) (向上找最近的 func/var 声明)
# ---------------------------------------------------------------------------
def mark_method_containing(t, needle, avail="iOS 16, *"):
    lines = t.split("\n")
    for i, line in enumerate(lines):
        if needle in line:
            # 向上找最近的 func/subscript 声明 (不要匹配到 let/var 语句本身)
            for j in range(i, -1, -1):
                if re.match(
                    r"^[ \t]*(?:public |private |internal |fileprivate |open |final |"
                    r"static |override |class |@\w+\s*)*(?:func|subscript)\b", lines[j]):
                    prev = ""
                    for k in range(j - 1, -1, -1):
                        if lines[k].strip():
                            prev = lines[k]
                            break
                    if "@available" not in prev:
                        lines.insert(j, "@available(%s)" % avail)
                    break
            break
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4) HelperSheet: helperTranscriptSheetStyle() 包一层 #available 兜底
# ---------------------------------------------------------------------------
def fix_helper_transcript_style(t):
    old = (
        "    func helperTranscriptSheetStyle() -> some View {\n"
        "        modifier(HelperTranscriptSheetStyle())\n"
        "    }")
    new = (
        "    @ViewBuilder\n"
        "    func helperTranscriptSheetStyle() -> some View {\n"
        "        if #available(iOS 16, *) {\n"
        "            self.modifier(HelperTranscriptSheetStyle())\n"
        "        } else {\n"
        "            self\n"
        "        }\n"
        "    }")
    if old in t:
        return t.replace(old, new)
    return t


# ---------------------------------------------------------------------------
# 5) forceSyncMemory() (iOS 17) -> #available 守卫
# ---------------------------------------------------------------------------
def fix_force_sync_memory(t):
    # 调用点守卫 (实际写法: Task { await forceSyncMemory() })
    t = t.replace(
        "await forceSyncMemory()",
        "if #available(iOS 17, *) { await forceSyncMemory() }")
    # 函数本体若用 iOS 17 API, 函数本身也要标 @available(iOS 17, *)
    t = mark_method_containing(
        t, "private func forceSyncMemory()", avail="iOS 17, *")
    return t


# ---------------------------------------------------------------------------
# 6) SystemVoiceCatalog: iOS 15 的 languageCode 变可选 -> 补可选链 + 默认值
# ---------------------------------------------------------------------------
def fix_system_voice_catalog(t):
    return t.replace(
        "Locale(identifier: tag).language.languageCode?.identifier.lowercased()",
        'Locale(identifier: tag).language.languageCode?.identifier?.lowercased() ?? ""')


# ---------------------------------------------------------------------------
# 7) LoggingManager: ish_set_verbose_trace 符号缺失 -> 补私有桩 (no-op)
# ---------------------------------------------------------------------------
def fix_ish_verbose_trace(t):
    if "func ish_set_verbose_trace" in t:
        return t  # 已经补过
    stub = (
        "\n\n"
        "// iOS 15 兜底: 上游期望宿主提供 ish_set_verbose_trace (verbose 跟踪开关),\n"
        "// 在 iOS 15 构建里该符号未声明。补一个私有 no-op 桩, 不影响功能。\n"
        "private func ish_set_verbose_trace(_ enabled: Bool) {}\n")
    return t.rstrip() + stub


# ---------------------------------------------------------------------------
# 8) NotificationNavigationStore: iOS 16 通知深链类型 -> 垫片隔离 (调用点零改动语义)
#    新文件 src/ios/Shared/iOS15NotificationNavShim.swift 提供 iOS 15 安全包装,
#    内部用 #available 守卫; 同时改写 ContentView 三个调用点改调垫片。
# ---------------------------------------------------------------------------
SHIM_PATH = "Shared/iOS15NotificationNavShim.swift"
SHIM_CONTENT = '''\
// iOS 15 兜底: NotificationNavigationStore 是 iOS 16 的通知深链类型。
// 在 iOS 15 上用垫片隔离, 调用点不改。深链在 iOS 15 上静默 no-op。
import Foundation

func nnsMarkHandled() {
    if #available(iOS 16, *) {
        NotificationNavigationStore.shared.markHandled()
    }
}

func nnsTakePending() -> String? {
    if #available(iOS 16, *) {
        return NotificationNavigationStore.shared.takePending()
    }
    return nil
}

var nnsHandledRecently: Bool {
    if #available(iOS 16, *) {
        return NotificationNavigationStore.shared.handledRecently
    }
    return false
}
'''


def fix_notification_nav_store(t):
    t = t.replace("NotificationNavigationStore.shared.markHandled()", "nnsMarkHandled()")
    t = t.replace("NotificationNavigationStore.shared.takePending()", "nnsTakePending()")
    t = t.replace("NotificationNavigationStore.shared.handledRecently", "nnsHandledRecently")
    return t


def main():
    print("== iOS 15 兜底修复 (ROOT=%s) ==" % ROOT)

    edit("Views/Providers/UnifiedModelPicker.swift",
         fix_unified_model_picker, "body 改写 iOS15 兼容")

    edit("NativeOffloads/AlarmOffloadBridge.swift",
         mark_toplevel_types_available, "整类型 @available(iOS16)")
    edit("Agent/Intents/ModelSelectionEntity.swift",
         mark_toplevel_types_available, "整类型 @available(iOS16)")

    edit("Agent/Jobs/HelperRunner.swift",
         lambda t: mark_method_containing(t, "helperWrapUpPrompt(reason: HelperWrapUpReason)"),
         "标记 helperWrapUpPrompt @available")
    edit("Agent/Jobs/HelperRunner.swift",
         lambda t: mark_method_containing(t, "SendPromptIntent.extractResponseText"),
         "标记 SendPromptIntent 调用方法 @available")

    edit("Views/Chat/HelperSheet.swift",
         fix_helper_transcript_style, "helperTranscriptSheetStyle 兜底")

    edit("Views/Settings/MemoryManagementView.swift",
         fix_force_sync_memory, "forceSyncMemory #available 守卫")

    edit("Providers/Voice/SystemVoiceCatalog.swift",
         fix_system_voice_catalog, "languageCode 可选链兜底")

    edit("Shared/LoggingManager.swift",
         fix_ish_verbose_trace, "ish_set_verbose_trace 补桩")

    # NotificationNavigationStore 垫片 + ContentView 调用点改写
    edit("Views/ContentView.swift",
         fix_notification_nav_store, "调用点改调垫片")
    shim_full = os.path.join(ROOT, SHIM_PATH)
    os.makedirs(os.path.dirname(shim_full), exist_ok=True)
    if not os.path.isfile(shim_full):
        open(shim_full, "w", encoding="utf-8").write(SHIM_CONTENT)
        print("  CREATE ✅", SHIM_PATH)
    else:
        print("  exists ", SHIM_PATH)

    print("== iOS 15 兜底修复完成 ==")


if __name__ == "__main__":
    main()
