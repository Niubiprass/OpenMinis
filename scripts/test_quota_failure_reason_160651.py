#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests for per-key balance failure reasons.

The user filled a separate access token for every key but both rows still said
「已用」.  A failed balance query used to be silently converted into a usage
figure, and the refresh toast counted that as success.  These are source
contracts only: the network paths need a device.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
VIEW = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()


class FailureReason(unittest.TestCase):
    def test_each_row_carries_its_own_note(self):
        self.assertIn('var failureNote: String?', QUOTA)
        self.assertIn('row.failureNote = failureNotes[failureKey(instanceId, row.id)]', QUOTA)

    def test_http_200_success_false_is_a_failure(self):
        self.assertIn('if (obj["success"] as? Bool) == false', QUOTA)
        self.assertIn('余额接口拒绝', QUOTA)
        self.assertIn('访问令牌无效或权限不足', QUOTA)

    def test_real_balance_clears_the_note(self):
        self.assertIn('clearFailure(instanceId: instanceId, rowId: rowId)', QUOTA)
        self.assertIn('keyQuota.kind == .balance', QUOTA)
        self.assertIn('billingQuota.kind == .balance', QUOTA)

    def test_usage_only_is_explained_not_called_balance(self):
        self.assertIn('站点只返回了用量，没有返回剩余余额', QUOTA)
        self.assertIn('row.info?.kind != .balance', VIEW)
        self.assertIn('row.failureNote', VIEW)

    def test_unavailable_is_not_rendered_as_empty_money(self):
        self.assertIn('return quotaRefreshing ? "…" : "—"', VIEW)
        self.assertIn('return AppLocalized("查询失败")', VIEW)


class HonestSummary(unittest.TestCase):
    def test_refresh_counts_balance_usage_and_failure_separately(self):
        self.assertIn('let balances = refreshed.filter { $0.info?.kind == .balance }.count', VIEW)
        self.assertIn('let used = refreshed.filter { $0.info?.kind == .used }.count', VIEW)
        self.assertIn('let failed = refreshed.filter { $0.info == nil }.count', VIEW)
        self.assertIn('%lld 把有余额', VIEW)
        self.assertIn('%lld 把只有用量', VIEW)
        self.assertIn('%lld 把查询失败', VIEW)

    def test_usage_is_not_reported_as_updated_balance(self):
        # The old message was based on `info != nil`, which counted 已用 as a
        # successful balance.  It must no longer be the source of the summary.
        self.assertNotIn('let answered = ProviderQuotaService.shared.quotaRows', VIEW)
        self.assertNotIn('已更新 %lld 把，其余站点未返回余额', VIEW)

    def test_single_key_refresh_distinguishes_used_from_balance(self):
        self.assertIn('if info?.kind == .balance', VIEW)
        self.assertIn('else if info?.kind == .used', VIEW)
        self.assertIn('只查到用量', VIEW)


if __name__ == '__main__':
    unittest.main(verbosity=2)