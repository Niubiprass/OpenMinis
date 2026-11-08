import Foundation
import Dispatch
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// These helpers deliberately live OUTSIDE AIChatViewModel (@MainActor).
// Task { } inside that class inherits MainActor; an "async" name does not
// move copyItem, decoding or JPEG encoding off the UI thread.

enum AttachmentProcessingError: LocalizedError {
    case timedOut
    case invalidFile(String)
    case imageDecodeFailed
    case failed(String, String)

    var errorDescription: String? {
        switch self {
        case .timedOut: return "附件处理超时，原文件已保留，请重试。"
        case .invalidFile(let name): return "无法读取附件：\(name)"
        case .imageDecodeFailed: return "无法解码图片，原文件已保留。"
        case .failed(let name, let reason): return "附件 \(name) 处理失败：\(reason)"
        }
    }
}

/// Exactly one terminal result, including cancel-before-install and late
/// provider callbacks. Do NOT race Task.value inside withTaskGroup: exiting
/// that group waits for the losing task, even after cancelAll().
final class AttachmentWorkState<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Error>?
    private var outcome: Result<Value, Error>?
    private var finished = false

    var isFinished: Bool {
        lock.lock(); defer { lock.unlock() }
        return finished
    }

    func install(_ continuation: CheckedContinuation<Value, Error>) {
        lock.lock()
        if let outcome {
            lock.unlock()
            continuation.resume(with: outcome)
        } else {
            self.continuation = continuation
            lock.unlock()
        }
    }

    @discardableResult
    func finish(_ outcome: Result<Value, Error>) -> Bool {
        lock.lock()
        guard !finished else { lock.unlock(); return false }
        finished = true
        // If nobody has installed yet, retain the terminal outcome for the
        // late install(). Once a live waiter was resumed it is safe to drop.
        if continuation == nil { self.outcome = outcome }
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        continuation?.resume(with: outcome)
        return true
    }
}

