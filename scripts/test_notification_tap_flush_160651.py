#!/usr/bin/env python3
"""Source-contract tests for [T-notification-tap-deferred-flush].

Reported 2026-10-20 (video + screen recording): while the user was in another
app, a "task completed" notice arrived; tapping it opened Minis on the session
LIST instead of the session the notice was about.

Device log made the failure unambiguous:

    04:02:04.625  🔄SESSION deferring nav commit — app backgrounded (count=1)
    04:02:04.687  lifecycle=didBecomeActive
    …            (no "flushing deferred nav commit" line at all)

So the tap DID arrive, the delegate DID fire, the sessionId WAS right, and the
push WAS requested — it was parked by the background-navigation gate and then
never released. The gate's own guard was the trap: the flush ran once, saw
`applicationState == .background` (SwiftUI's scenePhase flips before UIKit's
state does), returned, and nothing ever tried again.

Contract:
- A deferred push is retried a bounded number of times instead of being
  dropped on the first "still background" answer.
- `UIApplication.didBecomeActiveNotification` is the authoritative release
  point: it is posted AFTER applicationState becomes .active.
- The 90s staleness TTL still applies — an old destination must not yank the
  user somewhere they did not ask for.
- The deferral itself must NOT be removed: it exists to keep a background push
  from running a chat's first layout against a watchdog clock
  ([T-ios-bg-nav-push-watchdog]).

Static source checks only; the real proof is one notification tap on device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()


def func_body(name, next_marker='\n    }'):
    i = CONTENT.index(name)
    return CONTENT[i:CONTENT.index(next_marker, i)]


class DeferredFlush(unittest.TestCase):

    def test_retry_instead_of_single_shot(self):
        body = func_body('private func flushPendingBackgroundNavigation() {',
                         '// Consume before the staleness check')
        self.assertIn('guard UIApplication.shared.applicationState != .background else {', body)
        self.assertIn('schedulePendingFlushRetry()', body)
        self.assertNotIn('guard UIApplication.shared.applicationState != .background else { return }', body)

    def test_retry_is_bounded(self):
        self.assertIn('private static let pendingFlushRetryLimit = 10', CONTENT)
        self.assertIn('pendingFlushRetryCount < Self.pendingFlushRetryLimit', CONTENT)
        self.assertIn('retry budget exhausted', CONTENT)

    def test_retry_delay_is_short(self):
        # 200 ms: the transition it waits for measured 62 ms on device.
        self.assertIn('private static let pendingFlushRetryDelay: TimeInterval = 0.2', CONTENT)

    def test_retry_counter_resets(self):
        body = func_body('private func flushPendingBackgroundNavigation() {')
        self.assertIn('pendingFlushRetryCount = 0', body)

    def test_did_become_active_is_the_release_point(self):
        self.assertIn('publisher(for: UIApplication.didBecomeActiveNotification)', CONTENT)
        i = CONTENT.index('publisher(for: UIApplication.didBecomeActiveNotification)')
        tail = CONTENT[i:i + 900]
        self.assertIn('flushPendingBackgroundNavigation()', tail)

    def test_staleness_ttl_preserved(self):
        self.assertIn('pendingBackgroundNavigationTTL: TimeInterval = 90', CONTENT)
        self.assertIn('discarding deferred nav commit — stale', CONTENT)

    def test_deferral_still_exists_for_background_push_safety(self):
        # Removing the gate would trade a missed navigation for a background
        # first-layout hang — the crash it was built for.
        self.assertIn('pendingBackgroundNavigation = (newPath, Date())', CONTENT)
        self.assertIn('app backgrounded (count=', CONTENT)

    def test_flush_is_logged_both_ways(self):
        self.assertIn('flushing deferred nav commit (count=', CONTENT)
        self.assertIn('deferred nav commit applied', CONTENT)
        self.assertIn('retrying deferred nav commit (attempt=', CONTENT)


class NotificationTapPath(unittest.TestCase):
    """The parts that were ALREADY correct — pinned so a regression names itself."""

    def test_delegate_registered_at_launch(self):
        app = (ROOT / 'src/ios/AppDelegate.swift').read_text()
        self.assertIn('ShortcutNotificationDelegate.shared.register()', app)

    def test_did_receive_carries_session_id(self):
        intent = (ROOT / 'src/ios/Agent/Intents/SendPromptIntent.swift').read_text()
        self.assertIn('userInfo["sessionId"] as? String', intent)
        self.assertIn('NotificationNavigationStore.shared.setPending(sessionId)', intent)
        self.assertIn('openSessionFromIntent', intent)

    def test_no_ios16_gate_left(self):
        # ONLY the delegate class must be ungated — `SendPromptIntent` is a real
        # AppIntents type and keeps its iOS 16 gate legitimately.
        intent = (ROOT / 'src/ios/Agent/Intents/SendPromptIntent.swift').read_text()
        self.assertNotIn('@available(iOS 16.0, *)\nfinal class ShortcutNotificationDelegate', intent)
        i = intent.index('final class ShortcutNotificationDelegate')
        head = intent[max(0, i - 200):i]
        self.assertNotIn('@available(iOS 16', head)

    def test_warm_path_switches_session_atomically(self):
        i = CONTENT.index('publisher(for: Notification.Name("openSessionFromIntent"))')
        body = CONTENT[i:i + 1200]
        self.assertIn('nnsMarkHandled()', body)
        self.assertIn('switchToSession(sessionId)', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
