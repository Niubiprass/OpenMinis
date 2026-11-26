#!/usr/bin/env python3
"""Provider-list regression: layout scopes + actual cache/count Swift behavior.
No device/credential/network calls. Native rendering still needs device acceptance.
"""
import os
import re
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
KEY_MODEL = (IOS/'Providers/ProviderMultiKeys.swift').read_text()
KEY_VIEW = (IOS/'Views/Providers/MultiKeyManagerView.swift').read_text()
FIXTURES = ROOT/'scripts/fixtures'
PICKER = (IOS/'Views/Providers/UnifiedModelPicker.swift').read_text()
RELEASE = (IOS/'Providers/ModelReleaseIndex.swift').read_text()


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


def projection_declarations(store=STORE):
    """Exact production dependencies, shared by native and Apple UI harnesses."""
    markers = [
        '@Published private(set) var config: ProviderConfig {',
        'private struct ModelEntryProjection {',
        'private func derivedModelEntryProjection()',
        'func visibleEntryCount(', 'func hasVoiceModels('
    ]
    cache = 'private var modelEntryProjection: ModelEntryProjection? = nil'
    assert store.count(cache) == 1
    snapshot_epoch = 'private(set) var modelSnapshotRevision: UInt = 0'
    assert store.count(snapshot_epoch) == 1
    return '\n'.join([declaration(store, markers[0]), declaration(store, markers[1]),
                      cache, snapshot_epoch] + [declaration(store, marker) for marker in markers[2:]])


def projection_source(store=STORE):
    source = (FIXTURES/'provider_projection_support.swift').read_text()
    source += '\n@MainActor final class CountStore {\n' + projection_declarations(store)
    source += '\ninit(config: ProviderConfig) { self.config = config }\n}\n'
    shadow = declaration(store, 'func shadowVoiceProviders()')
    selection = '\n'.join(line.strip() for line in shadow.splitlines() if line.strip().startswith(
        ('let entries = projection.voiceEntriesByInstance[rep.id]',
         'let inputs = entries.filter', 'let outputs = entries.filter')))
    assert len(selection.splitlines()) == 3, 'Missing actual shadow input/output selection'
    main = (FIXTURES/'provider_projection_main.swift').read_text()
    assert main.count('// SHADOW_MODEL_SELECTION') == 1
    return source + main.replace('// SHADOW_MODEL_SELECTION', selection)


def assert_projection_contract(store):
    """Follow count -> cached pure projection -> ID aggregation/hidden rule."""
    count = declaration(store, 'func visibleEntryCount(')
    body = count[count.index('{') + 1:-1].strip()
    assert body == 'derivedModelEntryProjection().visibleCounts[instanceId] ?? 0', 'count must read projection'
    projection = declaration(store, 'private func derivedModelEntryProjection()')
    compact = re.sub(r'\s+', ' ', projection)
    assert 'if !entry.isHidden { visibleCounts[entry.providerInstanceId, default: 0] += 1 }' in compact, 'ID/hidden count aggregation'
    assert 'for entry in config.modelEntries {' in projection
    assert 'if let modelEntryProjection { return modelEntryProjection }' in projection
    assert 'modelEntryProjection = projection' in projection
    assert 'if entry.baseModel.isVoiceCandidate {' in projection
    assert 'voiceInstanceIds.insert(entry.providerInstanceId)' in projection
    assert 'voiceEntriesByInstance[entry.providerInstanceId, default: []].append(entry)' in projection
    assert 'modifiedAt > (latestModifiedAtByInstance[entry.providerInstanceId] ?? .distantPast)' in projection
    assert 'latestModifiedAtByInstance[entry.providerInstanceId] = modifiedAt' in projection
    hidden = declaration(projection, 'if !entry.isHidden {')
    assert 'voice' not in hidden and 'ModifiedAt' not in hidden, 'hidden must not filter legacy voice/timestamps'
    voice = declaration(projection, 'if entry.baseModel.isVoiceCandidate {')
    assert 'latestModifiedAtByInstance' not in voice, 'timestamp includes nonvoice'
    config = declaration(store, '@Published private(set) var config: ProviderConfig {')
    assert 'modelEntryProjection = nil' in declaration(config, 'didSet {'), 'config didSet must invalidate'
    has_voice = declaration(store, 'func hasVoiceModels(')
    assert 'derivedModelEntryProjection().voiceInstanceIds.contains(instanceId)' in has_voice
    for token in ('sorted', 'ModelReleaseIndex', 'ProviderKeychainHelper', 'UserDefaults',
                  'FileManager', 'URLSession', 'Data(contentsOf:', 'Task', 'await ',
                  'DispatchQueue', 'save(', '.write(', 'visibleEntries('):
        assert token not in count + projection + has_voice, 'impure/ranking count projection: ' + token
    assert '@MainActor\nfinal class ProviderConfigStore:' in store, 'production store must remain MainActor'


