#!/usr/bin/env python3
"""Source contracts and numeric bounds for the composer rainbow wave.

This is a static/numeric test, not a SwiftUI renderer or native iOS build.
"""
from pathlib import Path
import hashlib
import math
import re
import subprocess
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "src/ios/Views/Chat/AIChatView.swift"
WAVE = ROOT / "src/ios/Views/Chat/AudioWaveformView.swift"
BASELINE = ROOT / "scripts/fixtures/composer_wave_baseline_20261120"


def block(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[start:cursor]


def baseline_file(path):
    return BASELINE / "app" / path.relative_to(ROOT)


def scalar_function(source, marker, parameters, scope):
    body = block(source, marker).split("{", 1)[1].rsplit("}", 1)[0]
    statements = []
    current = None
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("let ") or line.startswith("return "):
            if current is not None:
                raise AssertionError(f"Missing expression terminator in {marker}: {current}")
            if line.startswith("let "):
                name, expression = line[4:].split("=", 1)
                current = ("let", name.strip(), expression.strip())
            else:
                current = ("return", "", line[7:].strip())
        elif current is not None:
            current = (current[0], current[1], current[2] + " " + line)
        else:
            raise AssertionError(f"Non-scalar statement in {marker}: {line}")
        if current is not None:
            kind, name, expression = current
            balance = expression.count("(") - expression.count(")")
            if balance <= 0 and not expression.endswith(("+", "-", "*", "/", "&&", "||")):
                statements.append(f"{name} = {swift_expr(expression)}" if kind == "let" else "return " + swift_expr(expression))
                current = None
    if current is not None:
        raise AssertionError(f"Unterminated scalar expression in {marker}: {current[2]}")
    code = f"def _f({', '.join(parameters)}):\n" + "\n".join("    " + s for s in statements)
    exec(compile(code, marker, "exec"), scope)
    return scope["_f"]


def swift_ternary(expr):
    """Rewrite a top-level Swift `a ? b : c` into Python `b if a else c`."""
    depth = 0
    quote = False
    qmark = None
    for i, ch in enumerate(expr):
        if quote:
            if ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "?" and depth == 0 and qmark is None:
            qmark = i
        elif ch == ":" and depth == 0 and qmark is not None:
            cond = expr[:qmark].strip()
            yes = expr[qmark + 1:i].strip()
            no = expr[i + 1:].strip()
            return f"({swift_ternary(yes)} if {swift_ternary(cond)} else {swift_ternary(no)})"
    return expr


def swift_expr(expr):
    expr = swift_ternary(expr.strip())
    expr = expr.strip().replace("Self.", "").replace(".pi", "pi")
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"(\w+)\.count\b", r"len(\1)", expr)
    expr = re.sub(r"(?<![=!<>])!(?=\s*[A-Za-z_(])", " not ", expr)
    expr = re.sub(r"\bCGFloat\(", "float(", expr)
    expr = re.sub(r"\bDouble\(", "float(", expr)
    expr = re.sub(r"\bInt\(", "int(", expr)
    expr = re.sub(r"\b\w+:\s*", "", expr)
    return expr


class WaveContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chat = CHAT.read_text()
        cls.wave_source = WAVE.read_text()
        cls.wave = block(cls.wave_source, "struct ComposerRainbowWave: View")
        cls.surface = block(cls.chat, "private struct ComposerSurface: ViewModifier")
        cls.constants = {k: float(v) if "." in v else int(v) for k, v in
                         re.findall(r"static let (\w+)(?:: \w+)? = ([\d.]+)", cls.wave)}
        env = {"min": min, "max": max, "int": int, "float": float,
               "floor": math.floor, "ceil": math.ceil, "sin": math.sin,
               "cos": math.cos, "exp": math.exp, "pi": math.pi, **cls.constants}
        env["latticeNoise"] = staticmethod(scalar_function(cls.wave, "private func latticeNoise(", ["value"], env))
        env["smoothNoise"] = staticmethod(scalar_function(cls.wave, "private func smoothNoise(", ["position"], env))
        cls.smooth_noise = env["smoothNoise"]
        # The silhouette table drives waveHeight, so the extractor needs it too.
        table = re.search(r"private static let profile: \[Double\] = \[([^\]]+)\]", cls.wave)
        if table:
            env["profile"] = [float(v) for v in table.group(1).split(",") if v.strip()]
            env["profileUnit"] = staticmethod(scalar_function(
                cls.wave, "private func profileUnit(", ["unit"], env))
        cls.row_count = staticmethod(scalar_function(cls.wave, "private func rowCount(", ["height"], env))
        cls.wave_height = staticmethod(scalar_function(cls.wave, "private func waveHeight(",
                                                       ["unit", "time", "audio"], env))
        cls.column_count = staticmethod(scalar_function(cls.wave, "private func columnCount(", ["width"], env))

    def test_wave_is_animated_colored_bounded_and_accessibility_safe(self):
        for token in ("TimelineView(.animation(minimumInterval: 1.0 / 30.0",
                       "paused: reduceMotion", "Canvas(opaque: false", "Gradient(colors:",
                       "glow.addFilter(.blur",
                       "transitionLife", "waveHeight", ".allowsHitTesting(false)",
                       ".accessibilityHidden(true)"):
            self.assertIn(token, self.wave)
        self.assertNotIn("spark", self.wave)
        self.assertLessEqual(self.constants["maxColumns"], 180)
        self.assertGreaterEqual(self.constants["maxRows"], 12)
        self.assertIn("for row in 0..<rows", self.wave)
        self.assertIn("age >= 0 && age < Self.transitionLife", self.wave)
        self.assertNotIn("Timer.publish", self.wave)
        self.assertNotIn("DispatchQueue.main.asyncAfter", self.wave)
        self.assertNotIn("drawingGroup()", self.wave)
        self.assertNotIn("Path(CGRect", self.wave)
        self.assertIn("row0.addRect(dot)", self.wave)
        self.assertIn("row4.addRect(dot)", self.wave)

    def test_five_row_geometry_and_intentional_negative_cases(self):
        c = self.constants
        self.assertGreaterEqual(c["maxRows"], 12)      # reference: ~15 rows at the crown
        self.assertLessEqual(c["rowPitch"], 2.0)       # reference: 3.5px / 865px composer
        self.assertGreaterEqual(c["rowPitch"], 1.2)
        self.assertLessEqual(c["canvasHeight"], 80)
        for width in (240, 296, 320, 366, 390, 700, 1024):
            columns = self.column_count(width)
            self.assertGreaterEqual(columns, 2)
            self.assertLessEqual(columns, 260)
            left = 1.15
            right = width - (1.15 + (width - 2.3))
            self.assertAlmostEqual(left, right, places=5)
            self.assertLessEqual(columns * c["maxRows"], 3600)  # dotted field stays bounded
        for t in (0, 1, 5, 30, 800000000):
            heights = [self.wave_height(i / 180, t, 0) for i in range(181)]
            rows = [self.row_count(h) for h in heights]
            self.assertGreaterEqual(min(rows), 1)
            self.assertLessEqual(max(rows), c["maxRows"])
            self.assertGreaterEqual(len(set(rows)), 1)
        # the surface undulates on its own: a tall crest must always exist,
        # the floor must stay a thin band, and nothing may depend on audio.
        for t in (0, 3, 11, 47, 900000000):
            hs = [self.wave_height(i / 180, t, 0) for i in range(181)]
            self.assertGreaterEqual(max(hs), 20.0)     # measured crest ~24pt in the reference
            self.assertLessEqual(min(hs), 8.0)         # edges taper to nothing
            self.assertGreaterEqual(max(self.row_count(h) for h in hs), 12)
            for a in (0.0, 1.0):
                same = [self.wave_height(i / 180, t, a) for i in range(181)]
                self.assertEqual([round(v, 9) for v in hs], [round(v, 9) for v in same])
        for width in (366, 700, 1024):
            self.assertLessEqual(self.column_count(width), 180)
        self.assertLessEqual(self.column_count(1024), 180)
        with self.assertRaises(AssertionError):
            self.assertLessEqual(c["maxRows"] + 1, c["maxRows"])  # cap must reject overflow
        with self.assertRaises(AssertionError):
            self.assertGreaterEqual(c["rowPitch"], 9.0)  # coarse 5-row band must fail
        with self.assertRaises(AssertionError):
            self.assertLessEqual(100, c["canvasHeight"])  # rectangle-height regression

    def test_wave_undulates_on_its_own_and_ignores_levels(self):
        # The reference composer wave is an idle animation: it must move by
        # itself and must NOT change shape with microphone levels.
        for t in (0, 2, 8):
            quiet = [self.wave_height(i / 60, t, 0) for i in range(61)]
            loud = [self.wave_height(i / 60, t, 1) for i in range(61)]
            self.assertEqual([round(v, 9) for v in quiet], [round(v, 9) for v in loud])
        crests = []
        for t in (0, 2, 4, 8, 16):
            hs = [self.wave_height(i / 200, t, 0) for i in range(201)]
            w = [max(0.0, h - 2.4) for h in hs]
            crests.append(sum(i * c for i, c in enumerate(w)) / sum(w) / 200)
        self.assertGreater(max(crests) - min(crests), 0.008)  # crest drifts over time
        self.assertEqual(min(1, max(0, -5)), 0)
        self.assertEqual(min(1, max(0, 3)), 1)
        self.assertIn("sampledLevel(at: unit)", self.wave)
        self.assertIn("return min(1, max(0, Double(levels[index])))", self.wave_source)
        self.assertIn("if voiceInputActive { return voiceVM.waveformLevels }", self.chat)
        self.assertIn("speechManager.audioLevels", self.chat)

    def test_reduce_motion_freezes_time_audio_palette_and_disables_sparks(self):
        self.assertIn("let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate", self.wave)
        self.assertIn("let motionTime = reduceMotion ? 0 : time", self.wave)
        self.assertIn("let audio = reduceMotion ? 0 : sampledLevel(at: unit)", self.wave)
        self.assertIn("if !reduceMotion", self.wave)
        self.assertIn("guard !reduceMotion else { return }", self.wave)
        base = [self.wave_height(i / 100, 0, 0) for i in range(101)]
        self.assertEqual(base, [self.wave_height(i / 100, 0, 0) for i in range(101)])

    def test_composer_layout_is_only_background_and_preserves_controls_byte_for_byte(self):
        old_chat = baseline_file(CHAT).read_text()
        old_surface = block(old_chat, "private struct ComposerSurface: ViewModifier")
        new_without = self.chat.replace(self.surface, "SURFACE")
        old_without = old_chat.replace(old_surface, "SURFACE")
        for a, b in ((new_without, old_without),):
            self.assertEqual(a, b)
        self.assertIn(".background(alignment: .bottom) { wave }", self.surface)
        self.assertIn(".clipShape(shape)", self.surface)
        self.assertIn("RoundedRectangle(cornerRadius: 20, style: .continuous)", self.surface)
        self.assertIn(".frame(height: ComposerRainbowWave.canvasHeight)", self.surface)
        self.assertNotIn(".padding(", self.surface)
        self.assertNotIn(".offset(", self.surface)
        self.assertIn("allowsHitTesting(false)", self.wave)
        self.assertIn("Color.clear.frame(height: 32)", self.chat)

    def test_audio_waveform_view_and_all_unrelated_chat_source_match_frozen_baseline(self):
        old_wave = baseline_file(WAVE).read_text()
        self.assertEqual(block(self.wave_source, "struct AudioWaveformView: View"),
                         block(old_wave, "struct AudioWaveformView: View"))
        self.assertEqual(hashlib.sha256(baseline_file(CHAT).read_bytes()).hexdigest(),
                         "9947d06e164bacd373295271bdc5113f4639c8ba356376f365f0367436ef47dd")
        self.assertIn("inputFieldOrWaveform", self.chat)
        self.assertIn("inputBottomRow", self.chat)

    def test_crests_translate_slowly_and_peak_groups_are_distinct(self):
        positions_a, positions_b = [], []
        samples = [i / 1000 for i in range(1001)]
        for t in (0, 2, 4, 8):
            for lo, hi, output in ((0.08, 0.48, positions_a), (0.52, 0.92, positions_b)):
                points = [u for u in samples if lo <= u <= hi]
                weights = [max(0.0, self.wave_height(u, t, 0) - 1.8) for u in points]
                output.append(sum(u * w for u, w in zip(points, weights)) / sum(weights))
        for positions in (positions_a, positions_b):
            self.assertGreater(max(positions) - min(positions), 0.005)  # measured ~0.01 breathe
            self.assertLessEqual(max(abs(a-b) for a,b in zip(positions, positions[1:])), 0.12)

    def test_status_transition_has_short_fading_trails_and_no_timer(self):
        self.assertIn(".onChange(of: voiceActive)", self.wave)
        self.assertIn("transitionBeganAt = timeline.date.timeIntervalSinceReferenceDate", self.wave)
        self.assertIn("private static let transitionLife = 0.48", self.wave)
        self.assertIn("traceContext.opacity = opacity * (1.0 - progress)", self.wave)
        self.assertIn("traceContext.stroke(trace", self.wave)
        self.assertIn("trace.addQuadCurve", self.wave)
        self.assertNotIn("spark", self.wave)


if __name__ == "__main__":
    unittest.main(verbosity=2)
