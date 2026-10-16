#!/usr/bin/env python3
"""Thinking resize-source and production reconciliation regression.
Source checks are NOT UIKit execution. On CI run the extracted Swift method
with Foundation and small Transaction/model stubs, not a hand-written oracle.
"""
from pathlib import Path
import os, shutil, subprocess, tempfile
ROOT = Path(__file__).resolve().parents[1]
view = (ROOT / 'src/ios/Views/Chat/AssistantBlockView.swift').read_text()
start = view.index('struct ThinkingBlockView: View')
end = view.index('// MARK: - Typing Indicator', start)
thinking = view[start:end]
a = thinking.index('    private func reconcileAutomaticExpansion(streaming: Bool) {')
b = thinking.index('\n    var body: some View {', a)
method = thinking[a:b].replace('private func', 'func', 1)
assert thinking.count('reconcileAutomaticExpansion(streaming:') == 3, 'mount + stream edge + declaration'
assert 'NotificationCenter.default.post' not in thinking, 'model publisher is the sole resize source'
assert '.onChange(of: block.isThinkingExpanded)' not in thinking
assert 'guard !block.thinkingUserToggled else { return }' in method
assert 'guard block.isThinkingExpanded != expanded else { return }' in method
assert 'transaction.disablesAnimations = true' in method
follow = thinking[thinking.index('.onChange(of: block.content.count)'):thinking.index('.onChange(of: isStreaming)')]
assert 'if #available(iOS 16.0, *)' in follow
legacy = follow[follow.index('var transaction = Transaction(animation: nil)'):]
assert 'withAnimation(' not in legacy and 'transaction.disablesAnimations = true' in legacy
assert 'proxy.scrollTo("thinkingBottom", anchor: .bottom)' in legacy
print('Thinking resize source contracts PASS (not UIKit validation)', flush=True)
swift = shutil.which('swift')
if not swift:
    if os.getenv('V64R_REQUIRE_SWIFT') == '1':
        raise SystemExit('Swift required; reconciliation runtime NOT RUN')
    print('SKIP production Swift reconciliation execution: Swift unavailable')
    raise SystemExit(0)
program = '''import Foundation
struct Transaction {
    var disablesAnimations = false
    init(animation: String? = nil) {}
}
func withTransaction(_ t: Transaction, _ body: () -> Void) { body() }
final class Block {
    var thinkingUserToggled = false
    var writes = 0
    var isThinkingExpanded = false { didSet { writes += 1 } }
}
struct Harness {
    let block: Block
''' + method + '''
}
let key = "chat.autoExpandThinking"
let saved = UserDefaults.standard.object(forKey: key)
defer {
    if let saved { UserDefaults.standard.set(saved, forKey: key) }
    else { UserDefaults.standard.removeObject(forKey: key) }
}
var checked = 0
for auto in [false, true] {
 for manual in [false, true] {
  for streaming in [false, true] {
   for initial in [false, true] {
    UserDefaults.standard.set(auto, forKey: key)
    let block = Block()
    block.thinkingUserToggled = manual
    block.isThinkingExpanded = initial
    block.writes = 0
    let harness = Harness(block: block)
    harness.reconcileAutomaticExpansion(streaming: streaming)
    let expected = manual || (streaming && !auto) ? initial : streaming
    precondition(block.isThinkingExpanded == expected, "state mismatch")
    precondition(block.writes == (expected == initial ? 0 : 1), "duplicate write")
    harness.reconcileAutomaticExpansion(streaming: streaming)
    precondition(block.writes == (expected == initial ? 0 : 1), "mount/edge not idempotent")
    checked += 1
   }
  }
 }
}
UserDefaults.standard.removeObject(forKey: key)
let block = Block()
let harness = Harness(block: block)
harness.reconcileAutomaticExpansion(streaming: true)
precondition(block.isThinkingExpanded, "default auto expand")
harness.reconcileAutomaticExpansion(streaming: false)
precondition(!block.isThinkingExpanded, "finished mount must collapse")
print("Production reconciliation Swift PASS (\\(checked) combinations + default, Foundation stubs; NOT UIKit)")
'''
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / 'ThinkingReconciliation.swift'
    path.write_text(program)
    subprocess.run([swift, str(path)], check=True)