def projection_mutations(store=STORE):
    count = declaration(store, 'func visibleEntryCount(')
    fixed = count[:count.index('{') + 1] + '\n        return 2\n    }'
    mutations = {}
    for label, old, new in [
        ('drop-hidden', 'if !entry.isHidden {', 'if true {'),
        ('fixed-count', count, fixed),
        ('no-config-invalidation', '            modelEntryProjection = nil', '            // mutation: no invalidation')
    ]:
        assert store.count(old) == 1, 'Mutation anchor must be unique: ' + label
        mutations[label] = store.replace(old, new, 1)
    return mutations


def assert_picker_sort_contract(picker, store, release):
    worker = declaration(picker, 'private final class PickerSortWorker:')
    inputs = declaration(picker, 'private enum PickerSortInput:')
    for token in ('ProviderConfigStore', 'ModelEntry', 'ProviderInstance', 'ModelsDevAPI',
                  'ModelReleaseIndex.rank', 'SwiftUI', 'UserDefaults', 'Keychain', '.sync('):
        assert token not in worker + inputs, 'Worker leaked UI/catalog/credentials: ' + token
    assert 'private var pending: Request?' in worker
    assert 'let replaced = pending' in worker and 'pending = request' in worker
    assert 'replaced?.continuation.resume(throwing: CancellationError())' in worker
    assert 'private static let queue = DispatchQueue(' in worker and 'Self.queue.async' in worker
    assert 'withTaskCancellationHandler' in worker and 'onCancel: { cancellation.cancel() }' in worker
    assert worker.count('try cancellation.check()') >= 5
    assert 'struct Rank: Comparable, Sendable' in release
    assert 'modelSnapshotRevision &+= 1' in declaration(store, '@Published private(set) var config:')
    assert 'private(set) var modelSnapshotRevision: UInt = 0' in store
    load = declaration(picker, 'private func loadSections()')
    assert load.count('try await sortWorker.sort(') == 2
    assert load.count('guard isCurrent(ticket) else { return }') >= 4
    assert 'let entries = store.config.modelEntries' in load
    assert 'alphabetical[0].map { entries[$0] }' in load
    assert 'offsets.map { section.entries[$0] }' in load
    assert load.count('config.existingIds?()') == 1
    current = declaration(picker, 'private func isCurrent(')
    for token in ('generation: refreshGeneration', 'revision: store.configRevision',
                  'snapshotRevision: store.modelSnapshotRevision', 'key: cacheKey',
                  'return ticket.accepts(current: current, cancelled: Task.isCancelled)'):
        assert token in current
    cache = declaration(picker, 'private enum SectionCache')
    assert '@MainActor\n    private enum SectionCache' in picker
    assert 'snapshotRevision == snapshot' in cache
    rank = declaration(picker, 'private func captureReleaseKeys(')
    assert 'ModelsDevAPI.releaseIndex()' not in rank
    assert load.count('await ModelsDevAPI.prepareReleaseIndex()') == 1
    assert 'captureReleaseKeys(captured, index: index)' in load
    before_await, after_await = load.split('await ModelsDevAPI.prepareReleaseIndex()')
    assert 'guard isCurrent(ticket) else { return }' in before_await
    assert 'guard isCurrent(ticket) else { return }' in after_await.split('captureReleaseKeys')[0]
    assert 'index: index' in rank
    assert '@MainActor\n    private func captureReleaseKeys(' in picker
    assert 'resolve(modelId, index: index)' in declaration(release, 'static func rank(')
    candidates = declaration(picker, 'private func candidateEntries(')
    for token in ('!entry.isHidden', 'store.instance(for: entry.providerInstanceId)?.isEnabled == true',
                  'matchesPreference(', 'pool.append(.systemASROnline)', 'pool.append(.systemASROffline)',
                  'pool.append(.systemTTS)', 'ModelEntry.systemTTSVoiceEntries()',
                  'config.candidateFilter', '!existing.contains($0.id)'):
        assert token in candidates
    assert '.onChange(of: store.modelSnapshotRevision)' in picker
    assert '.onChange(of: configurationKey)' in picker
    assert 'makeCacheKey(existingIds: nil)' in declaration(picker, 'private var configurationKey:')
    enqueue = declaration(worker, 'private func enqueue(')
    assert enqueue.index('try request.cancellation.check()') < enqueue.index('pending = request')
    assert 'Task.detached' not in worker + load


