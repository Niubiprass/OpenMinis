#!/usr/bin/env python3
"""Source-contract tests for [T-minisight-agent-signal].

The MiniSight tweak (debs/MiniSight in Niubiprass/theos-ci) draws a "Minis 操作中"
capsule above everything, driven only by two Darwin notifications. Nothing in
the app posted them, so the capsule never appeared.

Agreed wiring (2026-10-20): the APP posts them, from the single funnel every
tool call passes through. Rules the user cares about, in their words:
「会不会对这个 APP 有什么影响啊？我总是怕它卡」— so the contract is about
cost and blast radius:

- One pair of posts per BURST of tool work (0→1 / 1→0), never per call: tools
  run concurrently and back-to-back, and a per-call post would strobe.
- A minimum visible floor, so an instant tool does not flash.
- Every exit path closes the burst (`defer`), including throw / timeout /
  cancel — a capsule stuck on screen forever would be worse than none.
- ADDITIVE ONLY: no existing logic changes; deleting the two call lines returns
  the app to its previous behaviour.
- The notification names must match the tweak byte for byte. A typo disables
  the feature silently, which is exactly the class of bug a source test catches.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
TOOLS = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift').read_text()


def signal_body():
    i = TOOLS.index('final class MiniSightSignal {')
    return TOOLS[i:]


class SignalContract(unittest.TestCase):

    def test_names_match_the_tweak(self):
        # debs/MiniSight/Tweak.xm / README: com.openminis.agent.started|stopped
        self.assertIn('static let startedNotification = "com.openminis.agent.started"', TOOLS)
        self.assertIn('static let stoppedNotification = "com.openminis.agent.stopped"', TOOLS)

    def test_posts_on_darwin_centre(self):
        body = signal_body()
        self.assertIn('CFNotificationCenterGetDarwinNotifyCenter()', body)
        self.assertIn('CFNotificationCenterPostNotification(', body)

    def test_one_pair_per_burst_not_per_tool(self):
        body = signal_body()
        # Show only on 0→1 …
        self.assertIn('if depth == 1 {', body)
        # … hide only on 1→0.
        self.assertIn('if depth == 0, previousDepth > 0 {', body)

    def test_minimum_visible_floor(self):
        self.assertIn('private static let minimumVisible: TimeInterval = 0.6', TOOLS)
        self.assertIn('delay = Self.minimumVisible - elapsed', signal_body())

    def test_delayed_hide_is_cancellable(self):
        body = signal_body()
        self.assertIn('pendingHide?.cancel()', body)
        self.assertIn('DispatchWorkItem { [weak self] in self?.hideIfIdle() }', body)

    def test_no_preference_or_timer_state(self):
        # The signal intentionally writes one short status.txt line so the
        # SpringBoard pet can show the current device action. What it must not
        # do is persist preferences, create URL sessions, or own a timer loop.
        body = signal_body()
        for forbidden in ('UserDefaults', 'URLSession', 'Timer.scheduledTimer'):
            self.assertNotIn(forbidden, body)
        self.assertIn('FileManager.default', body)


class SignalScope(unittest.TestCase):

    def test_only_real_mcp_calls_light_the_capsule(self):
        body = signal_body()
        # browser_use always; shell_execute only when it actually calls MCP.
        self.assertIn('if tool == "browser_use" { return true }', body)
        self.assertIn('return args.contains("minis-mcp-cli") || args.contains("bin/mcp call")', body)
        self.assertIn('static func shouldSignal(tool: String, args: String) -> Bool', body)

    def test_watchdog_ceiling(self):
        body = signal_body()
        self.assertIn('private static let maxVisible: TimeInterval = 120', body)
        self.assertIn('private func forceHide()', body)
        self.assertIn('Self.maxVisible', body)


class FunnelWiring(unittest.TestCase):

    def test_begin_and_defer_end_at_the_funnel(self):
        i = TOOLS.index('func executeSingleToolUse(')
        body = TOOLS[i:i + 6000]
        self.assertIn('MiniSightSignal.shared.begin(tool: tu.name, args: sightArgs)', body)
        self.assertIn('defer { if sightSignals { MiniSightSignal.shared.end() } }', body)
        # begin must precede the defer that closes it
        self.assertLess(body.index('begin(tool: tu.name'), body.index('MiniSightSignal.shared.end()'))

    def test_wiring_is_additive(self):
        # The two lines must sit at the top of the function, before the CPU
        # probe — an addition, not a rewrite of the executor.
        i = TOOLS.index('func executeSingleToolUse(')
        head = TOOLS[i:i + 6000]
        self.assertLess(head.index('MiniSightSignal.shared.begin(tool: tu.name'),
                        head.index('PerfProbe.toolBefore'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
