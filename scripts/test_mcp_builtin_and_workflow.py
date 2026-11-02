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
OAUTH = (ROOT / "src/ios/Providers/AgentProvider.swift").read_text()
OAI = (ROOT / "src/ios/Providers/OpenAI/OpenAIAgentProvider.swift").read_text()
OAIP = (ROOT / "src/ios/Providers/OpenAI/OpenAIProvider.swift").read_text()
MKEYS = (ROOT / "src/ios/Providers/ProviderMultiKeys.swift").read_text()
APROV = (ROOT / "src/ios/Providers/AgentProvider.swift").read_text()
VM = (ROOT / "src/ios/Agent/Chat/AIChatViewModel.swift").read_text()
RB = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+RequestBudget.swift").read_text()
COLL = (ROOT / "src/ios/Agent/MessageList/CollectionViewMessageListV3.swift").read_text()
INFRA = (ROOT / "src/ios/Agent/MessageList/MessageListInfrastructure.swift").read_text()
LLME = (ROOT / "src/ios/Providers/LLMError.swift").read_text()
FALLBACK = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+Fallback.swift").read_text()
NLMON = (ROOT / "src/ios/Shared/NetworkMonitor.swift").read_text()
XCSTR = (ROOT / "src/ios/Localizable.xcstrings").read_text()
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
ok("credentialResourceIdentity" in OAIP and "SHA256.hash" in OAIP, "Key 指纹不泄露原文")
ok("oauth:" in OAIP and "codexAccountId" in OAIP, "OAuth 按账号隔离")
ok("resourceIdentity" in OAUTH, "推理回显记录凭据资源")
ok("credentialResourceIdentity" in OAIP and "SHA256" in OAIP, "资源用 Key 指纹标识")
ok("resourceIdentity: self.responsesResourceIdentity" in OAI, "生成时写入当前资源")
ok("echo.resourceIdentity == self.responsesResourceIdentity" in OAI, "跨资源不复用旧 ID")
ok('"fc_syn_' in OAI and 'entry["id"] = safeFcId' not in OAI, "函数调用始终用合成 ID")
ok("case requestTooLarge(" in LLME, "新增请求体过大错误")
ok("var isRequestTooLarge" in LLME, "可区分请求体过大")
ok("if case .requestTooLarge = self { return 413 }" in LLME, "413 保留结构化状态")
ok("case .requestTooLarge: return .requestTooLarge" in MKEYS, "Key 层识别请求体过大")
ok(".requestTooLarge, .cancelled, .unknown:" in LLME, "请求体过大不盲目重发")
ok("case .rateLimited, .invalidAPIKey, .providerError, .requestTooLarge:" in LLME,
   "请求体过大可进入缩体重试")
ok("provider.bodyCap." in LLME and "static let floor" in LLME, "按站点学习请求体上限")
ok("byteBudgetedMessages(" in RB and "estimateRequestBytes(" in RB, "通用请求体预算已实现")
ok("reasoningEcho = nil" in RB, "旧推理回显也计入裁剪")
for path in ["src/ios/Providers/Anthropic/AnthropicAgentProvider.swift","src/ios/Providers/Gemini/GeminiAgentProvider.swift"]:
 text=(ROOT/path).read_text()
 ok("byteBudgetedMessages(" in text and "requestBytesAtDispatch" in text, path.split("/")[3]+" 发送前裁剪")
 if "Anthropic" in path:
  ok(text.index("let requestMessages") < text.index("#if DEBUG"), "Anthropic 裁剪变量不在 DEBUG 内")
for path in ["src/ios/Providers/Anthropic/AnthropicProvider.swift","src/ios/Providers/Gemini/GeminiProvider.swift"]:
 text=(ROOT/path).read_text()
 ok(("case 413" in text or "statusCode == 413" in text) and "noteRejected" in text, path.split("/")[3]+" 413 学习上限")
ok("private func guardRequestBodySize(_ body: inout" in OAIP, "守卫可原地裁剪请求体")
ok(") async throws -> (AsyncThrowingStream<String, Error>, Int) {\n        var body = body" in OAIP,
   "streamRaw 参数先转可变局部量")
ok("requestTooLargeServerDetail" in LLME and "detail.isEmpty" in LLME, "服务器 413 与本地超限可区分")
ok("error.isRequestTooLarge" in FALLBACK, "本地/服务器 413 均先缩体重试")
ok("static let floor = 128 * 1024" in LLME, "站点上限有 128KB 下限")
ok("officialHosts" in LLME and "openai.azure.com" in LLME, "官方/Azure 不按小站点上限")
ok('"api.anthropic.com"' in LLME and '"generativelanguage.googleapis.com"' in LLME,
   "官方三大域都在白名单")
ok("lastRequestBudgetKey" in OAIP and '"|image"' in OAIP, "聊天与图片预算分开记录")
ok("$0 / 2" in LLME, "413 后站点上限减半收敛")
ok("maxAge" in LLME and "removeObject(forKey: prefix + key)" in LLME,
   "学到的上限七天后恢复默认")
ok("gatewayRetries" in OAUTH and "gatewayRetries < gatewayRetrySlots" in OAUTH,
   "524 重试名额独立于 priority")
ok("var bodyCapRetryRemaining = 2" in FALLBACK, "最多两次缩体收敛")
ok("bodyCapRetryRemaining = 1" in FALLBACK and "requestTooLargeServerDetail == nil" in FALLBACK,
   "本地超限只额外重试一次")
