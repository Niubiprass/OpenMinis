#!/usr/bin/env python3
"""Source/algorithm contracts only; NOT an iOS runtime or UIKit behavior test."""
import pathlib
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

def source(path):
    return (ROOT / path).read_text()

class HostModel:
    def __init__(self):
        self.identity = None
        self.fast = self.rebuild = 0
    def apply(self, identity):
        if identity is not None and identity == self.identity:
            self.fast += 1
        else:
            self.rebuild += 1
            self.identity = identity

class ReflowModel:
    def __init__(self):
        self.last = None
        self.due = None
        self.height = self.prepared = 0
        self.runs = 0
    def correction(self, t, height):
        delta = height - self.height
        self.height = height
        if self.due is None:
            delay = max(0, .25 - (t - self.last)) if abs(delta) > 100 and self.last is not None else 0
            self.due = t + delay
    def fire(self, t):
        if self.due is not None and t >= self.due:
            self.due = None
            self.last = t
            self.prepared = self.height
            self.runs += 1

class RenderContracts(unittest.TestCase):
    def test_identity_model(self):
        h = HostModel()
        for _ in range(10): h.apply(('message-a', 'block-a'))
        self.assertEqual((h.fast, h.rebuild), (9, 1))
        h.apply(('message-b', 'block-a'))
        self.assertEqual((h.fast, h.rebuild), (9, 2))
        h.apply(None)
        h.apply(None)
        self.assertEqual(h.rebuild, 4)

    def test_host_source_uses_item_not_counter(self):
        s = source('src/ios/iOS15Compat.swift')
        self.assertNotIn('_ios15ApplyGen', s)
        self.assertNotIn('_v63ConfigGen', s)
        self.assertIn('identity == hostedContentIdentity', s)
        self.assertIn('_V63Probe.hitFast()', s)
        self.assertIn('_V63Probe.hitRebuild()', s)
        self.assertIn('hostedContentIdentity = identity', s)
        self.assertIn('ios15LastGoodFitH = 0', s)
        cells = source('src/ios/Agent/MessageList/CollectionViewMessageListV3.swift')
        self.assertEqual(cells.count('applyContentConfiguration(config.ios15ContentIdentity(item))'), 4)

    def test_width_contract(self):
        s = source('src/ios/iOS15Compat.swift')
        self.assertIn('resolvedHostingWidth(size.width)', s)
        self.assertIn('resolvedHostingWidth(targetSize.width)', s)
        self.assertNotIn('cvW - 32', s)
        self.assertNotIn('let measCapW15', s)
        for full in (320, 390, 744, 1024):
            # Only the SwiftUI content owns the left/right 16pt padding.
            self.assertEqual(full - 2 * 16, full - 32)

    def test_trailing_reflow_after_final_token(self):
        m = ReflowModel()
        m.correction(1, 200)
        m.fire(1)
        m.correction(1.1, 500)
        m.correction(1.15, 700)
        m.fire(1.2)
        self.assertEqual(m.prepared, 200)
        m.fire(1.25)
        self.assertEqual((m.prepared, m.runs), (700, 2))
        other = ReflowModel()
        other.correction(1.1, 400)
        other.fire(1.1)
        self.assertEqual(other.prepared, 400)

    def test_reflow_source_has_trailing_schedule(self):
        s = source('src/ios/Agent/MessageList/MessageListLayout.swift')
        self.assertNotIn('static var v43BurstAt', s)
        self.assertNotIn('full-reflow suppressed', s)
        self.assertIn('asyncAfter(deadline: .now() + reflowDelay)', s)
        self.assertIn('self.lastFooterReflowAt = CACurrentMediaTime()', s)

    def test_large_blank_row_can_shrink_without_first_shrink_lockout(self):
        layout = source('src/ios/Agent/MessageList/MessageListLayout.swift')
        self.assertIn('isMarkdownText(key: key, at: index)', layout)
        self.assertNotIn('static var v31MaxH', layout)
        self.assertIn('v31Shrink[index] = (key: key, high: original, low: preferred, at: now)', layout)
        self.assertIn('v31Shrink.removeAll()', layout)
        self.assertIn('v31Bounce.removeAll()', layout)
        self.assertIn('markdownTextKeyByIndex.removeAll()', layout)
        # Reproduce three actual device traces. Only a confirmed DOWN→UP→DOWN
        # for the SAME stable row may be held. The first real shrink never is.
        def accept(events):
            down = bounce = None
            result = []
            for key, old, new, time in events:
                if new < old-100:
                    blocked = bool(bounce and bounce[0] == key
                                   and abs(old-bounce[1]) < 24 and time-bounce[2] < 2)
                    if not blocked: down, bounce = (key,old,new,time), None
                elif new > old+100:
                    if down and down[0] == key and abs(old-down[2]) < 24 and new >= down[1]-24 and time-down[3] < 2:
                        bounce = (key,new,time)
                    else: bounce = None
                    down = None
                    blocked = False
                else: blocked = False
                result.append(not blocked)
            return result
        self.assertEqual(accept([('text-A',491,267,0)]), [True])
        self.assertEqual(accept([('text-A',324,212,0)]), [True])
        self.assertEqual(accept([('text-A',491,267,0),('text-A',267,491,0.5),('text-A',491,267,1)]), [True,True,False])
        self.assertEqual(accept([('text-A',491,267,0),('text-B',267,491,0.5),('text-A',491,267,1)]), [True,True,True])

if __name__ == '__main__':
    unittest.main()