enum AttachmentIO {
    /// Blocking work runs on a Dispatch worker, never a cooperative Swift
    /// executor or MainActor. A timed-out/cancelled caller can return without
    /// waiting for an uncooperative FileProvider or codec. Late owned output
    /// is discarded, not published as a new attachment.
    static func perform<Value>(timeout: TimeInterval = 60,
                               discard: @escaping (Value) -> Void = { _ in },
                               work: @escaping (@escaping () throws -> Void) throws -> Value) async throws -> Value {
        let state = AttachmentWorkState<Value>()
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                state.install(continuation)
                DispatchQueue.global(qos: .userInitiated).async {
                    guard !state.isFinished else { return }
                    do {
                        let value = try autoreleasepool {
                            try work {
                                if state.isFinished { throw CancellationError() }
                            }
                        }
                        if !state.finish(.success(value)) { discard(value) }
                    } catch { state.finish(.failure(error)) }
                }
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout) {
                    state.finish(.failure(AttachmentProcessingError.timedOut))
                }
            }
        }, onCancel: { state.finish(.failure(CancellationError())) })
    }

    static func remove(_ urls: [URL]) async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            DispatchQueue.global(qos: .utility).async {
                for url in urls where url.path != "/dev/null" {
                    try? FileManager.default.removeItem(at: url)
                }
                continuation.resume()
            }
        }
    }

    static func copy(_ source: URL, to destination: URL, originalDate: Date? = nil) async throws {
        let _: URL = try await perform(discard: { (url: URL) in try? FileManager.default.removeItem(at: url) }) { check in
            let fm = FileManager.default
            var committed = false
            defer { if !committed { try? fm.removeItem(at: destination) } }
            let access = source.startAccessingSecurityScopedResource()
            defer { if access { source.stopAccessingSecurityScopedResource() } }
            try check()
            try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            var coordinationError: NSError?
            var copyError: Error?
            NSFileCoordinator().coordinate(readingItemAt: source, options: [], error: &coordinationError) { readable in
                do {
                    // The deadline can expire while NSFileCoordinator waits for
                    // an unresponsive provider; don't run another copy only to
                    // report it after success has already been discarded.
                    try check()
                    try fm.copyItem(at: readable, to: destination)
                } catch { copyError = error }
            }
            if let coordinationError { throw coordinationError }
            if let copyError { throw copyError }
            guard fm.fileExists(atPath: destination.path) else {
                throw AttachmentProcessingError.invalidFile(source.lastPathComponent)
            }
            // Large attachments are copied by FileManager (streamed). A weak
            // or truncated provider copy must not look like success.
            let sourceSize = (try? fm.attributesOfItem(atPath: source.path)[.size] as? NSNumber)?.intValue
            let copiedSize = (try? fm.attributesOfItem(atPath: destination.path)[.size] as? NSNumber)?.intValue
            if let sourceSize, copiedSize != sourceSize {
                throw AttachmentProcessingError.failed(source.lastPathComponent, "复制不完整")
            }
            try check()
            if let originalDate {
                try fm.setAttributes([.creationDate: originalDate, .modificationDate: originalDate], ofItemAtPath: destination.path)
            }
            committed = true
            return destination
        }
    }

    static func write(_ data: Data, to destination: URL, originalDate: Date? = nil) async throws {
        try await perform(discard: { (_: URL) in try? FileManager.default.removeItem(at: destination) }) { check in
            let fm = FileManager.default
            var committed = false
            defer { if !committed { try? fm.removeItem(at: destination) } }
            try check()
            try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: destination, options: .atomic)
            try check()
            if let originalDate {
                try fm.setAttributes([.creationDate: originalDate, .modificationDate: originalDate], ofItemAtPath: destination.path)
            }
            committed = true
            return destination
        }
    }

    static func kind(name: String, header: Data? = nil) -> InputAttachment.Kind {
        let ext = (name as NSString).pathExtension.lowercased()
        if let type = UTType(filenameExtension: ext) {
            if type.conforms(to: .image) { return .image }
            if type.conforms(to: .movie) { return .video }
        }
        if ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tiff"].contains(ext) { return .image }
        if ["mp4", "mov", "m4v", "avi", "mkv"].contains(ext) { return .video }
        if let header, AttachmentImageCodec.detectExtension(header) != nil { return .image }
        return .document
    }

    static func classify(_ url: URL, name: String) async throws -> InputAttachment.Kind {
        try await perform { check in
            try check()
            let handle = try FileHandle(forReadingFrom: url)
            defer { try? handle.close() }
            let header = try handle.read(upToCount: 16)
            return kind(name: name, header: header)
        }
    }

    /// Import a provider/Files URL into the private attachment cache without
    /// touching the composer or any @MainActor state except on return.
    /// The copy runs on a dispatch worker even though this entry point is also
    /// called from MainActor (CLI/Shortcuts); the returned attachment is owned
    /// by the caller and a throw leaves no published path.
    static func stageFile(_ source: URL, fileName: String? = nil) async throws -> InputAttachment {
        let rawName = fileName ?? source.lastPathComponent
        let name = sanitizedName(rawName.isEmpty ? "attachment" : rawName)
        return try await perform(timeout: 120, discard: { (attachment: InputAttachment) in
            try? FileManager.default.removeItem(at: attachment.cacheURL)
        }) { check in
            let directory = try cacheDirectory()
            let access = source.startAccessingSecurityScopedResource()
            defer { if access { source.stopAccessingSecurityScopedResource() } }
            try check()
            let safeName = try AttachmentBatchProcessor.copyUnique(source, name: name, into: directory)
            let placed = directory.appendingPathComponent(safeName)
            do {
                let handle = try FileHandle(forReadingFrom: placed)
                let header = try handle.read(upToCount: 16)
                try? handle.close()
                try check()
                // IntentFile can lie about its extension; a recognised image
                // signature wins, and an empty/wrong suffix is repaired without
                // touching the original bytes.
                if let header, let ext = AttachmentImageCodec.detectExtension(header) {
                    let current = (safeName as NSString).pathExtension.lowercased()
                    let known = ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "tiff"]
                    if !known.contains(current) {
                        let stem = (safeName as NSString).deletingPathExtension
                        let repaired = "\(stem).\(ext)"
                        let destination = directory.appendingPathComponent(repaired)
                        try FileManager.default.moveItem(at: placed, to: destination)
                        return InputAttachment(fileName: "\((name as NSString).deletingPathExtension).\(ext)",
                                               cacheURL: destination, kind: .image)
                    }
                    return InputAttachment(fileName: name, cacheURL: placed, kind: .image)
                }
                let type = kind(name: name, header: header)
                return InputAttachment(fileName: name, cacheURL: placed, kind: type)
            } catch {
                try? FileManager.default.removeItem(at: placed)
                throw error
            }
        }
    }

    /// Same contract as stageFile for bytes a provider already materialized.
    static func stageData(_ data: Data, fileName: String) async throws -> InputAttachment {
        let name = sanitizedName(fileName.isEmpty ? "attachment" : fileName)
        let directory = try cacheDirectory()
        let destination = directory.appendingPathComponent("\(UUID().uuidString.prefix(8))_\(name)")
        try await write(data, to: destination)
        let header = data.prefix(16)
        return InputAttachment(fileName: name, cacheURL: destination,
                               kind: kind(name: name, header: header))
    }

    static func sanitizedName(_ raw: String) -> String {
        let base = (raw as NSString).lastPathComponent
        let clean = base == "." || base == ".." || base.isEmpty ? "attachment" : base
        return String(clean.prefix(180))
    }

    /// Staging dir for not-yet-sent attachments. Deliberately Application
    /// Support, not `Caches`: iOS purges Caches, and a draft chip that outlives
    /// its bytes turned a normal send into "file not found" (2026-11-08 15:43).
    nonisolated static func cacheDirectory() throws -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("InputAttachments", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Pre-upgrade location, read-only fallback while repairing an old chip.
    nonisolated static func legacyCacheDirectory() -> URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("InputAttachments", isDirectory: true)
    }
}

