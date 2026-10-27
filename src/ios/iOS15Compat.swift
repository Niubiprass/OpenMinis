//
//  iOS15Compat.swift
//  MinisApp
//
//  iOS 15 port: SwiftUI types introduced in iOS 16, reimplemented with the
//  iOS 15 API surface. Behaviour is intentionally close-but-not-identical --
//  these exist so the app compiles and stays usable on iOS 15.5, not to win
//  design awards.
//

import SwiftUI
import UIKit
import UniformTypeIdentifiers

// MARK: - AnyShape (iOS 16)

/// Type-erased `Shape`. iOS 16 ships this; iOS 15 needs a hand-rolled version.
public struct AnyShape: Shape {
    private let _path: (CGRect) -> Path

    public init<S: Shape>(_ wrapped: S) {
        // 显式闭包，不依赖 unapplied method reference —— 后者在某些
        // Swift 版本/泛型上下文下会推导失败
        _path = { rect in wrapped.path(in: rect) }
    }

    public func path(in rect: CGRect) -> Path {
        _path(rect)
    }
}

// MARK: - UnevenRoundedRectangle (iOS 16)

/// Rectangle with a per-corner radius. iOS 16 ships this; iOS 15 does not.
public struct UnevenRoundedRectangle: Shape {
    public var topLeadingRadius: CGFloat
    public var bottomLeadingRadius: CGFloat
    public var bottomTrailingRadius: CGFloat
    public var topTrailingRadius: CGFloat
    public var style: RoundedCornerStyle

    public init(topLeadingRadius: CGFloat = 0,
                bottomLeadingRadius: CGFloat = 0,
                bottomTrailingRadius: CGFloat = 0,
                topTrailingRadius: CGFloat = 0,
                style: RoundedCornerStyle = .continuous) {
        self.topLeadingRadius = topLeadingRadius
        self.bottomLeadingRadius = bottomLeadingRadius
        self.bottomTrailingRadius = bottomTrailingRadius
        self.topTrailingRadius = topTrailingRadius
        self.style = style
    }

    public func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        let tl = max(0, min(topLeadingRadius, min(w, h) / 2))
        let tr = max(0, min(topTrailingRadius, min(w, h) / 2))
        let bl = max(0, min(bottomLeadingRadius, min(w, h) / 2))
        let br = max(0, min(bottomTrailingRadius, min(w, h) / 2))

        var p = Path()
        p.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        if tr > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr),
                     radius: tr, startAngle: .degrees(-90), endAngle: .degrees(0),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - br))
        if br > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - br, y: rect.maxY - br),
                     radius: br, startAngle: .degrees(0), endAngle: .degrees(90),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX + bl, y: rect.maxY))
        if bl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + bl, y: rect.maxY - bl),
                     radius: bl, startAngle: .degrees(90), endAngle: .degrees(180),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        if tl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl),
                     radius: tl, startAngle: .degrees(180), endAngle: .degrees(270),
                     clockwise: false)
        }
        p.closeSubpath()
        return p
    }
}

// MARK: - LabeledContent (iOS 16)

/// Label + value row. iOS 16 ships this; iOS 15 approximates it with an
/// `HStack` that pushes the content to the trailing edge.
public struct LabeledContent<Label: View, Content: View>: View {
    private let label: Label
    private let content: Content

    public init(@ViewBuilder content: () -> Content,
                @ViewBuilder label: () -> Label) {
        self.content = content()
        self.label = label()
    }

    public var body: some View {
        HStack(alignment: .firstTextBaseline) {
            label
            Spacer(minLength: 8)
            content
        }
    }
}

extension LabeledContent where Label == Text {
    /// `LabeledContent("Title", value: "…")`
    public init<S1: StringProtocol, S2: StringProtocol>(_ title: S1, value: S2)
    where Content == Text {
        self.init(content: { Text(value) }, label: { Text(title) })
    }

    /// `LabeledContent("Title") { … }`
    public init<S: StringProtocol>(_ title: S, @ViewBuilder content: () -> Content) {
        self.init(content: content, label: { Text(title) })
    }
}

// MARK: - NavigationPath (iOS 16)

/// Minimal stand-in for SwiftUI's iOS 16 `NavigationPath`.
///
/// The port replaces `NavigationStack(path:)` with `NavigationView`, so these
/// values are carried but never drive navigation on iOS 15. Kept as a real
/// type so existing `@State` declarations and helpers still compile.
public struct NavigationPath: Equatable {
    private var elements: [AnyHashable]

    public init() {
        elements = []
    }

    public init<C: Collection>(_ elements: C) where C.Element: Hashable {
        self.elements = elements.map { AnyHashable($0) }
    }

    public var count: Int { elements.count }
    public var isEmpty: Bool { elements.isEmpty }

    public mutating func append<V: Hashable>(_ value: V) {
        elements.append(AnyHashable(value))
    }

    public mutating func removeLast(_ k: Int = 1) {
        guard k > 0 else { return }
        elements.removeLast(min(k, elements.count))
    }

    public static func == (lhs: NavigationPath, rhs: NavigationPath) -> Bool {
        lhs.elements == rhs.elements
    }

    /// 栈顶元素 —— iOS 15 的 shim 用它决定该 push 哪一层。
    public var last: AnyHashable? { elements.last }

    public var allElements: [AnyHashable] { elements }
}

// MARK: - navigationDestination(for:) 注册表 (iOS 16)

/// iOS 16 的 `.navigationDestination(for: D.self) { d in … }` 把「值 → 目标视图」的
/// 映射交给 SwiftUI 的 path 系统。iOS 15 没有这套机制，这里用一个全局注册表
/// 近似：注册时记下类型 → 构造器，push 时按栈顶元素的实际类型回查。
///
/// 局限性：全局单例，多个 NavigationStack 共享同一份映射。本项目只有
/// ContentView 与 Settings 两处使用，且目标类型不同，实际不会串。
public final class NavigationDestinationRegistry {
    public static let shared = NavigationDestinationRegistry()

    private var handlers: [ObjectIdentifier: (Any) -> AnyView] = [:]
    private let lock = NSLock()

    public func register<D: Hashable>(_ type: D.Type,
                                      handler: @escaping (D) -> AnyView) {
        lock.lock()
        defer { lock.unlock() }
        handlers[ObjectIdentifier(type)] = { value in
            guard let typed = value as? D else { return AnyView(EmptyView()) }
            return handler(typed)
        }
    }

    public func resolve(_ value: Any) -> AnyView {
        lock.lock()
        defer { lock.unlock() }
        let key = ObjectIdentifier(type(of: value))
        if let h = handlers[key] { return h(value) }
        // 类型不完全匹配时（例如 AnyHashable 装箱差异）逐个尝试。
        for (_, h) in handlers {
            let probe = h(value)
            if !(probe is AnyView) { return probe }
        }
        return AnyView(EmptyView())
    }

    public func resolveHashable(_ value: AnyHashable) -> AnyView {
        resolve(value.base)
    }
}

/// `NavigationLink(value:)` / `NavigationStack(path:)` 共用的目标视图。
public struct NavigationPathDestinationView: View {
    let value: AnyHashable

    public init(_ value: AnyHashable) { self.value = value }

    public var body: some View {
        NavigationDestinationRegistry.shared.resolveHashable(value)
    }
}

/// `.navigationDestination(for:)` 的 iOS 15 替身：注册映射，不改变视图本身。
private struct _NavigationDestinationInstaller: ViewModifier {
    func body(content: Content) -> some View { content }
}

extension View {
    /// iOS 16 `.navigationDestination(for:destination:)` 替身。
    ///
    /// 在 iOS 15 上把 `destination` 闭包登记进注册表；`NavigationLink(value:)`
    /// 与 `NavigationStack(path:)` 随后从注册表取回目标视图。
    public func navigationDestination<D: Hashable, V: View>(
        for data: D.Type,
        @ViewBuilder destination: @escaping (D) -> V
    ) -> some View {
        NavigationDestinationRegistry.shared.register(D.self) { d in
            AnyView(destination(d))
        }
        return modifier(_NavigationDestinationInstaller())
    }
}

