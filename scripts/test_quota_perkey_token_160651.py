#!/usr/bin/env python3
"""Source-contract tests for [T-quota-perkey-token].

Reported 2026-10-20: 「有两个 key，我要创两个访问令牌，怎么加入呢？它这里只能写一个」
then 「这两个 K 都是我的两个账号啊，一个是我用 GitHub 的，一个是我用 L 站的」.

Why one field was wrong: the New API balance endpoint `/api/user/self` answers
for an ACCOUNT, not for an `sk-…` key. With two accounts under one provider, the
instance-wide token could only ever describe one of them — the second key's row
was showing the FIRST account's number, which looks authoritative and is wrong.

Contract:
- Tokens are stored per (instance, keyId) in the Keychain, and fall back to the
  instance-wide token so existing single-account setups keep working untouched.
- The query uses the token of the key it is asking about.
- Each balance row opens an editor for THAT key's token.
- Nothing is synced; no token is ever logged or rendered in full.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
STORE = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()


class KeychainScope(unittest.TestCase):

    def test_service_is_scoped_by_key(self):
        self.assertIn('com.openminis.app.provider.\\(instanceId).quotakey.\\(keyId)', STORE)

    def test_save_and_load_take_a_key_id(self):
        self.assertIn('static func saveQuotaAccessToken(_ token: String, instanceId: String, keyId: String)', STORE)
        self.assertIn('static func loadQuotaAccessToken(instanceId: String, keyId: String) -> String?', STORE)

    def test_falls_back_to_the_instance_wide_token(self):
        i = STORE.index('static func resolvedQuotaAccessToken(instanceId: String, keyId: String) -> String?')
        body = STORE[i:i + 700]
        self.assertIn('loadQuotaAccessToken(instanceId: instanceId, keyId: keyId)', body)
        self.assertIn('return loadQuotaAccessToken(instanceId: instanceId)', body)

    def test_clearing_saves_empty(self):
        # An empty string must DELETE the item, not store one, or a cleared
        # token would keep being used.
        i = STORE.index('static func saveQuotaAccessToken(_ token: String, instanceId: String, keyId: String)')
        body = STORE[i:i + 900]
        self.assertIn('SecItemDelete', body)
        self.assertIn('guard !token.isEmpty', body)


class QueryUsesTheRightToken(unittest.TestCase):

    def test_quota_fetch_takes_the_row_id(self):
        self.assertIn('rowId: String = "main") async -> QuotaInfo?', QUOTA)
        self.assertIn('rowId: rowId', QUOTA)

    def test_balance_uses_the_per_key_resolver(self):
        self.assertIn('resolvedQuotaAccessToken(instanceId: instanceId, keyId: rowId)', QUOTA)

    def test_refresh_all_passes_each_rows_id(self):
        self.assertIn('Self.fetchQuota(for: instance, key: secret, rowId: row.id)', QUOTA)


class RowEditor(unittest.TestCase):

    def test_rows_are_tappable(self):
        self.assertIn('quotaTokenTarget = row', DETAIL)
        self.assertIn('.sheet(item: $quotaTokenTarget)', DETAIL)

    def test_editor_saves_and_clears_by_key(self):
        i = DETAIL.index('private struct KeyQuotaTokenSheet: View')
        body = DETAIL[i:]
        self.assertIn('saveQuotaAccessToken(trimmed, instanceId: instanceId, keyId: row.id)', body)
        self.assertIn('saveQuotaAccessToken("", instanceId: instanceId, keyId: row.id)', body)

    def test_editor_is_not_an_account_password_field(self):
        # Same reasoning as issue #364: a bare SecureField invites AutoFill to
        # offer saving a long-lived API credential as a site password.
        i = DETAIL.index('private struct KeyQuotaTokenSheet: View')
        body = DETAIL[i:]
        self.assertIn('.textContentType(.oneTimeCode)', body)

    def test_editor_explains_the_account_rule(self):
        self.assertIn('同一个账号下的多把 Key 共用一个令牌；不同账号各填各的。不填则用上面那个通用令牌。',
                      (ROOT / 'src/ios/Localizable.xcstrings').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
