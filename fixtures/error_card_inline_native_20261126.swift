// Template: emit with scripts/test_error_card_inline_20261126.py --emit-native /tmp/ErrorCardInlineTests.swift
// Add GENERATED file to an app-hosted iOS XCTest target, then xcodebuild test on Darwin.
// Production structs/modifier/footer methods are inserted verbatim, not reimplemented.
// This tests native natural sizing; it does NOT claim collection/gesture integration.
// Required integration matrix: tap text + padding twice; hold/copy/dismiss without toggle;
// retry without toggle; auto-retry/cancel/error replacement; scroll off/reuse/back;
// two errors expanded independently; 10k text; accessibility XXXL; composer visible;
// history vs pinned-bottom anchors; expand/collapse during another active message.
import XCTest
import SwiftUI
import UIKit
import Combine

private func AppLocalized(_ key: String) -> String { key }
private func AppLocalizedFormat(_ key: String, _ args: CVarArg...) -> String { key }
private enum ChatColors { static let primaryText: Color = .primary }
private enum AIChatViewModel { static let retryDelays = [1, 2, 3] }
private final class ChatMessage: ObservableObject {
    let id = UUID()
    @Published var error: String?
    init(_ error: String) { self.error = error }
}
private final class CellStateBridgeV2: ObservableObject {
    var autoRetryAttempt = 0
    var autoRetryIsNetwork = false
    var autoRetryNetworkHint = ""
    var autoRetryCountdown = 0
    var isActiveMessage = false
    var onRetry: (() -> Void)?
}

// INSERT_PRODUCTION_SHARED

private struct FixtureFooter: View {
    @ObservedObject var message: ChatMessage
    @ObservedObject var bridge: CellStateBridgeV2
    @ObservedObject var errorCard: InlineErrorCardState
    var body: some View { inlineError(message.error ?? "") }
// INSERT_PRODUCTION_INLINE
}

@available(iOS 16.0, *)
@MainActor
final class ErrorCardInlineNativeTests: XCTestCase {
    func testProductionNaturalSizingAndReset() {
        let raw = "Error " + String(repeating: "长错误0123456789 ", count: 1000)
        for contentSize in [ContentSizeCategory.large, .accessibilityExtraExtraExtraLarge] {
            let message = ChatMessage(raw)
            let bridge = CellStateBridgeV2()
            let state = InlineErrorCardState()
            state.reconcile(messageID: message.id, rawError: raw, retryAttempt: 0, processing: false)
            let root = FixtureFooter(message: message, bridge: bridge, errorCard: state)
                .environment(\.sizeCategory, contentSize)
            let host = UIHostingController(rootView: root)
            let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 390, height: 844))
            window.rootViewController = host
            window.makeKeyAndVisible()
            func measure() -> CGFloat {
                host.view.setNeedsLayout()
                host.view.layoutIfNeeded()
                return host.sizeThatFits(in: CGSize(width: 320, height: .greatestFiniteMagnitude)).height
            }
            let collapsed = measure()
            state.toggle(messageID: message.id, rawError: raw)
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.05))
            let expanded = measure()
            XCTAssertGreaterThan(expanded, collapsed + 100)
            state.toggle(messageID: message.id, rawError: raw)
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.05))
            XCTAssertEqual(measure(), collapsed, accuracy: 2)
            state.toggle(messageID: message.id, rawError: raw)
            state.reconcile(messageID: message.id, rawError: raw, retryAttempt: 1, processing: false)
            XCTAssertFalse(state.value.expanded)
            window.isHidden = true
        }
    }
}
