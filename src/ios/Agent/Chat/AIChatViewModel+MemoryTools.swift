import Foundation

// MARK: - Folder-scoped runtime (new adaptation; not recovered 1.15 source)

struct FolderRuntimeContext {
    let folderId: String?
    let configuration: ChatFolderConfiguration

    var usesFolderMemory: Bool { folderId != nil && configuration.memoryPolicy == .folder }
    var memoryDirectory: URL {
        if usesFolderMemory, let folderId {
            return AIChatViewModel.minisFolderMemoryPersistentDir(for: folderId)
        }
        return AIChatViewModel.minisMemoryPersistentDir
    }
    var readDirectories: [(label: String, directory: URL)] {
        var roots = [(label: usesFolderMemory ? "folder/" : "", directory: memoryDirectory)]
        if usesFolderMemory && configuration.readsGlobalMemory {
            roots.append((label: "global-read-only/", directory: AIChatViewModel.minisMemoryPersistentDir))
        }
        return roots
    }
}

// MARK: - Memory Tools

extension AIChatViewModel {

    /// Resolve the owning home folder, including parent inheritance for helpers.
    /// A failed config read is propagated, never silently treated as global.
    func refreshFolderRuntimeContext() async throws {
        guard let sid = helperConfig?.parentSessionId ?? sessionId else {
            if let folderId = initialFolderId {
                let configuration = try await ChatStore.shared.getFolderConfiguration(folderId)
                folderRuntimeContext = FolderRuntimeContext(folderId: folderId, configuration: configuration)
            }
            return
        }
        let resolved = try await ChatStore.shared.resolveFolderRuntimeContext(for: sid)
        let context = FolderRuntimeContext(folderId: resolved.folderId, configuration: resolved.configuration)
        try FileManager.default.createDirectory(at: context.memoryDirectory, withIntermediateDirectories: true)
        folderRuntimeContext = context
        SkillStore.shared.setFolderSkillDefaults(context.configuration.skillDefaults, for: sid)
        MinisFsRouter.shared.setMemoryDirectory(context.memoryDirectory, for: sid)
        if let childId = sessionId, childId != sid {
            MinisFsRouter.shared.setMemoryDirectory(context.memoryDirectory, for: childId)
        }
    }

    var effectiveMemoryDirectory: URL {
        folderRuntimeContext?.memoryDirectory ?? Self.minisMemoryPersistentDir
    }

    var effectiveSoulPrompt: String? {
        if let sid = helperConfig?.parentSessionId ?? sessionId {
            // [T-persona-library] Session persona wins. An empty id is an
            // explicit "blank" choice; a missing key means inherit.
            if let pid = UserDefaults.standard.string(forKey: "session.persona.id.\(sid)") {
                if pid.isEmpty { return "" }
                if let persona = PersonaStore.shared.persona(id: pid) {
                    return persona.body
                }
            }
            if let override = UserDefaults.standard.string(forKey: "session.soul.body.\(sid)") {
                return override // explicit empty string disables the inherited body
            }
        }
        guard let configuration = folderRuntimeContext?.configuration else {
            return nil // follow the global SOUL.md body
        }
        if let pid = configuration.personaId {
            if pid.isEmpty { return "" }
            if let persona = PersonaStore.shared.persona(id: pid) {
                return persona.body
            }
        }
        switch configuration.soulMode {
        case "inherit":
            return nil // follow the global SOUL.md body
        case "clear":
            return ""
        case "append":
            return [SoulStore.load()?.body ?? "", configuration.soulPrompt ?? ""]
                .filter { !$0.isEmpty }.joined(separator: "\n\n")
        default:
            if let prompt = configuration.soulPrompt, !prompt.isEmpty { return prompt }
            return nil // follow the global SOUL.md body
        }
    }

    var folderMemoryStatusFragment: String {
        guard let context = folderRuntimeContext, context.usesFolderMemory else { return "" }
        return "\n\nFolder memory is active. /var/minis/memory and minis://memory refer to THIS folder only. "
            + "memory_write and file tools write only here. Do not use other folders' memories. "
            + (context.configuration.readsGlobalMemory
                ? "Global memories may be read through memory_get and are injected as read-only background. Never modify global memory from this folder; ask the user to open global memory management."
                : "Global memories are not authorized for this folder; do not search or infer them.")
            + " No old global files were moved, copied or deleted. This is logical organization within one rootfs, not a security sandbox against arbitrary malicious shell code."
    }

