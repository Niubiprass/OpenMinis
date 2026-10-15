#!/usr/bin/env python3
"""Source contracts + executable transition oracle; no UIKit/Swift runtime required."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYOUT = (ROOT / 'src/ios/Agent/MessageList/MessageListLayout.swift').read_text()
INFRA = (ROOT / 'src/ios/Agent/MessageList/MessageListInfrastructure.swift').read_text()
HOST = (ROOT / 'src/ios/iOS15Compat.swift').read_text()
V3 = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()


def body(source, signature):
    start = source.index('{', source.index(signature))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def remap(old, new, parked):
    # Transition oracle for the production oldIndexByItem/newDeferred loop.
    indices = {item: index for index, item in enumerate(old)}
    return {index: parked[indices[item]] for index, item in enumerate(new)
            if item in indices and indices[item] in parked}


class DeferredHeightRegression(unittest.TestCase):
    def test_production_remaps_by_item_not_row(self):
        method = body(LAYOUT, 'func updateCacheForSnapshot(')
        self.assertIn('oldIndexByItem[item] = i', method)
        self.assertIn('for (newIndex, item) in newIds.enumerated()', method)
        self.assertIn('if let oldIndex = oldIndexByItem[item]', method)
        self.assertIn('var newDeferred: [Int: CGFloat] = [:]', method)
        self.assertIn('if let h = deferredHeights[oldIndex] { newDeferred[newIndex] = h }', method)
        self.assertIn('deferredHeights = newDeferred', method)

    def test_prepend_moves_a_height_without_writing_b(self):
        self.assertEqual(remap(['A', 'B'], ['X', 'A', 'B'], {0: 95}), {1: 95})

    def test_reorder_multiple_parked(self):
        self.assertEqual(remap(['A', 'B', 'C'], ['C', 'A', 'B'], {0: 95, 2: 140}),
                         {0: 140, 1: 95})

    def test_deleted_item_never_writes_replacement(self):
        self.assertEqual(remap(['A', 'B'], ['X', 'B'], {0: 95}), {})

    def test_append_preserves_identity(self):
        self.assertEqual(remap(['A'], ['A', 'B'], {0: 95}), {0: 95})

    def test_empty_snapshot_drops_pending(self):
        self.assertEqual(remap(['A'], [], {0: 95}), {})

    def test_repeated_snapshot_uses_current_positions(self):
        parked = remap(['A', 'B'], ['B', 'A'], {0: 95})
        self.assertEqual(remap(['B', 'A'], ['A', 'C'], parked), {0: 95})

    def test_clear_cannot_flush_previous_session(self):
        self.assertIn('deferredHeights.removeAll()', body(LAYOUT, 'func clearHeightCache()'))

    def test_new_measurement_or_invalidation_supersedes_pending(self):
        for signature in ('func invalidateHeight(', 'func setCachedHeight(',
                          'override func invalidationContext(\n        forPreferredLayoutAttributes'):
            method = body(LAYOUT, signature)
            self.assertIn('deferredHeights.removeValue(forKey: index)', method)
            if 'heightCache[index] =' in method:
                self.assertLess(method.index('deferredHeights.removeValue'), method.index('heightCache[index] ='))


class NumericIdentityDiagnostics(unittest.TestCase):
    def test_identity_is_deterministic_and_body_free(self):
        method = body(INFRA, 'var scrollDiagnosticID: UInt64')
        for case in ('wholeMessage', 'assistantHeader', 'assistantBlock', 'assistantFooter'):
            self.assertIn('.' + case, method)
        self.assertIn('14695981039346656037', method)
        self.assertIn('&* 1099511628211', method)
        for forbidden in ('contentKey', 'hashValue', '.content', '.text'):
            self.assertNotIn(forbidden, method)
        self.assertIn('cell.scrollDiagnosticID = item.scrollDiagnosticID', V3)
        self.assertIn('scrollDiagnosticID = 0', body(INFRA, 'override func prepareForReuse()'))

    def test_plaf_captures_values_before_mutation(self):
        method = body(INFRA, 'override func preferredLayoutAttributesFitting(')
        self.assertLess(method.index('let diagnosticIncomingH'), method.index('super.preferredLayoutAttributesFitting(layoutAttributes)'))
        self.assertLess(method.index('let diagnosticSuperH'), method.index('attrs.size.height = cached'))
        line = next(line for line in INFRA.splitlines() if '[CellSizing][V64-CONVERGE] item=' in line)
        for field in ('item=', 'cell=', 'idx=', 'incoming=', 'super=', 'raw=', 'reconciled=', 'final=', 'tkFound=', 'tk=', 'hold='):
            self.assertIn(field, line)
        self.assertNotIn('contentKey', line)

    def test_host_identity_is_host_owned_not_index_owned(self):
        self.assertIn('(hostedContentIdentity?.base as? MessageListItem)?.scrollDiagnosticID', HOST)
        line = next(line for line in HOST.splitlines() if '[V64R-HOST-HOLD] item=' in line)
        for field in ('item=', 'cellItem=', 'host=', 'incoming=', 'raw=', 'measured=', 'locked=', 'final=', 'decel='):
            self.assertIn(field, line)
        self.assertNotIn('contentKey', line)
        self.assertNotIn('if ios15MonoH - height > 80', HOST)
        self.assertIn('if now - lastHeightHoldLogAt > 0.5', HOST)


if __name__ == '__main__':
    unittest.main(verbosity=2)
