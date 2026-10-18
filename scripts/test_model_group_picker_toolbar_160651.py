#!/usr/bin/env python3
"""Model-group picker commit-button regression; source + optional real iOS SwiftUI typecheck.

No provider config is created or changed. V64R_REQUIRE_SWIFT=1 fails closed
without a macOS Xcode/iPhoneOS toolchain. Typecheck is not a device UI test.
"""
from pathlib import Path
import difflib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PICKER = ROOT / 'src/ios/Views/Providers/UnifiedModelPicker.swift'
SOURCE = PICKER.read_text()
START = '    @ToolbarContentBuilder\n    private var toolbarContent: some ToolbarContent {'
END = '    /// A stable "which System row" key'


def toolbar(source):
    return START + source.split(START, 1)[1].split(END, 1)[0]


def item_bodies(source):
    # Toolbar items contain balanced action/label closures; avoid fragile line counts.
    items = []
    for match in re.finditer(r'ToolbarItem\(placement: (\.\w+)\)\s*\{', source):
        opening = match.end() - 1
        level = 1
        cursor = opening + 1
        while cursor < len(source) and level:
            if source[cursor] == '{':
                level += 1
            elif source[cursor] == '}':
                level -= 1
            cursor += 1
        if level:
            raise AssertionError('Unbalanced ToolbarItem body')
        items.append((match[1], source[opening + 1:cursor - 1]))
    return items


def baseline_gate(orig_stripped: str, stripped: str, accepted) -> str | None:
    """Shared accepted-diff gate. Returns None when every non-equal diff block
    adds at least one line carrying an accepted marker, else a failure reason.
    """
    sm = difflib.SequenceMatcher(None, orig_stripped.splitlines(), stripped.splitlines())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        added_lines = stripped.splitlines()[j1:j2]
        if not any(any(frag in line for frag in accepted) for line in added_lines):
            return (f'removed {orig_stripped.splitlines()[i1:i2]!r} '
                    f'added {added_lines!r}')
    return None