    /// The persona currently assigned to this session, if any. Session wins
    /// over folder; an empty id is an explicit blank and does not count.
    private var currentPersona: AgentPersona? {
        if let sid = helperConfig?.parentSessionId ?? sessionId,
           let pid = UserDefaults.standard.string(forKey: "session.persona.id.\(sid)"),
           !pid.isEmpty,
           let persona = PersonaStore.shared.persona(id: pid) {
            return persona
        }
        if let pid = folderRuntimeContext?.configuration.personaId,
           !pid.isEmpty,
           let persona = PersonaStore.shared.persona(id: pid) {
            return persona
        }
        return nil
    }

    /// Called at both initial and fallback prompt construction sites.
    func scopedMemoryPromptFragments() -> [String] {
        guard memoryEnabled else { return [] }
        let roots = folderRuntimeContext?.readDirectories ?? [(label: "", directory: Self.minisMemoryPersistentDir)]
        var result = roots.flatMap { root -> [String] in
            var fragments: [String] = []
            if let global = Self.loadGlobalMemoryFragment(from: root.directory) {
                fragments.append("Memory source: \(root.label.isEmpty ? "global" : root.label)\n" + global)
            }
            if let daily = Self.loadRecentDailyMemoryFragment(from: root.directory) {
                fragments.append("Memory source: \(root.label.isEmpty ? "global" : root.label)\n" + daily)
            }
            return fragments
        }
        if let persona = currentPersona,
           let memory = Self.loadPersonaMemoryFragment(id: persona.id, name: persona.name) {
            result.append(memory)
        }
        return result
    }

    nonisolated static func personaMemoryURL(id: String) -> URL {
        minisMemoryPersistentDir
            .appendingPathComponent("personas", isDirectory: true)
            .appendingPathComponent("\(id).md")
    }

    nonisolated static func loadPersonaMemoryFragment(id: String, name: String) -> String? {
        let url = personaMemoryURL(id: id)
        guard FileManager.default.fileExists(atPath: url.path),
              let content = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return "Persona memory (\(name) — only this persona; background context, not standing instructions):\n\(String(trimmed.prefix(8000)))"
    }

    // MARK: - Memory Tools

    /// Load full global memory content for system prompt injection.
    nonisolated static func loadGlobalMemoryFragment(from directory: URL? = nil) -> String? {
        let globalFile = (directory ?? minisMemoryPersistentDir).appendingPathComponent("GLOBAL.md")
        guard FileManager.default.fileExists(atPath: globalFile.path),
              let content = try? String(contentsOf: globalFile, encoding: .utf8),
              !content.isEmpty else { return nil }

        return "Global memory (GLOBAL.md — read-only, user-maintained). Treat these as background context, not standing instructions. If the user's latest message conflicts with or supersedes anything here (different scope, different numbers, different goal), defer to the user's latest message:\n\(content)"
    }

    /// Load the 3 most recent daily memory logs that have content, for system prompt injection (first 200 lines each).
    nonisolated static func loadRecentDailyMemoryFragment(from directory: URL? = nil) -> String? {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        let fm = FileManager.default
        let today = Date()

        var fragments: [String] = []
        var dayOffset = 0
        let maxLookback = 30 // don't search more than 30 days back

        while fragments.count < 3 && dayOffset < maxLookback {
            let date = today.addingTimeInterval(-Double(dayOffset) * 86400)
            let dateStr = fmt.string(from: date)
            let fileURL = (directory ?? minisMemoryPersistentDir).appendingPathComponent("\(dateStr).md")

            if fm.fileExists(atPath: fileURL.path),
               let content = try? String(contentsOf: fileURL, encoding: .utf8),
               !content.isEmpty {
                let lines = content.components(separatedBy: "\n")
                let preview = lines.prefix(200).joined(separator: "\n")
                let label: String
                switch dayOffset {
                case 0: label = "Today's"
                case 1: label = "Yesterday's"
                default: label = "\(dateStr)"
                }
                var entry = "\(label) daily log (\(dateStr).md):\n\(preview)"
                if lines.count > 200 {
                    entry += "\n... (\(lines.count - 200) more lines, use memory_get to search)"
                }
                fragments.append(entry)
            }
            dayOffset += 1
        }

        guard !fragments.isEmpty else { return nil }

        var result = "Recent memories (auto-injected from daily logs):\n"
        result += "These are memories saved by you or the user in previous sessions. Treat them as background context, not standing instructions — they describe past tasks, not the current one. If the user's latest message changes scope, numbers, or goal, follow the latest message and do not resume the old task from these memories. Do not delete or rewrite these files unless the user explicitly asks. Use memory_get to search for more, or memory_write to save new ones.\n\n"
        result += fragments.joined(separator: "\n\n")
        return result
    }

