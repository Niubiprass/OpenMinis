#!/usr/bin/env python3
"""Offline production-extracted dirty/detail fixtures; synthetic accounts only.
Required native entry (macOS): V64R_REQUIRE_SWIFT=1 python3 scripts/test_quota_detail_repair_20261117.py
No Swift is SKIP locally, never a PASS; required/macOS fails closed.
"""
import re
import subprocess
import unittest
import test_quota_current_key_20261116 as original
from test_quota_current_key_20261116 import ROOT, Q, declaration, storage_harness

D = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
FIX = ROOT / 'scripts/fixtures'
START = '// BEGIN QUOTA_DETAIL_SNAPSHOT_LOADER'
END = '// END QUOTA_DETAIL_SNAPSHOT_LOADER'

def unprivate(text):
    # Access only, not behavior: native fixture can inspect bounded task slots.
    return re.sub(r'\b(?:fileprivate|private)(?:\(set\))?\s+', '', text)

def dirty_harness():
    return storage_harness().split('@main struct QuotaStorageFixture', 1)[0] + (FIX / 'quota_dirty_reschedule_async_20261117.swift').read_text()

def detail_loader(source=D):
    return unprivate(source.split(START, 1)[1].split(END, 1)[0])

def detail_harness():
    base = storage_harness().split('@main struct QuotaStorageFixture', 1)[0]
    members = ['struct KeyQuota:', 'private func attach(', 'func quotaRows(', 'static func mask(',
               'func refreshQuota(', 'func refreshAllKeys(']
    extracted = '\n'.join(unprivate(declaration(Q, marker)) for marker in members)
    base = base.replace('final class CacheAsyncHarness {', 'final class CacheAsyncHarness {\nstatic let shared = CacheAsyncHarness()\n' + extracted)
    base = base.replace('func publishRevision(_ id: String) {}', unprivate(declaration(Q, 'private func publishRevision(')))
    revision = next(line.strip() for line in Q.splitlines() if line.strip().startswith('@Published private(set) var revision'))
    base = base.replace('\nvar revision = 0\n', '\n' + unprivate(revision) + '\n', 1)
    base = base.replace('static var lowThresholdUSD: Double { 3 }', 'static var lowThresholdUSD: Double { FixtureThreshold.shared.read() }')
    return ('import Combine\n' + base + '\ntypealias ProviderQuotaService = CacheAsyncHarness\n' +
            (FIX / 'quota_detail_snapshot_support_20261117.swift').read_text() + detail_loader() +
            (FIX / 'quota_detail_snapshot_async_20261117.swift').read_text())

def assert_detail_fences(test, source):
    loader = detail_loader(source)
    accepts = declaration(loader, 'func accepts(_ request:')
    for value in ('instanceId == request.instance.id', 'scope == request.scope', 'generation == request.generation'):
        test.assertIn(value, accepts)
    worker = declaration(loader, 'func startProjection(')
    test.assertIn('guard projectionTask == nil, pending != nil', worker)
    test.assertIn('if !Task.isCancelled, accepts(request)', worker)
    manual = declaration(loader, 'func refresh(for instance:')
    test.assertIn('if accepts(request)', manual)
    test.assertEqual(manual.count('acceptsManual(instance, scope: wantedScope, version: version)'), 3)
    project = declaration(loader, 'func project(for instance:')
    test.assertNotIn('query(', project)
    test.assertNotIn('refreshQuota', project)
    test.assertIn('pending = Request', project)

