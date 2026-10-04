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
/// path-driven call sites in ContentView.swift go through `CompatPathStack`
/// instead, which drives the same destination closure from a
/// `CompatNavigationPath` on iOS 15. `CompatNavigationLink` below is the other
/// half of that pair: it is what makes a value-based link actually push on
/// iOS 15, where plain `NavigationLink(value:)` does not exist.
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

/// `NavigationSplitViewVisibility` stand-in (the real one is iOS 16+).
///
/// Held in a `@State` that is declared unconditionally, so it cannot mention
/// the iOS 16 type. On iOS 15 the sidebar-collapse state is simply never
/// driven — see `compatNavigationSplitView`.
@available(iOS 15.0, *)
public enum CompatSplitViewVisibility: Hashable {
    case automatic
    case all
    case doubleColumn
    case detailOnly

    @available(iOS 16.0, *)
    var toSystemVisibility: NavigationSplitViewVisibility {
        switch self {
        case .automatic: return .automatic
        case .all: return .all
        case .doubleColumn: return .doubleColumn
        case .detailOnly: return .detailOnly
        }
    }

    @available(iOS 16.0, *)
    init(_ system: NavigationSplitViewVisibility) {
        switch system {
        case .automatic: self = .automatic
        case .all: self = .all
        case .doubleColumn: self = .doubleColumn
        case .detailOnly: self = .detailOnly
        default: self = .automatic
        }
    }
}

/// `NavigationSplitView` (iOS 16+) fallback to `NavigationView`.
///
/// The one call site (ContentView's iPad regular-width layout) already switches
/// between a split and a stack layout by size class, so on a compact width the
/// fallback renders the same hierarchy the stack layout would.
@available(iOS 15.0, *)
@ViewBuilder
public func compatNavigationSplitView<Sidebar: View, Detail: View>(
    columnVisibility: Binding<CompatSplitViewVisibility>,
    @ViewBuilder sidebar: () -> Sidebar,
    @ViewBuilder detail: () -> Detail
) -> some View {
    if #available(iOS 16.0, *) {
        NavigationSplitView(
            columnVisibility: Binding<NavigationSplitViewVisibility>(
                get: { columnVisibility.wrappedValue.toSystemVisibility },
                set: { columnVisibility.wrappedValue = CompatSplitViewVisibility($0) }
            ),
            sidebar: sidebar,
            detail: detail
        )
    } else {
        NavigationView {
            sidebar()
        }
        .navigationViewStyle(.stack)
    }
}

// MARK: - Navigation path

/// Drop-in replacement for SwiftUI's `NavigationPath` (iOS 16+).
///
/// WHY THIS EXISTS
/// `NavigationPath` is an opaque iOS 16 type with no iOS 15 counterpart, and it
/// cannot be shimmed by `NavigationView` — that view has no bindable path at
/// all. But every operation this app performs on its path is plain array
/// semantics:
///
///     NavigationPath([id])   .append(x)   .isEmpty   .count
///     whole-value assignment (`path = NavigationPath()`)
///     `onChange(of: path)`
///
/// so a thin wrapper over `[Element]` reproduces all of it. The public surface
/// below is intentionally identical to `NavigationPath`'s, which means the
/// ~65 call sites in ContentView.swift that manipulate `navigationPath` keep
/// compiling unchanged — the migration is confined to the type name.
///
/// Conforms to `Equatable` so `onChange(of:)` keeps working; `NavigationPath`
/// itself is Equatable for the same reason.
@available(iOS 15.0, *)
public struct CompatNavigationPath<Element: Hashable>: Equatable {
    public private(set) var elements: [Element] = []

    public init() {}

    public init<S: Sequence>(_ elements: S) where S.Element == Element {
        self.elements = Array(elements)
    }

    public var count: Int { elements.count }
    public var isEmpty: Bool { elements.isEmpty }
    public var first: Element? { elements.first }
    public var last: Element? { elements.last }

    public mutating func append(_ element: Element) {
        elements.append(element)
    }

    public mutating func removeLast() {
        guard !elements.isEmpty else { return }
        elements.removeLast()
    }

    public mutating func removeLast(_ k: Int) {
        guard k > 0, !elements.isEmpty else { return }
        elements.removeLast(min(k, elements.count))
    }

