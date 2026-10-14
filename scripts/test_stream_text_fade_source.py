#!/usr/bin/env python3
"""Source-structure regressions for streaming text visibility (stdlib only).

Run: python3 scripts/test_stream_text_fade_source.py
Negative control: python3 scripts/test_stream_text_fade_source.py --ref f017c76

These tests inspect Swift text, not Swift execution. They do NOT compile UIKit,
run a simulator/device, measure alpha, or establish that flicker is fixed.
--ref reads the two files with git show without changing the working tree.
"""
import argparse
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW_PATH = "src/ios/Views/Chat/SelectableMarkdownView.swift"
FADE_PATH = "src/ios/Views/Chat/TextFadeAnimator.swift"
VIEW = FADE = ""


def without_comments(text):
    # Preserve Swift strings while dropping comments so prose cannot satisfy a
    # regression assertion. This is a source scanner, NOT a Swift parser.
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
    return tokens.sub(lambda m: m[0] if m[0].startswith('"') else " ", text)


def block(source, marker):
    """Return a brace-balanced body following an exact marker."""
    start = source.index("{", source.index(marker)) + 1
    depth = 1
    for pos in range(start, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos]
    raise ValueError("Unbalanced source block: " + marker)


class StreamFadeSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.update = block(VIEW, "func updateUIView(")
        cls.make = block(VIEW, "func makeUIView(")
        cls.coordinator = VIEW[VIEW.index("final class Coordinator:"):]

    def test_ios15_finishes_existing_fades_before_early_returns(self):
        # New systems must not cancel every update (that would disable ripple).
        modern = block(self.update, "if #available(iOS 16.0, *) {")
        self.assertEqual(modern.strip(), "")
        gate = self.update.index("if #available(iOS 16.0, *) {")
        remainder = self.update[gate:]
        legacy = block(remainder, "else {")
        self.assertEqual(legacy.strip(),
                         "context.coordinator.fadeAnimator.cancelAll()")
        cancel = self.update.index("fadeAnimator.cancelAll()")
        for early in ("guard markdown !=", "if shouldDefer {",
                      "if contentHash =="):
            self.assertLess(cancel, self.update.index(early))

    def test_only_reveal_schedule_is_guarded_by_ios16(self):
        self.assertEqual(VIEW.count(".scheduleAnimation(for:"), 1)
        marker = ("if #available(iOS 16.0, *),\n"
                  "           let revealRange = fadeRevealRange,")
        reveal = block(self.update, marker)
        self.assertIn("let liveStorage = textView.textStorage as? NSTextStorage",
                      self.update[self.update.index(marker):])
        self.assertIn("context.coordinator.fadeTextView = textView", reveal)
        self.assertIn("scheduleAnimation(for: revealRange, in: liveStorage)", reveal)
        self.assertNotIn("cancelAll()", reveal)

    def test_every_live_full_assignment_cancels_old_generation_first(self):
        full = block(self.update, "if !fastPathTaken {")
        self.assertRegex(full, r"fadeAnimator\.cancelAll\(\)\s+"
                              r"textView\.attributedText = attributed")
        # Measurement/subview assignments are outside this live render update.
        self.assertEqual(re.findall(r"\battributedText\s*=", self.update),
                         ["attributedText ="])

    def test_new_generation_is_not_cancelled_after_scheduling(self):
        assign = self.update.index("textView.attributedText = attributed")
        schedule = self.update.index(".scheduleAnimation(for:")
        self.assertLess(assign, schedule)
        self.assertNotIn(".cancelAll()", self.update[schedule:])

    def test_append_keeps_textkit_fast_path_without_cancellation(self):
        fast = self.update[self.update.index("var fastPathTaken = false"):
                           self.update.index("if !fastPathTaken {")]
        self.assertIn("Self.prefixesEqualIgnoringFontSubstitution", fast)
        self.assertIn("oldStorage.replaceCharacters(in: tailRange, with: tail)", fast)
        self.assertIn("oldStorage.beginEditing()", fast)
        self.assertIn("oldStorage.endEditing()", fast)
        self.assertIn("fastPathTaken = true", fast)
        self.assertNotIn("cancelAll()", fast)

    def test_reveal_diff_remains_utf16_and_precedes_assignment(self):
        diff = self.update[self.update.index("var fadeRevealRange:"):
                           self.update.index("var fastPathTaken = false")]
        self.assertIn("oldStorage.string as NSString", diff)
        self.assertIn("attributed.string as NSString", diff)
        self.assertIn("newStr.substring(to: oldLen) == (oldStr as String)", diff)
        self.assertIn("NSRange(location: oldLen, length: attributed.length - oldLen)", diff)
        self.assertNotIn(".count", diff)

    def test_prefix_comparison_still_preserves_real_color_and_style_changes(self):
        compare = block(VIEW, "private static func prefixesEqualIgnoringFontSubstitution(")
        # Dropping foregroundColor to hide fade alpha would swallow real styles.
        self.assertNotIn("foregroundColor", compare)
        removals = re.findall(r"removeValue\(forKey: ([^)]+)\)", compare)
        self.assertEqual(removals, ["fontKey", "nsOriginalFontKey"] * 2)
        self.assertIn("(nN as NSDictionary).isEqual(to: nO)", compare)
        self.assertIn("fontN == originalO", compare)
        self.assertIn("effectiveRange: &newRange", compare)
        self.assertIn("effectiveRange: &oldRange", compare)
        self.assertIn("min(NSMaxRange(newRange), NSMaxRange(oldRange)", compare)
        self.assertNotIn("enumerateAttributes", compare)

    def test_make_finishes_old_view_before_new_view_and_drops_replay(self):
        self.assertLess(self.make.index("fadeAnimator.cancelAll()"),
                        self.make.index("let textView = SelectableMarkdownTextView()"))
        self.assertIn("context.coordinator.fadeTextView = nil", self.make)
        self.assertIn("context.coordinator.cancelDeferredRender()", self.make)

    def test_dismantle_finishes_then_releases_redraw_and_replay(self):
        end = block(VIEW, "static func dismantleUIView(")
        self.assertRegex(end, r"coordinator\.fadeAnimator\.cancelAll\(\)\s+"
                             r"coordinator\.fadeTextView = nil\s+"
                             r"coordinator\.cancelDeferredRender\(\)")
        cleanup = block(self.coordinator, "func cancelDeferredRender()")
        self.assertIn("pendingMarkdown = nil", cleanup)
        self.assertIn("replayDeferredRender = nil", cleanup)

    def test_scene_resign_settles_before_display_link_can_pause(self):
        init = block(self.coordinator, "override init()")
        resign = init[init.index("forName: UIApplication.willResignActiveNotification"):]
        self.assertIn("self?.inactiveEnteredAt = Date()", resign)
        self.assertIn("self?.fadeAnimator.cancelAll()", resign)
        foreground = init[:init.index("resignActiveObserver =")]
        self.assertIn("self?.applyDeferredRenderIfNeeded()", foreground)

    def test_foreground_replay_keeps_existing_watchdog_guards(self):
        replay = block(self.coordinator, "private func applyDeferredRenderIfNeeded()")
        self.assertIn("guard UIApplication.shared.applicationState == .active", replay)
        self.assertLess(replay.index("replayDeferredRender = nil"), replay.index("replay()"))
        self.assertIn("case .background: return true", self.update)
        self.assertIn("case .inactive: return inactiveDuration >= 30.0", self.update)
        self.assertIn("context.coordinator.deferRender(markdown)", self.update)

    def test_animator_cancel_stops_link_restores_exact_color_and_clears_ranges(self):
        cancel = block(FADE, "func cancelAll()")
        self.assertLess(cancel.index("stopDisplayLink()"), cancel.index("storage.beginEditing()"))
        self.assertIn("value: w.originalColor, range: w.range", cancel)
        self.assertIn("words.removeAll(keepingCapacity: true)", cancel)
        self.assertNotIn("withAlphaComponent", cancel)
        self.assertIn("displayLink?.invalidate()", block(FADE, "private func stopDisplayLink()"))

    def test_ios16_animator_timing_and_alpha_mechanics_are_retained(self):
        self.assertIn("wordFadeDuration: CFTimeInterval = 0.45", FADE)
        self.assertIn("staggerWindow: CFTimeInterval = 0.10", FADE)
        schedule = block(FADE, "func scheduleAnimation(for")
        self.assertIn("value: original.withAlphaComponent(0)", schedule)
        self.assertIn("startDisplayLinkIfNeeded()", schedule)
        tick = block(FADE, "@objc private func tick()")
        self.assertIn("Self.easeOutCubic(t)", tick)
        self.assertIn("value: w.originalColor, range: w.range", tick)

    def test_rich_text_tables_attachments_and_bounded_layout_stay_present(self):
        for token in ("renderer.render(blocks: content.blocks)", "prebuiltHasTable",
                      "splitStreamingTableTail(markdown)", "TableAttachment",
                      "textView.layoutManager.ensureLayout(forGlyphRange:",
                      "let skipAttachUpdate = fastPathTaken && newAttachInTail == 0",
                      "textView.updateAttachmentViews()"):
            self.assertIn(token, self.update)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ref", help="Inspect a git revision instead of worktree")
    args, test_args = parser.parse_known_args()

    def read(relative):
        if args.ref:
            return subprocess.check_output(
                ["git", "-C", str(args.root), "show", f"{args.ref}:{relative}"],
                text=True)
        return (args.root / relative).read_text(encoding="utf-8")

    global VIEW, FADE
    VIEW, FADE = (without_comments(read(p)) for p in (VIEW_PATH, FADE_PATH))
    print("SOURCE-STRUCTURE ONLY; no Swift compilation or device behavior tested.", flush=True)
    unittest.main(argv=[__file__] + test_args, verbosity=2)


if __name__ == "__main__":
    main()
