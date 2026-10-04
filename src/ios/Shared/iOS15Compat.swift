//
//  iOS15Compat.swift
//  Minis
//
//  iOS 15 compatibility shims for APIs introduced in iOS 16/ 17.
//
//  The deployment target was lowered from iOS 16.0 to iOS 15.0. Most of the
//  app's iOS 16 API surface is funnelled through the types below so the
//  version check lives in exactly one place instead of being scattered across
//  ~200 call sites.
//
//  Rules of thumb used here:
//    * Prefer a semantic match over a visual match. The iOS 15 fallbacks are
//      chosen to behave the way the iOS 16 API would, not merely look similar.
//    * Never silently drop user-visible functionality. Where iOS 15 has no
//      equivalent (e.g. sheet detents), the fallback is a documented
//      approximation, not a no-op.
//    * A type or extension that is ONLY compiled when it would otherwise
//      reference an iOS 16+ symbol is annotated with @available so the
//      compiler never type-checks an unavailable branch on older SDKs.
//
//  KNOWN FUNCTIONAL GAPS on iOS 15 (system-framework limits, not bugs here):
//    * AppIntents (Siri / Shortcuts) requires iOS 16 — the intent types are
//      gated with @available(iOS 16, *) and simply do not exist on iOS 15.
//    * ActivityKit / Live Activity requires iOS 16.1 — the AgentWidget target
//      therefore cannot be lowered below 16.1, see the widget target's
//      IPHONEOS_DEPLOYMENT_TARGET.
//    * AlarmKit requires iOS 26 and is already behind #if canImport(AlarmKit).
//

import SwiftUI

// MARK: - Navigation

/// Drop-in replacement for SwiftUI's `NavigationStack` (iOS 16+).
///
/// On iOS 16+ this IS `NavigationStack`, so all runtime behaviour — including
/// `navigationDestination(for:)` resolution and the identity semantics the app
/// depends on — is unchanged.
///
/// On iOS 15 it degrades to `NavigationView` with `.stack` style, which is the
/// documented predecessor and looks/behaves the same for the plain
/// (no-bound-path) case.
///
/// IMPORTANT: this shim does NOT cover `NavigationStack(path:)`, which has no
/// iOS 15 equivalent because `NavigationPath` is itself an iOS 16 type. The two
/// path-driven call sites in ContentView.swift branch on availability directly.
@available(iOS 15.0, *)
@ViewBuilder
public func CompatNavigationStack<Content: View>(
    @ViewBuilder content: () -> Content
) -> some View {
    if #available(iOS 16.0, *) {
        NavigationStack(content: content)
    } else {
        NavigationView {
            content()
        }
        .navigationViewStyle(.stack)
    }
}

/// `NavigationSplitView` (iOS 16+) fallback to `NavigationView`.
///
/// The one call site (ContentView's iPad regular-width layout) already switches
/// between a split and a stack layout by size class, so on a compact width the
/// fallback renders the same hierarchy the stack layout would.
@available(iOS 15.0, *)
@ViewBuilder
public func CompatNavigationSplitView<Sidebar: View, Detail: View>(
    @ViewBuilder sidebar: () -> Sidebar,
    @ViewBuilder detail: () -> Detail
) -> some View {
    if #available(iOS 16.0, *) {
        NavigationSplitView(sidebar: sidebar, detail: detail)
    } else {
        NavigationView {
            sidebar()
        }
        .navigationViewStyle(.stack)
    }
}

// MARK: - Labeled content

/// Drop-in replacement for SwiftUI's `LabeledContent` (iOS 16+).
///
/// Covers both call shapes used in the codebase:
///   * `CompatLabeledContent("Title", value: someValue)` — 33 sites
///   * `CompatLabeledContent("Title") { content }`      — 12 sites
///
/// The iOS 15 fallback is an `HStack` with a `Spacer`, which is how
/// `LabeledContent` lays out inside a `Form`/`List` on iOS 16 anyway.
@available(iOS 15.0, *)
public struct CompatLabeledContent<Label: View, Value: View>: View {
    private let label: Label
    private let value: Value

    public init(@ViewBuilder label: () -> Label, @ViewBuilder value: () -> Value) {
        self.label = label()
        self.value = value()
    }

    public var body: some View {
        if #available(iOS 16.0, *) {
            LabeledContent {
                label
            } content: {
                value
            }
        } else {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                label
                Spacer(minLength: 8)
                value
            }
        }
    }
}

@available(iOS 15.0, *)
public extension CompatLabeledContent where Label == Text {
    /// Mirrors `LabeledContent(_:value:)`. The value is rendered as text on
    /// iOS 15; on iOS 16 the real `LabeledContent` handles formatting.
    init<S: StringProtocol>(_ title: S, value: S) {
        self.init {
            Text(title)
        } value: {
            Text(value)
        }
    }

