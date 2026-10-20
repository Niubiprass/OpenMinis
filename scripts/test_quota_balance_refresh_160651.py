#!/usr/bin/env python3
"""Source-contract tests for real relay balance + in-picker refresh.

Covers:
- [T-quota-newapi-balance]: New API sites expose the real remaining balance at
  `GET {root}/api/user/self`, authenticated by a saved dashboard access token
  or by the in-app browser's login cookies. The existing OpenAI billing pair
  returns a placeholder limit on relays (1e8) and must never win over the real
  balance. Access tokens live in the Keychain, local-only (not iCloud-synced).
- [T-picker-refresh-all]: the session model picker refreshes every ENABLED
  provider from its own base URL + key, then reports how many models are no
  longer listed. Nothing is merged across sites.

Static checks only; live endpoints and WKWebView need a device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')

QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
STORE = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
INSTANCES = (ROOT / 'src/ios/Views/Providers/ProviderInstancesView.swift').read_text()
PICKER = (ROOT / 'src/ios/Views/Providers/UnifiedModelPicker.swift').read_text()


class NewAPIBalance(unittest.TestCase):
    """[T-quota-newapi-balance] Real balance from New API relays."""

    def test_api_root_strips_v1(self):
        self.assertIn('static func apiRoot(_ baseURL: String) -> String', QUOTA)
        self.assertIn('if root.hasSuffix("/v1") { root = String(root.dropLast(3)) }', QUOTA)

    def test_user_self_endpoint_used(self):
        self.assertIn('root + "/api/user/self"', QUOTA)
        self.assertIn('req.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")', QUOTA)

    def test_quota_per_unit_from_status(self):
        self.assertIn('root + "/api/status"', QUOTA)
        self.assertIn('quota_per_unit', QUOTA)
        self.assertIn('defaultQuotaPerUnit: Double = 500_000', QUOTA)

    def test_cookie_fallback_uses_own_webview_store(self):
        # The in-app browser's store — never Safari's (iOS sandbox forbids it).
        self.assertIn('WKWebsiteDataStore.default().httpCookieStore.getAllCookies', QUOTA)
        self.assertIn('DispatchQueue.main.async', QUOTA)

    def test_real_balance_wins_over_placeholder_billing(self):
        # Order matters INSIDE fetchOpenAIQuota: New API first, then the
        # OpenAI billing pair (which relays fill with a 1e8 placeholder).
        body = QUOTA[QUOTA.index('private static func fetchOpenAIQuota'):]
        newapi = body.index('if let balance = await fetchNewAPIBalance')
        billing = body.index('dashboard/billing/subscription')
        self.assertLess(newapi, billing)

    def test_balance_kind_marks_real_balance(self):
        self.assertIn('enum Kind {', QUOTA)
        self.assertIn('case balance', QUOTA)
        self.assertIn('kind: .balance', QUOTA)


class QuotaTokenKeychain(unittest.TestCase):
    """Access tokens are Keychain-local, never synced."""

    def test_read_write_delete_exist(self):
        for fn in ('saveQuotaAccessToken', 'loadQuotaAccessToken', 'deleteQuotaAccessToken'):
            self.assertIn('static func {}('.format(fn), STORE, fn)

    def test_not_icloud_synced(self):
        start = STORE.index('static func saveQuotaAccessToken')
        end = STORE.index('// MARK: - OAuth Token')
        block = STORE[start:end]
        self.assertNotIn('kSecAttrSynchronizable', block)


class QuotaUI(unittest.TestCase):
    """Detail view wires both credential paths."""

    def test_balance_section_present(self):
        self.assertIn('quotaSection(instance)', DETAIL)
        self.assertIn('Text("余额")', DETAIL)

    def test_single_token_field_only(self):
        # [T-quota-single-field] Exactly ONE input in this section — the access
        # token. No user id, no panel host, no in-app login: anything else the
        # site demands is not asked for; the query falls back to 已用.
        self.assertIn('Text("访问令牌")', DETAIL)
        self.assertNotIn('Button("在 App 内登录该站点")', DETAIL)
        self.assertNotIn('AppLocalized("用户 ID")', DETAIL)
        self.assertNotIn('AppLocalized("面板地址")', DETAIL)
        self.assertIn('/api/usage/token/', QUOTA)

    def test_login_sheet_is_own_webview(self):
        self.assertIn('struct ProviderQuotaLoginView: View', INSTANCES)
        self.assertIn('config.websiteDataStore = .default()', INSTANCES)
        self.assertNotIn('SFSafariViewController', INSTANCES)

    def test_list_badge_colors_by_kind(self):
        self.assertIn('let isBalance = quota.kind == .balance', INSTANCES)
        self.assertIn('isBalance ? Color.green : Color.secondary', INSTANCES)


class PickerRefreshAll(unittest.TestCase):
    """[T-picker-refresh-all] Refresh every enabled provider in place."""

    def test_refresh_button_in_toolbar(self):
        self.assertIn('Image(systemName: "arrow.clockwise")', PICKER)
        self.assertIn('refreshAllModels()', PICKER)
        self.assertIn('.accessibilityLabel(Text("刷新模型列表"))', PICKER)

    def test_refreshes_each_enabled_instance_independently(self):
        self.assertIn('let targets = store.instances.filter { $0.isEnabled }', PICKER)
        self.assertIn('for target in targets {\n                await store.refreshModels(for: target)', PICKER)

    def test_reports_unlisted_count(self):
        self.assertIn('store.modelEntries.filter { $0.isUnavailableFromProvider }.count', PICKER)
        self.assertIn('个模型不再提供', PICKER)

    def test_does_not_merge_sites(self):
        # No global merge: refresh calls go per instance, and sections are
        # rebuilt from the store's per-instance entries afterwards.
        self.assertEqual(PICKER.count('await store.refreshModels(for: target)'), 1)
        self.assertIn('loadSections()', PICKER)


if __name__ == '__main__':
    unittest.main(verbosity=2)
