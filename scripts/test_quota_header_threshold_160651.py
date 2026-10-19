#!/usr/bin/env python3
"""Source-contract tests for [T-quota-header-balance] and [T-quota-threshold].

Two rules the user asked for explicitly:
1. The balance is shown ONCE per provider, on the section header — not on
   every model row, and never on top of the collapse button.
2. The "low balance" cut-off is user-configurable (default $3) instead of
   hardcoded, and it only applies to a REAL balance — a usage-only figure has
   no scale, so flagging it would be a guess.

Static checks only; layout and colour need a device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
PICKER = (ROOT / 'src/ios/Views/Providers/UnifiedModelPicker.swift').read_text()
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()


class HeaderBalance(unittest.TestCase):
    def test_balance_lives_in_section_header(self):
        header = PICKER[PICKER.index('} header: {'):PICKER.index('// MARK: - Entry Row')]
        self.assertIn('cachedQuota(instanceId: item.instance.id)', header)
        self.assertIn('q.displayText', header)

    def test_not_repeated_per_model_row(self):
        # entryRow is the ONLY model-row renderer for instance sections.
        body = PICKER[PICKER.index('private func entryRow('):PICKER.index('// MARK: - Empty State')]
        self.assertNotIn('displayText', body)

    def test_collapse_button_kept(self):
        header = PICKER[PICKER.index('} header: {'):PICKER.index('// MARK: - Entry Row')]
        self.assertIn('collapsedInstanceIds.insert(item.instance.id)', header)
        self.assertIn('chevron.down" : "chevron.up', header)
        self.assertIn('frame(width: 28, height: 28)', header)

    def test_colour_rules(self):
        self.assertIn('private func quotaTint(_ q: ProviderQuotaService.QuotaInfo) -> Color', PICKER)
        # Grey for usage-only, green/yellow only for a real balance.
        self.assertIn('return .secondary', PICKER)
        self.assertIn('return q.highlighted ? .yellow : .green', PICKER)


class ConfigurableThreshold(unittest.TestCase):
    def test_key_and_default(self):
        self.assertIn('static let lowThresholdDefaultsKey = "quota.lowThresholdUSD"', QUOTA)
        self.assertIn('return 3.0', QUOTA)

    def test_threshold_used_everywhere(self):
        self.assertIn('highlighted: balance < lowThresholdUSD', QUOTA)
        self.assertIn('remaining < Self.lowThresholdUSD', QUOTA)

    def test_stepper_in_settings(self):
        self.assertIn('Stepper(value: $quotaLowThreshold, in: 0...1000, step: 1)', DETAIL)
        self.assertIn('@AppStorage(ProviderQuotaService.lowThresholdDefaultsKey)', DETAIL)

    def test_used_only_never_flagged(self):
        # .used is produced with highlighted: false and the tint stays grey.
        self.assertIn('kind: .used', QUOTA)
        self.assertIn('if q.kind == .balance {', PICKER)


if __name__ == '__main__':
    unittest.main(verbosity=2)
