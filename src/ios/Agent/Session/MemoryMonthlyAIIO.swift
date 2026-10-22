import Foundation

/// File I/O for the manual AI monthly digest, kept out of both the memory
/// store (which must not silently swallow read failures) and the settings
/// view (which must not grow a directory scanner or a file writer).
enum MemoryMonthlyAIIO {
    static func dailyTexts(in directory: URL, month: String) -> [(day: String, text: String)] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        return names
            .filter { $0.hasPrefix("\(month)-") && $0.hasSuffix(".md") && $0.count == 13 }
            .sorted()
            .compactMap { name in
                let url = directory.appendingPathComponent(name)
                guard let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
                return (String(name.dropLast(3)), text)
            }
    }

    static func writeAISummary(_ digest: MonthlyMemoryDigest, in directory: URL) throws {
        let url = directory.appendingPathComponent("\(digest.month)-AI.md")
        let body = "# \(digest.month) 月记忆 AI 摘要\n\n"
            + "> 由 \(digest.sourceDays) 份日记忆生成；原文和机械月记忆不受影响。\n\n"
            + "\(digest.summary)\n"
        guard let data = body.data(using: .utf8) else { return }
        try data.write(to: url, options: .atomic)
    }
}
