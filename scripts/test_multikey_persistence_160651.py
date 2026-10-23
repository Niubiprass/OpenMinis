#!/usr/bin/env python3
"""Source contracts for persisting multi-key preferences and priority order."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODEL = (ROOT / "src/ios/Providers/ProviderMultiKeys.swift").read_text(encoding="utf-8")
VIEW = (ROOT / "src/ios/Views/Providers/MultiKeyManagerView.swift").read_text(encoding="utf-8")


class Persistence(unittest.TestCase):
    def test_switch_and_strategy_force_a_write(self):
        for name in ("func setEnabled(", "func setStrategy("):
            i = MODEL.index(name)
            j = MODEL.index("    }", i)
            body = MODEL[i:j]
            self.assertIn("synchronize()", body, name)

    def test_strategy_saves_on_selection_not_on_disappear(self):
        self.assertIn("showStrategyPicker = true", VIEW)
        self.assertIn("manager.setStrategy(item, for: instance.id)", VIEW)
        self.assertIn(".confirmationDialog(\"负载均衡策略\"", VIEW)
        self.assertNotIn(".onDisappear {\n                            manager.setStrategy", VIEW)


class PriorityOrder(unittest.TestCase):
    def test_priority_uses_main_then_ring_order(self):
        switch = MODEL.index("switch strategy(for: instanceId) {")
        i = MODEL.index("case .priority:", switch)
        j = MODEL.index("case .random:", i)
        body = MODEL[i:j]
        self.assertIn("return pool[0].lease", body)
        # pool is built with main first, then ring keys in stored order.
        self.assertIn("if !main.isEmpty {", MODEL)
        self.assertIn("for entry in ring {", MODEL)

    def test_copy_explains_no_same_request_retry(self):
        self.assertIn("固定用主 Key；主 Key 报错或被停用后", MODEL)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: multi-key persistence; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
