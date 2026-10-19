import Foundation

// MARK: - [T-memory-import] Inbound Markdown from other apps

/// Receives a Markdown file handed to Minis by another app's share sheet (or
/// by "Open in…" / Files) and stages it for the memory importer.
///
/// Why a separate inbox instead of the chat attachment pipeline: a `.md` file
/// shared to Minis is almost always a memory the user wants to keep, not a
/// document to attach to a chat. Routing it to the import sheet lets the user
/// choose the destination and resolve same-name conflicts — the two things the
/// chat pipeline cannot ask about.
///
/// The file is read immediately (security-scoped access is only valid inside
/// the open-URL callback) and the text is kept in memory; nothing is written
/// until the user confirms in `MemoryImportView`.
enum MemoryImportInbox {
    struct Payload: Identifiable, Equatable {
        let id = UUID()
        let fileName: String
        let text: String
    }

    /// Latest staged payload. Set by `handle(_:)`; cleared by the importer.
    private(set) static var pending: Payload?

    /// Returns true when `url` is a Markdown/text file this app should treat as
    /// a memory import. Anything else (backups, images, PDFs) returns false so
    /// the existing attachment pipeline keeps handling it.
    @discardableResult
    static func handle(_ url: URL) -> Bool {
        guard url.isFileURL else { return false }
        let ext = url.pathExtension.lowercased()
        guard ext == "md" || ext == "markdown" || ext == "txt" else { return false }

        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }

        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8) else {
            AppLogger(category: "MemoryImport").error("ingest failed: unreadable \(ext)")
            return false
        }
        pending = Payload(fileName: url.lastPathComponent, text: text)
        AppLogger(category: "MemoryImport").info("staged \(ext) \(data.count) bytes")
        return true
    }

    static func clear() {
        pending = nil
    }
}
