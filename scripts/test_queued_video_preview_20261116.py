#!/usr/bin/env python3
"""Real queued-cell video contracts + actual Swift source with platform mocks.
No Python handoff simulation. --require-native fails closed without macOS Swift.
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REQUIRE_NATIVE = '--require-native' in sys.argv or os.environ.get('V64R_REQUIRE_SWIFT') == '1'
if '--require-native' in sys.argv:
    sys.argv.remove('--require-native')
ROOT = Path(__file__).resolve().parent.parent
BAR = (ROOT / 'src/ios/Views/Chat/ChatInputBar.swift').read_text()
ROW = (ROOT / 'src/ios/Views/Chat/ChatMessageViews.swift').read_text()
LIST = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
PREVIEW = (ROOT / 'src/ios/Views/Chat/Media/FileAttachmentPreview.swift').read_text()
MODELS = (ROOT / 'src/ios/Agent/Chat/ChatModels.swift').read_text()


def braced(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
        end += 1
    return source[start:end]


class QueuedVideoContracts(unittest.TestCase):
    def test_actual_queued_branch_is_button_to_explicit_bridge(self):
        queued = braced(BAR, 'struct QueuedAttachmentPreview: View')
        video = queued.split('case .video:', 1)[1].split('case .document:', 1)[0]
        for token in ('Button {', 'onOpenVideo(attachment)', 'Image(systemName: "play.fill")',
                      '.buttonStyle(.plain)', 'attachment.loadState == .ready',
                      'attachment.cacheURL.isFileURL', '.disabled('):
            self.assertIn(token, video)
        self.assertIn('let onOpenVideo: (InputAttachment) -> Bool', queued)
        self.assertNotIn('.sheet(', queued)
        self.assertNotIn('.fullScreenCover(', queued)
        self.assertIn('@Environment(\\.openQueuedVideo)', ROW)
        self.assertIn('QueuedAttachmentPreview(attachments: message.inputAttachments, onOpenVideo:', ROW)
        self.assertIn('openQueuedVideo(attachment, messageID: message.id)', ROW)
        self.assertIn('.environment(\\.openQueuedVideo, OpenQueuedVideoAction', LIST)
        self.assertIn('[weak self, sessionId = vm.sessionId]', LIST)

    def test_bridge_checks_live_queue_and_owning_session(self):
        bridge = braced(LIST, 'func openQueuedVideo(')
        for token in ('sessionId == vm.sessionId', '$0.id == messageID', 'message.isQueued',
                      '$0.id == attachment.id', 'current.loadState == .ready',
                      'current.cacheURL == attachment.cacheURL',
                      'fileAttachmentPresenter.openQueuedVideo(current, sessionId: sessionId)'):
            self.assertIn(token, bridge)
        self.assertNotIn('activeSessionId', bridge)
        self.assertNotIn('onWithdraw', bridge)

    def test_retention_is_bounded_offmain_and_cancellable(self):
        source = braced(PREVIEW, 'final class QueuedVideoPreviewSource:')
        for token in ('O_NONBLOCK', 'O_NOFOLLOW', 'fstat(', 'S_IFREG', 'metadata.st_size > 0',
                      'metadata.st_size <= Self.maximumBytes', 'read(upToCount: count)',
                      'while remaining > 0', 'isCancelled()', 'QueuedVideoPreviewLease('):
            self.assertIn(token, source)
        self.assertNotIn('readToEnd()', source)
        self.assertNotIn('linkItem', source)
        request = braced(PREVIEW, 'func openQueuedVideo(')
        self.assertIn('Task.detached(priority: .userInitiated)', request)
        self.assertIn('source.retainCopy(isCancelled: { Task.isCancelled })', request)
        self.assertIn('self.requestToken == token', request)
        self.assertIn('self.ownerSessionId == sessionId', request)
        self.assertIn('self.openVideo(lease.url, queuedLease: lease)', request)
        reset = braced(PREVIEW, 'func reset()')
        self.assertIn('queuedVideoCopyTask?.cancel()', reset)
        self.assertIn('requestToken = UUID()', reset)
        self.assertIn('dismantleUIViewController', LIST)
        self.assertIn('fileAttachmentPresenter.reset()\n            vm = newVM', LIST)

    def test_lease_lives_through_stable_player_teardown(self):
        self.assertIn('let queuedLease: QueuedVideoPreviewLease?', PREVIEW)
        self.assertIn('DispatchQueue.global(qos: .utility).async', PREVIEW)
        self.assertIn('.fullScreenCover(item: $filePresenter.videoSheet) { video in', LIST)
        self.assertIn('MinisVideoFullscreenPlayer(fileURL: video.url)', LIST)
        self.assertIn('withExtendedLifetime(video.queuedLease)', LIST)
        self.assertIn('filePresenter.queuedVideoDidDisappear(id: video.id)', LIST)
        close = braced(PREVIEW, 'func queuedVideoDidDisappear(')
        self.assertIn('guard videoSheet?.id == id else { return }', close)

    def test_preview_never_mutates_queue_or_logs_private_data(self):
        request = braced(PREVIEW, 'func openQueuedVideo(')
        for token in ('sendMessage(', 'withdraw', 'removeItem(', 'markRead(', 'activeSessionId'):
            self.assertNotIn(token, request)
        queued_logs = [line.strip() for line in PREVIEW.splitlines() + LIST.splitlines()
                       if '.info("[QueuedVideoPreview]' in line]
        self.assertGreaterEqual(len(queued_logs), 6)
        for line in queued_logs:
            self.assertNotIn('\\(', line)
            self.assertRegex(line, r'\.info\("\[QueuedVideoPreview\] stage=[a-z-]+"\)')
        # Do not weaken the prior composer predicates to make the queue pass.
        self.assertIn('onOpenVideo?(attachment.cacheURL)', BAR)
        self.assertIn('var onOpenVideo: ((URL) -> Void)?', BAR)
        self.assertIn('placeholderTile(icon: "doc.fill", fileName: attachment.fileName)', BAR)
        self.assertIn('openGallery(startingAt: attachment)', BAR)

    def test_fixture_targets_production_classes_and_races(self):
        fixture = (ROOT / 'scripts/fixtures/queued_video_preview_20261116.swift').read_text()
        for token in ('source.retainCopy(', 'bridge.openQueuedVideo(', 'presenter.openQueuedVideo(',
                      'presenter.bind(to:', 'stage=discarded', 'weak var coverLease',
                      'manager.removeItem(at: original)', 'mkfifo(', 'maximumBytes + 1'):
            self.assertIn(token, fixture)
        for declaration in ('class FileAttachmentPresenter', 'class QueuedVideoPreviewSource',
                            'class QueuedVideoPreviewLease', 'func openQueuedVideo('):
            self.assertNotIn(declaration, fixture)
        retained = PREVIEW.split('// MARK: - Queued video retained source', 1)[1].split('\n', 1)[1].split('// MARK: - End queued video retained source', 1)[0]
        self.assertTrue(retained.lstrip().startswith('/// Independent copy'))
        for name in ('final class QueuedVideoPreviewLease:', 'final class QueuedVideoPreviewSource:'):
            self.assertIn(braced(PREVIEW, name), retained)
        self.assertIn('func openQueuedVideo(', braced(LIST, 'func openQueuedVideo('))

    def test_native_production_handoff_and_lease(self):
        compiler = shutil.which('swiftc')
        if not compiler or platform.system() != 'Darwin':
            message = 'native SKIP: iSH/no macOS Swift; actual Swift fixture NOT executed'
            if REQUIRE_NATIVE:
                self.fail(message + ' (--require-native fails closed)')
            self.skipTest(message)
        compiler = subprocess.check_output(['xcrun', '--find', 'swiftc'], text=True, timeout=30).strip()
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True, timeout=30).strip()
        self.assertTrue(Path(sdk).is_dir(), 'Native macOS SDK unavailable')
        fixture = (ROOT / 'scripts/fixtures/queued_video_preview_20261116.swift').read_text()
        mocks, cases = fixture.split('// MARK: - Native cases', 1)
        retained = PREVIEW.split('// MARK: - Queued video retained source', 1)[1].split('\n', 1)[1].split('// MARK: - End queued video retained source', 1)[0]
        planning = PREVIEW[PREVIEW.index('enum FileAttachmentResourceURL'):PREVIEW.index('// MARK: - Stable overlay presentation')]
        presenter = PREVIEW[PREVIEW.index('enum FileAttachmentSheet'):PREVIEW.index('// MARK: - Mixed-format pager')]
        model = braced(MODELS, 'struct InputAttachment:')
        bridge = braced(LIST, 'func openQueuedVideo(')
        wrapper = '\n@MainActor final class NativeQueueBridge {\nvar vm: MockVM?\nlet fileAttachmentPresenter: FileAttachmentPresenter\ninit(vm: MockVM, presenter: FileAttachmentPresenter) { self.vm = vm; fileAttachmentPresenter = presenter }\n@discardableResult\n' + bridge + '\n}\n'
        production = mocks + model + retained + planning + presenter + wrapper + cases
        with tempfile.TemporaryDirectory(prefix='queued-video-native-') as directory:
            swift = Path(directory) / 'main.swift'
            binary = Path(directory) / 'fixture'
            swift.write_text(production)
            compiled = subprocess.run([compiler, '-sdk', sdk, '-swift-version', '5', '-parse-as-library',
                                       str(swift), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('PASS native production queued-video handoff/session/cancel/drain/lease', ran.stdout)
            print(ran.stdout.strip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