/// All decoding, orientation normalization, resizing and JPEG encoding uses
/// ImageIO/CoreGraphics. No UIImage.jpegData / UIGraphicsImageRenderer / CA
/// work: the #222 hang was send -> UIKit JPEG -> ImageIO -> system queue wait.
enum AttachmentImageCodec {
    static let sourceOptions: [CFString: Any] = [kCGImageSourceShouldCache: false]

    static func detectExtension(_ data: Data) -> String? {
        let b = [UInt8](data.prefix(16))
        guard b.count >= 4 else { return nil }
        if b.starts(with: [0xff, 0xd8, 0xff]) { return "jpg" }
        if b.starts(with: [0x89, 0x50, 0x4e, 0x47]) { return "png" }
        if b.starts(with: [0x47, 0x49, 0x46, 0x38]) { return "gif" }
        if b.count >= 12, Array(b[0..<4]) == [0x52, 0x49, 0x46, 0x46], Array(b[8..<12]) == [0x57, 0x45, 0x42, 0x50] { return "webp" }
        if b.count >= 12, Array(b[4..<8]) == [0x66, 0x74, 0x79, 0x70] {
            let brand = String(bytes: b[8..<12], encoding: .ascii) ?? ""
            if ["heic", "heix", "hevc", "hevx", "mif1", "msf1"].contains(brand) { return "heic" }
        }
        if b.starts(with: [0x42, 0x4d]) { return "bmp" }
        if b.starts(with: [0x49, 0x49, 0x2a, 0x00]) || b.starts(with: [0x4d, 0x4d, 0x00, 0x2a]) { return "tiff" }
        return nil
    }

