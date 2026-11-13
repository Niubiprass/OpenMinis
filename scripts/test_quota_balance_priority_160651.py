#!/usr/bin/env python3
"""[T-quota-balance-priority] A real balance outranks usage; a failed probe
never discards a reading that already succeeded.

The old single routing function was replaced by `collect()` (query order) and
`Snapshot.primary` (display priority). This suite keeps the original intents
and the mutation checks that prove each rule is enforced:

  1. the saved-token balance is queried first,
  2. only a real remaining balance outranks usage,
  3. a later failed probe must not replace earlier successful readings,
  4. billing parsing stays pure and only trusts explicit USD evidence,
  5. per-key balances keep using that key's own token and user id.

Source contracts run everywhere. With swiftc the production protocol and
projection are extracted unchanged and run against fixtures. No network, no
keys, no iOS services.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
PROTOCOL = (ROOT / 'src/ios/Providers/RelayQuotaProtocol.swift').read_text()
COLLECT = 'private static func collect('
PRIMARY = 'static func primary(in values: [Reading]) -> Reading?'


def declaration(source, marker):
    start = source.index(marker)
    end = source.index('\n    }', start) + len('\n    }')
    return source[start:end]


def without_comments(text):
    return re.sub(r'//[^\n]*', '', text)


def routing_errors(body):
    body = without_comments(body)
    errors = []
    calls = re.findall(r'await\s+(fetch\w+|query)\(', body)
    if not calls or calls[0] != 'fetchNewAPIBalance':
        errors.append('saved access-token balance must be fetched first')
    if 'readings += values' not in body:
        errors.append('a successful balance must be kept alongside probe readings')
    if re.search(r'readings\s*=\s*values', body):
        errors.append('a later probe must not replace earlier readings')
    if 'return balance' in body:
        errors.append('account balance must not short-circuit the chat-key probe')
    if body.count('attempts.append') < 2:
        errors.append('failures must be recorded separately from readings')
    return errors


def priority_errors(body):
    body = without_comments(body)
    errors = []
    ranks = {name: int(rank) for name, rank in re.findall(r'case \.(\w+): return (\d+)', body)}
    for scope in ('accountBalance', 'keyQuota', 'subscription'):
        if scope not in ranks:
            errors.append(f'{scope} must rank as a real remaining balance')
    if 'usage' in ranks:
        errors.append('usage must not compete with a real balance')
    if 'if r.used != nil { return 10 }' not in body:
        errors.append('usage-only readings must rank below every real balance')
    ordered = [ranks[k] for k in ('accountBalance', 'keyQuota', 'subscription') if k in ranks]
    if len(ordered) == 3 and ordered != sorted(ordered):
        errors.append('account balance must outrank key quota and plan remainder')
    return errors


class BalancePrioritySource(unittest.TestCase):
    def test_routing_order_and_balance_only_early_returns(self):
        self.assertEqual(routing_errors(declaration(QUOTA, COLLECT)), [])

    def test_display_priority_prefers_real_balances(self):
        self.assertEqual(priority_errors(declaration(PROTOCOL, PRIMARY)), [])

    def test_reject_usage_query_before_access_token_query(self):
        body = declaration(QUOTA, COLLECT)
        block = body[body.index('if ctx.token?.isEmpty == false'):
                     body.index('metadataLock.lock(); let hint')]
        # Move the whole balance query after the probe loop.
        mutant = body.replace(block, '', 1)
        loop_end = mutant.index('        }\n', mutant.index('for source in order'))
        mutant = mutant[:loop_end] + block + mutant[loop_end:]
        self.assertIn('saved access-token balance must be fetched first', routing_errors(mutant))

    def test_reject_unconditional_usage_dominance(self):
        body = declaration(PROTOCOL, PRIMARY)
        mutant = body.replace('if r.used != nil { return 10 }', 'if r.used != nil { return -1 }', 1)
        # Either rule firing means the mutant was caught; assert on the union so
        # the test proves detection rather than one exact message.
        errors = priority_errors(mutant)
        self.assertTrue(
            'usage must not compete with a real balance' in errors
            or 'usage-only readings must rank below every real balance' in errors,
            errors)

    def test_reject_dropping_readings_when_a_probe_fails(self):
        body = declaration(QUOTA, COLLECT)
        mutant = body.replace('readings += values', 'readings = values', 1)
        self.assertIn('a later probe must not replace earlier readings', routing_errors(mutant))

    def test_billing_parser_is_pure_and_needs_usd_evidence(self):
        body = declaration(PROTOCOL, 'static func parseBilling(')
        for forbidden in ('Keychain', 'UIApplication', 'UserDefaults', 'URLSession'):
            self.assertNotIn(forbidden, body)
        self.assertIn('hard_limit_usd', body)
        self.assertIn('total_usage', body)
        # A bare "balance" field is not USD money until tagged or named _usd.
        self.assertIn('balance_usd', body)
        self.assertIn('uppercased() == "USD"', body)

    def test_per_key_credentials_and_cache_identity_stay_separate(self):
        body = declaration(QUOTA, 'private static func context(')
        self.assertIn('resolvedQuotaAccessToken(instanceId: instance.id, keyId: rowId)', body)
        self.assertIn('userID(instanceId: instance.id, keyId: rowId)', body)
        self.assertIn('instance.id, rowId', QUOTA)


def harness():
    projection = ('\nenum Projection {\n'
                  + declaration(QUOTA, 'struct QuotaInfo {') + '\n'
                  + 'static var lowThresholdUSD: Double { 3 }\n'
                  + declaration(QUOTA, 'static func project(') + '\n}\n')
    fixture = (ROOT / 'scripts/fixtures/quota_priority_fixtures.swift').read_text()
    return PROTOCOL + projection + fixture


class NativeRoutingFixtures(unittest.TestCase):
    def test_actual_swift_routing_with_fixture_responses(self):
        swiftc = shutil.which('swiftc')
        if swiftc is None:
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1' or sys.platform == 'darwin':
                self.fail('swiftc is required on the build host')
            self.skipTest('swiftc unavailable: native routing NOT compiled or executed')
        with tempfile.TemporaryDirectory(prefix='quota-priority-') as folder:
            path = Path(folder) / 'QuotaPriority.swift'
            binary = Path(folder) / 'quota-priority'
            path.write_text(harness())
            compiled = subprocess.run([swiftc, '-swift-version', '5', str(path), '-o', str(binary)],
                                      text=True, capture_output=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('quota-priority-ok', run.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
