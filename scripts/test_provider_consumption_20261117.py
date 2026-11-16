#!/usr/bin/env python3
"""Offline production-extracted consumption regression; no credentials/network.
Required gate: V64R_REQUIRE_SWIFT=1 python3 scripts/test_provider_consumption_20261117.py
or python3 scripts/test_provider_consumption_20261117.py --require-native.
Reuses the existing quota extractor READ-ONLY; never edits its fixtures/tests.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import test_quota_current_key_20261116 as quota

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'src/ios'
A = (P / 'Providers/AgentProvider.swift').read_text()
M = (P / 'Providers/ProviderMultiKeys.swift').read_text()
F = (P / 'Agent/Chat/AIChatViewModel+ProviderFactory.swift').read_text()
L = (P / 'Providers/LLMProviderFactory.swift').read_text()
T = (P / 'Views/Providers/ModelQuickTestSheet.swift').read_text()
O = (P / 'NativeOffloads/ModelUseOffloadBridge.swift').read_text()
Q = (P / 'Providers/ProviderQuotaService.swift').read_text()
FIX = ROOT / 'scripts/fixtures'
args = None

def decl(text, marker):
    return quota.declaration(text, marker)

def public(text):
    return re.sub(r'\b(?:fileprivate|private)\s+', '', text)

def top(text, marker):
    start = text.index(marker)
    return text[start:text.index('\n}', start) + 2]

def boundary(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]

def harness():
    # This contains real consumed/resolveCurrent/runAutomatic/refreshRow,
    # epoch/version/owner/persistence paths, not only the pure RefreshClock.
    base = quota.async_harness().split('@main struct QuotaAsyncFixture', 1)[0]
    base = base.replace(top(base, 'struct ProviderInstance:'), top(support(), 'struct ProviderInstance:'))
    base = base.replace(top(base, '@MainActor final class ProviderConfigStore'), top(support(), '@MainActor final class ProviderConfigStore'))
    # Match the entire current dependency declaration, not a stale one-line
    # literal: quota's synthetic key now has usage/masking members as well.
    base = base.replace(top(base, 'struct ProviderAPIKey {'), top(M, 'struct ProviderAPIKey:'))
    base = base.replace('enum SyntheticKeyStatus { case active, disabled }\n', '')
    base += '\n' + top(M, 'struct ProviderKeyLease:')
    base = base.replace(top(base, 'final class ProviderMultiKeyManager'), manager())
    # Real scheduling: a successful emitted event must actually query/commit
    # the selected synthetic row without an explicit manual refresh in tests.
    base = base.replace(decl(base, '    func scheduleAutomatic('), public(decl(Q, 'private func scheduleAutomatic(')))
    epoch = public(decl(Q, 'func consumptionEpoch('))
    if epoch not in base:
        base = base.replace('final class CacheAsyncHarness {', 'final class CacheAsyncHarness {\n' + epoch)
    base += '\nenum ProviderQuotaService { static let shared = CacheAsyncHarness() }\n'
    base += '\n' + top(M, 'struct ProviderConsumptionReporter:')
    base += '\nimport Darwin\n' + M[M.index('enum MultiKeyFailureKind:'):M.index('/// [T-multikey] One API key')]
    base += '\n' + top(M, 'enum MultiKeyStrategy:')
    base += '\n' + A[A.index('// MARK: - Protocol'):]
    helpers = support()
    helpers = helpers[helpers.index('// Remaining synthetic'):]  # replacements already installed above
    base += '\n' + helpers
    agent_factory = decl(F, '    static func makeAgentProvider(\n')
    base += '\n@MainActor final class AIChatViewModel {\n' + agent_factory + '\n}\n'
    llm_factory = decl(L, '    static func makeProviderWithConsumption(')
    builders = (FIX / 'provider_consumption_builders_20261117.swift').read_text()
    base += '\n@MainActor enum LLMProviderFactory {\n' + llm_factory + '\n' + builders + '\n}\n'
    quick = boundary(T, '            let request = try await LLMProviderFactory.makeProviderWithConsumption', '\n\n        case .imageGen:')
    base += '\n@MainActor func quickText(_ entry: ModelEntry) async throws -> SyntheticResult {\n' + quick + '\n}\n'
    stream = boundary(O, '                try Task.checkCancellation()\n                let requestConsumption = consumption?.started()\n                let stream =', '\n            }\n\n            // Write output file')
    base += '\nfunc offloadStream(_ provider: any LLMProvider, consumption: ProviderConsumptionReporter?) async throws {\nvar fullText = ""; var emittedOutput = false\nlet streamFd: Int32 = -1\nlet messages: [LLMMessage] = []; let systemPrompt: String? = nil; let maxTokens = 128; let temperature = -1.0\n' + stream + '\n_ = fullText; _ = emittedOutput\n}\n'
    send = boundary(O, '                try Task.checkCancellation()\n                let requestConsumption = consumption?.started()\n                let response =', '\n            }\n\n            // Determine output format')
    base += '\nfunc offloadSend(_ provider: any LLMProvider, consumption: ProviderConsumptionReporter?) async throws -> LLMResponse {\nlet messages: [LLMMessage] = []; let systemPrompt: String? = nil; let maxTokens = 128; let temperature = -1.0\n' + send + '\n}\n'
    raw = boundary(O, '        let overridesCredential = spec.headers.keys.contains', '\n\n        var out:')
    base += '\nfunc rawBoundary(_ openAI: OpenAIProvider, consumption: ProviderConsumptionReporter?, spec: SyntheticRawSpec) async throws {\nlet bodyObject: [String: Any]? = nil\n' + raw + '\n}\n'
    image_start = T.index('        case .imageGen:', T.index('let request = try await LLMProviderFactory.makeProviderWithConsumption'))
    image = T[image_start:T.index('        case .speechOut:', image_start)]
    image = image.split('\n', 1)[1]
    base += '\n@MainActor func quickImage(_ entry: ModelEntry) async throws -> SyntheticResult {\n' + image + '\n}\n'
    return base + (FIX / 'provider_consumption_behavior_20261117.swift').read_text()

def support():
    return (FIX / 'provider_consumption_support_20261117.swift').read_text()

def manager():
    skeleton = (FIX / 'provider_consumption_manager_20261117.swift').read_text()
    # Credential storage/config are synthetic. Lease selection, success
    # counters/lastUsed, event construction and notification are PRODUCTION.
    markers = ['private struct MainState:', 'private func fingerprint(', 'private func mainState(',
               'private func unlockedKeys(', 'private func reserveCursor(', 'func lease(for ',
               'private func increment(', 'func recordSuccess(lease:', 'func notifyQuotaSuccess(',
               'func reportQuotaSuccess(']
    return skeleton.replace('// PRODUCTION MEMBERS', '\n'.join(public(decl(M, marker)) for marker in markers))

class SourceContracts(unittest.TestCase):
    def test_production_extraction_is_exact(self):
        text = harness()
        for marker in ['func recordSuccess(lease:', 'func notifyQuotaSuccess(', 'func reportQuotaSuccess(',
                       'func lease(for ', 'func consumptionEpoch(', 'func consumed(_ success:',
                       'func runAutomatic(', 'func refreshRow(', 'func scheduleAutomatic(']:
            source = M if marker.startswith(('func recordSuccess', 'func notifyQuotaSuccess', 'func reportQuotaSuccess', 'func lease')) else Q
            if marker in ('func runAutomatic(', 'func refreshRow(', 'func scheduleAutomatic('): marker = 'private ' + marker
            self.assertIn(public(decl(source, marker)), text)
        self.assertIn(A[A.index('// MARK: - Protocol'):], text)
        self.assertIn(decl(F, '    static func makeAgentProvider(\n'), text)
        self.assertIn(decl(L, '    static func makeProviderWithConsumption('), text)
        self.assertIn(top(M, 'struct ProviderConsumptionReporter:'), text)
        self.assertIn(top(M, 'struct ProviderAPIKey:'), text)
        self.assertIn(top(M, 'struct ProviderKeyLease:'), text)
        self.assertEqual(text.count('struct ProviderAPIKey:'), 1)
        self.assertEqual(text.count('struct ProviderKeyLease:'), 1)
        self.assertNotIn('SyntheticKeyStatus', text)
        self.assertIn(boundary(O, '        let overridesCredential = spec.headers.keys.contains', '\n\n        var out:'), text)
        image_start = T.index('        case .imageGen:', T.index('let request = try await LLMProviderFactory.makeProviderWithConsumption'))
        self.assertIn(T[image_start:T.index('        case .speechOut:', image_start)].split('\n', 1)[1], text)
        self.assertIn('ProviderQuotaService.shared.consumed(event)', text)
        self.assertIn('self?.consumed(success)', Q)
        self.assertIn('service.consumed(success)', text)
        self.assertNotIn('https://api.openai', text)
        code = re.sub(r'//[^\n]*', '', text)
        for call in ('URLSession.shared', 'URLSession(configuration:', '.data(for:', '.data(from:', '.bytes(for:'):
            self.assertNotIn(call, code, 'fixture must not perform real transport')
        self.assertEqual(text.count('func consumptionEpoch('), 1)
        self.assertEqual(text.count('struct ProviderConsumptionReporter:'), 1)

    def test_frozen_identity_epoch_date_and_monotonic_last_used(self):
        single = boundary(A, '        if let consumption {', '        let manager = ProviderMultiKeyManager.shared')
        self.assertLess(single.index('consumption.started()'), single.index('baseline.streamAgentMessageClamped('))
        self.assertRegex(single, r'try Task.checkCancellation\(\)\s+let succeededAt = Date\(\)\s+requestConsumption.succeeded')
        self.assertLess(A.index('let credentialIdentity = ProviderQuotaSuccess.identity(lease.key)'), A.index('let stream = try await provider.streamAgentMessageClamped'))
        success = decl(M, 'func recordSuccess(lease:')
        self.assertNotIn('Date()', success)
        self.assertIn('max(list[index].lastUsed ?? succeededAt, succeededAt)', success)
        self.assertIn('succeededAt: succeededAt, requestEpoch: requestEpoch, credentialIdentity: credentialIdentity', success)
        self.assertNotIn('Date()', decl(M, 'func notifyQuotaSuccess('))
        self.assertLess(Q.index('guard success.requestEpoch == nil || success.requestEpoch == epoch'), Q.index('Task.detached', Q.index('func consumed(_ success:')))
        self.assertIn('$0 < success.succeededAt', decl(Q, 'func consumed(_ success:'))

    def test_success_only_single_key_and_no_double_report(self):
        single = boundary(A, '        if let consumption {', '        let manager = ProviderMultiKeyManager.shared')
        for forbidden in ('leaseAsync(', 'recordSuccess(', 'recordFailure(', 'retryLease', 'isActiveAsync'):
            self.assertNotIn(forbidden, single)
        self.assertIn('allowsMultiKey && supportsKeyPool', F)
        self.assertIn('allowsMultiKey: false', F)
        self.assertIn('if let consumption {', A)
        self.assertIn('instance.credentialType == .apiKey', L)
        self.assertIn('guard !key.isEmpty else { return nil }', M)
        self.assertIn('guard let requestEpoch else { return }', M)
        self.assertEqual(single.count('.succeeded(at: succeededAt)'), 1)

    def test_concrete_llm_routes_and_direct_boundaries(self):
        self.assertIn('return (provider, consumption)', L)
        self.assertNotIn('MultiKeyAgentProvider', L)
        for source in (T, O):
            self.assertIn('provider as? OpenAIProvider', source)
            self.assertIn('makeProviderWithConsumption', source)
        self.assertRegex(O, r'try Task.checkCancellation\(\)\s+let succeededAt = Date\(\)\s+requestConsumption\?\.succeeded')
        self.assertIn('let requestConsumption = consumption?.started()', O)
        self.assertIn('let consumption = request.consumption?.started()', T)

    def test_required_workflow_hook_present(self):
        workflow = (ROOT / '.github/workflows/ios15-v64-repair.yml').read_text()
        self.assertIn('V64R_REQUIRE_SWIFT=1 python3 scripts/test_provider_consumption_20261117.py', workflow)

    def test_fixture_scenarios_not_clock_only(self):
        behavior = (FIX / 'provider_consumption_behavior_20261117.swift').read_text()
        for label in ['off freezes main', 'empty ring no selection', 'must not report:',
                      'stream creation not consumption', 'partial + done + cancel no report',
                      'multi cannot double report', 'late A cannot steal B', 'lastUsed max preserves both counts',
                      'request epoch rejects old in-flight send even with identical key',
                      'OpenAI downcast preserved', 'Offload failure no report',
                      'emitted event did not schedule/commit real quota']:
            self.assertIn(label, behavior)
        self.assertNotIn('service.refreshRow(', behavior)
        self.assertIn('service.cachedQuota(instanceId: "event-to-quota")', behavior)

class NativeBehavior(unittest.TestCase):
    def compiler(self):
        compiler = shutil.which('swiftc')
        required = args.require_native or os.getenv('V64R_REQUIRE_SWIFT') == '1' or sys.platform == 'darwin'
        if not compiler:
            if required: self.fail('required native rejected: swiftc missing (no fixture behavior was executed)')
            self.skipTest('swiftc missing; production Swift behavior NOT executed')
        return compiler

    def execute(self, compiler, text, reject=False):
        with tempfile.TemporaryDirectory(prefix='consumption-fixture-') as tmp:
            source = Path(tmp) / 'consumption.swift'
            binary = Path(tmp) / 'consumption'
            source.write_text(text)
            compile_result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(source), '-o', str(binary)],
                                            capture_output=True, text=True, timeout=120)
            # A non-compiling mutant is NOT behavioral rejection evidence.
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=240)
            if reject:
                self.assertNotEqual(result.returncode, 0, 'unsafe mutant passed actual production fixture')
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('provider-consumption-production-ok', result.stdout)

    def test_native_production_paths_and_regression_mutants(self):
        compiler = self.compiler()
        text = harness()
        self.execute(compiler, text)
        mutants = [
            ('list[index].lastUsed = max(list[index].lastUsed ?? succeededAt, succeededAt)', 'list[index].lastUsed = succeededAt'),
            ('guard success.requestEpoch == nil || success.requestEpoch == epoch else { lock.unlock(); return }', '// unsafe: ignore request epoch'),
            ('                        let succeededAt = Date()\n                        for item in pending', '                        var succeededAt = Date()\n                        for item in pending'),
        ]
        # Delay-A mutant resamples only after the awaited active-check. It
        # compiles but must lose the true A-before-B ordering assertion.
        date_mutant = text.replace(mutants[2][0], mutants[2][1], 1)
        anchor = '                            manager.recordSuccess(lease: lease, for: instanceId,'
        self.assertIn(anchor, date_mutant)
        date_mutant = date_mutant.replace(anchor, '                            succeededAt = Date()\n' + anchor, 1)
        for old, new in mutants[:2]:
            with self.subTest(mutation=old):
                self.assertIn(old, text)
                self.execute(compiler, text.replace(old, new, 1), reject=True)
        self.execute(compiler, date_mutant, reject=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-native', action='store_true')
    args, remaining = parser.parse_known_args()
    unittest.main(argv=[sys.argv[0]] + remaining, verbosity=2)
