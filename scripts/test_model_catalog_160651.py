#!/usr/bin/env python3
"""Source-contract tests for [T-115-model-catalog]: read-only global catalog.

Entry lives in ProviderInstancesView (NOT the guarded UnifiedModelPicker
toolbar). The catalog has zero write paths: no selection/save/refresh that
could disturb saved provider configs, model groups or routing.
"""
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEW = (ROOT / 'src/ios/Views/Providers/ProviderInstancesView.swift').read_text()


class ModelCatalogSource(unittest.TestCase):
    """[T-115-model-catalog] Source-wiring contracts."""

    def test_catalog_view_exists_with_entry(self):
        self.assertIn('struct ModelCatalogView: View', VIEW)
        self.assertIn('NavigationLink {\n                    ModelCatalogView()', VIEW)
        self.assertIn('Label("Model Catalog", systemImage: "books.vertical")', VIEW)

    def test_grouping_and_search(self):
        # Grouped by provider instance, ordered like the picker, searchable.
        self.assertIn('ProviderConfigStore.sortedByReleaseRank(store.entries(for: instance.id))', VIEW)
        self.assertIn('store.instances.compactMap', VIEW)
        self.assertIn('@State private var query = ""', VIEW)
        self.assertIn('.searchable(text: $query', VIEW)

    def test_metadata_badges_only_when_known(self):
        # No fabricated capabilities: chips render only for reported fields.
        self.assertIn('if let ctx = m.contextWindow', VIEW)
        self.assertIn('if let out = m.maxOutputTokens', VIEW)
        self.assertIn('if m.supportsReasoning == true', VIEW)
        self.assertIn('if let modality = m.modalityOverride', VIEW)
        self.assertIn('Explicit modality flags only', VIEW)

    def test_modality_badges_explicit_flags_only(self):
        self.assertIn('static func modalityBadges(_ m: ModelModality) -> [String]', VIEW)
        self.assertIn('if m.contains(.imageInput) { out.append("vision") }', VIEW)
        # Legacy alias must not fabricate vision from nothing.
        self.assertNotIn('textOnly', VIEW[VIEW.index('static func modalityBadges'):])

    def test_catalog_has_zero_write_paths(self):
        # Read-only v1: no selection, save, override, hide, group or refresh
        # anywhere in the catalog section of the file.
        section = VIEW[VIEW.index('struct ModelCatalogView'):]
        for forbidden in ['onAddMulti', 'updateGroup', 'save(', 'setCustom',
                          'isHidden', 'refreshModels', 'toggleHidden',
                          'ProviderConfigStore.shared.save']:
            self.assertNotIn(forbidden, section,
                             f'catalog must not contain write path: {forbidden}')

    def test_empty_states(self):
        self.assertIn('"No models available"', VIEW)
        self.assertIn('"No matches"', VIEW)


import os
import shutil
import subprocess
import tempfile

API = (ROOT / 'src/ios/Providers/ModelsDevAPI.swift').read_text()
RANK = (ROOT / 'src/ios/Providers/ModelReleaseIndex.swift').read_text()
PICKER = (ROOT / 'src/ios/Views/Providers/UnifiedModelPicker.swift').read_text()
FIXTURES = ROOT / 'scripts/fixtures'


def declaration(text, marker):
    start = text.index(marker)
    at = text.index('{', start)
    depth, end = 1, at + 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    assert depth == 0, 'Unbalanced declaration: ' + marker
    return text[start:end]