// MARK: - NavigationLink(value:) (iOS 16)

extension NavigationLink {
    /// iOS 16 的 `NavigationLink(value:label:)`。
    ///
    /// 在 iOS 15 上退化成传统的 `NavigationLink(destination:label:)`，目的地由
    /// `.navigationDestination` 注册表按 `value` 的实际类型解析出来。
    public init<P: Hashable>(value: P, @ViewBuilder label: () -> Label)
    where Destination == NavigationPathDestinationView {
        self.init(destination: NavigationPathDestinationView(AnyHashable(value)),
                  label: label)
    }
}

// MARK: - NavigationStack (iOS 16)

/// iOS 16 `NavigationStack` 替身。
///
/// 用 iOS 15 的 `NavigationView` + 一个隐藏的 `NavigationLink(isActive:)`
/// 模拟：path 非空 → push 栈顶对应的目标；path 清空 → pop 回根。
/// 只驱动一层（本项目 path 深度为 1，深层由视图内部的普通 NavigationLink 展开）。
public struct NavigationStack<Root: View>: View {
    @Binding private var path: NavigationPath
    private let root: Root

    public init(path: Binding<NavigationPath>, @ViewBuilder root: () -> Root) {
        self._path = path
        self.root = root()
    }

    public init(@ViewBuilder root: () -> Root) {
        self._path = .constant(NavigationPath())
        self.root = root()
    }

    public var body: some View {
        NavigationView {
            root
                .background(
                    NavigationLink(
                        isActive: Binding(
                            get: { !path.isEmpty },
                            set: { active in
                                if !active { path.removeLast(path.count) }
                            }
                        ),
                        destination: {
                            Group {
                                if let top = path.last {
                                    NavigationPathDestinationView(top)
                                } else {
                                    EmptyView()
                                }
                            }
                        },
                        label: { EmptyView() }
                    )
                    .opacity(0)
                    .frame(width: 0, height: 0)
                )
        }
        .navigationViewStyle(StackNavigationViewStyle())
    }
}

// MARK: - NavigationSplitView (iOS 16)

public enum NavigationSplitViewVisibility {
    case automatic
    case doubleColumn
    case detailOnly
}

/// iOS 15 上不存在分栏容器，退化为「固定宽度侧栏 + 详情」的 HStack。
/// 只有 iPad 宽布局会走到这里；iPhone 走 `NavigationStack` 分支。
public struct NavigationSplitView<Sidebar: View, Detail: View>: View {
    @Binding private var columnVisibility: NavigationSplitViewVisibility
    private let sidebar: Sidebar
    private let detail: Detail

    public init(columnVisibility: Binding<NavigationSplitViewVisibility>,
                @ViewBuilder sidebar: () -> Sidebar,
                @ViewBuilder detail: () -> Detail) {
        self._columnVisibility = columnVisibility
        self.sidebar = sidebar()
        self.detail = detail()
    }

    public init(@ViewBuilder sidebar: () -> Sidebar,
                @ViewBuilder detail: () -> Detail) {
        self._columnVisibility = .constant(.automatic)
        self.sidebar = sidebar()
        self.detail = detail()
    }

    public var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                if columnVisibility != .detailOnly {
                    sidebar
                        .frame(width: min(340, geo.size.width * 0.36))
                }
                detail
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

// MARK: - UIHostingConfiguration (iOS 16)

/// `UIHostingConfiguration` 的 iOS 15 替身。
///
/// 遵守 `UIContentConfiguration`，所以项目里的
/// `cell.applyContentConfiguration(config)` 一行都不用改：cell 拿到的是
/// 一个普通的 content configuration，内部用 `UIHostingController` 渲染。
// [V63-PROBE] 装机可观测性计数器。★必须是**非泛型**类型: Swift 禁止在
// 泛型类型里声明静态存储属性, 放进去 Release 编译直接失败(run#157)。
private final class _V63Probe {
    static var fastHit: UInt = 0
    static var rebuildHit: UInt = 0
    static var lastPrint: CFTimeInterval = 0
    static func hitFast() { fastHit &+= 1; maybePrint() }
    static func hitRebuild() { rebuildHit &+= 1; maybePrint() }
    private static func maybePrint() {
        let now = CACurrentMediaTime()
        guard now - lastPrint > 0.5 else { return }
        lastPrint = now
        print("[V63-PROBE] fast=\(fastHit) rebuild=\(rebuildHit)")
    }
}

/// Narrow escape hatch for a *confirmed* TextKit shrink on a settled row.
/// Do not remove the hosting high-water guard globally: it also shields
/// transient attachment measurements from collapsing live cells.
protocol IOS15HostingHeightResettable: AnyObject {
    func resetIOS15HostingHeightForConfirmedShrink()
    func consumeIOS15PendingStableShrink()
    /// A committed model shape transition, NOT a smaller fitting sample.
    func noteIOS15HostingContentShape(_ shape: AnyHashable)
    /// Synchronous coordinator transaction: one offset owner per correction.
    var ios15PerformHeightChange: ((() -> Void) -> Void)? { get set }
}

private struct _IOS15HostRenderContext: Equatable {
    let identity: AnyHashable?
    let revision: UInt
    let generation: UInt
    let width: CGFloat
}

private struct _IOS15HostRenderSample: Equatable {
    let context: _IOS15HostRenderContext
    let size: CGSize

    // Render revisions reject stale callbacks, but are NOT geometry changes.
    // Otherwise every text reconfigure evicts the same accepted height again.
    func needsPublication(comparedTo previous: Self?) -> Bool {
        guard let previous else { return true }
        return context.identity != previous.context.identity
            || abs(context.width - previous.context.width) > 0.5
            || abs(size.width - previous.size.width) > 0.5
            || abs(size.height - previous.size.height) > 0.5
    }
}

private struct _IOS15HostRenderHeightKey: PreferenceKey {
    // Absence is NOT a rendered zero (especially for an asynchronously mounted row).
    static var defaultValue: _IOS15HostRenderSample? { nil }
    static func reduce(value: inout _IOS15HostRenderSample?, nextValue: () -> _IOS15HostRenderSample?) {
        if let next = nextValue() { value = next }
    }
}

private final class _HostingContentCellView<Content: View>: UIView, UIContentView, IOS15HostingHeightResettable {
    func resetIOS15HostingHeightForConfirmedShrink() {
        ios15MonoH = 0
        shrinkCandidate = nil
        shrinkCandidateAt = 0
        ios15MonoHW = 0
        ios15LastGoodFitH = 0
        host?.view.invalidateIntrinsicContentSize()
        invalidateIntrinsicContentSize()
    }
    // A smaller positive fit is evidence, not permission to drop a live row.
    // Confirmation is time-separated, same graph/width, and never streaming.
    private var shrinkCandidate: CGFloat?
    private var shrinkCandidateAt: CFTimeInterval = 0
    private var shrinkRetryScheduled = false
    private var hostingRevision: UInt = 0

    private func owningCell() -> SelfSizingCell? {
        var ancestor = superview
        while let view = ancestor {
            if let cell = view as? SelfSizingCell { return cell }
            ancestor = view.superview
        }
        return nil
    }

    func consumeIOS15PendingStableShrink() {
        guard let (_, cv, ip, layout) = boundRow(),
              !cv.isTracking, !cv.isDragging, !cv.isDecelerating,
              !layout.deferSelfSizing,
              contentShapeChangePending || !layout.isStreamingCell(ip.item) else { return }
        // Also consume invalidation debt when ordinary fitting already accepted
        // the shrink and cleared its candidate. Comparing old/new mono here lost it.
        if shrinkCandidate != nil {
            _ = ios15FittingSize(CGSize(width: resolvedHostingWidth(bounds.width), height: 0))
        }
        publishPendingHeightChange()
    }

