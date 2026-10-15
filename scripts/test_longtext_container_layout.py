#!/usr/bin/env python3
"""Source contracts only. Run LongTextContainerLayoutTests on iOS for TextKit proof."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/ios/Shared/NSTextContainerSetSizeGuard.m'


def code_only(text):
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)


class LongTextContainerSourceTests(unittest.TestCase):
    def setUp(self):
        self.code = code_only(SOURCE.read_text())

    def test_no_2000pt_probe_rewrite(self):
        self.assertNotIn('kProbeHeightFloor', self.code)
        self.assertNotIn('kProbeHeightCeiling', self.code)
        self.assertNotIn('gProbeHeightCount', self.code)
        # Review every write, not just the name of the deleted rule.
        writes = re.findall(r'newSize\.height\s*=(?!=)\s*([^;]+);', self.code)
        self.assertEqual(writes, ['kMaxContainerHeight'])
        self.assertRegex(self.code, r'kMaxContainerHeight\s*=\s*1e5\s*;')
        self.assertIn('if (newSize.height > kMaxContainerHeight)', self.code)

    def test_storm_and_invalid_geometry_defences_remain(self):
        for contract in ['kRepeatThreshold = 2', 'kStormForwardLimit = 40',
                         '!isfinite(newSize.height)', 'newSize.height < 0',
                         's->repeatCount >= kRepeatThreshold',
                         's->commitCount > kStormForwardLimit * 4',
                         'CGSizeEqualToSize(s->lastSize, newSize)',
                         'gOriginalSetSize)(self, _cmd, newSize)']:
            self.assertIn(contract, self.code)

    def test_fitting_does_not_add_historical_height_locks(self):
        markdown = code_only((ROOT / 'src/ios/Views/Chat/SelectableMarkdownView.swift').read_text())
        view = markdown.split('final class SelectableMarkdownTextView:', 1)[1]
        fitting = view.split('override func sizeThatFits(_ size: CGSize) -> CGSize {', 1)[1]
        fitting = fitting.split('override var intrinsicContentSize:', 1)[0]
        self.assertIn('textContainer.size.height = oldHeight', fitting)
        self.assertNotIn('lastComputedHeight', fitting)
        self.assertNotIn('max(fit.height', fitting)

    def test_runtime_cases_are_registered(self):
        tests = (ROOT / 'src/ios/MinisTests/LongTextContainerLayoutTests.swift').read_text()
        for case in ['testRealHeightsAreNotMistakenForProbes',
                     'testTextKitLaysOutTheWholeLongResponse',
                     'testLiveFittingGrowsPast2007AndFreshViewAgrees',
                     'testSameWidthClippedContainerFitsLikeFreshFullContainer']:
            self.assertIn('func ' + case, tests)
        project = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()
        self.assertIn('/* MinisTests */ = {isa = PBXFileSystemSynchronizedRootGroup;', project)
        self.assertNotIn('LongTextContainerLayoutTests.swift,', project)


if __name__ == '__main__':
    unittest.main(verbosity=2)
