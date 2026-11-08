import Combine
import CoreFoundation
import CryptoKit
import Foundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers
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

/// All full-image I/O, ImageIO decode, PNG encoding and hash/readback work is
/// performed on `io`, never in a SwiftUI body or a MainActor callback.
enum MiniSightAssetCatalog {
    enum ImportKind: String, CaseIterable, Identifiable {
        case auto, singleImage, petdex8x9
        var id: String { rawValue }
        var title: String {
            switch self {
            case .auto: return "自动识别（推荐）"
            case .singleImage: return "单张图片（静态角色）"
            case .petdex8x9: return "Petdex 8 列 × 9 行图集"
            }
        }
    }
    enum Failure: LocalizedError {
        case invalidURL, http(Int), contentType, tooLarge, dimensions, format, atlasLayout
        case unreadable, verification, cancelled, timeout, rollback
        var errorDescription: String? {
            switch self {
            case .invalidURL: return "请输入不含账号密码的 HTTP(S) 图片直链。"
            case .http(let status): return "下载失败：HTTP \(status)。"
            case .contentType: return "下载类型不是受支持图片，网页、ZIP 和网站素材包不能直接导入。"
            case .tooLarge: return "素材超过 24 MiB 输入上限，或本地文件不是普通文件。"
            case .dimensions: return "图片尺寸无效：每边最多 16384 像素，总像素最多 4000 万。"
            case .format: return "仅支持 ImageIO 可解码的静态 PNG、JPEG、HEIC/HEIF、WebP；图集必须为 PNG。"
            case .atlasLayout: return "图集必须正向、无间隔，8 列 × 9 行；每格宽高 12:13（例如整图 768×936 或 2304×2808）。不会凭比例自动猜图集。"
            case .unreadable: return "素材或元数据不可读，原素材未替换。请重新选择格式后导入。"
            case .verification: return "素材写入或本地回读校验失败，未确认切换。"
            case .cancelled: return "已取消。"
            case .timeout: return "素材处理超时，请使用更小的本地图片重试。"
            case .rollback: return "切换失败且回退写入未完成；原素材仍保留在 pet.backup.png，请勿删除。"
            }
        }
    }
    /// Schema is plain Codable JSON, readable by both Swift and Foundation ObjC.
    /// The renderer must use ONLY the sprite child layer; assigning an atlas to
    /// UIImageView.image also paints a second, full-sheet grid behind the pet.
    struct Metadata: Codable, Equatable {
        var schema = 1
        var format = "minisight-atlas-v1"
        var id: String
        var title: String
        var sourceKind: String
        var columns = 8
        var rows = 9
        var cellWidth = 96
        var cellHeight = 104
        var frameCounts = [6, 8, 8, 4, 5, 8, 6, 6, 6]
        var previewRow = 0
        var previewColumn = 0
        var selectedVariant: Int? = 0
        var variants: Int? = 72
        var layoutVersion: Int? = 2
        var bytes: Int
        var sha256: String
        var revision: String
        var createdAt: TimeInterval
        var valid: Bool {
            schema == 1 && format == "minisight-atlas-v1" && UUID(uuidString: id) != nil &&
            columns == 8 && rows == 9 && cellWidth == 96 && cellHeight == 104 &&
            frameCounts == [6, 8, 8, 4, 5, 8, 6, 6, 6] && previewRow == 0 && previewColumn == 0 &&
            (selectedVariant ?? 0) >= 0 && (selectedVariant ?? 0) < 72 &&
            (sourceKind == ImportKind.singleImage.rawValue
                ? ((variants ?? 1) >= 1 && (variants ?? 1) <= 72 && (layoutVersion ?? 1) <= 3)
                : ((variants ?? 72) == 72 && (layoutVersion ?? 1) <= 2)) &&
            ImportKind(rawValue: sourceKind) != nil && sourceKind != ImportKind.auto.rawValue &&
            bytes > 0 && bytes <= maxStoredBytes &&
            sha256.count == 64 && UUID(uuidString: revision) != nil && title.utf8.count <= 512
        }
    }
    struct Item: Identifiable {
        let name: String
        let title: String
        let bytes: Int
        let variant: Int
        let metadata: Metadata?
        let preview: UIImage?
        var id: String { "\(name)#\(variant)" }
        /// The old tiler already replaced the source with 12x11 frames; it
        /// cannot be restored, so the UI must ask for one fresh import.
        var isLossyLegacySingle: Bool {
            metadata?.sourceKind == ImportKind.singleImage.rawValue &&
            (metadata?.layoutVersion ?? 1) == 2
        }
    }
    struct Snapshot {
        let items: [Item]
        let currentID: String?
        let canRestore: Bool
    }
    static let maxInputBytes = 24 * 1024 * 1024
    static let maxStoredBytes = 16 * 1024 * 1024
    static let io = DispatchQueue(label: "com.openminis.minisight.asset-io", qos: .utility)
    static let didChange = Notification.Name("MiniSightAssetsDidChange")
    static let resourceNotification = "com.openminis.minisight.resources"
    static var dir: URL { MiniSightPetFile.directory.appendingPathComponent("costumes", isDirectory: true) }
    static var metadataURL: URL { MiniSightPetFile.directory.appendingPathComponent("pet.json") }
    static var currentVariant: Int { (try? metadata(at: metadataURL))?.selectedVariant ?? 0 }
    private static func sidecar(_ file: URL) -> URL { file.deletingPathExtension().appendingPathExtension("json") }
    private static func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

