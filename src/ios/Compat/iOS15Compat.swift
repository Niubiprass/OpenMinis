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

// MARK: - AnyShape (iOS 16)

/// Type-erased `Shape`. iOS 16 ships this; iOS 15 needs a hand-rolled version.
public struct AnyShape: Shape {
    private let _path: (CGRect) -> Path

    public init<S: Shape>(_ wrapped: S) {
        _path = wrapped.path(in:)
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
}

// MARK: - ProposedViewSize (iOS 16)

/// Size proposal used by `UIViewRepresentable.sizeThatFits`.
public struct ProposedViewSize: Equatable {
    public var width: CGFloat?
    public var height: CGFloat?

    public init(width: CGFloat? = nil, height: CGFloat? = nil) {
        self.width = width
        self.height = height
    }

    public init(_ size: CGSize) {
        self.width = size.width
        self.height = size.height
    }

    public static let zero = ProposedViewSize(width: 0, height: 0)
    public static let infinity = ProposedViewSize(width: .infinity, height: .infinity)
    public static let unspecified = ProposedViewSize(width: nil, height: nil)

    public func replacingUnspecifiedDimensions(by size: CGSize) -> CGSize {
        CGSize(width: width ?? size.width, height: height ?? size.height)
    }
}
