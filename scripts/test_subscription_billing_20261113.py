#!/usr/bin/env python3
"""Subscription billing/check-in contracts. No vendor/account network requests.
macOS CI compiles production Swift; iSH explicitly skips native tests.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
CREDIT = ROOT / 'src/ios/Providers/Subscription/SubscriptionCredit.swift'
TOOLS = ROOT / 'src/ios/Providers/Subscription/SubscriptionLLMProvider.swift'

def section(text, begin, end):
    lo = text.index(begin)
    hi = text.index(end, lo)
    assert hi > lo
    return text[lo:hi]

class BillingSourceContracts(unittest.TestCase):
    def test_frozen_sources_and_license_exist(self):
        relative = 'docs/SUBSCRIPTION-BILLING-SOURCES.md'
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', relative], cwd=ROOT,
                                 capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0, 'Source/license file must be tracked, not only present locally')
        text = (ROOT / relative).read_text()
        for required in ['MIT License', 'Copyright (c) 2026 LaoDing',
                         'b04d865fa2da7f78f5a1d98d376306a65580fa11',
                         '531efd3578eca867acfe1bc0e882bbfedbcef175']:
            self.assertIn(required, text)

    def test_refresh_never_claims_and_claim_requires_fresh_status(self):
        text = CREDIT.read_text()
        read = section(text, '    static func checkin(', '    enum ClaimResult')
        claim = section(text, '    static func claim(', '    private static func post(')
        read_credit = section(text, '    static func credit(', '    static func checkin(')
        for endpoint in ['daily-checkin', 'checkin_credits/claim']:
            self.assertNotIn(endpoint, read)
            self.assertNotIn(endpoint, read_credit)
            self.assertIn(endpoint, claim)
        self.assertLess(claim.index('try await checkin(context)'), claim.index('if current.checkedIn'))
        self.assertLess(claim.index('if current.checkedIn'), claim.index('daily-checkin'))
        # One claim per ACCOUNT, not per provider: two accounts of the same
        # instance must never share a lock, and one account must never run two.
        self.assertIn('let key = SubscriptionCheckinLedger.key(context)', claim)
        self.assertIn('claiming.insert(key).inserted', claim)
        self.assertIn('defer { claiming.remove(key) }', claim)
        # A cached "already signed today" must stop before any status request.
        self.assertLess(claim.index('SubscriptionCheckinLedger.completed(key)'),
                        claim.index('try await checkin(context)'))
        # Completion is written only after the service accepted the claim.
        self.assertLess(claim.index('daily-checkin'), claim.index('SubscriptionCheckinLedger.confirmed(key'))
        self.assertIn('TraeCredential(context.credentials).deviceID', claim)
        self.assertNotIn('UUID()', claim)

    def test_transport_and_account_guards_survive(self):
        text = CREDIT.read_text()
        post = section(text, '    private static func post(', '\n}')
        self.assertGreaterEqual(post.count('try requireCurrent(context)'), 3)
        self.assertIn('allowedHosts: [host]', post)
        self.assertNotIn('refreshToken', post)
        self.assertNotIn('for attempt', post)  # uncertain writes are not replayed
        guard = section(text, '    static func requireCurrent(', '    static func credit(')
        for required in ['ProviderConfigStore.shared.instance', 'accountEpoch',
                         'current.credentials == context.credentials', 'Task.checkCancellation']:
            self.assertIn(required, guard)
        http = (ROOT / 'src/ios/Providers/Subscription/SubscriptionHTTPClient.swift').read_text()
        self.assertIn('completionHandler(nil)', http)

    def test_native_detail_location_and_independent_failures(self):
        accounts = (ROOT / 'src/ios/Providers/Subscription/SubscriptionAccounts.swift').read_text()
        detail = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
        # Exactly one account list, hosted where the old single-credential row
        # used to be, with all three account actions wired to the host view.
        self.assertEqual(detail.count('SubscriptionAccountsSection('), 1)
        for wired in ['onAdd: { beginAccountLogin(nil) }',
                      'onReauthenticate: { beginAccountLogin($0) }',
                      'onRemove: { slot in pendingAccountRemoval = slot }']:
            self.assertIn(wired, detail)
        self.assertNotIn('SubscriptionCreditSection', detail)
        self.assertNotIn('struct SubscriptionCreditSection: View',
                         (ROOT / 'src/ios/Providers/Subscription/SubscriptionCredit.swift').read_text())
        # The list must be able to sign in, re-sign-in and remove one account.
        self.assertIn('SubscriptionLoginSheet(instanceId: request.slot', detail)
        self.assertIn('store.addSubscriptionAccount(instanceId: instance.id, slot: slot, makeActive: true)', detail)
        self.assertIn('store.removeSubscriptionAccount(instanceId: instanceId, slot: slot)', detail)
        self.assertIn('store.setActiveSubscriptionAccount(instanceId: instance.id, slot: account.id)', accounts)
        # Independent per-account outcomes: one failed endpoint must not erase
        # the other's result, and nothing may write back for a replaced account.
        read = section(accounts, '    private func read(', '    private func claim()')
        self.assertEqual(read.count('catch {'), 2)
        self.assertEqual(read.count('try SubscriptionCreditAPI.requireCurrent(ctx)'), 2)
        self.assertIn('guard generation == request else { return }', read)
        # Claim is only enabled when the account truly can claim today.
        self.assertIn('checkin?.canClaim == false', accounts)
        self.assertIn('await read(ctx, generation: request)', accounts)
        self.assertIn('.onChange(of: store.authRevision)', accounts)
        self.assertIn('.onDisappear { reset() }', accounts)
        self.assertIn('签到', accounts)

    def test_tool_title_missing_uses_existing_preflight(self):
        text = TOOLS.read_text()
        args = section(text, '    func arguments(', '    mutating func accept(')
        for required in ['call.unparsedArguments == nil', 'case .object = call.arguments',
                         '!call.id.isEmpty', '!call.name.isEmpty',
                         'schema.removeValue(forKey: "required")', 'validateToolArguments']:
            self.assertIn(required, args)
        preflight = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ToolPreflight.swift').read_text()
        self.assertIn('static let preflightNonBlockingFields: Set<String> = ["tool_title"]', preflight)
        self.assertIn('toolDef.required.filter { !Self.preflightNonBlockingFields.contains($0) }', preflight)
        completed = section(text, '        case .toolCallEnd(', '        case .error(')
        self.assertIn('inputs[index]', completed)
        self.assertIn('== call.arguments', completed)
        self.assertIn('!completed.contains(where: { $0.id == call.id })', completed)

class BillingSwiftContract(unittest.TestCase):
    def test_actual_billing_parser_and_status_rules(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            if os.getenv('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Swift required; actual subscription billing validation NOT executed')
            self.skipTest('Swift unavailable; actual subscription billing NOT compiled/executed')
        text = CREDIT.read_text()
        begin, end = '// BEGIN SUBSCRIPTION_BILLING_PURE', '// END SUBSCRIPTION_BILLING_PURE'
        self.assertEqual(text.count(begin), 1)
        self.assertEqual(text.count(end), 1)
        region = section(text, begin, end)
        fixture = (ROOT / 'scripts/fixtures/subscription_billing_harness.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='subscription-billing-') as tmp:
            path, binary = Path(tmp) / 'main.swift', Path(tmp) / 'billing'
            path.write_text('import Foundation\nimport CoreFoundation\n' + region + '\n' + fixture)
            result = subprocess.run([compiler, '-swift-version', '5', str(path), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('subscription-billing-ok', result.stdout)
            print(result.stdout.strip())

if __name__ == '__main__':
    unittest.main(verbosity=2)
