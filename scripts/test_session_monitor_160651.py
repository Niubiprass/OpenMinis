#!/usr/bin/env python3
"""Source-contract tests for [T-session-monitor].

Requested 2026-10-20: 「其他会话可以在我聊的会话界面显示窗口，让我知道它在干嘛」
…then refined across several mockups into the final shape:

- Enabled PER SESSION from the sidebar's long-press menu (小圆点 icon), not by a
  global switch — the user asked "怎么控制会话？我要每个会话控制".
- The pill only appears for sessions that are (a) marked 监看 and (b) actually
  running; it never includes the session you are looking at.
- Collapsed: "N 个在运行 · 2:14". Tap → short list with title / what it is doing
  / elapsed. Tap a row → jump to that session. Drag → position remembered.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
STORE = (ROOT / 'src/ios/Agent/Chat/ChatLifecycleSupport.swift').read_text()
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()


class Store(unittest.TestCase):

    def test_monitored_set_is_persisted(self):
        self.assertIn('final class SessionMonitorStore: ObservableObject', STORE)
        self.assertIn('private static let defaultsKey = "monitoredSessionIds"', STORE)
        self.assertIn('UserDefaults.standard.set(Array(monitored), forKey: Self.defaultsKey)', STORE)

    def test_toggle_flips_one_session(self):
        i = STORE.index('func toggle(_ sessionId: String)')
        body = STORE[i:i + 500]
        self.assertIn('monitored.insert(sessionId)', body)
        self.assertIn('monitored.remove(sessionId)', body)

    def test_elapsed_clock_starts_and_clears_with_running_state(self):
        i = STORE.index('func sync(runningIds: Set<String>)')
        body = STORE[i:i + 700]
        self.assertIn('startedAt[id] = Date()', body)
        self.assertIn('startedAt.removeValue(forKey: id)', body)

    def test_no_sync_to_cloud(self):
        # A view preference, exactly like collapsedSessionIds.
        self.assertNotIn('CloudSync', STORE[STORE.index('final class SessionMonitorStore'):])


class Menu(unittest.TestCase):

    def test_menu_action_exists(self):
        self.assertIn('case toggleMonitor(String)', CONTENT)

    def test_wording_flips_and_uses_the_dot_icon(self):
        self.assertIn('key.monitored ? "取消监看" : "监看"', CONTENT)
        self.assertIn('key.monitored ? "smallcircle.filled.circle" : "circle"', CONTENT)

    def test_handler_toggles_the_store(self):
        i = CONTENT.index('case .toggleMonitor(let sid):')
        self.assertIn('SessionMonitorStore.shared.toggle(sid)', CONTENT[i:i + 120])

    def test_key_carries_monitored_state(self):
        self.assertIn('let monitored: Bool', CONTENT)
        self.assertEqual(CONTENT.count('monitored: SessionMonitorStore.shared.isMonitored'), 2)


class Pill(unittest.TestCase):

    def test_pill_is_mounted_on_the_transcript(self):
        self.assertIn('SessionMonitorPill(currentSessionId: vm.sessionId)', CHAT)

    def test_pill_excludes_the_current_session(self):
        self.assertIn('$0 != currentSessionId', CHAT)

    def test_pill_only_shows_marked_sessions(self):
        self.assertIn('store.isMonitored($0)', CHAT)

    def test_pill_hides_when_nothing_is_running(self):
        i = CHAT.index('private struct SessionMonitorPill: View')
        body = CHAT[i:]
        self.assertIn('if rows.isEmpty {', body)
        self.assertIn('EmptyView()', body)

    def test_expanding_and_jumping(self):
        i = CHAT.index('private struct SessionMonitorPill: View')
        body = CHAT[i:]
        self.assertIn('expanded = true', body)
        self.assertIn('name: Notification.Name("openSessionFromIntent")', body)

    def test_position_is_remembered(self):
        i = CHAT.index('private struct SessionMonitorPill: View')
        body = CHAT[i:]
        self.assertIn('@AppStorage("sessionMonitor.pillDX")', body)
        self.assertIn('@AppStorage("sessionMonitor.pillDY")', body)

    def test_timer_lives_in_the_pill_not_the_chat_body(self):
        # The elapsed labels tick once a second; if that state lived on the chat
        # view the whole transcript would re-render every second. Scoped to the
        # pill's own struct — the stop button carries its own 1 s timer too, and
        # is equally a self-contained leaf.
        i = CHAT.index('private struct SessionMonitorPill: View')
        body = CHAT[i:]
        self.assertIn('Timer.publish(every: 1', body)
        self.assertIn('@ObservedObject private var tracker', body)

    def test_tap_header_collapses(self):
        # User asked for a manual collapse, not only the 8 s auto one.
        i = CHAT.index('private struct SessionMonitorPill: View')
        body = CHAT[i:]
        self.assertIn('expanded = false', body)
        self.assertIn('chevron.up', body)

if __name__ == '__main__':
    unittest.main(verbosity=2)
