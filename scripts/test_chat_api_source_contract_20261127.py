"""Portable source-contract checks, not execution of Swift/network/UI."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'src/ios'
def read(p): return (root/p).read_text()
engine=read('Providers/ProviderChatAPI.swift');agent=read('Providers/OpenAI/OpenAIAgentProvider.swift');raw=read('Providers/OpenAI/OpenAIProvider.swift');detail=read('Views/Providers/ProviderInstanceDetailView.swift');add=read('Views/Providers/AddProviderView.swift')
stream=agent.split('    func streamChatAPINegotiated(',1)[1].split('    private func streamChatCompletions(',1)[0]
checks={
'add defaults automatic without rejected setup sheet': 'chatAPIFormatMode: ProviderChatAPIMode = .automatic' in add and 'chatAPISetupTarget' not in add,
'project registration':all(read('Minis.xcodeproj/project.pbxproj').count(token)==1 for token in ['CB83E001 /* ProviderChatAPI.swift in Sources */ =','CB83E002 /* ProviderChatAPI.swift */ =','CB83E002 /* ProviderChatAPI.swift */,','CB83E001 /* ProviderChatAPI.swift in Sources */,']),
'explicit endpoint pair only': all(x in engine for x in ['text.contains("only supports " + other)','text.contains(current + " is disabled")','[400,403,404,405].contains(status)']),
'negotiation before parser consumes any event':stream.index('catch let rejection')<stream.index('for try await event') and stream.count('catch let rejection')==1,
'bounded and denies tool continuations': all(x in stream for x in ['budget.take()','last.role == .user','case .toolUse, .toolResult: return true']),
'no persist on thinking-only or tool-only finish': 'if completed && content' in stream and 'case .refusal,.toolUse: completed=false' in stream and '.thinkingDelta' not in stream,
'settings observes verified history': all(x in detail for x in ['ProviderChatAPIHistory.didChange','ProviderChatAPI.status(for: instance)','guard !Task.isCancelled','detectedChatFormat']),
'long forbidden reason not sliced before display': '[403] access denied: \\(safeReason())' in raw and 'replacingOccurrences(of: key' in raw,
}
print(json.dumps(checks,indent=2));raise SystemExit(not all(checks.values()))
