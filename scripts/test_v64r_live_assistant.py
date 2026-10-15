#!/usr/bin/env python3
"""Execute the production live-assistant helpers with small Foundation stubs.
This tests helper selection on a Swift host (macOS CI), not UIKit height/cache
invalidation, collection-view layout, or device rendering. Without Swift only
source contracts run; their success does not count as runtime test success.
"""
import os, re, shutil, subprocess, tempfile, textwrap
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root/'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()


def extract_helper(name):
    # Match the production declaration through its same-indent closing brace.
    # Nested scopes are more indented; stop loudly if the declaration changes.
    declaration = re.search(r'(?m)^( +)static func ' + re.escape(name) + r'\(', source)
    assert declaration is not None, f'Missing production helper: {name}'
    closing = re.search(r'(?m)^' + declaration.group(1) + r'}\s*$', source[declaration.end():])
    assert closing is not None, f'Missing helper closing brace: {name}'
    return textwrap.dedent(source[declaration.start():declaration.end() + closing.end()])


latest = extract_helper('latestAssistantMessage')
live = extract_helper('liveAssistantMessageIds')
layout = (root/'src/ios/Agent/MessageList/MessageListLayout.swift').read_text()
range_start = layout.index('    func isStreamingCell(_ index: Int) -> Bool {')
range_end = layout.index('\n    }', range_start) + len('\n    }')
range_method = textwrap.dedent(layout[range_start:range_end])
range_probe = '\nstruct RangeProbe {\nvar streamingCellRanges: [Range<Int>]\n' + range_method + '\n}\n'
range_checks = r'''
let ranges = RangeProbe(streamingCellRanges: [2..<5, 8..<11])
for index in 0..<15 {
    check(ranges.isStreamingCell(index) == ([2,3,4,8,9,10].contains(index)), "exact live range at \\(index)")
}
check(!RangeProbe(streamingCellRanges: []).isStreamingCell(0), "no live ranges")
print("Production Swift range tests: PASS (queued rows after live footer excluded)")
'''
# These are source-only contracts; UIKit behavior still requires device testing.
assert 'layout.invalidateHeight(at: i, discardPrecalc: true)' in source
assert 'if !isLiveItem, let memo = layout.measuredHeight' in source
assert 'dataSource?.indexPath(for: item)' in source
assert 'bridge.autoRetryAttempt = isLatestAssistant ?' in source
assert 'if abs(delta) > 0.5, !pendingFooterReflow {' in layout
assert 'if let last = ranges.last, index >= last.lowerBound' not in range_method
assert 'messages.last(where: { $0.role == .assistant })' in latest
assert 'guard isProcessing else { return [] }' in live
assert 'latestAssistantMessage(in: messages)' in live
assert 'case .running, .streaming: return true' in live
assert 'msg.role == .assistant' in live
print('Live-assistant source contracts: PASS (source only; no runtime claim)', flush=True)

stubs = r'''
import Foundation

enum Role { case user, assistant, systemInfo, compactDivider }
enum ToolStatus { case running, streaming, completed, failed }
struct Block {
    let toolStatus: ToolStatus?
}
struct ChatMessage {
    let id = UUID()
    let role: Role
    var blocks: [Block] = []
}
'''
checks = r'''
var checks = 0
func check(_ condition: @autoclosure () -> Bool, _ name: String) {
    precondition(condition(), name)
    checks += 1
}
func ids(_ messages: [ChatMessage], processing: Bool = true) -> Set<UUID> {
    Probe.liveAssistantMessageIds(messages: messages, isProcessing: processing)
}
let assistant = ChatMessage(role: .assistant)
let queuedUser = ChatMessage(role: .user)
let queuedUser2 = ChatMessage(role: .user)
let system = ChatMessage(role: .systemInfo)
let divider = ChatMessage(role: .compactDivider)

check(Probe.latestAssistantMessage(in: [assistant])?.id == assistant.id, "assistant tail")
check(ids([assistant]) == Set([assistant.id]), "assistant tail live")
let queued = [assistant, queuedUser, queuedUser2]
check(Probe.latestAssistantMessage(in: queued)?.id == assistant.id, "queued users keep latest assistant")
check(ids(queued) == Set([assistant.id]), "queued users keep assistant live")
let trailingRows = [assistant, queuedUser, system, divider]
check(Probe.latestAssistantMessage(in: trailingRows)?.id == assistant.id, "system/divider tail keeps latest assistant")
check(ids(trailingRows) == Set([assistant.id]), "system/divider tail keeps assistant live")

let running = ChatMessage(role: .assistant, blocks: [Block(toolStatus: .running)])
let streaming = ChatMessage(role: .assistant, blocks: [Block(toolStatus: .streaming)])
let completed = ChatMessage(role: .assistant, blocks: [Block(toolStatus: .completed)])
let failed = ChatMessage(role: .assistant, blocks: [Block(toolStatus: .failed)])
let plain = ChatMessage(role: .assistant, blocks: [Block(toolStatus: nil)])
let mixed = ChatMessage(role: .assistant, blocks: [Block(toolStatus: .completed), Block(toolStatus: .running)])
let multiTurn = [completed, running, failed, streaming, plain, mixed, assistant, queuedUser, system]
check(Probe.latestAssistantMessage(in: multiTurn)?.id == assistant.id, "latest assistant after earlier tools")
check(ids(multiTurn) == Set([running.id, streaming.id, mixed.id, assistant.id]), "earlier running/streaming tools remain live; settled tools do not")
check(ids([completed, assistant, queuedUser]) == Set([assistant.id]), "completed earlier tool excluded")
check(ids([plain, assistant, queuedUser]) == Set([assistant.id]), "earlier ordinary assistant excluded")
check(ids([completed, queuedUser]) == Set([completed.id]), "latest assistant remains live regardless of own tool status")
check(ids([assistant, queuedUser, queuedUser2]) == Set([assistant.id]), "latest assistant appears once")

check(ids(multiTurn, processing: false).isEmpty, "processing false clears latest and earlier live tools")
check(ids(queued, processing: false).isEmpty, "processing false with queued users")
check(Probe.latestAssistantMessage(in: queued)?.id == assistant.id, "latest helper independent of processing")

let nonAssistantTool = ChatMessage(role: .user, blocks: [Block(toolStatus: .running)])
let noAssistant = [nonAssistantTool, system, divider]
check(Probe.latestAssistantMessage(in: noAssistant) == nil, "no assistant")
check(ids(noAssistant).isEmpty, "non-assistant running tool ignored")
check(ids([assistant, nonAssistantTool]) == Set([assistant.id]), "non-assistant tool cannot become latest")
check(Probe.latestAssistantMessage(in: []) == nil, "empty latest")
check(ids([]).isEmpty, "empty live")
check(ids([], processing: false).isEmpty, "empty stopped")
print("Production Swift live-assistant helper tests: PASS (\(checks) checks; host stubs, not UIKit/device)")
'''

swift = shutil.which('swift')
if swift:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)/'LiveAssistantTests.swift'
        path.write_text(stubs + '\nstruct Probe {\n' + latest + '\n' + live + '\n}\n' + range_probe + checks + range_checks)
        subprocess.run([swift, str(path)], check=True)
else:
    if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
        raise SystemExit('Swift required in CI; runtime helper tests NOT RUN')
    print('SKIP production Swift live-assistant execution: Swift unavailable; runtime NOT RUN (run on macOS CI)')
