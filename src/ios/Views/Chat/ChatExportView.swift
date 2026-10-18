import SwiftUI
import UIKit
import QuickLook

// MARK: - [T-115-export] 分享对话为长图或 PDF (App Store 1.15)
//
// Port scope (iOS 15.5): whole-conversation export as a long image or a
// multi-page PDF. Header shows the assistant icon, the last model name and
// the date; appearance follows the current light/dark mode. Thinking blocks
// collapse to a one-line meta row and tool calls to one-line summaries
// (v1 keeps exports compact; the official "drag to select a range" and
// "fold/hide tool calls" options are out of scope here).
//
// NOT implemented: drag-range selection, per-item fold/hide toggles,
// width presets (phone/iPad/adaptive). The exported width is the phone
// width (390pt), which reads well everywhere.

enum ChatExportKind: Identifiable {
    case longImage
    case pdf

    var id: Self { self }

    var title: String {
        switch self {
        case .longImage: return AppLocalized("导出长图")
        case .pdf: return AppLocalized("导出 PDF")
        }
    }
}

// MARK: - Renderer

enum ChatExportRenderer {

    enum RowKind {
        case user      // right-aligned bubble
        case assistant // left-aligned bubble
        case meta      // plain muted line (thinking / tools / dividers)
    }

    struct Row {
        let kind: RowKind
        let text: String
    }

    static func buildRows(from messages: [RawMessage]) -> [Row] {
        var rows: [Row] = []
        for m in messages {
            switch m.role {
            case .user:
                if m.isToolResultOnly { continue }
                let texts = m.parts.compactMap { part -> String? in
                    if case .text(let s) = part { return s }
                    return nil
                }
                let t = texts.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty { rows.append(Row(kind: .user, text: t)) }
            case .assistant:
                var textParts: [String] = []
                var toolLines: [String] = []
                for part in m.parts {
                    switch part {
                    case .text(let s):
                        if !s.isEmpty { textParts.append(s) }
                    case .toolUse(let tu):
                        toolLines.append("⚙︎ \(tu.name)")
                    case .toolResult(let tr):
                        let head = tr.output.replacingOccurrences(of: "\n", with: " ")
                        toolLines.append("→ \(head.prefix(80))")
                    case .mediaRef:
                        break
                    }
                }
                if let rc = m.reasoningContent, !rc.isEmpty {
                    let head = rc.replacingOccurrences(of: "\n", with: " ")
                    rows.append(Row(kind: .meta, text: "思考 · \(head.prefix(120))…"))
                }
                if !textParts.isEmpty {
                    rows.append(Row(kind: .assistant, text: textParts.joined(separator: "\n")))
                }
                if !toolLines.isEmpty {
                    rows.append(Row(kind: .meta, text: toolLines.joined(separator: "\n")))
                }
            }
        }
        return rows
    }

    // MARK: Metrics

    static let pageMargin: CGFloat = 16
    static let bubblePadding: CGFloat = 12
    static let rowGap: CGFloat = 9
    static let headerGap: CGFloat = 12

    static func bodyFont(weight: UIFont.Weight = .regular) -> UIFont {
        .systemFont(ofSize: 15, weight: weight)
    }

    static func textWidth(for pageWidth: CGFloat) -> CGFloat {
        pageWidth - pageMargin * 2 - bubblePadding * 2
    }

    static func measure(_ text: String, font: UIFont, width: CGFloat) -> CGFloat {
        let attr = NSAttributedString(string: text, attributes: [.font: font])
        let rect = attr.boundingRect(
            with: CGSize(width: width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            context: nil
        )
        return ceil(rect.height) + 4
    }

    static func rowHeight(_ row: Row, pageWidth: CGFloat) -> CGFloat {
        switch row.kind {
        case .user, .assistant:
            return measure(row.text, font: bodyFont(), width: textWidth(for: pageWidth)) + bubblePadding * 2
        case .meta:
            return measure(row.text, font: .systemFont(ofSize: 12.5), width: pageWidth - pageMargin * 2)
        }
    }

    static func headerSize(pageWidth: CGFloat) -> CGFloat {
        22 + headerGap + 1 // icon+text row, gap, hairline
    }

    // MARK: Long image

    static func renderLongImage(rows: [Row], pageWidth: CGFloat = 390,
                                modelName: String, dateText: String) -> UIImage? {
        var total: CGFloat = headerSize(pageWidth: pageWidth) + pageMargin
        for row in rows {
            total += rowHeight(row, pageWidth: pageWidth) + rowGap
        }
        total += pageMargin
        guard total > 0, total < 40_000 else { return nil }

        let format = UIGraphicsImageRendererFormat(for: UITraitCollection.current)
        format.scale = 2
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: pageWidth, height: total), format: format)