def picker_sort_source():
    support = (FIXTURES/'provider_picker_sort_main.swift').read_text()
    # Real production algorithms; stubs supply data shapes / in-memory catalog only.
    parts = ['import Foundation', support.split('// PRODUCTION_DECLARATIONS')[0],
             declaration(RELEASE, 'enum ModelReleaseIndex {')]
    for marker in ('private enum PickerSortInput:', 'private struct PickerBuildTicket:',
                   'private final class PickerSortCancellation:', 'private final class PickerSortWorker:'):
        parts.append(declaration(PICKER, marker))
    parts.append('@MainActor final class SortReference {\nvar config: ProviderConfig\ninit(config: ProviderConfig) { self.config = config }\n')
    parts.append(declaration(STORE, 'private func sortedEntries(').replace('private func', 'func', 1))
    parts.append(declaration(STORE, 'static func sortedByReleaseRank('))
    parts.append('}\n')
    parts.append(support.split('// PRODUCTION_DECLARATIONS')[1])
    return '\n'.join(parts)


def quota_row_source(view=VIEW):
    support = (FIXTURES/'provider_quota_row_projection.swift').read_text()
    assert support.count('// PRODUCTION_LOADER') == 1
    return support.replace('// PRODUCTION_LOADER', declaration(
        view, '@MainActor final class ProviderQuotaRowProjectionLoader:'))


