#!/usr/bin/env python3
"""Source-contract tests for [T-115-volume-slider]: read-replies TTS volume.

Covers the working-tree capsule volume slider (cloud + System paths), the
shared UserDefaults key with the settings-page slider, and the
SpeechControlling.applySpeechVolume hook. Static checks only; no device /
config changes.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
PLAYER = (ROOT / 'src/ios/Providers/Voice/VoiceOutputPlayer.swift').read_text()
RESOLVER = (ROOT / 'src/ios/Providers/Voice/VoiceProviderResolver.swift').read_text()
CONTROL = (ROOT / 'src/ios/Views/Chat/Voice/SpeechPlayerControl.swift').read_text()
VM = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
SYS = (ROOT / 'src/ios/Providers/Voice/SystemVoiceCatalog.swift').read_text()
KEEPALIVE = (ROOT / 'src/ios/Agent/Background/BackgroundKeepAliveManager.swift').read_text()


class VolumeSliderSource(unittest.TestCase):
    """[T-115-volume-slider] Source-wiring contracts."""

    def test_unified_preference_clamped_and_persisted(self):
        self.assertIn('voice.output.volume', PLAYER)
        self.assertIn('min(max(v, 0), 1)', PLAYER)

    def test_cloud_player_applies_volume_real_time(self):
        # Current unit: setVolume applies immediately; new units pick it up in
        # pumpPlayback alongside rate.
        self.assertIn('func setVolume(_ volume: Float)', PLAYER)
        self.assertIn('player?.volume = min(max(volume, 0), 1)', PLAYER)
        self.assertIn('p.volume = VoiceOutputPreferences.volume', PLAYER)
        self.assertIn('p.enableRate = true', PLAYER)  # rate wiring stays intact

    def test_protocol_and_vm_hook(self):
        self.assertIn('func applySpeechVolume(_ volume: Float)', RESOLVER)
        self.assertIn('func applySpeechVolume(_ volume: Float) {', VM)
        self.assertIn('VoiceOutputPreferences.volume = clamped', VM)
        self.assertIn('SystemVoicePreferences.volume = clamped', VM)
        self.assertIn('min(max(volume, 0), 1)', VM)

    def test_capsule_slider_writes_both_paths(self):
        self.assertIn('@State private var volume: Float = VoiceOutputPreferences.volume', CONTROL)
        self.assertIn('Slider(value: $volume, in: 0...1)', CONTROL)
        self.assertIn('VoiceOutputPreferences.volume = newValue', CONTROL)
        self.assertIn('SystemVoicePreferences.volume = newValue', CONTROL)
        self.assertIn('VoiceOutputPlayer.shared.setVolume(newValue)', CONTROL)
        self.assertIn('applySpeechVolume(newValue)', CONTROL)

    def test_settings_page_and_capsule_share_one_key(self):
        # SystemVoicePreferences.volume reads/writes the SAME "speechVolume"
        # key as BackgroundKeepAliveManager.speechVolume (whose slider lives in
        # EnhancedBackgroundSettingsView) — one slider on either surface moves
        # the other, and the System TTS path reads it at utterance creation.
        self.assertIn('volumeKey = "speechVolume"', SYS)
        self.assertIn('"speechVolume"', KEEPALIVE)
        self.assertIn('utterance.volume = SystemVoicePreferences.volume',
                      (ROOT / 'src/ios/Providers/Voice/VoiceProvider+System.swift').read_text())

    def test_system_path_semantics_honest(self):
        # System TTS snapshots volume at utterance creation; the code must not
        # pretend mid-utterance real-time changes (the cloud path IS real-time,
        # via VoiceOutputPlayer.setVolume).
        self.assertIn('cannot change volume mid-utterance', RESOLVER)


if __name__ == '__main__':
    unittest.main(verbosity=2)