    private func scheduleStableShrinkRetry() {
        guard !shrinkRetryScheduled else { return }
        shrinkRetryScheduled = true
        let context = currentRenderContext()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { [weak self] in
            guard let self else { return }
            guard self.isCurrent(context) else {
                self.shrinkRetryScheduled = false
                // A stale timer must not steal a newer root's only retry.
                if self.shrinkCandidate != nil { self.scheduleStableShrinkRetry() }
                return
            }
            // Keep the flag set during measurement: at most one retry per
            // external fitting pass, never a self-sustaining timer loop.
            self.consumeIOS15PendingStableShrink()
            self.shrinkRetryScheduled = false
        }
    }

    // Root generation changes only when installing a root, NOT on layout callbacks.
    private var renderGeneration: UInt = 0
    private var renderedSample: _IOS15HostRenderSample?
    private var publishedRenderSample: _IOS15HostRenderSample?
    private var renderPublicationScheduled = false
    // An ordinary fitting pass can accept the shrink before the retry consumer.
    // Keep an explicit debt until ALL outer caches have been evicted afterward.
    private var heightInvalidationPending = false

    private func currentRenderContext() -> _IOS15HostRenderContext {
        _IOS15HostRenderContext(identity: hostedContentIdentity, revision: hostingRevision,
                                generation: renderGeneration, width: appliedHostWidth)
    }

    private func installRoot(_ config: UIHostingConfiguration<Content>, width: CGFloat) {
        appliedHostWidth = width
        renderGeneration &+= 1
        renderedSample = nil
        // Preserve published geometry across same-item/same-width roots. Only
        // the fresh sample's context must match the new revision/generation.
        if let previous = publishedRenderSample,
           previous.context.identity != hostedContentIdentity || abs(previous.context.width - width) > 0.5 {
            publishedRenderSample = nil
        }
        let context = currentRenderContext()
        host?.rootView = AnyView(
            config.content.id(config.contentIdentity)
                .frame(width: width, alignment: .leading)
                // Measure the complete NATURAL row, not the allocated UIKit wrapper.
                // Width stays proposed/full-cell; only the vertical proposal is ideal.
                .fixedSize(horizontal: false, vertical: true)
                .background(GeometryReader { geometry in
                    Color.clear.preference(key: _IOS15HostRenderHeightKey.self,
                        value: _IOS15HostRenderSample(context: context, size: geometry.size))
                })
                .onPreferenceChange(_IOS15HostRenderHeightKey.self) { [weak self] sample in
                    guard let sample else { return }
                    self?.receiveRenderedHeight(sample)
                }
                .frame(maxWidth: width, alignment: .leading)
        )
    }

    private func isCurrent(_ context: _IOS15HostRenderContext) -> Bool {
        context == currentRenderContext()
            && abs(resolvedHostingWidth(bounds.width) - context.width) <= 0.5
    }

    private var isFooter: Bool {
        guard let item = hostedContentIdentity?.base as? MessageListItem else { return false }
        if case .assistantFooter = item { return true }
        return false
    }

    private func receiveRenderedHeight(_ sample: _IOS15HostRenderSample) {
        // Preference delivery is normally on main; marshal before touching UIKit/state.
        if !Thread.isMainThread {
            DispatchQueue.main.async { [weak self] in self?.receiveRenderedHeight(sample) }
            return
        }
        guard isCurrent(sample.context), sample.size.height.isFinite,
              sample.size.width.isFinite, abs(sample.size.width - sample.context.width) <= 0.5,
              sample.size.height > 1 || (isFooter && sample.size.height == 0) else { return }
        if let old = renderedSample, old.context == sample.context,
           abs(old.size.height - sample.size.height) <= 0.5 { return }
        renderedSample = sample
        scheduleRenderPublication()
    }

    private func scheduleRenderPublication() {
        guard !renderPublicationScheduled else { return }
        renderPublicationScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.renderPublicationScheduled = false
            self.publishPendingHeightChange()
        }
    }

    private func boundRow() -> (SelfSizingCell, UICollectionView, IndexPath, MessageListLayout)? {
        guard window != nil, let identity = hostedContentIdentity?.base as? MessageListItem,
              let cell = owningCell(), let cv = cell.superview as? UICollectionView,
              let ip = cv.indexPath(for: cell),
              let ds = cv.dataSource as? UICollectionViewDiffableDataSource<CollectionViewMessageListV3.Section, MessageListItem>,
              ds.itemIdentifier(for: ip) == identity,
              let layout = cv.collectionViewLayout as? MessageListLayout else { return nil }
        return (cell, cv, ip, layout)
    }

    // Survives same-item root revisions: a committed expand/collapse is not
    // invalidated merely because a final text batch installs another root.
    private var contentShapeChangePending = false
    private var contentShape: AnyHashable?
    var ios15PerformHeightChange: ((() -> Void) -> Void)?

    func noteIOS15HostingContentShape(_ shape: AnyHashable) {
        let previous = contentShape
        contentShape = shape
        guard let previous, previous != shape else { return }
        contentShapeChangePending = true
        // Install one new geometry context for this discrete model transition.
        // Old queued preferences must not confirm a newer expand/collapse.
        if let config = configuration as? UIHostingConfiguration<Content> {
            installRoot(config, width: resolvedHostingWidth(bounds.width))
        }
        host?.view.invalidateIntrinsicContentSize()
        host?.view.setNeedsLayout()
        invalidateIntrinsicContentSize()
        setNeedsLayout()
    }

    private func rowIsIdle(_ cv: UICollectionView, _ layout: MessageListLayout) -> Bool {
        !cv.isTracking && !cv.isDragging && !cv.isDecelerating && !layout.deferSelfSizing
    }

    private func mayShrinkRow(_ cv: UICollectionView, _ ip: IndexPath, _ layout: MessageListLayout) -> Bool {
        guard rowIsIdle(cv, layout) else { return false }
        if contentShapeChangePending { return true }
        // Ordinary fits still require the original non-streaming contract.
        guard !layout.deferSelfSizing, !layout.isStreamingCell(ip.item) else { return false }
        return true
    }

    private func publishPendingHeightChange() {
        guard let (cell, cv, ip, layout) = boundRow() else { return }
        let sample = renderedSample.flatMap { isCurrent($0.context) ? $0 : nil }
        let changed = sample?.needsPublication(comparedTo: publishedRenderSample) ?? false
        // Explicit debts must survive geometry dedup; a shape needs a fresh
        // current-root sample, while an already accepted shrink can publish now.
        guard changed || heightInvalidationPending || (contentShapeChangePending && sample != nil) else { return }
        // A confirmed shrink's invalidation debt must also wait for settle;
        // apply(root revision) cannot erase it between fitting and publication.
        if heightInvalidationPending || contentShapeChangePending {
            guard rowIsIdle(cv, layout) else { return }
        }
        // Park a collapse while browsing/streaming. Do not remove layout's cached
        // height first: that would turn it into a 'first fit' and bypass defer.
        if let sample, sample.size.height < ios15MonoH - 8 || (sample.size.height == 0 && ios15MonoH > 0) {
            if shrinkCandidate == nil || abs((shrinkCandidate ?? 0) - sample.size.height) > 1 {
                shrinkCandidate = sample.size.height
                shrinkCandidateAt = CACurrentMediaTime()
            }
            guard mayShrinkRow(cv, ip, layout) else {
                scheduleStableShrinkRetry()
                return
            }
            // Model shape + current natural geometry is already independent
            // evidence. Ordinary fitter shrink still needs its 80ms confirm.
            guard contentShapeChangePending || CACurrentMediaTime() - shrinkCandidateAt >= 0.08 else {
                scheduleStableShrinkRetry()
                return
            }
            _ = ios15FittingSize(CGSize(width: appliedHostWidth, height: 0))
            guard ios15MonoH <= sample.size.height + 1 else { return }
        }
        // Invalidate only. preferred fitting -> layout's deferred/anchor machinery
        // commits the result; NEVER write setCachedHeight from a render callback.
        let publish = {
            cell.clearCachedHeight()
            layout.invalidateHeight(at: ip.item, discardPrecalc: true)
            if let key = cell.contentKey {
                layout.invalidateMemo(forKey: key)
                layout.invalidateMemo(forKey: SelfSizingCell.renderQualifiedKey(key, for: cell))
            }
            self.heightInvalidationPending = false
            self.publishedRenderSample = sample
            if sample != nil { self.contentShapeChangePending = false }
            self.host?.view.invalidateIntrinsicContentSize()
            self.invalidateIntrinsicContentSize()
            layout.invalidateLayout()
        }
        // A shrink can finish on the 120ms confirmation retry, outside scroll
        // settle. Its coordinator owns the anchor (and disables layout's second
        // offset adjustment) for exactly this synchronous cache eviction.
        if let transaction = ios15PerformHeightChange,
           heightInvalidationPending || contentShapeChangePending {
            transaction(publish)
        } else {
            publish()
        }
    }

