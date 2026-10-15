#!/usr/bin/env python3
"""160645: executable transition oracle + production source contracts (not UIKit)."""
import math
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = (ROOT / 'src/ios/iOS15Compat.swift').read_text()
CELL = (ROOT / 'src/ios/Agent/MessageList/MessageListInfrastructure.swift').read_text()
V3 = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()


class FitOracle:
    def __init__(self):
        self.identity, self.width, self.high, self.good, self.candidate = None, 0, 0, 0, None

    def fit(self, raw, now, identity='A', width=390, idle=True, streaming=False):
        if identity != self.identity or abs(width - self.width) > .5:
            self.identity, self.width = identity, width
            self.high, self.good, self.candidate = 0, 0, None
        fresh = math.isfinite(raw) and raw > 1
        h = raw if fresh else self.good
        if fresh and h < self.high - 8:
            if self.candidate and abs(h - self.candidate[0]) <= 1 and now - self.candidate[1] >= .08 and idle and not streaming:
                self.high, self.candidate = h, None
            elif not self.candidate or abs(h - self.candidate[0]) > 1:
                self.candidate = h, now
        elif fresh:
            self.candidate = None
        if self.high > 1 and h > 1 and h < self.high - 8:
            h = self.high
        self.high = max(self.high, h)
        if fresh:
            self.good = h
        return h


class StableHostTests(unittest.TestCase):
    def test_device_same_item_shrinks_release_after_confirmation(self):
        for high, low in ((505, 326), (679, 455), (1015, 679)):
            m = FitOracle()
            self.assertEqual(m.fit(high, 0), high)
            self.assertEqual(m.fit(low, .01), high)
            self.assertEqual(m.fit(low, .13), low)
            self.assertEqual(m.fit(0, .14), low)

    def test_long_short_long_short_same_identity_width_and_invalid_fallback(self):
        m = FitOracle()
        sequence = ((505, 0, 505), (326, .01, 505),
                    (326, .13, 326), (float('nan'), .14, 326),
                    (679, .3, 679), (float('inf'), .31, 679),
                    (455, .4, 679), (0, .41, 679),
                    (455, .53, 455), (-1, .54, 455),
                    (1, .55, 455))
        for raw, now, expected in sequence:
            self.assertEqual(m.fit(raw, now, identity='same-item', width=390), expected)

    def test_both_production_fitting_entries_delegate_without_raw_bypass(self):
        # Source contract only: this does not invoke either UIKit entry point.
        start = HOST.index('    override func systemLayoutSizeFitting(_ targetSize: CGSize)')
        stop = HOST.index('    private var isMeasuring:', start)
        entries = HOST[start:stop]
        self.assertEqual(entries.count('ios15FittingSize(targetSize)'), 2)
        self.assertEqual(entries.count('ios15FittingSize(size)'), 1)
        self.assertNotIn('host.view.sizeThatFits', entries)
        self.assertNotIn('host.sizeThatFits', entries)
        self.assertNotIn('fitSize.height', entries)

    def test_same_runloop_is_not_confirmation(self):
        m = FitOracle()
        m.fit(505, 0)
        m.fit(326, .01)
        self.assertEqual(m.fit(326, .012), 505)

    def test_zero_nan_infinity_never_confirm_shrink(self):
        for bad in (0, float('nan'), float('inf'), -1):
            m = FitOracle()
            m.fit(505, 0)
            self.assertEqual(m.fit(bad, .2), 505)

    def test_dragging_deceleration_and_streaming_do_not_release(self):
        m = FitOracle()
        m.fit(505, 0)
        m.fit(326, .01, idle=False)
        self.assertEqual(m.fit(326, .13, idle=False), 505)
        self.assertEqual(m.fit(326, .25, streaming=True), 505)
        self.assertEqual(m.fit(326, .38), 326)

    def test_measurement_bounce_cancels_candidate(self):
        m = FitOracle()
        m.fit(505, 0)
        m.fit(326, .01)
        m.fit(505, .1)
        self.assertEqual(m.fit(326, .2), 505)
        self.assertEqual(m.fit(327, .33), 327)

    def test_identity_and_width_cannot_inherit_high_water(self):
        for args in ({'identity': 'B'}, {'width': 744}):
            m = FitOracle()
            m.fit(1015, 0)
            self.assertEqual(m.fit(455, .01, **args), 455)

    def test_production_trust_guards_and_all_cache_layers(self):
        for text in ('!cv.isTracking, !cv.isDragging, !cv.isDecelerating',
                     '!layout.deferSelfSizing, !layout.isStreamingCell(ip.item)',
                     'ds.itemIdentifier(for: ip) == identity',
                     'context == currentRenderContext()',
                     'abs(resolvedHostingWidth(bounds.width) - context.width) <= 0.5',
                     'now - shrinkCandidateAt >= 0.08, mayShrink',
                     'cell.clearCachedHeight()', 'discardPrecalc: true',
                     'layout.invalidateMemo', 'shrinkRetryScheduled = true'):
            self.assertIn(text, HOST)
        self.assertIn('self.consumeIOS15PendingStableShrink()\n            self.shrinkRetryScheduled = false', HOST)
        self.assertIn('ios15FittingSize(size)', HOST)
        self.assertIn('if abs(width - appliedHostWidth) > 0.5,', HOST)
        self.assertIn('addChild(host)', HOST)
        self.assertIn('host.didMove(toParent: parent)', HOST)
        self.assertIn('host.removeFromParent()', HOST)
        self.assertNotIn('layout.setCachedHeight', HOST)
        self.assertNotIn('cell.setCachedHeight', HOST)

    def test_tool_thinking_growth_not_clamped_to_super(self):
        self.assertNotIn('let _v64grew', CELL)
        self.assertNotIn('_ios15Reconciled = _v64est', CELL)
        self.assertIn('height: UIView.layoutFittingCompressedSize.height', CELL)
        self.assertIn('verticalFittingPriority: .fittingSizeLevel', CELL)

    def test_settle_consumes_non_textkit_hosts(self):
        self.assertIn('for cell in cv.visibleCells { consumeHostShrink(in: cell) }', V3)
        self.assertLess(V3.index('let anchorItem = anchorIP'), V3.index('for cell in cv.visibleCells { consumeHostShrink'))
        self.assertIn('dataSource?.indexPath(for: $0)', V3)
        self.assertIn('savedOffset + ((postY ?? anchorPreY', V3)

    def test_anchor_math_preserves_screen_position(self):
        for dy in (-31.3, -13, 100):
            before_y, before_offset = 1000, 1020
            after_y = before_y + dy
            after_offset = before_offset + after_y - before_y
            self.assertAlmostEqual(before_y - before_offset, after_y - after_offset)


if __name__ == '__main__':
    unittest.main(verbosity=2)
