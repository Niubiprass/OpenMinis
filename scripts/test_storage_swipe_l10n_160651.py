#!/usr/bin/env python3
"""Source-contract tests for storage-page swipe-delete and label localization.

Covers:
- [T-storage-swipe-delete-20261019]: session rows swipe to reveal a Delete
  action; the destructive step still confirms first; the removal is the same
  file-only cleanup as the detail view's "Clear Session Files" (conversation
  preserved); the list reloads sizes afterwards.
- [T-storage-l10n-20261019]: the overview rows route their labels through
  AppLocalized so a Chinese UI no longer shows English category names
  (storageRow takes a plain String parameter, which bypasses the string
  catalog when handed a bare literal).

Static checks only; swipe gestures and device rendering need a device.
"""
import json
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
STORAGE = (ROOT / 'src/ios/Views/Settings/StorageManagementView.swift').read_text()
XCSTRINGS = json.loads((ROOT / 'src/ios/Localizable.xcstrings').read_text())


class StorageSwipeDelete(unittest.TestCase):
    """[T-storage-swipe-delete-20261019] Swipe-to-delete on session rows."""

    def test_swipe_action_reveals_delete(self):
        self.assertIn('.swipeActions(edge: .trailing, allowsFullSwipe: false)', STORAGE)
        self.assertIn('Label("Delete", systemImage: "trash")', STORAGE)
        self.assertIn('pendingClearSession = session', STORAGE)

    def test_destructive_action_confirms_before_deleting(self):
        self.assertIn('@State private var pendingClearSession', STORAGE)
        self.assertIn('.alert("Clear Session Files?", isPresented: Binding(', STORAGE)
        self.assertIn('Button("Clear \\(vm.format(pendingClearSession?.totalSize ?? 0))", role: .destructive)', STORAGE)
        self.assertIn('Button("Cancel", role: .cancel) { pendingClearSession = nil }', STORAGE)

    def test_clear_matches_detail_view_file_removal(self):
        # Same removal as the detail view's "Clear Session Files": this row's
        # minis directory + descendants, then reload so sizes refresh.
        self.assertIn('private func clearFiles(for session: StorageManagementViewModel.SessionStorage)', STORAGE)
        self.assertIn('for sid in [sessionId] + descendants', STORAGE)
        self.assertIn('SessionStorageCleanup.removeSessionDirectory(sid, minisBase: minisBase)', STORAGE)

    def test_conversation_preserved_semantics(self):
        # The swipe path is a file-only cleanup; it must not call a session
        # record deletion API anywhere in the storage view.
        self.assertNotIn('deleteSession(', STORAGE)
        section = STORAGE[STORAGE.index('[T-storage-swipe-delete-20261019] Same removal'):]
        self.assertIn('The conversation itself is preserved.', section)


class StorageLabelLocalization(unittest.TestCase):
    """[T-storage-l10n-20261019] Overview labels go through AppLocalized."""

    KEYS = [
        'Shell Container', 'Chat Database', 'Session Files', 'Logs & Caches',
        'Temporary Files', 'Orphaned Session Files', 'Stale Shell Leftovers', 'Other',
    ]

    def test_labels_localized(self):
        # Static rows pass the key straight to AppLocalized; the five swipeable
        # buckets route through OverviewBucket.titleKey (also AppLocalized).
        for key in ('Shell Container', 'Chat Database', 'Other'):
            self.assertIn('label: AppLocalized("{}")'.format(key), STORAGE, key)
        for bucket in ('sessionFiles', 'logsAndCaches', 'temporaryFiles',
                       'orphanedSessions', 'staleRootfs'):
            self.assertIn('swipeableStorageRow(.{},'.format(bucket), STORAGE, bucket)
        self.assertIn('label: AppLocalized(bucket.titleKey)', STORAGE)

    def test_no_bare_label_literals_regression(self):
        # Guard: the bare-literal bug must not come back — these keys may only
        # appear in this file wrapped by AppLocalized.
        for key in self.KEYS:
            self.assertNotIn('label: "{}"'.format(key), STORAGE, key)

    def test_overview_buckets_declared(self):
        # Every swipeable bucket must be a declared case with a title key, and
        # the unsafe buckets must NOT be swipeable.
        for bucket in ('logsAndCaches', 'temporaryFiles', 'sessionFiles',
                       'orphanedSessions', 'staleRootfs'):
            self.assertIn('case {}'.format(bucket), STORAGE, bucket)
        for unsafe in ('case shellContainer', 'case chatDatabase'):
            self.assertNotIn(unsafe, STORAGE, unsafe)

    def test_overview_confirm_and_clear_wired(self):
        self.assertIn('pendingOverviewBucket = bucket', STORAGE)
        self.assertIn('private func clearBucket(_ bucket: OverviewBucket)', STORAGE)
        self.assertIn('LoggingManager.shared.deleteAllLogs()', STORAGE)
        self.assertIn('hasPrefix(".alpine-rootfs-broken-")', STORAGE)

    def test_translations_exist(self):
        strings = XCSTRINGS['strings']
        for key in self.KEYS:
            zh = (strings.get(key, {}).get('localizations', {}).get('zh-Hans', {})
                  .get('stringUnit', {}).get('value'))
            self.assertTrue(zh, 'missing zh-Hans for {}'.format(key))


if __name__ == '__main__':
    unittest.main(verbosity=2)