    private func installHostedView(_ controller: UIHostingController<AnyView>) {
        guard controller.view.superview !== self else { return }
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: trailingAnchor),
            controller.view.topAnchor.constraint(equalTo: topAnchor),
            controller.view.bottomAnchor.constraint(equalTo: bottomAnchor)
        ])
    }

    private func reconcileHostParent() {
        guard let host else { return }
        var parent: UIViewController?
        if window != nil {
            var responder: UIResponder? = next
            while let current = responder {
                if let controller = current as? UIViewController, controller !== host {
                    parent = controller
                    break
                }
                responder = current.next
            }
        }
        guard host.parent !== parent else { return }
        if host.parent != nil {
            host.willMove(toParent: nil)
            host.view.removeFromSuperview()
            host.removeFromParent()
        }
        if let parent {
            parent.addChild(host)
            installHostedView(host)
            host.didMove(toParent: parent)
        } else {
            installHostedView(host) // retain graph off-window; no per-token mount churn
        }
    }

    override func didMoveToSuperview() {
        super.didMoveToSuperview()
        reconcileHostParent()
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        reconcileHostParent()
        if window != nil { scheduleRenderPublication() }
    }

    private func removeHostedController() {
        guard let host else { return }
        if host.parent != nil { host.willMove(toParent: nil) }
        host.view.removeFromSuperview()
        if host.parent != nil { host.removeFromParent() }
        self.host = nil
    }

    deinit { removeHostedController() }

    private var host: UIHostingController<AnyView>?
    private var appliedHostWidth: CGFloat = 0

    override func layoutSubviews() {
        super.layoutSubviews()
        guard let host, let config = configuration as? UIHostingConfiguration<Content>,
              bounds.width.isFinite, bounds.width > 1 else { return }
        let width = resolvedHostingWidth(bounds.width)
        guard abs(width - appliedHostWidth) > 0.5 else { return }
        appliedHostWidth = width
        installRoot(config, width: width)
        ios15MonoH = 0
        shrinkCandidate = nil
        shrinkCandidateAt = 0
        ios15MonoHW = 0
        ios15LastGoodFitH = 0
        host.view.invalidateIntrinsicContentSize()
        invalidateIntrinsicContentSize()
    }

    var configuration: UIContentConfiguration {
        didSet { apply(configuration) }
    }

    init(configuration: UIContentConfiguration) {
        self.configuration = configuration
        super.init(frame: .zero)
        backgroundColor = .clear
        apply(configuration)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }


    // ios15-port IOS15_HOSTING_FITTING
    // 集合视图自排版入口: 布局引擎问"给定宽度下你多高"。
    // 原替身没实现, 宽度会退化成 SwiftUI 理想宽(长文本远超屏宽 -> 左右被裁),
    // 高度也算错(单元格之间的黑块 / 内容贴不了底)。
    override func systemLayoutSizeFitting(_ targetSize: CGSize) -> CGSize {
        ios15FittingSize(targetSize)
    }

    override func systemLayoutSizeFitting(
        _ targetSize: CGSize,
        withHorizontalFittingPriority horizontalFittingPriority: UILayoutPriority,
        verticalFittingPriority: UILayoutPriority
    ) -> CGSize {
        ios15FittingSize(targetSize)
    }

    /// 递归保险。曾经在这里调 `host.view.systemLayoutSizeFitting(...)`：
    /// 宿主视图是四边钉在本视图上的，布局引擎解析它的尺寸时会反过来问
    /// "本视图多大"，于是又调回 systemLayoutSizeFitting —— 无限递归 →
    /// 栈溢出 EXC_BAD_ACCESS（实测崩溃栈: ios15FittingSize ↔
    /// _systemLayoutSizeFittingSize 反复嵌套）。所以这里只用
    /// `sizeThatFits` 这条不经过布局引擎的路径。
    // [V60-ZHAO-HOST] 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案:
    // SwiftUI hosting 层直接尺寸协商入口 —— 父视图走 sizeThatFits 路径
    // (不经过 systemLayoutSizeFitting)时也按传入真实宽向 SwiftUI 要高度,
    // 并 ceil 对齐像素。测量宽 == 渲染宽 → 高度不再错位。
    override func sizeThatFits(_ size: CGSize) -> CGSize {
        ios15FittingSize(size)
    }

    private var isMeasuring: Bool = false
    // [V64R-HOST] Content identity is independent of update count. The old
    // increment-then-compare generation check could never take the fast path.
    private var hostedContentIdentity: AnyHashable?
    private var lastLoggedWidth: CGFloat = -1
    private var ios15LastGoodFitH: CGFloat = 0
    private var lastHeightHoldLogAt: CFTimeInterval = 0
    // [V61-MONO] 高度单调锁状态: (历史最高, 绑定宽度)。宽变即重置。
    private var ios15MonoH: CGFloat = 0
    private var ios15MonoHW: CGFloat = 0

    // [V64R-WIDTH] Both UIKit fitting entry points measure the FULL cell.
    // The SwiftUI assistant block consumes its own 16pt horizontal padding;
    // subtracting another 32pt here measured a different line-wrap geometry.
    private func resolvedHostingWidth(_ proposed: CGFloat) -> CGFloat {
        var ancestor = superview
        var collectionWidth: CGFloat?
        while let view = ancestor {
            if let collection = view as? UICollectionView,
               collection.bounds.width.isFinite, collection.bounds.width > 1 {
                collectionWidth = collection.bounds.width
                break
            }
            ancestor = view.superview
        }
        // This layout allocates full-width cells. Its current width wins
        // over a stale pre-rotation cell bounds/proposed fitting width.
        if let collectionWidth { return collectionWidth }
        let localWidth = bounds.width.isFinite && bounds.width > 1 ? bounds.width : nil
        let windowWidth = window?.bounds.width
        let fallback = collectionWidth ?? localWidth
            ?? ((windowWidth?.isFinite == true && (windowWidth ?? 0) > 1) ? windowWidth! : UIScreen.main.bounds.width)
        guard proposed.isFinite, proposed > 1, proposed < 1_000_000 else { return fallback }
        return collectionWidth.map { min(proposed, $0) } ?? proposed
    }

    private func ios15FittingSize(_ targetSize: CGSize) -> CGSize {
        let width = resolvedHostingWidth(targetSize.width)
        let probeCvW = (superview?.superview as? UICollectionView)?.bounds.width ?? -1
        print("[IOS15Size] in targetW=\(targetSize.width) w=\(width) cellW=\(bounds.width) cvW=\(probeCvW) hostNil=\(host == nil)")
        guard let host = host, !isMeasuring else {
            return CGSize(width: width, height: max(0, bounds.height))
        }
        isMeasuring = true
        defer { isMeasuring = false }
        // A fitting pass may precede layoutSubviews after rotation/reuse.
        // Measure the same root-width contract that will actually render.
        if abs(width - appliedHostWidth) > 0.5,
           let config = configuration as? UIHostingConfiguration<Content> {
            appliedHostWidth = width
            installRoot(config, width: width)
            host.view.invalidateIntrinsicContentSize()
        }
        // [v25] 测量前先强制宿主视图布局: SwiftUI 内容未布局时 sizeThatFits 返回 0
        // (日志实证 56 次 out h=0.0 → cell 高度塌缩 → 整条消息不显示)。
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        var size = host.view.sizeThatFits(CGSize(width: width,
                                                 height: CGFloat.greatestFiniteMagnitude))
        if !size.height.isFinite || size.height <= 1 {
            size = host.view.sizeThatFits(CGSize(width: width, height: 0))
        }
        if abs(width - ios15MonoHW) > 0.5 {
            ios15MonoHW = width
            ios15MonoH = 0
            ios15LastGoodFitH = 0
            shrinkCandidate = nil
        }
        // Only a natural, rendered, current-width footer zero is evidence of
        // emptiness. A zero from UIKit's asynchronous fitter alone is NEVER so.
        let natural = renderedSample.flatMap { isCurrent($0.context) ? $0 : nil }
        let emptyFooter = isFooter && natural?.size.height == 0
            && size.height.isFinite && size.height <= 1 && size.height >= 0
        if let natural, natural.size.height > 1 || emptyFooter {
            size.height = natural.size.height
        }
        let diagnosticRawH = size.height
        let diagnosticLastGoodH = ios15LastGoodFitH
        var height = size.height
        // [v25] 仍失败且有历史好值 → 用历史好值兜底, 避免塌缩成 0。
        if (!height.isFinite || height <= 1) && !emptyFooter {
            height = ios15LastGoodFitH > 1 ? ios15LastGoodFitH : max(0, bounds.height)
        }
        print("[IOS15Size] out w=\(width) h=\(height) idealW=\(size.width) idealH=\(size.height)")
        // Do not promote a fallback to fresh evidence or preserve a high-water
        // value as the forever-zero fallback after an accepted shrink.
        let freshFit = (diagnosticRawH.isFinite && diagnosticRawH > 1) || emptyFooter
        let row = boundRow()
        let mayShrink = row.map { mayShrinkRow($0.1, $0.2, $0.3) } ?? false
        if freshFit, height < ios15MonoH - 8 || (emptyFooter && ios15MonoH > 0) {
            let now = CACurrentMediaTime()
            // A model shape transition can override the whole-message streaming
            // exclusion, but ONLY after current natural geometry arrives.
            let trustedShape = contentShapeChangePending && natural != nil
            if trustedShape, mayShrink {
                ios15MonoH = height
                ios15LastGoodFitH = height
                shrinkCandidate = nil
                heightInvalidationPending = true
                scheduleRenderPublication()
            } else if let candidate = shrinkCandidate, abs(height - candidate) <= 1,
               now - shrinkCandidateAt >= 0.08, mayShrink,
               !contentShapeChangePending || natural != nil {
                ios15MonoH = height
                ios15LastGoodFitH = height
                shrinkCandidate = nil
                heightInvalidationPending = true
                scheduleRenderPublication()
            } else {
                if shrinkCandidate == nil || abs(height - (shrinkCandidate ?? 0)) > 1 {
                    shrinkCandidate = height
                    shrinkCandidateAt = now
                }
                scheduleStableShrinkRetry()
            }
        } else if freshFit {
            shrinkCandidate = nil
        }
        // Keep the last *accepted* fit for zero/invalid transient fallback.
        // A held low candidate must not become the fallback before confirmation.
        // [V61-MONO] 单调锁生效点: 同宽下回缩超容差(8pt) → 沿用历史最高。
        // 挡住「测量管道抖动」(attachment 缓存时序导致同内容两次测量差
        // 157pt)直接上屏 —— 那就是用户看到的整屏跳动。
        if ios15MonoH > 0, (height > 1 && height < ios15MonoH - 8) || (emptyFooter && height == 0) {
            // Include small holds too; retain per-host throttling, not a size gate.
            do {
                let now = CACurrentMediaTime()
                if now - lastHeightHoldLogAt > 0.5 {
                    lastHeightHoldLogAt = now
                    var owner: UIView? = superview
                    while let v = owner, !(v is UICollectionViewCell) { owner = v.superview }
                    let cell = owner as? UICollectionViewCell
                    let cv = cell?.superview as? UICollectionView
                    let index = cell.flatMap { cv?.indexPath(for: $0)?.item } ?? -1
                    let itemID = (hostedContentIdentity?.base as? MessageListItem)?.scrollDiagnosticID ?? 0
                    print("[V64R-HOST-HOLD] item=\(itemID) cellItem=\((cell as? SelfSizingCell)?.scrollDiagnosticID ?? 0) host=\(UInt(bitPattern: Unmanaged.passUnretained(self).toOpaque())) cell=\(cell.map { UInt(bitPattern: Unmanaged.passUnretained($0).toOpaque()) } ?? 0) idx=\(index) incoming=\(targetSize.height) raw=\(diagnosticRawH) measured=\(height) lastGood=\(diagnosticLastGoodH) locked=\(ios15MonoH) final=\(ios15MonoH) width=\(width) tracking=\(cv?.isTracking == true ? 1 : 0) dragging=\(cv?.isDragging == true ? 1 : 0) decel=\(cv?.isDecelerating == true ? 1 : 0)")
                }
            }
            height = ios15MonoH
        }
        if height > ios15MonoH { ios15MonoH = height }
        if freshFit { ios15LastGoodFitH = height }
        return CGSize(width: width, height: max(0, height))
    }

    private func apply(_ config: UIContentConfiguration) {
        hostingRevision &+= 1
        // Same-item render revisions must not cancel an already accepted
        // shrink's outer-cache invalidation. Identity replacement below does.
        shrinkCandidate = nil
        shrinkCandidateAt = 0
        // Content identity owns the graph. Revision owns render callbacks only.
        if let existing = host, let newConfig = config as? UIHostingConfiguration<Content>,
           let identity = newConfig.contentIdentity, identity == hostedContentIdentity {
            _V63Probe.hitFast()
            installRoot(newConfig, width: resolvedHostingWidth(bounds.width))
            // Keep accepted fallback for this item; new natural rendering provides
            // growth/shrink evidence without a per-token remove/addChild cycle.
            existing.view.invalidateIntrinsicContentSize()
            invalidateIntrinsicContentSize()
            existing.view.setNeedsLayout()
            setNeedsLayout()
            return
        }
        _V63Probe.hitRebuild()
        removeHostedController()
        heightInvalidationPending = false
        contentShapeChangePending = false
        contentShape = nil
        ios15PerformHeightChange = nil
        hostedContentIdentity = nil
        renderGeneration &+= 1
        renderedSample = nil
        publishedRenderSample = nil
        ios15MonoH = 0
        ios15MonoHW = 0
        ios15LastGoodFitH = 0
        guard let config = config as? UIHostingConfiguration<Content> else { return }
        hostedContentIdentity = config.contentIdentity
        let controller = UIHostingController(rootView: AnyView(EmptyView()))
        controller.view.backgroundColor = .clear
        controller.view.clipsToBounds = true
        host = controller
        installRoot(config, width: resolvedHostingWidth(bounds.width))
        // addChild must precede insertion and didMove must follow it.
        reconcileHostParent()
        installHostedView(controller)
    }

}