    static func inputURL(_ text: String) throws -> URL {
        let raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard raw.rangeOfCharacter(from: .whitespacesAndNewlines.union(.controlCharacters)) == nil,
              let parts = URLComponents(string: raw), let url = parts.url,
              ["http", "https"].contains(parts.scheme?.lowercased() ?? ""),
              !(parts.host ?? "").isEmpty, parts.user == nil, parts.password == nil, parts.fragment == nil else {
            throw Failure.invalidURL
        }
        return url
    }

    static func boundedData(_ file: URL, limit: Int) throws -> Data {
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true,
              let size = values.fileSize, size > 0, size <= limit else { throw Failure.tooLarge }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        return try boundedData(handle, limit: limit)
    }

    static func boundedData(_ handle: FileHandle, limit: Int) throws -> Data {
        var data = Data()
        while let chunk = try handle.read(upToCount: min(64 * 1024, limit + 1 - data.count)), !chunk.isEmpty {
            data.append(chunk)
            if data.count > limit { throw Failure.tooLarge }
        }
        guard !data.isEmpty else { throw Failure.unreadable }
        return data
    }

    private static func metadata(at file: URL) throws -> Metadata {
        let data = try boundedData(file, limit: 16 * 1024)
        let value = try JSONDecoder().decode(Metadata.self, from: data)
        guard value.valid else { throw Failure.verification }
        return value
    }
    /// True when the pixels are a contact sheet of SEPARATE pets rather than
    /// one pet drawn at the same overall ratio. Every figure sits inside its
    /// own 1/8 x 1/9 cell, so the largest opaque blob is far narrower than the
    /// sheet; one pet's body spans several cells. Measured on a small
    /// thumbnail with alpha, so an opaque JPEG of a sheet still counts and a
    /// transparent single pet does not.
    private static func gridLooksLikePets(_ source: CGImageSource) -> Bool {
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: 480
        ]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return false }
        let w = cg.width, h = cg.height
        guard w >= 32, h >= 36 else { return false }
        var pixels = [UInt8](repeating: 0, count: w * h * 4)
        guard let context = CGContext(data: &pixels, width: w, height: h, bitsPerComponent: 8,
                                      bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
        context.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
        var seen = [Bool](repeating: false, count: w * h)
        var stack: [Int] = []
        stack.reserveCapacity(4096)
        var components = 0
        var widest = 0
        for start in 0..<(w * h) where !seen[start] && pixels[start * 4 + 3] >= 8 {
            var minX = start % w, maxX = minX
            stack.removeAll(keepingCapacity: true)
            stack.append(start)
            seen[start] = true
            var area = 0
            while let p = stack.popLast() {
                area += 1
                let x = p % w, y = p / w
                if x < minX { minX = x }
                if x > maxX { maxX = x }
                if x > 0, !seen[p - 1], pixels[(p - 1) * 4 + 3] >= 8 { seen[p - 1] = true; stack.append(p - 1) }
                if x + 1 < w, !seen[p + 1], pixels[(p + 1) * 4 + 3] >= 8 { seen[p + 1] = true; stack.append(p + 1) }
                if y > 0, !seen[p - w], pixels[(p - w) * 4 + 3] >= 8 { seen[p - w] = true; stack.append(p - w) }
                if y + 1 < h, !seen[p + w], pixels[(p + w) * 4 + 3] >= 8 { seen[p + w] = true; stack.append(p + w) }
            }
            guard area >= 24 else { continue }
            components += 1
            widest = max(widest, maxX - minX + 1)
            if components > 400 { break }
        }
        return components >= 6 && widest * 100 < w * 35
    }

    /// `auto` treats an upright image whose pixels match the 768:936 Petdex
    /// sheet AND are laid out as a grid of separate figures as a pack.
    /// Everything else stays a single static image.
    static func prepare(_ data: Data, kind: ImportKind, title: String,
                        operation: MiniSightAssetOperation) throws -> (Data, Metadata) {
        try operation.check()
        guard data.count <= maxInputBytes else { throw Failure.tooLarge }
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options),
              CGImageSourceGetCount(source) == 1,
              let uti = CGImageSourceGetType(source) as String?,
              ["public.png", "public.jpeg", "public.heic", "public.heif", "org.webmproject.webp"].contains(uti),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let height = (props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue else { throw Failure.format }
        guard width > 0, height > 0, width <= 16384, height <= 16384,
              Int64(width) * Int64(height) <= 40_000_000 else { throw Failure.dimensions }
        let orientation = (props[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        // 8x9 outer cells, each cell a 8x9 animation atlas. Require the same
        // 768:936 proportion (1% tolerance); support 768x936, 2304x2808 and
        // any intermediate re-encode. The UTI is NOT required to be PNG: the
        // photo picker hands a JPEG conversion of a PNG asset to us, and
        // demanding public.png here is what silently downgraded a real
        // 8x9 sheet to "single image" on 2026-11-08.
        let packDelta = abs(width * 936 - height * 768)
        let packRatio = orientation == 1 && packDelta <= max(768 * 4, height * 8)
        let looksLikePack = packRatio && (uti == "public.png" || gridLooksLikePets(source))
        let resolved: ImportKind = kind == .auto ? (looksLikePack ? .petdex8x9 : .singleImage) : kind
        if resolved == .petdex8x9 {
            guard packRatio else { throw Failure.atlasLayout }
        }
        let maxPixel = resolved == .singleImage ? 1536 : 936
        let thumbnailOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel
        ]
        guard let decoded = CGImageSourceCreateThumbnailAtIndex(source, 0, thumbnailOptions as CFDictionary) else {
            throw Failure.unreadable
        }
        try operation.check()
        // Packs are normalised to 768x936. A single photo keeps its own aspect
        // and resolution: tiling it into 12x11 frames is what made it blurry.
        let canvasW = resolved == .petdex8x9 ? 768 : decoded.width
        let canvasH = resolved == .petdex8x9 ? 936 : decoded.height
        guard canvasW > 0, canvasH > 0,
              let context = CGContext(data: nil, width: canvasW, height: canvasH, bitsPerComponent: 8,
                                      bytesPerRow: canvasW * 4, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
            throw Failure.unreadable
        }
        context.interpolationQuality = .high
        context.translateBy(x: 0, y: CGFloat(canvasH))
        context.scaleBy(x: 1, y: -1)
        if resolved == .petdex8x9 {
            context.draw(decoded, in: CGRect(x: 0, y: 0, width: 768, height: 936))
        } else {
            context.draw(decoded, in: CGRect(x: 0, y: 0, width: canvasW, height: canvasH))
        }
        guard let cg = context.makeImage() else { throw Failure.unreadable }
        let encoded = NSMutableData()
        guard let writer = CGImageDestinationCreateWithData(encoded, UTType.png.identifier as CFString, 1, nil) else {
            throw Failure.verification
        }
        CGImageDestinationAddImage(writer, cg, nil)
        guard CGImageDestinationFinalize(writer), encoded.length <= maxStoredBytes else { throw Failure.verification }
        let output = encoded as Data
        let name = String(title.prefix(100))
        var metadata = Metadata(id: UUID().uuidString, title: name.isEmpty ? "本地素材" : name,
                                sourceKind: resolved.rawValue, bytes: output.count, sha256: digest(output),
                                revision: UUID().uuidString, createdAt: Date().timeIntervalSince1970)
        if resolved == .singleImage {
            metadata.layoutVersion = 3
            metadata.variants = 1
            metadata.selectedVariant = 0
        }
        try verify(output, metadata: metadata)
        try operation.check()
        return (output, metadata)
    }

    private static func verify(_ data: Data, metadata: Metadata) throws {
        guard metadata.valid, data.count == metadata.bytes, digest(data) == metadata.sha256,
              let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              ((metadata.sourceKind == ImportKind.singleImage.rawValue)
                ? ((props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue ?? 0) > 0 &&
                  ((props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue ?? 0) > 0
                : packShaped(props)),
              CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary) != nil else {
            throw Failure.verification
        }
    }

    /// A pack record must still be a single upright frame with the 12:13 sheet
    /// proportion. New imports are normalised to 768x936; the checker stays
    /// proportional so an older re-encoded sheet (e.g. 1260x1536) remains
    /// valid without being rewritten just to satisfy an exact pixel count.
    private static func packShaped(_ props: [CFString: Any]) -> Bool {
        guard let w = (props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let h = (props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              w > 0, h > 0 else { return false }
        return abs(w * 936 - h * 768) <= max(768 * 4, h * 8)
    }

    static func preview(at file: URL, variant: Int = 0) throws -> UIImage {
        let data = try boundedData(file, limit: maxStoredBytes)
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let w = (props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let h = (props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              w > 0, h > 0, w <= 16384, h <= 16384, Int64(w) * Int64(h) <= 40_000_000 else { throw Failure.unreadable }
        let metaFile = file == MiniSightPetFile.url ? metadataURL : sidecar(file)
        let meta = FileManager.default.fileExists(atPath: metaFile.path) ? try metadata(at: metaFile) : nil
        if let meta { try verify(data, metadata: meta) }
        let maxPixel = meta?.sourceKind == ImportKind.singleImage.rawValue ? 1536 : 936
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                      kCGImageSourceCreateThumbnailWithTransform: true,
                                      kCGImageSourceShouldCacheImmediately: true,
                                      kCGImageSourceThumbnailMaxPixelSize: maxPixel]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { throw Failure.unreadable }
        guard let meta else { return UIImage(cgImage: cg, scale: 1, orientation: .up) }
        if meta.sourceKind == ImportKind.singleImage.rawValue {
            // v3 keeps the original image. v1 had one copy per OUTER cell;
            // v2 is the old destructive tiling, where one 12x11 inner frame
            // is the only remaining whole-image copy.
            let lv = meta.layoutVersion ?? 1
            if lv >= 3 { return UIImage(cgImage: cg, scale: 1, orientation: .up) }
            let v = min(71, max(0, variant))
            let rect: CGRect
            if lv == 1 {
                let cw = cg.width / 8, ch = cg.height / 9
                rect = CGRect(x: (v % 8) * cw, y: (v / 8) * ch, width: cw, height: ch)
            } else {
                let fw = cg.width / 64, fh = cg.height / 81
                rect = CGRect(x: (v % 8) * 8 * fw, y: (v / 8) * 9 * fh, width: fw, height: fh)
            }
            guard rect.width > 0, rect.height > 0, let cell = cg.cropping(to: rect) else { throw Failure.verification }
            return UIImage(cgImage: cell, scale: 1, orientation: .up)
        }
        let v = min(71, max(0, variant))
        let fw = cg.width / 64, fh = cg.height / 81
        guard fw > 0, fh > 0,
              let cell = cg.cropping(to: CGRect(x: (v % 8) * 8 * fw, y: (v / 8) * 9 * fh, width: fw, height: fh)) else {
            throw Failure.verification
        }
        return UIImage(cgImage: cell, scale: 1, orientation: .up)
    }

    /// A single-image record that is really a pack sheet — the 2026-11-08
    /// regression, where a JPEG conversion defeated the PNG-only detector —
    /// is normalised back into a real pack in place. One-time: the rewritten
    /// metadata says petdex8x9, so the guard stops matching afterwards.
    @discardableResult
    private static func migrateSingleToPack(file: URL, metaFile: URL, meta: Metadata) -> Metadata? {
        guard meta.sourceKind == ImportKind.singleImage.rawValue,
              (meta.layoutVersion ?? 1) >= 3, (meta.variants ?? 1) == 1,
              let source = CGImageSourceCreateWithURL(file as CFURL, nil),
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              packShaped(props), gridLooksLikePets(source),
              let data = try? boundedData(file, limit: maxInputBytes),
              let (png, fresh) = try? prepare(data, kind: .petdex8x9, title: meta.title,
                                              operation: MiniSightAssetOperation()),
              let json = try? JSONEncoder().encode(fresh) else { return nil }
        if file == MiniSightPetFile.url {
            guard (try? replaceCurrent(png, json: json, keepBackup: true)) != nil else { return nil }
            try? Data("0".utf8).write(to: MiniSightPetFile.directory.appendingPathComponent("variant"), options: .atomic)
        } else {
            guard (try? write(png, to: file)) != nil, (try? write(json, to: metaFile)) != nil else { return nil }
        }
        return fresh
    }

    static func snapshot() throws -> Snapshot {
        let fm = FileManager.default
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let files = try fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey])
        let imageFiles = files.filter { ["png", "jpg", "jpeg", "heic", "heif", "webp"].contains($0.pathExtension.lowercased()) }
        guard imageFiles.count <= 500 else { throw Failure.tooLarge }
        var items: [Item] = []
        var migrated = false
        for file in imageFiles.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
            var meta = try? metadata(at: sidecar(file))
            if let current = meta,
               let fresh = migrateSingleToPack(file: file, metaFile: sidecar(file), meta: current) {
                meta = fresh
                migrated = true
            }
            let bytes = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            if meta?.sourceKind == ImportKind.petdex8x9.rawValue {
                for v in 0..<72 {
                    items.append(Item(name: file.lastPathComponent,
                                      title: "\(meta?.title ?? "图集") · \(v + 1)",
                                      bytes: bytes, variant: v, metadata: meta, preview: nil))
                }
            } else {
                let title = meta?.title ?? file.lastPathComponent
                let lossy = meta?.sourceKind == ImportKind.singleImage.rawValue && (meta?.layoutVersion ?? 1) == 2
                items.append(Item(name: file.lastPathComponent,
                                  title: lossy ? "\(title)（旧版已压缩，请重新添加）" : title,
                                  bytes: bytes, variant: 0, metadata: meta, preview: nil))
            }
        }
        var currentMeta = try? metadata(at: metadataURL)
        if let current = currentMeta,
           let fresh = migrateSingleToPack(file: MiniSightPetFile.url, metaFile: metadataURL, meta: current) {
            currentMeta = fresh
            migrated = true
        }
        if migrated {
            DispatchQueue.main.async { publishChange() }
        }
        let currentID = currentMeta.map { "\($0.id)#\($0.selectedVariant ?? 0)" }
        let backup = MiniSightPetFile.directory.appendingPathComponent("pet.backup.png")
        return Snapshot(items: items, currentID: currentID, canRestore: fm.fileExists(atPath: backup.path))
    }
    private static func write(_ data: Data, to file: URL) throws {
        try data.write(to: file, options: .atomic)
        guard try boundedData(file, limit: maxInputBytes) == data else { throw Failure.verification }
    }
    private static func optionalData(_ file: URL, limit: Int) throws -> Data? {
        FileManager.default.fileExists(atPath: file.path) ? try boundedData(file, limit: limit) : nil
    }
    private static func put(_ data: Data?, at file: URL) throws {
        if let data { try write(data, to: file) }
        else if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
    }
    private static func assetURL(_ name: String) throws -> URL {
        guard !name.isEmpty, name == (name as NSString).lastPathComponent, !name.contains("..") else { throw Failure.unreadable }
        return dir.appendingPathComponent(name)
    }

    static func importData(_ data: Data, kind: ImportKind, title: String,
                           operation: MiniSightAssetOperation) throws -> Item {
        let (png, meta) = try prepare(data, kind: kind, title: title, operation: operation)
        try operation.check()
        let file = dir.appendingPathComponent(meta.id + ".png")
        let json = try JSONEncoder().encode(meta)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try operation.beginCommit()
        do {
            try write(png, to: file)
            try write(json, to: sidecar(file))
            try verify(try boundedData(file, limit: maxStoredBytes), metadata: metadata(at: sidecar(file)))
            return Item(name: file.lastPathComponent, title: meta.title, bytes: png.count, variant: 0, metadata: meta, preview: nil)
        } catch {
            // Cleanup failures are surfaced; a partial record is never a usable atlas.
            do { try put(nil, at: file); try put(nil, at: sidecar(file)) }
            catch { throw Failure.rollback }
            throw error
        }
    }

    static func activate(_ item: Item) throws {
        let file = try assetURL(item.name)
        let meta = try metadata(at: sidecar(file))
        let data = try boundedData(file, limit: maxStoredBytes)
        try verify(data, metadata: meta)
        var selected = meta
        selected.selectedVariant = item.variant
        selected.revision = UUID().uuidString
        try replaceCurrent(data, json: JSONEncoder().encode(selected), keepBackup: true)
        try? Data("\(item.variant)".utf8).write(to: MiniSightPetFile.directory.appendingPathComponent("variant"), options: .atomic)
    }

    /// Backup first, then image, then JSON manifest (commit marker). If any step
    /// fails restore the exact old pair. Readers should keep their last good
    /// image when image/json revisions momentarily mismatch.
    private static func replaceCurrent(_ data: Data, json: Data?, keepBackup: Bool) throws {
        let image = MiniSightPetFile.url
        let oldImage = try optionalData(image, limit: maxInputBytes)
        let oldJSON = try optionalData(metadataURL, limit: 16 * 1024)
        if keepBackup, let oldImage {
            try write(oldImage, to: MiniSightPetFile.directory.appendingPathComponent("pet.backup.png"))
            try put(oldJSON, at: MiniSightPetFile.directory.appendingPathComponent("pet.backup.json"))
        }
        do {
            try write(data, to: image)
            try put(json, at: metadataURL)
            if let json {
                let meta = try JSONDecoder().decode(Metadata.self, from: json)
                try verify(try boundedData(image, limit: maxStoredBytes), metadata: meta)
                guard try metadata(at: metadataURL) == meta else { throw Failure.verification }
            }
        } catch {
            do { try put(oldImage, at: image); try put(oldJSON, at: metadataURL) }
            catch { throw Failure.rollback }
            throw error
        }
    }

    static func restorePrevious() throws {
        let image = MiniSightPetFile.directory.appendingPathComponent("pet.backup.png")
        let jsonURL = MiniSightPetFile.directory.appendingPathComponent("pet.backup.json")
        let data = try boundedData(image, limit: maxInputBytes)
        let json = try optionalData(jsonURL, limit: 16 * 1024)
        if let json { try verify(data, metadata: JSONDecoder().decode(Metadata.self, from: json)) }
        // Old metadata-free bytes are deliberately restored unchanged.
        try replaceCurrent(data, json: json, keepBackup: true)
    }

    static func delete(_ item: Item) throws {
        let file = try assetURL(item.name)
        let fm = FileManager.default
        // Deleting a catalog record does NOT erase pet.png or silently switch.
        // The active image is an independent verified copy and remains usable.
        let image = try optionalData(file, limit: maxInputBytes)
        let json = try optionalData(sidecar(file), limit: 16 * 1024)
        do {
            try put(nil, at: file); try put(nil, at: sidecar(file))
            guard !fm.fileExists(atPath: file.path), !fm.fileExists(atPath: sidecar(file).path) else { throw Failure.verification }
        } catch {
            do { try put(image, at: file); try put(json, at: sidecar(file)) }
            catch { throw Failure.rollback }
            throw error
        }
    }

    static func stage(data: Data, operation: MiniSightAssetOperation) throws -> URL {
        try operation.check()
        guard !data.isEmpty, data.count <= maxInputBytes else { throw Failure.tooLarge }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("minisight-source-" + UUID().uuidString)
        try data.write(to: file, options: .atomic)
        guard try boundedData(file, limit: maxInputBytes) == data else {
            try? FileManager.default.removeItem(at: file); throw Failure.verification
        }
        return file
    }
    static func stage(file source: URL, operation: MiniSightAssetOperation) throws -> URL {
        try operation.check()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("minisight-source-" + UUID().uuidString)
        guard FileManager.default.createFile(atPath: file.path, contents: nil) else { throw Failure.verification }
        do {
            let input = try FileHandle(forReadingFrom: source)
            let output = try FileHandle(forWritingTo: file)
            defer { try? input.close(); try? output.close() }
            var count = 0
            while let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty {
                try operation.check()
                guard chunk.count <= maxInputBytes - count else { throw Failure.tooLarge }
                try output.write(contentsOf: chunk)
                count += chunk.count
            }
            guard count > 0 else { throw Failure.unreadable }
            _ = try boundedData(file, limit: maxInputBytes)
            return file
        } catch { try? FileManager.default.removeItem(at: file); throw error }
    }

    static func importFile(_ file: URL, kind: ImportKind, title: String,
                           operation: MiniSightAssetOperation) throws -> Item {
        defer { try? FileManager.default.removeItem(at: file) }
        return try importData(boundedData(file, limit: maxInputBytes), kind: kind,
                              title: title, operation: operation)
    }

    /// Call on main only AFTER successful readback. Does not show/enable the pet.
    /// Plugin must subscribe to this dedicated note: settings reload intentionally
    /// does not reload resources. No show/start or renderer-flip workaround.
    static func publishChange() {
        NotificationCenter.default.post(name: didChange, object: nil)
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(resourceNotification as CFString), nil, nil, true)
    }
}

