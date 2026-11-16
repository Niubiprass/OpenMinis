import CryptoKit
import Foundation

/// Bundled model data only. No downloader/account key and no audio files.
/// Read on the wake worker, never during SwiftUI rendering or a microphone tap.
enum MiniSightWakeAssets {
    enum Failure: LocalizedError {
        case missing, invalid, checksum
        var errorDescription: String? {
            switch self {
            case .missing: return "这个安装包缺少离线唤醒模型，名字唤醒未启动。"
            case .invalid: return "离线唤醒资源无效，名字唤醒未启动。"
            case .checksum: return "离线唤醒模型校验失败，未开启麦克风。"
            }
        }
    }
    struct Files: Sendable {
        let encoder: URL
        let decoder: URL
        let joiner: URL
        let tokens: URL
        let vocabulary: Set<String>
    }
    struct Manifest: Decodable {
        let schema: Int
        let format: String
        let engineVersion: String
        let sampleRate: Int
        let files: [Entry]
    }
    struct Entry: Decodable {
        let file: String
        let bytes: Int
        let sha256: String
    }
    static let resourceFiles: Set<String> = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"]
    static let expectedHashes: [String: String] = [
        "encoder.onnx": "4ded45b30961270f2a9a64bede4569b324c36d4f3a772c1b35bb70a244150675",
        "decoder.onnx": "fb581d6734511676e246e0dff2fea01b31b0913176cb3ca64576dbab0a177774",
        "joiner.onnx": "f79760052b87239e325f0567c752ad3130b30d92effb847d4307743c20c59a24",
        "tokens.txt": "72316508d9119696145abc6f1f8cdc46287535c34e5ce7e595f845cb1499cf2e"
    ]

    static func load(bundle: Bundle = .main) throws -> Files {
        guard let root = bundle.resourceURL?.appendingPathComponent("MiniSightWake", isDirectory: true) else {
            throw Failure.missing
        }
        return try load(at: root)
    }
    static func load(at root: URL) throws -> Files {
        guard !Thread.isMainThread else { throw Failure.invalid }
        let info = try root.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard info.isDirectory == true, info.isSymbolicLink != true else { throw Failure.invalid }
        let data = try read(root.appendingPathComponent("manifest.json"), limit: 32 * 1024)
        let manifest = try JSONDecoder().decode(Manifest.self, from: data)
        guard manifest.schema == 1, manifest.format == "minisight-kws-wenetspeech-v1",
              manifest.engineVersion == "2.0.1", manifest.sampleRate == 16000,
              manifest.files.count == 4, Set(manifest.files.map(\.file)) == resourceFiles else { throw Failure.invalid }
        var total = 0
        var vocabulary = Set<String>()
        for entry in manifest.files {
            guard entry.bytes > 0, entry.bytes <= 12 * 1024 * 1024,
                  entry.sha256 == expectedHashes[entry.file],
                  entry.sha256.count == 64, entry.sha256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
                throw Failure.invalid
            }
            total += entry.bytes
            guard total <= 20 * 1024 * 1024 else { throw Failure.invalid }
            let data = try read(root.appendingPathComponent(entry.file), limit: entry.bytes)
            guard data.count == entry.bytes,
                  SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == entry.sha256 else { throw Failure.checksum }
            if entry.file == "tokens.txt" { vocabulary = try MiniSightWakeName.vocabulary(from: data) }
        }
        guard !vocabulary.isEmpty else { throw Failure.invalid }
        return Files(encoder: root.appendingPathComponent("encoder.onnx"), decoder: root.appendingPathComponent("decoder.onnx"),
                     joiner: root.appendingPathComponent("joiner.onnx"), tokens: root.appendingPathComponent("tokens.txt"), vocabulary: vocabulary)
    }
    private static func read(_ url: URL, limit: Int) throws -> Data {
        let info = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard url.isFileURL, info.isRegularFile == true, info.isSymbolicLink != true,
              let size = info.fileSize, size > 0, size <= limit else { throw Failure.invalid }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var data = Data()
        while let chunk = try handle.read(upToCount: min(64 * 1024, limit + 1 - data.count)), !chunk.isEmpty {
            data.append(chunk)
            guard data.count <= limit else { throw Failure.invalid }
        }
        guard data.count == size else { throw Failure.invalid }
        return data
    }
}
