#!/usr/bin/env python3
"""Source contracts for per-provider display currency (CNY/USD).

Not Swift compilation and not a device test. The runtime path is covered by
the existing cost tests; this guards the storage key and the UI wiring.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"


def read(rel):
    return (IOS / rel).read_text(encoding="utf-8")


class ProviderCurrencyContracts(unittest.TestCase):
    def test_store_is_per_instance(self):
        src = read("Providers/ProviderQuotaService.swift")
        self.assertIn('private let currencyPrefix = "pricing.currency."', src)
        self.assertIn("func displayCurrency(instanceId: String) -> String", src)
        self.assertIn("func setDisplayCurrency(instanceId: String, currency: String)", src)
        self.assertIn('guard code == "CNY" || code == "USD"', src)
        self.assertIn("currencyPrefix + instanceId", src)
        self.assertIn("return TurnCost.currency", src)

    def test_turn_cost_accepts_explicit_currency(self):
        src = read("Shared/AppLocalization.swift")
        self.assertIn("static func formatted(_ usd: Double, rate: Double? = nil, currency: String? = nil)", src)
        self.assertIn("static func compact(_ usd: Double, rate: Double? = nil, currency: String? = nil)", src)
        self.assertIn("(currency ?? Self.currency).uppercased()", src)

    def test_snapshot_carries_currency(self):
        lifecycle = read("Agent/Chat/ChatLifecycleSupport.swift")
        self.assertIn("var currency: String? = nil", lifecycle)
        self.assertIn("TurnCost.compact(lastUSD, rate: exchangeRate, currency: currency)", lifecycle)
        self.assertIn("TurnCost.formatted($0, currency: vm.costSnapshot.currency)", lifecycle)

        vm = read("Agent/Chat/AIChatViewModel.swift")
        self.assertIn("currency: ProviderPricingService.shared.displayCurrency(instanceId: instanceId)", vm)

    def test_rate_sheet_exposes_picker(self):
        src = read("Views/Providers/ProviderInstanceDetailView.swift")
        self.assertIn('Picker("显示币种", selection: currencyBinding)', src)
        self.assertIn('Text("人民币（¥）").tag("CNY")', src)
        self.assertIn('Text("美元（$）").tag("USD")', src)
        self.assertIn("pricing.setDisplayCurrency(instanceId: instanceId, currency: $0)", src)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: per-provider currency; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)