def assert_catalog_contract(api=API, picker=PICKER, rank=RANK):
    snapshot = declaration(api, 'private struct RegistrySnapshot: Sendable')
    assert 'let epoch: UUID' in snapshot and 'let registry:' in snapshot and 'let timestamp: Date' in snapshot
    assert 'var ' not in snapshot, 'snapshot must be immutable'
    assert api.count('@unchecked Sendable') == 1, 'only the short-lock box may be unchecked'
    box = declaration(api, 'private final class CatalogBox:')
    assert 'lock.lock()' in box and 'defer { lock.unlock() }' in box
    assert 'private var state = CatalogState()' in box
    assert 'struct ReleaseEntry: Sendable' in api and 'struct ReleaseIndex: Sendable' in api
    for kind in ('stage2', 'aggregate', 'release'):
        marker = 'private static func ' + kind + 'Index(for snapshot:'
        method = declaration(api, marker)
        assert 'cached.epoch == snapshot.epoch' in method, 'wrong read epoch: ' + kind
        assert 'state.snapshot?.epoch == snapshot.epoch' in method, 'missing late-build fence: ' + kind
        assert kind + ' = EpochCache(epoch: snapshot.epoch, value: index)' in method
        assert 'snapshot.registry' in method, 'derived index must use captured registry: ' + kind
        assert 'cacheTimestamp' not in method
    for marker in ('static func fetchModels(', 'static func pricingPerMillion(', 'static func enrichModel(', 'static func enrichModels('):
        assert 'let snapshot = loadRegistry()' in declaration(api, marker)
    resolver = declaration(api, 'private static func resolveDevModel(')
    assert 'in snapshot: RegistrySnapshot' in resolver
    assert 'stage2Index(for: snapshot)' in resolver and 'aggregateIndex(for: snapshot)' in resolver
    cold = declaration(api, 'private static func installColdRegistry(')
    assert 'if let installed = state.snapshot { return installed }' in cold, 'late cold read must not replace refresh'
    assert cold.index('if let installed = state.snapshot { return installed }') < cold.index('state.snapshot = candidate'), 'late cold read may replace refresh'
    swap = declaration(api, 'private static func installRefreshedRegistry(')
    assert 'let retired = state' in swap and 'withExtendedLifetime(retired)' in swap
    for kind in ('stage2', 'aggregate', 'release'):
        assert 'state.' + kind + ' = nil' in swap
    refresh = declaration(api, 'private static func scheduleBackgroundRefresh()')
    assert refresh.index('guard !state.isRefreshing') < refresh.index('state.isRefreshing = true')
    assert 'defer { catalog.withLock { $0.isRefreshing = false } }' in declaration(api, 'private static func refreshFromNetwork()')
    prepare = declaration(api, 'static func prepareReleaseIndex()')
    assert 'if let cached = currentReleaseIndex() { return cached }' in prepare
    assert 'state.releaseWaiters.append(continuation)' in prepare
    assert 'guard !state.releasePreparing' in prepare
    assert 'releaseQueue.async' in prepare and 'let index = releaseIndex()' in prepare
    assert 'for waiter in waiters { waiter.resume(returning: index) }' in prepare
    for forbidden in ('.sync(', 'Semaphore', 'Task.detached', 'Task.isCancelled'):
        assert forbidden not in prepare, 'unbounded/blocking/shared cancellation: ' + forbidden
    assert 'private static let calendar' not in rank
    assert 'let calendar = Calendar(identifier: .gregorian)' in declaration(rank, 'static func parseReleaseDate(')
    load = declaration(picker, 'private func loadSections()')
    assert load.count('await ModelsDevAPI.prepareReleaseIndex()') == 1, 'picker must await shared cold preparation'
    before, after = load.split('await ModelsDevAPI.prepareReleaseIndex()')
    assert 'guard isCurrent(ticket) else { return }' in before
    assert 'guard isCurrent(ticket) else { return }' in after.split('captureReleaseKeys')[0]
    capture = declaration(picker, 'private func captureReleaseKeys(')
    assert 'ModelsDevAPI.releaseIndex()' not in capture
    assert 'index: index' in capture and 'ModelsDevAPI.ReleaseIndex?' in capture