class SourceContracts(unittest.TestCase):
    def test_commit_and_cancel_have_separate_items(self):
        items = item_bodies(toolbar(SOURCE))
        self.assertEqual([p for p, _ in items],
                         ['.topBarLeading', '.topBarTrailing'])
        self.assertIn('Button("Cancel") { dismiss() }', items[0][1])
        self.assertNotIn('onAddMulti', items[0][1])
        self.assertNotIn('Button("Add', items[0][1])
        self.assertIn('Button("Add (\\(selectedEntryIds.count))")', items[1][1])
        self.assertEqual(items[1][1].count('config.onAddMulti?(selectedEntryIds)'), 1)
        self.assertLess(items[1][1].index('config.onAddMulti?'), items[1][1].index('dismiss()'))
        self.assertIn('.disabled(selectedEntryIds.isEmpty)', items[1][1])
        self.assertIn('Button("Done") { dismiss() }', items[1][1])
        self.assertIn('} else {', items[1][1])

    def test_toolbar_verbatim_from_original_project_history(self):
        history = subprocess.run(['git', 'show',
                                  '255a24feac02ab02ab24535bceee3207d0204112:src/ios/Views/Providers/UnifiedModelPicker.swift'],
                                 cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertEqual(toolbar(SOURCE), toolbar(history))

    def test_only_toolbar_changed_from_accepted_baseline(self):
        original = subprocess.run(['git', 'show', 'b113f88:src/ios/Views/Providers/UnifiedModelPicker.swift'],
                                  cwd=ROOT, text=True, capture_output=True, check=True).stdout
        # Baseline b113f88 accepted only the toolbar change (the original suite
        # asserted byte-equality after masking the toolbar). This round ALSO
        # adds the [T-115-picker-unlisted] entryRow fix — the session picker
        # must surface `isUnavailableFromProvider` ("Not listed by provider")
        # exactly like the provider-detail page does. Those accepted edits are
        # whitelisted by content; anything ELSE still fails the guard.
        stripped = SOURCE.replace(toolbar(SOURCE), '<TOOLBAR>')
        orig_stripped = original.replace(toolbar(original), '<TOOLBAR>')
        accepted = ('unlisted', 'Not listed by provider', 'no longer lists', 'T-115-quota')
        # [T-115-picker-unlisted] Accept diff BLOCKS whose added lines carry an
        # accepted marker (the entryRow unlisted fix); the block's removed
        # lines are the pre-fix counterparts of those same edits and go with
        # them. Anything else still fails the guard.
        failure = baseline_gate(orig_stripped, stripped, accepted)
        if failure:
            self.fail(f'Unexpected picker edit vs baseline b113f88: {failure}')

    def test_whitelist_rejects_bare_comments_and_code(self):
        # Negative gate: a comment-only insertion or an arbitrary behavioral
        # edit NOT carrying an accepted marker must FAIL the baseline guard —
        # there is no comment-whitelist hole. Both fixtures are built on
        # orig_stripped (baseline b113f88, which contains NO accepted markers),
        # so any non-equal block is by construction unmarked and must fail.
        original = subprocess.run(['git', 'show', 'b113f88:src/ios/Views/Providers/UnifiedModelPicker.swift'],
                                  cwd=ROOT, text=True, capture_output=True, check=True).stdout
        stripped = SOURCE.replace(toolbar(SOURCE), '<TOOLBAR>')
        orig_stripped = original.replace(toolbar(original), '<TOOLBAR>')
        accepted = ('unlisted', 'Not listed by provider', 'no longer lists', 'T-115-quota')

        # 1) Bare comment inserted into the baseline: must FAIL.
        lines = orig_stripped.splitlines()
        lines.insert(10, '            // anything goes?')
        comment_tampered = '\n'.join(lines)
        failure = baseline_gate(orig_stripped, comment_tampered, accepted)
        self.assertIsNotNone(
            {failure},
            'a comment-only diff block must not whitelist itself')

        # 2) Sneaky behavioral edit on the baseline: must FAIL.
        behavior_tampered = orig_stripped.replace(
            'guard !disabled else { return }',
            'guard !disabled, false else { return } // disable rows always')
        failure = baseline_gate(orig_stripped, behavior_tampered, accepted)
        self.assertIsNotNone(
            {failure},
            'an unmarked behavioral edit must not pass the gate')

    def test_session_picker_surfaces_provider_unlisted(self):
        # [T-115-picker-unlisted] The session picker row must show + block
        # models the provider no longer lists (absentSince set), instead of
        # rendering them as selectable like the provider-detail page's
        # "供应商未列出": red tag, dimmed row, no quick test, no selection.
        self.assertIn('let unlisted = entry.isUnavailableFromProvider', SOURCE)
        self.assertIn('Text("Not listed by provider")', SOURCE)
        self.assertIn('foregroundStyle(.red.opacity(0.8))', SOURCE)
        self.assertIn('if !unlisted {\n                    quickTestButton(entry)', SOURCE)
        self.assertIn('.opacity(disabled || unlisted ? 0.55 : 1)', SOURCE)
        self.assertIn('guard !disabled, !unlisted else { return }', SOURCE)

    def test_existing_commit_chains_are_retained(self):
        detail = (ROOT / 'src/ios/Views/Providers/ModelGroupDetailView.swift').read_text()
        slot = (ROOT / 'src/ios/Views/Providers/GroupSlotPicker.swift').read_text()
        store = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
        self.assertIn('onAddMulti:', detail)
        self.assertIn('store.updateGroup(group)', detail)
        self.assertIn('onAddMulti:', slot)
        self.assertIn('ProviderConfigStore.shared.addGroup(group)', slot)
        self.assertIn('assign(group.id)', slot)
        self.assertIn('func addGroup(', store)
        self.assertIn('func updateGroup(', store)
        self.assertIn('options: .atomic', store)


class IOSSwiftUITypecheck(unittest.TestCase):
    def test_exact_toolbar_compiles_for_ios15_5(self):
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Xcode/iPhoneOS SwiftUI typecheck required, but unavailable')
            self.skipTest('Xcode/iPhoneOS SDK unavailable; SwiftUI toolbar NOT compiled')
        sdk = subprocess.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'],
                             text=True, capture_output=True, check=True).stdout.strip()
        wrapper = '''import SwiftUI
struct PickerToolbarConfig { var onAddMulti: ((Set<String>) -> Void)? }
struct PickerToolbarHarness: View {
    let isMulti: Bool
    let selectedEntryIds: Set<String>
    let config: PickerToolbarConfig
    @Environment(\\.dismiss) private var dismiss
    var body: some View { Text("Harness").toolbar { toolbarContent } }
''' + toolbar(SOURCE) + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='model-picker-toolbar-') as temporary:
            fixture = Path(temporary) / 'PickerToolbar.swift'
            fixture.write_text(wrapper)
            result = subprocess.run(['xcrun', '--sdk', 'iphoneos', 'swiftc', '-swift-version', '5',
                                     '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios15.5', str(fixture)],
                                    text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print('iOS 15.5 SwiftUI exact toolbar typecheck: PASS (not a rendered UI test)')


if __name__ == '__main__':
    print('Source contracts + optional SwiftUI compile only; no device/config changes.', flush=True)
    unittest.main(verbosity=2)