def assert_quota_row_contract(view):
    loader = declaration(view, '@MainActor final class ProviderQuotaRowProjectionLoader:')
    row = declaration(view, 'private struct InstanceRow: View')
    body = declaration(row, 'var body: some View')
    assert 'cachedQuota(' not in row, 'quota read must not return to row/body'
    assert '@ObservedObject private var quotaService' not in row, 'global revision must not redraw all rows'
    assert '@StateObject private var quotaLoader = ProviderQuotaRowProjectionLoader()' in row
    assert 'let quota = quotaLoader.value(for: quotaScope)' in body
    assert 'quotaService.refreshAllIfNeeded(instances: [instance])' in body
    assert '.onReceive(quotaService.$revision.receive(on: DispatchQueue.main))' in body, 'read after willSet'
    assert 'UserDefaults.didChangeNotification' in row
    assert '.onReceive(thresholdChanges.receive(on: DispatchQueue.main))' in body
    assert '.onChange(of: quotaScope)' in body
    assert 'quotaLoader.cancel()' in declaration(body, '.onDisappear {')
    assert 'guard isQuotaVisible else { return }' in declaration(row, 'private func projectQuota()')
    assert 'credentialGeneration = ProviderRowCredentialCache.shared.generation' in body
    assert 'if display != value { display = value }' in declaration(loader, 'private func publish(')
    assert loader.count('@Published') == 1, 'publish display only'
    assert 'struct Display: Equatable, Sendable' in loader
    assert 'private var pending: Request?' in loader
    start = declaration(loader, 'private func startProjection()')
    assert 'guard projectionTask == nil, let request = pending else { return }' in start
    assert 'Task { [weak self] in' in start
    assert start.index('await Self.buildDisplay') < start.index('guard let self else')
    assert 'if !Task.isCancelled, self.accepts(request),' in start, 'canceled read must never publish'
    assert 'isCurrent(request.scope, request.quotaRevision)' in start
    assert 'scope == request.scope && generation == request.generation' in declaration(loader, 'private func accepts(')
    assert 'withTaskCancellationHandler' in loader and 'onCancel: { worker.cancel() }' in loader
    assert 'Task.detached(priority: .utility)' in loader
    assert 'deinit { projectionTask?.cancel() }' in loader
    cancel = declaration(loader, 'func cancel()')
    for token in ('generation &+= 1', 'scope = nil; pending = nil', 'projectionTask?.cancel()', 'publish(nil)'):
        assert token in cancel
    assert 'projectionTask = nil' not in cancel, 'cancellation cannot free a blocked read slot'
    current = declaration(loader, 'private static func currentScopeMatches(')
    for token in ('ProviderQuotaService.shared.revision == revision', 'scope == makeScope(instance: current',
                  'store.authRevision', 'store.configRevision', 'store.modelSnapshotRevision',
                  'ProviderRowCredentialCache.shared.generation'):
        assert token in current, 'missing live fence: ' + token
    scope = declaration(loader, 'static func makeScope(')
    for field in ('instance.id', 'instance.providerType.rawValue', 'instance.credentialType.rawValue',
                  'instance.customBaseURL', 'instance.appendV1Suffix', 'instance.subscriptionAccountIds',
                  'instance.subscriptionActiveAccountId'):
        assert field in scope, 'missing row ownership field: ' + field
    read = declaration(loader, 'nonisolated private static func readCached(')
    assert 'ProviderQuotaService.shared.cachedQuota(instanceId: scope.instanceId)' in read
    for token in ('refreshAllIfNeeded', 'refreshQuota(', 'KeychainHelper.', 'URLSession', '.sync(',
                  'Task.yield', 'Data(contentsOf:', 'FileManager'):
        assert token not in loader, 'loader acquired request/I/O API: ' + token


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
        self.assertIn('.listRowBackground(', browsing)
        self.assertIn('Color(UIColor.secondarySystemGroupedBackground)', browsing)
        self.assertIn('let isLastMember = instance.id == members.last?.id', browsing)
        self.assertIn('ProviderRowSeparator(isLastMember: isLastMember)', browsing)
        self.assertIn('.listRowSeparator(.hidden)', browsing)
        self.assertNotIn('.clipShape(', declaration(VIEW, 'private func providerLink('))
        self.assertNotIn('UISwipeAction', VIEW)

    def test_card_gap_reserves_content_space_and_internal_lines(self):
        editing = declaration(VIEW, 'if isSortingProviders {')
        self.assertIn('.padding(.bottom, entry.isLastMember ? 10 : 0)', editing)
        self.assertIn('.padding(.bottom, entry.isLastMember ? 10 : 0)', declaration(VIEW, 'private func rowBackground('))
        content = declaration(VIEW, 'private func rowBackground(')
        self.assertNotIn('.overlay', declaration(VIEW, 'private func rowContent('))
        self.assertIn('ProviderRowSeparator(isLastMember: entry.isLastMember)', content)
        separator = declaration(VIEW, 'private struct ProviderRowSeparator: View')
        self.assertIn('if !isLastMember {', separator)
        self.assertIn('Color(UIColor.separator)', separator)
        self.assertIn('1 / UIScreen.main.scale', separator)
        self.assertIn('.allowsHitTesting(false)', separator)
        self.assertIn('.accessibilityHidden(true)', separator)
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
        assert_quota_row_contract(VIEW)
        assert_projection_contract(STORE)
        body = declaration(row, 'var body: some View')
        for token in ('ProviderKeychainHelper', 'UserDefaults', 'FileManager', 'URLSession',
                      'ModelReleaseIndex', 'visibleEntries(', 'sorted('):
            self.assertNotIn(token, body)

    def test_quota_row_projection_guards_and_actual_harness(self):
        assert_quota_row_contract(VIEW)
        source = quota_row_source()
        self.assertIn(declaration(VIEW, '@MainActor final class ProviderQuotaRowProjectionLoader:'), source)
        self.assertNotIn('// PRODUCTION_LOADER', source)
        self.assertIn('synthetic gate only', source)

    def test_quota_row_source_negatives_are_rejected(self):
        for name, old, new in [
            ('body-read', 'let quota = quotaLoader.value(for: quotaScope)',
             'let quota = quotaService.cachedQuota(instanceId: instance.id)'),
            ('no-cancel-fence', 'if !Task.isCancelled, self.accepts(request),', 'if self.accepts(request),'),
            ('wrong-scope', 'scope == request.scope && generation == request.generation',
             'generation == request.generation'),
        ]:
            self.assertEqual(VIEW.count(old), 1, name)
            with self.subTest(mutation=name), self.assertRaises(AssertionError):
                assert_quota_row_contract(VIEW.replace(old, new, 1))

    def test_projection_source_mutations_are_rejected(self):
        assert_projection_contract(STORE)
        for label, mutant in projection_mutations().items():
            with self.subTest(mutation=label):
                with self.assertRaises(AssertionError):
                    assert_projection_contract(mutant)

    def test_native_and_ui_harness_include_exact_production_dependencies(self):
        source = projection_source()
        ui = (FIXTURES/'provider_list_ui_support.swift').read_text().replace(
            '// MODEL_ENTRY_PROJECTION_DECLARATIONS', projection_declarations())
        for marker in ('@Published private(set) var config: ProviderConfig {',
                       'private struct ModelEntryProjection {',
                       'private func derivedModelEntryProjection()', 'func visibleEntryCount(',
                       'func hasVoiceModels('):
            exact = declaration(STORE, marker)
            self.assertIn(exact, source)
            self.assertIn(exact, ui)
        self.assertNotIn('// MODEL_ENTRY_PROJECTION_DECLARATIONS', ui)
        self.assertNotIn('// SHADOW_MODEL_SELECTION', source)
        self.assertIn('@MainActor final class CountStore', source)
        # Flags are data stubs, not a fabricated modality classification model.
        types = (IOS/'Providers/LLMTypes.swift').read_text()
        candidate = declaration(types, 'var isVoiceCandidate: Bool')
        self.assertIn('isVoiceInputCandidate || isVoiceOutputCandidate', candidate)


    def test_picker_cold_sort_source_boundary(self):
        assert_picker_sort_contract(PICKER, STORE, RELEASE)
        source = picker_sort_source()
        for marker in ('private enum PickerSortInput:', 'private struct PickerBuildTicket:',
                       'private final class PickerSortCancellation:', 'private final class PickerSortWorker:'):
            self.assertIn(declaration(PICKER, marker), source)
        self.assertIn(declaration(RELEASE, 'enum ModelReleaseIndex {'), source)
        self.assertIn(declaration(STORE, 'private func sortedEntries(').replace('private func', 'func', 1), source)
        self.assertIn(declaration(STORE, 'static func sortedByReleaseRank('), source)

    def test_picker_stale_publish_source_mutations_are_rejected(self):
        for name, picker, store in [
            ('no-ticket-check', PICKER.replace('return ticket.accepts(current: current, cancelled: Task.isCancelled)', 'return true'), STORE),
            ('no-snapshot-epoch', PICKER, STORE.replace('modelSnapshotRevision &+= 1', '// no epoch')),
            ('inline-sort', PICKER.replace('let alphabetical = try await sortWorker.sort(input)', 'let alphabetical = try PickerSortWorker.orderedOffsets(input, cancellation: PickerSortCancellation())'), STORE),
            ('wrong-array', PICKER.replace('alphabetical[0].map { entries[$0] }', 'alphabetical[0].map { store.config.modelEntries[$0] }'), STORE),
        ]:
            with self.subTest(mutation=name), self.assertRaises(AssertionError):
                assert_picker_sort_contract(picker, store, RELEASE)