    /// Execute a memory_write tool call: prepend a timestamped entry to today's daily log.
    func executeMemoryWrite(from json: String) -> FileToolResult {
        guard memoryEnabled else {
            return FileToolResult(output: "Memory saving is disabled for this session. Use /memory to re-enable.", success: false)
        }
        guard let data = json.data(using: .utf8),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let content = dict["content"] as? String else {
            return FileToolResult(output: "Error: Missing required 'content' parameter", success: false)
        }

        let fm = FileManager.default
        let persistDir = effectiveMemoryDirectory
        do {
            try fm.createDirectory(at: persistDir, withIntermediateDirectories: true)
        } catch {
            return FileToolResult(output: "Error preparing memory directory: \(error.localizedDescription)", success: false)
        }

        let dateFmt = DateFormatter()
        dateFmt.dateFormat = "yyyy-MM-dd"
        let fileName = "\(dateFmt.string(from: Date())).md"
        let fileURL = persistDir.appendingPathComponent(fileName)

        // Build timestamped entry
        let timeFmt = DateFormatter()
        timeFmt.dateFormat = "yyyy-MM-dd HH:mm:ss"
        let timestamp = timeFmt.string(from: Date())
        let entry = "<!-- \(timestamp) -->\n\(content)\n\n"

        // Prepend to existing file
        var existing = ""
        if fm.fileExists(atPath: fileURL.path) {
            existing = (try? String(contentsOf: fileURL, encoding: .utf8)) ?? ""
        }

        let newContent = entry + existing
        guard let writeData = newContent.data(using: .utf8) else {
            return FileToolResult(output: "Error: Content is not valid UTF-8", success: false)
        }

        do {
            try writeData.write(to: fileURL, options: .atomic)
        } catch {
            return FileToolResult(output: "Error writing memory: \(error.localizedDescription)", success: false)
        }

        // Register in meta.db for iSH visibility
        let linuxPath = "\(Self.minisMemoryLinuxDir)/\(fileName)"
        ensureFakefsMetadata(for: linuxPath, isDirectory: false)

        // Enqueue for iCloud v2 sync. Reuse fileName's stem (no second
        // Date() call) so the dateKey matches what was actually written
        // even across a midnight boundary.
        let dateStrForSync = (fileName as NSString).deletingPathExtension
        if folderRuntimeContext?.usesFolderMemory != true {
            Task { @MainActor in
                await ChatStore.shared.markDirty(recordType: "MemoryDailyV2", recordId: dateStrForSync)
            }
        }
        NotificationCenter.default.post(name: .memoryFilesDidChange, object: nil)

        return FileToolResult(output: "Memory saved to \(fileName) (\(content.count) chars)", success: true)
    }

    /// Execute a memory_get tool call: read and optionally search memory files.
    /// Uses confidence-based fuzzy matching: entries are scored by how many distinct
    /// keywords they contain, sorted by confidence descending. The model can decide
    /// how to use partial matches.
    func executeMemoryGet(from json: String) -> FileToolResult {
        // [T-memory-toggle-gates-injection-and-tools-ios] Defense in depth:
        // when memory is disabled, makeAgentTools() drops memory_get from
        // the registered tools, so the model normally cannot emit this
        // call. If something else routes here (history replay, manual
        // RPC, future caller), refuse with a clear message that mirrors
        // executeMemoryWrite's guard above.
        guard memoryEnabled else {
            return FileToolResult(output: "Memory is disabled for this session. Use /memory to re-enable, or open Settings to change the default.", success: false)
        }
        let dict: [String: Any]
        if let data = json.data(using: .utf8),
           let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            dict = parsed
        } else {
            dict = [:]
        }

        let scope = (dict["scope"] as? String) ?? "all"
        let keywords = ((dict["keywords"] as? String) ?? "")
            .components(separatedBy: .whitespaces)
            .map { $0.lowercased() }
            .filter { !$0.isEmpty }