    static func pixelSize(_ source: CGImageSource) -> (Int, Int)? {
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, sourceOptions as CFDictionary) as? [CFString: Any],
              let w = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let h = properties[kCGImagePropertyPixelHeight] as? NSNumber,
              w.intValue > 0, h.intValue > 0 else { return nil }
        return (w.intValue, h.intValue)
    }

    static func jpeg(_ source: CGImageSource, maxEdge: Int, quality: Double) -> Data? {
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(1, maxEdge),
            kCGImageSourceShouldCacheImmediately: true
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        return jpeg(thumbnail, quality: quality)
    }

    static func jpeg(_ image: CGImage, quality: Double, orientation: Int = 1) -> Data? {
        // Flatten alpha to white for the inference copy only. The user's
        // original PNG/GIF/HEIC file is always copied byte-for-byte separately.
        guard let context = CGContext(data: nil, width: image.width, height: image.height,
                                      bitsPerComponent: 8, bytesPerRow: 0,
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        let rect = CGRect(x: 0, y: 0, width: image.width, height: image.height)
        context.fill(rect)
        context.draw(image, in: rect)
        guard let flattened = context.makeImage() else { return nil }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        let properties: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: max(0, min(quality, 1)),
            kCGImagePropertyOrientation: orientation
        ]
        CGImageDestinationAddImage(destination, flattened, properties as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }

    static func resized(_ data: Data, maxEdge: Int) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions as CFDictionary),
              let (w, h) = pixelSize(source), max(w, h) > maxEdge else { return nil }
        return jpeg(source, maxEdge: maxEdge, quality: 0.85)
    }

    static func encoded(_ data: Data, maxEdge: Int, quality: Double) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions as CFDictionary) else { return nil }
        return jpeg(source, maxEdge: maxEdge, quality: quality)
    }

    /// Async wrappers for call sites that live on MainActor. The work is
    /// dispatched to a global queue; awaiting does not inherit MainActor.
    static func resizedJPEG(_ data: Data, maxEdge: Int) async -> Data? {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let output = autoreleasepool { resized(data, maxEdge: maxEdge) }
                continuation.resume(returning: output)
            }
        }
    }
}

/// Dimensions plus the resized inference copy, produced by one off-main pass.
struct ReadImageAnalysis: Sendable {
    let originalBytes: Int
    let originalWidth: Int
    let originalHeight: Int
    let inference: Data
    let width: Int
    let height: Int
}

extension AttachmentImageCodec {
    static func analyzeForRead(_ data: Data, maxEdge: Int = 2000) async -> ReadImageAnalysis? {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let result: ReadImageAnalysis? = autoreleasepool {
                    guard let source = CGImageSourceCreateWithData(data as CFData, sourceOptions as CFDictionary),
                          let (w, h) = pixelSize(source) else { return nil }
                    let inference = jpeg(source, maxEdge: maxEdge, quality: 0.85)
                        ?? encoded(data, maxEdge: maxEdge, quality: 0.85) ?? data
                    let dims = (CGImageSourceCreateWithData(inference as CFData, sourceOptions as CFDictionary))
                        .flatMap { pixelSize($0) } ?? (w, h)
                    return ReadImageAnalysis(originalBytes: data.count,
                                             originalWidth: w, originalHeight: h,
                                             inference: inference, width: dims.0, height: dims.1)
                }
                continuation.resume(returning: result)
            }
        }
    }
}

struct PreparedAttachmentBatch: Sendable {
    var parts: [AgentContentPart] = []
    var metas: [AttachmentMeta] = []
    var inlinedImages = 0
    var uploadedURLs: [URL] = []
}