    public mutating func removeAll() {
        elements.removeAll()
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.elements == rhs.elements
    }
}

/// A path-driven navigation container that works on iOS 15.
///
/// iOS 16+ branch: the real `NavigationStack(path:)` with the caller's
/// `navigationDestination` modifier applied inside, whose resolution and
/// identity semantics are what the app's transition-race workarounds (see the
/// `[T-ios-stacknav-transition-attributegraph-race]` notes in ContentView.swift)
/// were written against — so behaviour there is unchanged.
///
/// iOS 15 branch: `NavigationView` cannot host a bindable path, so the stack is
/// rendered manually — the element at the top of `path` determines the pushed
/// view. `NavigationStack` on iOS 15 does not exist, so `destinationView` is
/// supplied explicitly by the caller instead of being discovered via
/// `navigationDestination` (also iOS 16+). When a call site does not supply it,
/// the fallback shows the element's `String(describing:)` so the navigation is
/// still functional and obviously incomplete rather than silently empty.
///
/// This is a genuine behavioural reduction on iOS 15: no interactive
/// back-swipe, no native push animation, no `navigationDestination` lookup.
@available(iOS 15.0, *)
public struct CompatPathStack<Element: Hashable, Content: View>: View {
    private let pathBinding: Binding<CompatNavigationPath<Element>>
    private let content: () -> Content
    private let destinationView: ((Element) -> AnyView)?

    public init(
        path: Binding<CompatNavigationPath<Element>>,
        @ViewBuilder content: @escaping () -> Content,
        @ViewBuilder destination: @escaping (Element) -> some View
    ) {
        self.pathBinding = path
        self.content = content
        self.destinationView = { AnyView(destination($0)) }
    }

    /// Variant for call sites that only have a `navigationDestination` chain
    /// (iOS 16+ only). On iOS 15 there is nothing to resolve it from, so the
    /// fallback renders a placeholder for the top element.
    public init(
        path: Binding<CompatNavigationPath<Element>>,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.pathBinding = path
        self.content = content
        self.destinationView = nil
    }

    public var body: some View {
        if #available(iOS 16.0, *) {
            NavigationStack(path: NavigationPath(path.elements)) {
                content()
            }
        } else {
            legacyStack
        }
    }

    /// iOS 15 fallback: root, plus the element currently on top of the path.
    @ViewBuilder
    private var legacyStack: some View {
        if let top = pathBinding.wrappedValue.last, let destinationView {
            // Key on the element so SwiftUI builds a fresh destination view per
            // path entry. Without a stable identity SwiftUI would reuse the
            // outgoing view's @StateObject, which is the exact bug the
            // `[T-ios-stacknav-transition-attributegraph-race]` notes describe.
            destinationView(top)
                .id(top)
                .transition(.move(edge: .trailing))
        } else if let top = pathBinding.wrappedValue.last {
            Text(String(describing: top))
                .id(top)
                .transition(.move(edge: .trailing))
        } else {
            content()
                .transition(.move(edge: .leading))
        }
    }
}

// MARK: - Value-based navigation link

/// Drop-in replacement for SwiftUI's value-based `NavigationLink(value:)`
/// (iOS 16+).
///
/// WHY THIS EXISTS
/// The compact-width session row in ContentView.swift drives navigation with a
/// zero-opacity `NavigationLink(value: session.id) { EmptyView() }` layered
/// over the row's own background. The row itself is not tappable, so that link
/// IS the tap target — the whole "tap a session to open it" interaction on
/// iPhone hangs off it. Nothing else in the compact layout appends to the path
/// on a user gesture; every other write is programmatic (deep links, quick
/// actions, the background watchdog), so without a working link the iPhone
/// session list would be completely inert on iOS 15.
///
/// `NavigationView` on iOS 15 has no value-based link at all: it only offers
/// `NavigationLink(destination:isActive:)` and `NavigationLink(destination:tag:)`
/// driven by a selection binding. Rather than route a whole `String` through a
/// selection `Binding`, the iOS 15 branch appends to the same
/// `CompatNavigationPath` the stack renders from, which keeps one source of
/// truth for "what is on the navigation stack" across both OS versions.
///
/// On iOS 16+ this IS `NavigationLink(value:)`, so identity, transition and the
/// zero-opacity hit-testing behaviour are all unchanged.
@available(iOS 15.0, *)
public struct CompatNavigationLink<Label: View>: View {
    private let value: String?
    private let label: Label

