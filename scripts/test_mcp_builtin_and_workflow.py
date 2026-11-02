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
GATE = (ROOT / "src/ios/Agent/Chat/SessionWorkflowGate.swift").read_text()
PROJ = (ROOT / "src/ios/Minis.xcodeproj/project.pbxproj").read_text()
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
ok("先商讨" in CAPS and "推送和安装前硬停" in CAPS, "界面说明先商讨并硬停")
ok("追加任务清单" not in CAPS and "当前只做一项" not in CAPS, "移除旧串行任务说明")
ok("promptFragment(for:" in CHAT and CHAT.count("SessionAgentWorkflow.promptFragment") >= 2,
   "初发和模型切换都注入工程流程")
for text in ("先回答用户问题", "问结论是否正确", "照这个做吗", "问“推送吗”", "问“安装吗”", "结束本回合"):
    ok(text in GATE, f"提示含闸门：{text}")
ok("静态检查不能写成真机通过" in GATE, "提示区分静态与真机")
for action in ("git push", "gh workflow run", "install_app", "killall SpringBoard"):
    ok(action in GATE, f"闸门识别 {action}")
ok("checkFileTool" in GATE and '"file_write"' in GATE and '"file_edit"' in GATE,
   "结果确认前拦截写文件")
ok("STATUS.md" in GATE and ".notGated" in GATE, "STATUS 记录不被结果闸门拦")
ok("checkFileTool" in TOOLS, "分发层接入文件闸门")
ok("noteUserMessage" in CHAT, "用户发送时记录批准")
ok("submitQuestionAnswers" in CHAT and CHAT.count("noteUserMessage") >= 2, "问答卡答案也记录批准")
ok("SessionAgentWorkflow.check(command:" in TOOLS, "工具分发执行前调用闸门")
ok("workflowApprovedHost" in TOOLS, "批准后不重复弹主机确认")
ok("SkillStore.shared.setSessionOverride" in GATE, "插件模式自动启用工作流技能")
ok("clearSessionOverride" in GATE, "关闭模式只清理自动启用的技能")
ok("SessionWorkflowGate.swift in Sources" in PROJ, "新源码已加入 Xcode 工程")
ok("没有在当前这一步批准" in GATE, "拒绝信息说明等待批准")
ok("不要换别的方式绕过" in GATE, "提示禁止绕闸门")
ok('gitSubcommand' in GATE and '"-C"' in GATE, "支持 git -C 形式的推送")
ok('"mcp-appinst"' in GATE and '"dpkg"' in GATE and '"sbreload"' in GATE,
   "识别原生安装与注销")
ok('path=' in GATE and '".deb"' in GATE, "安装批准绑定包路径")
ok('10 * 60' in GATE, "批准十分钟过期")
ok('sameScope' in GATE and 'stored == signature' in GATE, "换命令/换包使批准失效")
ok("approvedGate == gate.rawValue" in GATE, "批准绑定到具体闸门")
ok("isApprovalText(_ raw: String, for gate: Gate)" in GATE, "各闸门批准词分开")
ok("会话能力" in VIEW and 'AppLocalized("Skills in Session")' not in VIEW, "菜单改名为会话能力")
ok("MCP 集成 → Minis 内置工具" in TOOLS, "权限错误提示走新路径")
ok("allowsFullSwipe" in MCP or "ForEach(store.servers)" in MCP,
   "外部 MCP 列表仍在")

failed = [n for n, valid in checks if not valid]
for n, valid in checks:
    print(("PASS " if valid else "FAIL ") + n)
print(f"{len(checks)-len(failed)}/{len(checks)} passed")
sys.exit(1 if failed else 0)
