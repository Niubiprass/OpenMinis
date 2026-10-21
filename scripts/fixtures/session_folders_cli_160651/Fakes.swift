// Dependency fakes only. No copy of bridge request/selector/patch/send logic.
import Foundation

struct FixtureError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}
struct ChatFolder: Equatable {
    var id: String
    var name: String
    var desc: String? = nil
    var isPinned = false
}
struct ChatSession: Equatable {
    var id: String
    var title: String? = nil
    var folderId: String? = nil
    var parentSessionId: String? = nil
    var isChild: Bool { parentSessionId != nil }
}
struct FolderRuntimeContext {
    var folderId: String?
    var configuration: ChatFolderConfiguration
}
extension Notification.Name {
    static let sessionDidUpdate = Notification.Name("fixture.sessionDidUpdate")
}

// Shadow UserDefaults so actual icon verification uses a hermetic dictionary,
// even on macOS; never write the test executable's preferences domain.
final class UserDefaults {
    static let standard = UserDefaults()
    var icons: [String: String] = [:]
    func dictionary(forKey key: String) -> [String: Any]? {
        key == "folderCustomIcons" ? icons : nil
    }
}
struct UIImage {
    let path: String
    init?(contentsOfFile path: String) {
        guard path == "/fixture/valid.png" || path == "/fixture/unencodable.png" else { return nil }
        self.path = path
    }
}
enum SidebarIconImage {
    static func encode(_ image: UIImage) -> Result<String, FixtureError> {
        image.path == "/fixture/unencodable.png" ? .failure(FixtureError("encode")) : .success("fixture:data:png")
    }
}
@MainActor final class FolderIconStore {
    static let shared = FolderIconStore()
    var icons: [String: String] = [:]
    var failMemory = false
    var failPersistence = false
    var writes = 0
    func setIcon(_ uri: String?, for id: String) {
        writes += 1
        if !failMemory { icons[id] = uri }
        if !failPersistence { UserDefaults.standard.icons[id] = uri }
    }
    func icon(for id: String) -> String? { icons[id] }
}

@MainActor final class ChatStore {
    static let shared = ChatStore()
    var folders: [String: ChatFolder] = [:]
    var rows: [String: ChatSession] = [:]
    var configs: [String: ChatFolderConfiguration] = [:]
    var faults: Set<String> = []
    var events: [String] = []
    var writes: [String] = []
    var expectedConfig: ChatFolderConfiguration?
    var casConcurrent: ChatFolderConfiguration?
    var serial = 0
    func listFolders() -> [ChatFolder] { folders.values.sorted { $0.id < $1.id } }
    func getFolder(_ id: String) -> ChatFolder? { folders[id] }
    func getSession(_ id: String) -> ChatSession? { rows[id] }
    func sessionExists(id: String) -> Bool { rows[id] != nil }
    func sessionIdsInFolder(_ id: String) -> [String] {
        rows.values.filter { $0.folderId == id }.map(\.id).sorted()
    }
    func sessionIdsWithDescendants(_ ids: [String]) -> [String] {
        var result = Set(ids)
        while true {
            let old = result
            for row in rows.values where row.parentSessionId.map({ result.contains($0) }) == true {
                result.insert(row.id)
            }
            if old == result { return result.sorted() }
        }
    }
    func getFolderConfiguration(_ id: String) throws -> ChatFolderConfiguration {
        events.append("config:" + id)
        if faults.contains("config:" + id) { throw FixtureError("config read failed") }
        guard folders[id] != nil else { throw FixtureError("missing folder") }
        return configs[id] ?? .default
    }
    func resolveFolderRuntimeContext(for id: String) throws -> FolderRuntimeContext {
        events.append("resolve:" + id)
        if faults.contains("resolve:" + id) { throw FixtureError("context failed") }
        var cursor = id
        var seen = Set<String>()
        for _ in 0..<16 {
            guard seen.insert(cursor).inserted, let row = rows[cursor] else { throw FixtureError("bad session") }
            if let parent = row.parentSessionId { cursor = parent; continue }
            return FolderRuntimeContext(folderId: row.folderId,
                configuration: try row.folderId.map { try getFolderConfiguration($0) } ?? .default)
        }
        throw FixtureError("bad hierarchy")
    }
    func createFolder(name: String, desc: String?) -> ChatFolder {
        writes.append("create")
        serial += 1
        let value = ChatFolder(id: "created-\(serial)", name: name, desc: desc)
        if !faults.contains("create") { folders[value.id] = value }
        return value
    }
    func renameFolder(_ id: String, name: String, desc: String?) {
        writes.append("rename")
        guard !faults.contains("rename"), var row = folders[id] else { return }
        row.name = name
        if let desc {
            let text = String(desc.trimmingCharacters(in: .whitespacesAndNewlines).prefix(100))
            row.desc = text.isEmpty ? nil : text
        }
        folders[id] = row
    }
    func toggleFolderPin(_ id: String) -> Bool {
        writes.append("pin")
        if !faults.contains("pin") { folders[id]?.isPinned.toggle() }
        return folders[id]?.isPinned ?? false
    }
    func setFolder(_ target: String?, forSessions ids: [String]) {
        writes.append("move")
        events.append("move:" + ids.joined(separator: ","))
        for (index, id) in ids.enumerated() {
            if faults.contains("move") { continue }
            if faults.contains("partialMove") && index > 0 { continue }
            rows[id]?.folderId = target
        }
    }
    func dissolveFolder(_ id: String) -> Bool {
        writes.append("dissolve")
        if faults.contains("dissolve") { return false }
        folders[id] = nil
        configs[id] = nil
        return true
    }
    func saveFolderConfiguration(_ id: String, configuration: ChatFolderConfiguration,
                                 expected: ChatFolderConfiguration) throws -> ChatFolderConfiguration {
        writes.append("configure")
        expectedConfig = expected
        if let concurrent = casConcurrent { configs[id] = concurrent }
        guard configs[id] ?? .default == expected else { throw FixtureError("CAS conflict") }
        if faults.contains("configure") { throw FixtureError("storage failed") }
        if !faults.contains("configureReadback") { configs[id] = configuration }
        return configuration
    }
}

