#!/usr/bin/env python3
"""Offline comprehensive quota tests. Actual production Swift, never user keys.

Run from any checkout. Source contracts always run. swiftc executes the actual
Foundation parser/request/merge/projection plus extracted routing with fixtures.
No compiler here is an explicit skip, never a claimed successful Swift build.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
PROTOCOL = (ROOT / 'src/ios/Providers/RelayQuotaProtocol.swift').read_text()


def declaration(source, marker):
    start = source.index(marker)
    end = source.index('\n    }', start) + len('\n    }')
    return source[start:end]


def harness():
    projection = ('\nenum Projection {\n'
                  + declaration(SOURCE, 'struct QuotaInfo {') + '\n'
                  + 'static var lowThresholdUSD: Double { 3 }\n'
                  + declaration(SOURCE, 'static func project(') + '\n}\n')
    fixture = (ROOT / 'scripts/relay_quota_protocol_fixtures.swift').read_text()
    fixture += r'''
let current = Date()
let currentAccount = try Q.parseAccount(data(#"{"quota":0}"#), root: root, now: current, scale: scale)[0]
let currentKey = try Q.parseNewAPI(tokenData, root: root, now: current, scale: scale)[0]
let projected = Projection.project(.init(owner: "a", readings: [currentAccount, currentKey], attempts: []))!
check(projected.kind == .balance && projected.balanceUSD == 0 && projected.amountUSD == 0, "legacy zero API")
check(projected.readings.count == 2 && projected.highlighted, "secondary low reading retained")
let projectedRaw = Projection.project(.init(owner: "a", readings: [rawAccount], attempts: []))!
check(projectedRaw.balanceUSD == nil && projectedRaw.amountUSD == nil && !projectedRaw.displayText.contains("$"), "raw quota never enters USD formatting")
let projectedUnknown = Projection.project(.init(owner: "a", readings: [noUsage], attempts: []))!
check(projectedUnknown.amountUSD == nil && projectedUnknown.displayText.contains("未知"), "cap without usage is not full balance")
let projectedUnlimited = Projection.project(.init(owner: "a", readings: [unlimitedToken], attempts: []))!
check(projectedUnlimited.kind == .used && projectedUnlimited.amountUSD == nil, "unlimited never fabricated zero")
let projectedRejected = Projection.project(.init(owner: "a", readings: rejected, attempts: []))!
check(projectedRejected.kind == .used && projectedRejected.balanceUSD == nil && !projectedRejected.highlighted, "invalid key not healthy balance")
let projectedStale = Projection.project(retained)!
check(projectedStale.isStale && projectedStale.observedAt == now && projectedStale.lastAttemptAt == failedAt, "legacy projection exposes accurate staleness")
let secondaryLine = RelayQuotaProtocol.secondaryLine([currentAccount, currentKey], primary: currentKey)
check(secondaryLine?.contains("账户余额") == true, "secondary pool keeps its own label")
check(secondaryLine?.contains("Key 额度") == false, "primary pool is not repeated")
let failedAttempt = RelayQuotaProtocol.Attempt(source: .sub2api, endpoint: "/v1/usage",
    attemptedAt: now, succeeded: false, failureNote: "额度接口返回 HTTP 500")
check(RelayQuotaProtocol.failureLine([failedAttempt])?.contains("HTTP 500") == true, "failure note surfaced once")
let probeOnly = RelayQuotaProtocol.Attempt(source: .openAIBilling, endpoint: "/x",
    attemptedAt: now, succeeded: false, failureNote: nil, probeMiss: true)
check(RelayQuotaProtocol.failureLine([probeOnly]) == nil, "probe miss is not a failure")
print("QuotaInfo projection fixtures PASS")
'''
    return PROTOCOL + projection + fixture


class SourceContracts(unittest.TestCase):
    def test_real_sources_and_legacy_projection(self):
        for symbol in ['struct QuotaInfo {', 'var balanceUSD: Double? = nil',
                       'var amountUSD: Double? = nil', 'enum Kind { case used, balance }',
                       'func cachedQuota(instanceId:', 'let ttl: TimeInterval = 300']:
            self.assertIn(symbol, SOURCE)
        self.assertIn('static func parseSub2API(', PROTOCOL)
        self.assertIn('static func parseNewAPI(', PROTOCOL)
        self.assertIn('static func parseAccount(', PROTOCOL)
        self.assertIn('static func parseBilling(', PROTOCOL)

    def test_account_does_not_short_circuit_chat_probe(self):
        body = declaration(SOURCE, 'private static func collect(')
        self.assertLess(body.index('fetchNewAPIBalance(ctx)'), body.index('for source in order'))
        self.assertNotIn('return balance', body)
        self.assertIn('readings += values', body)
        self.assertIn('hint.map { [$0] }', body)
        self.assertIn('probeMiss: hint == nil', body)
        self.assertIn('Source.probeOrder', body)
        self.assertNotIn('while ', body)

    def test_credential_routes_never_cross(self):
        context = declaration(SOURCE, 'private static func context(')
        self.assertIn('resolvedQuotaAccessToken(instanceId: instance.id, keyId: rowId)', context)
        self.assertIn('userID(instanceId: instance.id, keyId: rowId)', context)
        account = declaration(SOURCE, 'private static func fetchNewAPIBalance(')
        self.assertIn('root: ctx.accountRoot', account)
        self.assertIn('chatKey: nil, accountToken: ctx.token, userID: ctx.uid', account)
        query = declaration(SOURCE, 'private static func query(')
        self.assertIn('root: ctx.root', query)
        self.assertIn('chatKey: ctx.key, accountToken: nil, userID: nil', query)
        self.assertIn('completionHandler(nil)', PROTOCOL)
        self.assertIn('config.urlCredentialStorage = nil', SOURCE)
        self.assertIn('config.httpCookieStorage = nil', SOURCE)
        self.assertNotIn('body=\\(', SOURCE)

    def test_cache_identity_failure_and_generation(self):
        for token in ['SHA256.hash', 'instance.id, rowId', 'key, token ?? "", uid ?? "", cookie ?? ""',
                      'context?.owner != currentContext?.owner', 'epochs[instance.id] == epoch',
                      'keyCache.removeValue(forKey: instanceId)', 'merging(previous:',
                      'inFlight[slot] == nil', 'store.$authRevision', 'store.$config',
                      'ProviderMultiKeyManager.didChange', 'httpCookieStore.add(observer)']:
            self.assertIn(token, SOURCE)
        self.assertIn('previous.owner == owner', PROTOCOL)
        self.assertIn('old.refreshFailed = true', PROTOCOL)
        self.assertNotIn('old.observedAt =', PROTOCOL)

    def test_unit_and_unknown_amount_safety(self):
        self.assertNotIn('defaultQuotaPerUnit', SOURCE)
        self.assertIn('async -> Double?', SOURCE)
        self.assertIn('guard let qpu = await ProviderQuotaService.quotaPerUnit', SOURCE)
        self.assertNotIn('used ?? 0', PROTOCOL)
        self.assertIn('guard CFGetTypeID(n) != CFBooleanGetTypeID()', PROTOCOL)
        self.assertIn('static func secondaryLine(', PROTOCOL)
        self.assertIn('static func failureLine(', PROTOCOL)
        # Different pools are listed, never summed into one figure.
        self.assertNotIn('secondary.reduce', PROTOCOL)
        self.assertNotIn('remaining.reduce', PROTOCOL)
        self.assertIn('r.remaining = r.used.flatMap', PROTOCOL)
        self.assertIn('primary.unit.isUSD ? value : nil', SOURCE)
        self.assertIn('r.scope == primary.scope', SOURCE)
        self.assertIn('r.unit == primary.unit', SOURCE)
        self.assertIn('r.source == primary.source', SOURCE)

    def test_multikey_and_display_currency_are_preserved(self):
        body = declaration(SOURCE, 'func refreshAllKeys(')
        self.assertIn('withTaskGroup', body)
        self.assertIn('for row in rows', body)
        self.assertIn('rowId: row.id', body)
        self.assertIn('if count >= 4', body)
        self.assertIn('!ProviderMultiKeyManager.shared.isEnabled(for: $0.id)', SOURCE)
        for method in ['effectiveDisplayRate', 'displayCurrency', 'setCustomCurrency', 'rateOverride']:
            self.assertIn('func ' + method, SOURCE)

    def test_pure_harness_uses_production_without_reimplementation(self):
        text = harness()
        self.assertTrue(text.startswith(PROTOCOL))
        self.assertIn(declaration(SOURCE, 'static func project('), text)
        self.assertIn('foreign.readings.isEmpty', text)
        self.assertIn('management token retained', text)

    def test_foundation_behavior(self):
        swiftc = shutil.which('swiftc')
        if not swiftc:
            self.skipTest('swiftc unavailable in iSH; actual Swift harness must run on macOS CI')
        with tempfile.TemporaryDirectory(prefix='relay-quota-') as directory:
            path = Path(directory)
            swift = path / 'main.swift'
            swift.write_text(harness())
            binary = path / 'quota-tests'
            compiled = subprocess.run([swiftc, '-swift-version', '5', str(swift), '-o', str(binary)],
                                      text=True, capture_output=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('QuotaInfo projection fixtures PASS', run.stdout)
            print(run.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
