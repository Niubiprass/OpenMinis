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
        self.assertIn("private let colors: [Color]", text)
        self.assertIn("smoothNoise(position:", text)
        self.assertIn("private func latticeNoise(", text)
        self.assertIn("accessibilityReduceMotion", text)
        self.assertIn(".allowsHitTesting(false)", text)
        self.assertIn(".accessibilityHidden(true)", text)

    def test_text_and_both_voice_capture_modes_share_the_wave(self):
        text = CHAT.read_text()
        self.assertIn("ComposerRainbowWave(opacity: 0.32)", text)
        self.assertIn("ComposerRainbowWave(levels: voiceVM.waveformLevels, opacity: 0.28)", text)
        self.assertIn("ComposerRainbowWave(levels: speechManager.audioLevels, opacity: 0.34)", text)
        self.assertIn("private func composerBody(field: PastableTextView", text)
        self.assertIn("let waveform = VStack(spacing: 6)", text)
        self.assertNotIn("AudioWaveformView(levels: speechManager.audioLevels)", text)

    def test_input_bindings_and_voice_mode_contract_remain_present(self):
        text = CHAT.read_text()
        self.assertIn("text: inputTextBinding", text)
        self.assertIn("onReturnKey: { [composerActions]", text)
        self.assertIn("private var voiceInputActive: Bool", text)
        self.assertIn("InlineVoiceInputView(", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
