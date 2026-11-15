// Test-only dependencies for the extracted production display cache.
// No Keychain, files, server or real credential is used.
import Foundation

enum ProviderType: String, Hashable, Sendable {
    case anthropic, gemini, openAI, openAIResponses, antigravity, openRouter
    case xAI, kimiCode, githubCopilot, workBuddy, traeCN, unsupported
    var isDomesticSubscription: Bool { self == .workBuddy || self == .traeCN }
    var displayName: String { rawValue }
}
enum ProviderCredential: String, Hashable, Sendable { case apiKey, oauth }
struct TestToken: Codable, Sendable { let accessToken: String }
typealias ClaudeTokenStorage = TestToken
typealias GeminiTokenStorage = TestToken
typealias CodexTokenStorage = TestToken
typealias AntigravityTokenStorage = TestToken
typealias XAITokenStorage = TestToken
typealias KimiTokenStorage = TestToken
struct CopilotTokenStorage: Codable, Sendable { let githubToken: String }
struct SubscriptionTokenStorage: Codable, Sendable {
    let provider: String
    let accessToken: String
}
func AppLocalized(_ text: String) -> String { text }

enum ProviderKeychainHelper {
    // Only test-owned synthetic values. Lock mirrors the thread-safe Keychain
    // API and keeps concurrent test probes from sharing mutable unsafely.
    private static let lock = NSLock()
    private static var keys: [String: String] = [:]
    private static var strings: [String: String] = [:]
    private static var tokens: [String: Data] = [:]
    private static var reauth: Set<String> = []
    static func reset() { lock.lock(); defer { lock.unlock() }; keys = [:]; strings = [:]; tokens = [:]; reauth = [] }
    static func setKey(_ key: String?, id: String) { lock.lock(); defer { lock.unlock() }; keys[id] = key }
    static func setManual(_ value: String?, id: String) { lock.lock(); defer { lock.unlock() }; strings[id] = value }
    static func setToken<T: Encodable>(_ token: T, id: String) { lock.lock(); defer { lock.unlock() }; tokens[id] = try! JSONEncoder().encode(token) }
    static func setReauth(_ id: String) { lock.lock(); defer { lock.unlock() }; reauth.insert(id) }
    static func loadAPIKey(instanceId: String) -> String? { lock.lock(); defer { lock.unlock() }; return keys[instanceId] }
    static func loadOAuthString(instanceId: String, account: String) -> String? { lock.lock(); defer { lock.unlock() }; return strings[instanceId] }
    static func loadOAuthToken<T: Codable>(instanceId: String, as type: T.Type) -> T? {
        lock.lock(); defer { lock.unlock() }
        guard let data = tokens[instanceId] else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    static func oauthNeedsReauth(instanceId: String) -> Bool { lock.lock(); defer { lock.unlock() }; return reauth.contains(instanceId) }
}