def catalog_source(api=API):
    # Only I/O boundaries are DI; cache/load/single-flight/parse/index bodies are
    # exact production. Keep the original separate oracle unchanged otherwise.
    prod = declaration(api, 'enum ModelsDevAPI {')
    replacements = {
        'private static func loadDiskCache()': 'private static func loadDiskCache() -> (Data, Date)? { FixtureIO.shared.read() }',
        'private static func loadBundledRegistry()': 'private static func loadBundledRegistry() -> [String: ModelsDevProvider]? { nil }',
        'private static func scheduleBackgroundRefresh()': 'private static func scheduleBackgroundRefresh() { /* DI: no network */ }',
    }
    for marker, body in replacements.items():
        prod = prod.replace(declaration(prod, marker), body)
    # DI scheduling seam only: builders' production loops/rules stay verbatim.
    for kind, marker in [('stage2', 'private static func buildStage2Index('),
                         ('aggregate', 'private static func buildAggregateIndex('),
                         ('release', 'private static func buildReleaseIndex(')]:
        original = declaration(prod, marker)
        at = original.index('{') + 1
        gated = original[:at] + '\n        BuildGate.shared.checkpoint("' + kind + '")' + original[at:]
        prod = prod.replace(original, gated)
    models = api[api.index('private struct ModelsDevProvider:'):]
    actual = '\n'.join([prod, models, declaration(RANK, 'enum ModelReleaseIndex {'),
                         declaration(PICKER, 'private struct PickerBuildTicket:'),
                         (FIXTURES / 'provider_catalog_oracle.swift').read_text()])
    template = (FIXTURES / 'provider_catalog_main.swift').read_text()
    assert template.count('// PRODUCTION_CATALOG') == 1
    return template.replace('// PRODUCTION_CATALOG', actual)


class CatalogIsolationContracts(unittest.TestCase):
    def test_snapshot_epoch_and_async_wiring(self):
        assert_catalog_contract()

    def test_three_precise_negative_guards(self):
        variants = [
            (API.replace('cached.epoch == snapshot.epoch', 'true', 1), PICKER),
            (API, PICKER.replace('await ModelsDevAPI.prepareReleaseIndex()', 'ModelsDevAPI.releaseIndex()', 1)),
            (API.replace('if let installed = state.snapshot { return installed }', '// mutant: overwrite current epoch', 1), PICKER),
        ]
        for api, picker in variants:
            with self.assertRaises(AssertionError):
                assert_catalog_contract(api, picker)
        # SOURCE-only negatives. No compile failure is counted as native kill.

    def test_frozen_lookup_vote_and_release_rules_unchanged(self):
        oracle = (FIXTURES / 'provider_catalog_oracle.swift').read_text()
        for marker in ('private static func buildModels(', 'static func normalizedModelKey(',
                       'private static func prefixMatch(', 'private static func isUnrecognizedProvider(',
                       'private static func buildAggregateIndex(', 'private static func aggregate(',
                       'private static func buildStage2Index(', 'private static func applyDevData(',
                       'private static func normalizedCandidates(', 'private static func stripTrailingSlash('):
            with self.subTest(marker=marker):
                self.assertEqual(declaration(API, marker), declaration(oracle, marker))
        # Moving the original release fold must not alter iteration/tie rules.
        marker = '        var byFullId: [String: ReleaseEntry] = [:]'
        end = '        let index = ReleaseIndex(byFullId: byFullId, byTail: byTail)'
        actual = declaration(API, 'private static func buildReleaseIndex(')
        original = declaration(oracle, 'static func releaseIndex()')
        self.assertEqual(actual[actual.index(marker):actual.index(end)],
                         original[original.index(marker):original.index(end)])

    def test_real_production_harness_assembles(self):
        source = catalog_source()
        self.assertIn('state.releaseWaiters.append(continuation)', source)
        self.assertIn('late cold parse replaced refresh epoch', source)
        self.assertIn('enum LegacyCatalogOracle', source)


class CatalogNativeProduction(unittest.TestCase):
    def test_actual_catalog_isolation_and_legacy_oracle(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            if os.getenv('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Swift required; production catalog runtime NOT executed')
            self.skipTest('No local swiftc; production catalog NOT compiled/executed')
        with tempfile.TemporaryDirectory(prefix='provider-catalog-') as tmp:
            swift, binary = Path(tmp) / 'Catalog.swift', Path(tmp) / 'catalog'
            swift.write_text(catalog_source())
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(swift), '-o', str(binary)], text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, 'Compile failure is NOT a native mutant kill:\n' + result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('production catalog single-flight / main heartbeat / cancel ticket / late parse / snapshot caches / legacy oracle', result.stdout)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main(verbosity=2)