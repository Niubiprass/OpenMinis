#!/usr/bin/env python3
"""Daily check-in contracts: per-account ledger, no duplicate claims, and the
foreground-only scheduler. No vendor/account network requests.
macOS CI compiles the production Swift; iSH explicitly skips native tests.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
COORD = ROOT / 'src/ios/Providers/Subscription/SubscriptionCheckinCoordinator.swift'
ACCOUNTS = ROOT / 'src/ios/Providers/Subscription/SubscriptionAccounts.swift'
CREDIT = ROOT / 'src/ios/Providers/Subscription/SubscriptionCredit.swift'
APP = ROOT / 'src/ios/MinisApp.swift'


def section(text, begin, end):
    lo = text.index(begin)
    hi = text.index(end, lo)
    assert hi > lo
    return text[lo:hi]


class CheckinSourceContracts(unittest.TestCase):
    def test_ledger_is_per_account_and_not_per_slot(self):
        text = COORD.read_text()
        ledger = section(text, 'enum SubscriptionCheckinLedger {', '\n/// Foreground only')
        # Identity first so a re-login into the same vendor account keeps its
        # daily record; the slot id is only a fallback.
        self.assertIn('SubscriptionAccounts.identity(token)', ledger)
        self.assertIn('?? "\\(token.provider):slot:\\(slot)"', ledger)
        self.assertIn('SHA256.hash', ledger)
        # Completion is a confirmed day, never a mere attempt.
        self.assertIn('value.completedDay = requestDay', ledger)
        self.assertIn('value.attemptDay = SubscriptionCheckinPolicy.day(now)', ledger)
        self.assertNotIn('completedDay = SubscriptionCheckinPolicy.day(now)', ledger)

    def test_only_confirmed_completion_stops_queries(self):
        text = CREDIT.read_text()
        claim = section(text, '    static func claim(', '    private static func post(')
        self.assertIn('if SubscriptionCheckinLedger.completed(key) { return .alreadyCheckedIn }', claim)
        self.assertLess(claim.index('SubscriptionCheckinLedger.beginAttempt(key)'),
                        claim.index('try await checkin(context)'))
        # A crossing-midnight claim reply must not record the new day.
        self.assertIn('guard requestDay == SubscriptionCheckinPolicy.day(Date())', claim)
        # Cancellation and account replacement abort before the write.
        self.assertIn('try requireCurrent(context)', claim)

    def test_scheduler_is_foreground_only_and_never_replays(self):
        text = COORD.read_text()
        auto = section(text, 'enum SubscriptionAutoCheckin {', '\n}')
        self.assertIn('guard UIApplication.shared.applicationState == .active', auto)
        self.assertIn('UIApplication.shared.isProtectedDataAvailable', auto)
        # Every account attempt re-checks the parent is still enabled and the
        # switch still on — a toggle change mid-loop stops the claim.
        self.assertIn('fresh.isEnabled', auto)
        self.assertIn('fresh.subscriptionAutoCheckin', auto)
        # A cancelled/uncertain write returns instead of retrying blindly.
        self.assertIn('if error is CancellationError || Task.isCancelled { return }', auto)
        self.assertIn('SubscriptionCreditAPI.claim(context, automatic: true)', auto)
        # Once per day: one combined toast, never stacked alerts.
        self.assertIn('MinisToast.show', auto)
        self.assertNotIn('UIAlertController', auto)
        self.assertIn('markNotified', auto)
        # Leaving the foreground stops the tick and drops the pending attempt.
        self.assertIn('timer?.invalidate(); timer = nil', auto)
        self.assertIn('task?.cancel()', auto)

    def test_switches_default_on_and_are_persisted(self):
        instance = (ROOT / 'src/ios/Providers/ProviderInstance.swift').read_text()
        self.assertIn('subscriptionAutoCheckin = try c.decodeIfPresent(Bool.self, forKey: .subscriptionAutoCheckin) ?? true', instance)
        self.assertIn('subscriptionAutoFailover = (try? c.decodeIfPresent(Bool.self, forKey: .subscriptionAutoFailover)) ?? true', instance)
        # Off must round-trip; on stays implicit so old blobs are unchanged.
        self.assertIn('if !subscriptionAutoCheckin {', instance)
        store = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
        for required in ['func setSubscriptionAutoCheckin(', 'func setSubscriptionAutoFailover(']:
            self.assertIn(required, store)

    def test_app_wires_activation_without_blocking_launch(self):
        text = APP.read_text()
        self.assertEqual(text.count('SubscriptionAutoCheckin.activate()'), 1)
        self.assertEqual(text.count('SubscriptionAutoCheckin.deactivate()'), 1)
        # Must run after the launch yield, not inside the synchronous callback.
        active = text[text.index('SubscriptionAutoCheckin.activate()') - 900:
                      text.index('SubscriptionAutoCheckin.activate()')]
        self.assertIn('await Task.yield()', active)
        background = text.index('case .background:')
        self.assertGreater(text.index('SubscriptionAutoCheckin.deactivate()'), background)

    def test_account_row_shows_each_account_independently(self):
        text = ACCOUNTS.read_text()
        self.assertIn('struct SubscriptionAccountsSection: View', text)
        self.assertIn('SubscriptionAccountRow', text)
        for required in ['store.setActiveSubscriptionAccount', 'checkin?.canClaim == false',
                         'SubscriptionCreditAPI.claim(ctx)',
                         'SubscriptionCheckinLedger.markNotified']:
            self.assertIn(required, text)
        # No Task.detached around Keychain reads (non-Sendable instance).
        self.assertNotIn('Task.detached', text)


    def test_silent_terminal_and_receipt_contracts(self):
        coord, credit = COORD.read_text(), CREDIT.read_text()
        policy = section(coord, 'enum SubscriptionCheckinPolicy', '// END SUBSCRIPTION_CHECKIN_POLICY_PURE')
        self.assertIn('record.receiptDay == day(now)', policy)
        self.assertEqual(policy.count('if record.blockedDay == today { return false }'), 2)
        self.assertIn('notify: Bool = false', coord)
        self.assertIn('notify: false, now: now', coord)
        self.assertIn('noticeKeys = noticeKeys.filter', coord)
        self.assertIn('reminderKeys = reminderKeys.filter', coord)
        read = section(credit, '    static func checkin(', '    private static func queryCheckin(')
        for required in ['SubscriptionCheckinLedger.cachedStatus(key)', 'running.day == requestDay',
                         'SubscriptionCheckinLedger.remember(value', 'try requireCurrent(context)',
                         'guard requestDay == SubscriptionCheckinPolicy.day(Date())', 'traeCheckinRefusal(error)']:
            self.assertIn(required, read)
        self.assertNotIn('SubscriptionCheckinLedger.confirmed', read)
        claim = section(credit, '    static func claim(', '    private static func post(')
        catch = claim[claim.index('        } catch {'):]
        self.assertLess(catch.index('try requireCurrent(context)'), catch.index('SubscriptionCheckinLedger.blocked'))
        self.assertIn('notify: true', claim)
        accounts = section(ACCOUNTS.read_text(), '    private func claim()', '\n}')
        self.assertLess(accounts.index('needsSuccessNotice'), accounts.index('markNotified'))
        self.assertLess(accounts.index('markNotified'), accounts.index('MinisToast.show'))


class CheckinSwiftContract(unittest.TestCase):
    def test_actual_ledger_and_api_behaviour(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            if os.getenv('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Swift required; check-in runtime NOT executed')
            self.skipTest('Swift unavailable; production ledger/API harness NOT compiled/executed')
        coord, credit = COORD.read_text(), CREDIT.read_text()
        policy = section(coord, '// BEGIN SUBSCRIPTION_CHECKIN_POLICY_PURE', '// END SUBSCRIPTION_CHECKIN_POLICY_PURE')
        ledger = section(coord, '@MainActor\nenum SubscriptionCheckinLedger', '/// Foreground only:')
        billing = section(credit, '// BEGIN SUBSCRIPTION_BILLING_PURE', '// END SUBSCRIPTION_BILLING_PURE')
        api = section(credit, '@MainActor\nenum SubscriptionCreditAPI', '    private static func post(')
        # Replace only transport and app dependencies; execute the actual production methods.
        api += '''    private static func post(_ context: Context, host: String, path: String,
            body: [String: Any], mutation: Bool = false) async throws -> [String: Any] {
            try await CheckinTransport.send(mutation: mutation)
        }
    }
'''
        fixture = (ROOT / 'scripts/fixtures/subscription_checkin_runtime_harness.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='checkin-runtime-') as tmp:
            path, binary = Path(tmp) / 'Harness.swift', Path(tmp) / 'checkin'
            path.write_text('import Foundation\nimport CoreFoundation\n' + billing + policy + ledger + api + fixture)
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library', str(path), '-o', str(binary)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], env={**os.environ, 'HOME': tmp}, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('subscription-checkin-runtime-ok', result.stdout)


    def test_actual_policy_behaviour(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            if os.getenv('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Swift required; check-in policy validation NOT executed')
            self.skipTest('Swift unavailable; check-in policy NOT compiled/executed')
        text = COORD.read_text()
        begin, end = '// BEGIN SUBSCRIPTION_CHECKIN_POLICY_PURE', '// END SUBSCRIPTION_CHECKIN_POLICY_PURE'
        self.assertEqual(text.count(begin), 1)
        self.assertEqual(text.count(end), 1)
        region = section(text, begin, end)
        fixture = (ROOT / 'scripts/fixtures/subscription_checkin_harness.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='subscription-checkin-') as tmp:
            path, binary = Path(tmp) / 'main.swift', Path(tmp) / 'checkin'
            path.write_text('import Foundation\n' + region + '\n' + fixture)
            result = subprocess.run([compiler, '-swift-version', '5', str(path), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('subscription-checkin-ok', result.stdout)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
