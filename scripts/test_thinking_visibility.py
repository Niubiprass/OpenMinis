#!/usr/bin/env python3
"""Production waiting-predicate regression + thinking view source contracts.
Swift execution uses Foundation stubs on a Swift host; never claims UIKit proof.
"""
from pathlib import Path
import os, re, shutil, subprocess, tempfile
r = Path(__file__).resolve().parents[1]
m = (r/'src/ios/Agent/Chat/ChatModels.swift').read_text()
v = (r/'src/ios/Views/Chat/AssistantBlockView.swift').read_text()
c = (r/'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
start = m.index('    var shouldShowTypingIndicator: Bool {')
end = m.index('\n    }', start) + len('\n    }')
predicate = m[start:end]
assert 'blocks.allSatisfy({ $0.kind == .text && $0.content.isEmpty })' in predicate
assert '.id(block.id) // Never carry frozen' in v
thinking = v[v.index('struct ThinkingBlockView: View'):v.index('// MARK: - Typing Indicator')]
assert 'let thinkingBody = VStack' in thinking
assert '.fixedSize(horizontal: false, vertical: true)' in thinking
assert '.accessibilityHidden(true)' in thinking
assert '.frame(maxHeight: 300, alignment: .top)' in thinking
assert 'ScrollView { thinkingBody }' in thinking
assert 'frozenThinkingContent ??' in thinking
assert 'block.flushThinkingBuffer()' in thinking
assert 'if isExpanded.wrappedValue, !block.content.isEmpty' in thinking
sub = c[c.index('private func syncThinkingLayoutSubscriptions'):c.index('private func flushStreamingLayout')]
assert 'block.$content.dropFirst()' in sub
assert 'block.$isThinkingExpanded.removeDuplicates().dropFirst()' in sub
assert sub.index('.receive(on: DispatchQueue.main)') < sub.index('self.pendingTextLayoutItems.insert')
handler = c[c.index('            vm.textBlockLayoutSignal'):c.index('// 9. Text block filled')]
assert '.assistantFooter(message.id)' in handler
flush = c[c.index('private func doFlushStreamingLayout'):c.index('private func scheduleCoalescedScroll')]
for contract in ['case .assistantFooter(let mid):', 'ds.indexPath(for: item)', 'discardPrecalc: true', 'invalidateBlockMemos', 'clearCachedHeight()', 'snapshot.reconfigureItems']:
    assert contract in flush, contract
# Basic syntax sanity is NOT a Swift parser. CI must still build the real target.
print('Thinking visibility source contracts: PASS (NOT UIKit/runtime validation)', flush=True)
stubs = '''
import Foundation
enum Kind { case text, thinking, tool, info }
enum Status { case streaming, running, completed, failed }
struct Block { var kind: Kind; var content: String = ""; var toolStatus: Status? = nil }
struct Message {
 var blocks: [Block] = []
 var isAwaitingModelResponse = false
'''
checks = '''
}
var count = 0
func check(_ expected: Bool, _ message: Message, _ label: String) {
 precondition(message.shouldShowTypingIndicator == expected, label)
 count += 1
}
check(true, Message(), "opening wait")
check(true, Message(blocks: [Block(kind: .text)]), "empty text start is not output")
check(true, Message(blocks: [Block(kind: .text), Block(kind: .text)]), "multiple empty starts")
check(false, Message(blocks: [Block(kind: .text, content: "answer")]), "real text suppresses wait")
check(false, Message(blocks: [Block(kind: .thinking)]), "thinking header is visible; no fake reasoning")
check(false, Message(blocks: [Block(kind: .thinking, content: "provider supplied")]), "real thinking")
check(false, Message(blocks: [Block(kind: .info)]), "info header")
check(true, Message(blocks: [Block(kind: .text, content: "previous round")], isAwaitingModelResponse: true), "between rounds")
check(false, Message(blocks: [Block(kind: .tool, toolStatus: .running)], isAwaitingModelResponse: true), "running tool has its own feedback")
check(false, Message(blocks: [Block(kind: .tool, toolStatus: .streaming)], isAwaitingModelResponse: true), "streaming tool")
check(true, Message(blocks: [Block(kind: .tool, toolStatus: .completed)], isAwaitingModelResponse: true), "settled tool next request")
check(true, Message(blocks: [Block(kind: .tool, toolStatus: .failed)], isAwaitingModelResponse: true), "failed tool next request")
check(false, Message(blocks: [Block(kind: .tool, toolStatus: .completed), Block(kind: .text)]), "prior tool not fabricated waiting")
print("Production Swift waiting predicate: PASS (\\(count) cases, Foundation stubs only)")
'''
assert '.flatMap { $0 < block.content.endIndex ? $0 : nil } ?? startIdx' in thinking
# Window boundary adversary: a long single line ending in newline must NOT
# trim past endIndex into an empty thinking body (Python oracle, not Swift).
def tail(text, window):
    start = max(0, len(text) - window)
    newline = text.find('\n', start)
    clean = newline + 1 if newline >= 0 and newline + 1 < len(text) else start
    return text[clean:]
assert tail('a' * 9000 + '\n', 2000)
assert tail('a' * 9000 + '\n', 8000)
toggle = c[c.index('            if thinkingToggleSub == nil {'):c.index('        // MARK: - Snapshot', c.index('            if thinkingToggleSub == nil {'))] if '        // MARK: - Snapshot' in c[c.index('            if thinkingToggleSub == nil {'):] else c[c.index('            if thinkingToggleSub == nil {'):c.index('        private func applySnapshot')]
assert 'var snap = snapshot' not in toggle
swift = shutil.which('swift')
if swift:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)/'ThinkingVisibility.swift'
        path.write_text(stubs + predicate + checks)
        subprocess.run([swift, str(path)], check=True)
elif os.environ.get('V64R_REQUIRE_SWIFT') == '1':
    raise SystemExit('Swift required: production predicate runtime tests NOT RUN')
else:
    print('SKIP Swift predicate execution: Swift unavailable; runtime NOT RUN')
