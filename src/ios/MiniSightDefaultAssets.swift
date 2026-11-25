import CryptoKit
import Foundation
import ImageIO
import UIKit

/// Original CC0 geometric art, independent of imported characters/action packs.
/// All disk/decode work belongs on MiniSightAssetCatalog.io, never View.body.
enum MiniSightDefaultAssets {
    static let id = "FF49E3E8-6BE3-4D98-8BC2-69904C3C6801"
    static let title = "小团 · 原创基础角色"
    static let storageName = "base-storage-atlas.png"
    static let sha256 = "fc7560e05d55c3276e3fc808a162583acfac9611b43e93f5682cd8cf61ccda9e"
    static let frameCounts = [6, 8, 8, 4, 5, 8, 6, 6, 6]
    static var directory: URL { MiniSightPetFile.directory.appendingPathComponent("defaults", isDirectory: true) }
    static var storageURL: URL { directory.appendingPathComponent(storageName) }

    static func validated(_ data: Data) -> Bool {
        guard !data.isEmpty, data.count <= 1024 * 1024,
              SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == sha256,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetCount(source) == 1,
              let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              (props[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue == 768,
              (props[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue == 936,
              CGImageSourceCreateImageAtIndex(source, 0, nil) != nil else { return false }
        return true
    }

    /// Accept only these bundled original bytes; never falls back to downloads.
    static func bundledData(bundle: Bundle = .main) throws -> Data {
        let locations = [
            bundle.url(forResource: "base-storage-atlas", withExtension: "png", subdirectory: "MiniSightDefaults"),
            bundle.url(forResource: "base-storage-atlas", withExtension: "png", subdirectory: "Resources/MiniSightDefaults"),
            bundle.url(forResource: "base-storage-atlas", withExtension: "png")
        ]
        for case let file? in locations {
            if let data = try? MiniSightAssetCatalog.boundedData(file, limit: 1024 * 1024), validated(data) { return data }
        }
        throw MiniSightAssetCatalog.Failure.unreadable
    }

    /// Separate fallback copy; NEVER touches pet.png, pet.json or user metadata.
    @discardableResult
    static func stageFallback(bundle: Bundle = .main) throws -> Data {
        let data = try bundledData(bundle: bundle)
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let info = try directory.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard info.isDirectory == true, info.isSymbolicLink != true else { throw MiniSightAssetCatalog.Failure.verification }
        let old = try? MiniSightAssetCatalog.boundedData(storageURL, limit: 1024 * 1024)
        if old != data {
            try data.write(to: storageURL, options: .atomic)
            guard try MiniSightAssetCatalog.boundedData(storageURL, limit: 1024 * 1024) == data else {
                throw MiniSightAssetCatalog.Failure.verification
            }
            // A plugin may already have built a capsule while the original
            // selection was broken. Notify only after actual repair+readback;
            // subsequent snapshot calls with unchanged bytes never loop.
            DispatchQueue.main.async { MiniSightAssetCatalog.publishChange() }
        }
        return data
    }

    /// Upright sheet for App fallback. Use spriteLayout=3, variant=0,
    /// actionManifest=nil; do not reuse a broken user's action-pack identity.
    static func runtimeImage() -> UIImage? {
        guard let data = try? bundledData(), let image = UIImage(data: data)?.cgImage,
              let context = CGContext(data: nil, width: 768, height: 936, bitsPerComponent: 8,
                  bytesPerRow: 768 * 4, space: CGColorSpaceCreateDeviceRGB(),
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return nil }
        context.translateBy(x: 0, y: 936); context.scaleBy(x: 1, y: -1)
        context.draw(image, in: CGRect(x: 0, y: 0, width: 768, height: 936))
        guard let cg = context.makeImage() else { return nil }
        return UIImage(cgImage: cg, scale: 1, orientation: .up)
    }
    static func previewImage() -> UIImage? {
        guard let cg = runtimeImage()?.cgImage,
              let cell = cg.cropping(to: CGRect(x: 0, y: 0, width: 96, height: 104)) else { return nil }
        return UIImage(cgImage: cell, scale: 1, orientation: .up)
    }
}
