#!/usr/bin/env python3
"""160648: production Swift state/lifecycle extraction + source integration contracts.
CI: V64R_REQUIRE_SWIFT=1 is fail-closed. No UIKit/device coverage is claimed.
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = (ROOT / 'src/ios/iOS15Compat.swift').read_text()
V3 = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()


def extract(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def swift_program():
    # Definitions and methods below are extracted verbatim, NOT reimplemented.
    definitions = '\n'.join((
        extract(V3, 'private struct ThinkingHeightReleaseState<'),
        extract(HOST, 'private struct _IOS15HostRenderContext:'),
        extract(HOST, 'private struct _IOS15HostRenderSample:'),
    ))
    apply = extract(HOST, 'private func apply(_ config: UIContentConfiguration)')
    note = extract(HOST, 'func noteIOS15HostingContentShape(_ shape: AnyHashable) {')
    # installRoot's pure state prefix stops before the SwiftUI View builder.
    root = extract(HOST, 'private func installRoot(')
    prefix = root[root.index('{') + 1:root.index('        let context = currentRenderContext()')]
    shim = r'''
protocol UIContentConfiguration {}
struct UIHostingConfiguration<T>: UIContentConfiguration { let contentIdentity: AnyHashable? }
struct EmptyView {}
struct AnyView { init(_ view: EmptyView) {} }
enum FakeColor { case clear }
class FakeView {
    var backgroundColor: FakeColor?; var clipsToBounds = false
    func invalidateIntrinsicContentSize() {}
    func setNeedsLayout() {}
}
class UIHostingController<T> {
    let view = FakeView()
    init(rootView: T) {}
}
enum _V63Probe { static func hitFast() {}; static func hitRebuild() {} }
private final class HostShim<Content> {
    var hostingRevision: UInt = 0
    var renderGeneration: UInt = 0
    var shrinkCandidate: CGFloat?
    var shrinkCandidateAt: Double = 0
    var heightInvalidationPending = false
    var contentShapeChangePending = false
    var contentShape: AnyHashable?
    var ios15PerformHeightChange: ((() -> Void) -> Void)?
    var renderedSample: _IOS15HostRenderSample?
    var publishedRenderSample: _IOS15HostRenderSample?
    var hostedContentIdentity: AnyHashable?
    var appliedHostWidth: CGFloat = 390
    var ios15MonoH: CGFloat = 0
    var ios15MonoHW: CGFloat = 0
    var ios15LastGoodFitH: CGFloat = 0
    var host: UIHostingController<AnyView>?
    var configuration: UIContentConfiguration = UIHostingConfiguration<Content>(contentIdentity: nil)
    let bounds = CGRect(x: 0, y: 0, width: 390, height: 0)
    func resolvedHostingWidth(_ width: CGFloat) -> CGFloat { width }
    func invalidateIntrinsicContentSize() {}
    func setNeedsLayout() {}
    func removeHostedController() { host = nil }
    func reconcileHostParent() {}
    func installHostedView(_ controller: UIHostingController<AnyView>) {}
    func update(_ config: UIHostingConfiguration<Content>) { configuration = config; apply(config) }
'''
    shim += '\n' + apply + '\n' + note
    shim += '\nfunc installRoot(_ config: UIHostingConfiguration<Content>, width: CGFloat) {' + prefix + '\n}\n}\n'
    checks = r'''
func require(_ value: @autoclosure () -> Bool, _ label: String) {
    if !value() { fatalError(label) }
}
var state = ThinkingHeightReleaseState<String>()
state.register("m1:b", expanded: true)
require(!state.record("m1:b", expanded: true), "duplicate does not enqueue")
require(state.record("m1:b", expanded: false), "collapse")
require(state.pendingExpansion(for: "m1:b") == false, "pending collapse")
state.register("m1:b", expanded: true)
require(state.pendingExpansion(for: "m1:b") == false, "sync cannot overwrite debt")
state.register("m2:b", expanded: true)
require(state.record("m2:b", expanded: false), "same block different message")
state.complete(["m1:b"])
require(state.pendingItems == ["m2:b"], "completion is identity based")
state.record("m1:b", expanded: true)
state.record("m1:b", expanded: false)
require(state.pendingExpansion(for: "m1:b") == false, "coalesce to latest shape")
state.retain(["m1:b"])
require(state.pendingItems == ["m1:b"], "deleted identity removed")
state.reset()
require(state.pendingItems.isEmpty && state.expandedByItem.isEmpty, "session reset")
func sample(_ id: String, _ width: CGFloat, _ height: CGFloat, _ revision: UInt) -> _IOS15HostRenderSample {
    .init(context: .init(identity: AnyHashable(id), revision: revision, generation: revision, width: width),
          size: CGSize(width: width, height: height))
}
let old = sample("A", 390, 68, 1)
for revision in 2...200 {
    require(!sample("A", 390, 68, UInt(revision)).needsPublication(comparedTo: old), "revision storm")
}
require(!sample("A", 390, 68.4, 2).needsPublication(comparedTo: old), "epsilon")
require(sample("A", 390, 69, 2).needsPublication(comparedTo: old), "real height change")
require(sample("B", 390, 68, 2).needsPublication(comparedTo: old), "identity change")
require(sample("A", 744, 68, 2).needsPublication(comparedTo: old), "width change")
let host = HostShim<Int>()
host.update(.init(contentIdentity: AnyHashable("A")))
host.noteIOS15HostingContentShape(AnyHashable(true))
host.publishedRenderSample = old
host.renderedSample = old
host.heightInvalidationPending = true
host.ios15MonoH = 505
host.ios15LastGoodFitH = 505
host.noteIOS15HostingContentShape(AnyHashable(false))
require(host.contentShapeChangePending, "shape debt")
require(host.renderedSample == nil, "old geometry rejected on shape")
require(host.publishedRenderSample == old, "retain published geometry")
let generation = host.renderGeneration
host.noteIOS15HostingContentShape(AnyHashable(false))
require(host.renderGeneration == generation, "notification/model dedup")
host.update(.init(contentIdentity: AnyHashable("A")))
require(host.contentShapeChangePending && host.heightInvalidationPending, "same item preserves both debts")
require(host.ios15MonoH == 505 && host.ios15LastGoodFitH == 505, "keep accepted fallback")
require(host.publishedRenderSample == old, "same item retains publication")
host.installRoot(.init(contentIdentity: AnyHashable("A")), width: 744)
require(host.publishedRenderSample == nil, "width resets publication")
host.ios15PerformHeightChange = { work in work() }
host.update(.init(contentIdentity: AnyHashable("B")))
require(!host.contentShapeChangePending && !host.heightInvalidationPending, "new identity clears debt")
require(host.contentShape == nil && host.ios15PerformHeightChange == nil, "new identity clears shape and anchor")
require(host.ios15MonoH == 0 && host.ios15LastGoodFitH == 0, "new identity clears fallback")
print("production Swift: state, geometry storm, lifecycle PASS")
'''
    return 'import Foundation\n' + definitions + '\n' + shim + '\nprivate func runChecks() {\n' + checks + '\n}\nrunChecks()\n'


class HostShrinkRelease(unittest.TestCase):
    def test_production_swift_state_geometry_and_lifecycle(self):
        program = swift_program()  # Extraction must work even without Swift.
        swift = shutil.which('swift')
        if not swift:
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('V64R_REQUIRE_SWIFT=1 requires Swift; refusing oracle-only success')
            self.skipTest('Swift unavailable; production Swift execution not claimed')
        with tempfile.TemporaryDirectory(prefix='host-shrink-') as directory:
            path = pathlib.Path(directory) / 'main.swift'
            path.write_text(program)
            result = subprocess.run([swift, str(path)], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('production Swift: state, geometry storm, lifecycle PASS', result.stdout)

    def test_shape_is_committed_main_queue_not_browse_throttle(self):
        sync = extract(V3, 'private func syncThinkingLayoutSubscriptions(')
        self.assertIn('.receive(on: DispatchQueue.main)', sync)
        self.assertIn('weak block', sync)
        self.assertIn('expanded: block.isThinkingExpanded', sync)
        record = extract(V3, 'private func recordThinkingShape(')
        self.assertIn('DispatchQueue.main.async', record)
        self.assertIn('thinkingShapeFlushScheduled', record)
        self.assertNotIn('flushStreamingLayout()', record)
        flush = extract(V3, 'private func flushThinkingShapeChanges()')
        for forbidden in ('3.0', 'applySnapshot', 'reconfigureItems', 'resetIOS15HostingHeight'):
            self.assertNotIn(forbidden, flush)
        self.assertIn('thinkingHeightState.complete(completed)', flush)
        self.assertIn('if !hasHost { unhosted.append(item) }', flush)
        # Hosted rows hand off to the host; only fallback rows evict here.
        handoff = flush[:flush.index('if !unhosted.isEmpty')]
        self.assertNotIn('clearCachedHeight()', handoff)
        self.assertNotIn('invalidateHeight(at:', handoff)

    def test_explicit_debts_survive_geometry_dedup(self):
        publish = extract(HOST, 'private func publishPendingHeightChange()')
        self.assertIn('needsPublication(comparedTo: publishedRenderSample)', publish)
        self.assertIn('guard changed || heightInvalidationPending || (contentShapeChangePending && sample != nil)', publish)
        self.assertEqual(publish.count('cell.clearCachedHeight()'), 1)
        self.assertEqual(publish.count('layout.invalidateHeight(at:'), 1)
        self.assertIn('self.heightInvalidationPending = false', publish)
        self.assertIn('if sample != nil { self.contentShapeChangePending = false }', publish)
        self.assertNotIn('setCachedHeight', publish.replace('NEVER write setCachedHeight', ''))
        self.assertNotIn('sample != publishedRenderSample', publish)

    def test_shape_requires_fresh_context_not_a_transient_fit(self):
        note = extract(HOST, 'func noteIOS15HostingContentShape(_ shape: AnyHashable) {')
        self.assertIn('installRoot(config, width:', note)
        self.assertIn('guard let previous, previous != shape', note)
        fit = extract(HOST, 'private func ios15FittingSize(')
        self.assertIn('let trustedShape = contentShapeChangePending && natural != nil', fit)
        self.assertIn('!contentShapeChangePending || natural != nil', fit)
        self.assertIn('now - shrinkCandidateAt >= 0.08, mayShrink', fit)
        self.assertIn('context == currentRenderContext()', HOST)
        self.assertIn('ds.itemIdentifier(for: ip) == identity', HOST)

    def test_identity_cleanup_and_nested_single_anchor_owner(self):
        apply = extract(HOST, 'private func apply(_ config: UIContentConfiguration)')
        fast = apply[:apply.index('_V63Probe.hitRebuild()')]
        self.assertNotIn('heightInvalidationPending = false', fast)
        self.assertNotIn('contentShapeChangePending = false', fast)
        for token in ('heightInvalidationPending = false', 'contentShapeChangePending = false',
                      'contentShape = nil', 'ios15PerformHeightChange = nil'):
            self.assertIn(token, apply)
        transaction = extract(V3, 'private func performHostingHeightChange(')
        self.assertIn('!isFlushing else { updates(); return }', transaction)
        self.assertEqual(transaction.count('setContentOffset('), 1)
        self.assertIn('layout.suppressContentOffsetAdjustment = true', transaction)
        self.assertIn('dataSource?.indexPath(for: $0)', transaction)
        settle = extract(V3, 'private func settleAfterInteraction(')
        self.assertLess(settle.index('isFlushing = true'), settle.index('flushThinkingShapeChanges()'))
        self.assertLess(settle.index('flushThinkingShapeChanges()'), settle.index('for cell in cv.visibleCells { consumeHostShrink'))
        self.assertIn('(!vm.streamingUIUpdatesSuspended || isFlushing)', V3)
        self.assertIn('thinkingHeightState.reset()', V3)

    def test_geometry_dedup_model_without_swift(self):
        # Supplemental boundary model, never a substitute for required Swift CI.
        def changed(a, b):
            return a[0] != b[0] or any(abs(a[i] - b[i]) > .5 for i in (1, 2, 3))
        old = ('A', 390, 390, 68)
        for _ in range(200):
            self.assertFalse(changed(old, old))
        self.assertFalse(changed(('A', 390, 390, 68.4), old))
        self.assertTrue(changed(('A', 390, 390, 69), old))
        self.assertTrue(changed(('B', 390, 390, 68), old))


if __name__ == '__main__':
    unittest.main(verbosity=2)
