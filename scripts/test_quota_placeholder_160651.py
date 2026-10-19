#!/usr/bin/env python3
"""Source-contract tests for relay quota placeholder handling.

[T-quota-relay-placeholder] Relays implement OpenAI's billing endpoints but
fake `hard_limit_usd` with a huge value (typically 100000000) meaning
"unlimited". Subtracting real usage from it produced "剩 $99999977.88" on
every relay — a meaningless number. Above the ceiling the service must report
month-to-date usage instead, and must never mark it low (unknowable).

Static checks only; the live billing endpoints need a device + real keys.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()


class RelayQuotaPlaceholder(unittest.TestCase):
    """[T-quota-relay-placeholder] Placeholder caps degrade to usage."""

    def test_placeholder_ceiling_defined(self):
        self.assertIn('static let relayPlaceholderLimitUSD: Double = 1_000_000', QUOTA)

    def test_placeholder_cap_is_not_used_for_remaining(self):
        # The remaining-credit branch must be guarded by the ceiling, so a
        # relay's 1e8 cap can never produce "剩 $99999977.88" again.
        self.assertIn('if let hardLimit, hardLimit > 0, hardLimit < Self.relayPlaceholderLimitUSD {', QUOTA)
        self.assertIn('String(format: "剩 $%.2f", max(remaining, 0))', QUOTA)

    def test_placeholder_falls_back_to_usage(self):
        # Above the ceiling: report real month-to-date usage, never highlighted
        # (a fabricated "low balance" would be worse than no badge).
        self.assertIn('String(format: "已用 $%.2f", totalUsed)', QUOTA)
        start = QUOTA.index('String(format: "已用 $%.2f", totalUsed)')
        self.assertIn('kind: .used', QUOTA[start:start + 200])

    def test_real_caps_still_show_remaining(self):
        # A genuine cap (tens/hundreds/thousands) keeps the remaining display
        # and its low-balance highlighting.
        self.assertIn('let low = remaining < Self.lowThresholdUSD || remaining < limit * 0.15', QUOTA)

    def test_no_negative_remaining_rendered(self):
        # max(remaining, 0) keeps an over-quota account from showing "-$1.20".
        self.assertIn('max(remaining, 0)', QUOTA)


if __name__ == '__main__':
    unittest.main(verbosity=2)
