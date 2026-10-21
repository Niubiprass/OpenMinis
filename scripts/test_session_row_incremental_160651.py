#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests for the sidebar's single-row preview update.

The visible bug was: timestamp said 刚刚 while the preview still showed a reply
from minutes ago. The row was only rebuilt by the full listSessions() path,
which is throttled and cooldown-gated. These checks pin the incremental path.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
STORE = (ROOT / 'src/ios/Agent/Chat/ChatStore.swift').read_text()
VIEW = (ROOT / 'src/ios/Views/ContentView.swift').read_text()


class StoreRow(unittest.TestCase):
    def test_single_row_query_reuses_list_columns(self):
        self.assertIn('func sessionRow(_ id: String) -> ChatSession?', STORE)
        self.assertIn('Self.sessionListSQL(whereClause: " WHERE s.id = ?")', STORE)
        self.assertIn('decodeSessionRow(stmt, id: id).session', STORE)

    def test_single_row_query_keeps_preview(self):
        # getSession deliberately omits preview_text; sessionRow must not use it.
        block = STORE[STORE.index('func sessionRow('):]
        block = block[:block.index('func updateSessionModelId')]
        self.assertNotIn('SELECT id, title, model_id', block)
        self.assertIn('sessionListSQL', block)


class ViewPatch(unittest.TestCase):
    def test_unthrottled_observer_patches_one_row(self):
        self.assertIn('refreshSessionRow(sid)', VIEW)
        self.assertIn('ChatStore.shared.sessionRow(id)', VIEW)

    def test_row_patch_does_not_call_list_sessions(self):
        start = VIEW.index('private func refreshSessionRow(')
        end = VIEW.index('private func refreshSessionList()', start)
        body = VIEW[start:end]
        self.assertNotIn('listSessions()', body)
        self.assertIn('sessions[index] = row', body)

    def test_full_refresh_remains_for_structural_changes(self):
        self.assertIn('refreshSessionList()', VIEW)
        self.assertIn('SessionRefreshScheduler.decide', VIEW)


class PreviewEquality(unittest.TestCase):
    def test_preview_text_is_a_change_signal(self):
        self.assertIn('&& lhs.lastMessage == rhs.lastMessage', STORE)

    def test_preview_write_invalidates_list_cache(self):
        self.assertIn('invalidateSessionListCache(sessionId: sessionId)', STORE)


if __name__ == '__main__':
    unittest.main(verbosity=2)