#!/usr/bin/env python3
"""Source-contract tests for [T-115-keep-awake]: foreground screen keep-alive.

Covers ForegroundScreenKeepAlive (foreground + setting + task-refcount gating,
background release, clamped refcount), the AIChatView wiring (processing edges
+ appear/disappear pairing for cached VMs) and the settings toggle. Static
checks only; idle-timer behavior needs a device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
KEEPALIVE = (ROOT / 'src/ios/Agent/Background/BackgroundKeepAliveManager.swift').read_text()
CHATVIEW = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
SETTINGS = (ROOT / 'src/ios/Views/Settings/EnhancedBackgroundSettingsView.swift').read_text()


class KeepAwakeSource(unittest.TestCase):
    """[T-115-keep-awake] Source-wiring contracts."""

    def test_keeper_exists_and_gates_on_three_conditions(self):
        self.assertIn('final class ForegroundScreenKeepAlive', KEEPALIVE)
        self.assertIn('appearance.keepScreenAwakeDuringTasks', KEEPALIVE)
        # Screen stays on ONLY when: setting on && foreground && task running.
        self.assertIn('let keepAwake = isEnabled && isForeground && processingCount > 0', KEEPALIVE)
        self.assertIn('UIApplication.shared.isIdleTimerDisabled = keepAwake', KEEPALIVE)

    def test_background_releases_and_refcount_clamped(self):
        # Entering background or toggling off must release the screen even if
        # tasks are still running.
        self.assertIn('forName: UIApplication.didEnterBackgroundNotification', KEEPALIVE)
        self.assertIn('didBecomeActiveNotification', KEEPALIVE)
        self.assertIn('processingCount = max(0, processingCount - 1)', KEEPALIVE)
        self.assertIn('setEnabled(_ on: Bool)', KEEPALIVE)

    def test_no_system_brightness_dimming(self):
        # v1 honesty: we keep the screen awake; we do NOT touch system
        # brightness / UIScreen.main.brightness (scoped to the new class —
        # the manager file can mention brightness elsewhere).
        section = KEEPALIVE[KEEPALIVE.index('final class ForegroundScreenKeepAlive'):]
        self.assertNotIn('brightness', section)
        self.assertIn('"Dim during long tasks" is NOT implemented', KEEPALIVE)

    def test_chat_view_wires_edges_and_reappear(self):
        # Processing edge → lease; cached already-processing VM on (re)appear →
        # explicit +1/-1 pair so the refcount stays balanced.
        self.assertIn('ForegroundScreenKeepAlive.shared.taskStarted()', CHATVIEW)
        self.assertIn('ForegroundScreenKeepAlive.shared.taskEnded()', CHATVIEW)
        self.assertIn('onAppear {\n            if vm.isProcessing { ForegroundScreenKeepAlive.shared.taskStarted() }', CHATVIEW)
        self.assertIn('onDisappear {\n            if vm.isProcessing { ForegroundScreenKeepAlive.shared.taskEnded() }', CHATVIEW)

    def test_settings_toggle_wired(self):
        self.assertIn('"appearance.keepScreenAwakeDuringTasks"', SETTINGS)
        self.assertIn('Toggle("Keep Screen Awake During Tasks", isOn: $keepAwakeDuringTasks)', SETTINGS)
        self.assertIn('ForegroundScreenKeepAlive.shared.setEnabled(value)', SETTINGS)
        self.assertIn('ForegroundScreenKeepAlive.shared.setEnabled(keepAwakeDuringTasks)', SETTINGS)


if __name__ == '__main__':
    unittest.main(verbosity=2)