
// [iOS15-compat] `import AppIntents` is itself an iOS 16+ declaration, and an
// `import` cannot be guarded by @available — it is a compile-time error at a
// 15.0 deployment target. `canImport` is evaluated at compile time, so on
// iOS 15 this whole file compiles to nothing and the App Shortcuts / Siri
// surface is simply absent. That is a system-framework limit, not a
// regression: AppIntents does not exist below iOS 16.
#if canImport(AppIntents)
import AppIntents
import Foundation

/// Structured result returned by SendPromptIntent, usable in Shortcuts automation chains.
struct SendPromptResult: AppEntity {
    static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Prompt Result")
    static var defaultQuery = SendPromptResultQuery()

    var id: String  // session ID

    @Property(title: "Session ID")
    var sessionId: String

    @Property(title: "Model")
    var modelName: String

    @Property(title: "Status")
    var status: String

    @Property(title: "Is New Session")
    var isNewSession: Bool

    @Property(title: "Prompt")
    var prompt: String

    @Property(title: "Response")
    var responseText: String

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(sessionId)",
            subtitle: "\(modelName) · \(status)"
        )
    }

    init(sessionId: String, modelName: String, status: String, isNewSession: Bool, prompt: String = "", responseText: String = "") {
        self.id = sessionId
        self.sessionId = sessionId
        self.modelName = modelName
        self.status = status
        self.isNewSession = isNewSession
        self.prompt = prompt
        self.responseText = responseText
    }
}

/// Minimal query — result entities are ephemeral, not persisted.
struct SendPromptResultQuery: EntityQuery {
    func entities(for identifiers: [String]) async throws -> [SendPromptResult] {
        []
    }
}

#endif // canImport(AppIntents)
