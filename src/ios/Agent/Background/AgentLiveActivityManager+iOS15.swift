//
//  AgentLiveActivityManager+iOS15.swift
//  Minis
//
//  iOS 15 stand-in for AgentLiveActivityManager.
//
//  WHY THIS FILE EXISTS
//  `AgentLiveActivityManager` talks to ActivityKit (iOS 16.1+) through ~20
//  private helpers spread over ~1000 lines, and it is referenced from 21 sites
//  across BackgroundKeepAliveManager, ChatStore, AIChatViewModel, VoiceProviderResolver,
//  the settings UI and MinisApp. Guarding the real file with
//  `#if canImport(ActivityKit)` would therefore force `#if canImport` into all 21
//  call sites, or force a stub with a *different* API and edits at every one of
//  them. Neither is worth it.
//
//  So instead the split is: the real manager is compiled only where ActivityKit
//  exists, and this file provides the SAME public surface everywhere else. Every
//  existing call site compiles unchanged and simply becomes a no-op on iOS 15.
//
//  This is not a functional regression on iOS 15 — Live Activities do not exist
//  below iOS 16.1 at all. What IS preserved here is everything the rest of the app
//  legitimately reads on iOS 15: the tool-icon / display-name tables, the soul
//  name, the audio state, and `isLiveActivitySupported == false` so the settings
//  UI hides the Live Activity toggle instead of offering a switch that cannot work.
//
//  Every member below mirrors the real one's signature exactly. If you change one
//  side, change the other — the compiler will not catch the drift for you, because
//  only one of the two is ever visible in a given build.
//

import Foundation

#if !canImport(ActivityKit)

/// iOS 15 no-op twin of the real `AgentLiveActivityManager`.
///
/// See the file comment above for why this exists and what is deliberately
/// preserved.
@MainActor
final class AgentLiveActivityManager {
    static let shared = AgentLiveActivityManager()

    private init() {}

    // MARK: - Availability

    /// Always false on iOS 15: ActivityKit is iOS 16.1+. The settings UI reads
    /// this to hide the Live Activity toggle entirely.
    static var isLiveActivitySupported: Bool { false }

    // MARK: - State

    /// No Live Activity exists to carry a start time on iOS 15.
    var taskStartTime: Date? { nil }

    // MARK: - Lifecycle (all no-ops on iOS 15)

    func cleanupStaleActivities(source: String = "?") {}
    func startActivity(sessions: [LiveSessionSnapshot]) {}
    func updateActivity(sessions: [LiveSessionSnapshot]) {}
    func endActivity() {}
    func markSessionCompleted(sessionId: String, lastMessage: String) {}
    func finishActivity(lastMessages: [String: String] = [:]) async {}
    func handleSessionDeleted(_ sessionId: String) {}
    func dismissFinishedActivityOnForeground() {}
    func audioStateChanged(source: String) {}

    // MARK: - Audio state

    /// Mirrors the real nested struct so `currentAudioState()` keeps the same
    /// return type on both OS versions.
    struct AudioState {
        var isPlaying: Bool
        var isLoaded: Bool
        var title: String
    }

    /// Reads the same TTS-backed source as the real implementation
    /// (`VoiceOutputState`), so the enhanced-background "keep alive because audio
    /// is loaded" decision behaves identically on iOS 15 — it just has no Live
    /// Activity to keep alive. Field-for-field identical to the real
    /// implementation, including `title: ""` and the `!speechPaused` mapping.
    static func currentAudioState() -> AudioState {
        let v = VoiceOutputState.shared
        return AudioState(isPlaying: !v.speechPaused, isLoaded: v.isReadingAloud, title: "")
    }

    static func isAudioActive() -> Bool {
        VoiceOutputState.shared.isReadingAloud
    }

    /// Kept as a real value: `VoiceProviderResolver` sends it as the change
    /// source so a toggle that originated in the Live Activity can be told apart
    /// from one that originated in the app.
    static let userAudioToggleSource = "liveActivityToggle"

    // MARK: - Presentation helpers
    //
    // These are plain data lookups with no ActivityKit dependency, so the REAL
    // behaviour is kept here — the settings screen and the agent-session
    // summaries read them on every OS version.

    static func currentSoulName() -> String {
        let name = SoulStore.cachedMetadata.name.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? "Minis" : name
    }

    static func latestToolIcon() -> String {
        guard let toolName = SessionActivityTracker.shared.latestToolName() else { return "" }
        return sfSymbol(forTool: toolName)
    }

    static func sfSymbol(forTool toolName: String) -> String {
        switch toolName {
        case "browser", "browser_use":          return "globe"
        case "shell", "shell_execute":          return "terminal"
        case "file_read":                       return "doc.text"
        case "file_write":                      return "doc.text.fill"
        case "file_edit":                       return "pencil.line"
        case "read_image":                      return "photo"
        case "memory":                          return "brain.head.profile"
        case "text":                            return "bubble.left"
        case "thinking":                        return "lightbulb.max"
        case "code_interpret":                  return "chevron.left.forwardslash.chevron.right"
        default:                                return "ellipsis.circle"
        }
    }

    static func displayName(forTool toolName: String) -> String {
        switch toolName {
        case "browser", "browser_use":          return "Browser"
        case "shell", "shell_execute":          return "Shell"
        case "file_read":                       return "Read File"
        case "file_write":                      return "Write File"
        case "file_edit":                       return "Edit File"
        case "read_image":                      return "Read Image"
        case "memory":                          return "Memory"
        case "text":                            return "Responding"
        case "thinking":                        return "Thinking"
        case "code_interpret":                  return "Code"
        default:                                return "Working"
        }
    }
}

#endif // !canImport(ActivityKit)