enum AttachmentBatchProcessor {
    static func prepare(_ attachments: [InputAttachment], uploadsDir: URL,
                        inlineLimit: Int, perImageBase64Limit: Int,
                        messageBase64Limit: Int, phase: String,
                        nowStr: String) async throws -> PreparedAttachmentBatch {
        try await AttachmentIO.perform(timeout: max(60, Double(attachments.count) * 15), discard: { result in
            for url in result.uploadedURLs { try? FileManager.default.removeItem(at: url) }
        }) { check in
            let fm = FileManager.default
            let log = AppLogger(category: "Attachments")
            log.info("[UploadProbe] stage=prepare.begin phase=\(phase) count=\(attachments.count) main=\(Thread.isMainThread)")
            var batch = PreparedAttachmentBatch()
            var committed = false
            defer {
                if !committed {
                    for url in batch.uploadedURLs { try? fm.removeItem(at: url) }
                }
            }
            try check()
            try fm.createDirectory(at: uploadsDir, withIntermediateDirectories: true)
            var cumulativeBase64 = 0
            var missingFiles = 0
            for attachment in attachments {
                try check()
                guard attachment.loadState == .ready else {
                    batch.parts.append(.text("[attachment not ready yet: \(attachment.fileName)]"))
                    continue
                }
                // The chip and its bytes can be torn apart by a purge between
                // send() and here; skip that one instead of failing the batch.
                guard fm.fileExists(atPath: attachment.cacheURL.path) else {
                    missingFiles += 1
                    log.warning("[UploadProbe] stage=prepare.missing phase=\(phase) file=\(attachment.fileName)")
                    continue
                }
                let started = Date()
                do {
                    let attributes = try fm.attributesOfItem(atPath: attachment.cacheURL.path)
                    guard attributes[.type] as? FileAttributeType == .typeRegular else {
                        throw AttachmentProcessingError.invalidFile(attachment.fileName)
                    }
                    let fileSize = (attributes[.size] as? NSNumber)?.intValue ?? 0
                    let date = (attributes[.modificationDate] as? Date) ?? Date()
                    let safeName = try copyUnique(attachment.cacheURL, name: attachment.fileName, into: uploadsDir)
                    let destination = uploadsDir.appendingPathComponent(safeName)
                    batch.uploadedURLs.append(destination)
                    try fm.setAttributes([.creationDate: date, .modificationDate: date], ofItemAtPath: destination.path)
                    try check()
                    let linuxPath = "/var/minis/attachments/uploads/\(safeName)"
                    batch.metas.append(AttachmentMeta(path: linuxPath, size: fileSize, modified: date))
                    log.info("[UploadProbe] stage=prepare.copy phase=\(phase) id=\(attachment.id.uuidString.prefix(8)) kind=\(attachment.kind) bytes=\(fileSize) ms=\(Int(Date().timeIntervalSince(started) * 1000)) main=\(Thread.isMainThread)")
                    // Photos and images use this SAME path. Videos, PDFs and
                    // other files remain streaming copies; never read them all
                    // into Data just to attach them.
                    guard attachment.kind == .image else { continue }
                    let image = autoreleasepool { () -> (Data, String)? in
                        guard batch.inlinedImages < inlineLimit,
                              let source = CGImageSourceCreateWithURL(destination as CFURL, AttachmentImageCodec.sourceOptions as CFDictionary) else { return nil }
                        let rawTarget = (perImageBase64Limit / 4) * 3
                        let type = CGImageSourceGetType(source) as String?
                        let originalMime: String?
                        switch type {
                        case UTType.jpeg.identifier: originalMime = "image/jpeg"
                        case UTType.png.identifier: originalMime = "image/png"
                        case UTType.gif.identifier: originalMime = "image/gif"
                        case "org.webmproject.webp": originalMime = "image/webp"
                        default: originalMime = nil
                        }
                        if let originalMime, let (w, h) = AttachmentImageCodec.pixelSize(source),
                           max(w, h) <= 2000, fileSize <= rawTarget,
                           let data = try? Data(contentsOf: destination, options: .mappedIfSafe) {
                            return (data, originalMime)
                        }
                        let passes: [(Int, Double)] = [(2000, 0.85), (2000, 0.8), (1600, 0.75),
                                                      (1280, 0.7), (1024, 0.65), (800, 0.55), (640, 0.45)]
                        for (edge, quality) in passes {
                            if let encoded = AttachmentImageCodec.jpeg(source, maxEdge: edge, quality: quality),
                               encoded.count <= rawTarget {
                                return (encoded, "image/jpeg")
                            }
                        }
                        return nil
                    }
                    try check()
                    if let (data, mime) = image {
                        let inlineBase64 = base64Length(data.count)
                        if inlineBase64 <= perImageBase64Limit,
                           inlineBase64 <= messageBase64Limit - cumulativeBase64 {
                            batch.parts.append(.text("[attached image: \(linuxPath)]"))
                            batch.parts.append(.imageData(data: data, mimeType: mime, linuxPath: linuxPath))
                            cumulativeBase64 += inlineBase64
                            batch.inlinedImages += 1
                            log.info("[UploadProbe] stage=prepare.image phase=\(phase) bytes=\(data.count) mime=\(mime) main=\(Thread.isMainThread)")
                        } else {
                            // Encoded fine but over this message's bytes; the
                            // original still works with read_image.
                            batch.parts.append(.text("[image not inlined — original: \(linuxPath), use read_image to view it]"))
                            log.info("[UploadProbe] stage=prepare.image.deferred phase=\(phase) original=preserved")
                        }
                    } else if batch.inlinedImages >= inlineLimit {
                        // The codec was not even opened because the count cap
                        // was already full.
                        batch.parts.append(.text("[image not inlined — original: \(linuxPath), use read_image to view it]"))
                        log.info("[UploadProbe] stage=prepare.image.deferred phase=\(phase) original=preserved")
                    } else {
                        // Eligible but ImageIO could not read or encode it.
                        // Fail rather than send a silent placeholder the user
                        // believes was attached and analyzed.
                        throw AttachmentProcessingError.imageDecodeFailed
                    }
                } catch is CancellationError { throw CancellationError() }
                catch {
                    throw AttachmentProcessingError.failed(attachment.fileName, error.localizedDescription)
                }
            }
            try check()
            // Model-facing manifest and batch-reading tip live here so every
            // producer (send, queue, retry) gets exactly the same context.
            if !batch.metas.isEmpty {
                var xml = "<user-attached-files>\n"
                for meta in batch.metas {
                    xml += "  <file path=\"\(AIChatViewModel.xmlEscaped(meta.path))\" url=\"\(AIChatViewModel.xmlEscaped(meta.minisURL))\" size=\"\(meta.size)\" modified=\"\(nowStr)\" />\n"
                }
                xml += "</user-attached-files>"
                batch.parts.append(.text(xml))
            }
            let totalImages = attachments.filter { $0.kind == .image }.count
            if totalImages > batch.inlinedImages {
                let omitted = totalImages - batch.inlinedImages
                batch.parts.append(.text(
                    "<system-reminder>Only \(batch.inlinedImages) of \(totalImages) images are inlined above."
                    + " The remaining \(omitted) are saved to disk — use read_image to view them."
                    + " To stay within the context image limit (\(inlineLimit)),"
                    + " process images in batches: read a batch, analyze, then summarize your findings"
                    + " before reading the next batch.</system-reminder>"))
            }
            if missingFiles > 0 {
                batch.parts.append(.text("<system-reminder>\(missingFiles) attachment file(s) vanished before upload; the chat already shows a notice — ask the user to re-attach if the content matters.</system-reminder>"))
            }
            committed = true
            log.info("[UploadProbe] stage=prepare.done phase=\(phase) files=\(batch.metas.count) images=\(batch.inlinedImages) main=\(Thread.isMainThread)")
            return batch
        }
    }

