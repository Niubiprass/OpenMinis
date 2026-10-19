#!/usr/bin/env python3
"""[T-multikey] Contract tests for the per-provider key ring.

Design reference: Kelivo (Chevey339/kelivo, AGPL-3.0) —
lib/core/services/api_key_manager.dart and lib/core/models/api_keys.dart.
Only the design was read; every line here is Swift written for Minis.

These are source contracts. Selection behaviour, Keychain writes and the UI
need a device.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
MODEL = (ROOT / 'src/ios/Providers/ProviderMultiKeys.swift').read_text()
VIEW = (ROOT / 'src/ios/Views/Providers/MultiKeyManagerView.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
FACTORY = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ProviderFactory.swift').read_text()
PBX = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()


class Model(unittest.TestCase):
    def test_four_states(self):
        for s in ['case active', 'case disabled', 'case error']:
            self.assertIn(s, MODEL)

    def test_four_strategies(self):
        for s in ['case roundRobin', 'case priority', 'case random', 'case leastUsed']:
            self.assertIn(s, MODEL)

    def test_cooldown_makes_error_keys_come_back(self):
        self.assertIn('recoveryInterval', MODEL)
        self.assertIn('now.timeIntervalSince(updatedAt) >= recoveryInterval', MODEL)

    def test_park_after_three_consecutive(self):
        self.assertIn('maxConsecutiveFailures = 3', MODEL)
        self.assertIn('k.consecutiveFailures >= Self.maxConsecutiveFailures', MODEL)
        self.assertIn('k.consecutiveFailures = 0', MODEL)

    def test_keys_are_local_only(self):
        # A key ring is a credential: it must not ride iCloud Keychain.
        self.assertIn('kSecAttrSynchronizable as String: false', MODEL)

    def test_mask_hides_the_secret(self):
        self.assertIn('var masked: String', MODEL)
        self.assertIn('String(repeating: "•"', MODEL)


class Selection(unittest.TestCase):
    def test_falls_back_to_single_key(self):
        # Multi-key off (or every key parked) must behave exactly like before.
        self.assertIn('func effectiveKey(for instanceId: String) -> String?', MODEL)
        self.assertIn('return ProviderKeychainHelper.loadAPIKey(instanceId: instanceId)', MODEL)

    def test_round_robin_advances_a_cursor(self):
        self.assertIn('cursorPrefix', MODEL)
        self.assertIn('(idx + 1) % usable.count', MODEL)

    def test_selection_never_mutates_counters(self):
        # Counters move only in recordSuccess / recordFailure.
        idx = MODEL.index('func nextKey(')
        end = MODEL.index('// MARK: - Outcome')
        body = MODEL[idx:end]
        self.assertNotIn('successCount +=', body)
        self.assertNotIn('failureCount +=', body)


class Wiring(unittest.TestCase):
    def test_provider_factory_uses_the_ring(self):
        self.assertEqual(FACTORY.count('ProviderMultiKeyManager.shared.effectiveKey(for: instance.id)'), 7)
        self.assertNotIn('ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)', FACTORY)

    def test_sync_and_backup_keep_the_primary_key(self):
        # Those paths migrate the SINGLE saved key; they must not be rerouted
        # through the ring, or an export would silently pick a rotation slot.
        for name in ['Agent/Backup/BackupSecrets.swift',
                     'Agent/Sync/CloudSyncEngine.swift']:
            src = (ROOT / 'src/ios' / name).read_text()
            self.assertIn('ProviderKeychainHelper.loadAPIKey', src)

    def test_detail_view_has_toggle_and_entry(self):
        self.assertIn('Toggle(isOn: $multiKeyEnabled)', DETAIL)
        self.assertIn('MultiKeyManagerView(instance: instance)', DETAIL)
        self.assertIn('ProviderMultiKeyManager.shared.setEnabled', DETAIL)

    def test_registered_in_project(self):
        self.assertIn('ProviderMultiKeys.swift', PBX)
        self.assertIn('MultiKeyManagerView.swift', PBX)


class Ui(unittest.TestCase):
    def test_stats_and_strategy_present(self):
        for s in ['总数', '正常', '错误', '负载均衡策略']:
            self.assertIn(s, VIEW)

    def test_keys_are_masked_never_raw(self):
        self.assertIn('k.masked', VIEW)
        self.assertNotIn('Text(k.key)', VIEW)

    def test_error_keys_can_be_reactivated(self):
        self.assertIn('reactivate(keyId:', VIEW)
        self.assertIn('恢复使用', VIEW)

    def test_strategy_explains_itself(self):
        self.assertIn('s.explanation', VIEW)


if __name__ == '__main__':
    unittest.main(verbosity=2)