/// Cancellation is accepted until the atomic catalog commit begins. A late tap
/// cannot claim cancellation after the file has already been committed.
final class MiniSightAssetOperation {
    private let lock = NSLock()
    private var cancelled = false
    private var committing = false
    private var cancellation: (() -> Void)?
    private let deadline = Date().addingTimeInterval(60)
    func check() throws {
        lock.lock(); defer { lock.unlock() }
        if cancelled { throw MiniSightAssetCatalog.Failure.cancelled }
        if !committing && Date() >= deadline { throw MiniSightAssetCatalog.Failure.timeout }
    }
    func beginCommit() throws {
        try check()
        lock.lock(); defer { lock.unlock() }
        guard !cancelled else { throw MiniSightAssetCatalog.Failure.cancelled }
        committing = true
        cancellation = nil
    }
    @discardableResult func cancel() -> Bool {
        lock.lock()
        guard !committing else { lock.unlock(); return false }
        cancelled = true
        let callback = cancellation; cancellation = nil
        lock.unlock(); callback?()
        return true
    }
    func setCancellation(_ callback: @escaping () -> Void) {
        lock.lock()
        if cancelled { lock.unlock(); callback(); return }
        cancellation = callback
        lock.unlock()
    }
}

/// Bounded disk-streaming downloader. It never builds a multi-MiB buffer or
/// decodes an image on the main thread. Status/MIME and each chunk are checked.
final class MiniSightAssetDownload: NSObject, URLSessionDataDelegate {
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var output: FileHandle?
    private var temporary: URL?
    private var count = 0
    private var finished = false
    private var deadlineWork: DispatchWorkItem?
    private let operation: MiniSightAssetOperation
    private let progress: (Int, Int64) -> Void
    private let completion: (Result<Data, Error>) -> Void
    private let queue: OperationQueue = {
        let value = OperationQueue()
        value.name = "com.openminis.minisight.asset-download"
        value.maxConcurrentOperationCount = 1
        value.qualityOfService = .utility
        return value
    }()
    init(operation: MiniSightAssetOperation, progress: @escaping (Int, Int64) -> Void,
         completion: @escaping (Result<Data, Error>) -> Void) {
        self.operation = operation; self.progress = progress; self.completion = completion
    }
    func start(_ url: URL) {
        queue.addOperation { [self] in
            do {
                try operation.check()
                let file = FileManager.default.temporaryDirectory.appendingPathComponent("minisight-" + UUID().uuidString)
                guard FileManager.default.createFile(atPath: file.path, contents: nil) else {
                    throw MiniSightAssetCatalog.Failure.verification
                }
                temporary = file
                output = try FileHandle(forWritingTo: file)
                let config = URLSessionConfiguration.ephemeral
                config.timeoutIntervalForRequest = 25
                config.timeoutIntervalForResource = 55
                config.urlCache = nil
                config.httpCookieStorage = nil
                config.httpShouldSetCookies = false
                let session = URLSession(configuration: config, delegate: self, delegateQueue: queue)
                self.session = session
                var request = URLRequest(url: url)
                request.setValue("image/png, image/jpeg, image/heic, image/heif, image/webp", forHTTPHeaderField: "Accept")
                task = session.dataTask(with: request)
                operation.setCancellation { [weak self] in self?.cancel() }
                let work = DispatchWorkItem { [weak self] in
                    guard let self else { return }
                    self.queue.addOperation { self.finish(.failure(MiniSightAssetCatalog.Failure.timeout)) }
                }
                deadlineWork = work
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 60, execute: work)
                task?.resume()
            } catch { finish(.failure(error)) }
        }
    }
    private func cancel() {
        queue.addOperation { [weak self] in self?.finish(.failure(MiniSightAssetCatalog.Failure.cancelled)) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        guard let url = request.url,
              (try? MiniSightAssetCatalog.inputURL(url.absoluteString)) != nil,
              !(response.url?.scheme == "https" && url.scheme == "http") else {
            completionHandler(nil); finish(.failure(MiniSightAssetCatalog.Failure.invalidURL)); return
        }
        completionHandler(request)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        do {
            try operation.check()
            guard let http = response as? HTTPURLResponse else { throw MiniSightAssetCatalog.Failure.contentType }
            guard (200...299).contains(http.statusCode) else { throw MiniSightAssetCatalog.Failure.http(http.statusCode) }
            guard ["image/png", "image/jpeg", "image/heic", "image/heif", "image/webp", "application/octet-stream"]
                .contains(http.mimeType?.lowercased() ?? "") else { throw MiniSightAssetCatalog.Failure.contentType }
            guard response.expectedContentLength <= Int64(MiniSightAssetCatalog.maxInputBytes) else {
                throw MiniSightAssetCatalog.Failure.tooLarge
            }
            progress(0, response.expectedContentLength)
            completionHandler(.allow)
        } catch { completionHandler(.cancel); finish(.failure(error)) }
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard !finished else { return }
        do {
            try operation.check()
            guard data.count <= MiniSightAssetCatalog.maxInputBytes - count else { throw MiniSightAssetCatalog.Failure.tooLarge }
            guard let output else { throw MiniSightAssetCatalog.Failure.verification }
            try output.write(contentsOf: data)
            count += data.count
            progress(count, dataTask.response?.expectedContentLength ?? -1)
        } catch { finish(.failure(error)) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard !finished else { return }
        if let error { finish(.failure(error)); return }
        do {
            try operation.check()
            try output?.close(); output = nil
            guard let temporary else { throw MiniSightAssetCatalog.Failure.verification }
            finish(.success(try MiniSightAssetCatalog.boundedData(temporary, limit: MiniSightAssetCatalog.maxInputBytes)))
        } catch { finish(.failure(error)) }
    }
    private func finish(_ result: Result<Data, Error>) {
        guard !finished else { return }
        finished = true
        deadlineWork?.cancel(); deadlineWork = nil
        task?.cancel(); task = nil
        session?.invalidateAndCancel(); session = nil
        try? output?.close(); output = nil
        if let temporary { try? FileManager.default.removeItem(at: temporary) }
        temporary = nil
        completion(result)
    }
}
