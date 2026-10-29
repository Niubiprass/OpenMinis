#!/usr/bin/env python3
"""Regression contracts for the sent-file attachment preview fix.

The failure this pins down had two independent causes:
1. The old group preview handed `minis://` URLs straight to QuickLook,
   so even a successfully-presented sheet had no file to render.
2. Presentation state lived in each reusable UICollectionView cell, so a
   tap could be dropped or the sheet torn down with the cell.

It also preserves the user's requested behaviour: one composed message's
files share a pager, and text / markdown / HTML / audio keep their dedicated
reader rather than being flattened into QuickLook.

Wired into the iOS15 v64 Repair workflow so this path cannot regress unnoticed.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTBAR = (ROOT / 'src/ios/Views/Chat/ChatInputBar.swift').read_text()
PREVIEW = (ROOT / 'src/ios/Views/Chat/Media/FileAttachmentPreview.swift').read_text()
LIST = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
MEDIA = (ROOT / 'src/ios/Views/Chat/MinisMediaViews.swift').read_text()
AUDIO = (ROOT / 'src/ios/Views/Chat/Media/AudioPreview.swift').read_text()
PBX = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()


class AttachmentPreviewRegression(unittest.TestCase):
    def test_file_tile_no_longer_passes_internal_url_to_quicklook(self):
        self.assertIn('private func openFile(_ meta: AttachmentMeta)', INPUTBAR)
        self.assertIn('openFileAttachments(attachments, startingAt: meta.id)', INPUTBAR)
        self.assertNotIn('MultiFilePreview(urls:', INPUTBAR)
        self.assertNotIn('previewFiles', INPUTBAR)
        # The whole point of the fix: never put a minis:// NSURL in QL.
        self.assertIn('resolveMinisFileURL(url: ref.url, sessionId: sessionId)', PREVIEW)

    def test_paths_with_spaces_hash_and_percent_encode_once(self):
        self.assertIn('components.scheme = "minis"', PREVIEW)
        self.assertIn('components.path = "/" + String(pieces[1])', PREVIEW)
        # Image gallery keeps its existing URL path; the sent-FILE path must
        # not build a URL from an unescaped path any more.
        files = INPUTBAR[INPUTBAR.index('private func openFile('):INPUTBAR.index('private func fileIconName(')]
        self.assertNotIn('URL(string: meta.minisURL)', files)

    def test_presentation_is_outside_reusable_cells(self):
        self.assertIn('fileprivate let fileAttachmentPresenter = FileAttachmentPresenter()', LIST)
        self.assertIn('filePresenter: fileAttachmentPresenter', LIST)
        self.assertIn('.sheet(item: $filePresenter.sheet)', LIST)
        self.assertNotIn('.sheet(isPresented: $showFilePreview)', INPUTBAR)

    def test_cells_receive_the_action_explicitly(self):
        # UIHostingConfiguration starts an independent environment; the action
        # must be injected at the whole-message hosting config.
        self.assertIn('.environment(\\.openFileAttachments, OpenFileAttachmentsAction', LIST)
        self.assertIn('.environment(\\.openMinisURL, OpenMinisURLAction', LIST)

    def test_owner_session_is_explicit_and_never_guessed(self):
        self.assertIn('sessionId == ownerSessionId', PREVIEW)
        self.assertIn('guard let sessionId, !sessionId.isEmpty', PREVIEW)
        self.assertIn('coord.bindFileAttachmentSession(vm.sessionId)', LIST)
        self.assertIn('context.coordinator.bindFileAttachmentSession(vm.sessionId)', LIST)

    def test_selection_is_an_id_not_a_silent_first_page(self):
        self.assertIn('startingAt selectedID: UUID', PREVIEW)
        self.assertIn('items.contains(where: { $0.id == selectedID })', PREVIEW)
        self.assertIn('resolved.contains(where: { $0.id == selectedID })', PREVIEW)
        self.assertNotIn('?? 0\n            previewFiles', INPUTBAR)

    def test_unsupported_files_still_swipe(self):
        # A message with two .deb files must page between them; the old
        # planner dropped every .share item and presented the share sheet
        # for the tapped one, so the pager never appeared.
        self.assertIn('Unsupported formats join the pager as a share-only page', PREVIEW)
        self.assertIn('let items = resolved', PREVIEW)
        self.assertIn('if items.count == 1, !canPreview(items[0])', PREVIEW)
        self.assertNotIn('let items = resolved.filter { canPreview($0) }', PREVIEW)

    def test_each_format_keeps_its_reader(self):
        for ext in ('minisMarkdownExtensions', 'minisTextExtensions',
                    'minisHTMLExtensions', 'minisAudioExtensions',
                    'minisDocumentExtensions'):
            self.assertIn(ext, PREVIEW)
        self.assertIn('MinisTextPreviewView(fileURL: item.localURL, onClose: onClose)', PREVIEW)
        self.assertIn('MinisMarkdownPreviewView(fileURL: item.localURL, onClose: onClose)', PREVIEW)
        self.assertIn('MinisHTMLPreviewView(fileURL: item.localURL', PREVIEW)
        self.assertIn('MinisAudioPreviewView(fileURL: item.localURL, onClose: onClose)', PREVIEW)
        self.assertIn('QLPreviewController.canPreview', PREVIEW)
        # One pager over a message's files, in original order.
        self.assertIn('TabView(selection: $selectedID)', PREVIEW)

    def test_readers_close_the_group_not_the_host(self):
        self.assertIn('var onClose: (() -> Void)? = nil', MEDIA)
        self.assertIn('var onClose: (() -> Void)? = nil', AUDIO)
        self.assertIn('if let onClose { onClose() } else { dismiss() }', MEDIA)
        self.assertIn('FileAttachmentGroupPreview(group: group, onClose: dismissFilePreview)', LIST)

    def test_unavailable_file_is_not_a_silent_blank_sheet(self):
        self.assertIn('@Published var unavailableName: String?', PREVIEW)
        self.assertIn('self.unavailableName = tappedName', PREVIEW)
        self.assertIn('AppLocalized("File Not Found")', LIST)
        self.assertIn('Preview unavailable', PREVIEW)

    def test_sent_video_opens_the_player_not_the_share_sheet(self):
        # 2026-10-30: tapping a sent .mp4/.mov produced the iOS share sheet.
        # The URL router had no video branch, so mp4 fell through to `.share`.
        self.assertIn('minisVideoExtensions.contains(ext)', LIST)
        self.assertIn('fileAttachmentPresenter.openVideo(file)', LIST)
        self.assertIn('@Published var videoSheet: FileAttachmentVideoPresentation?', PREVIEW)
        self.assertIn('.fullScreenCover(item: $filePresenter.videoSheet) { video in', LIST)
        self.assertIn('MinisVideoFullscreenPlayer(fileURL: video.url)', LIST)
        # The tile must build its URL with the escaping encoder, not URL(string:).
        self.assertIn('FileAttachmentResourceURL.make(path: meta.path) { openURL(url) }', MEDIA)
        self.assertNotIn('URL(string: meta.minisURL) { openURL(url) }', MEDIA)

    def test_tool_sheet_wrapper_survives_the_file_sheet_insert(self):
        # The 153fb09 run failed at `swiftc -parse` because the new file
        # sheet replaced the opening line of the existing tool sheet.
        self.assertIn('.sheet(item: $toolPresenter.sheetData) { data in', LIST)
        self.assertIn('.sheet(item: $filePresenter.sheet) { sheet in', LIST)

    def test_open_minis_environment_uses_weak_self(self):
        # The 5fc10db run failed because the second closure captured `self`
        # strongly, making `self?` illegal on a non-optional Coordinator.
        self.assertIn('.environment(\\.openMinisURL, OpenMinisURLAction { [weak self] url in', LIST)

    def test_new_source_is_registered_in_the_app_target(self):
        self.assertIn('FileAttachmentPreview.swift in Sources', PBX)
        self.assertIn('FileAttachmentPreview.swift */', PBX)


if __name__ == '__main__':
    unittest.main(verbosity=2)
