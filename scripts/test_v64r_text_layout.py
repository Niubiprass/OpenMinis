#!/usr/bin/env python3
"""Source contracts only: UIKit rendering requires real device acceptance."""
from pathlib import Path
r=Path(__file__).resolve().parents[1]
v=(r/'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
c=(r/'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
a=v[v.index('    private func applyStreamingTextBlockContent('):v.index('    private func flushDeferredStreamingTextUpdateIfNeeded(')]
assert a.index('block.content = text') < a.index('textBlockLayoutSignal.send')
assert a.index('cacheAttributedString(for: block)') < a.index('textBlockLayoutSignal.send')
assert a.index('textBlockLayoutSignal.send') < a.index('if wasEmpty && !text.isEmpty')
assert 'vm.textBlockLayoutSignal\n                .receive(on: DispatchQueue.main)' in c
b=c[c.index('        private func doFlushStreamingLayout()'):c.index('        private func scheduleCoalescedScroll()')]
assert 'pendingTextLayoutItems.subtract(changed)' in b
assert 'guard let vm, !vm.isLoadingSession, !vm.streamingUIUpdatesSuspended' in b
assert 'syncThinkingLayoutSubscriptions(messages)' in c
assert 'thinkingLayoutSubs[item] = Publishers.Merge(' in c
assert 'block.$content.dropFirst().map { _ in false }' in c
assert 'block.$isThinkingExpanded.removeDuplicates().dropFirst().map { _ in true }' in c
assert 'self.recordThinkingShape(item, expanded: block.isThinkingExpanded)' in c
assert 'private func flushThinkingShapeChanges()' in c
assert 'thinkingHeightState.record(item, expanded: expanded)' in c
assert 'self.hasPendingSnapshot || !self.pendingTextLayoutItems.isEmpty' in c
assert b.index('ds.indexPath(for: item)') < b.index('layout.invalidateHeight')
for x in ['discardPrecalc: true','clearCachedHeight()', 'applySnapshot(messages: vm.messages, caller: "text-batch")', 'snapshot.reconfigureItems']:
 assert x in b,x
assert 'guard vm.isProcessing' not in b
print('Text-batch layout source contracts: PASS; NOT UIKit/runtime validation')