public struct UIHostingConfiguration<Content: View>: UIContentConfiguration {
    public let content: Content
    private let _minWidth: CGFloat?
    private let _minHeight: CGFloat?
    fileprivate var contentIdentity: AnyHashable?

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
        self._minWidth = nil
        self._minHeight = nil
        self.contentIdentity = nil
    }

    private init(content: Content, minWidth: CGFloat?, minHeight: CGFloat?, contentIdentity: AnyHashable?) {
        self.content = content
        self._minWidth = minWidth
        self._minHeight = minHeight
        self.contentIdentity = contentIdentity
    }

    // Identity must include the message and block, not its changing text hash.
    public func ios15ContentIdentity<ID: Hashable>(_ identity: ID) -> UIHostingConfiguration<Content> {
        var result = self
        result.contentIdentity = AnyHashable(identity)
        return result
    }

    public func minSize(width: CGFloat? = nil, height: CGFloat? = nil)
    -> UIHostingConfiguration<Content> {
        UIHostingConfiguration(content: content, minWidth: width, minHeight: height, contentIdentity: contentIdentity)
    }

    public func margins(_ edges: Edge.Set = .all, _ length: CGFloat? = nil)
    -> UIHostingConfiguration<Content> {
        self  // iOS 15 的替身不实现边距；cell 自身已按 zero margins 布局
    }

    public func makeContentView() -> UIView & UIContentView {
        _HostingContentCellView<Content>(configuration: self)
    }

    public func updated(for state: UIConfigurationState) -> UIHostingConfiguration<Content> {
        self
    }
}

