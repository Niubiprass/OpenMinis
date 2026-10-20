#!/usr/bin/env python3
"""[T-quota-balance-priority] Saved access-token balances precede usage.

A successful /api/usage/token/ response may contain only spent usage. It must
not short-circuit /api/user/self or a real billing balance. Source contracts
run everywhere, including negative/mutation checks. When swiftc is available,
the ACTUAL routing function and QuotaInfo declaration are extracted unchanged
and exercised with async fixture fetchers (no network, keys, or iOS access).
Without swiftc the native part is explicitly SKIPPED, not reported as compiled.
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
SOURCE = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
ROUTE = 'private static func fetchOpenAIQuota('
BILLING = 'private static func fetchOpenAIBillingQuota('


def declaration(source, marker):
    """Extract a class member through its four-space-indented closing brace."""
    start = source.index(marker)
    end = source.index('\n    }', start) + len('\n    }')
    return source[start:end]


def routing_contract_errors(source):
    body = re.sub(r'//[^\n]*', '', declaration(source, ROUTE))
    errors = []
    calls = re.findall(r'await\s+(fetch\w+)\(', body)
    if calls != ['fetchNewAPIBalance', 'fetchKeyUsage', 'fetchOpenAIBillingQuota']:
        errors.append('saved access-token balance must be fetched first')
    account = r'if let balance = await fetchNewAPIBalance\([\s\S]*?rowId: rowId\)\s*\{\s*return balance\s*\}'
    if not re.search(account, body):
        errors.append('preserve the row id and return account balance, including zero')
    for name in ('keyQuota', 'billingQuota'):
        branch = rf'if let {name}, {name}\.kind == \.balance\s*\{{\s*return {name}\s*\}}'
        if not re.search(branch, body):
            errors.append(f'{name} may short-circuit only for .balance')
    returns = re.findall(r'\breturn\s+([^\n}]+)', body)
    if [r.strip() for r in returns] != ['balance', 'keyQuota', 'billingQuota', 'keyQuota ?? billingQuota']:
        errors.append('only fall back to usage after exhausting real balances')
    if not re.search(r'return keyQuota \?\? billingQuota\s*\}$', body):
        errors.append('billing failure must not discard successful key usage')
    return errors


class BalancePrioritySource(unittest.TestCase):
    def test_routing_order_and_balance_only_early_returns(self):
        self.assertEqual(routing_contract_errors(SOURCE), [])

    def test_billing_isolated_with_existing_safety_guards(self):
        body = declaration(SOURCE, BILLING)
        self.assertIn('key: String, baseURL: String', body)
        self.assertIn('let session = URLSession.shared', body)
        self.assertIn('guard let totalUsed else { return nil }', body)
        self.assertIn('hardLimit > 0, hardLimit < Self.relayPlaceholderLimitUSD', body)
        self.assertIn('totalUsed = cents.doubleValue / 100.0', body)
        self.assertIn('highlighted: low', body)
        self.assertIn('kind: .balance', body)
        self.assertIn('kind: .used', body)
        self.assertNotIn('fetchKeyUsage(', body)
        self.assertNotIn('fetchNewAPIBalance(', body)

    def test_original_per_key_token_resolver_still_used(self):
        body = declaration(SOURCE, 'private static func fetchNewAPIBalance(')
        self.assertIn('resolvedQuotaAccessToken(instanceId: instanceId, keyId: rowId)', body)
        self.assertIn('req.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")', body)
        self.assertIn('balanceRoot(instanceId: instanceId, apiBase: baseURL)', body)
        self.assertIn('Self.fetchQuota(for: instance, key: secret, rowId: row.id)', SOURCE)
        route = declaration(SOURCE, ROUTE)
        for write in ('saveQuotaAccessToken(', 'deleteQuotaAccessToken(', 'UserDefaults', 'SecItem'):
            self.assertNotIn(write, route)

    def test_results_keep_their_original_amount_kind_and_threshold(self):
        route = declaration(SOURCE, ROUTE)
        self.assertNotIn('QuotaInfo(', route)
        self.assertNotIn('amountUSD', route)
        self.assertNotIn('balanceUSD', route)
        self.assertNotIn('lowThresholdUSD', route)
        body = declaration(SOURCE, BILLING)
        self.assertIn('let low = remaining < Self.lowThresholdUSD', body)
        self.assertIn('balanceUSD: max(remaining, 0)', body)

    def test_unlimited_keys_remain_usage_only_fallback(self):
        body = declaration(SOURCE, 'private static func fetchKeyUsage(')
        unlimited = body[body.index('if unlimited {'):body.index('let quotaPoints:')]
        self.assertIn('kind: .used', unlimited)
        self.assertIn('highlighted: false', unlimited)
        self.assertNotIn('kind: .balance', unlimited)

    def test_reject_usage_query_before_access_token_query(self):
        route = declaration(SOURCE, ROUTE)
        match = re.search(r'        if let balance = await fetchNewAPIBalance[\s\S]*?\n        }\n', route)
        self.assertIsNotNone(match)
        block = match.group(0)
        mutant = route.replace(block, '', 1)
        position = mutant.index('        let billingQuota')
        mutant = mutant[:position] + block + mutant[position:]
        self.assertIn('saved access-token balance must be fetched first', routing_contract_errors(mutant))

    def test_reject_unconditional_usage_return(self):
        route = declaration(SOURCE, ROUTE)
        self.assertIn('if let keyQuota, keyQuota.kind == .balance', route)
        mutant = route.replace('if let keyQuota, keyQuota.kind == .balance', 'if let keyQuota', 1)
        self.assertIn('keyQuota may short-circuit only for .balance', routing_contract_errors(mutant))

    def test_reject_dropping_usage_when_billing_fails(self):
        route = declaration(SOURCE, ROUTE)
        self.assertIn('return keyQuota ?? billingQuota', route)
        mutant = route.replace('return keyQuota ?? billingQuota', 'return billingQuota', 1)
        self.assertIn('billing failure must not discard successful key usage', routing_contract_errors(mutant))


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
            path.write_text(native_harness(), encoding='utf-8')
            compiled = subprocess.run([swiftc, '-swift-version', '5', '-parse-as-library', str(path), '-o', str(binary)],
                                      capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('16 routing fixtures PASS', ran.stdout)


def native_harness():
    import json
    cases = [
        ('saved_token_beats_usage', 'account', 'keyUsed', 'billingBalance', 'account', ['account'], 'main'),
        ('saved_token_zero_is_balance', 'accountZero', 'keyUsed', 'billingBalance', 'accountZero', ['account'], 'main'),
        ('saved_token_keeps_low_warning', 'accountLow', 'nil', 'nil', 'accountLow', ['account'], 'main'),
        ('saved_token_beats_key_balance', 'account', 'keyBalance', 'billingBalance', 'account', ['account'], 'main'),
        ('key_balance_after_token_failure', 'nil', 'keyBalance', 'billingBalance', 'keyBalance', ['account', 'key'], 'main'),
        ('key_zero_is_balance', 'nil', 'keyZero', 'billingBalance', 'keyZero', ['account', 'key'], 'main'),
        ('billing_balance_beats_key_usage', 'nil', 'keyUsed', 'billingBalance', 'billingBalance', ['account', 'key', 'billing'], 'main'),
        ('billing_zero_beats_key_usage', 'nil', 'keyUsed', 'billingZero', 'billingZero', ['account', 'key', 'billing'], 'main'),
        ('billing_balance_without_key_endpoint', 'nil', 'nil', 'billingBalance', 'billingBalance', ['account', 'key', 'billing'], 'main'),
        ('billing_failure_keeps_key_usage', 'nil', 'keyUsed', 'nil', 'keyUsed', ['account', 'key', 'billing'], 'main'),
        ('keep_key_usage_over_monthly_usage', 'nil', 'keyUsed', 'billingUsed', 'keyUsed', ['account', 'key', 'billing'], 'main'),
        ('monthly_usage_is_last_resort', 'nil', 'nil', 'billingUsed', 'billingUsed', ['account', 'key', 'billing'], 'main'),
        ('all_failed_is_unavailable_not_zero', 'nil', 'nil', 'nil', 'nil', ['account', 'key', 'billing'], 'main'),
        ('known_zero_usage_survives_failure', 'nil', 'keyUsedZero', 'nil', 'keyUsedZero', ['account', 'key', 'billing'], 'main'),
        ('ring_a_keeps_own_row_id', 'accountLow', 'keyUsed', 'nil', 'accountLow', ['account'], 'ring-A'),
        ('ring_b_keeps_own_row_id', 'account', 'keyUsed', 'nil', 'account', ['account'], 'ring-B'),
    ]
    runs = []
    for name, account, key, billing, expected, steps, row in cases:
        runs.append(f'        await runCase({json.dumps(name)}, account: {account}, key: {key}, billing: {billing}, expected: {expected}, steps: {json.dumps(steps)}, row: {json.dumps(row)})')
    template = r'''
import Foundation

enum FixtureService {
    __INFO__

    __ROUTE__

    private static var accountResult: QuotaInfo?
    private static var keyResult: QuotaInfo?
    private static var billingResult: QuotaInfo?
    private static var trace: [String] = []
    private static var expectedRow = "main"
    private static var count = 0

    private static func fetchNewAPIBalance(instanceId: String, baseURL: String,
                                            rowId: String) async -> QuotaInfo? {
        precondition(instanceId == "fixture-provider" && rowId == expectedRow)
        precondition(baseURL == "https://example.invalid/v1")
        trace.append("account")
        return accountResult
    }

    private static func fetchKeyUsage(key: String, baseURL: String) async -> QuotaInfo? {
        precondition(key == "fixture-api-key" && baseURL == "https://example.invalid/v1")
        trace.append("key")
        return keyResult
    }

    private static func fetchOpenAIBillingQuota(key: String, baseURL: String) async -> QuotaInfo? {
        precondition(key == "fixture-api-key" && baseURL == "https://example.invalid/v1")
        trace.append("billing")
        return billingResult
    }

    private static func balance(_ label: String, _ amount: Double, _ low: Bool = false) -> QuotaInfo {
        QuotaInfo(displayText: label, highlighted: low, kind: .balance,
                  balanceUSD: amount, amountUSD: amount)
    }

    private static func used(_ label: String, _ amount: Double) -> QuotaInfo {
        QuotaInfo(displayText: label, highlighted: false, kind: .used, amountUSD: amount)
    }

    private static func runCase(_ name: String, account: QuotaInfo?, key: QuotaInfo?,
                                billing: QuotaInfo?, expected: QuotaInfo?,
                                steps: [String], row: String) async {
        accountResult = account
        keyResult = key
        billingResult = billing
        expectedRow = row
        trace = []
        let actual = await fetchOpenAIQuota(instanceId: "fixture-provider", key: "fixture-api-key",
                                          baseURL: "https://example.invalid/v1", rowId: row)
        precondition(trace == steps, "\(name): wrong fetch order \(trace)")
        switch (actual, expected) {
        case (nil, nil): break
        case let (.some(a), .some(e)):
            precondition(a.displayText == e.displayText && a.kind == e.kind &&
                         a.amountUSD == e.amountUSD && a.balanceUSD == e.balanceUSD &&
                         a.highlighted == e.highlighted, "\(name): wrong balance/usage result")
        default: fatalError("\(name): unexpected missing/present result")
        }
        count += 1
    }

    static func run() async {
        let account = balance("account", 8.75)
        let accountZero = balance("account-zero", 0, true)
        let accountLow = balance("account-low", 0.25, true)
        let keyBalance = balance("key-balance", 40)
        let keyZero = balance("key-zero", 0, true)
        let billingBalance = balance("billing-balance", 99)
        let billingZero = balance("billing-zero", 0, true)
        let keyUsed = used("key-used", 25.5)
        let keyUsedZero = used("key-used-zero", 0)
        let billingUsed = used("billing-used", 16)
__RUNS__
        print("\(count) routing fixtures PASS")
    }
}

@main struct QuotaPriorityMain {
    static func main() async {
        await FixtureService.run()
    }
}
'''
    return (template.replace('__INFO__', declaration(SOURCE, 'struct QuotaInfo {'))
            .replace('__ROUTE__', declaration(SOURCE, ROUTE))
            .replace('__RUNS__', '\n'.join(runs)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