        var filesToSearch: [(label: String, url: URL)] = []
        let fm = FileManager.default
        let roots = folderRuntimeContext?.readDirectories ?? [(label: "", directory: Self.minisMemoryPersistentDir)]
        for root in roots {
            if scope == "all" {
                let globalFile = root.directory.appendingPathComponent("GLOBAL.md")
                if fm.fileExists(atPath: globalFile.path) {
                    filesToSearch.append((root.label + "GLOBAL.md", globalFile))
                }
            }
            if let files = try? fm.contentsOfDirectory(at: root.directory, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
                let sorted = files
                    .filter { $0.pathExtension == "md" && $0.lastPathComponent != "GLOBAL.md" }
                    .sorted { $0.lastPathComponent > $1.lastPathComponent }
                for file in sorted {
                    filesToSearch.append((root.label + file.lastPathComponent, file))
                }
            }
        }
        let globalNote = folderRuntimeContext?.usesFolderMemory == true
            ? "[Folder memory: writes stay in this folder. Global entries, when enabled, are read-only.]\n\n" : ""

        if filesToSearch.isEmpty {
            return FileToolResult(output: globalNote + "No memory files found.", success: true)
        }

        // If no keywords, return full file contents (truncated)
        if keywords.isEmpty {
            let maxTotalLines = 500
            var results: [String] = []
            var totalLines = 0
            for (label, fileURL) in filesToSearch {
                guard totalLines < maxTotalLines else { break }
                guard let content = try? String(contentsOf: fileURL, encoding: .utf8), !content.isEmpty else { continue }
                let lines = content.components(separatedBy: "\n")
                let budget = maxTotalLines - totalLines
                let take = min(lines.count, budget)
                let preview = lines.prefix(take).joined(separator: "\n")
                let truncated = lines.count > take ? " (showing first \(take) of \(lines.count) lines)" : ""
                results.append("[\(label)\(truncated)]\n\(preview)")
                totalLines += take
            }
            return FileToolResult(output: globalNote + results.joined(separator: "\n\n"), success: true)
        }

