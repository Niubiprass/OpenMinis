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
        # Request-scoped leases park a key with an absolute deadline; the old
        # updatedAt-only arithmetic would let a key fail on every request as
        # soon as the cooldown had elapsed once.
        self.assertIn('if let until = unavailableUntil, now < until', MODEL)
        self.assertIn('now >= (unavailableUntil ?? updatedAt.addingTimeInterval(recoveryInterval))', MODEL)

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
    def test_single_key_when_multi_key_is_off(self):
        # Multi-key off still uses the instance's main credential.
        self.assertIn('func effectiveKey(for instanceId: String) -> String?', MODEL)
        self.assertIn('lease(for: instanceId)?.key', MODEL)

    def test_every_key_parked_falls_back_to_main_once(self):
        # [T-multikey-last-resort] Two empty ring keys plus one funded main key
        # used to end in "no usable Key" until the cooldown. When the pool is
        # empty, main gets one last attempt; the caller's `excluding` set still
        # stops a same-request retry loop.
        idx = MODEL.index('func lease(for instanceId:')
        end = MODEL.index('func recordSuccess(lease:', idx)
        body = MODEL[idx:end]
        self.assertIn('guard !pool.isEmpty else {', body)
        self.assertIn('guard !main.isEmpty, !excluding.contains("main") else { return nil }', body)
        self.assertIn('return ProviderKeyLease(id: "main", key: main)', body)

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
        self.assertIn('Toggle(isOn: Binding(', DETAIL)
        self.assertIn('MultiKeyManagerView(instance: instance)', DETAIL)
        self.assertIn('ProviderMultiKeyManager.shared.setEnabled(on, for: instance.id)', DETAIL)

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


class ManagementUi(unittest.TestCase):
    def test_existing_key_can_be_edited(self):
        self.assertIn('MultiKeyEditSheet', VIEW)
        self.assertIn('manager.update(keyId: key.id', VIEW)
        self.assertIn('SecureField("留空则保持当前 Key"', VIEW)
        self.assertIn('只有填写新 Key 才会替换', VIEW)

    def test_existing_key_can_be_deleted(self):
        self.assertIn('manager.remove(keyId:', VIEW)
        self.assertIn('Button("删除", role: .destructive)', VIEW)
        self.assertIn('删除后不再使用', VIEW)

    def test_row_opens_editor_and_has_explicit_trailing_delete(self):
        self.assertIn('.onTapGesture { editingKey = k }', VIEW)
        self.assertIn('.swipeActions(edge: .trailing', VIEW)
        self.assertIn('Label("删除", systemImage: "trash")', VIEW)
        self.assertIn('Image(systemName: "pencil")', VIEW)
        self.assertIn('Image(systemName: "trash")', VIEW)
        # A leading-only swipeActions implementation was the reason the row
        # looked untouchable on device; the trailing action is the regression
        # guard.
        self.assertIn('Label("恢复使用", systemImage: "arrow.clockwise")', VIEW)

    def test_duplicate_keys_are_rejected(self):
        self.assertIn('existingKeys.contains(trimmedKey)', VIEW)
        self.assertIn('keys.contains(where: { $0.key == trimmed })', VIEW)

    def test_key_never_rendered_in_clear(self):
        self.assertNotIn('Text(k.key)', VIEW)
        self.assertNotIn('Text(key.key)', VIEW)


class EmptyRingAndLockIO(unittest.TestCase):
    def test_empty_ring_is_single_key_mode(self):
        # [T-multikey-empty-ring] A latched-on switch with zero ring keys must
        # not wrap requests; otherwise the only saved key gets parked and every
        # message reports "no usable Key".
        idx = MODEL.index('func lease(for instanceId:')
        end = MODEL.index('func recordSuccess(lease:', idx)
        body = MODEL[idx:end]
        self.assertIn('let ring = unlockedKeys(instanceId)', body)
        self.assertIn('guard storedEnabled(for: instanceId), !ring.isEmpty else {', body)
        self.assertIn('func isActive(for instanceId: String) -> Bool', MODEL)
        self.assertIn('!keys(for: instanceId).isEmpty', MODEL)
        self.assertIn('isActive(for: instance.id)', FACTORY)

    def test_record_persists_outside_the_ring_lock(self):
        # [T-multikey-lock-io] 05:52 device stackshot: main thread in
        # keys(for:) waiting on `lock`, holder in recordSuccess ->
        # saveMainState -> UserDefaults (cfprefsd). No persistence under `lock`.
        for name in ['func recordSuccess(lease:', 'func recordFailure(lease:']:
            i = MODEL.index(name)
            j = MODEL.index('// MARK: - Selection', i)
            body = MODEL[i:j]
            unlock = body.index('lock.unlock()')
            for persist in ['saveMainState(', 'unlockedSave(']:
                k = body.index(persist)
                self.assertGreater(k, unlock, f'{persist} still runs while holding lock')
            self.assertIn('recordLock.lock()', body)

    def test_detail_body_uses_cached_rows_not_keychain(self):
        # The freeze path: quotaRows -> keys(for:) read from SwiftUI body.
        detail = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
        i = detail.index('private func quotaSection(_ instance: ProviderInstance) -> some View {')
        j = detail.index('if quotaRefreshing {', i)
        body = detail[i:j]
        self.assertIn('let rows = quotaRowsSnapshot', body)
        self.assertNotIn('quotaRows(for: instance)', body)
        self.assertNotIn('ProviderMultiKeyManager.shared.keys', body)
        self.assertIn('Task.detached', detail)


class FailoverWiring(unittest.TestCase):
    def test_chat_provider_is_wrapped_when_multi_key_is_on(self):
        self.assertIn('MultiKeyAgentProvider(instanceId: instance.id', FACTORY)
        self.assertIn('ProviderMultiKeyManager.shared.isActive(for: instance.id)', FACTORY)

    def test_builder_receives_the_lease_key(self):
        self.assertIn('apiKeyOverride: key', FACTORY)
        self.assertIn('apiKeyOverride ?? ProviderKeychainHelper.loadAPIKey', MODEL + (ROOT / 'src/ios/Providers/LLMProviderFactory.swift').read_text())

    def test_failover_is_request_scoped_and_bounded(self):
        WRAP = (ROOT / 'src/ios/Providers/AgentProvider.swift').read_text()
        self.assertIn('manager.keys(for: instanceId).count + 1', WRAP)
        self.assertIn('manager.lease(for: instanceId, excluding: attempted)', WRAP)
        self.assertIn('attemptedSecrets.insert(lease.key).inserted', WRAP)

    def test_partial_response_is_not_replayed_on_another_key(self):
        WRAP = (ROOT / 'src/ios/Providers/AgentProvider.swift').read_text()
        self.assertIn('if exposed {', WRAP)
        self.assertIn('excludeOnResume(lease.id)', WRAP)
        self.assertIn('continuation.finish(throwing: error)', WRAP)


if __name__ == '__main__':
    unittest.main(verbosity=2)