class QuotaDetailSourceContracts(unittest.TestCase):
    def test_exact_real_service_extraction(self):
        for harness in (dirty_harness(), detail_harness()):
            for marker in ('func invalidate(instanceId:', 'func invalidateAll(', 'func warmCurrent(',
                           'func resolveCurrent(', 'func scheduleAutomatic(', 'func runAutomatic(',
                           'func refreshRow(', 'func invalidateRow(', 'func persistLatest(', 'static func persist('):
                self.assertEqual(declaration(harness, marker), unprivate(declaration(Q, marker)), marker)
        text = detail_harness()
        for marker in ('struct KeyQuota:', 'func attach(', 'func quotaRows(', 'func refreshQuota(', 'func refreshAllKeys('):
            self.assertEqual(declaration(text, marker), unprivate(declaration(Q, marker)), marker)
        self.assertIn(detail_loader(), text)
        self.assertEqual(declaration(text, 'func publishRevision('), unprivate(declaration(Q, 'private func publishRevision(')))
        self.assertIn('ProviderQuotaService.shared.$revision.dropFirst().sink', text)
        self.assertNotIn('URLSession(', text)
        self.assertNotIn('SecItemCopyMatching(', text)
        self.assertIn('FixturePlan.shared.count', text)

    def test_detail_has_one_real_published_revision_and_preserves_other_entries(self):
        revision = re.compile(r'^\s*(?:@Published\s+)?var revision\s*=\s*0\s*$', re.MULTILINE)
        detail = detail_harness()
        actual = [line.strip() for line in revision.findall(detail)]
        production = next(line.strip() for line in Q.splitlines() if line.strip().startswith('@Published private(set) var revision'))
        self.assertEqual(actual, [unprivate(production)])
        for text in (storage_harness(), dirty_harness()):
            self.assertEqual([line.strip() for line in revision.findall(text)], ['var revision = 0'])
        self.assertEqual(declaration(detail, 'func publishRevision('), unprivate(declaration(Q, 'private func publishRevision(')))
        self.assertIn('ProviderQuotaService.shared.$revision.dropFirst().sink', detail)

    def test_dirty_resume_epoch_origin_foreground_and_no_revision_restart(self):
        warm = declaration(Q, 'private func warmCurrent(')
        for value in ('guard let context = await self.resolveCurrent', 'expectedEpoch: epoch', 'validatedOrigin: origin', 'replacing: false'):
            self.assertIn(value, warm)
        scheduler = declaration(Q, 'private func scheduleAutomatic(')
        for value in ('epochs[instanceId] == expectedEpoch', 'currentOrigins[instanceId] == validatedOrigin', 'clocks[instanceId]?.running != true', '!replacing, scheduled[instanceId] != nil', 'deadline(active: active'):
            self.assertIn(value, scheduler)
        self.assertIn('if dirty { warmCurrent(instanceId: instanceId, expectedEpoch: epoch) }', declaration(Q, 'func invalidate(instanceId:'))
        self.assertIn('for (id, epoch) in dirtyEpochs', declaration(Q, 'private func invalidateAll('))
        self.assertNotIn('scheduleAutomatic', declaration(Q, 'private func publishRevision('))
        resolver = declaration(Q, 'private func resolveCurrent(')
        self.assertIn('capturedOrigin ?? invalidatedOrigin ?? Self.storedCurrent(instanceId)', resolver)
        self.assertIn('invalidatedOrigins[instanceId] = origin', declaration(Q, 'func invalidate(instanceId:'))
        self.assertIn('invalidatedOrigins[id] = origin', declaration(Q, 'private func invalidateAll('))
        self.assertEqual(declaration(Q, 'private func runAutomatic(').count('UIApplication.shared.applicationState == .active'), 2)

    def test_detail_observers_bounded_workers_and_generation_negative_control(self):
        assert_detail_fences(self, D)
        mutant = D.replace(' && generation == request.generation', '', 1)
        with self.assertRaises(AssertionError): assert_detail_fences(self, mutant)
        for value in ('.onChange(of: quotaService.revision)', '.onChange(of: quotaLowThreshold)',
                      '.onChange(of: store.authRevision)', '.onChange(of: instance)', 'quotaDetail.cancel()'):
            self.assertIn(value, D)
        body = D[D.index('struct ProviderInstanceDetailView:'):]
        self.assertNotIn('quotaRows(for:', body.replace('// call `quotaRows(for:)` from the body.', ''))
        self.assertNotIn('quotaRowsSnapshot =', body)
        self.assertEqual(body.count('quotaDetail.refresh(for:'), 2)
        self.assertIn('quotaDetail.isShowing(instance.id)', body)
        self.assertIn('quotaDetail.reload(for: instance)', declaration(D, 'private func reloadQuotaRows('))
        manual = declaration(detail_loader(), 'func refresh(for instance:')
        self.assertIn('manualTask == nil', manual)
        self.assertIn('defer { manualTask = nil }', manual)
        self.assertNotIn('manualTask = nil', declaration(detail_loader(), 'func cancel('))
        for marker in ('func consumptionEpoch(', 'func consumed(_ success: ProviderQuotaSuccess)'):
            self.assertEqual(declaration(detail_harness(), marker), unprivate(declaration(Q, marker)))

    def test_pricing_byte_identical_and_successat_writer_restore_preserved(self):
        head = subprocess.check_output(['git', '-C', str(ROOT), 'show', 'HEAD:src/ios/Providers/ProviderQuotaService.swift'], text=True)
        marker = 'final class ProviderPricingService:'
        self.assertEqual(Q[Q.index(marker):], head[head.index(marker):])
        self.assertIn('currentOrigin?.rowId != rowId || clocks[instanceId]?.lastSuccessAt == capturedSuccessAt', declaration(Q, 'private func invalidateRow('))
        self.assertIn('memoryVersions[instanceId, default: 0] == capturedVersion', declaration(Q, 'private func resolveCurrent('))
        self.assertNotIn('dictionaryRepresentation', declaration(Q, 'private static func persist('))

class QuotaDetailNativeProductionFixtures(unittest.TestCase):
    run_production = original.NativeProductionFixtures.run_production
    def test_native_dirty_resume_and_stranding_mutation(self):
        text = dirty_harness()
        self.run_production(text, 'quota-dirty-reschedule-ok', library=True)
        old = 'if dirty { warmCurrent(instanceId: instanceId, expectedEpoch: epoch) }'
        self.assertIn(old, text)
        self.run_production(text.replace(old, '', 1), 'quota-dirty-reschedule-ok', library=True, reject=True)

    def test_native_detail_and_generation_mutation(self):
        text = detail_harness()
        self.run_production(text, 'quota-detail-snapshot-ok', library=True)
        old = ' && generation == request.generation'
        self.assertIn(old, text)
        self.run_production(text.replace(old, '', 1), 'quota-detail-snapshot-ok', library=True, reject=True)

if __name__ == '__main__': unittest.main(verbosity=2)
