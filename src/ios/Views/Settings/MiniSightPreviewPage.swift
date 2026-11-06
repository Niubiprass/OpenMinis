import SwiftUI

/// Lightweight in-app preview. It uses the same imported atlas as the host,
/// but it is intentionally a local preview, not a second display runtime.
struct MiniSightPreviewPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var image: UIImage?
    private let timer = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationView {
            VStack(spacing: 20) {
                if let image {
                    MiniSightPreviewSprite(image: image, size: CGFloat(config.petSize), interval: config.activityInterval)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "pawprint").font(.system(size: 54)).foregroundStyle(.secondary)
                        Text("还没有导入精灵图；可在“配色、服装与素材”导入。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                Text("预览使用已保存的素材和大小；不发 AI 请求，也不显示桌面浮窗。")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding(24)
            .navigationTitle("预览桌宠效果")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }
        .navigationViewStyle(.stack)
        .onAppear(perform: load)
        .onReceive(timer) { _ in load() }
    }

    private func load() {
        guard let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("MiniSight/pet.png") else { return }
        if let data = try? Data(contentsOf: dir) { image = UIImage(data: data) }
    }
}

/// Decodes the selected row only. A sliced atlas is 9 rows × 8 columns.
private struct MiniSightPreviewSprite: UIViewRepresentable {
    let image: UIImage
    let size: CGFloat
    let interval: Double

    func makeUIView(context: Context) -> UIView { context.coordinator.view }
    func updateUIView(_ view: UIView, context: Context) {
        context.coordinator.update(image: image, size: size, interval: interval)
    }
    func makeCoordinator() -> Coordinator { Coordinator() }
    static func dismantleUIView(_ view: UIView, coordinator: Coordinator) { coordinator.stop() }

    final class Coordinator {
        let view = UIView()
        private let imageView = UIImageView()
        private var timer: Timer?
        private var image: UIImage?
        private var size: CGFloat = 96
        private var column = 0
        init() {
            view.addSubview(imageView)
            imageView.contentMode = .scaleAspectFit
        }
        func update(image: UIImage, size: CGFloat, interval: Double) {
            self.image = image; self.size = size
            view.setNeedsLayout()
            if timer == nil {
                timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 7.0, repeats: true) { [weak self] _ in self?.tick() }
                RunLoop.main.add(timer!, forMode: .common)
            }
            tick()
        }
        func tick() {
            guard let image, image.size.width > 8 else { imageView.image = nil; return }
            let width = image.size.width, height = image.size.height
            guard let cg = image.cgImage else { imageView.image = nil; return }
            column = (column + 1) % 8
            let rect = CGRect(x: CGFloat(column) / 8.0 * CGFloat(cg.width),
                              y: CGFloat(cg.height) / 9.0,
                              width: CGFloat(cg.width) / 8.0,
                              height: CGFloat(cg.height) / 9.0)
            imageView.image = cg.cropping(to: rect).map { UIImage(cgImage: $0, scale: image.scale, orientation: .up) }
            _ = (width, height)
        }
        func stop() { timer?.invalidate(); timer = nil }
    }
}
