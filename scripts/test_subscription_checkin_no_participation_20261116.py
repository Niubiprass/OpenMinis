#!/usr/bin/env python3
"""Focused no-participation regression: source guards + REAL production Swift.
No Python implementation of the runtime policy, vendor calls or device state.
Required on future macOS CI: V64R_REQUIRE_SWIFT=1 python3 <this file>.
"""
import unittest
import test_subscription_checkin_20261113 as checkin


class NoParticipationContracts(unittest.TestCase):
    def test_qualification_before_any_attempt_or_cleanup(self):
        text = checkin.CREDIT.read_text()
        claim = checkin.section(text, '    static func claim(', '    private static func post(')
        qualified = claim.index('guard current.canClaim')
        for call in ['SubscriptionCheckinLedger.beginAttempt', 'SubscriptionCheckinLedger.clearClaimOutcome']:
            self.assertGreater(claim.index(call), qualified)
        self.assertLess(claim.index('guard current.eligibility != .unknown'), qualified)
        self.assertIn('if automatic && !SubscriptionCheckinLedger.canAttempt(key)', claim)
        self.assertIn('checkin(context, forceRefresh: true)', claim)
        auto = checkin.COORD.read_text().split('enum SubscriptionAutoCheckin {', 1)[1]
        self.assertNotIn('SubscriptionCheckinLedger.beginAttempt', auto)

    def test_exclusion_unknown_and_attempts_never_create_journal(self):
        text = checkin.COORD.read_text()
        for begin, end in [('    static func beginAttempt(', '    /// Caller owns'),
                           ('    static func beginClaim(', '    static func failedClaim('),
                           ('    static func unknown(', '    /// Unmapped refusal'),
                           ('    static func blocked(', '    static func cachedStatus(')]:
            body = checkin.section(text, begin, end)
            self.assertNotIn('write(key', body)
            self.assertNotIn('UserDefaults.standard.set', body)
        self.assertNotIn('value.blockedDay = requestDay', text)
        self.assertIn('private static let memoryLimit = 128', text)
        self.assertIn('participation.count >= memoryLimit', text)
        self.assertIn('participation = participation.filter { $0.value.day == today }', text)

    def test_old_failure_migration_is_identity_scoped(self):
        text = checkin.COORD.read_text()
        read = checkin.section(text, '    static func record(', '    private static func write(')
        self.assertIn('value.completedDay == nil && !value.verifiedRetryableFailure', read)
        self.assertIn('UserDefaults.standard.removeObject(forKey: prefix + key)', read)
        self.assertNotIn('dictionaryRepresentation', read)
        self.assertIn('legacyFailure && value.failedClaimDay == today', read)
        self.assertIn('eligibility: .unknown', read)
        self.assertIn('forKey: .verifiedRetryableFailure) ?? false', text)
        cleanup = checkin.section(text, '    private static func discardUncompleted(', '    @discardableResult\n    static func beginClaim(')
        self.assertIn('guard value.completedDay != requestDay', cleanup)
        self.assertIn('if value.completedDay == nil', cleanup)
        self.assertNotIn('value.completedDay = nil', text)

    def test_generic_refusal_not_a_retryable_or_unsupported_mapping(self):
        text = checkin.CREDIT.read_text()
        parser = checkin.section(text, '    static func traeCheckinRefusal(', '    static func workBuddyClaim(')
        self.assertIn('error.code == 9095', parser)
        self.assertNotIn('9004', parser)
        claim = checkin.section(text, '    static func claim(', '    private static func post(')
        self.assertIn('if billing.verifiedRetryableFailure', claim)
        self.assertIn('SubscriptionCheckinLedger.quietRefusal', claim)
        pure = checkin.section(text, '// BEGIN SUBSCRIPTION_BILLING_PURE', '// END SUBSCRIPTION_BILLING_PURE')
        self.assertNotIn('verifiedRetryableFailure: true', pure)
        self.assertIn('guard record.verifiedRetryableFailure', checkin.COORD.read_text())

    def test_row_exclusion_hides_note_and_button_without_touching_balance(self):
        text = checkin.ACCOUNTS.read_text()
        self.assertIn('if checkin?.checkedIn == true || checkin?.eligibility != .ineligible', text)
        self.assertIn('if checkin?.eligibility != .ineligible, let note', text)
        self.assertIn('checkin?.canClaim == false || checkin == nil', text)
        self.assertIn('SubscriptionCreditAPI.credit(ctx)', text)
        self.assertIn('onReauthenticate', text)
        self.assertIn('refresh(forceRefresh: false)', text)
        self.assertIn('SubscriptionCreditAPI.checkin(ctx, forceRefresh: forceRefresh)', text)

    def test_runtime_fixture_asserts_absent_defaults_not_empty_policy(self):
        fixture = (checkin.ROOT / 'scripts/fixtures/subscription_checkin_runtime_harness.swift').read_text()
        for evidence in ['func expectThreeOnly(', 'absent(fourthKey())', 'savedKeys.count == 3',
                         'for code in [9095, 9004, 701]', 'old refusal not automatically reattempted today',
                         'cancelled mutation leaves no journal', 'late query preserves pending receipt bytes',
                         'concurrent claims dispatch one mutation', 'memory entries expire at day boundary']:
            self.assertIn(evidence, fixture)

    def test_actual_production_swift_runtime(self):
        # The existing runner extracts production ledger/API/automatic loop and
        # substitutes ONLY transport/framework dependencies. No cloned logic.
        checkin.CheckinSwiftContract('test_actual_ledger_and_api_behaviour').test_actual_ledger_and_api_behaviour()


if __name__ == '__main__':
    unittest.main(verbosity=2)
