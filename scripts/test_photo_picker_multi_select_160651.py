#!/usr/bin/env python3
"""Regression contracts for large PHPicker multi-selects.

Verifies the exact behavior the user demanded and the fix for the hang:
- one picker confirmation = ALL selected photos start loading at once and stay
  in the same outgoing message (NO two-at-a-time sequential batching)
- every load has a 30s watchdog: attempt 1 auto-retries once, attempt 2 marks
  the chip failed instead of hanging the send button forever
- failed chips are tappable to retry in place (provider retained in the VM)
- images load via file representation first (bounded memory), Data/UIImage
  only as fallbacks
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
ATTACHMENTS = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+Attachments.swift').read_text()
INPUTBAR = (ROOT / 'src/ios/Views/Chat/ChatInputBar.swift').read_text()


class PhotoPickerMultiSelect(unittest.TestCase):
    def test_picker_keeps_unlimited_selection(self):
        self.assertIn('config.selectionLimit = 0', CHAT)

    def test_all_selected_items_start_together_no_batching(self):
        # One picker confirmation + one loop that starts every job at once.
        self.assertIn('for job in jobs {\n            startPhotoLoad(job, attempt: 1)', CHAT)
        # No sequential two-at-a-time gating anywhere.
        self.assertNotIn('stride(from: 0, to: jobs.count, by: 2)', CHAT)

    def test_watchdog_bounds_every_load(self):
        self.assertIn('await Task.sleep(nanoseconds: 30_000_000_000)', CHAT)
        self.assertIn('if attempt == 1 {\n                AppLogger(category: "PhotoPicker").error("load timeout(30s) attempt1', CHAT)
        self.assertIn('vm.markPlaceholderFailed(id: job.id)', CHAT)

    def test_failed_chip_retries_in_place(self):
        self.assertIn('func retryPhotoLoad(id: UUID) {', CHAT)
        self.assertIn('vm.setAttachmentLoading(id: id)', CHAT)
        self.assertIn('func pendingPhotoProvider(for id: UUID)', ATTACHMENTS)
        self.assertIn('Text("重试")', INPUTBAR)
        self.assertIn('Button {\n                onRetry?()', INPUTBAR)

    def test_remove_prunes_retained_provider(self):
        self.assertIn('pendingPhotoProviders.removeValue(forKey: attachment.id)', ATTACHMENTS)

    def test_images_copy_file_representation_not_full_data(self):
        self.assertIn('provider.loadFileRepresentation(forTypeIdentifier: UTType.image.identifier)', CHAT)
        self.assertIn('vm.finalizeImagePlaceholder(id: job.id, from: tmp)', CHAT)
        self.assertIn('func finalizeImagePlaceholder(id: UUID, from sourceURL: URL)', ATTACHMENTS)

    def test_ready_placeholders_are_written_to_cache(self):
        self.assertIn('func finalizeImagePlaceholder(id: UUID, data: Data', ATTACHMENTS)
        self.assertIn('attachments[index].loadState = .ready', ATTACHMENTS)


if __name__ == '__main__':
    unittest.main(verbosity=2)