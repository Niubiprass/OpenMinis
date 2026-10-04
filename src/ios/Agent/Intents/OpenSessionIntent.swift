
// [iOS15-compat] `import AppIntents` is itself an iOS 16+ declaration, and an
// `import` cannot be guarded by @available — it is a compile-time error at a
// 15.0 deployment target. `canImport` is evaluated at compile time, so on
// iOS 15 this whole file compiles to nothing and the App Shortcuts / Siri
// surface is simply absent. That is a system-framework limit, not a
// regression: AppIntents does not exist below iOS 16.
#if canImport(AppIntents)
import AppIntents
import Foundation

/// Opens a specific chat session in the Minis app.
struct OpenSessionIntent: AppIntent {
    static var title: LocalizedStringResource = "Open Session"
    static var description = IntentDescription("Opens a Minis chat session in the app.")
    static var openAppWhenRun = true

    @Parameter(title: "Session")
    var session: SessionEntity

    @MainActor
    func perform() async throws -> some IntentResult {
        NotificationCenter.default.post(
            name: .openSessionFromIntent,
            object: nil,
            userInfo: ["sessionId": session.id]
        )
        return .result()
    }
}

extension Notification.Name {
    static let openSessionFromIntent = Notification.Name("openSessionFromIntent")
}

#endif // canImport(AppIntents)