class ProviderListSwiftTests(unittest.TestCase):
    def compiler(self):
        compiler = shutil.which('swiftc')
        if compiler:
            return compiler
        if os.getenv('V64R_REQUIRE_SWIFT') == '1':
            self.fail('Swift required; provider list runtime tests NOT executed')
        self.skipTest('No local swiftc; production Swift NOT compiled/executed')

    def test_production_quota_row_projection(self):
        compiler = self.compiler()
        source = quota_row_source()
        with tempfile.TemporaryDirectory(prefix='provider-quota-row-') as tmp:
            swift, binary = Path(tmp)/'Row.swift', Path(tmp)/'row'
            swift.write_text(source)
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(swift), '-o', str(binary)],
                                    text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, 'Native compile required; NOT a mutation kill:\n' + result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('actual quota row projection', result.stdout)
            print(result.stdout.strip())

    def test_production_picker_sort_worker(self):
        compiler = self.compiler()
        source = picker_sort_source()
        with tempfile.TemporaryDirectory(prefix='provider-picker-sort-') as tmp:
            swift, binary = Path(tmp)/'Picker.swift', Path(tmp)/'picker'
            swift.write_text(source)
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(swift), '-o', str(binary)],
                                    text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, 'Native compile is required; NOT a mutation kill:\n' + result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('actual picker worker ordering / cancellation / ticket / captured snapshot', result.stdout)
            print(result.stdout.strip())

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
        source = projection_source()
        # Baseline must compile and pass BEFORE testing source mutations. A
        # compile error is never accepted as a behavioral mutation kill.
        variants = {'baseline': source}
        variants.update({name: projection_source(mutant) for name, mutant in projection_mutations().items()})
        baseline_passed = False
        with tempfile.TemporaryDirectory(prefix='provider-row-count-') as tmp:
            for name, variant in variants.items():
                if name != 'baseline':
                    self.assertTrue(baseline_passed, 'Baseline must compile and pass before any mutation')
                with self.subTest(variant=name):
                    swift, binary = Path(tmp)/(name + '.swift'), Path(tmp)/name
                    swift.write_text(variant)
                    result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library',
                                             str(swift), '-o', str(binary)],
                                            text=True, capture_output=True, timeout=120)
                    self.assertEqual(result.returncode, 0, 'NOT a mutation kill: ' + name + '\n' + result.stdout + result.stderr)
                    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
                    if name == 'baseline':
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn('production visible model count', result.stdout)
                        baseline_passed = True
                        print(result.stdout.strip())
                    else:
                        self.assertNotEqual(result.returncode, 0, 'Behavioral mutation survived: ' + name)
                        self.assertIn('Precondition failed', result.stdout + result.stderr,
                                      'Non-assertion crash is not a mutation kill: ' + name)
                        print('PASS: compiled production mutation killed by runtime assertion: ' + name)

    def test_editor_save_preserves_existing_credential_state(self):
        compiler = self.compiler()
        source = 'import Foundation\n' + declaration(KEY_MODEL, 'struct ProviderAPIKey:')
        action = declaration(KEY_VIEW, 'Button("保存") {')
        action = action[action.index('{') + 1:-1].replace('dismiss()', 'dismissed = true')
        source += '''
struct EditorProbe {
    let key: ProviderAPIKey
    var name = ""
    var replacement: String
    var enabled = true
    var existingKeys: [String] = []
    var duplicateKey = false
    var dismissed = false
    var saves = 0
    var savedName: String?
    var savedReplacement: String?
    var savedEnabled = true
    mutating func onSave(_ name: String?, _ replacement: String?, _ enabled: Bool) {
        saves += 1; savedName = name; savedReplacement = replacement; savedEnabled = enabled
    }
    mutating func save() {
''' + action + '''
    }
}
// Synthetic values only. The production Save closure runs verbatim.
let original = ProviderAPIKey(key: "synthetic-long-key-0123456789")
var unchanged = EditorProbe(key: original, name: "new note", replacement: original.key, enabled: false)
unchanged.save()
precondition(unchanged.saves == 1 && unchanged.savedReplacement == nil)
precondition(unchanged.savedName == "new note" && !unchanged.savedEnabled && unchanged.dismissed)
var blank = EditorProbe(key: original, replacement: "  ")
blank.save()
precondition(blank.savedReplacement == nil && blank.saves == 1)
var changed = EditorProbe(key: original, replacement: "  synthetic-replacement-key  ")
changed.save()
precondition(changed.savedReplacement == "synthetic-replacement-key" && changed.dismissed)
var duplicate = EditorProbe(key: original, replacement: "synthetic-duplicate", existingKeys: ["synthetic-duplicate"])
duplicate.save()
precondition(duplicate.duplicateKey && duplicate.saves == 0 && !duplicate.dismissed)
var preserved = EditorProbe(key: original, replacement: original.key, existingKeys: [original.key])
preserved.save()
precondition(preserved.saves == 1 && preserved.savedReplacement == nil && !preserved.duplicateKey)
print("PASS: production editor Save unchanged / blank / replace / duplicate")
'''
        with tempfile.TemporaryDirectory(prefix='multikey-editor-save-') as tmp:
            swift, binary = Path(tmp)/'main.swift', Path(tmp)/'save'
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
        ui_support = ui_support.replace('// MODEL_ENTRY_PROJECTION_DECLARATIONS', projection_declarations())
        declarations = '\n'.join(declaration(VIEW, marker) for marker in [
            'enum ProviderGroupOrder {', 'struct ProviderListEntry:', 'struct CardCornerShape:',
            'private struct ProviderRowSeparator: View',
            'final class ProviderRowCredentialCache:',
            '@MainActor final class ProviderQuotaRowProjectionLoader:', 'private struct InstanceRow: View'
        ])
        declarations += '\n' + declaration(KEY_MODEL, 'struct ProviderAPIKey:')
        declarations += '\n' + declaration(KEY_VIEW, 'struct MultiKeyEditSheet: View')
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