        return renderer.image { ctx in
            let cg = ctx.cgContext
            UIColor.systemBackground.setFill()
            cg.fill(CGRect(x: 0, y: 0, width: pageWidth, height: total))

            var y: CGFloat = pageMargin
            y = drawHeader(in: ctx, pageWidth: pageWidth, modelName: modelName, dateText: dateText, y: y)

            for row in rows {
                let h = rowHeight(row, pageWidth: pageWidth)
                drawRow(row, in: ctx, pageWidth: pageWidth, y: y, height: h)
                y += h + rowGap
            }
        }
    }

    // MARK: PDF

    static func renderPDF(rows: [Row], pageWidth: CGFloat = 390,
                          modelName: String, dateText: String) -> Data? {
        // One logical page = one screenful of content height.
        let pageHeight: CGFloat = 844
        let format = UIGraphicsPDFRendererFormat()
        format.documentInfo = [
            kCGPDFContextTitle as String: "Minis Chat Export",
            kCGPDFContextCreator as String: "Minis"
        ]
        let renderer = UIGraphicsPDFRenderer(
            bounds: CGRect(x: 0, y: 0, width: pageWidth, height: pageHeight),
            format: format
        )

        var cursor: CGFloat = 0
        var firstPage = true
        var headerDrawn = false

        return renderer.pdfData { ctx in
            func ensureSpace(_ needed: CGFloat) {
                if cursor + needed > pageHeight - pageMargin * 2 {
                    ctx.beginPage()
                    firstPage = false
                    cursor = pageMargin
                }
            }
            if firstPage {
                ctx.beginPage()
                cursor = pageMargin
            }
            // Header only on the first page.
            let headerH = headerSize(pageWidth: pageWidth)
            if !headerDrawn {
                cursor = drawHeader(in: ctx, pageWidth: pageWidth, modelName: modelName, dateText: dateText, y: cursor)
                headerDrawn = true
            }
            for row in rows {
                let h = rowHeight(row, pageWidth: pageWidth)
                ensureSpace(h + rowGap)
                drawRow(row, in: ctx, pageWidth: pageWidth, y: cursor, height: h)
                cursor += h + rowGap
            }
        }
    }

    // MARK: Drawing

    private static func drawHeader(in ctx: UIGraphicsRendererContext, pageWidth: CGFloat,
                                   modelName: String, dateText: String, y: CGFloat) -> CGFloat {
        // Assistant icon + model name + date.
        let iconSize: CGFloat = 26
        let iconRect = CGRect(x: pageMargin, y: y, width: iconSize, height: iconSize)
        let icon = UIImage(systemName: "sparkles")?.withTintColor(.label) ?? UIImage()
        icon.draw(in: iconRect)

        let textX = pageMargin + iconSize + 10
        let labelW = pageWidth - textX - pageMargin
        let title = "Minis · \(modelName)"
        let titleAttr = NSAttributedString(string: title, attributes: [
            .font: UIFont.systemFont(ofSize: 15, weight: .semibold),
            .foregroundColor: UIColor.label
        ])
        titleAttr.draw(at: CGPoint(x: textX, y: y + 1))

        let dateAttr = NSAttributedString(string: dateText, attributes: [
            .font: UIFont.systemFont(ofSize: 12),
            .foregroundColor: UIColor.secondaryLabel
        ])
        dateAttr.draw(at: CGPoint(x: textX, y: y + 22))

        // Hairline under the header.
        UIColor.separator.withAlphaComponent(0.5).setFill()
        ctx.cgContext.fill(CGRect(x: pageMargin, y: y + 34, width: pageWidth - pageMargin * 2, height: 0.5))
        return y + 34 + headerGap
    }

    private static func drawRow(_ row: Row, in ctx: UIGraphicsRendererContext,
                                pageWidth: CGFloat, y: CGFloat, height: CGFloat) {
        switch row.kind {
        case .user, .assistant:
            let isUser = row.kind == .user
            let textW = textWidth(for: pageWidth)
            let bubbleW = min(textW + bubblePadding * 2, pageWidth - pageMargin - 20)
            let bubbleH = height
            let bubbleX: CGFloat
            if isUser {
                bubbleX = pageWidth - pageMargin - bubbleW
            } else {
                bubbleX = pageMargin
            }
            let bubbleRect = CGRect(x: bubbleX, y: y, width: bubbleW, height: bubbleH)

            let path = UIBezierPath(roundedRect: bubbleRect, cornerRadius: 14)
            if isUser {
                UIColor.systemBlue.setFill()
            } else {
                UIColor.secondarySystemBackground.setFill()
            }
            path.fill()

            let attr = NSAttributedString(string: row.text, attributes: [
                .font: bodyFont(),
                .foregroundColor: UIColor.label
            ])
            let textRect = CGRect(
                x: bubbleX + bubblePadding,
                y: y + 10,
                width: textW,
                height: bubbleH - 20
            )
            attr.draw(with: textRect, options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        case .meta:
            let attr = NSAttributedString(string: row.text, attributes: [
                .font: UIFont.systemFont(ofSize: 12.5),
                .foregroundColor: UIColor.secondaryLabel
            ])
            let rect = CGRect(
                x: pageMargin + 3,
                y: y + 2,
                width: pageWidth - pageMargin * 2 - 6,
                height: height + 20
            )
            attr.draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading], context: nil)
        }
    }
}

