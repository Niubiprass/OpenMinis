#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests for site pricing + independent cost ledger."""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
QUOTA = (ROOT / 'src/ios/Providers/ProviderQuotaService.swift').read_text()
VM = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
LIFE = (ROOT / 'src/ios/Agent/Chat/ChatLifecycleSupport.swift').read_text()
VIEW = (ROOT / 'src/ios/Views/Chat/ChatInputBar.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
MODELS = (ROOT / 'src/ios/Agent/Chat/ChatModels.swift').read_text()


class Pricing(unittest.TestCase):
    def test_reads_the_sites_own_endpoint(self):
        self.assertIn('final class ProviderPricingService', QUOTA)
        self.assertIn('root + "/api/pricing"', QUOTA)
        self.assertIn('group_ratio', QUOTA)
        self.assertIn('completion_ratio', QUOTA)
        self.assertIn('quota_type', QUOTA)

    def test_converts_ratios_to_per_million_usd(self):
        self.assertIn('ratio * groupRatio * 1_000_000.0 / qpu', QUOTA)
        self.assertIn('let output = input * completion', QUOTA)

    def test_only_button_or_provider_page_triggers_network(self):
        self.assertIn('从站点读取定价', DETAIL)
        self.assertIn('pricingService.refresh(for: instance)', DETAIL)
        self.assertIn('.task(id: instance.id)', DETAIL)
        self.assertNotIn('pricingService.refresh(for: instance)\n', VM)

    def test_rate_override_lives_with_provider(self):
        self.assertIn('ratePrefix = "pricing.rateOverride."', QUOTA)
        self.assertIn('func setRateOverride(instanceId:', QUOTA)
        self.assertIn('Text("汇率")', DETAIL)
        self.assertIn('RateOverrideSheet', DETAIL)
        self.assertIn('effectiveRate(instanceId: instanceId)', VM)

    def test_appearance_has_no_amount_section(self):
        appearance = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
        self.assertNotIn('金额显示', appearance)
        self.assertNotIn('汇率（1 美元 =）', appearance)
        self.assertNotIn('币种', appearance)
        self.assertNotIn('备用汇率', LIFE)

    def test_manual_fallback_is_per_model_and_optional(self):
        self.assertIn('func manualPrice(instanceId:', QUOTA)
        self.assertIn('func setManualPrice(instanceId:', QUOTA)
        self.assertIn('manualPrice(instanceId: instanceId, modelId: modelId)', QUOTA)
        self.assertIn('struct ManualPriceSheet', DETAIL)
        self.assertIn('手动补价', DETAIL)


class Ledger(unittest.TestCase):
    def test_independent_file_not_message_schema(self):
        self.assertIn('final class CostLedger', LIFE)
        self.assertIn('cost-ledger.json', LIFE)
        self.assertIn('struct Entry: Codable', LIFE)
        # No message-table field added for costs.
        self.assertNotIn('cost_usd', LIFE)

    def test_records_each_api_call(self):
        self.assertIn('recordCallCost(usage:', VM)
        self.assertIn('CostLedger.shared.record(', VM)
        self.assertIn('turnCostUSD += amount', VM)

    def test_resets_turn_and_loads_session_total(self):
        self.assertIn('var turnCostUSD = 0.0', VM)
        self.assertIn('CostLedger.shared.total(for: ledgerSessionId)', VM)
        self.assertIn('costSnapshot = CostSnapshot(', VM)

    def test_partial_history_is_explicit(self):
        self.assertIn('历史消息没有中间调用记录', LIFE)


class Display(unittest.TestCase):
    def test_cost_is_part_of_context_hint(self):
        self.assertIn('var costText: String?', LIFE + MODELS)
        self.assertIn('costText: costSuffix', MODELS)

    def test_input_has_no_cost_tap_target(self):
        chat = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
        self.assertIn('let placeholderLabel = UILabel()', VIEW)
        self.assertNotIn('onCostTap: { [vm]', chat)
        self.assertNotIn('CostDetailSheet(vm:', chat)

    def test_cost_detail_lives_in_token_usage_sheet(self):
        chat = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
        self.assertIn('Section("Context")', chat)
        self.assertIn('AppLocalized("本会话累计")', chat)
        self.assertIn('CostLedger.shared.total(for: ledgerSessionId)', chat)

    def test_cost_breakdown_has_three_scopes(self):
        chat = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
        self.assertIn('AppLocalized("本次")', chat)
        self.assertIn('AppLocalized("本轮（含工具调用）")', chat)
        self.assertIn('AppLocalized("本会话累计")', chat)
        self.assertIn('最终以站点账单为准', chat)


if __name__ == '__main__':
    unittest.main(verbosity=2)