ok("trimRequestBody(&body, target: providerCap)" in OAIP, "发送前按站点上限裁剪")
ok('if type == "input_image"' in OAIP, "裁剪保留 Responses 图片占位结构")
ok('removeValue(forKey: "encrypted_content")' in OAIP, "裁剪旧推理密文但保留 ID")
ok('"_omitted":"older tool arguments' in OAIP, "旧工具参数换成合法 JSON 占位")
ok("(12, 4_000), (6, 1_500), (2, 600), (0, 300)" in OAIP, "分级裁剪且保留最新消息")
ok('noteRejected(key: key' in OAIP, "413 后记住更低的站点上限")
ok("bodyCapRetryRemaining" in FALLBACK and "retrying the SAME entry" in FALLBACK,
   "413 先同模型缩体重试")
ok("pathGenerationBeforeAttempt" in FALLBACK and "pathSnapshot().generation" in FALLBACK,
   "换网后跳过剩余倒计时")
ok("path.satisfied, path.generation != pathAtFailure" in FALLBACK,
   "仅在恢复联网时提前重试")
ok("path.usesInterfaceType" in NLMON and "availableInterfaces" not in NLMON.split("activeInterfaceTypes")[1].split("}")[0],
   "按活动网卡而不是可用网卡识别切换")
ok("pathExpensive" in NLMON and "isExpensive" in NLMON, "VPN 下用昂贵标志识别底层蜂窝")
ok("@unchecked Sendable" in NLMON, "网络监听可跨任务读取")
ok("concurrency limit" in MKEYS and "requests-per-minute" in MKEYS,
   "并发与每分钟限流归为限流")
ok("kPerImageMaxBytes = 640 * 1024" in VM and "kRequestImageMaxBytes = 768 * 1024" in VM,
   "图片预算低于常见 1MB 网关上限")
ok("kPerImageMaxBytes = 640 * 1024" in (ROOT / "src/ios/MinisTests/Standalone/ImageBudgetBase64Tests.swift").read_text(),
   "图片预算测试常量同步")
ok("Network line failed — retrying in %llds" in XCSTR, "线路重试提示已本地化")
ok("bridge.autoRetryIsNetwork" in COLL and "autoRetryIsNetwork" in INFRA,
   "活动消息接入线路重试状态")
ok("NetworkLineHealth" in NLMON and "alternativeNetwork" in NLMON,
   "有十分钟线路记忆")
ok("nonisolated(unsafe) private static var observations" in NLMON,
   "线路记忆静态表声明并发安全")
ok("autoRetryNetworkHint" in FALLBACK and "最近可用" in XCSTR,
   "有其它线路可用证据时写进提示")
ok("[413] Request body is too large (%@, site limit %@)" in XCSTR, "请求过大提示已本地化")
ok("这个分组暂时没有可用渠道" in XCSTR, "无可用渠道提示已本地化")
ok("Gateway timed out" in XCSTR and "请求体超过站点限制" in XCSTR and "request too large" in XCSTR,
   "补全审查指出的本地化键")
ok("图片超过这个站点的请求上限" in XCSTR, "图片 413 与文本 413 分开提示")
ok("这条网络的出口 IP 被拦截" in XCSTR, "403 区分 Key 与出口 IP")
ok("case .networkError: return .network" in MKEYS, "网络错误有独立分类")
ok("case .network, .other, .requestTooLarge: return false" in MKEYS,
   "网络错误不轮换、不停用 Key")
ok("case .network, .requestTooLarge, .other: return nil" in MKEYS,
   "网络与 413 无 Key 冷却")
ok("kind.mayTryAnotherKey || kind == .network" in MKEYS, "网络失败仍记 Key 统计")
ok("case 403: return .forbidden" in MKEYS, "403 保留独立分类")
ok("[403] access denied" in (ROOT / "src/ios/Providers/Anthropic/AnthropicProvider.swift").read_text(),
   "Anthropic 403 不当作 Key 无效")
ok("[403] access denied" in (ROOT / "src/ios/Providers/Gemini/GeminiProvider.swift").read_text(),
   "Gemini 403 不当作 Key 无效")
ok("case .forbidden: return nil" in MKEYS, "403 不冷却 Key（可能是出口 IP 拦截）")
ok("if statusCode == 403" in OAIP and "[403] access denied" in OAIP, "403 不再当作 Key 无效")
ok("case 413: return .requestTooLarge" in MKEYS, "413 归为请求体过大")
ok(".requestTooLarge: return false" in MKEYS, "413 不换 Key")
ok("case 520...523: return .other" in MKEYS, "Cloudflare 源站错误不轮换 Key")
ok("(520...523).contains(code)" in MKEYS, "结构化 520 同样不轮换 Key")
ok(MKEYS.index("no available channel") < MKEYS.index("Only a leading HTTP status"),
   "无可用渠道在状态码之前判定")
ok("case 524: return .gatewayTimeout" in MKEYS, "524 归为网关超时")
ok("Gateway timed out" in MKEYS, "524 有独立类别")
ok("kind == .gatewayTimeout" in APROV and "gatewayRetrySlots" in APROV,
   "524 先同 Key 重试")
ok("maxRequestBodyBytes = 8 * 1024 * 1024" in OAIP, "请求体上限降到 8MB")
ok("statusCode == 413" in OAIP and "noteRejected" in OAIP, "413 记录站点上限并给可操作重试")
ok("520, 521, 522, 523, 524" in OAIP, "Cloudflare 源站错误归为可重试")
ok("kRequestImageMaxBytes = 768 * 1024" in VM, "图片总预算低于网关上限")
ok("larger than roughly 16KB" in VM and "524 timeout" in VM,
   "提示大文件分块写，避免 524")
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