// MARK: - Preview sheet

struct ChatExportSheet: View {
    let kind: ChatExportKind
    let sessionId: String

    @Environment(\.dismiss) private var dismiss
    @State private var messages: [RawMessage] = []
    @State private var image: UIImage?
    @State private var pdfURL: URL?
    @State private var errorText: String?
    @State private var generating = false

    private var modelName: String {
        messages.last { $0.role == .assistant }?.modelDisplayName ?? "Minis"
    }

    private var dateText: String {
        let d = messages.last?.createdAt ?? Date()
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.string(from: d)
    }

    var body: some View {
        NavigationView {
            Group {
                if let image {
                    ZoomableImageScrollView(image: image)
                } else if let pdfURL {
                    QLPreviewWrapper(url: pdfURL)
                } else if let errorText {
                    VStack(spacing: 10) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.largeTitle)
                            .foregroundColor(.orange)
                        Text(errorText).font(.subheadline)
                    }
                } else {
                    ProgressView("正在生成…")
                }
            }
            .navigationTitle(kind.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("完成")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if image != nil || pdfURL != nil {
                        Button {
                            share()
                        } label: {
                            Image(systemName: "square.and.arrow.up")
                        }
                    }
                }
            }
        }
        .onAppear {
            loadAndGenerate()
        }
    }

    private func loadAndGenerate() {
        guard !generating else { return }
        generating = true
        Task {
            let loaded = await ChatStore.shared.loadMessages(sessionId: sessionId)
            await MainActor.run { self.messages = loaded }
            generate()
        }
    }

    private func generate() {
        guard generating else { return }
        generating = false
        let rows = ChatExportRenderer.buildRows(from: messages)
        Task.detached(priority: .userInitiated) {
            switch kind {
            case .longImage:
                let img = ChatExportRenderer.renderLongImage(
                    rows: rows, modelName: modelName, dateText: dateText)
                await MainActor.run { self.image = img; if img == nil { self.errorText = AppLocalized("生成失败") } }
            case .pdf:
                let data = ChatExportRenderer.renderPDF(
                    rows: rows, modelName: modelName, dateText: dateText)
                await MainActor.run {
                    if let data {
                        let url = FileManager.default.temporaryDirectory
                            .appendingPathComponent("MinisChat-\(UUID().uuidString.prefix(6)).pdf")
                        try? data.write(to: url)
                        self.pdfURL = url
                    } else {
                        self.errorText = AppLocalized("生成失败")
                    }
                }
            }
        }
    }

    private func share() {
        guard let presenter = UIApplication.shared.windows.first?.rootViewController else { return }
        let url: URL?
        if let image {
            let tmp = FileManager.default.temporaryDirectory
                .appendingPathComponent("MinisChat-\(UUID().uuidString.prefix(6)).png")
            try? image.pngData()?.write(to: tmp)
            url = tmp
        } else {
            url = pdfURL
        }
        guard let url else { return }
        let avc = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        avc.popoverPresentationController?.sourceView = presenter.view
        presenter.present(avc, animated: true)
    }
}

// MARK: - Zoomable image preview (UIKit zoom wrapper, iOS15-safe)

struct ZoomableImageScrollView: UIViewRepresentable {
    let image: UIImage

    func makeUIView(context: Context) -> UIScrollView {
        let scroll = UIScrollView()
        scroll.backgroundColor = .systemBackground
        scroll.minimumZoomScale = 1
        scroll.maximumZoomScale = 4
        scroll.delegate = context.coordinator
        let imageView = UIImageView(image: image)
        imageView.contentMode = .scaleAspectFit
        imageView.frame = CGRect(origin: .zero, size: image.size)
        scroll.addSubview(imageView)
        scroll.contentSize = image.size
        context.coordinator.imageView = imageView
        return scroll
    }

    func updateUIView(_ scroll: UIScrollView, context: Context) {
        context.coordinator.imageView?.image = image
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        weak var imageView: UIImageView?
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }
    }
}

// MARK: - PDF preview via QuickLook (iOS15-safe)

struct QLPreviewWrapper: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> QLPreviewController {
        let ql = QLPreviewController()
        ql.dataSource = context.coordinator
        return ql
    }

    func updateUIViewController(_ vc: QLPreviewController, context: Context) {
        context.coordinator.url = url
        vc.reloadData()
    }

    func makeCoordinator() -> Coordinator { Coordinator(url: url) }

    final class Coordinator: NSObject, QLPreviewControllerDataSource {
        var url: URL
        init(url: URL) { self.url = url }
        func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
        func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem { url as NSURL }
    }
}