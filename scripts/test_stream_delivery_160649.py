#!/usr/bin/env python3
"""Source-structure regressions for REPAIR-160649 streaming text delivery.

Run: python3 scripts/test_stream_delivery_160649.py
Negative control: python3 scripts/test_stream_delivery_160649.py --ref 00c0c3a

These tests inspect Swift text, not Swift execution. They do NOT compile
UIKit, run a simulator/device, or measure wall-clock delivery. The
assertions below re-encode the source contract: every textDelta feeds a
quiet-period tail-edge worker (tier intervals non-decreasing, 0.06s for
short text), tool-block boundaries settle the worker BEFORE publishing so
ordering is preserved, and every exit path (clean end / cancellation /
mid-stream error) finishes the worker before any final write so a stale
snapshot can never overwrite the complete text.
"""
import argparse
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = "src/ios/Agent/Chat/AIChatViewModel+SSEStream.swift"


def load(commit=None):
    """Read the target file from the working tree, or via git show --ref."""
    if commit:
        out = subprocess.run(
            ["git", "show", f"{commit}:{PATH}"], cwd=ROOT,
            capture_output=True, text=True)
        if out.returncode != 0:
            raise SystemExit(out.stderr)
        return out.stdout
    return (ROOT / PATH).read_text()


def without_comments(text):
    """Drop Swift comments while preserving string literals.

    This is a source scanner, NOT a Swift parser.
    """
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


def between(source, start_marker, end_marker):
    return source[source.index(start_marker):source.index(end_marker)]


class StreamDeliverySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.updates = without_comments(load(getattr(cls, "ref", None)))
        cls.raw = load(getattr(cls, "ref", None))
        cls.actor = block(cls.updates, "actor StreamTextDelivery {")
        # Anchor on markers that only exist in processStreamEvents' real switch
        # (the diagEventName switch uses payload-less variants like
        # "case .textDelta:").
        cls.stream_switch = between(cls.updates, "case .contentBlockStart(let start):",
                                    "case .usage(let u):")
        cls.delta_case = between(cls.stream_switch, "case .textDelta(let text):",
                                 "case .toolInputDelta(let name")
        # The tool boundary lives in contentBlockStart(.toolUse): text flush
        # (step 1) THEN tool block append (step 2).
        cls.tool_boundary = between(cls.stream_switch, "case .contentBlockStart(let start):",
                                    "case .textDelta(let text):")
        cls.tool_complete = between(cls.stream_switch, "case .toolCallComplete(",
                                    "case .thinkingDelta")

    def test_tail_edge_enqueue_is_the_text_delta_commit(self):
        # Every textDelta hands the newest snapshot to the delivery worker;
        # the old next-delta-gated inline commit is gone.
        self.assertIn("textDelivery.enqueue(result.assistantText, block: blockIdx)",
                      self.delta_case)
        self.assertNotIn("setStreamingTextBlockContent(", self.delta_case)

    def test_no_delta_throttle_bookkeeping_left(self):
        self.assertNotIn("lastTextDeltaFlush", self.updates)
        self.assertNotIn("lastTextDeltaFlushedLength", self.updates)

    def test_actor_is_fully_wired_not_dead_code(self):
        # Every external entry point has at least one call site.
        self.assertGreaterEqual(self.updates.count("textDelivery.enqueue("), 1)
        self.assertGreaterEqual(self.updates.count("textDelivery.settle()"), 1)
        self.assertGreaterEqual(self.updates.count("textDelivery.finish("), 3)
        # One worker spans the lifetime of one stream: defined once, and
        # instantiated once per processStreamEvents call.
        self.assertEqual(self.updates.count("actor StreamTextDelivery {"), 1)
        self.assertEqual(self.updates.count("let textDelivery = StreamTextDelivery {"), 1)

    def test_interval_tiers_are_monotonic_and_match_spec(self):
        body = block(self.actor, "static func interval(forUTF16Length")
        nums = [float(n) for n in re.findall(r"\b\d+\.\d+\b", body)]
        self.assertEqual(nums, [0.06, 0.10, 0.20, 1.00, 1.50, 2.00])
        self.assertEqual(nums, sorted(nums))
        # Thresholds appear in tier order; >= 32k stays conservative.
        self.assertLess(body.index("< 500"), body.index("< 2_000"))
        self.assertLess(body.index("< 2_000"), body.index("< 32_000"))
        self.assertLess(body.index("< 32_000"), body.index("< 64_000"))
        self.assertLess(body.index("< 64_000"), body.index("< 128_000"))
        # The worker waits per-tier on the UTF-16 snapshot length.
        self.assertIn("interval(forUTF16Length: next.text.utf16.count)", self.actor)

    def test_sink_signature_carries_target_block_and_finality(self):
        self.assertIn("@Sendable (Int, String, Bool) async -> Void", self.actor)
        # Tail commits are NOT final (no attributed cache, scroll allowed).
        self.assertIn("await sink(snapshot.block, snapshot.text, false)", self.actor)
        # Finish commits the final snapshot.
        finish = block(self.actor, "func finish(with text: String, block: Int)")
        self.assertIn("await stop()", finish)
        self.assertIn("await sink(block, text, true)", finish)

    def test_stop_closes_before_join_so_no_stale_overwrite(self):
        stop = block(self.actor, "func stop() async")
        self.assertLess(stop.index("closed = true"), stop.index("cancel()"))
        self.assertIn("await oldWorker?.value", stop)
        stop_tail = stop[stop.index("await oldWorker?.value"):]
        self.assertIn("pending = nil", stop_tail)

    def test_settle_is_rearmable_mid_stream(self):
        # settle() must NOT close the actor — enqueue re-arms a fresh worker.
        settle = block(self.actor, "func settle() async")
        self.assertNotIn("closed = true", settle)
        self.assertIn("await oldWorker?.value", settle)

    def test_tool_boundary_settles_before_publish(self):
        # Ordering: join the tail worker, flush the text block, THEN append
        # the tool block — the tool publish can never be overtaken.
        self.assertIn("await textDelivery.settle()", self.tool_boundary)
        flush = self.tool_boundary.index("await textDelivery.settle()")
        append = self.tool_boundary.index("messages[msgIdx].blocks.append(toolBlock)")
        self.assertLess(flush, append)
        # The boundary still force-flushes the complete text block (direct
        # write, bypassing the suspend gate) so no text is swallowed.
        self.assertIn("block.content = assistantText", self.tool_boundary)
        self.assertIn("publishUnlessTransitioning()", self.tool_boundary)
        # toolCallComplete's own flush stays comprehensive (fresh markdown).
        self.assertIn("setStreamingTextBlockContent(", self.tool_complete)
        self.assertIn("cacheAttributedString: true", self.tool_complete)

    def test_exit_paths_finish_before_any_final_throw_or_return(self):
        # CancellationError path.
        cancel = block(self.updates, "} catch is CancellationError {")
        self.assertIn("textDelivery.finish(", cancel)
        self.assertLess(cancel.index("textDelivery.finish("),
                        cancel.index("throw CancellationError()"))
        # Mid-stream error path.
        self.assertIn("await textDelivery.finish(with: result.assistantText",
                      self.updates)
        self.assertLess(self.updates.index('if let err = _streamError {'),
                        self.updates.index("textDelivery.finish(",
                                           self.updates.index('if let err = _streamError {')))
        self.assertLess(self.updates.index("textDelivery.finish(",
                                           self.updates.index('if let err = _streamError {')),
                        self.updates.index("throw err"))
        # Clean end: finish lands after the TTS tail flush, before return.
        clean = self.updates[self.updates.index("feedDynamicTTS(buf, force: true)"):]
        self.assertIn("textDelivery.finish(", clean)
        self.assertLess(clean.index("textDelivery.finish("), clean.index("return result"))

    def test_tts_and_scroll_semantics_preserved(self):
        # First-delta TTS clear + sentence extraction stay in the delta path.
        self.assertIn("stopSpeechForThisSession", self.delta_case)
        self.assertIn("extractNewSentences(from: result.assistantText", self.delta_case)
        self.assertIn("feedDynamicTTS(buffered, force: false)", self.delta_case)
        # The delivery sink maps finality onto the old commit behaviour:
        # final -> cache attributed string, no scroll; live -> scroll.
        delivery = self.updates[self.updates.index("let textDelivery = StreamTextDelivery"):
                                self.updates.index("var lastThinkingDeltaFlush")]
        self.assertIn("cacheAttributedString: isFinal", delivery)
        self.assertIn("requestScroll: !isFinal", delivery)
        # Everything routes through setStreamingTextBlockContent exactly twice
        # in this file: the actor sink + the tool boundary flush.
        self.assertEqual(self.updates.count("setStreamingTextBlockContent("), 2)

    def test_interval_names_utf16_and_units_match_doc(self):
        # The worker latches the target block at enqueue time.
        enqueue = block(self.actor, "func enqueue(_ text: String, block: Int)")
        self.assertIn("pending = (block, text)", enqueue)
        self.assertIn("guard worker == nil else { return }", enqueue)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", metavar="COMMIT",
                        help="read the source from git show COMMIT instead of "
                             "the working tree (negative control: tests should fail)")
    args = parser.parse_args()
    StreamDeliverySourceTests.ref = args.ref
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StreamDeliverySourceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()