import SwiftUI
import UIKit

/// Shared appearance vocabulary used by the simplified pet page. The old
/// MiniSightAppearancePage was removed, but these values still drive the
/// runtime and the costume picker.
enum MiniSightPetPalette: String, CaseIterable {
    case natural, warm, cool, mint, rose
    var title: String {
        switch self {
        case .natural: return "原图"
        case .warm: return "暖橙"
        case .cool: return "冷蓝"
        case .mint: return "薄荷"
        case .rose: return "玫瑰"
        }
    }
    var color: Color {
        switch self {
        case .natural: return .clear
        case .warm: return Color(red: 0.96, green: 0.55, blue: 0.32)
        case .cool: return Color(red: 0.38, green: 0.58, blue: 0.98)
        case .mint: return Color(red: 0.35, green: 0.80, blue: 0.61)
        case .rose: return Color(red: 0.92, green: 0.45, blue: 0.63)
        }
    }
}

enum MiniSightAssetCatalog {
    struct Item { let name: String; let bytes: Int }
    static var dir: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MiniSight/costumes", isDirectory: true)
    }
    static func load() -> [Item] {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return ((try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.fileSizeKey])) ?? [])
            .filter { ["png", "webp", "jpg"].contains($0.pathExtension.lowercased()) }
            .compactMap { url in
                let values = try? url.resourceValues(forKeys: [.fileSizeKey])
                return Item(name: url.lastPathComponent, bytes: values?.fileSize ?? 0)
            }.sorted { $0.name < $1.name }
    }
    static func add(_ image: UIImage, source: String) {
        guard source == "files", let data = image.pngData() else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? data.write(to: dir.appendingPathComponent("local-\(Int(Date().timeIntervalSince1970)).png"))
    }
}