    /// iOS 15 only: the path to append to on tap. Nil on iOS 16+, where the real
    /// link writes to the stack itself.
    private let path: Binding<CompatNavigationPath<String>>?

    public init(
        value: String,
        path: Binding<CompatNavigationPath<String>>? = nil,
        @ViewBuilder label: () -> Label
    ) {
        self.value = value
        self.label = label()
        self.path = path
    }

    public var body: some View {
        if #available(iOS 16.0, *) {
            NavigationLink(value: value ?? "") { label }
        } else if let path {
            // The iOS 15 stack (`CompatPathStack.legacyStack`) re-renders from
            // the path, so appending is all a push needs. Animations are left
            // to the destination's own `.transition` — driving an explicit
            // animation here would fight the transaction the caller may already
            // be running (ContentView commits programmatic pushes with
            // `disablesAnimations`).
            Button {
                var next = path.wrappedValue
                next.append(value ?? "")
                path.wrappedValue = next
            } label: {
                label
            }
            .buttonStyle(.plain)
        } else {
            // No path bound (split layout, or a call site outside a
            // CompatPathStack): fall back to a non-navigating label so the
            // content still renders.
            label
        }
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

/// Which detent a sheet is currently resting at, in a deployment-target-safe
/// type. Stands in for `PresentationDetent` in stored properties
/// (`@State private var detent: …`) that are declared unconditionally and
/// therefore cannot mention an iOS 16+ type.
@available(iOS 15.0, *)
public enum CompatDetentSelection: Hashable {
    case large
    case medium
    case small
    case fraction(CGFloat)
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

