#!/usr/bin/env python3
"""Production Swift extraction + source contracts; NOT UIKit/runtime proof.

V64R_REQUIRE_SWIFT=1 requires executable Swift (CI must fail closed).
The Foundation shim exercises real fitting/intrinsic/key-reset methods, not a
Python reimplementation. UITextView/TextKit remain deliberately simplified.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEXT = ROOT / 'src/ios/Views/Chat/SelectableMarkdownView.swift'


def extract_member(source, marker):
    """Brace match while ignoring Swift comments/string literals."""
    start = source.index(marker)
    opening = source.index('{', start)
    i, depth, state = opening, 0, 'code'
    while i < len(source):
        pair, char = source[i:i+2], source[i]
        if state == 'line':
            if char == '\n':
                state = 'code'
        elif state == 'block':
            if pair == '*/':
                state = 'code'
                i += 1
        elif state == 'string':
            if char == '\\':
                i += 1
            elif char == '"':
                state = 'code'
        elif pair == '//':
            state = 'line'
            i += 1
        elif pair == '/*':
            state = 'block'
            i += 1
        elif char == '"':
            state = 'string'
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:i+1]
        i += 1
    raise AssertionError('unterminated Swift member: ' + marker)


def code_only(source):
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)


class StabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEXT.read_text()
        cls.view = cls.source.split('final class SelectableMarkdownTextView:', 1)[1]
        cls.fit = extract_member(cls.view, 'override func sizeThatFits(_ size: CGSize) -> CGSize')
        cls.intrinsic = extract_member(cls.view, 'override var intrinsicContentSize: CGSize')
        cls.keys = extract_member(cls.view, 'fileprivate func invalidateTextMeasurementKeys()')

    def test_probe_restores_both_axes_including_empty(self):
        fit = code_only(self.fit)
        self.assertIn('textContainer.size.width = oldWidth', fit)
        self.assertIn('textContainer.size.height = oldHeight', fit)
        self.assertLess(fit.index('defer {'), fit.index('guard textStorage.length > 0'))
        self.assertIn('if textContainer.size.width != oldWidth', fit)
        self.assertIn('if textContainer.size.height != oldHeight', fit)
        for forbidden in ('frame =', 'bounds =', 'layoutIfNeeded(',
                          'lastComputedHeight', 'max(fit.height'):
            self.assertNotIn(forbidden, fit)
        self.assertIn('height: ceil(fit.height)', self.intrinsic)
        self.assertIn('width: UIView.noIntrinsicMetric', self.intrinsic)

    def test_layout_only_reinvalidates_changed_geometry_demand(self):
        layout = extract_member(self.view, 'override func layoutSubviews()')
        self.assertIn('let needsIntrinsicUpdate = _widthChanged || _ios15WRegrabbed', layout)
        self.assertIn('|| abs(ios15LastNeededH - _needH) > 0.5', layout)
        self.assertIn('if needsIntrinsicUpdate {\n                    invalidateIntrinsicContentSize()', layout)
        update = extract_member(self.source, 'func updateUIView(_ textView: SelectableMarkdownTextView, context: Context)')
        self.assertIn('textView.invalidateIntrinsicContentSize()', update)
        self.assertIn('textView.invalidateCellSizeIfNeeded()', update)

    def test_storage_commit_drops_length_only_keys(self):
        update = extract_member(self.source, 'func updateUIView(_ textView: SelectableMarkdownTextView, context: Context)')
        reset = update.index('textView.invalidateTextMeasurementKeys()')
        self.assertGreater(reset, update.index('oldStorage.endEditing()'))
        self.assertGreater(reset, update.index('textView.attributedText = attributed'))
        self.assertLess(reset, update.rindex('textView.invalidateIntrinsicContentSize()'))
        for key in ('lastSizedStorageLen = -1', 'ios15LatchedNeedH = 0',
                    'coord.cachedSizes.removeAll(keepingCapacity: true)',
                    'coord.cachedSizeMarkdownCount = -1'):
            self.assertIn(key, self.keys)
        self.assertNotIn('lastComputedHeight =', self.keys)
        self.assertNotIn('deferredCorrectionPending =', self.keys)

    def test_short_text_and_fade_prefix_contracts_preserved(self):
        for route in ('if finalizedSTF, pending.length <= 8000,',
                      'if finalizedCommitted, liveStorage.length <= 8000,',
                      'let inset = uiView.textContainerInset.top + uiView.textContainerInset.bottom',
                      'Self.prefixesEqualIgnoringFontSubstitution(newPrefix, _oldPrefix)',
                      # [T-stream-fade-ios15] 淡入不再按系统版本分叉：iOS 15
                      # 也要逐字淡入，这里守住「排动画」这一步本身。
                      'if let revealRange = fadeRevealRange,'):
            self.assertIn(route, self.source)
        infrastructure = (ROOT / 'src/ios/Agent/MessageList/MessageListInfrastructure.swift').read_text()
        self.assertIn('height: UIView.layoutFittingCompressedSize.height', infrastructure)
        self.assertIn('verticalFittingPriority: .fittingSizeLevel', infrastructure)
        self.assertNotIn('height: attrs.size.height)', infrastructure)

    def test_production_swift_methods_against_foundation_shim(self):
        swift = shutil.which('swift')
        required = os.environ.get('V64R_REQUIRE_SWIFT') == '1'
        if not swift:
            if required:
                self.fail('V64R_REQUIRE_SWIFT=1 but swift executable is unavailable')
            self.skipTest('Swift unavailable; source checks only, NOT UIKit validation')
        # Use the production condition as Swift too, so condition regressions
        # cannot pass by leaving a separately handwritten Python oracle intact.
        condition = re.search(r'let needsIntrinsicUpdate = (.*?)\n            ios15LastNeededH =',
                              self.view, re.S)
        self.assertIsNotNone(condition)
        program = SHIM + '\nfinal class ProductionTextView: UITextView {\n' + '\n'.join((
            'var lastSizedStorageLen = 12\nvar ios15LatchedNeedH: CGFloat = 80\nvar lastComputedHeight: CGFloat = 80',
            self.fit, self.intrinsic, self.keys)) + '\n}\n'
        program += '\nfunc demandChanged(_ old: CGFloat, _ new: CGFloat, _ width: Bool, _ regrab: Bool) -> Bool {\n'
        program += 'let ios15LastNeededH = old, _needH = new\nlet _widthChanged = width, _ios15WRegrabbed = regrab\n'
        program += 'return ' + condition.group(1) + '\n}\n' + CASES
        with tempfile.TemporaryDirectory(prefix='minis-text-stability-') as directory:
            path = Path(directory) / 'ProductionTextMeasure.swift'
            path.write_text(program)
            result = subprocess.run([swift, str(path)], text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('production Swift shim checks: PASS', result.stdout)
        print(result.stdout.strip())


SHIM = r'''
import Foundation
import CoreGraphics
class UIView {
    static let noIntrinsicMetric: CGFloat = -1
    var bounds = CGRect(x: 0, y: 0, width: 358, height: 120)
}
final class UIScreen {
    static let main = UIScreen()
    let bounds = CGRect(x: 0, y: 0, width: 390, height: 844)
}
final class ProbeContainer {
    var writes = 0
    var size = CGSize(width: 358, height: 120) { didSet { writes += 1 } }
}
final class ProbeStorage {
    var length = 100
    var explicitLines = 0
    var lineHeight: CGFloat = 20
}
class SelectableMarkdownView {
    class Coordinator {
        var cachedSizes: [Int: CGFloat] = [358: 80]
        var cachedSizeMarkdownCount = 12
    }
}
class UITextView: UIView {
    let textContainer = ProbeContainer()
    let textStorage = ProbeStorage()
    var delegate: AnyObject?
    // A deliberately simple line model. Test isolation/production control flow,
    // not Apple's glyph metrics. Simulate super mutating even an empty probe.
    var clampInSuper = true
    var superWidthDrift: CGFloat = 0
    func sizeThatFits(_ size: CGSize) -> CGSize {
        let columns = max(1, Int(size.width / 10))
        let lines = max(1, Int(ceil(Double(textStorage.length) / Double(columns)))) + textStorage.explicitLines
        let height = CGFloat(lines) * textStorage.lineHeight + 8
        if clampInSuper {
            textContainer.size = CGSize(width: size.width + superWidthDrift, height: height)
        }
        return CGSize(width: size.width, height: height)
    }
    var intrinsicContentSize: CGSize { .zero }
}
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    precondition(condition(), message)
}
'''

CASES = r'''
let view = ProductionTextView()
let original = view.textContainer.size
let expected = view.intrinsicContentSize.height
for width: CGFloat in [390, 358, 390, 358, 744, 358] {
    let result = view.sizeThatFits(CGSize(width: width, height: 1))
    check(result.width == width, "probe must answer the proposed sane width")
    check(view.textContainer.size == original, "probe polluted live container geometry")
    check(view.intrinsicContentSize.height == expected, "probe changed later intrinsic height")
    check(view.intrinsicContentSize.width == UIView.noIntrinsicMetric, "ideal width leaked")
}
for priorHeight: CGFloat in [120, 280, 480, 120] {
    view.textContainer.size = CGSize(width: 358, height: priorHeight)
    check(view.sizeThatFits(CGSize(width: 358, height: 1)).height == expected,
          "old visible/parent height contaminated natural fit")
    check(view.textContainer.size.height == priorHeight, "old clipped height was not restored")
}
view.textStorage.length = 0
view.superWidthDrift = 0.25
let emptyGeometry = view.textContainer.size
_ = view.sizeThatFits(CGSize(width: 390, height: 4))
check(view.textContainer.size == emptyGeometry, "empty-text probe failed defer restoration")
view.textStorage.length = 100
view.superWidthDrift = 0
view.clampInSuper = false
view.textContainer.writes = 0
_ = view.sizeThatFits(CGSize(width: 358, height: 1))
check(view.textContainer.writes == 0, "same-value restoration dirtied TextKit")

// Real content demand changes must still grow AND shrink; no high-water lock.
view.textStorage.length = 300
let grown = view.intrinsicContentSize.height
check(grown > expected, "streaming append did not grow")
view.textStorage.length = 100
check(view.intrinsicContentSize.height == expected, "short rewrite could not shrink")
view.textStorage.explicitLines = 2
let newlineHeight = view.intrinsicContentSize.height
check(newlineHeight > expected, "newlines did not affect demand")
view.textStorage.explicitLines = 0
view.textStorage.lineHeight = 30
check(view.intrinsicContentSize.height > expected, "font/style demand change lost")
view.textStorage.lineHeight = 20

let coordinator = SelectableMarkdownView.Coordinator()
view.delegate = coordinator
view.invalidateTextMeasurementKeys()
check(view.lastSizedStorageLen == -1, "equal-length storage generation not invalidated")
check(view.ios15LatchedNeedH == 0, "attribute-only change left latch alive")
check(coordinator.cachedSizes.isEmpty && coordinator.cachedSizeMarkdownCount == -1,
      "short-text cached result survived new committed generation")
check(view.lastComputedHeight == 80, "reset must preserve delta accounting, not zero/floor height")

check(!demandChanged(80, 80, false, false), "stable layout invalidated intrinsic again")
check(!demandChanged(80, 80.25, false, false), "subpixel demand noise invalidated intrinsic")
check(demandChanged(80, 81, false, false), "growth demand not invalidated")
check(demandChanged(80, 79, false, false), "shrink demand not invalidated")
check(demandChanged(80, 80, true, false), "width/inset/border geometry transition missed")
check(demandChanged(80, 80, false, true), "regrabbed render width not invalidated")
print("production Swift shim checks: PASS (not UIKit/TextKit validation)")
'''

if __name__ == '__main__':
    unittest.main(verbosity=2)
