#!/usr/bin/env python3
"""Entry-lookup index + one-pass fallback ring (main-thread watchdog regression).

Background (2026-10-23, device log):
  * 23:21:52 the compaction path logged "[Compact] prev marker found" and then the
    main thread produced NO log line for 44 s; at 23:22:36 iOS killed the app with
    a scene-update watchdog (exception 0x8badf00d, 10 s allowance).
  * The 19:35 report on the same build carries a symbolized stack straight into
        ModelGroupRouter.nextFallback(group:currentEntryId:store:)
      → AIChatViewModel.compactFallbackCandidates(startingAt:)
      → AIChatViewModel.generateCompactSummary(conversationText:statusMsg:)
  * The 19:52 StreamHang reports show 11.7 s hangs in
        availableEntryIds → ProviderConfigStore.entry(for:) → _stringCompareInternal
  Root cause: `entry(for:)` did up to four linear scans over every model entry,
  and the compaction ring walk called `availableEntryIds` (which calls
  `entry(for:)` per member) once per step ⇒ O(members² × entries) on the main
  actor.

These are source contracts (no Xcode here): they pin the O(1) index, the
one-pass ring, and the preserved lookup priority. `V64R_REQUIRE_SWIFT` style
runtime checks stay in the Swift suites.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
ROUTER = (ROOT / 'src/ios/Providers/ModelGroupRouter.swift').read_text()
COMPACT = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+Compaction.swift').read_text()


def swift_function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index('{', start)
    level = 1
    cursor = brace + 1
    while cursor < len(source) and level:
        if source[cursor] == '{':
            level += 1
        elif source[cursor] == '}':
            level -= 1
        cursor += 1
    if level:
        raise AssertionError('unbalanced braces for ' + signature)
    return source[brace + 1:cursor - 1]


class EntryLookupIndex(unittest.TestCase):
    def test_entry_lookup_is_indexed(self):
        body = swift_function_body(STORE, 'func entry(for entryId: String) -> ModelEntry?')
        self.assertIn('let index = entryLookupIndex()', body)
        # Priority order preserved: id → uuid → legacy map → ":" key.
        order = [body.index('index.byId[entryId]'),
                 body.index('index.byUuid[entryId]'),
                 body.index('legacyUuidToCompositeKey[entryId]'),
                 body.index('index.byLegacyColonKey[entryId]')]
        self.assertEqual(order, sorted(order), 'lookup priority order changed')

    def test_entry_lookup_no_linear_scan(self):
        body = swift_function_body(STORE, 'func entry(for entryId: String) -> ModelEntry?')
        self.assertNotIn('config.modelEntries.first(where:', body,
                         'entry(for:) must not scan modelEntries on the hot path')

    def test_index_is_cached_per_config_revision(self):
        body = swift_function_body(STORE, 'private func entryLookupIndex() -> EntryLookupIndex')
        self.assertIn('entryLookupIndexRevision == configRevision', body)
        self.assertIn('entryLookupIndexCache = index', body)
        self.assertIn('entryLookupIndexRevision = configRevision', body)
        # One dictionary per key FORM keeps duplicate-key tie-breaks form-local.
        for key in ('byId', 'byUuid', 'byLegacyColonKey'):
            self.assertIn(key + '[' , body)
        self.assertEqual(body.count('if byId[entry.id] == nil'), 1)
        self.assertEqual(body.count('if byUuid[entry.uuid] == nil'), 1)


class OnePassRing(unittest.TestCase):
    def test_router_exposes_available_ids(self):
        self.assertIn('static func availableEntryIds(group: ModelGroup, store: ProviderConfigStore) -> [String]',
                      ROUTER)
        # Per-entry filter logs must not be info: they ran hundreds of times per turn.
        body = swift_function_body(ROUTER, 'static func availableEntryIds(group: ModelGroup, store: ProviderConfigStore) -> [String]')
        self.assertNotIn('logger.info(', body)
        self.assertIn('logger.debug(', body)

    def test_router_has_precomputed_overload(self):
        body = swift_function_body(ROUTER, 'static func nextFallback(\n        currentEntryId: String,\n        available: [String]\n    ) -> String?')
        self.assertIn('available.firstIndex(of: currentEntryId)', body)
        self.assertNotIn('store.entry(for:', body)

    def test_compaction_walks_ring_once(self):
        body = swift_function_body(COMPACT, 'private func compactFallbackCandidates(startingAt first: ModelEntry) -> [ModelEntry]')
        self.assertIn('let available = ModelGroupRouter.availableEntryIds(group: group, store: store)',
                      body)
        self.assertIn('nextFallback(\n                    currentEntryId: cursor, available: available)', body)
        # The per-step refilter must be gone.
        self.assertNotIn('nextFallback(\n                    group: group, currentEntryId: cursor, store: store)', body)
        # Loop bound follows the routable ring, not the raw member list.
        self.assertIn('for _ in 0..<available.count', body)
        self.assertNotIn('0..<max(1, group.memberEntryIds.count)', body)


class LookupSemantics(unittest.TestCase):
    """Python model of the index: proves O(1) lookup matches the old linear scan."""

    @staticmethod
    def linear(entries, legacy_map, query):
        for e in entries:
            if e['id'] == query:
                return e
        for e in entries:
            if e['uuid'] == query:
                return e
        mapped = legacy_map.get(query)
        if mapped is not None:
            for e in entries:
                if e['id'] == mapped:
                    return e
        for e in entries:
            if e['colon'] == query:
                return e
        return None

    @staticmethod
    def indexed(entries, legacy_map, query):
        by_id, by_uuid, by_colon = {}, {}, {}
        for e in entries:                      # first wins, like first(where:)
            if e['id'] not in by_id:
                by_id[e['id']] = e
            if e['uuid'] not in by_uuid:
                by_uuid[e['uuid']] = e
            if e['colon'] not in by_colon:
                by_colon[e['colon']] = e
        if query in by_id:
            return by_id[query]
        if query in by_uuid:
            return by_uuid[query]
        if query in legacy_map and legacy_map[query] in by_id:
            return by_id[legacy_map[query]]
        if query in by_colon:
            return by_colon[query]
        return None

    def test_duplicate_keys_and_cross_form_collisions(self):
        entries = [
            {'id': 'A/m1', 'uuid': 'u-dup', 'colon': 'A:m1'},
            {'id': 'B/m1', 'uuid': 'u-dup', 'colon': 'B:m1'},   # duplicate uuid
            {'id': 'C/m1', 'uuid': 'u-c',  'colon': 'A/m1'},    # colon collides with A id
        ]
        legacy = {'old-uuid': 'C/m1'}
        probes = ['A/m1', 'B/m1', 'C/m1', 'u-dup', 'u-c', 'A:m1', 'B:m1', 'old-uuid', 'missing']
        for probe in probes:
            self.assertEqual(self.linear(entries, legacy, probe),
                             self.indexed(entries, legacy, probe),
                             'index diverged for ' + probe)

    def test_priority_id_beats_uuid_of_earlier_entry(self):
        entries = [
            {'id': 'X/m', 'uuid': 'k', 'colon': 'X:m'},
            {'id': 'k',   'uuid': 'z', 'colon': 'Y:m'},
        ]
        # 'k' is entry1's uuid AND entry2's id → id wins (old code checked id first).
        self.assertEqual(self.indexed(entries, {}, 'k')['id'], 'k')


class RouteRingSemantics(unittest.TestCase):
    @staticmethod
    def step(available, current):
        if current not in available:
            return available[0] if available else None
        idx = available.index(current)
        if idx + 1 < len(available):
            return available[idx + 1]
        return available[0] if idx > 0 else None

    def test_ring_walks_every_member_once(self):
        available = ['a', 'b', 'c']
        seen, cursor = [], 'b'
        for _ in range(len(available)):
            nxt = self.step(available, cursor)
            if nxt is None:
                break
            cursor = nxt
            if nxt not in seen:
                seen.append(nxt)
        self.assertEqual(seen, ['c', 'a', 'b'])

    def test_single_entry_ring_terminates(self):
        self.assertIsNone(self.step(['only'], 'only'))

    def test_current_missing_falls_to_first(self):
        self.assertEqual(self.step(['a', 'b'], 'gone'), 'a')


class ForegroundOnlyCompaction(unittest.TestCase):
    """A background-resumed load must not start a summarization."""

    def test_entry_auto_compact_requires_active_app(self):
        body = swift_function_body(COMPACT, 'func autoCompactOnEntryIfNeeded()')
        self.assertIn('UIApplication.shared.applicationState == .active', body)
        active = body.index('applicationState == .active')
        start_compact = body.index('compactAll()')
        self.assertLess(active, start_compact,
                        'the foreground gate must sit before the compaction start')

    def test_compaction_file_imports_uikit_guarded(self):
        head = COMPACT[:400]
        self.assertIn('#if canImport(UIKit)', head)
        self.assertIn('import UIKit', head)


if __name__ == '__main__':
    unittest.main(verbosity=2)