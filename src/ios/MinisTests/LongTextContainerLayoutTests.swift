import XCTest
import UIKit
@testable import Minis

/// Runs against the installed swizzle, not a duplicate of its arithmetic.
/// A stale cell cache is not needed to reproduce the 160644 2007pt ceiling.
@MainActor
final class LongTextContainerLayoutTests: XCTestCase {
    private func paragraphs(_ count: Int) -> String {
        (1...count).map {
            String(format: "【%02d】", $0) +
            "清晨的雾从青岚城东门漫进来，像一层尚未晾干的薄纱。街边卖热栗子的老人刚支起摊子，铜锅里噼啪作响，远处钟楼敲了六下，鸽群便从屋檐下同时飞起。"
        }.joined(separator: "\n\n") + "\nEND160644"
    }

    func testRealHeightsAreNotMistakenForProbes() {
        NSTextContainerSetSizeGuard.install()
        let container = NSTextContainer(size: .zero)
        // Old V38C fails at 3000; also check the old threshold's neighbours.
        let heights: [CGFloat] = [1999, 2000, 2999, 3000, 4000, 12000, 100000]
        for height in heights {
            container.size = CGSize(width: 358, height: height)
            XCTAssertEqual(container.size.height, height)
        }
        container.size = CGSize(width: 358, height: CGFloat.greatestFiniteMagnitude)
        XCTAssertEqual(container.size.height, 100000)
    }

    func testTextKitLaysOutTheWholeLongResponse() {
        NSTextContainerSetSizeGuard.install()
        let storage = NSTextStorage(string: paragraphs(40), attributes: [
            .font: UIFont.systemFont(ofSize: 17)
        ])
        let manager = NSLayoutManager()
        let container = NSTextContainer(size: .zero)
        container.lineFragmentPadding = 0
        manager.addTextContainer(container)
        storage.addLayoutManager(manager)
        container.size = CGSize(width: 358, height: CGFloat.greatestFiniteMagnitude)
        manager.ensureLayout(for: container)
        let glyphs = manager.glyphRange(for: container)
        let characters = manager.characterRange(forGlyphRange: glyphs, actualGlyphRange: nil)
        XCTAssertEqual(NSMaxRange(characters), storage.length, "END160644 must have a layout fragment")
        XCTAssertGreaterThan(manager.usedRect(for: container).height, 3000)
    }

    func testLiveFittingGrowsPast2007AndFreshViewAgrees() {
        NSTextContainerSetSizeGuard.install()
        func makeView() -> SelectableMarkdownTextView {
            let view = SelectableMarkdownTextView(frame: CGRect(x: 0, y: 0, width: 358, height: 500), textContainer: nil)
            view.isScrollEnabled = false
            view.textContainerInset = UIEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
            view.textContainer.lineFragmentPadding = 0
            view.textContainer.widthTracksTextView = false
            view.textContainer.heightTracksTextView = false
            view.textContainer.size = CGSize(width: 358, height: CGFloat.greatestFiniteMagnitude)
            return view
        }
        func measure(_ view: SelectableMarkdownTextView, count: Int) -> CGFloat {
            view.attributedText = NSAttributedString(string: paragraphs(count), attributes: [
                .font: UIFont.systemFont(ofSize: 17)
            ])
            return view.sizeThatFits(CGSize(width: 358, height: CGFloat.greatestFiniteMagnitude)).height
        }
        let live = makeView()
        let short = measure(live, count: 10)
        let middle = measure(live, count: 25)
        let full = measure(live, count: 40)
        XCTAssertGreaterThan(middle, short + 500)
        XCTAssertGreaterThan(full, middle + 500)
        XCTAssertGreaterThan(full, 3000)
        XCTAssertEqual(measure(makeView(), count: 40), full, accuracy: 1,
                       "Fresh/reentered and incrementally updated rendering must agree")
    }
}
