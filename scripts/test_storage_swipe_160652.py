#!/usr/bin/env python3
"""Storage swipe delete: the trash button deletes directly.

History: this page has been through an .alert, then a .confirmationDialog with
a custom isPresented Binding. On device the dialog opened and closed without
ever removing a byte, because the binding setter cleared `pendingDeletion`
before the button action could read it. The regression this file now guards is
therefore structural: the delete target must be passed by value from the
button, nothing may sit between the tap and the removal call, and a failure
must be visible instead of silent.
"""
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

# No confirmation step on the list at all: there is no state that can be
# cleared before the action runs.
ok('.alert(' not in list_view, 'list has no alert')
ok('.confirmationDialog(' not in list_view, 'list has no confirmation dialog')
ok('@State private var pendingDeletion' not in list_view, 'no pending-deletion state to lose')
ok('queueDeletion' not in list_view, 'swipe does not queue, it deletes')

# The tap calls the removal directly, with the target passed by value.
ok('delete(.session(session))' in list_view, 'session trash deletes directly')
ok('delete(.bucket(bucket))' in list_view, 'overview trash deletes directly')
ok('private func delete(_ target: DeletionTarget)' in list_view, 'single delete entry point')
ok('await clearFiles(for: session)' in list_view, 'session delete really removes directories')
ok('await clearBucket(bucket)' in list_view, 'bucket delete really removes files')

# Removal is verified, not assumed: missing dirs are skipped, errors counted,
# and the outcome is both logged and shown.
ok('try fm.removeItem(at: dir)' in list_view, 'session delete calls removeItem')
ok('[StorageDelete]' in list_view, 'removal outcome is logged for device checks')
ok('未能删除' in list_view and '已删除' in list_view, 'result is shown either way')

# Detail page keeps its own confirmation (a plain $bool alert) but must report
# failures too instead of zeroing the size unconditionally.
ok('.alert(' in detail_view, 'detail page keeps its own confirmation')
ok('onFilesCleared' in detail_view, 'detail page still refreshes the list')

print(f'{len(fails)} failure(s)')
sys.exit(1 if fails else 0)
