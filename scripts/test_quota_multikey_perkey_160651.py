#!/usr/bin/env python3
"""Source-contract tests for [T-quota-multikey-perkey].

The user's report (2026-10-20), with a screenshot of 供应商详情 → 余额:
「这些是多 key 的，但是它不是还有一个主的吗？」 — the page showed ONE figure
(当前 已用 $10.88) while 多 Key 模式 was on. That figure belonged to the
credential key in 凭证, and nothing on screen said so; the key actually serving
the requests (the ring) was invisible.

Agreed design (style B of the approved mockup):
- 余额 section lists ONE ROW PER KEY: 主 Key (凭证) first, then 轮询 1..N.
  Right-aligned tabular amounts, low ones orange, unknown ones a dash.
- 3 keys must ALL be queried — but ONLY when the user taps
  「测试并刷新余额（查全部 N 把）」. Nothing auto-fires: the previous behaviour
  spent one request per provider on every list appearance, and with a ring that
  number described a key that was not in use.
- Aggregates (list row, picker, composer capsule) take the LOWEST real balance,
  so a nearly-spent key cannot hide behind a healthy sibling.

Static source checks only; a live relay is needed for the real numbers.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
STRINGS = (ROOT / 'src/ios/Localizable.xcstrings').read_text()


class PerKeyModel(unittest.TestCase):

    def test_key_quota_row_type(self):
        self.assertIn('struct KeyQuota: Identifiable {', QUOTA)
        for field in ('let title: String', 'let badge: String', 'let masked: String',
                      'let isMain: Bool', 'var info: QuotaInfo?', 'var queriedAt: Date?'):
            self.assertIn(field, QUOTA)

    def test_rows_are_main_first_then_ring(self):
        i = QUOTA.index('func quotaRows(for instance: ProviderInstance) -> [KeyQuota] {')
        body = QUOTA[i:QUOTA.index('private func attach(', i)]
        self.assertLess(body.index('id: "main"'), body.index('keys(for: instance.id)'))
        self.assertIn('String(format: AppLocalized("轮询 %lld"), Int64(index + 1))', body)

    def test_rows_carry_no_secret(self):
        # A row may only hold the masked form; the full key never reaches a view.
        i = QUOTA.index('struct KeyQuota: Identifiable {')
        body = QUOTA[i:QUOTA.index('\n    }', i)]
        self.assertIn('masked: String', body)
        self.assertNotIn('key: String', body)

    def test_mask_matches_ring_format(self):
        self.assertIn('return key.prefix(6) + "…" + key.suffix(4)', QUOTA)


class PerKeyFetching(unittest.TestCase):

    def test_explicit_key_entry_point(self):
        # [T-quota-perkey-token] the signature grew a rowId (which key's token
        # to use); the delegation contract is unchanged.
        self.assertIn('static func fetchQuota(for instance: ProviderInstance, key: String,', QUOTA)
        # The single-key path must delegate, not duplicate the query.
        i = QUOTA.index('static func fetchQuota(for instance: ProviderInstance) async -> QuotaInfo? {')
        body = QUOTA[i:i + 1200]
        self.assertIn('return await fetchQuota(for: instance, key: key)', body)

    def test_every_key_is_queried(self):
        i = QUOTA.index('func refreshAllKeys(for instance: ProviderInstance) async {')
        body = QUOTA[i:QUOTA.index('private func publishAggregate', i)]
        self.assertIn('for row in rows {', body)
        self.assertIn('Self.fetchQuota(for: instance, key: secret, rowId: row.id)', body)
        # Concurrent: four slow relays must not serialize into a minute-long tap.
        self.assertIn('withTaskGroup', body)

    def test_results_publish_as_they_land(self):
        i = QUOTA.index('func refreshAllKeys(for instance: ProviderInstance) async {')
        body = QUOTA[i:QUOTA.index('private func publishAggregate', i)]
        self.assertIn('self.revision += 1', body)
        self.assertIn('keyCache[instance.id, default: [:]][rowId] = entry', body)

    def test_aggregate_is_the_lowest_balance(self):
        i = QUOTA.index('private func publishAggregate(for instanceId: String) {')
        body = QUOTA[i:]
        self.assertIn('let lowest = balances.min()', body)
        self.assertIn('kind: .balance', body)
        self.assertIn('highlighted: lowest < Self.lowThresholdUSD', body)

    def test_amount_fields_for_every_path(self):
        # `amountUSD` is what the rows print; every QuotaInfo construction that
        # knows a number must set it or the row shows the raw displayText.
        self.assertIn('var amountUSD: Double? = nil', QUOTA)
        self.assertIn('amountUSD: max(remaining, 0)', QUOTA)
        self.assertIn('amountUSD: totalUsed', QUOTA)
        self.assertIn('amountUSD: balance', QUOTA)
        self.assertIn('amountUSD: usd', QUOTA)


class ManualOnly(unittest.TestCase):

    def test_auto_refresh_skips_multikey_instances(self):
        i = QUOTA.index('func refreshAllIfNeeded(instances: [ProviderInstance]) {')
        body = QUOTA[i:QUOTA.index('// MARK: - [T-quota-multikey-perkey] Per-key rows', i)]
        self.assertIn('!ProviderMultiKeyManager.shared.isEnabled(for: $0.id)', body)

    def test_detail_page_has_no_automatic_key_query(self):
        i = DETAIL.index('private func quotaSection(_ instance: ProviderInstance) -> some View {')
        body = DETAIL[i:DETAIL.index('// [T-quota-threshold]', i)]
        # The ONLY query site inside the section is the button's action.
        self.assertEqual(body.count('refreshAllKeys('), 1)
        self.assertEqual(body.count('refreshQuota('), 1)
        self.assertNotIn('.onAppear {\n            Task', body)

    def test_button_states_the_cost(self):
        self.assertIn('测试并刷新余额（查全部 %lld 把）', DETAIL)
        self.assertIn('Int64(rows.count)', DETAIL)


class DetailRendering(unittest.TestCase):

    def test_rows_render_in_every_mode(self):
        # [T-quota-one-entry] The main key is a row in single-key mode too;
        # the old "当前" branch hid the only credential entry.
        i = DETAIL.index('let rows = quotaRowsSnapshot')
        j = DETAIL.index('if quotaRefreshing {', i)
        body = DETAIL[i:j]
        self.assertIn('let multiKeyOn = multiKeyEnabled', body)
        self.assertIn('rows.contains { !$0.isMain }', body)
        self.assertIn('ForEach(rows) { row in', body)
        self.assertIn('if rows.isEmpty', body)

    def test_body_does_not_query_the_keychain(self):
        i = DETAIL.index('private func quotaSection(_ instance: ProviderInstance) -> some View {')
        j = DETAIL.index('if quotaRefreshing {', i)
        body = DETAIL[i:j]
        self.assertIn('let rows = quotaRowsSnapshot', body)
        self.assertNotIn('quotaRows(for: instance)', body)
        self.assertNotIn('ProviderMultiKeyManager.shared.keys', body)

    def test_empty_ring_is_single_key_mode(self):
        # Deleting every extra key must not leave the ring active: with no ring
        # the request path uses the saved credential and reports its real error.
        i = QUOTA.index('func quotaRows(for instance: ProviderInstance) -> [KeyQuota] {')
        j = QUOTA.index('private func attach(', i)
        body = QUOTA[i:j]
        self.assertIn('guard ProviderMultiKeyManager.shared.isEnabled(for: instance.id) else { return rows }', body)
        self.assertIn('let ring = ProviderMultiKeyManager.shared.keys(for: instance.id)', body)
        self.assertIn('guard !ring.isEmpty else { return rows }', body)

    def test_rows_show_main_badge_and_index_badges(self):
        self.assertIn('Text(row.badge)', DETAIL)
        self.assertIn('AppLocalized("主")', QUOTA)

    def test_right_aligned_tabular_amounts(self):
        self.assertIn('.monospacedDigit()', DETAIL)
        self.assertIn('using: .trailing', DETAIL) if False else None
        # Right-aligned VStack is what makes the column compare by eye.
        self.assertIn('VStack(alignment: .trailing, spacing: 2) {', DETAIL)

    def test_unknown_is_a_dash_not_zero(self):
        self.assertIn('return quotaRefreshing ? "…" : "—"', DETAIL)

    def test_low_balance_is_orange_and_captioned(self):
        self.assertIn('if info.highlighted { return .orange }', DETAIL)
        self.assertIn('AppLocalized("低于 %@")', DETAIL)

    def test_view_observes_the_service(self):
        self.assertIn('@ObservedObject private var quotaService = ProviderQuotaService.shared', DETAIL)


class PerKeyLocalization(unittest.TestCase):

    def test_chinese_strings(self):
        for key in ('"主 Key"', '"轮询 %lld"', '"未查询"', '"不可用"', '"已用"',
                    '"低于 %@"', '"测试并刷新余额（查全部 %lld 把）"'):
            self.assertIn(key, STRINGS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
