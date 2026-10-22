import Foundation

struct MemoryLibraryRoot: Identifiable {
    let id: String
    let title: String
    let directory: URL
    let isReadOnly: Bool
    let isGlobal: Bool
    /// Optional section filter (daily vs GLOBAL.md) for roots sharing one directory.
    let nameFilter: ((String) -> Bool)?

    init(id: String, title: String, directory: URL, isReadOnly: Bool, isGlobal: Bool,
         nameFilter: ((String) -> Bool)? = nil) {
        self.id = id
        self.title = title
        self.directory = directory
        self.isReadOnly = isReadOnly
        self.isGlobal = isGlobal
        self.nameFilter = nameFilter
    }
}

/// Only caller-supplied directories are authorized; no session or global-root lookup.
final class MemoryDocumentStore {
    struct Snapshot: Identifiable {
        let rootID: String
        let fileName: String
        let originalText: String
        let exists: Bool
        fileprivate let originalBytes: Data?
        fileprivate let directory: URL
        var id: String { rootID + "\u{0}" + fileName }
    }

    enum Failure: LocalizedError, Equatable {
        case unauthorized, unsafePath, missing, invalidUTF8, readOnly, conflict, unsavedExport, coordination
        var errorDescription: String? {
            switch self {
            case .unauthorized: return NSLocalizedString("The memory directory is not authorized or has a duplicate ID.", comment: "Memory library error")
            case .unsafePath: return NSLocalizedString("Only regular Markdown files directly inside the allowed directory are supported. Symlinks are not allowed.", comment: "Memory library error")
            case .missing: return NSLocalizedString("The memory file no longer exists.", comment: "Memory library error")
            case .invalidUTF8: return NSLocalizedString("The memory file is not valid UTF-8. Nothing was saved.", comment: "Memory library error")
            case .readOnly: return NSLocalizedString("This memory file or directory is read-only.", comment: "Memory library error")
            case .conflict: return NSLocalizedString("The file changed or was removed. Your draft is kept. Cancel to reload before editing again.", comment: "Memory library error")
            case .unsavedExport: return NSLocalizedString("Save or cancel the draft before sharing a saved file.", comment: "Memory library error")
            case .coordination: return NSLocalizedString("File coordination did not complete. Please try again.", comment: "Memory library error")
            }
        }
    }

    private let roots: [MemoryLibraryRoot]
    private let directories: [URL]
    // Shared across store instances, including independently presented detail views.
    private static let lock = NSLock()
    private let fm = FileManager.default

    init(roots: [MemoryLibraryRoot]) {
        self.roots = roots
        // Missing roots must retain directory semantics after resolving existing ancestors.
        // URL equality includes the directory hint on macOS; without it, a missing
        // GLOBAL.md placeholder can be rejected even though its parent is authorized.
        directories = roots.map { Self.directoryURL($0.directory.standardizedFileURL.resolvingSymlinksInPath()) }
    }

    func list() throws -> [Snapshot] {
        try locked {
            var result: [Snapshot] = []
            for root in roots {
                let directory = try authorizedDirectory(rootID: root.id)
                var names: [String] = []
                if try fileType(at: directory) != nil {
                    names = try fm.contentsOfDirectory(atPath: directory.path).filter {
                        $0.hasSuffix(".md") && !$0.hasPrefix(".") && $0.caseInsensitiveCompare("SOUL.md") != .orderedSame
                    }
                }
                if root.isGlobal && !names.contains("GLOBAL.md") { names.append("GLOBAL.md") }
                for name in names.sorted(by: { a, b in
                    if a == "GLOBAL.md" { return b != a }
                    if b == "GLOBAL.md" { return false }
                    return a > b
                }) {
                    // No recursion; a directory or symlink named *.md is an explicit error.
                    result.append(try readUnlocked(rootID: root.id, fileName: name))
                }
            }
            return result
        }
    }

    func readSnapshot(rootID: String, fileName: String) throws -> Snapshot {
        try locked { try readUnlocked(rootID: rootID, fileName: fileName) }
    }

