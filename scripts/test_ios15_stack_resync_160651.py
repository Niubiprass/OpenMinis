#!/usr/bin/env python3
"""Source-contract tests for [T-ios15-stack-resync].

Reported 2026-10-20 18:47 (screen recording): the user could not enter ANY
session and could not create a new one; only a relaunch recovered it. Same
family as the earlier 「退出不了会话」 freeze.

Device log, PID 16510, 18:47:00–18:47:20:
    forty  🔑DRAFT openSession id=…      (every tap, alternately two sessions)
    ZERO   🔄SESSION stackNav APPEAR     (no screen ever presented)
    → app relaunched at 18:47:56 (new PID, mounts replayed)

Immediately before it, 18:47:05.921 → 18:47:06.952 shows an Inactive→Active
blip with `[SuspendState] SUSPEND … RESUME`, i.e. the streaming UI was torn
down and rebuilt. The stack's pushed screen went away with it, but
`navigationPath` — the INTENT — stayed non-empty. Every later tap appended
another entry to a path whose screen no longer existed, so the simulated
stack had nothing to show and each push was swallowed.

Contract: intent alone must never be trusted. The destination view reports what
is actually mounted (`mountedStackChatId`), and a tap that finds "path non-empty
but nothing mounted" REPLACES the path instead of appending to it. That heals
both 「进不去会话」 and 「建不了新会话」 with one commit.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()


class MountedReality(unittest.TestCase):

    def test_state_tracks_the_mounted_chat(self):
        self.assertIn('@State private var mountedStackChatId: String?', CONTENT)

    def test_destination_reports_appear_and_disappear(self):
        i = CONTENT.index('.navigationDestination(for: String.self)')
        body = CONTENT[i:CONTENT.index('// MARK: - Detail View', i)]
        self.assertIn('mountedStackChatId = id', body)
        self.assertIn('if mountedStackChatId == id { mountedStackChatId = nil }', body)


class SelfHealingTap(unittest.TestCase):

    def test_open_session_replaces_a_dead_path(self):
        i = CONTENT.index('private func openSession(_ id: String) {')
        body = CONTENT[i:i + 2200]
        self.assertIn('if !navigationPath.isEmpty, mountedStackChatId == nil {', body)
        self.assertIn('switchToSession(id)', body)

    def test_heal_happens_before_the_append(self):
        i = CONTENT.index('private func openSession(_ id: String) {')
        body = CONTENT[i:i + 2200]
        self.assertLess(body.index('mountedStackChatId == nil'),
                        body.index('next.append(id)'))

    def test_heal_is_logged(self):
        self.assertIn('stack resync — pathCount=', CONTENT)

    def test_normal_append_still_used_when_a_chat_is_mounted(self):
        # Regression guard: the fix must not turn every tap into a replace.
        i = CONTENT.index('private func openSession(_ id: String) {')
        body = CONTENT[i:i + 2200]
        self.assertIn('next.append(id)', body)
        self.assertIn('commitNavigationPath(next)', body)


class NoNewBackgroundDeferral(unittest.TestCase):

    def test_switch_to_session_replaces_path(self):
        i = CONTENT.index('private func switchToSession(_ id: String) {')
        body = CONTENT[i:i + 500]
        self.assertIn('commitNavigationPath(NavigationPath([id]))', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
