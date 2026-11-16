#!/usr/bin/env python3
"""Offline current-Key regression. Production Swift, synthetic identities only.
macOS: V64R_REQUIRE_SWIFT=1 python3 scripts/test_quota_current_key_20261116.py
No compiler/SDK is a SKIP locally and a hard failure when required/on macOS.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Q = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
M = (ROOT / 'src/ios/Providers/ProviderMultiKeys.swift').read_text()
P = (ROOT / 'src/ios/Providers/RelayQuotaProtocol.swift').read_text()

def declaration(text, marker):
    start = text.index(marker)
    return text[start:text.index('\n    }', start) + 6]

FIXTURE_DEFAULTS = '''
// Dependency injection only: exact production UserDefaults calls use a unique
// Foundation suite. Fatal-error mutants cannot poison the next baseline run.
enum UserDefaults {
    static let standard = Foundation.UserDefaults(suiteName: "com.openminis.quota-fixture." + UUID().uuidString)!
}
'''

def writer_members():
    start = Q.index('    private var memoryVersions:')
    end = Q.index('    /// [T-quota-15min]', start)
    return re.sub(r'\b(?:fileprivate|private)\s+', '', Q[start:end])

def harness():
    pure = Q.split('// BEGIN QUOTA_CURRENT_KEY_PURE', 1)[1].split('// END QUOTA_CURRENT_KEY_PURE', 1)[0]
    members = ['struct QuotaInfo {', 'private struct StoredQuota:', 'private struct CacheEntry {',
               'private static func store(', 'private static func storedInfo(', 'private static func storedCurrent(',
               'private static func snapshot(', 'private static func reproject(', 'static func project(',
               'private func publishAggregate(']
    body = '\n'.join(re.sub(r'\b(?:fileprivate|private)\s+', '', declaration(Q, item)) for item in members)
    skeleton = '''
final class CacheHarness {
static let storedPrefix = "quota.lastKnown.v2.fixture."
static let currentPrefix = "quota.currentRow.v2.fixture."
static var lowThresholdUSD: Double { 3 }
var cache: [String: CacheEntry] = [:]
var keyCache: [String: [String: CacheEntry]] = [:]
var currentOrigins: [String: ProviderQuotaCurrentKeyPolicy.Origin] = [:]
var invalidatedOrigins: [String: ProviderQuotaCurrentKeyPolicy.Origin] = [:]
var rowOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
var selectableOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
var memoryVersions: [String: UInt64] = [:]
let lock = NSLock()
'''
    return P + FIXTURE_DEFAULTS + pure + skeleton + body + '\n}\n' + (ROOT / 'scripts/fixtures/quota_current_key_20261116.swift').read_text()

def async_harness():
    pure = Q.split('// BEGIN QUOTA_CURRENT_KEY_PURE', 1)[1].split('// END QUOTA_CURRENT_KEY_PURE', 1)[0]
    # The policy clock also has a consumed(at:) method. Extract only the real
    # service class, never a same-named pure helper and its following members.
    service = Q[Q.index('final class ProviderQuotaService:'):]
    members = ['struct QuotaInfo {', 'private struct StoredQuota:', 'private struct CacheEntry {',
               'private struct RefreshOutcome {', 'private final class RetryCapture', 'private struct Context {',
               'private static func store(', 'private static func storedInfo(', 'private static func storedCurrent(',
               'private static func snapshot(', 'private static func reproject(', 'static func project(',
               'private func publishAggregate(', 'private static func rowKey(', 'private func failureKey(',
               'private func resolveCurrent(', 'func consumptionEpoch(', 'func consumed(_ success: ProviderQuotaSuccess)', 'private func runAutomatic(',
               'private func refreshRow(', 'private func invalidateRow(', 'private func publishRevision(',
               'func cachedQuota(', 'func failureNote(', 'func noteFailure(', 'func clearFailure(',
               'private func warmCurrent(', 'private func invalidateAll(', 'func invalidate(instanceId:',
               'private func suspendAutomaticRefresh(']
    def extract(marker):
        if marker in ('private final class RetryCapture', 'private func failureKey('):
            return service[service.index(marker):].split('\n', 1)[0]
        return declaration(service, marker)
    body = '\n'.join(re.sub(r'\b(?:fileprivate|private)\s+', '', extract(item)) for item in members)
    # Extract only the event, not adjacent factory/reporter adapters added by
    # the success-boundary repair. Those have their own integration fixtures.
    success_start = M.index('struct ProviderQuotaSuccess:')
    success = M[success_start:M.index('\n}', success_start) + 2]
    skeleton = '''
final class CacheAsyncHarness {
static let storedPrefix = "quota.lastKnown.v2.asyncfixture."
static let currentPrefix = "quota.currentRow.v2.asyncfixture."
static let logger = SyntheticLogger()
static var lowThresholdUSD: Double { 3 }
static let metadataLock = NSLock()
static var relayHints: [String: RelayQuotaProtocol.Source] = [:]
let ttl: TimeInterval = 15 * 60
var scheduled: [String: Task<Void, Never>] = [:]
var fallbackTask: Task<Void, Never>?
var revision = 0
var cache: [String: CacheEntry] = [:]
var keyCache: [String: [String: CacheEntry]] = [:]
var failureNotes: [String: String] = [:]
var inFlight: [String: UUID] = [:]
var epochs: [String: UUID] = [:]
var currentOrigins: [String: ProviderQuotaCurrentKeyPolicy.Origin] = [:]
var invalidatedOrigins: [String: ProviderQuotaCurrentKeyPolicy.Origin] = [:]
var rowOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
var selectableOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
var validating = Set<String>()
var clocks: [String: ProviderQuotaCurrentKeyPolicy.RefreshClock] = [:]
var lastPublished: [String: String] = [:]
var scheduledCount: [String: Int] = [:]
let lock = NSLock()
'''
    support = (ROOT / 'scripts/fixtures/quota_current_key_async_support_20261116.swift').read_text()
    main = (ROOT / 'scripts/fixtures/quota_current_key_async_20261116.swift').read_text()
    return 'import CryptoKit\n' + P + FIXTURE_DEFAULTS + pure + success + support + skeleton + writer_members() + body + '\n}\n' + main

def storage_harness():
    text = async_harness().split('@main struct QuotaAsyncFixture', 1)[0]
    text = text.replace(FIXTURE_DEFAULTS, (ROOT / 'scripts/fixtures/quota_storage_backend_20261117.swift').read_text())
    stub = declaration(text, '    func scheduleAutomatic(_ id:')
    real = re.sub(r'\b(?:fileprivate|private)\s+', '', declaration(Q, 'private func scheduleAutomatic('))
    text = text.replace(stub, real)
    # Real foreground TTL entry, not a counter/policy substitute.
    foreground = re.sub(r'\b(?:fileprivate|private)\s+', '', declaration(Q, 'func refreshAllIfNeeded('))
    text = text.replace('final class CacheAsyncHarness {', 'final class CacheAsyncHarness {\n' + foreground)
    return text + (ROOT / 'scripts/fixtures/quota_storage_async_20261117.swift').read_text()

def assert_memory_isolation(test, source):
    service = source[source.index('final class ProviderQuotaService:'):]
    markers = ['func cachedQuota(', 'private func attach(', 'private func resolveCurrent(',
               'func consumed(_ success:', 'private func refreshRow(', 'private func invalidateRow(',
               'private func publishAggregate(', 'private func persistLatest(', 'private func schedulePersistence(']
    slow = re.compile(r'UserDefaults\.|JSONEncoder|JSONDecoder|Self\.(?:store\(|storedCurrent\(|storedInfo\(|project\(|reproject\(|persist\()|AppLocalized\(')
    for marker in markers:
        held = False
        for line in declaration(service, marker).splitlines():
            # Early guard/if returns unlock only that branch, not the live path.
            stripped = line.strip()
            if stripped in ('lock.lock()', 'self.lock.lock()'): held = True
            if stripped in ('lock.unlock()', 'self.lock.unlock()'): held = False
            if held:
                test.assertIsNone(slow.search(line), marker + ': slow operation under UI mutex: ' + line)
    for marker in ('private func enqueuePersistence(', 'private func resetPersistence('):
        body = declaration(service, marker)
        for forbidden in ('UserDefaults', 'JSONEncoder', 'JSONDecoder', '.async', '.sync', 'Self.store', 'Self.project'):
            test.assertNotIn(forbidden, body)

class SourceContracts(unittest.TestCase):
    def test_memory_only_lock_and_bad_store_mutant(self):
        assert_memory_isolation(self, Q)
        anchor = 'enqueuePersistence(.row(info, origin, entry.fetchedAt), instanceId: instance.id, domain: "row:" + rowId)'
        mutant = Q.replace(anchor, anchor + '\n            Self.store(info, instanceId: instance.id, origin: origin, at: entry.fetchedAt)', 1)
        with self.assertRaises(AssertionError): assert_memory_isolation(self, mutant)

    def test_ordered_writer_and_storage_fixture_exact_extraction(self):
        text = storage_harness()
        for marker in ('enum PersistenceValue {', 'struct PersistenceJob {', 'func enqueuePersistence(',
                       'func resetPersistence(', 'func schedulePersistence(', 'func persistLatest(',
                       'static func persist(', 'func cachedQuota(', 'func invalidate(instanceId:',
                       'func invalidateAll(', 'func warmCurrent(', 'func resolveCurrent(',
                       'func scheduleAutomatic(', 'func suspendAutomaticRefresh(',
                       'func refreshAllIfNeeded('):
            production = re.sub(r'\b(?:fileprivate|private)\s+', '', declaration(Q, marker))
            self.assertEqual(declaration(text, marker), production, marker)
        self.assertIn(writer_members(), text)
        self.assertNotIn('scheduledCount[id, default: 0] += 1', text)
        self.assertIn('DispatchQueue.main.async', text)
        self.assertIn('Foundation.UserDefaults.didChangeNotification', text)
        self.assertIn('queue: .main', text)
        self.assertIn('await mainProbe(save, id: "save")', text)
        self.assertIn('await cancellationGate.waitForArrival()', text)
        self.assertIn('saved.origin.owner == capturedOwner', declaration(Q, 'private static func persist('))
        self.assertIn('expectedUSD: 1.10', text)
        self.assertIn('row(nil) delete cannot overtake', text)
        self.assertIn('same-owner durable pointer survives successAt fence', async_harness())
        self.assertNotIn('dictionaryRepresentation', declaration(Q, 'private static func persist('))
        for forbidden in ('writer.sync', 'writer.wait', 'storageLock'):
            self.assertNotIn(forbidden, Q)
        self.assertNotIn('currentPrefix', declaration(Q, 'private static func store('))
        self.assertNotIn('durableSalt', declaration(Q, 'func cachedQuota(').split('// Projection')[0])

    def test_current_not_lowest_or_other_row(self):
        body = declaration(Q, 'private func publishAggregate(')
        self.assertIn('ProviderQuotaCurrentKeyPolicy.current(', body)
        self.assertIn('entry.origin == selected', body)
        for bad in ('.min', '.reduce', 'infos.first', 'entries.keys.sorted'):
            self.assertNotIn(bad, body)
        self.assertNotIn('storedInfo(instanceId: instanceId)?.info', Q)

    def test_final_success_separate_from_credentials_and_stats_retained(self):
        body = declaration(M, 'func recordSuccess(lease:')
        self.assertIn('successCount = increment', body)
        self.assertIn('schedulePersistence(for: instanceId)', body)
        self.assertIn('quotaCredentialsUnchanged: true', body)
        self.assertIn('notifyQuotaSuccess(lease: lease', body)
        self.assertIn('ProviderQuotaService.shared.consumed(event)', M)
        self.assertIn('credentialIdentity', Q)

    def test_cancel_owner_and_configuration_fences(self):
        body = declaration(Q, 'private func refreshRow(')
        for item in ('!Task.isCancelled', 'context?.owner != currentContext?.owner',
                     'epochs[instance.id] == epoch', 'inFlight[slot] == ticket', 'freshInstance',
                     'rowOrigins', 'origin: origin', 'merging(previous:'):
            self.assertIn(item, body)
        self.assertIn('canRestore(value.origin, current: origin)', Q)
        self.assertIn('durableSalt', Q)
        self.assertIn('key, token ?? "", uid ?? "", cookie ?? ""', Q)

    def test_current_only_foreground_throttle_and_real_bill(self):
        automatic = declaration(Q, 'private func runAutomatic(')
        self.assertIn('rowId: context.rowId', automatic)
        self.assertIn('currentOrigins[instanceId] == origin', automatic)
        self.assertIn('Task.isCancelled || outcome.deferred', automatic)
        self.assertNotIn('refreshAllKeys', automatic)
        self.assertIn('UIApplication.shared.applicationState == .active', automatic)
        self.assertIn('deadline(active:', automatic)
        self.assertIn('get(req, retry: ctx.retry)', Q)
        self.assertIn('value(forHTTPHeaderField: "Retry-After")', Q)
        self.assertIn('ctx.retry.retryAfter == nil', declaration(Q, 'private static func collect('))
        self.assertIn('let ttl: TimeInterval = 15 * 60', Q)
        self.assertIn('900_000_000_000', Q)
        self.assertNotIn('self.revision += 1', declaration(Q, 'private func refreshRow('))

    def test_async_repair_fences_and_safe_extraction(self):
        resolver = declaration(Q, 'private func resolveCurrent(')
        self.assertIn('mayCommitResolution(', resolver)
        self.assertIn('capturedSuccessAt: lastSuccessAt', resolver)
        self.assertIn('memoryVersions[instanceId, default: 0] == capturedVersion', resolver)
        self.assertIn('currentSuccessAt: clocks[instanceId]?.lastSuccessAt', resolver)
        self.assertIn('if changed { memoryVersions[instanceId, default: 0] &+= 1 }', resolver)
        self.assertIn('if changed {\n            _ = publishAggregate', resolver)
        epoch_method = declaration(Q, 'func consumptionEpoch(')
        self.assertIn('lock.lock(); defer { lock.unlock() }', epoch_method)
        event = declaration(Q, 'func consumed(_ success: ProviderQuotaSuccess)')
        guard = 'guard success.requestEpoch == nil || success.requestEpoch == epoch else { lock.unlock(); return }'
        self.assertIn(guard, event)
        self.assertLess(event.index(guard), event.index('Task.detached'))
        self.assertIn('requestEpoch: UUID? = nil', M)
        row = declaration(Q, 'private func refreshRow(')
        self.assertIn('includingUnavailable: true', row)
        self.assertIn('invalidateRow(instanceId:', row)
        self.assertNotIn('invalidate(instanceId:', row)
        self.assertIn('return .init(deferred: true)', row)
        retired = declaration(Q, 'private func invalidateRow(')
        self.assertNotRegex(retired, r'epochs\[instanceId\]\s*=(?!=)')
        self.assertNotIn('inFlight = inFlight.filter', retired)
        self.assertNotIn('keyCache.removeValue', retired)
        self.assertIn('activeOrigin?.owner == capturedOwner', retired)
        self.assertIn('currentOrigin?.owner == capturedOwner', retired)
        self.assertIn('capturedOwner: context?.durableOwner', row)
        generated = harness()
        self.assertNotIn('filevar ', generated)
        self.assertIn('var owner: String = ""', generated)
        self.assertIn('selectableOrigins', generated)
        asynchronous = async_harness()
        self.assertNotIn('filevar ', asynchronous)
        for marker in ('func resolveCurrent(', 'func runAutomatic(', 'func refreshRow(', 'func invalidateRow('):
            self.assertIn(marker, asynchronous)
        service_class = asynchronous[asynchronous.index('final class CacheAsyncHarness {'):]
        self.assertEqual(service_class.count('func consumed(_ success: ProviderQuotaSuccess)'), 1)
        self.assertNotIn('func consumed(at now:', service_class)
        self.assertNotIn('mutating func begin(', service_class)
        event_method = declaration(Q, 'func consumed(_ success: ProviderQuotaSuccess)')
        extracted_event = declaration(asynchronous, 'func consumed(_ success: ProviderQuotaSuccess)')
        self.assertEqual(extracted_event, re.sub(r'\b(?:fileprivate|private)\s+', '', event_method))
        self.assertIn('await gate.waitForArrival()', asynchronous)
        self.assertNotIn('URLSession(', asynchronous)
        self.assertNotIn('SecItemCopyMatching(', asynchronous)

    def test_selection_failure_and_currency_unchanged(self):
        old = subprocess.check_output(['git', '-C', str(ROOT), 'show', 'b0bec05:src/ios/Providers/ProviderMultiKeys.swift'], text=True)
        for marker in ('func lease(for instanceId:', 'func recordFailure(lease:', 'private func reserveCursor('):
            current = declaration(M, marker)
            if marker == 'func recordFailure(lease:':
                # Companion success-time repair keeps lastUsed monotonic on
                # failure too. Normalize ONLY that exact assignment; every
                # cooldown/selection/count/owner rule still matches baseline.
                current = current.replace('list[index].lastUsed = max(list[index].lastUsed ?? now, now)\n                list[index].updatedAt',
                                          'list[index].lastUsed = now; list[index].updatedAt')
            self.assertEqual(current, declaration(old, marker))
        self.assertIn('func effectiveDisplayRate', Q)
        self.assertIn('func setCustomCurrency', Q)
        self.assertIn('fetchNewAPIBalance(ctx)', declaration(Q, 'private static func collect('))

class NativeProductionFixtures(unittest.TestCase):
    def run_production(self, text, expected, *, library=False, reject=False):
        compiler = shutil.which('swiftc')
        required = os.getenv('V64R_REQUIRE_SWIFT') == '1' or sys.platform == 'darwin'
        if not compiler:
            if required: self.fail('Swift required; actual production native fixture NOT executed')
            self.skipTest('iSH has no Swift/Apple SDK: native fixture NOT compiled/executed')
        cmd = [compiler, '-swift-version', '5']
        if sys.platform == 'darwin':
            xcrun = shutil.which('xcrun')
            self.assertIsNotNone(xcrun, 'macOS SDK required; fail closed')
            sdk = subprocess.check_output([xcrun, '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
            cmd += ['-sdk', sdk]
        with tempfile.TemporaryDirectory(prefix='quota-current-') as tmp:
            source, binary = Path(tmp) / 'main.swift', Path(tmp) / 'fixture'
            source.write_text(text)
            if library: cmd.append('-parse-as-library')
            result = subprocess.run(cmd + [str(source), '-o', str(binary)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], env={**os.environ, 'HOME': tmp}, capture_output=True, text=True, timeout=30)
            if reject:
                self.assertNotEqual(result.returncode, 0, 'Unsafe behavior mutation was not rejected')
                self.assertNotIn(expected, result.stdout)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(expected, result.stdout)

    def test_native_policy_cache_and_current_key(self):
        self.run_production(harness(), 'quota-current-key-ok')

    def test_native_real_async_and_behavior_mutations(self):
        text = async_harness()
        self.run_production(text, 'quota-current-key-async-ok', library=True)
        mutations = [
            ('!Task.isCancelled, memoryVersions[instanceId, default: 0] == capturedVersion,\n              ProviderQuotaCurrentKeyPolicy.mayCommitResolution(\n                captured: capturedOrigin, current: currentOrigins[instanceId],\n                capturedSuccessAt: lastSuccessAt, currentSuccessAt: clocks[instanceId]?.lastSuccessAt)', '!Task.isCancelled'),
            ('Task.isCancelled || outcome.deferred', 'Task.isCancelled'),
            ('currentOrigin?.rowId != rowId || clocks[instanceId]?.lastSuccessAt == capturedSuccessAt', 'true'),
            ('rowId: rowId, includingUnavailable: true', 'rowId: rowId, includingUnavailable: false'),
            ('activeOrigin == nil || activeOrigin?.owner == capturedOwner,\n              currentOrigin?.rowId != rowId || currentOrigin?.owner == capturedOwner,\n              currentOrigin?.rowId != rowId || clocks[instanceId]?.lastSuccessAt == capturedSuccessAt', 'true')
        ]
        for old, new in mutations:
            with self.subTest(mutation=old):
                self.assertIn(old, text)
                self.run_production(text.replace(old, new, 1), 'quota-current-key-async-ok', library=True, reject=True)

    def test_native_blocked_storage_and_old_lock_mutant(self):
        text = storage_harness()
        self.run_production(text, 'quota-storage-async-ok', library=True)
        anchor = 'enqueuePersistence(.row(info, origin, entry.fetchedAt), instanceId: instance.id, domain: "row:" + rowId)'
        self.assertIn(anchor, text)
        unsafe = text.replace(anchor, anchor + '\n            Self.store(info, instanceId: instance.id, origin: origin, at: entry.fetchedAt)', 1)
        self.run_production(unsafe, 'quota-storage-async-ok', library=True, reject=True)

if __name__ == '__main__': unittest.main(verbosity=2)