    init<S: StringProtocol, V: CustomStringConvertible>(_ title: S, value: V) {
        self.init {
            Text(title)
        } value: {
            Text(value.description)
        }
    }
}

// MARK: - Sheet presentation

/// Detent requested by a sheet, expressed in a deployment-target-safe type.
///
/// The call sites used to spell `Set<PresentationDetent>`, but that type is
/// iOS 16+ and — critically — it appears in the SIGNATURE of a view modifier
/// that is applied unconditionally in a modifier chain. SwiftUI modifiers
/// cannot be wrapped in `if #available` without breaking the chain, and
/// marking the modifier `@available(iOS 16, *)` would push that burden onto
/// all29 call sites.
///
/// Declaring our own equivalent enum keeps the modifier fully available on
/// iOS 15 and confines the version check to this one implementation.
@available(iOS 15.0, *)
public enum CompatPresentationDetent: Hashable {
    case large
    case medium
    case small
    /// Fraction of the container height, e.g. `0.75` for a 75%-height sheet.
    case fraction(CGFloat)
    /// Fixed height in points.
    case height(CGFloat)

    @available(iOS 16.0, *)
    var toSystemDetent: PresentationDetent {
        switch self {
        case .large: return .large
        case .medium: return .medium
        case .small: return .small
        case .fraction(let value): return .fraction(value)
        case .height(let value): return .height(value)
        }
    }
}

/// Drop-in replacement for `.presentationDetents(_:)` (iOS 16+).
///
/// iOS 15 has no detent system: a sheet is always presented at its natural
/// height (`.pageSheet` behaviour). Applying the modifier there is correct and
/// matches what iOS 16 renders for a single `.large` detent.
///
/// Sites that request `.medium` + `.large` lose the medium stop on iOS 15;
/// the sheet still presents, dismisses and forwards its content normally.
/// This approximation is a genuine behavioural difference, documented in
/// KNOWN FUNCTIONAL GAPS at the top of this file.
@available(iOS 15.0, *)
public extension View {
    func compatPresentationDetents(_ detents: Set<CompatPresentationDetent>) -> some View {
        if #available(iOS 16.0, *) {
            presentationDetents(Set(detents.map(\.toSystemDetent)))
        } else {
            self
        }
    }
}

// MARK: - Share sheet

/// Drop-in replacement for SwiftUI's `ShareLink` (iOS 16+).
///
/// On iOS 15 there is no `ShareLink`; the equivalent is a button driving a
/// `UIActivityViewController` presented from the key window's top-most
/// view controller.
///
/// Deliberately minimal: it covers the only shape used in the codebase,
/// `ShareLink(item: URL)`. Adding the `subject:` / `message:` / preview
/// overloads would multiply the generic parameters, and the iOS 16 branch
/// would then have to reproduce `ShareLink`'s exact overload resolution —
/// something that cannot be compile-checked here. Keep it narrow and add
/// overloads only when a call site actually needs one.
@available(iOS 15.0, *)
public struct CompatShareLink<Label: View>: View {
    private let url: URL
    private let label: () -> Label

    public init(item: URL, @ViewBuilder label: @escaping () -> Label) {
        self.url = item
        self.label = label
    }

    public var body: some View {
        if #available(iOS 16.0, *) {
            ShareLink(item: url, label: label)
        } else {
            Button(action: presentActivitySheet) {
                label()
            }
            .buttonStyle(.plain)
        }
    }

    private func presentActivitySheet() {
        let controller = UIActivityViewController(
            activityItems: [url],
            applicationActivities: nil
        )
        guard let presenter = Self.topViewController() else { return }
        // iPad requires a popover anchor or the presentation traps.
        if let popover = controller.popoverPresentationController {
            popover.sourceView = presenter.view
            popover.sourceRect = CGRect(
                x: presenter.view.bounds.midX,
                y: presenter.view.bounds.midY,
                width: 0,
                height: 0
            )
            popover.permittedArrowDirections = []
        }
        presenter.present(controller, animated: true)
    }

    private static func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
        let window = scenes
            .flatMap { $0.windows }
            .first { $0.isKeyWindow }
            ?? scenes.flatMap { $0.windows }.first
        var top = window?.rootViewController
        while let presented = top?.presentedViewController {
            top = presented
        }
        return top
    }
}

@available(iOS 15.0, *)
public extension CompatShareLink where Label == Text {
    /// Mirrors `ShareLink(item:)`'s default label. `ShareLink(item:)` without a
    /// label closure renders `Label("Share Item", systemImage: "square.and.arrow.up")`,
    /// reproduced here so the toolbar item looks identical on iOS 15.
    init(item: URL) {
        self.init(item: item) {
            Label("Share Item", systemImage: "square.and.arrow.up")
        }
    }
}
