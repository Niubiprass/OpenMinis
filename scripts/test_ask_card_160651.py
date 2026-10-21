#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests: [T-115-ask-card] 提问卡片 (App Store 1.15 "向用户提问").

Official spec: 助手在对话中用卡片提问/请求确认；多题逐题作答；没有"始终
允许"；超时返回未确认。Voice answering and in-notification answering are
NOT in this port (iOS 15.5 constraints) — the card UI, inline answers,
cancel and the 10-minute timeout are.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


print("== [T-115-ask-card] contract tests ==")

# 1) Kind exists and is NOT a tool kind.
models = read("src/ios/Agent/Chat/ChatModels.swift")
check("AssistantBlockKind has .questionCard", "case questionCard" in models)
infra = read("src/ios/Agent/MessageList/MessageListInfrastructure.swift")
check("isToolKind excludes questionCard",
      re.search(r"case \.text, \.thinking, \.info, \.questionCard:\s*return false", infra) is not None)

# 2) Decode path (persisted toolUse -> block) resolves ask_user.
store = read("src/ios/Agent/Chat/ChatStore.swift")
check("ChatStore kind resolution maps ask_user", re.search(r'case "ask_user":[\s\S]{0,500}?kind = \.questionCard', store) is not None)

# 3) Streaming path resolves ask_user too.
sse = read("src/ios/Agent/Chat/AIChatViewModel+SSEStream.swift")
check("SSE blockKind maps ask_user", re.search(r'case "ask_user": \.questionCard', sse) is not None)

# 4) Tool registration (with explicit no-always-allow + timeout semantics).
td = read("src/ios/Agent/Chat/AIChatViewModel+ToolDefinitions.swift")
check("ask_user tool registered", re.search(r'name: "ask_user"', td) is not None)
check("ask_user mentions pause until answer", "PAUSES" in td or "pauses" in td)
check("ask_user mentions unconfirmed timeout", "未确认" in td)
check("ask_user has questions param", '"questions": AgentToolParam(type: .array' in td)

# 5) Param type plumbing for .array across providers.
prov = read("src/ios/Providers/AgentProvider.swift")
check("AgentParamType has .array", "case array" in prov)
anthropic = read("src/ios/Providers/Anthropic/AnthropicAgentProvider.swift")
check("Anthropic schema maps .array", re.search(r"case \.array: \.array", anthropic) is not None)
gemini = read("src/ios/Providers/Gemini/GeminiAgentProvider.swift")
check("Gemini schema maps ARRAY", re.search(r"case \.array: return \"ARRAY\"", gemini) is not None)

# 6) Handler wired into the tool dispatch switch.
ct = read("src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift")
check("dispatch switch has ask_user", re.search(r'case "ask_user":', ct) is not None)
check("handleAskUser exists", "func handleAskUser(argsJson:" in ct)
check("handler waits with checked continuation", "withCheckedContinuation" in ct)
check("handler has 600s timeout", "let timeout: TimeInterval = 600" in ct)
check("handler resumes unconfirmed on cancel", "onCancel:" in ct)

# 7) VM state + resume APIs.
vm = read("src/ios/Agent/Chat/AIChatViewModel.swift")
check("@Published activeQuestionCard", "@Published var activeQuestionCard: ActiveQuestionCard?" in vm)
check("card is reference state for timeout task", "final class ActiveQuestionCard" in vm)
check("continuation state handles pre-install cancel", "class AskUserContinuationState" in ct and "func install(" in ct and "resumeImmediately" in ct)
check("timeout task is cancelled after resume", "card.timeoutTask?.cancel()" in ct)
check("submitQuestionAnswers API", "func submitQuestionAnswers(_ answers: [String: String])" in vm)
check("cancelQuestionCard API", "func cancelQuestionCard()" in vm)

