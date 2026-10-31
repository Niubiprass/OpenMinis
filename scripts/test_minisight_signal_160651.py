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

ROOT = Path(__file__).resolve().parent.parent
TOOLS = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift').read_text()


def signal_body():
    i = TOOLS.index('final class MiniSightSignal: @unchecked Sendable {')
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
        self.assertIn('if show {', body)
        self.assertIn('publishLocked(edge: show ? Self.startedNotification : nil)', body)
        self.assertIn('guard activities.isEmpty else { publishLocked(); return }', body)

    def test_minimum_visible_floor(self):
        self.assertIn('private static let minimumVisible: TimeInterval = 0.6', TOOLS)
        self.assertIn('delay = Self.minimumVisible - elapsed', signal_body())

    def test_delayed_hide_is_cancellable(self):
        body = signal_body()
        self.assertIn('pendingHide?.cancel()', body)
        self.assertIn('hideIfIdle(generation: generation)', body)

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
        self.assertNotIn('if tool == "browser_use" { return true }', body)
        self.assertIn('guard tool == "shell_execute"', body)
        self.assertIn('return !deviceInvocations(command, includeNative: false).isEmpty', body)
        self.assertIn('words[1] == "call"', body)
        self.assertIn('name == "minis-mcp-cli"', body)
        self.assertIn('name == "mcp"', body)
        self.assertIn('words.count >= 4', body)
        self.assertIn('words.count >= 3', body)
        # Neither real local tools nor the browser branch owns a sight token.
        funnel = TOOLS[TOOLS.index('func executeSingleToolUse('):]
        browser = funnel[funnel.index('case "browser_use":'):funnel.index('case "read_image":')]
        self.assertNotIn('MiniSightSignal', browser)

    def test_signal_ends_only_after_owned_scopes_finish(self):
        body = signal_body()
        self.assertIn('guard activities.removeValue(forKey: token) != nil else { return }', body)
        self.assertIn('guard activities.isEmpty else { publishLocked(); return }', body)
        self.assertIn('activities.isEmpty, stateGeneration == generation, shownAt != nil', body)


class ApprovalBridgeContracts(unittest.TestCase):
    def test_single_request_and_cancel_are_fail_closed(self):
        bridge = (ROOT / 'src/ios/Views/Settings/MiniSightConfirm.swift').read_text()
        self.assertIn('guard !requestInFlight else { return false }', bridge)
        self.assertIn('withTaskCancellationHandler', bridge)
        self.assertIn('finish(false, cancelPet: true)', bridge)
        self.assertIn('confirm-cancel.txt', bridge)
        self.assertIn('Self.cancelName', bridge)
        self.assertIn('try? FileManager.default.removeItem(at: resultURL)', bridge)


class FunnelWiring(unittest.TestCase):

    def test_begin_and_defer_end_at_mcp_execution_scope(self):
        i = TOOLS.index('case "shell_execute":')
        end = TOOLS.index('case "file_read":', i)
        body = TOOLS[i:end]
        self.assertIn('MiniSightSignal.shouldSignal(tool: tu.name, args: argsJson)', body)
        self.assertIn('MiniSightSignal.shared.begin(phase: .waiting', body)
        self.assertIn('defer { if let sightToken { MiniSightSignal.shared.end(sightToken) } }', body)
        self.assertLess(body.index('begin(phase: .waiting'), body.index('end(sightToken)'))

    def test_no_generic_funnel_wakeup(self):
        i = TOOLS.index('func executeSingleToolUse(')
        head = TOOLS[i:TOOLS.index('switch tu.name', i)]
        self.assertNotIn('MiniSightSignal.shared.begin', head)
        self.assertNotIn('MiniSightSignal.shared.end', head)


if __name__ == '__main__':
    unittest.main(verbosity=2)
