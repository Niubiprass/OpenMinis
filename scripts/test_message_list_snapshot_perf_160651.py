#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[T-ios-first-block-footer-gap] Regression guard for the chat freeze.

Device HangDetector samples (2026-10-22 01:19 / 01:22 / 01:40 / 05:05)
showed `CollectionViewMessageList.Coordinator.applySnapshot` spending
>2s with `Array.firstIndex(of:)` -> `MessageListItem.__derived_enum_equals`
at the top of the stack. The two quadratic lookups were:

  * `newItems.firstIndex(of: .assistantFooter(id))` for every assistant
    message (O(messages × items)), and
  * `messages.last(where: { $0.role == .assistant })` for every assistant
    message (O(messages²)).

Both are now O(1)/O(n). This is a source contract; it cannot time a device.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
SRC = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()


class SnapshotPerf(unittest.TestCase):
    def test_footer_lookup_is_precomputed(self):
        self.assertIn('var footerIndexByMessage: [UUID: Int] = [:]', SRC)
        self.assertIn('footerIndexByMessage[mid] = index', SRC)
        self.assertIn('let footerIdx = footerIndexByMessage[message.id]', SRC)
        # The per-message scan was the stack top in the device hang report.
        self.assertNotIn('newItems.firstIndex(of: .assistantFooter', SRC)

    def test_last_assistant_is_computed_once(self):
        self.assertIn(
            'let lastAssistantMessageId = messages.last(where: { $0.role == .assistant })?.id',
            SRC,
        )
        self.assertIn('let isLastAssistant = (message.id == lastAssistantMessageId)', SRC)
        self.assertNotIn(
            'let isLastAssistant = (message.id == messages.last(where: { $0.role == .assistant })?.id)',
            SRC,
        )

    def test_index_map_is_built_after_dedupe(self):
        # Indices must match the array actually applied to the diffable data
        # source, so the map is built after `uniqueItems`.
        i = SRC.index('newItems = Self.uniqueItems(newItems, caller: caller)')
        j = SRC.index('var footerIndexByMessage', i)
        self.assertGreater(j, i)
        self.assertLess(j - i, 1200)


if __name__ == '__main__':
    unittest.main(verbosity=2)