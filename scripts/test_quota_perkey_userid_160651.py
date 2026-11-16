#!/usr/bin/env python3
"""Source contracts for the New-Api-User id entry (instance + per-key).

Not Swift compilation. The backend key shape is the important part: one
provider can hold keys from different site accounts, so a single instance-wide
id is only the fallback.
"""
from pathlib import Path
import unittest
from test_quota_current_key_20261116 import declaration

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
QUOTA = (IOS / "Providers/ProviderQuotaService.swift").read_text(encoding="utf-8")
DETAIL = (IOS / "Views/Providers/ProviderInstanceDetailView.swift").read_text(encoding="utf-8")


class PerKeyUserID(unittest.TestCase):
    def test_storage_has_instance_default_and_per_key_override(self):
        self.assertIn("static func userID(instanceId: String, keyId: String? = nil)", QUOTA)
        self.assertIn('"quota.newAPIUserID.\\(instanceId).\\(keyId)"', QUOTA)
        self.assertIn('"quota.newAPIUserID.\\(instanceId)"', QUOTA)
        self.assertIn("static func setUserID(_ value: String, instanceId: String, keyId: String? = nil)", QUOTA)

    def test_balance_request_uses_the_keys_own_id(self):
        self.assertIn("userID(instanceId: instance.id, keyId: rowId)", QUOTA)
        self.assertIn("resolvedQuotaAccessToken(instanceId: instance.id, keyId: rowId)", QUOTA)

    def test_no_duplicate_instance_fields(self):
        # [T-quota-one-entry] The user rejected "outside and inside" fields.
        # The only entry is the per-key sheet, for one key or many.
        self.assertNotIn('ProviderQuotaService.setUserID(newValue, instanceId: instance.id)', DETAIL)
        self.assertIn('每把 Key 独立保存，只有这一处', DETAIL)
        self.assertIn('点上面的 Key 填访问令牌和用户 ID', DETAIL)

    def test_per_key_sheet_has_id_field_and_saves_it(self):
        sheet = DETAIL.split("private struct KeyQuotaTokenSheet", 1)[1]
        self.assertIn('Text(AppLocalized("用户 ID"))', sheet)
        self.assertIn('ProviderQuotaService.setUserID(userID, instanceId: instanceId, keyId: row.id)', sheet)
        self.assertIn('ProviderQuotaService.userID(instanceId: instanceId, keyId: row.id)', sheet)
        self.assertNotIn(".keyboardType(.numberPad)", sheet)
        self.assertIn("数字、字母或中文", sheet)

    def test_warning_points_at_the_entry(self):
        self.assertIn("点上面的 Key 填访问令牌和用户 ID", DETAIL)


class MainThreadFreeze(unittest.TestCase):
    def test_refresh_never_builds_rows_on_main(self):
        # Device 2026-10-23 02:58:32: main thread waited on a lock while the
        # refresh path read Keychain/ring state. Both refresh and row building
        # must run in detached tasks; only the finished snapshot publishes on
        # the main actor.
        i = DETAIL.index("Button(quotaRefreshing")
        j = DETAIL.index(".disabled(quotaRefreshing)", i)
        block = DETAIL[i:j]
        # The production loader owns bounded detached work now, rather than
        # three ad-hoc Task.detached closures inside this button. Inspect the
        # real methods and retain both query and projection off-main fences.
        self.assertIn("quotaDetail.refresh(for: instance, multi: multiKeyOn)", block)
        self.assertNotIn("ProviderQuotaService.shared.quotaRows(", block)
        self.assertNotIn("Task.detached", block)
        build = declaration(DETAIL, "nonisolated private static func buildSnapshot(")
        query = declaration(DETAIL, "nonisolated private static func query(")
        for worker in (build, query):
            self.assertIn("Task.detached(priority: .userInitiated)", worker)
            self.assertIn("withTaskCancellationHandler", worker)
            self.assertIn("onCancel: { worker.cancel() }", worker)
        self.assertIn("ProviderQuotaService.shared.quotaRows(for: instance)", build)
        self.assertIn("await ProviderQuotaService.shared.refreshAllKeys(for: instance)", query)
        self.assertIn("await ProviderQuotaService.shared.refreshQuota(for: instance)", query)
        section = declaration(DETAIL, "private func quotaSection(")
        self.assertIn("let rows = quotaRowsSnapshot", section)
        self.assertNotIn("ProviderQuotaService.shared.quotaRows(", section)
        projection = declaration(DETAIL, "private func startProjection(")
        self.assertIn("guard projectionTask == nil, pending != nil", projection)
        self.assertIn("if !Task.isCancelled, accepts(request) { snapshot = value }", projection)
        refresh = declaration(DETAIL, "func refresh(for instance:")
        self.assertIn("manualTask == nil", refresh)
        self.assertIn("if accepts(request)", refresh)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: New-Api-User id entry; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)