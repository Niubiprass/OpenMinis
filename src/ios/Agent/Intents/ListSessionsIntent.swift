
// [iOS15-compat] `import AppIntents` is itself an iOS 16+ declaration, and an
// `import` cannot be guarded by @available — it is a compile-time error at a
// 15.0 deployment target. `canImport` is evaluated at compile time, so on
// iOS 15 this whole file compiles to nothing and the App Shortcuts / Siri
// surface is simply absent. That is a system-framework limit, not a
// regression: AppIntents does not exist below iOS 16.
#if canImport(AppIntents)
import AppIntents
import Foundation

/// Lists all chat sessions — useful for automation scripts that need a session ID.
struct ListSessionsIntent: AppIntent {
    static var title: LocalizedStringResource = "List Sessions"
    static var description = IntentDescription("Lists all Minis chat sessions with their titles and IDs.")
    static var openAppWhenRun = false

    func perform() async throws -> some IntentResult & ReturnsValue<String> {
        let sessions = await ChatStore.shared.listSessions().filter { !$0.isChild }

        if sessions.isEmpty {
            return .result(value: "No sessions found.")
        }

        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated

        let lines = sessions.map { session -> String in
            let title = session.title ?? "Untitled"
            let age = formatter.localizedString(for: session.updatedAt, relativeTo: Date())
            return "\(title) (\(age)) — \(session.id)"
        }

        return .result(value: lines.joined(separator: "\n"))
    }
}

#endif // canImport(AppIntents)
