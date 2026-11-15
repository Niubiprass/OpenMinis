#!/usr/bin/env python3
"""Provider-list regression: layout scopes + actual cache/count Swift behavior.
No device/credential/network calls. Native rendering still needs device acceptance.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / 'src/ios'
VIEW = (IOS/'Views/Providers/ProviderInstancesView.swift').read_text()
STORE = (IOS/'Providers/ProviderConfigStore.swift').read_text()
FIXTURES = ROOT/'scripts/fixtures'


def declaration(text, marker):
    start = text.index(marker)
    at = text.index('{', start)
    depth = 1
    end = at + 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise AssertionError('Unbalanced declaration: ' + marker)
    return text[start:end]


class ProviderListContracts(unittest.TestCase):
    def test_swipe_cannot_select_the_sorting_layout(self):
        self.assertIn('@State private var isSortingProviders = false', VIEW)
        self.assertEqual(VIEW.count('isSortingProviders.toggle()'), 1)
        self.assertIn('Button(isSortingProviders ? AppLocalized("Done") : AppLocalized("Edit"))', VIEW)
        self.assertIn('editMode = isSortingProviders ? .active : .inactive', VIEW)
        self.assertNotIn('if editMode.isEditing', VIEW)
        self.assertIn('.listStyle(.insetGrouped)', VIEW)
        body = declaration(VIEW, 'var body: some View {\n        List {')
        editing = declaration(body, 'if isSortingProviders {')
        self.assertIn('.onMove(perform: moveRows)', editing)
        # Native grouped sections own both card and swipe-button clipping outside
        # explicit sorting. A transient swipe cannot replace this section tree.
        browsing = body[body.index('} else {', body.index(editing)) + len('} else {'):]
        self.assertIn('ForEach(ProviderGroupOrder.types(in: store.instances)', browsing)
        self.assertIn('ForEach(members)', browsing)
        self.assertIn('providerLink(instance)', browsing)
        self.assertNotIn('.listRowBackground', browsing)
        self.assertNotIn('UISwipeAction', VIEW)

    def test_card_gap_reserves_content_space_and_internal_lines(self):
        editing = declaration(VIEW, 'if isSortingProviders {')
        self.assertIn('.padding(.bottom, entry.isLastMember ? 10 : 0)', editing)
        self.assertIn('.padding(.bottom, entry.isLastMember ? 10 : 0)', declaration(VIEW, 'private func rowBackground('))
        content = declaration(VIEW, 'private func rowBackground(')
        self.assertNotIn('.overlay', declaration(VIEW, 'private func rowContent('))
        self.assertIn('if !entry.isLastMember {', content)
        self.assertIn('Color(UIColor.separator)', content)
        self.assertIn('1 / UIScreen.main.scale', content)
        self.assertIn('.allowsHitTesting(false)', content)
        self.assertIn('.accessibilityHidden(true)', content)
        self.assertIn('.listSectionSeparator(.hidden)', VIEW)
        self.assertNotIn('.listRowInsets(', VIEW)

    def test_actions_and_delete_cancel_are_preserved(self):
        link = declaration(VIEW, 'private func providerLink(')
        self.assertIn('.swipeActions(edge: .trailing, allowsFullSwipe: false)', link)
        self.assertIn('pendingDeleteInstance = instance', link)
        self.assertIn('editingInstanceId = instance.id', link)
        self.assertNotIn('store.removeInstance(', link)
        self.assertIn('Button("Cancel", role: .cancel) { pendingDeleteInstance = nil }', VIEW)
        self.assertIn('presenting: pendingDeleteInstance', VIEW)
        self.assertIn('.swipeEditDestination(item: $editingInstanceId)', VIEW)

    def test_render_does_not_probe_credentials_or_rank_models(self):
        row = declaration(VIEW, 'private struct InstanceRow: View')
        self.assertNotIn('ProviderKeychainHelper.', row)
        self.assertNotIn('visibleEntries(', row)
        self.assertEqual(row.count('visibleEntryCount(for: instance.id)'), 1)
        self.assertIn('.task(id: request)', row)
        self.assertIn('!Task.isCancelled', row)
        self.assertIn('credentialRequest == request', row)
        self.assertIn('cache.generation == request.generation', row)
        self.assertIn('currentRequestMatches(request)', row)
        self.assertIn('func currentRequestMatches(_ request:', row)
        self.assertIn('ProviderRowCredentialCache.didInvalidate', row)
        # Quota scheduling, data interpretation and the display are not replaced.
        self.assertIn('quotaService.refreshAllIfNeeded(instances: [instance])', row)
        self.assertIn('quotaService.cachedQuota(instanceId: instance.id)', row)
        count = declaration(STORE, 'func visibleEntryCount(')
        self.assertIn('entry.providerInstanceId == instanceId && !entry.isHidden', count)
        self.assertNotIn('sorted', count)
        self.assertNotIn('ModelReleaseIndex', count)


class ProviderListSwiftTests(unittest.TestCase):
    def compiler(self):
        compiler = shutil.which('swiftc')
        if compiler:
            return compiler
        if os.getenv('V64R_REQUIRE_SWIFT') == '1':
            self.fail('Swift required; provider list runtime tests NOT executed')
        self.skipTest('No local swiftc; production Swift NOT compiled/executed')

    def test_production_async_credential_cache(self):
        compiler = self.compiler()
        cache = declaration(VIEW, 'final class ProviderRowCredentialCache:')
        source = (FIXTURES/'provider_row_cache_support.swift').read_text() + '\n' + cache
        source += '\n' + (FIXTURES/'provider_row_cache_main.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='provider-row-cache-') as tmp:
            swift, binary = Path(tmp)/'Cache.swift', Path(tmp)/'cache'
            swift.write_text(source)
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(swift), '-o', str(binary)],
                                    text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('production credential-cache', result.stdout)
            print(result.stdout.strip())

    def test_production_count_visibility(self):
        compiler = self.compiler()
        method = declaration(STORE, 'func visibleEntryCount(')
        source = '''import Foundation
struct Entry { let providerInstanceId: String; let isHidden: Bool }
struct Config { var modelEntries: [Entry] }
struct CountStore { var config: Config
''' + method + '''
}
let entries = [Entry(providerInstanceId: "A", isHidden: false), Entry(providerInstanceId: "A", isHidden: true),
               Entry(providerInstanceId: "B", isHidden: false), Entry(providerInstanceId: "A", isHidden: false)]
var store = CountStore(config: Config(modelEntries: entries))
precondition(store.visibleEntryCount(for: "A") == 2)
precondition(store.visibleEntryCount(for: "B") == 1)
precondition(store.visibleEntryCount(for: "missing") == 0)
store.config.modelEntries = []
precondition(store.visibleEntryCount(for: "A") == 0)
print("PASS: production visible model count")
'''
        with tempfile.TemporaryDirectory(prefix='provider-row-count-') as tmp:
            swift, binary = Path(tmp)/'main.swift', Path(tmp)/'count'
            swift.write_text(source)
            result = subprocess.run([compiler, '-swift-version', '5', str(swift), '-o', str(binary)],
                                    text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_modified_views_typecheck_for_ios15(self):
        xcrun = shutil.which('xcrun')
        if sys.platform != 'darwin' or not xcrun:
            if os.getenv('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Apple SDK required; provider list views NOT typechecked')
            self.skipTest('No Apple SDK; native SwiftUI views NOT typechecked')
        sdk = subprocess.check_output([xcrun, '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        support = (FIXTURES/'provider_row_cache_support.swift').read_text()
        ui_support = (FIXTURES/'provider_list_ui_support.swift').read_text()
        ui_support = ui_support.replace('// COUNT_METHOD', declaration(STORE, 'func visibleEntryCount('))
        declarations = '\n'.join(declaration(VIEW, marker) for marker in [
            'enum ProviderGroupOrder {', 'struct ProviderListEntry:', 'struct CardCornerShape:',
            'final class ProviderRowCredentialCache:', 'private struct InstanceRow: View'
        ])
        # Extract the actual conditional list subtree (both branches) and exact
        # edit button. Everything below compiles against real SwiftUI/UIKit;
        # only service/model dependencies are substituted.
        start = VIEW.index('            if isSortingProviders {')
        end = VIEW.index('            // [T-mimo-shadow-voice] Voice Services', start)
        rows = VIEW[start:end]
        button = declaration(VIEW, 'Button(isSortingProviders ? AppLocalized("Done")')
        helpers = '\n'.join(declaration(VIEW, marker) for marker in [
            'private var listRows', 'private func rowContent(', 'private func providerGroupTitle(',
            'private func providerLink(', 'private func rowBackground(', 'private func moveRows('
        ])
        helpers = helpers.replace('private func rowContent(', '@ViewBuilder private func rowContent(')
        helpers = helpers.replace('private func rowBackground(', '@ViewBuilder private func rowBackground(')
        shell = '''
@MainActor struct ProviderLayoutProbe: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var isSortingProviders = false
    @State private var editMode: EditMode = .inactive
    @State private var editingInstanceId: String?
    @State private var pendingDeleteInstance: ProviderInstance?
    var body: some View {
        List {
''' + rows + '''
        }
        .listStyle(.insetGrouped)
        .environment(\\.editMode, $editMode)
        .toolbar {
            ToolbarItem(placement: .navigationBarLeading) {
''' + button + '''
            }
        }
    }
''' + helpers + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='provider-list-ios15-') as tmp:
            swift = Path(tmp)/'View.swift'
            swift.write_text(support + ui_support + declarations + shell)
            result = subprocess.run([xcrun, '--sdk', 'iphoneos', 'swiftc', '-swift-version', '5',
                                     '-typecheck', '-sdk', sdk, '-target', 'arm64-apple-ios15.5',
                                     '-module-cache-path', str(Path(tmp)/'ModuleCache'), str(swift)],
                                    text=True, capture_output=True, timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print('PASS: actual provider list / row SwiftUI iOS15.5 typecheck; no gesture execution')


if __name__ == '__main__':
    unittest.main(verbosity=2)