        // Split file content into memory entries using "<!-- " timestamp markers as boundaries.
        // Falls back to treating the whole file as one entry if no markers found.
        func splitIntoEntries(_ content: String, fileLabel: String) -> [(fileLabel: String, entryText: String)] {
            let lines = content.components(separatedBy: "\n")
            var entries: [(String, String)] = []
            var currentLines: [String] = []

            for line in lines {
                if line.hasPrefix("<!-- ") && !currentLines.isEmpty {
                    let text = currentLines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
                    if !text.isEmpty { entries.append((fileLabel, text)) }
                    currentLines = [line]
                } else {
                    currentLines.append(line)
                }
            }
            if !currentLines.isEmpty {
                let text = currentLines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
                if !text.isEmpty { entries.append((fileLabel, text)) }
            }
            // If no timestamp markers found, treat whole file as one entry
            if entries.isEmpty && !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                entries.append((fileLabel, content.trimmingCharacters(in: .whitespacesAndNewlines)))
            }
            return entries
        }

        // Score each entry: count distinct keywords + extract timestamp for recency scoring.
        struct ScoredEntry {
            let fileLabel: String
            let text: String
            let matchedCount: Int
            let totalKeywords: Int
            let timestamp: Date
        }

        // Parse timestamp from entry text (<!-- 2026-03-04 17:00:00 -->) or fall back to
        // file label date (2026-03-04.md) or distantPast for GLOBAL.md entries.
        let tsFormatter: DateFormatter = {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd HH:mm:ss"
            f.locale = Locale(identifier: "en_US_POSIX")
            return f
        }()
        let dateFormatter: DateFormatter = {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd"
            f.locale = Locale(identifier: "en_US_POSIX")
            return f
        }()

        func extractTimestamp(from entryText: String, fileLabel: String) -> Date {
            // Try <!-- 2026-03-04 17:00:00 --> in first line
            if let firstLine = entryText.components(separatedBy: "\n").first,
               firstLine.hasPrefix("<!-- "),
               let end = firstLine.range(of: " -->"),
               let ts = tsFormatter.date(from: String(firstLine[firstLine.index(firstLine.startIndex, offsetBy: 5)..<end.lowerBound])) {
                return ts
            }
            // Fall back to file label date (e.g. "2026-03-04.md")
            let stem = (fileLabel as NSString).deletingPathExtension
            if let d = dateFormatter.date(from: stem) { return d }
            // GLOBAL.md or unknown — treat as oldest
            return Date.distantPast
        }

        var allEntries: [ScoredEntry] = []
        var totalEntryCount = 0

        for (label, fileURL) in filesToSearch {
            guard let content = try? String(contentsOf: fileURL, encoding: .utf8), !content.isEmpty else { continue }
            let entries = splitIntoEntries(content, fileLabel: label)
            totalEntryCount += entries.count
            for (fileLabel, entryText) in entries {
                let lower = entryText.lowercased()
                let matchedCount = keywords.filter { lower.contains($0) }.count
                if matchedCount > 0 {
                    let ts = extractTimestamp(from: entryText, fileLabel: fileLabel)
                    allEntries.append(ScoredEntry(
                        fileLabel: fileLabel,
                        text: entryText,
                        matchedCount: matchedCount,
                        totalKeywords: keywords.count,
                        timestamp: ts
                    ))
                }
            }
        }

        if allEntries.isEmpty {
            return FileToolResult(
                output: globalNote + "No matches found for keywords: \(keywords.joined(separator: ", ")) (scanned \(totalEntryCount) memory entries)",
                success: true
            )
        }

        // Compute combined score: 50% normalized confidence + 50% normalized recency.
        // Normalize confidence: matchedCount / totalKeywords → [0, 1]
        // Normalize recency: (ts - minTs) / (maxTs - minTs) → [0, 1], newer = higher
        let minTs = allEntries.map { $0.timestamp.timeIntervalSince1970 }.min() ?? 0
        let maxTs = allEntries.map { $0.timestamp.timeIntervalSince1970 }.max() ?? 1
        let tsRange = maxTs - minTs  // may be 0 if all entries have same timestamp

        let scored: [(entry: ScoredEntry, score: Double)] = allEntries.map { entry in
            let confScore = Double(entry.matchedCount) / Double(max(entry.totalKeywords, 1))
            let recencyScore: Double
            if tsRange > 0 {
                recencyScore = (entry.timestamp.timeIntervalSince1970 - minTs) / tsRange
            } else {
                recencyScore = 1.0  // all same age — treat equally
            }
            let combined = 0.5 * confScore + 0.5 * recencyScore
            return (entry, combined)
        }

        let sortedScored = scored.sorted { $0.score > $1.score }

        // Cap output to avoid flooding context. Two independent limits, whichever
        // is hit FIRST wins:
        //   1. Entry count — max 60 entries (legacy T-memory-get-limit).
        //   2. Byte size — max 30 KB of UTF-8 entry text. From a field
        //      report: a single memory_get returned ~70 KB, making the
        //      tool-result view stutter for seconds. We accumulate per entry
        //      and stop AFTER the entry that pushes the running total past the
        //      ceiling (so the triggering entry is shown whole, never sliced).
        let maxEntries = 60
        let maxBytes = 30 * 1024  // 30,720 bytes

        var rendered: [String] = []
        var shownBytes = 0
        var stoppedByBytes = false
        for item in sortedScored {
            if rendered.count >= maxEntries { break }
            let confidence = "\(item.entry.matchedCount)/\(item.entry.totalKeywords)"
            let scoreStr = String(format: "%.2f", item.score)
            let block = "[score: \(scoreStr) | confidence: \(confidence) | \(item.entry.fileLabel)]\n\(item.entry.text)"
            rendered.append(block)
            shownBytes += block.utf8.count
            // Append-then-break: include this entry in full, then stop.
            if shownBytes >= maxBytes {
                stoppedByBytes = true
                break
            }
        }

        let output = rendered.joined(separator: "\n\n---\n\n")

        let shownCount = rendered.count
        let truncatedNote: String
        if stoppedByBytes {
            let kb = String(format: "%.1f", Double(shownBytes) / 1024.0)
            truncatedNote = "\n\n[Truncated: showing \(shownCount) of \(sortedScored.count) matching entries, total \(kb) KB]"
        } else if sortedScored.count > shownCount {
            // Hit the entry-count cap before the byte cap.
            truncatedNote = "\n\n[Showing top \(shownCount) of \(sortedScored.count) matching entries]"
        } else {
            truncatedNote = ""
        }

        let summary = "Found \(sortedScored.count) matching entries (scanned \(totalEntryCount) total), sorted by combined score (50% confidence + 50% recency):"
        return FileToolResult(output: globalNote + summary + "\n\n" + output + truncatedNote, success: true)
    }

    /// Escape single quotes for shell arguments.
    private func shellEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "'", with: "'\\''")
    }


}