    /// CAS covers every writer using this store. External uncoordinated writers do not share the lock.
    func save(_ snapshot: Snapshot, text: String) throws -> Snapshot {
        try locked {
            let root = try authorizedRoot(snapshot.rootID)
            guard !root.isReadOnly else { throw Failure.readOnly }
            let url = try documentURL(rootID: root.id, fileName: snapshot.fileName)
            guard snapshot.directory == url.deletingLastPathComponent() else { throw Failure.unauthorized }
            // No directory is created by init/list/read/cancel. Creation is deferred until save.
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            return try coordinated(at: url, writing: true) { coordinatedURL in
                guard coordinatedURL.standardizedFileURL == url,
                      try self.documentURL(rootID: root.id, fileName: snapshot.fileName) == url else {
                    throw Failure.unsafePath
                }
                // Atomic replacement can succeed for a read-only file when
                // its parent is writable. Respect file permissions as well as
                // the caller's read-only root instead of silently replacing it.
                guard self.fm.isWritableFile(atPath: url.deletingLastPathComponent().path),
                      !self.fm.fileExists(atPath: url.path) || self.fm.isWritableFile(atPath: url.path) else {
                    throw Failure.readOnly
                }
                let current = try self.readBytes(at: url)
                // Data equality is byte-exact, unlike Swift's canonically equivalent String equality.
                guard (current != nil) == snapshot.exists, current == snapshot.originalBytes else {
                    throw Failure.conflict
                }
                let bytes = Data(text.utf8)
                try bytes.write(to: url, options: .atomic)
                return self.makeSnapshot(rootID: root.id, fileName: snapshot.fileName, directory: snapshot.directory, bytes: bytes)
            }
        }
    }

    /// Exports immutable, previously read/saved snapshots, never an editor's draft or a live-file copy.
    func export(_ snapshots: [Snapshot]) throws -> URL {
        try locked {
            guard !snapshots.isEmpty else { throw Failure.unsavedExport }
            var sections = ["# Memory documents\n"]
            for snapshot in snapshots.sorted(by: { ($0.rootID, $0.fileName) < ($1.rootID, $1.fileName) }) {
                let root = try authorizedRoot(snapshot.rootID)
                let url = try documentURL(rootID: root.id, fileName: snapshot.fileName)
                guard snapshot.directory == url.deletingLastPathComponent() else { throw Failure.unauthorized }
                guard snapshot.exists else { throw Failure.unsavedExport }
                let source = Self.heading(root.title) + " [" + Self.heading(root.id) + "]"
                sections.append("## Source: \(source)\n\n### File: \(Self.heading(snapshot.fileName))\n\n\(snapshot.originalText)\n")
            }
            let directory = fm.temporaryDirectory.appendingPathComponent("memory-export-" + UUID().uuidString, isDirectory: true)
            try fm.createDirectory(at: directory, withIntermediateDirectories: false)
            let url = directory.appendingPathComponent("memories.md")
            try Data(sections.joined(separator: "\n---\n\n").utf8).write(to: url, options: .atomic)
            return url
        }
    }

    private func locked<T>(_ operation: () throws -> T) rethrows -> T {
        Self.lock.lock()
        defer { Self.lock.unlock() }
        return try operation()
    }

    private func authorizedRoot(_ id: String) throws -> MemoryLibraryRoot {
        let matches = roots.filter { $0.id == id }
        guard matches.count == 1 else { throw Failure.unauthorized }
        return matches[0]
    }

    private static func directoryURL(_ url: URL) -> URL {
        URL(fileURLWithPath: url.path, isDirectory: true)
    }

    private func authorizedDirectory(rootID: String) throws -> URL {
        let root = try authorizedRoot(rootID)
        guard root.directory.isFileURL, root.directory.path.hasPrefix("/"),
              let index = roots.firstIndex(where: { $0.id == rootID }) else { throw Failure.unsafePath }
        let original = root.directory.standardizedFileURL
        var ancestor = URL(fileURLWithPath: "/", isDirectory: true)
        for component in original.pathComponents.dropFirst() {
            ancestor.appendPathComponent(component, isDirectory: true)
            if let type = try fileType(at: ancestor) {
                #if canImport(Darwin)
                // Apple's system aliases are outside the caller-controlled memory tree.
                if ancestor.path == "/var" || ancestor.path == "/tmp" { continue }
                #endif
                guard type == .typeDirectory else { throw Failure.unsafePath }
            }
        }
        let canonical = Self.directoryURL(original.resolvingSymlinksInPath())
        guard canonical == directories[index] else { throw Failure.unsafePath }
        return canonical
    }

    private func documentURL(rootID: String, fileName: String) throws -> URL {
        guard fileName.count > 3, fileName.hasSuffix(".md"), !fileName.hasPrefix("."),
              !fileName.contains("/"), !fileName.contains("\\"), !fileName.contains(":"),
              !fileName.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else {
            throw Failure.unsafePath
        }
        let directory = try authorizedDirectory(rootID: rootID)
        let url = directory.appendingPathComponent(fileName)
        guard url.deletingLastPathComponent() == directory else { throw Failure.unsafePath }
        if let type = try fileType(at: url), type != .typeRegular { throw Failure.unsafePath }
        return url
    }

    private func fileType(at url: URL) throws -> FileAttributeType? {
        do { return try fm.attributesOfItem(atPath: url.path)[.type] as? FileAttributeType }
        catch let error as NSError {
            if error.domain == NSCocoaErrorDomain &&
                [CocoaError.fileNoSuchFile.rawValue, CocoaError.fileReadNoSuchFile.rawValue].contains(error.code) {
                return nil
            }
            throw error
        }
    }

