#!/usr/bin/env python3
"""Source contracts and numeric bounds for the composer rainbow wave.

This is a static/numeric test, not a SwiftUI renderer or native iOS build.

The contract changed on 2026-11-22: the wave is now matched to the reference
recording (dot pitch / dot size / travelling flow / measured hue proportions)
instead of the earlier dense design. The bounds below encode THAT target.
"""
from pathlib import Path
import difflib
import hashlib
import math
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "src/ios/Views/Chat/AIChatView.swift"
WAVE = ROOT / "src/ios/Views/Chat/AudioWaveformView.swift"
BASELINE = ROOT / "scripts/fixtures/composer_wave_baseline_20261120"

# Hue shares measured from the reference (bottom band, 9 frames).
MEASURED_SHARES = {
    "red": 16.2, "orange": 9.1, "yellow-green": 1.2, "green-cyan": 13.0,
    "cyan-blue": 23.5, "blue-violet": 5.4, "violet": 4.1, "magenta": 27.5,
}


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


def swift_ternary(expr):
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
    expr = re.sub(r"\bDouble\(", "float(", expr)
    expr = re.sub(r"\bCGFloat\(", "float(", expr)
    expr = re.sub(r"\bInt\(", "int(", expr)
    expr = re.sub(r"\b\w+:\s*", "", expr)
    return expr


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
               "floor": math.floor, "ceil": math.ceil,
               "sin": math.sin, "cos": math.cos, "exp": math.exp, "pi": math.pi,
               **cls.constants}
        env["latticeNoise"] = staticmethod(scalar_function(cls.wave, "private func latticeNoise(", ["value"], env))
        env["smoothNoise"] = staticmethod(scalar_function(cls.wave, "private func smoothNoise(", ["position"], env))

        table = re.search(r"private static let profile: \[Double\] = \[([^\]]+)\]", cls.wave)
        assert table, "profile table missing"
        env["profile"] = [float(v) for v in table.group(1).split(",") if v.strip()]
        env["profileUnit"] = staticmethod(scalar_function(cls.wave, "private func profileUnit(", ["unit"], env))

        # Travelling-wave table, rebuilt with the same formula in Python so the
        # loop in flowScale does not have to be transpiled.
        flow = re.findall(r"\(\s*([\d.]+),\s*(-?[\d.]+),\s*([\d.]+)\s*\)",
                          block(cls.wave, "private static let flow:"))
        assert len(flow) == 3, f"expected 3 flow components, got {flow}"
        env["flow"] = [tuple(float(v) for v in row) for row in flow]

        def flowScale(unit, time):
            amount = 0.0
            for wavelengths, speed, amplitude in env["flow"]:
                amount += amplitude * math.sin(2 * math.pi * (wavelengths * unit - speed * time))
            edge = min(1.0, min(unit, 1 - unit) / 0.16)
            return max(0.22, 1.0 + amount * edge)
        env["flowScale"] = staticmethod(flowScale)

        env["drift"] = staticmethod(scalar_function(cls.wave, "private func drift(", ["time"], env))
        cls.row_count = staticmethod(scalar_function(cls.wave, "private func rowCount(", ["height"], env))
        cls.column_count = staticmethod(scalar_function(cls.wave, "private func columnCount(", ["width"], env))
        cls.wave_height = staticmethod(scalar_function(cls.wave, "private func waveHeight(",
                                                       ["unit", "time"], env))

    # ---- geometry: matched to the reference recording -------------------

    def test_geometry_matches_reference_grid(self):
        c = self.constants
        # 913 px card / 12 px pitch = 76 dots; 6 px dots → dot/pitch = 0.5.
        ratio = c["dotSize"] / c["columnPitch"]
        self.assertGreaterEqual(ratio, 0.42)
        self.assertLessEqual(ratio, 0.58)
        self.assertAlmostEqual(c["columnPitch"], c["rowPitch"], places=6)  # square grid
        self.assertGreaterEqual(c["columnPitch"], 4.0)
        self.assertLessEqual(c["columnPitch"], 5.2)
        self.assertLessEqual(c["maxRows"], 10)
        self.assertGreaterEqual(c["peakHeight"], 24.0)
        self.assertLessEqual(c["peakHeight"], 28.0)
        self.assertLessEqual(c["canvasHeight"], 80)
        for width in (296, 320, 350, 366, 390):
            columns = self.column_count(width)
            self.assertGreaterEqual(columns, 60)
            self.assertLessEqual(columns, 96)
        self.assertLessEqual(self.column_count(1024), c["maxColumns"])

    def test_heights_bounded_and_rows_capped(self):
        c = self.constants
        peak_over_time = 0.0
        for t in (0, 1, 5, 30, 800000000, 3.3, 7.7, 11.1, 21.5):
            hs = [self.wave_height(i / 200, t) for i in range(201)]
            self.assertGreaterEqual(min(hs), 0.0)
            self.assertLessEqual(max(hs), c["peakHeight"] * 1.9)
            self.assertGreaterEqual(max(hs), 15.0)   # a crest always exists
            peak_over_time = max(peak_over_time, max(hs))
            for h in hs:
                rows = self.row_count(h)
                self.assertGreaterEqual(rows, 1)
                self.assertLessEqual(rows, c["maxRows"])

    # ---- flow: the surface must travel, not pulse ----------------------

    def test_surface_travels_like_water(self):
        def crest(t):
            samples = [i / 400 for i in range(401)]
            weights = [max(0.0, self.wave_height(u, t) - 2.0) for u in samples]
            total = sum(weights)
            self.assertGreater(total, 0.0)
            return sum(u * w for u, w in zip(samples, weights)) / total

        positions = [crest(t) for t in (0, 0.25, 0.5, 1.0, 2.0)]
        self.assertGreater(max(positions) - min(positions), 0.03)   # crest wanders
        self.assertLess(max(positions) - min(positions), 0.40)      # but stays a wave

        # Frame-to-frame change at 30 fps: visible, yet not jitter.
        deltas = []
        for t in (0.0, 1.0, 2.5):
            a = [self.wave_height(i / 200, t) for i in range(201)]
            b = [self.wave_height(i / 200, t + 1.0 / 30.0) for i in range(201)]
            deltas.append(sum(abs(x - y) for x, y in zip(a, b)) / len(a))
        mean_delta = sum(deltas) / len(deltas)
        self.assertGreater(mean_delta, 0.25)    # reference: ~0.43 pt per frame
        self.assertLess(mean_delta, 2.0)

    def test_wave_ignores_microphone_levels(self):
        # The composer wave is an idle animation; it must not read `levels`.
        height_block = block(self.wave, "private func waveHeight(")
        self.assertNotIn("sampledLevel", height_block)
        self.assertNotIn("audio", height_block)
        self.assertIn("private func sampledLevel(at position: Double)", self.wave_source)
        self.assertIn("if voiceInputActive { return voiceVM.waveformLevels }", self.chat)

    # ---- colour: measured proportions ---------------------------------

    def test_palette_reproduces_measured_hue_shares(self):
        cycle_src = block(self.wave, "private static let cycle:")
        weights = [(float(h), float(w)) for h, w in
                   re.findall(r"\(\s*([\d.]+),\s*([\d.]+)\s*\)", cycle_src)]
        self.assertEqual(len(weights), 7, f"expected 7 hue anchors, got {weights}")
        total = sum(w for _, w in weights)
        self.assertAlmostEqual(total, 100.0, delta=1.5)   # measured shares, not arbitrary weights

        def share(lo, hi):
            return sum(w for h, w in weights if lo <= h < hi) / total * 100.0

        got = {
            "red": share(0.0, 0.08),
            "orange": share(0.08, 0.20),
            "yellow-green": share(0.20, 0.35),
            "green-cyan": share(0.35, 0.50),
            "cyan-blue": share(0.50, 0.62),
            "blue-violet": share(0.62, 0.75),
            "violet": share(0.75, 0.88),
            "magenta": share(0.88, 1.0),
        }
        for name, target in MEASURED_SHARES.items():
            self.assertLessEqual(abs(got[name] - target), 6.0,
                                 f"{name}: {got[name]:.1f}% vs measured {target}%")

    def test_colour_scrolls_and_warms_only_at_crests(self):
        # The band travels sideways; a static gradient cannot match the video.
        self.assertIn("time * Self.cycleSpeed", self.wave)
        self.assertIn("private static let cycleSpeed", self.wave)
        self.assertIn("private static let cycleSpan", self.wave)
        # Warmth is gated by height and steep in the vertical direction, so the
        # hue does not sweep through green on its way to orange.
        self.assertIn("pow(Double(row) / Double(rows - 1), 3.2)", self.wave)
        self.assertIn("private static let crestHue", self.wave)
        warm = block(self.wave, "private func warmAmount(")
        self.assertIn("/ 0.40", warm)
        self.assertNotIn("Gradient(colors:", self.wave)   # per-dot colour, not a painted ramp

    # ---- unchanged behaviour ------------------------------------------

    def test_reduce_motion_and_accessibility(self):
        self.assertIn("let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate", self.wave)
        self.assertIn("paused: reduceMotion", self.wave)
        self.assertIn("if !reduceMotion", self.wave)
        self.assertIn("guard !reduceMotion else { return }", self.wave)
        self.assertIn(".accessibilityHidden(true)", self.wave)
        self.assertIn(".allowsHitTesting(false)", self.wave)
        self.assertIn("Canvas(opaque: false", self.wave)
        self.assertNotIn("Timer.publish", self.wave)
        self.assertNotIn("drawingGroup()", self.wave)
        base = [self.wave_height(i / 100, 0) for i in range(101)]
        self.assertEqual(base, [self.wave_height(i / 100, 0) for i in range(101)])

    def test_row_light_thread_matches_measurements(self):
        # Measured from the reference: row 4 (0 = bottom) carries a near-white
        # stretch, centre 0.52-0.61 of the width, length pulsing 20-50%.
        c = self.constants
        self.assertAlmostEqual(c["rowLightIndex"], 4.0, places=2)
        self.assertAlmostEqual(c["rowLightSigma"], 1.1, places=2)
        self.assertAlmostEqual(c["rowLightCentre"], 0.56, places=2)
        self.assertAlmostEqual(c["rowLightLength"], 0.32, places=2)
        self.assertGreaterEqual(c["rowLightWhite"], 0.7)
        self.assertIn("private func rowLight(", self.wave)
        self.assertIn("exp(-rowDistance * rowDistance)", self.wave)
        self.assertIn("whiten: Self.rowLightWhite * light", self.wave)
        # Near-white on purpose: the measured stretch is V 0.94 / S 0.18.
        self.assertIn("private static func color(hue: Double, sat: Double, val: Double, whiten: Double = 0)",
                      self.wave)

    def test_vertical_three_stage_wash(self):
        # Bottom rows deep/saturated, upper rows pale — measured, not taste.
        self.assertIn("let vertical = rows > 1 ? Double(row) / Double(rows - 1) : 0", self.wave)
        self.assertIn("0.88 - 0.42 * pow(vertical, 0.85)", self.wave)

    def test_transition_trails_remain(self):
        self.assertIn(".onChange(of: voiceActive)", self.wave)
        self.assertIn("transitionBeganAt = timeline.date.timeIntervalSinceReferenceDate", self.wave)
        self.assertIn("private static let transitionLife = 0.48", self.wave)
        self.assertIn("traceContext.opacity = opacity * (1.0 - progress)", self.wave)
        self.assertIn("trace.addQuadCurve", self.wave)

    def test_composer_surface_only_hosts_the_background(self):
        self.assertIn(".background(alignment: .bottom) { wave }", self.surface)
        self.assertIn(".clipShape(shape)", self.surface)
        self.assertIn(".frame(height: ComposerRainbowWave.canvasHeight)", self.surface)
        self.assertNotIn(".padding(", self.surface)
        self.assertNotIn(".offset(", self.surface)

    def test_unrelated_sources_unchanged(self):
        # AudioWaveformView (the level meter above the composer) must not move.
        self.assertEqual(block(self.wave_source, "struct AudioWaveformView: View"),
                         block(baseline_file(WAVE).read_text(), "struct AudioWaveformView: View"))

        # AIChatView gained the download-panel hand-off on 2026-11-22. Every
        # changed hunk must belong to that feature; anything else is drift.
        allowed = ("showDownloadsPanel", "pendingDownloadLocate", "locateDownloadTarget",
                   "DownloadLocateTarget", "downloadLogger", "[Downloads]", "Downloads",
                   # wave batch: the composer call site gained voiceActive earlier
                   "ComposerRainbowWave", "waveLevels", "voiceActive", "opacity")
        old = baseline_file(CHAT).read_text().splitlines()
        new = self.chat.splitlines()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
            if tag == "equal":
                continue
            chunk = "\n".join(old[i1:i2] + new[j1:j2])
            self.assertTrue(any(token in chunk for token in allowed),
                            f"unrelated change in AIChatView: {chunk[:400]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
