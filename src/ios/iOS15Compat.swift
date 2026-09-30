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
private final class _HostingContentCellView<Content: View>: UIView, UIContentView {
    private var host: UIHostingController<AnyView>?
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
    private var isMeasuring: Bool = false
    private var lastLoggedWidth: CGFloat = -1

    private func ios15FittingSize(_ targetSize: CGSize) -> CGSize {
        var width = targetSize.width
        // ⚠️ 关键: 布局引擎问"压缩尺寸"时传的是 UIView.layoutFittingCompressedSize,
        // 宽高都是 Double.greatestFiniteMagnitude (≈1.8e308)。它是**有限数**,
        // 所以 `width.isInfinite` 拦不住 —— 之前直接把它当真实宽度交给 SwiftUI,
        // 内容按无界宽度排版: 长文本不换行、按自然宽度居中渲染 → 左右被裁;
        // 同时 TextKit 在这个荒谬宽度下抛 NSException → 自排版永远退回估算
        // 高度 → 单元格之间大片黑块（日志实测 1977 次全部 threw）。
        // 这里把"未指定/哨兵"宽度替换成集合视图的真实宽度。
        if !(width > 0) || width.isInfinite || width >= 1_000_000 {
            var probe: UIView? = superview
            var cvW: CGFloat = 0
            while let v = probe {
                if let collection = v as? UICollectionView {
                    cvW = collection.bounds.width
                    break
                }
                probe = v.superview
            }
            width = cvW > 0 ? cvW : (window?.bounds.width ?? UIScreen.main.bounds.width)
        }
        let probeCvW = (superview?.superview as? UICollectionView)?.bounds.width ?? -1
        print("[IOS15Size] in targetW=\(targetSize.width) w=\(width) cellW=\(bounds.width) cvW=\(probeCvW) hostNil=\(host == nil)")
        guard let host = host, !isMeasuring else {
            return CGSize(width: width, height: max(0, bounds.height))
        }
        isMeasuring = true
        defer { isMeasuring = false }
        var size = host.view.sizeThatFits(CGSize(width: width,
                                                 height: CGFloat.greatestFiniteMagnitude))
        if !(size.height > 0) {
            size = host.view.sizeThatFits(CGSize(width: width, height: 0))
        }
        var height = size.height
        if !(height > 0) { height = bounds.height }
        print("[IOS15Size] out w=\(width) h=\(height) idealW=\(size.width) idealH=\(size.height)")
        return CGSize(width: width, height: max(0, height))
    }

    private func apply(_ config: UIContentConfiguration) {
        subviews.forEach { $0.removeFromSuperview() }
        host = nil
        guard let config = config as? UIHostingConfiguration<Content> else { return }
        let controller = UIHostingController(rootView: AnyView(config.content))
        controller.view.backgroundColor = .clear
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: trailingAnchor),
            controller.view.topAnchor.constraint(equalTo: topAnchor),
            controller.view.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        host = controller
    }
}

public struct UIHostingConfiguration<Content: View>: UIContentConfiguration {
    public let content: Content
    private let _minWidth: CGFloat?
    private let _minHeight: CGFloat?

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
        self._minWidth = nil
        self._minHeight = nil
    }

    private init(content: Content, minWidth: CGFloat?, minHeight: CGFloat?) {
        self.content = content
        self._minWidth = minWidth
        self._minHeight = minHeight
    }

    public func minSize(width: CGFloat? = nil, height: CGFloat? = nil)
    -> UIHostingConfiguration<Content> {
        UIHostingConfiguration(content: content, minWidth: width, minHeight: height)
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
    static func present(_ vc: UIViewController) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard var top = scenes.flatMap({ $0.windows }).first(where: { $0.isKeyWindow })?.rootViewController else {
                return
            }
            while let presented = top.presentedViewController, !presented.isBeingDismissed {
                top = presented
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