// MARK: - PhotosPickerItem (iOS 16)

/// `PhotosUI.PhotosPickerItem` 的 iOS 15 替身。
///
///  photo picker 本身（`PhotosPicker` / `.photosPicker`）在 iOS 15 不存在，
///  移植脚本会摘掉那些 modifier，所以这里的实例永远是"空"的：
///  `loadTransferable` 返回 nil，相关代码自然走失败分支而不是崩溃。
public struct PhotosPickerItem: Hashable {
    public init() {}

    public var itemIdentifier: String? { nil }
    public var supportedContentTypes: [UTType] { [] }

    public func loadTransferable<T>(type: T.Type) async throws -> T? { nil }

    public static func == (lhs: PhotosPickerItem, rhs: PhotosPickerItem) -> Bool { true }
    public func hash(into hasher: inout Hasher) {}
}

// MARK: - Transferable / ShareLink (iOS 16)

/// iOS 16 的 `Transferable` 协议替身。仅用于让 `struct X: Transferable`
/// 的声明继续成立；真正的传输行为在 iOS 15 上不可用。
public protocol Transferable {}

public enum MinisSharePresenter {
    public static func present(items: [Any]) {
        let vc = UIActivityViewController(activityItems: items, applicationActivities: nil)
        guard let scene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive }),
              let window = scene.windows.first(where: { $0.isKeyWindow })
                ?? scene.windows.first,
              let root = window.rootViewController else { return }
        var presenter = root
        while let presented = presenter.presentedViewController {
            presenter = presented
        }
        presenter.present(vc, animated: true)
    }
}

// MARK: - Regex 字面量替身 (iOS 16)

/// iOS 16 的 `Regex` 字面量 (`/…/`) 与 `wholeMatch(of:)` / `ranges(of:)`
/// 在 iOS 15 没有对应物，移植脚本把它们改写成这里的 NSRegularExpression 包装。
public enum MinisRegex {
    public static func wholeMatch(_ text: String, _ pattern: String) -> Bool {
        let full = NSRange(text.startIndex..., in: text)
        guard let re = try? NSRegularExpression(pattern: pattern),
              let m = re.firstMatch(in: text, range: full) else { return false }
        return NSEqualRanges(m.range, full)
    }

    public static func ranges(_ text: String, _ pattern: String) -> [Range<String.Index>] {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return [] }
        let full = NSRange(text.startIndex..., in: text)
        return re.matches(in: text, range: full).compactMap { Range($0.range, in: text) }
    }
}

// MARK: - MinisShareLinkButton (ShareLink 替代, iOS 15)

/// iOS 15 没有 `ShareLink`（它是 iOS 16 才有的），这里用 `UIActivityViewController`
/// 包一个等价的分享按钮。stage3 把源码里的 `ShareLink(...)` 整调用替换成它，
/// 调用点不用改。支持 `ShareLink(item:)` / `ShareLink(item:subject:message:)` /
/// `ShareLink("标题", item:)` 三种写法。
import UIKit
import PhotosUI

public struct MinisShareLinkButton: View {
    public let item: Any
    public var subject: String? = nil
    public var message: String? = nil

    public init(item: Any, subject: String? = nil, message: String? = nil) {
        self.item = item
        self.subject = subject
        self.message = message
    }

    public init(_ label: String, item: Any) {
        self.item = item
        self.subject = nil
        self.message = nil
    }

    public var body: some View {
        Button(action: { share() }) {
            Label("Share", systemImage: "square.and.arrow.up")
        }
    }

    private func share() {
        let items: [Any]
        if let url = item as? URL {
            items = [url]
        } else if let str = item as? String {
            items = [str]
        } else {
            items = [item]
        }
        let av = UIActivityViewController(activityItems: items,
                                          applicationActivities: nil)
        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let root = scene.windows.first?.rootViewController {
            av.popoverPresentationController?.sourceView = root.view
            root.present(av, animated: true, completion: nil)
        }
    }
}


// iOS15_RUNTIME_FIX_APPLIED 1.14
/// iOS 15 photo + document pickers (UIKit-based; bypasses SwiftUI's broken
/// multi-sheet chain on iOS 15 which silently drops presentations).
enum UIKitPickerPresenter {
    /// [T-picker-present-race] 原来的做法是"固定等 0.45 秒再弹"。如果那时上一个
    /// 弹窗（相册/文件选择前面的那个操作菜单）还没完全消失、或转场还没结束，
    /// 选择器会被硬塞进去：先闪一下内容，随后整片空白，得退出来再点一次才好。
    /// 现在改成等"上一个弹窗真的走完"再弹，并且最多重试 ~2 秒。
    static func present(_ vc: UIViewController, attempt: Int = 0) {
        DispatchQueue.main.async {
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard var top = scenes.flatMap({ $0.windows }).first(where: { $0.isKeyWindow })?.rootViewController else {
                return
            }
            while let presented = top.presentedViewController, !presented.isBeingDismissed {
                top = presented
            }
            // 注意：不要在 iOS 15 上用 transitionCoordinator.isRunning —— 该属性
            // 不存在（CI 编译直接报 "has no member 'isRunning'"）。这里只依据
            // 「是否还在关闭中 / 是否还是操作菜单 / 是否还有被呈现的控制器」判断。
            let settling = top.isBeingDismissed
                || top is UIAlertController          // 操作菜单还在：等它消失
            if settling, attempt < 16 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                    present(vc, attempt: attempt + 1)
                }
                return
            }
            guard top.presentedViewController == nil, vc.presentingViewController == nil else {
                if attempt < 16 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                        present(vc, attempt: attempt + 1)
                    }
                }
                return
            }
            top.present(vc, animated: true)
        }
    }
}

final class AttachmentPickerCoordinator: NSObject, PHPickerViewControllerDelegate, UIDocumentPickerDelegate {
    var onPhotos: (([PHPickerResult]) -> Void)?
    var onFiles: (([URL]) -> Void)?

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        picker.dismiss(animated: true)
        onPhotos?(results)
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        onFiles?(urls)
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {}
}

struct PHPickerView: UIViewControllerRepresentable {
    let onPicked: ([PHPickerResult]) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .any(of: [.images, .videos])
        config.selectionLimit = 0
        config.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPicked: ([PHPickerResult]) -> Void
        init(onPicked: @escaping ([PHPickerResult]) -> Void) { self.onPicked = onPicked }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            onPicked(results)
        }
    }
}


// MARK: - onGeometryChange 回填 (iOS 16 API)
// ios15-port IOS15_GEOM_BACKPORT  (见 scripts/ios15_fallback.py)
// 复刻 iOS 16 `onGeometryChange(for:of:action:)`：把被测视图的几何值转成
// Preference，值变化时才回调 action。iOS 15 无此 API，而它承载着输入栏高度等
// 关键测量（缺失会导致最后一条消息被输入栏盖住、底部渲染成黑区）。

private struct IOS15GeometryValueKey<T: Equatable>: PreferenceKey {
    static var defaultValue: T? { nil }
    static func reduce(value: inout T?, nextValue: () -> T?) {
        if let next = nextValue() { value = next }
    }
}

extension View {
    func onGeometryChange15<T: Equatable>(
        for type: T.Type,
        of transform: @escaping (GeometryProxy) -> T,
        action: @escaping (T) -> Void
    ) -> some View {
        self
            .background(
                GeometryReader { proxy in
                    Color.clear
                        .preference(key: IOS15GeometryValueKey<T>.self,
                                    value: transform(proxy))
                        .allowsHitTesting(false)
                }
            )
            .onPreferenceChange(IOS15GeometryValueKey<T>.self) { value in
                if let value = value { action(value) }
            }
    }
}
import SwiftUI
import UIKit