struct Model { var displayName: String }
struct ModelEntry { var model: Model }
enum BindingSource: Equatable {
    case group(String, String)
    case directEntry(modelEntryId: String, fallback: String? = nil)
}
struct SessionModelBinding: Equatable {
    var sessionId: String
    var primarySource: BindingSource
    var subModelSource: BindingSource? = nil
}
@MainActor final class ProviderConfigStore {
    static let shared = ProviderConfigStore()
    var entries = ["model-A": ModelEntry(model: Model(displayName: "Model A")),
                   "model-B": ModelEntry(model: Model(displayName: "Model B"))]
    var bindings: [String: SessionModelBinding] = [:]
    var inference: [String: String] = [:]
    var writes: [String] = []
    func entry(for id: String) -> ModelEntry? { entries[id] }
    func binding(for id: String) -> SessionModelBinding? { bindings[id] }
    func setBinding(_ value: SessionModelBinding, for id: String) { bindings[id] = value; writes.append("binding:" + id) }
    func inferenceConfig(for id: String) -> String? { inference[id] }
    func setInferenceConfig(_ value: String, for id: String) { inference[id] = value; writes.append("inference:" + id) }
}
final class MinisFsRouter {
    static let shared = MinisFsRouter()
    let activeSessionId = "B" // Deliberately differs from the guest caller A.
    func sid(for token: UInt64) -> String? { token == 101 ? "A" : token == 202 ? "B" : nil }
}
struct AppLogger {
    init(category: String) {}
    func info(_ text: String) {}
}
enum PromptOrigin { case cli }
enum PromptOutcome: Equatable { case sent, queued, rejected(String) }
@MainActor final class AIChatViewModel {
    var sessionId: String?
    var sessionSource = ""
    var initialFolderId: String?
    var folderRuntimeContext: FolderRuntimeContext?
    var isProcessing = false
    var selectedModel = Model(displayName: "Default")
    var promptQueue: [String] = []
    var attachments: [String] = []
    var outcome: PromptOutcome = .sent
    init(id: String? = nil) { sessionId = id }
    func loadSession() async { ChatStore.shared.events.append("load:" + (sessionId ?? "nil")) }
    func ensureSessionReturningId() async -> String? {
        let store = ChatStore.shared
        store.serial += 1
        let id = "draft-\(store.serial)"
        if store.faults.contains("sessionUnavailable") { return nil }
        sessionId = id
        if !store.faults.contains("persistMissing") {
            let fid = store.faults.contains("persistFolder") ? nil : initialFolderId
            store.rows[id] = ChatSession(id: id, title: "new", folderId: fid)
            store.events.append("persist:" + (fid ?? "none"))
        }
        return id
    }
    func refreshFolderRuntimeContext() async throws {
        let store = ChatStore.shared
        if store.faults.contains("refresh") { throw FixtureError("refresh failed") }
        folderRuntimeContext = try store.resolveFolderRuntimeContext(for: sessionId!)
        if store.faults.contains("staleContext") { folderRuntimeContext?.folderId = "FB" }
        store.events.append("refresh:" + (folderRuntimeContext?.folderId ?? "none"))
    }
    func addDataAttachment(data: Data, fileName: String) { attachments.append(fileName) }
    func submitProgrammaticPrompt(_ prompt: String, origin: PromptOrigin, silent: Bool) -> PromptOutcome {
        let store = ChatStore.shared
        store.events.append("send:" + (sessionId ?? "nil"))
        ViewModelCache.shared.submissions.append((sessionId ?? "nil", prompt))
        return outcome
    }
}
@MainActor final class ViewModelCache {
    static let shared = ViewModelCache()
    var cache: [String: AIChatViewModel] = [:]
    var drafts: [AIChatViewModel] = []
    var submissions: [(String, String)] = []
    var nextOutcome: PromptOutcome = .sent
    func get(for id: String) -> AIChatViewModel? { cache[id] }
    func getOrCreate(for id: String) -> (AIChatViewModel, Bool) {
        if let value = cache[id] { return (value, false) }
        let value = AIChatViewModel(id: id)
        value.outcome = nextOutcome
        cache[id] = value
        return (value, true)
    }
    func createDraft() -> AIChatViewModel {
        let value = AIChatViewModel()
        value.outcome = nextOutcome
        drafts.append(value)
        ChatStore.shared.events.append("draft")
        return value
    }
}
