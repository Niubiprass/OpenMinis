// This harness uses real Apple frameworks. Production declarations are prepended
// by run_ios15_geometry_probe.py; no copied layout arithmetic lives here.
struct ProbeFailure: Error { let message: String }

@main final class ProbeApp: UIResponder, UIApplicationDelegate {
    var window: UIWindow?
    var cases: [[String: Any]] = []
    let runID = "__RUN_ID__"

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        window.rootViewController = UIViewController()
        window.makeKeyAndVisible()
        self.window = window
        Task { @MainActor in
            do {
                try testText()
                try testComposer()
                try await testHost()
                writeResult(status: "passed", error: nil)
            } catch {
                writeResult(status: "failed", error: String(describing: error))
            }
        }
        return true
    }

    func check(_ condition: Bool, _ label: String, _ assertions: inout [[String: Any]]) throws {
        assertions.append(["name": label, "passed": condition])
        if !condition { throw ProbeFailure(message: label) }
    }

    func record(_ name: String, _ assertions: [[String: Any]], _ values: [String: Any]) {
        cases.append(["name": name, "passed": true, "assertions": assertions, "measurements": values])
    }

    func paragraphs(_ count: Int) -> String {
        (1...count).map { index in
            "【\(index)】清晨的雾漫过城门，长回复末行应该完整显示。UIKit TextKit measures the actual glyphs, not a numerical oracle."
        }.joined(separator: "\n\n") + "\nEND_GEOMETRY_PROBE"
    }

    func makeText() -> ProbeProductionTextView {
        let storage = NSTextStorage()
        let manager = NSLayoutManager()
        let container = NSTextContainer(size: CGSize(width: 358, height: 100000))
        container.lineFragmentPadding = 0
        container.widthTracksTextView = false
        container.heightTracksTextView = false
        manager.addTextContainer(container)
        storage.addLayoutManager(manager)
        let view = ProbeProductionTextView(frame: CGRect(x: 0, y: 0, width: 358, height: 120), textContainer: container)
        view.isScrollEnabled = false
        view.textContainerInset = UIEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
        return view
    }

    func testText() throws {
        var assertions: [[String: Any]] = []
        var heights: [CGFloat] = []
        let view = makeText()
        for (index, text) in [paragraphs(40), "短正文末行\nEND_GEOMETRY_PROBE", paragraphs(40)].enumerated() {
            view.attributedText = NSAttributedString(string: text, attributes: [.font: UIFont.systemFont(ofSize: 17)])
            // Same real width, but a deliberately clipped prior visible height.
            view.textContainer.size = CGSize(width: 358, height: 120)
            let before = view.textContainer.size
            let size = view.sizeThatFits(CGSize(width: 358, height: .greatestFiniteMagnitude))
            try check(size.height.isFinite && size.height > 0, "phase_\(index)_finite_positive_fit", &assertions)
            try check(view.textContainer.size == before, "phase_\(index)_live_container_unchanged", &assertions)
            let oracle = makeText()
            oracle.attributedText = view.attributedText
            oracle.layoutManager.ensureLayout(for: oracle.textContainer)
            let range = oracle.layoutManager.glyphRange(for: oracle.textContainer)
            let chars = oracle.layoutManager.characterRange(forGlyphRange: range, actualGlyphRange: nil)
            try check(NSMaxRange(chars) == oracle.textStorage.length, "phase_\(index)_all_characters_laid_out", &assertions)
            let used = oracle.layoutManager.usedRect(for: oracle.textContainer)
            let lastGlyph = oracle.layoutManager.glyphIndexForCharacter(at: oracle.textStorage.length - 1)
            let lastLine = oracle.layoutManager.lineFragmentUsedRect(forGlyphAt: lastGlyph, effectiveRange: nil)
            let bottom = max(used.maxY, lastLine.maxY) + 8
            try check(size.height + 1 >= bottom, "phase_\(index)_last_line_fits_measured_height", &assertions)
            try check(abs(size.height - oracle.sizeThatFits(CGSize(width: 358, height: .greatestFiniteMagnitude)).height) <= 1,
                      "phase_\(index)_matches_fresh_full_container", &assertions)
            heights.append(size.height)
        }
        try check(heights[0] > 3000, "long_body_exceeds_historical_2007pt_ceiling", &assertions)
        try check(heights[1] + 500 < heights[0], "same_width_short_body_shrinks", &assertions)
        try check(abs(heights[0] - heights[2]) <= 1, "same_width_long_body_restored", &assertions)
        record("text_long_short_long", assertions, ["width": 358, "heights": heights,
                                                     "oracle": "independent full-height TextKit container and final glyph line"])
    }

    func testComposer() throws {
        var assertions: [[String: Any]] = []
        let view = ProbeComposer(frame: CGRect(x: 0, y: 0, width: 320, height: 40))
        view.font = UIFont.systemFont(ofSize: 17)
        view.maxHeight = 100
        view.text = "短输入"
        view.isScrollEnabled = false
        view.scrollWrites = 0
        let first = view.intrinsicContentSize
        let baselineWrites = view.scrollWrites
        for _ in 0..<25 { _ = view.intrinsicContentSize }
        try check(view.scrollWrites == baselineWrites, "short_repeated_intrinsic_no_same_value_scroll_writes", &assertions)
        try check(!view.isScrollEnabled && first.height < view.maxHeight, "short_under_cap_does_not_scroll", &assertions)
        view.text = paragraphs(10)
        let writesBeforeGrowth = view.scrollWrites
        let tall = view.intrinsicContentSize
        try check(view.isScrollEnabled && tall.height == view.maxHeight, "overflow_scrolls_and_height_is_capped", &assertions)
        try check(view.scrollWrites == writesBeforeGrowth + 1, "crossing_cap_enables_scroll_once", &assertions)
        let overflowWrites = view.scrollWrites
        for _ in 0..<25 { _ = view.intrinsicContentSize }
        try check(view.scrollWrites == overflowWrites, "overflow_repeated_intrinsic_no_same_value_scroll_writes", &assertions)
        view.pinnedHeight = 144
        try check(view.intrinsicContentSize.height == 144 && view.isScrollEnabled,
                  "pinned_height_preserves_overflow_policy", &assertions)
        view.text = "短输入"
        let writesBeforeShrink = view.scrollWrites
        try check(view.intrinsicContentSize.height == 144 && !view.isScrollEnabled,
                  "pinned_short_keeps_pinned_height_but_disables_scroll", &assertions)
        try check(view.scrollWrites == writesBeforeShrink + 1, "crossing_cap_disables_scroll_once", &assertions)
        let settledWrites = view.scrollWrites
        for _ in 0..<25 { _ = view.intrinsicContentSize }
        try check(view.scrollWrites == settledWrites, "pinned_repeated_intrinsic_is_idempotent", &assertions)
        view.bounds.size.width = 0
        let zero = view.intrinsicContentSize
        try check(zero.width == UIView.noIntrinsicMetric && zero.height == view.font!.lineHeight,
                  "zero_width_uses_original_font_lineheight_rule", &assertions)
        try check(view.scrollWrites == settledWrites, "zero_width_does_not_write_scroll", &assertions)
        record("composer_intrinsic", assertions, ["short_height": first.height, "overflow_height": tall.height,
                                                 "scroll_setter_calls": view.scrollWrites])
    }

    func content(_ text: String, id: Int) -> ProbeLegacyHostingConfiguration<AnyView> {
        ProbeLegacyHostingConfiguration {
            AnyView(Text(text).font(.system(size: 17)).fixedSize(horizontal: false, vertical: true))
        }.ios15ContentIdentity(MessageListItem.row(id))
    }

    func settle() async {
        try? await Task.sleep(nanoseconds: 180_000_000)
    }

    func fit(_ view: UIView) -> CGFloat {
        view.setNeedsLayout()
        view.layoutIfNeeded()
        return view.systemLayoutSizeFitting(CGSize(width: 358, height: 0),
                                           withHorizontalFittingPriority: .required,
                                           verticalFittingPriority: .fittingSizeLevel).height
    }

    func testHost() async throws {
        var assertions: [[String: Any]] = []
        let view = content(paragraphs(8), id: 1).makeContentView()
        view.frame = CGRect(x: 0, y: 0, width: 358, height: 0)
        window!.rootViewController!.view.addSubview(view)
        await settle()
        let firstGraph = view.subviews.first!
        let long = fit(view)
        view.configuration = content("短消息", id: 1)
        await settle()
        _ = fit(view)
        await settle()
        let short = fit(view)
        try check(view.subviews.first === firstGraph, "same_identity_retains_hosted_UIView", &assertions)
        try check(long.isFinite && short.isFinite && long > short + 100 && short > 1,
                  "same_identity_content_update_remeasures_and_shrinks", &assertions)
        view.configuration = content(paragraphs(8), id: 1)
        await settle()
        let restored = fit(view)
        try check(view.subviews.first === firstGraph && abs(restored - long) <= 1,
                  "same_identity_long_short_long_restores_geometry_and_graph", &assertions)
        let fits = [view.sizeThatFits(CGSize(width: 358, height: 0)).height,
                    view.systemLayoutSizeFitting(CGSize(width: 358, height: 0)).height]
        try check(fits.allSatisfy { abs($0 - restored) <= 1 }, "all_three_fitting_entries_agree", &assertions)
        record("host_same_identity", assertions, ["long": long, "short": short, "restored": restored])
        assertions = []
        view.configuration = content("复用为另一个项目", id: 2)
        await settle()
        let reused = fit(view)
        try check(view.subviews.first !== firstGraph, "different_identity_rebuilds_hosted_UIView", &assertions)
        try check(reused.isFinite && reused > 1 && reused < long - 100,
                  "different_identity_does_not_inherit_old_height", &assertions)
        record("host_reuse_identity", assertions, ["old_height": long, "new_height": reused])
        view.removeFromSuperview()
        assertions = []
        let footer = ProbeLegacyHostingConfiguration { AnyView(EmptyView()) }
            .ios15ContentIdentity(MessageListItem.row(3)).makeContentView()
        footer.frame = CGRect(x: 0, y: 0, width: 358, height: 0)
        window!.rootViewController!.view.addSubview(footer)
        await settle()
        let empty = fit(footer)
        try check(empty.isFinite && empty >= 0 && empty <= 1,
                  "fresh_legitimate_empty_footer_remains_zero_not_positive_body", &assertions)
        try check(abs(fit(footer) - empty) <= 1, "empty_footer_repeated_fit_is_stable", &assertions)
        record("empty_footer", assertions, ["height": empty, "scope": "fresh zero-height footer, not reused positive-height cell"])
        footer.removeFromSuperview()
    }

    func writeResult(status: String, error: String?) {
        #if targetEnvironment(simulator)
        let simulator = true
        #else
        let simulator = false
        #endif
        var result: [String: Any] = [
            "schema": 1, "run_id": runID, "status": status, "cases": cases,
            "runtime": ["system_name": UIDevice.current.systemName, "system_version": UIDevice.current.systemVersion,
                        "operating_system": ProcessInfo.processInfo.operatingSystemVersionString,
                        "model": UIDevice.current.model, "is_simulator": simulator,
                        "simulator_model_identifier": ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] ?? "unknown"]
        ]
        if let error { result["error"] = error }
        do {
            let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: directory.appendingPathComponent(runID + ".json"), options: .atomic)
        } catch { NSLog("Geometry probe cannot write result: %@", String(describing: error)) }
    }
}