    private func readBytes(at url: URL) throws -> Data? {
        guard let type = try fileType(at: url) else { return nil }
        guard type == .typeRegular else { throw Failure.unsafePath }
        let bytes = try Data(contentsOf: url)
        guard String(data: bytes, encoding: .utf8) != nil else { throw Failure.invalidUTF8 }
        return bytes
    }

    private func readUnlocked(rootID: String, fileName: String) throws -> Snapshot {
        let root = try authorizedRoot(rootID)
        let url = try documentURL(rootID: rootID, fileName: fileName)
        if try fileType(at: url) == nil {
            guard root.isGlobal && ["GLOBAL.md", "SOUL.md"].contains(fileName) else { throw Failure.missing }
            return makeSnapshot(rootID: rootID, fileName: fileName, directory: url.deletingLastPathComponent(), bytes: nil)
        }
        return try coordinated(at: url, writing: false) { coordinatedURL in
            guard coordinatedURL.standardizedFileURL == url,
                  try self.documentURL(rootID: rootID, fileName: fileName) == url else { throw Failure.unsafePath }
            let bytes = try self.readBytes(at: url)
            guard bytes != nil || (root.isGlobal && ["GLOBAL.md", "SOUL.md"].contains(fileName)) else { throw Failure.missing }
            return self.makeSnapshot(rootID: rootID, fileName: fileName, directory: url.deletingLastPathComponent(), bytes: bytes)
        }
    }

    private func makeSnapshot(rootID: String, fileName: String, directory: URL, bytes: Data?) -> Snapshot {
        Snapshot(rootID: rootID, fileName: fileName, originalText: bytes.map { String(decoding: $0, as: UTF8.self) } ?? "",
                 exists: bytes != nil, originalBytes: bytes, directory: directory)
    }

    private static func heading(_ text: String) -> String {
        text.replacingOccurrences(of: "\r", with: " ").replacingOccurrences(of: "\n", with: " ")
    }

    /// [T-memory-import] Writes `text` as `fileName` under `rootID`, honouring
    /// the caller's same-name decision. Deliberately separate from `save()`:
    /// an import has no prior snapshot to compare against, so there is nothing
    /// to CAS — the conflict policy IS the caller's explicit choice.
    ///
    /// `overwrite == false` never touches an existing file (`.conflict`), which
    /// is what the "跳过" and "重命名" branches rely on.
    @discardableResult
    func importDocument(rootID: String, fileName: String, text: String, overwrite: Bool) throws -> Snapshot {
        try locked {
            let root = try authorizedRoot(rootID)
            guard !root.isReadOnly else { throw Failure.readOnly }
            let url = try documentURL(rootID: root.id, fileName: fileName)
            guard url.pathExtension.lowercased() == "md" else { throw Failure.unsafePath }
            if !overwrite, fm.fileExists(atPath: url.path) { throw Failure.conflict }
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            return try coordinated(at: url, writing: true) { coordinatedURL in
                guard coordinatedURL.standardizedFileURL == url else { throw Failure.unsafePath }
                guard self.fm.isWritableFile(atPath: url.deletingLastPathComponent().path) else {
                    throw Failure.readOnly
                }
                let bytes = Data(text.utf8)
                try bytes.write(to: url, options: .atomic)
                return self.makeSnapshot(
                    rootID: root.id,
                    fileName: fileName,
                    directory: url.deletingLastPathComponent(),
                    bytes: bytes
                )
            }
        }
    }

    /// Whether `fileName` already exists under `rootID` (drives the conflict
    /// prompt before anything is written). An unreadable/invalid name reports
    /// false: `importDocument` re-validates and throws the real error.
    func documentExists(rootID: String, fileName: String) -> Bool {
        guard let root = roots.first(where: { $0.id == rootID }) else { return false }
        do {
            let url = try documentURL(rootID: root.id, fileName: fileName)
            return fm.fileExists(atPath: url.path)
        } catch {
            return false
        }
    }

    private func coordinated<T>(at url: URL, writing: Bool, _ operation: @escaping (URL) throws -> T) throws -> T {
        #if canImport(Darwin)
        let coordinator = NSFileCoordinator(filePresenter: nil)
        var error: NSError?
        var result: Result<T, Error>?
        let accessor: (URL) -> Void = { coordinatedURL in
            result = Result { try operation(coordinatedURL) }
        }
        if writing {
            coordinator.coordinate(writingItemAt: url, options: [], error: &error, byAccessor: accessor)
        } else {
            coordinator.coordinate(readingItemAt: url, options: [], error: &error, byAccessor: accessor)
        }
        if let error = error { throw error }
        guard let result = result else { throw Failure.coordination }
        return try result.get()
        #else
        return try operation(url)
        #endif
    }
}