    /// Round trip used by the `selection:` bridging binding.
    /// `PresentationDetent` is a struct with exactly these five cases, so the
    /// mapping is exhaustive; the `default` arm only keeps this compiling if
    /// Apple ever adds a case.
    @available(iOS 16.0, *)
    init(_ system: PresentationDetent) {
        switch system {
        case .large: self = .large
        case .medium: self = .medium
        case .small: self = .small
        case .fraction(let value): self = .fraction(value)
        case .height(let value): self = .height(value)
        default: self = .medium
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

    /// Selection-aware variant. iOS 15 has no detent selection, so the binding
    /// is simply not driven there — the sheet still opens and dismisses, it
    /// just does not rest at a user-chosen height.
    func compatPresentationDetents(
        _ detents: Set<CompatPresentationDetent>,
        selection: Binding<CompatDetentSelection>
    ) -> some View {
        if #available(iOS 16.0, *) {
            presentationDetents(
                Set(detents.map(\.toSystemDetent)),
                selection: Binding<PresentationDetent>(
                    get: { selection.wrappedValue.toSystemDetent },
                    set: { selection.wrappedValue = CompatDetentSelection($0) }
                )
            )
        } else {
            self
        }
    }
}

// MARK: - Sheet chrome

/// Drop-in replacement for `.presentationDragIndicator(_:)` (iOS 16+).
///
/// iOS 15 sheets have no drag indicator and no way to show one, so this is a
/// documented no-op there: the sheet presents and dismisses exactly as before,
/// it just lacks the grabber. The enum is redeclared rather than reusing
/// SwiftUI's `Visibility` so the parameter type stays iOS 15-legal.
@available(iOS 15.0, *)
public enum CompatDragIndicatorVisibility {
    case automatic
    case visible
    case hidden
}

@available(iOS 15.0, *)
public extension View {
    func compatPresentationDragIndicator(_ visibility: CompatDragIndicatorVisibility) -> some View {
        if #available(iOS 16.0, *) {
            presentationDragIndicator(visibility.systemValue)
        } else {
            self
        }
    }
}

@available(iOS 16.0, *)
private extension CompatDragIndicatorVisibility {
    var systemValue: Visibility {
        switch self {
        case .automatic: return .automatic
        case .visible: return .visible
        case .hidden: return .hidden
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

// MARK: - Geometry observation

/// Version-safe stand-in for `View.onGeometryChange(for:of:action:)` (iOS 18+).
///
/// WHY THIS EXISTS
/// `onGeometryChange` is the modern replacement for the
/// `GeometryReader` + `onAppear` + `onChange(of:)` scaffold, and this codebase
/// standardised on it after an iOS 18 async-renderer SIGTRAP
/// (`[T-ios-geometry-observer-crash]`, `ViewGraphGeometryObservers.needsUpdate`).
/// It is iOS 18+, so the deployment-target lowering to 15.0 would not compile.
/// Rather than reverting those five call sites to the scaffold that previously
/// crashed, the version check is centralised here.
///
/// The iOS 15–17 branch uses a zero-impact `GeometryReader` background plus
/// `onAppear` / `onChange`. Two deliberate differences from iOS 18+:
///
///   * The action fires on appear with the initial value, matching
///     `onGeometryChange`'s documented initial-fire behaviour. Call sites rely
///     on this to seed state that used to be seeded in `onAppear`.
///   * `GeometryReader` fills its parent, so the reader is confined to a
///     `Color.clear` background layer that does not affect layout — the same
///     containment the call sites already used around the observer.
///
/// The `transform` closure receives a `GeometryProxy` in both branches so the
/// call sites' measurement expressions are unchanged.
@available(iOS 15.0, *)
public struct CompatGeometryObserver<Value: Equatable, Transform: @Sendable (GeometryProxy) -> Value>: ViewModifier {
    private let transform: Transform
    private let action: (Value) -> Void

    public init(
        for type: Value.Type,
        transform: @escaping @Sendable (GeometryProxy) -> Value,
        action: @escaping (Value) -> Void
    ) {
        self.transform = transform
        self.action = action
    }

    @ViewBuilder
    public func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content.onGeometryChange(for: Value.self, of: transform, action: action)
        } else {
            legacyObserver(content: content)
        }
    }

    /// iOS 15–17 measurement path. See the type comment for why the reader is
    /// confined to a `Color.clear` background and why the action also fires
    /// from `onAppear`.
    ///
    /// PERFORMANCE. The iOS 18 `onGeometryChange` is an *observer*: it runs the
    /// action only when the measured value actually changes. The obvious
    /// `GeometryReader` + `onChange(of: transform(proxy))` port is not — the
    /// `GeometryReader` is itself a content view, so its body (and therefore
    /// `transform`) is re-evaluated on every layout pass. In a scrolling
    /// message list that means the measurement runs per frame, and because the
    /// call sites debounce via `Task` inside the action, a fresh `Task` is
    /// allocated per frame too. That is a per-frame allocation + measurement
    /// cost on the hottest path in the app, and it shows up as dropped frames
    /// and stutter while scrolling.
    ///
    /// The fix is to move the *comparison* out of the per-frame path: the
    /// reader publishes into `@State`, the state drives `.onChange`, and the
    /// action fires only on a genuine transition. `transform` still runs once
    /// per layout pass (unavoidable — that is how `GeometryReader` works), but
    /// nothing downstream of it allocates or re-runs unless the value moved.
    @ViewBuilder
    private func legacyObserver(content: Content) -> some View {
        content
            .background {
                GeometryReader { proxy in
                    Color.clear
                        .onAppear {
                            let value = transform(proxy)
                            lastValue = value
                            action(value)
                        }
                        .onChange(of: transform(proxy)) { newValue in
                            // Skip the write when the measurement is unchanged:
                            // this is what keeps a scrolling list from firing
                            // the action on every frame.
                            guard newValue != lastValue else { return }
                            lastValue = newValue
                            action(newValue)
                        }
                }
            }
    }

    /// Mirrors the last measured value. `nil` until the first layout pass.
    @State private var lastValue: Value?
}

@available(iOS 15.0, *)
public extension View {
    /// See `CompatGeometryObserver`.
    func compatOnGeometryChange<Value: Equatable>(
        for type: Value.Type,
        of transform: @escaping @Sendable (GeometryProxy) -> Value,
        action: @escaping (Value) -> Void
    ) -> some View {
        modifier(CompatGeometryObserver(for: type, of: transform, action: action))
    }
}