    static func base64Length(_ rawBytes: Int) -> Int { ((max(0, rawBytes) + 2) / 3) * 4 }

    static func copyUnique(_ source: URL, name: String, into directory: URL) throws -> String {
        let fm = FileManager.default
        let safeName = (name as NSString).lastPathComponent
        guard !safeName.isEmpty, safeName != ".", safeName != ".." else {
            throw AttachmentProcessingError.invalidFile(name)
        }
        let stem = (safeName as NSString).deletingPathExtension
        let ext = (safeName as NSString).pathExtension
        for i in 0..<10000 {
            let candidate = i == 0 ? safeName : stem + "_\(i)" + (ext.isEmpty ? "" : ".\(ext)")
            let destination = directory.appendingPathComponent(candidate)
            do {
                try fm.copyItem(at: source, to: destination)
                let sourceSize = (try? fm.attributesOfItem(atPath: source.path)[.size] as? NSNumber)?.intValue
                let copiedSize = (try? fm.attributesOfItem(atPath: destination.path)[.size] as? NSNumber)?.intValue
                if let sourceSize, copiedSize != sourceSize {
                    try? fm.removeItem(at: destination)
                    throw AttachmentProcessingError.failed(name, "复制不完整")
                }
                return candidate
            }
            catch {
                if (error as NSError).domain == NSCocoaErrorDomain,
                   (error as NSError).code == NSFileWriteFileExistsError { continue }
                throw error
            }
        }
        throw AttachmentProcessingError.failed(name, "文件名冲突过多")
    }
}
