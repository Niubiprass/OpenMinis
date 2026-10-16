#!/usr/bin/env python3
"""160650: production Swift extraction plus source contracts, NOT device proof.

CI executes the real policy, traversal and height accessor against a small UIKit
shim. Only #available's platform predicate is substituted to exercise iOS15 on
macOS. Apple TextKit/SwiftUI behavior must still be tested on the device.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_text_measure_stability import extract_member, code_only

ROOT = Path(__file__).resolve().parents[1]
CELL = (ROOT / 'src/ios/Agent/MessageList/MessageListInfrastructure.swift').read_text()
TEXT = (ROOT / 'src/ios/Views/Chat/SelectableMarkdownView.swift').read_text()
POLICY = extract_member(CELL, 'struct CurrentTextKitHeightSlice') + '\n' + extract_member(CELL, 'enum CurrentTextKitHeightFloor')
COLLECT = extract_member(CELL, 'private func currentTextKitSlices()')
ACCESS = extract_member(TEXT, 'func currentCellTextKitHeight(for width: CGFloat)')


class CurrentHeightTests(unittest.TestCase):
    def test_lifetime_pin_is_not_current_measurement_set_on_ios15(self):
        repair = CELL[CELL.index('// [160650]'):CELL.index('// [160645] Reconciliation')]
        self.assertIn('if #available(iOS 16.0, *)', repair)
        ios15 = repair.split('} else {', 1)[1]
        self.assertNotIn('hostingSubtree', ios15)
        self.assertNotIn('lastComputedHeight', ios15)
        self.assertIn('CurrentTextKitHeightFloor.resolve(currentText.slices)', ios15)
        self.assertGreater(CELL.index('let currentText = currentTextKitSlices()'),
                           CELL.index('self.contentView.systemLayoutSizeFitting('))
        self.assertIn('tkCount=', CELL)
        self.assertIn('tkRejected=', CELL)

    def test_current_content_width_visibility_and_owner_guards(self):
        for guard in ('!view.isHidden', 'view.alpha > 0.01',
                      'view.window === self.window',
                      'view.isDescendant(of: self.contentView)',
                      'seen.insert(ObjectIdentifier(text))',
                      'text.currentCellTextKitHeight(for: width)',
                      'if let scroll = view as? UIScrollView, scroll.isScrollEnabled'):
            self.assertIn(guard, COLLECT)
        for guard in ('ios15LatchLen == textStorage.length',
                      'abs(ios15LatchW - width) <= 0.5',
                      'abs((ios15LastRenderContentW ?? -1) - width) <= 0.5',
                      'ios15LatchHash == textStorage.mutableString.hash',
                      'return ios15LatchedNeedH'):
            self.assertIn(guard, ACCESS)
        for forbidden in ('sizeThatFits(', 'layoutIfNeeded(', 'invalidateLayout(',
                          'invalidateIntrinsicContentSize('):
            self.assertNotIn(forbidden, code_only(ACCESS + COLLECT))
        self.assertIn('if let previousEnd = end, slice.top < previousEnd - 0.5', POLICY)
        self.assertNotIn('max(', code_only(POLICY))

    def test_real_swift_policy_accessor_and_tree_walk(self):
        swift = shutil.which('swift')
        if not swift:
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('CI requires real Swift execution, but swift is missing')
            self.skipTest('no Swift in iSH; native CI execution required')
        self.assertEqual(ACCESS.count('if #available(iOS 16.0, *)'), 1)
        accessor = ACCESS.replace('if #available(iOS 16.0, *)', 'if simulatedModernOS')
        program = SHIM + '\n' + POLICY + '\nfinal class SelectableMarkdownTextView: UIScrollView {\n' + FIELDS + accessor + '\n}\n'
        program += 'final class Cell {\nlet contentView: UIView\nlet window: UIWindow?\ninit(_ window: UIWindow) { self.window = window; contentView = UIView(); contentView.window = window }\n'
        program += COLLECT + '\nfunc snapshot() -> [CurrentTextKitHeightSlice] { currentTextKitSlices().slices }\n}\n' + CASES
        with tempfile.TemporaryDirectory(prefix='minis-current-tk-') as tmp:
            path = Path(tmp) / 'CurrentTextKit.swift'
            path.write_text(program)
            result = subprocess.run([swift, str(path)], capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('production current TextKit Swift: PASS', result.stdout)
        print(result.stdout.strip())


SHIM = r'''
import Foundation
import CoreGraphics
final class UIWindow {}
struct Insets { var left: CGFloat = 0; var right: CGFloat = 0 }
class UIView {
    var isHidden = false
    var alpha: CGFloat = 1
    var window: UIWindow?
    weak var superview: UIView?
    var subviews: [UIView] = []
    var bounds = CGRect(x: 0, y: 0, width: 358, height: 744)
    var top: CGFloat = 0
    func add(_ child: UIView) {
        child.superview?.subviews.removeAll { $0 === child }
        child.superview = self; child.window = window; subviews.append(child)
    }
    func isDescendant(of parent: UIView) -> Bool {
        var current: UIView? = self
        while let view = current { if view === parent { return true }; current = view.superview }
        return false
    }
    func convert(_ rect: CGRect, to parent: UIView) -> CGRect {
        var result = rect
        var current: UIView? = self
        while let view = current, view !== parent { result.origin.y += view.top; current = view.superview }
        return result
    }
}
class UIScrollView: UIView { var isScrollEnabled = false }
final class Storage {
    var mutableString: NSMutableString = NSMutableString(string: "current text")
    var length: Int { mutableString.length }
}
func check(_ value: @autoclosure () -> Bool, _ message: String) { precondition(value(), message) }
'''
FIELDS = r'''
var simulatedModernOS = false
let textStorage = Storage()
var textContainerInset = Insets()
var lastComputedHeight: CGFloat = 1215
var ios15LatchedNeedH: CGFloat = 744
var ios15LatchLen = 0
var ios15LatchW: CGFloat = 358
var ios15LastRenderContentW: CGFloat? = 358
var ios15LatchHash = 0
func stamp() { ios15LatchLen = textStorage.length; ios15LatchHash = textStorage.mutableString.hash }
'''
CASES = r'''
let window = UIWindow()
let cell = Cell(window)
let live = SelectableMarkdownTextView()
live.stamp()
cell.contentView.add(live)
check(live.currentCellTextKitHeight(for: 358) == 744, "stale per-view height 1215 leaked instead of current rendered 744")
let pinnedOldView = SelectableMarkdownTextView()
pinnedOldView.stamp()
pinnedOldView.ios15LatchedNeedH = 471
pinnedOldView.window = window
// Retained by a prior lifetime-pin snapshot, but NOT in the current cell.
let oldPin = [live, pinnedOldView]
for _ in 0..<312 {
    let floor = CurrentTextKitHeightFloor.resolve(cell.snapshot())
    check(floor == 744, "session-return measurement oscillated toward retained old view")
    check(max(748, floor ?? 0) == 748, "748/1215 device bounce reproduced")
}
check(oldPin.count == 2, "lifetime pin should stay alive without being measured")

// Nested markdown is an attachment of its parent, not extra row height.
let nested = SelectableMarkdownTextView()
nested.stamp(); nested.ios15LatchedNeedH = 471
live.add(nested)
check(cell.snapshot().count == 1, "nested attachment double-counted")
check(CurrentTextKitHeightFloor.resolve(cell.snapshot()) == 744, "nested attachment inflated floor")

// Hidden/transparent/scroll-clipped content cannot inflate the row.
let hidden = SelectableMarkdownTextView()
hidden.stamp(); hidden.isHidden = true
cell.contentView.add(hidden)
let transparentHost = UIView(); transparentHost.alpha = 0
cell.contentView.add(transparentHost)
let transparentText = SelectableMarkdownTextView(); transparentText.stamp(); transparentHost.add(transparentText)
let scrollingHost = UIScrollView(); scrollingHost.isScrollEnabled = true
cell.contentView.add(scrollingHost)
let scrollText = SelectableMarkdownTextView(); scrollText.stamp(); scrollingHost.add(scrollText)
check(cell.snapshot().count == 1, "hidden/scrolling text was promoted")

// True separately allocated vertical segments must add, never simply max.
let second = SelectableMarkdownTextView()
second.stamp(); second.top = 800; second.ios15LatchedNeedH = 100
second.bounds.size.height = 100
cell.contentView.add(second)
check(CurrentTextKitHeightFloor.resolve(cell.snapshot()) == 844, "legitimate second text segment lost")
second.top = 300
check(CurrentTextKitHeightFloor.resolve(cell.snapshot()) == nil, "overlapping transition copies were added")
second.isHidden = true

// Same-length rewrite, missing or wrong-width sample must not recycle stale high.
live.textStorage.mutableString.setString("changed text")
check(live.currentCellTextKitHeight(for: 358) == nil, "same-length different-content sample reused")
live.stamp()
check(live.currentCellTextKitHeight(for: 390) == nil, "wrong-width sample reused")
live.ios15LastRenderContentW = 390
check(live.currentCellTextKitHeight(for: 358) == nil, "old render geometry accepted")
live.ios15LastRenderContentW = 358
live.ios15LatchedNeedH = 0
check(live.currentCellTextKitHeight(for: 358) == nil, "unmeasured sample promoted")
live.ios15LatchedNeedH = 267
check(CurrentTextKitHeightFloor.resolve(cell.snapshot()) == 267, "legitimate shrink permanently locked high")
live.ios15LatchedNeedH = 822
check(CurrentTextKitHeightFloor.resolve(cell.snapshot()) == 822, "legitimate growth/clipping floor lost")
check(CurrentTextKitHeightFloor.resolve([]) == nil, "empty cell invented height")
check(CurrentTextKitHeightFloor.resolve([CurrentTextKitHeightSlice(top: 0, bottom: 10, height: .nan)]) == nil, "NaN floor accepted")
live.isScrollEnabled = true
check(live.currentCellTextKitHeight(for: 358) == nil, "scroll document promoted as allocated height")
print("production current TextKit Swift: PASS (not UIKit/runtime proof)")
'''

if __name__ == '__main__':
    unittest.main(verbosity=2)
