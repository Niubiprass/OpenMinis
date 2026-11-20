#!/usr/bin/env python3
"""Source contracts for the composer rainbow wave in text and voice modes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "src/ios/Views/Chat/AIChatView.swift"
WAVE = ROOT / "src/ios/Views/Chat/AudioWaveformView.swift"


class ComposerRainbowWaveContracts(unittest.TestCase):
    def test_shared_wave_is_colored_animated_and_accessibility_safe(self):
        text = WAVE.read_text()
        self.assertIn("struct ComposerRainbowWave: View", text)
        self.assertIn("TimelineView(.animation", text)
        self.assertIn("Canvas(opaque: false", text)
        self.assertIn("private let colorStops:", text)
        self.assertIn("let root = size.height - 1.5", text)
        self.assertIn("particlePaths[bucket].addRect(rect)", text)
        self.assertIn("colorBucketCount = 28", text)
        self.assertIn("maxRise = min(size.height - 2, 54)", text)
        self.assertIn("smoothNoise(position:", text)
        self.assertIn("private func hash(column:", text)
        self.assertIn("accessibilityReduceMotion", text)
        self.assertIn(".allowsHitTesting(false)", text)
        self.assertIn(".accessibilityHidden(true)", text)

    def test_wave_is_mounted_on_the_complete_composer_not_the_text_field(self):
        text = CHAT.read_text()
        self.assertIn("private var composerWaveLevels: [Float]", text)
        self.assertIn(".modifier(ComposerSurface(waveLevels: composerWaveLevels))", text)
        surface = text.split("private struct ComposerSurface: ViewModifier", 1)[1].split(
            "private struct ComposerContextGlow", 1)[0]
        self.assertIn("var waveLevels: [Float] = []", surface)
        self.assertIn("ComposerRainbowWave(levels: waveLevels", surface)
        self.assertIn("let foreground = content", surface)
        self.assertLess(surface.index("let foreground = content"), surface.index(".background(alignment: .bottom)"))
        self.assertIn(".background { shape.glassEffect(.regular, in: shape) }", surface)
        self.assertIn(".frame(height: 100)", surface)
        self.assertIn(".clipShape(shape)", surface)
        self.assertIn("inputFieldOrWaveform", text)
        self.assertIn("inputBottomRow", text)
        composer = text.split("private func composerBody(field: PastableTextView", 1)[1].split(
            "private var composerResizeHandle", 1)[0]
        self.assertNotIn("ComposerRainbowWave", composer)
        self.assertNotIn("ComposerRainbowWave(opacity: 0.48)", composer)
        self.assertIn("Color.clear.frame(height: 32)", text)

    def test_particle_cloud_is_higher_and_denser_than_old_thin_strip(self):
        text = WAVE.read_text()
        self.assertIn("maxRise = min(size.height - 2, 54)", text)
        self.assertIn("let xStep: CGFloat = 2.35", text)
        self.assertIn("let yStep: CGFloat = 2.55", text)
        self.assertIn("let dot: CGFloat = 1.75", text)
        self.assertIn("for layer in 0..<2", text)
        self.assertIn("centerA = 0.43 + 0.19", text)
        self.assertIn("audioLift = Double(audio)", text)

    def test_text_and_both_voice_capture_modes_share_the_wave(self):
        text = CHAT.read_text()
        self.assertIn("if voiceInputActive { return voiceVM.waveformLevels }", text)
        self.assertIn("if speechManager.state == .recording { return speechManager.audioLevels }", text)
        self.assertIn("private func composerBody(field: PastableTextView", text)
        self.assertIn("let waveform = VStack(spacing: 6)", text)
        self.assertNotIn("ComposerRainbowWave(levels: speechManager.audioLevels", text)
        self.assertNotIn("ComposerRainbowWave(levels: voiceVM.waveformLevels", text)
        self.assertNotIn("AudioWaveformView(levels: speechManager.audioLevels)", text)

    def test_input_bindings_and_voice_mode_contract_remain_present(self):
        text = CHAT.read_text()
        self.assertIn("text: inputTextBinding", text)
        self.assertIn("onReturnKey: { [composerActions]", text)
        self.assertIn("private var voiceInputActive: Bool", text)
        self.assertIn("InlineVoiceInputView(", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
