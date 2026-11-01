#!/usr/bin/env python3
"""Contracts for moving built-in device tools to MCP and adding the
per-session plugin-engineer workflow. Source only; no Xcode on iSH."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MCP = (ROOT / "src/ios/Views/MCP/MCPIntegrationsView.swift").read_text()
DEV = (ROOT / "src/ios/Views/Settings/PluginDevView.swift").read_text()
SETTINGS = (ROOT / "src/ios/Views/ContentView.swift").read_text()
CAPS = (ROOT / "src/ios/Views/Chat/SessionSkillsView.swift").read_text()
CHAT = (ROOT / "src/ios/Agent/Chat/AIChatViewModel.swift").read_text()
TOOLS = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift").read_text()
VIEW = (ROOT / "src/ios/Views/Chat/AIChatView.swift").read_text()

checks = []
def ok(cond, name):
    checks.append((name, bool(cond)))

ok("Minis 内置工具" in MCP, "MCP 页有内置工具分组")
ok("允许 AI 操作手机" in MCP and "HostAccessPermission.isEnabled" in MCP,
   "主机总开关已移到 MCP")
ok("MiniSightSettingsView()" in MCP and "操作指示器" in MCP,
   "操作指示器已移到 MCP")
ok("允许 AI 操作手机" not in DEV and "MiniSightSettingsView()" not in DEV,
   "旧插件页不再重复两段")
ok('Label("新建插件项目"' not in DEV, "旧插件页不再有新建项目")
ok('Section("插件开发")' not in SETTINGS, "设置首页移除插件开发入口")
ok("PluginDevView()" not in SETTINGS, "设置首页不再跳旧页")
ok("settings/plugin" not in SETTINGS, "旧深链未残留")

ok("工程 Agent" in CAPS and "插件工程师" in CAPS, "会话能力有插件工程师")
ok("SessionAgentWorkflow.setEnabled" in CAPS, "开关按会话保存")
ok("追加任务清单" in CAPS, "界面说明会追加而不是覆盖")
ok("promptFragment(for:" in CHAT and CHAT.count("SessionAgentWorkflow.promptFragment") >= 2,
   "初发和模型切换都注入工程流程")
ok("不得覆盖、遗忘" in CAPS and "待授权" in CAPS, "提示包含任务队列与授权状态")
ok("静态检查不能写成真机通过" in CAPS, "提示区分静态与真机")
for action in ("推送", "CI", "安装", "卸载", "注销", "重启"):
    ok(action in CAPS, f"逐项授权含 {action}")
ok("会话能力" in VIEW and 'AppLocalized("Skills in Session")' not in VIEW, "菜单改名为会话能力")
ok("MCP 集成 → Minis 内置工具" in TOOLS, "权限错误提示走新路径")
ok("allowsFullSwipe" in MCP or "ForEach(store.servers)" in MCP,
   "外部 MCP 列表仍在")

failed = [n for n, valid in checks if not valid]
for n, valid in checks:
    print(("PASS " if valid else "FAIL ") + n)
print(f"{len(checks)-len(failed)}/{len(checks)} passed")
sys.exit(1 if failed else 0)
