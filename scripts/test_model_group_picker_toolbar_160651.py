#!/usr/bin/env python3
"""Model-group picker commit-button regression; source + optional real iOS SwiftUI typecheck.

No provider config is created or changed. V64R_REQUIRE_SWIFT=1 fails closed
without a macOS Xcode/iPhoneOS toolchain. Typecheck is not a device UI test.
"""
from pathlib import Path
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
        self.assertEqual(SOURCE.replace(toolbar(SOURCE), '<TOOLBAR>'),
                         original.replace(toolbar(original), '<TOOLBAR>'))

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
