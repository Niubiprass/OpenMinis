#!/usr/bin/env python3
"""Storage swipe delete: one alert only (iOS 15 shadows a second one)."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
src = (root / 'src/ios/Views/Settings/StorageManagementView.swift').read_text()
list_view = src.split('struct SessionStorageDetailView', 1)[0]
detail_view = src.split('struct SessionStorageDetailView', 1)[1]
fails = []

def ok(cond, name):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)

ok(list_view.count('.alert(') == 1, 'list has exactly one alert')
ok('pendingDeletion' in list_view and 'DeletionTarget' in list_view, 'one shared deletion state')
ok('.session(session)' in list_view, 'session swipe uses shared state')
ok('.bucket(bucket)' in list_view, 'overview swipe uses shared state')
ok('performPendingDeletion' in list_view, 'single confirmation performs removal')
ok('removeSessionDirectory' in list_view, 'session delete reuses the checked helper')
ok('deletionError' in list_view and '未能删除' in list_view, 'failed removals are reported')
ok('async -> Int' in list_view, 'bucket removal counts failures')
ok('.alert(' in detail_view, 'detail page keeps its own confirmation')
ok('onFilesCleared' in detail_view, 'detail page still refreshes the list')

print(f'{len(fails)} failure(s)')
sys.exit(1 if fails else 0)
