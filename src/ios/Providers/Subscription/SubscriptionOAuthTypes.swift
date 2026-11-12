import CoreFoundation
import Foundation
import KWWKAI

/// Kept in the existing per-instance OAuth Keychain slot. The provider tag
/// prevents cross-provider decoding; no Keychain item identifier travels in exports.
struct SubscriptionTokenStorage: Codable, Equatable, Sendable {
    let provider: String
    var credentials: KWWKAI.OAuthCredentials
    var loginAccount: String?
    var accessToken: String { credentials.access }
    var refreshToken: String? { credentials.refresh.isEmpty ? nil : credentials.refresh }
    var isExpired: Bool { credentials.isExpired }
}

enum SubscriptionProviderError: LocalizedError {
    case unsupported(String)
    case notAuthenticated(String)
    case invalidResponse(String)
    case persistence(String, Int32?)
    case refreshRejected(String)
    case cancelled

    var errorDescription: String? {
        switch self {
        case .unsupported(let s), .notAuthenticated(let s), .invalidResponse(let s),
             .persistence(let s, _), .refreshRejected(let s): return s
        case .cancelled: return "登录已取消"
        }
    }
}

extension NSLock {
    @discardableResult
    func subscriptionWithLock<T>(_ body: () throws -> T) rethrows -> T {
        lock(); defer { unlock() }; return try body()
    }
}

extension KWWKAI.JSONValue {
    /// Lossless conversion via JSONSerialization/JSONDecoder; invalid input is
    /// an error, never silently turned into empty tool arguments.
    static func subscriptionValue(_ value: Any) throws -> KWWKAI.JSONValue {
        let data = try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed])
        return try JSONDecoder().decode(KWWKAI.JSONValue.self, from: data)
    }

    var subscriptionObject: Any {
        switch self {
        case .null: return NSNull()
        case .bool(let x): return x
        case .int(let x): return x
        case .double(let x): return x
        case .string(let x): return x
        case .array(let x): return x.map(\.subscriptionObject)
        case .object(let x): return x.mapValues(\.subscriptionObject)
        }
    }
}