// [T-floating-circle-toolbar] 全 App 统一的「浮起来的圆钮」。
//
// 用户 2026-10-26 的要求：列表页右上那颗终端、左上那颗设置，以及会话页的
// 返回键，都要和聊天页「…」按钮长得一样——不是一个画上去的圆圈，而是白底、
// 极细描边、带柔和投影，看着浮在导航栏上。
//
// [T-frosted-circle-3] 数值必须和「…」按钮完全一致（用户 2026-10-26 反馈
// 返回键看着"没有朦胧感、磨砂感"）：之前这里用 systemBackground（深色下是纯黑）、
// 材质只给 0.55、投影也偏弱，结果在深色界面上是一块死板的深灰圆盘；「…」用的是
// 0.24 的灰底 + 0.85 的材质 + 更强的投影，才有磨砂玻璃的通透。
//
// 两个要点：
// ① 投影必须由「不透明的圆」投出来——ultraThinMaterial 没有形状级的透明度，
//    SwiftUI 按矩形给它算阴影，圆钮底下会出现一圈圆角方影。
// ② 尺寸 34pt，外面留到 44pt 给投影和触控（HIG 最小 44）。
struct FloatingCircleChrome: ViewModifier {
    var diameter: CGFloat

    func body(content: Content) -> some View {
        content
            .frame(width: diameter, height: diameter)
            .background {
                ZStack {
                    // 纯色圆：投影的剪影，负责"浮起来"。
                    Circle()
                        .fill(Color(UIColor { traits in
                            traits.userInterfaceStyle == .dark
                                ? UIColor(white: 0.24, alpha: 1)
                                : UIColor.white
                        }))
                        .shadow(color: Color(UIColor { traits in
                            traits.userInterfaceStyle == .dark
                                ? UIColor(white: 0, alpha: 0.45)
                                : UIColor(white: 0, alpha: 0.10)
                        }), radius: 2, x: 0, y: 1)
                        .shadow(color: Color(UIColor { traits in
                            traits.userInterfaceStyle == .dark
                                ? UIColor(white: 0, alpha: 0.50)
                                : UIColor(white: 0, alpha: 0.16)
                        }), radius: 5, x: 0, y: 2)
                    // 系统材质：实时模糊才是"磨砂"的来源。
                    Circle()
                        .fill(.ultraThinMaterial)
                        .opacity(0.85)
                    // 0.5 点描边收口，否则材质边缘会糊进导航栏底色。
                    Circle()
                        .strokeBorder(Color(UIColor { traits in
                            traits.userInterfaceStyle == .dark
                                ? UIColor(white: 1, alpha: 0.10)
                                : UIColor(white: 0, alpha: 0.06)
                        }), lineWidth: 0.5)
                }
            }
            .frame(width: 44, height: 44)
    }
}

extension View {
    /// 包成 34pt 白底圆钮（外框 44pt）。
    func floatingCircleChrome(diameter: CGFloat = 34) -> some View {
        modifier(FloatingCircleChrome(diameter: diameter))
    }
}

// [T-floating-circle-back] 自绘返回键的配套：把侧滑返回救回来。
//
// 隐藏系统返回键（.navigationBarBackButtonHidden）后，UINavigationController
// 会把 interactivePopGestureRecognizer 的 delegate 设回自己，并在返回按钮为
// nil 时把侧滑手势关掉。这里把 delegate 摘掉、在手势确实能 pop（栈深 > 1）
// 时重新启用，等于恢复系统的侧滑行为。
struct SwipeBackEnabler: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> UIViewController {
        SwipeBackProbe()
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {
        (uiViewController as? SwipeBackProbe)?.apply()
    }
}

final class SwipeBackProbe: UIViewController {
    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        apply()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        apply()
    }

    func apply() {
        DispatchQueue.main.async { [weak self] in
            guard let nav = self?.navigationController,
                  let gesture = nav.interactivePopGestureRecognizer else { return }
            // [T-floating-circle-back-pop] 记住这条导航栈，返回键直接 pop 它。
            NavPopBridge.navigationController = nav
            // 只接管一次；反复设 nil 会让正在进行的侧滑被中途取消。
            if gesture.delegate !== nav || gesture.isEnabled == false {
                gesture.delegate = nil
            }
            gesture.isEnabled = nav.viewControllers.count > 1
        }
    }
}

// [T-floating-circle-back-pop] 返回键不靠 SwiftUI 的 dismiss。
//
// 用户 2026-10-26 反馈「会话页返回键有时候不生效」。这个 App 在 iOS 15 上用的是
// 自己写的 NavigationStack 兜底（隐藏 NavigationLink + isActive 绑定），
// dismiss 能不能落地取决于那条绑定的当前状态——栈被「resync」替换过之后，
// SwiftUI 认为已经没东西可 pop 了，按钮就变成点了没反应。
// 直接拿真实的 UINavigationController 弹栈是确定性的：栈里还有上一页就弹，
// 弹完 SwiftUI 那条 isActive 绑定会被系统同步回 false，路径跟着清空。
enum NavPopBridge {
    static weak var navigationController: UINavigationController?

    /// 返回是否真的弹了栈。false 表示没有可弹的导航栈，调用方再退回 dismiss。
    @discardableResult
    static func popTop() -> Bool {
        guard let nav = navigationController, nav.viewControllers.count > 1 else {
            return false
        }
        nav.popViewController(animated: true)
        return true
    }
}

private let navGlassLogger = AppLogger(category: "NavGlass")

// [T-navbar-glass] 导航栏底下那块毛玻璃。
//
// 用户 2026-10-26 给的参照：会话页标题/返回/「…」下面那块板，是「比页面亮一档的
// 深色玻璃」——底色 #292929 左右，页面才 #0a0a0a；底下内容糊成大块光斑、认不出字；
// 只有背景被糊，按钮和标题始终清晰；板底是一条硬边，不是渐变消失。
//
// 做法（不是截图 PS）：
// ① UIVisualEffectView + UIBlurEffect(systemUltraThinMaterial*)，实时采样，GPU 合成；
// ② 上面叠一层很淡的白（深色 10%，浅色 35%）把整块抬亮一档；
// ③ 底部 1 像素发丝线做硬边；
// ④ 跟着列表滚动淡入淡出：会话在顶部时 alpha 0（跟原来一模一样），
//    内容往上滚 20pt 内渐显到 1；
// ⑤ 整块不接收触摸，按钮照常点。
//
// 位置：插在导航栏正下方（nav.view 里 navigationBar 的下一个兄弟位），
// 上面是系统导航栏（按钮层），下面是页面内容——不会盖住返回键。
struct NavBarGlassBackground: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> UIViewController {
        NavBarGlassProbe()
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {}
}

final class NavBarGlassProbe: UIViewController {
    private weak var containerView: UIView?
    private weak var blurView: UIVisualEffectView?
    private weak var tintView: UIView?
    private weak var hairline: UIView?
    private weak var observedScroll: UIScrollView?
    private var offsetObservation: NSKeyValueObservation?
    private var retries = 0

    /// 我们要把系统导航栏自己的底色清掉，否则它会盖住这块玻璃——
    /// 现在用户看到的「半行字被硬切」，就是系统那层近乎不透明的材质。
    private var clearAppearance: UINavigationBarAppearance?
    private weak var patchedBar: UINavigationBar?
    private var savedStandard: UINavigationBarAppearance?
    private var savedScrollEdge: UINavigationBarAppearance?
    private var savedCompact: UINavigationBarAppearance?
    private var savedTranslucent = true