# 8) UI: card view exists and is rendered.
qcv_path = ROOT / "src/ios/Views/Chat/QuestionCardView.swift"
check("QuestionCardView.swift exists", qcv_path.exists())
qcv = qcv_path.read_text(encoding="utf-8", errors="replace") if qcv_path.exists() else ""
check("card view has live/interactive state", "private var isLive: Bool" in qcv)
check("card view submits via vm", "vm.submitQuestionAnswers" in qcv)
check("card view cancels via vm", "vm.cancelQuestionCard()" in qcv)
check("card view shows unconfirmed notice", "未确认" in qcv)
abv = read("src/ios/Views/Chat/AssistantBlockView.swift")
check("AssistantBlockView renders QuestionCardView", "QuestionCardView(block: block)" in abv)

# 9) List plumbing: accessibility id, estimate, tool-name logging.
v3 = read("src/ios/Agent/MessageList/CollectionViewMessageListV3.swift")
check("V3 accessibility id", 'case .questionCard: return "assistantQuestionBlock"' in v3)
check("V3 precalc estimate branch", re.search(r"case \.questionCard:\s*// \[T-115-ask-card\][\s\S]*?setEstimatedHeight", v3) is not None)
check("V3 height estimator exists", "estimateQuestionCardHeight" in v3)
check("V3 tool-name log branch", r'case .questionCard: "ask_user"' in v3)

# 10) Detail sheet + clipboard export + background-task summary handle it.
toolsheet = read("src/ios/Views/Chat/ToolLiveSheet.swift")
check("ToolLiveSheet nav detail", re.search(r"case \.questionCard:\s*return \"ask_user\"", toolsheet) is not None)
check("ToolLiveSheet icon", "case .questionCard: Image(systemName: \"questionmark.circle\")" in toolsheet)
cmv = read("src/ios/Views/Chat/ChatMessageViews.swift")
check("fullMessageText includes card", "case .questionCard:" in cmv)
bt = read("src/ios/Agent/Chat/AIChatViewModel+BackgroundTask.swift")
check("BackgroundTask tool name", re.search(r"case \.questionCard: toolName = \"ask_user\"", bt) is not None)
check("toolDescription covers card", re.search(r"case \.questionCard:\s*return AppLocalized\(\"向你提问\"\)", models) is not None)

# 11) iOS 15 compatibility: no iOS16-only API in the new view.
check("no LabeledContent in card view", "LabeledContent" not in qcv)
check("no PageTabViewStyle in card view", "PageTabViewStyle" not in qcv)

# 12) Negative: no always-allow concept added anywhere.
check("no 'always allow' persisted", "alwaysAllow" not in ct and "AlwaysAllow" not in ct)

# 13) [T-115-ask-alert] Waiting question stays discoverable outside its chat.
life = read("src/ios/Agent/Chat/ChatLifecycleSupport.swift")
check("alert center exists", "final class QuestionAlertCenter" in life)
check("alert registers the waiting card", "func questionAppeared(sessionId: String?, toolUseId: String" in life)
check("alert clears on answer/cancel/timeout", "func questionEnded(toolUseId: String)" in life)
check("alert posts a local notification", "UNNotificationRequest(" in life and '"sessionId": item.sessionId' in life)
check("alert notification does not expose the question", 'content.body = AppLocalized("打开 Minis 查看并回答，任务正在等待。")' in life)
check("alert has an in-app banner", "struct QuestionAlertBanner" in life)
check("handler registers alert when card appears", "QuestionAlertCenter.shared.questionAppeared(" in ct)
check("submit clears alert", "QuestionAlertCenter.shared.questionEnded(toolUseId: card.toolUseId)" in vm)
app = read("src/ios/MinisApp.swift")
check("banner mounted at app root", "QuestionAlertBanner()" in app)
chat = read("src/ios/Views/Chat/AIChatView.swift")
check("chat reports its visible session", "QuestionAlertCenter.shared.setVisibleSession(sessionId)" in chat)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL PASS")