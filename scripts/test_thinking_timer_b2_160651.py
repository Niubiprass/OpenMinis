#!/usr/bin/env python3
"""Source-contract tests for [T-thinking-timer-b2].

「思考的后面可以加时间显示吗，不然我都不知道等待多长时间」 — asked 2026-10-20 and
iterated through six placements (message tail, capsule, nav bar, edge rail,
avatar ring, composer placeholder) before the user picked B2:

  the elapsed seconds go INSIDE the composer's red stop button, with a
  comet-tail ring sweeping once a minute around it.

Constraints the user stated explicitly during the review, all pinned here:
- 「点还在动」 — the existing vertical dot animation must be untouched (this
  change does not go near TypingIndicator).
- 「会不会影响之前…卡了一半都不显示」 — the counter must not ride on the chat
  body: it lives in its own view so only that subtree re-renders each second.
- The tap target and layout size must stay the same as the 34pt glyph it
  replaced, so nothing in the composer shifts.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()


class Placement(unittest.TestCase):

    def test_stop_button_uses_the_timed_view(self):
        self.assertIn('StopButtonWithTimer()', CHAT)
        # The old plain glyph must be gone from the stop branch.
        self.assertNotIn('Image(systemName: "stop.circle.fill")\n                    .font(.system(size: 34))', CHAT)

    def test_counter_is_its_own_view(self):
        self.assertIn('private struct StopButtonWithTimer: View {', CHAT)

    def test_timer_lives_inside_that_view(self):
        i = CHAT.index('private struct StopButtonWithTimer: View {')
        body = CHAT[i:]
        self.assertIn('Timer.publish(every: 1', body)
        # …and nowhere near the chat body above it.
        self.assertNotIn('Timer.publish(every: 1', CHAT[:i])


class Ring(unittest.TestCase):

    def test_one_turn_per_minute(self):
        self.assertIn('private static let ticksPerTurn = 60', CHAT)
        self.assertIn('CGFloat(seconds % Self.ticksPerTurn)', CHAT)

    def test_comet_tail_is_a_fading_gradient(self):
        i = CHAT.index('private struct StopButtonWithTimer: View {')
        body = CHAT[i:]
        self.assertIn('AngularGradient', body)
        self.assertIn('Color.red.opacity(0.0)', body)

    def test_ring_hidden_before_the_first_second(self):
        i = CHAT.index('private struct StopButtonWithTimer: View {')
        body = CHAT[i:]
        self.assertIn('.opacity(seconds == 0 ? 0 : 1)', body)

    def test_past_a_minute_switches_to_m_ss(self):
        self.assertIn('String(format: "%d:%02d"', CHAT)


class LayoutSafety(unittest.TestCase):

    def test_footprint_matches_the_old_glyph(self):
        self.assertIn('private static let discSize: CGFloat = 30', CHAT)
        self.assertIn('private static let ringSize: CGFloat = 38', CHAT)
        self.assertIn('.frame(width: Self.ringSize, height: Self.ringSize)', CHAT)

    def test_digits_do_not_push_the_layout(self):
        i = CHAT.index('private struct StopButtonWithTimer: View {')
        body = CHAT[i:]
        self.assertIn('.minimumScaleFactor(0.6)', body)
        self.assertIn('.monospacedDigit()', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