    /// 滚动多少点才算「完全显形」。
    private let fadeDistance: CGFloat = 20

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        install()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        teardown()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        layoutGlass()
    }

    override func traitCollectionDidChange(_ previous: UITraitCollection?) {
        super.traitCollectionDidChange(previous)
        guard previous?.userInterfaceStyle != traitCollection.userInterfaceStyle else { return }
        applyColors()
    }

    // MARK: - 安装

    private func install() {
        DispatchQueue.main.async { [weak self] in
            guard let this = self, let nav = this.navigationController else { return }
            if this.containerView == nil { this.build(in: nav) }
            this.layoutGlass()
            if this.observedScroll == nil { this.attachScrollObserver(in: nav) }
        }
    }

    private func build(in nav: UINavigationController) {
        let container = UIView()
        container.isUserInteractionEnabled = false
        container.backgroundColor = .clear

        let blur = UIVisualEffectView(effect: Self.blurEffect(for: traitCollection))
        blur.isUserInteractionEnabled = false
        container.addSubview(blur)

        let tint = UIView()
        tint.isUserInteractionEnabled = false
        container.addSubview(tint)

        let line = UIView()
        line.isUserInteractionEnabled = false
        container.addSubview(line)

        // [T-navbar-glass-always] 常态显示，不再跟着滚动淡入淡出。
        //
        // 两个原因：
        // ① UIVisualEffectView 的祖先只要 alpha < 1，磨砂层就会被压成一块
        //    平的色块（UIKit 的既定行为），而这段玻璃正是靠容器 alpha 做淡入的。
        //    实测：日志 alpha=1.00 时仍然是死灰板，用户连试三版都"没有模糊感"。
        // ② 系统导航栏本来就是常驻的，不必等滚动。
        container.alpha = 1
        // 插在导航栏正下方：上面是按钮层，下面才是页面内容。
        if nav.navigationBar.superview === nav.view {
            nav.view.insertSubview(container, belowSubview: nav.navigationBar)
        } else {
            nav.view.addSubview(container)
        }

        containerView = container
        blurView = blur
        tintView = tint
        hairline = line
        applyColors()
    }

    private static func blurEffect(for traits: UITraitCollection) -> UIBlurEffect {
        traits.userInterfaceStyle == .dark
            ? UIBlurEffect(style: .systemUltraThinMaterialDark)
            : UIBlurEffect(style: .systemUltraThinMaterialLight)
    }

    private func applyColors() {
        let dark = traitCollection.userInterfaceStyle == .dark
        blurView?.effect = Self.blurEffect(for: traitCollection)
        // 把整块抬到「比页面亮一档」。数值先给深色 10% 白、浅色 35% 白，
        // 真机看效果再调（参照图栏内 #292929、页面 #0a0a0a）。
        // 深色一档先给 6%：真机上 10% 把栏抬得比参照图（#292929）还亮。
        // 浅色档从 30% 白降到 12%：30% 叠在白色页面上几乎把内容糊死，
        // 看上去就是一块灰白板，完全没有"透"的感觉。
        tintView?.backgroundColor = dark
            ? UIColor(white: 1, alpha: 0.06)
            : UIColor(white: 1, alpha: 0.12)
        hairline?.backgroundColor = dark
            ? UIColor(white: 1, alpha: 0.10)
            : UIColor(white: 0, alpha: 0.08)
    }

    private func layoutGlass() {
        guard let container = containerView,
              let nav = navigationController else { return }
        releaseBarBackgroundIfNeeded(nav.navigationBar)
        ensureOrdering(in: nav)
        let width = nav.view.bounds.width
        // 导航栏在 nav.view 里的真实位置（iOS 15 上它位于状态栏下面，
        // 直接用 navigationBar.frame 会少掉状态栏那一段）。
        let barRect = nav.navigationBar.convert(nav.navigationBar.bounds, to: nav.view)
        // 从屏幕最顶端一直铺到导航栏底边（连状态栏一起糊）。
        let height = max(barRect.maxY, nav.view.safeAreaInsets.top)
        let target = CGRect(x: 0, y: 0, width: width, height: height)
        if container.frame != target {
            container.frame = target
            blurView?.frame = container.bounds
            tintView?.frame = container.bounds
            hairline?.frame = CGRect(x: 0, y: height - 1, width: width, height: 1)
        }
    }

    // MARK: - 跟随滚动淡入淡出

    /// 玻璃必须紧贴在导航栏下面一层；SwiftUI 重排子视图时可能把内容视图
    /// 又插到我们上面（那层是整页不透明底色，会直接吃掉落玻璃），这里校正。
    private func ensureOrdering(in nav: UINavigationController) {
        guard let container = containerView else { return }
        let bar = nav.navigationBar
        guard let cIndex = nav.view.subviews.firstIndex(of: container),
              let bIndex = nav.view.subviews.firstIndex(of: bar) else { return }
        if bIndex != cIndex + 1 {
            nav.view.insertSubview(container, belowSubview: bar)
            navGlassLogger.info("[NavGlass] reordered container under navigation bar")
        }
    }

    /// 系统导航栏那层近不透明的材质会把我们的玻璃挡住，清掉它。
    /// 只在被系统改回去时重设（用对象身份判断，滚动时几乎零成本）。
    private func releaseBarBackgroundIfNeeded(_ bar: UINavigationBar) {
        if clearAppearance == nil {
            let appearance = UINavigationBarAppearance()
            appearance.configureWithTransparentBackground()
            appearance.backgroundEffect = nil
            appearance.backgroundColor = .clear
            appearance.shadowColor = .clear
            appearance.titleTextAttributes = bar.standardAppearance.titleTextAttributes
            appearance.largeTitleTextAttributes = bar.standardAppearance.largeTitleTextAttributes
            clearAppearance = appearance
        }
        guard let appearance = clearAppearance,
              bar.standardAppearance !== appearance else { return }
        if patchedBar !== bar {
            savedStandard = bar.standardAppearance
            savedScrollEdge = bar.scrollEdgeAppearance
            savedCompact = bar.compactAppearance
            savedTranslucent = bar.isTranslucent
            patchedBar = bar
        }
        bar.isTranslucent = true
        bar.standardAppearance = appearance
        bar.scrollEdgeAppearance = appearance
        bar.compactAppearance = appearance
    }

    /// 离开这一页时把系统导航栏还原，列表页那边保持原样。
    private func restoreBarBackground() {
        guard let bar = patchedBar else { return }
        if let savedStandard { bar.standardAppearance = savedStandard }
        if let savedScrollEdge { bar.scrollEdgeAppearance = savedScrollEdge }
        if let savedCompact { bar.compactAppearance = savedCompact }
        bar.isTranslucent = savedTranslucent
        patchedBar = nil
        savedStandard = nil
        savedScrollEdge = nil
        savedCompact = nil
    }

    private func attachScrollObserver(in nav: UINavigationController) {
        let found = Self.firstScrollView(in: nav.topViewController?.view ?? nav.view)
            ?? Self.firstScrollView(in: nav.view)
        guard let scroll = found else {
            // 列表可能还没挂上来：0.1s 一次、最多 5 秒，找到就停。
            if retries < 50 {
                retries += 1
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                    self?.install()
                }
            } else {
                navGlassLogger.warning("[NavGlass] scroll view not found, glass stays hidden")
            }
            return
        }
        observedScroll = scroll
        offsetObservation = scroll.observe(\UIScrollView.contentOffset,
                                           options: [.initial, .new]) { [weak self] scrollView, _ in
            self?.updateAlpha(for: scrollView)
        }
    }

    private static func firstScrollView(in view: UIView) -> UIScrollView? {
        if let scroll = view as? UIScrollView { return scroll }
        for sub in view.subviews {
            if let found = firstScrollView(in: sub) { return found }
        }
        return nil
    }

    private func updateAlpha(for scroll: UIScrollView) {
        layoutGlass()
        // [T-navbar-glass-always] 不再按滚动位置改 alpha（见 build 里的说明）：
        // 祖先 alpha < 1 会把磨砂压平，这正是"玻璃永远不糊"的直接原因。
        if let c = containerView, c.alpha != 1 { c.alpha = 1 }
        _ = scroll
    }

    // MARK: - 拆

    private func teardown() {
        restoreBarBackground()
        offsetObservation?.invalidate()
        offsetObservation = nil
        observedScroll = nil
        containerView?.removeFromSuperview()
        containerView = nil
    }
}
