#!/usr/bin/env python3
"""Source contracts for the plugin workbench (Settings → 插件开发).

Locks four things that broke or were half-built before:
  1. iOS 15 Section syntax — a footer needs the `header:` form.
  2. The analysis stage must hand over REAL analyzer commands, not prose.
  3. The project→chat handoff must be staged in QuickActionRouter and
     consumed by a new draft (no pasteboard-only path).
  4. The old, stale `ios15-build.yml` packager stays retired.
Plus the MiniSight settings that live on the same screen (regression guard).
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEV = ROOT / "src/ios/Views/Settings/PluginDevView.swift"
ROUTER = ROOT / "src/ios/Shared/QuickActionRouter.swift"
CHAT = ROOT / "src/ios/Views/Chat/AIChatView.swift"
MINISIGHT = ROOT / "src/ios/Views/Settings/MiniSightSettingsView.swift"

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


dev = DEV.read_text()
router = ROUTER.read_text()
chat = CHAT.read_text()
mini = MINISIGHT.read_text()

# 1. Section syntax: `Section("x") { ... } footer:` is invalid on iOS 15.
bad = [m.group(0) for m in re.finditer(r'Section\("[^"]*"\) \{', dev)]
# A lone Section("x") { is fine; only the ones followed by footer: matter.
bad_footer = [m.group(0) for m in re.finditer(r'Section\("[^"]*"\) \{(?:(?!\n            \}).)*?\n            \} footer:', dev, re.S)]
check("无 Section(\"…\"){ } footer: 写法", not bad_footer, str(bad_footer[:2]))

# 2. Analysis commands.
check("分析命令生成器存在", "static func analyzerCommands(for" in dev)
for token in ("rz-bin", "rizin", "pdg", "LD_LIBRARY_PATH", "/opt/twork-analyzer"):
    check(f"命令含 {token}", token in dev)
check("提示词注入命令块", "先用本机分析器取证" in dev)
check("命令写入提示词", "analysisCommands.trimmingCharacters" in dev)
check("保存时刷新命令", "project.analysisCommands = PluginProject.analyzerCommands" in dev)
check("界面可复制命令", 'Button("复制命令")' in dev)
check("analysisCommands 参与编解码", dev.count("analysisCommands") >= 5
      and "forKey: .analysisCommands" in dev)

# 3. Handoff staging.
check("路由器有 stage 方法", "func stageProjectHandoff" in router)
check("路由器一次性消费", "func takePendingHandoff" in router)
check("消费后清空 prompt", "pendingPrompt = nil" in router)
check("sheet 创建时 stage", "quickActionRouter.stageProjectHandoff"
      if "quickActionRouter.stageProjectHandoff" in dev
      else "QuickActionRouter.shared.stageProjectHandoff" in dev)
check("详情页 stage 而非仅剪贴板", "stageProjectHandoff(prompt: project.workflowPrompt" in dev)
check("新草稿消费交接", "takePendingHandoff()" in chat and "vm.inputText = handoff.prompt" in chat)
check("只在新草稿消费", "if cached.isNew, vm.inputText" in chat)

# 4. Retired packager.
check("ios15-build.yml 已删除", not (ROOT / ".github/workflows/ios15-build.yml").exists())
wf = (ROOT / ".github/workflows/ios15-v64-repair.yml").read_text()
check("v64 Repair 仍是唯一出包流程", "ios15-v64-repair.yml" in wf)
check("新测试已接入 CI", "test_plugin_workbench_160651.py" in wf)
check("信号测试已接入 CI", "test_minisight_signal_160651.py" in wf)

# 5. Same-screen MiniSight regressions.
check("重力开关仍在", '"minisight.gravity"' in mini)
check("尺寸仍是 36...140 步进 2", "36...140, step: 2" in mini)
check("设置先落盘再通知", "synchronize()" in mini)

failed = [(n, d) for n, ok, d in results if not ok]
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + (f"  [{d}]" if not ok and d else ""))
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
