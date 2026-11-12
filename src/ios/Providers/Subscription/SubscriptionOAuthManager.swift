import Foundation
import KWWKAI
import SafariServices
import UIKit

/// App-owned auth state: credentials never go through Shell or plaintext files.
@MainActor
final class SubscriptionOAuthManager {
    static let shared = SubscriptionOAuthManager()
    private init() {}
    private struct Login {
        let id: UUID
        let cancellation: CancellationHandle
        let task: Task<Void, Error>
    }
    private struct Refresh { let id: UUID; let epoch: UUID; let task: Task<OAuthCredentials, Error> }
    private var logins: [String: Login] = [:]
    private var refreshes: [String: Refresh] = [:]
    private var epochs: [String: UUID] = [:]
    private var presentations: [String: SubscriptionSafariPresentation] = [:]
    private var listeners: [String: TraeLoopback] = [:]
    private let client = SubscriptionHTTPClient(allowedHosts: ["copilot.tencent.com", "api.trae.cn"], timeout: 30, maxResponseBytes: 1_048_576)

    func isAuthenticated(instanceId: String, type: ProviderType) -> Bool {
        guard !ProviderKeychainHelper.oauthNeedsReauth(instanceId: instanceId),
              let s = load(instanceId, type) else { return false }
        return !s.accessToken.isEmpty
    }
    func maskedToken(instanceId: String, type: ProviderType) -> String? {
        guard let t = load(instanceId, type)?.accessToken, t.count > 8 else { return nil }
        return "\(t.prefix(4))…\(t.suffix(4))"
    }
    func accountLabel(instanceId: String, type: ProviderType) -> String? {
        guard let s = load(instanceId, type) else { return nil }
        return s.loginAccount ?? Self.label(s.credentials)
    }
    func cancelLogin(instanceId: String) {
        let login = logins.removeValue(forKey: instanceId)
        login?.cancellation.cancel()
        login?.task.cancel()
        listeners.removeValue(forKey: instanceId)?.stop()
        presentations.removeValue(forKey: instanceId)?.cancel()
    }
    func logout(instanceId: String) {
        epochs[instanceId] = UUID() // fence an already-delivered refresh callback
        cancelLogin(instanceId: instanceId)
        refreshes.removeValue(forKey: instanceId)?.task.cancel()
        ProviderKeychainHelper.deleteOAuthToken(instanceId: instanceId)
    }

    /// A credential written from outside (a restored backup) becomes this
    /// instance's account. It must win over a sign-in that is still waiting in
    /// the browser: bump the epoch so a late login result is fenced out, and
    /// stop the sheet/listener so nothing keeps waiting on it.
    func adoptExternalCredential(instanceId: String) {
        epochs[instanceId] = UUID()
        cancelLogin(instanceId: instanceId)
        refreshes.removeValue(forKey: instanceId)?.task.cancel()
    }

    func login(instanceId: String, type: ProviderType) async throws {
        guard type == .workBuddy || type == .traeCN else {
            throw SubscriptionProviderError.unsupported("不支持的登录方式")
        }
        try Task.checkCancellation()
        cancelLogin(instanceId: instanceId)
        let epoch = UUID()
        epochs[instanceId] = epoch
        refreshes.removeValue(forKey: instanceId)?.task.cancel()
        let id = UUID()
        let cancellation = CancellationHandle()
        let task = Task { @MainActor [self] in
            try Task.checkCancellation()
            try cancellation.throwIfCancelled()
            guard logins[instanceId]?.id == id, epochs[instanceId] == epoch else { throw CancellationError() }
            let browser = SubscriptionBrowserPresenter(instanceId: instanceId, loginID: id,
                                                        type: type, cancellation: cancellation, manager: self)
            defer {
                if logins[instanceId]?.id == id {
                    listeners.removeValue(forKey: instanceId)?.stop()
                    presentations.removeValue(forKey: instanceId)?.cancel()
                }
            }
            let callbacks = OAuthLogin.Callbacks(onProgress: { _ in }, browser: browser)
            let c: OAuthCredentials
            if type == .workBuddy {
                c = try await OAuthLogin.loginWorkBuddy(site: .china, callbacks: callbacks, client: client)
            } else {
                let listener = TraeLoopback()
                listeners[instanceId] = listener
                defer {
                    listener.stop()
                    if listeners[instanceId] === listener { listeners[instanceId] = nil }
                }
                let cb = OAuthLogin.Callbacks(onProgress: { _ in }, browser: browser,
                    loopback: { _, _, _ in listener })
                c = try await TraeOAuth.login(profile: .china, callbacks: cb, client: client)
            }
            try Task.checkCancellation()
            try cancellation.throwIfCancelled()
            guard logins[instanceId]?.id == id, epochs[instanceId] == epoch else { throw CancellationError() }
            guard !c.access.isEmpty else { throw SubscriptionProviderError.invalidResponse("登录未返回有效凭据，请重试") }
            try ProviderKeychainHelper.saveSubscriptionOAuthTokenChecked(
                SubscriptionTokenStorage(provider: type.rawValue, credentials: c, loginAccount: Self.label(c)),
                instanceId: instanceId)
        }
        logins[instanceId] = Login(id: id, cancellation: cancellation, task: task)
        defer { if logins[instanceId]?.id == id { logins[instanceId] = nil } }
        try await withTaskCancellationHandler {
            try await task.value
            try Task.checkCancellation()
        } onCancel: {
            cancellation.cancel() // Synchronous fence, before the MainActor cleanup can run.
            task.cancel()
            Task { @MainActor [weak self] in
                if self?.logins[instanceId]?.id == id { self?.cancelLogin(instanceId: instanceId) }
            }
        }
    }

    func validAccessToken(instanceId: String, type: ProviderType) async throws -> String {
        try await validCredentials(instanceId: instanceId, type: type).access
    }
    func validCredentials(instanceId: String, type: ProviderType, forceRefresh: Bool = false,
                          rejectedAccess: String? = nil) async throws -> OAuthCredentials {
        try Task.checkCancellation()
        guard type == .workBuddy || type == .traeCN, let initial = load(instanceId, type) else {
            throw LLMError.invalidAPIKey(detail: "该账号尚未登录")
        }
        guard !ProviderKeychainHelper.oauthNeedsReauth(instanceId: instanceId) else {
            throw LLMError.invalidAPIKey(detail: "登录已失效，请重新登录")
        }
        if let rejectedAccess, initial.accessToken != rejectedAccess { return initial.credentials }
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        let needs = initial.credentials.expires != .max && initial.credentials.expires <= now + 300_000
        guard forceRefresh || needs else { return initial.credentials }
        // Do not start a fresh old-account renewal after re-login has fenced it.
        guard logins[instanceId] == nil else { throw CancellationError() }
        if let running = refreshes[instanceId] {
            let credentials = try await running.task.value
            try Task.checkCancellation()
            guard epochs[instanceId] == running.epoch else { throw CancellationError() }
            return credentials
        }
        guard !initial.credentials.refresh.isEmpty else {
            ProviderKeychainHelper.markOAuthNeedsReauth(instanceId: instanceId)
            throw LLMError.invalidAPIKey(detail: "登录已过期，请重新登录")
        }
        let epoch = epochs[instanceId] ?? UUID()
        epochs[instanceId] = epoch
        let id = UUID()
        let task = Task<OAuthCredentials, Error> { @MainActor [self] in
            try Task.checkCancellation()
            guard epochs[instanceId] == epoch else { throw CancellationError() }
            let next: OAuthCredentials
            do {
                if type == .workBuddy {
                    next = try await WorkBuddyOAuthProvider(site: .china).refresh(initial.credentials, using: client)
                } else {
                    next = try await SubscriptionTraeRefresh.refresh(initial.credentials, client: client)
                }
            } catch {
                try Task.checkCancellation()
                if error is CancellationError { throw error }
                guard epochs[instanceId] == epoch, let current = load(instanceId, type) else { throw CancellationError() }
                if current != initial { return current.credentials }
                if let e = error as? OAuthRefreshError, e.kind == .rejected {
                    ProviderKeychainHelper.markOAuthNeedsReauth(instanceId: instanceId)
                    throw LLMError.invalidAPIKey(detail: "登录已失效，请重新登录")
                }
                // A network/5xx failure never deletes or parks still-valid credentials.
                if !forceRefresh && !current.isExpired { return current.credentials }
                throw SubscriptionProviderError.invalidResponse("账号续期暂不可用，请稍后重试；原登录凭据未被移除")
            }
            try Task.checkCancellation()
            guard epochs[instanceId] == epoch, let current = load(instanceId, type) else { throw CancellationError() }
            // Another device/re-login owns any blob that moved since this request.
            if current != initial { return current.credentials }
            guard !next.access.isEmpty else { throw SubscriptionProviderError.invalidResponse("账号续期未返回有效凭据") }
            // Keep persistence outside the network catch: Keychain failures must reach the caller.
            try ProviderKeychainHelper.saveSubscriptionOAuthTokenChecked(
                SubscriptionTokenStorage(provider: type.rawValue, credentials: next, loginAccount: initial.loginAccount),
                instanceId: instanceId)
            return next
        }
        refreshes[instanceId] = Refresh(id: id, epoch: epoch, task: task)
        defer { if refreshes[instanceId]?.id == id { refreshes[instanceId] = nil } }
        let credentials = try await task.value
        try Task.checkCancellation()
        guard epochs[instanceId] == epoch else { throw CancellationError() }
        return credentials
    }

    private func load(_ id: String, _ type: ProviderType) -> SubscriptionTokenStorage? {
        guard let s = ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: SubscriptionTokenStorage.self),
              s.provider == type.rawValue else { return nil }
        return s
    }
    private static func label(_ c: OAuthCredentials) -> String? {
        for k in ["accountName", "nickname", "uid", "userId"] {
            if case .string(let s)? = c.extras[k], !s.isEmpty { return s }
        }
        return nil
    }

    /// The sign-in page must be the domestic vendor's own site, and it is not
    /// always the API host: WorkBuddy answers with pages on
    /// www.workbuddy.cn (it was CodeBuddy before the rename, so
    /// codebuddy.cn still appears), and Trae opens www.trae.cn. Whole
    /// registrable domains are allowed rather than single hostnames — pinning
    /// one host is what blocked a real sign-in.
    private static func isDomesticLoginHost(_ host: String, type: ProviderType) -> Bool {
        let allowed: [String] = type == .workBuddy
            ? ["workbuddy.cn", "workbuddy.ai", "codebuddy.cn", "tencent.com"]
            : ["trae.cn"]
        return allowed.contains { host == $0 || host.hasSuffix("." + $0) }
    }

    fileprivate func present<T: Sendable>(instanceId: String, loginID: UUID, type: ProviderType,
        cancellation: CancellationHandle, url: URL,
        work: @escaping @Sendable () async throws -> T) async throws -> T {
        try Task.checkCancellation()
        try cancellation.throwIfCancelled()
        guard logins[instanceId]?.id == loginID else { throw CancellationError() }
        guard url.scheme == "https", let host = url.host?.lowercased(),
              url.user == nil, url.password == nil, url.port == nil || url.port == 443,
              Self.isDomesticLoginHost(host, type: type) else {
            // Name the host, never the whole URL: it carries a login state.
            throw SubscriptionProviderError.invalidResponse(
                "登录页域名 \(url.host ?? "（无）") 不在允许范围，已阻止打开")
        }
        let p = SubscriptionSafariPresentation(cancellation: cancellation)
        presentations[instanceId] = p
        defer { if presentations[instanceId] === p { presentations[instanceId] = nil } }
        return try await p.run(url, work: work)
    }
}

private struct SubscriptionBrowserPresenter: OAuthBrowserPresenter {
    let instanceId: String
    let loginID: UUID
    let type: ProviderType
    let cancellation: CancellationHandle
    let manager: SubscriptionOAuthManager
    func run<T: Sendable>(_ url: URL,
        while work: @escaping @Sendable () async throws -> T) async throws -> T {
        try await manager.present(instanceId: instanceId, loginID: loginID, type: type,
                                  cancellation: cancellation, url: url, work: work)
    }
}

@MainActor
private final class SubscriptionLoginGate<T: Sendable> {
    private var continuation: CheckedContinuation<T, Error>?
    private var result: Result<T, Error>?
    func wait(_ c: CheckedContinuation<T, Error>) {
        if let result { c.resume(with: result) } else { continuation = c }
    }
    func finish(_ value: Result<T, Error>) {
        guard result == nil else { return }
        result = value
        let c = continuation; continuation = nil
        c?.resume(with: value)
    }
}

@MainActor
private final class SubscriptionSafariPresentation: NSObject, SFSafariViewControllerDelegate {
    private var controller: SFSafariViewController?
    private var cancelWork: (() -> Void)?
    private var cancelled = false
    private var finished = false
    private let cancellation: CancellationHandle

    init(cancellation: CancellationHandle) {
        self.cancellation = cancellation
        super.init()
    }

    /// Finishing (or failing) once is final: a later dismissal must not turn a
    /// delivered result into a second, contradictory outcome.
    func cancel() {
        guard !finished else { return }
        finished = true
        cancelled = true
        cancellation.cancel()
        cancelWork?()
        controller?.dismiss(animated: true)
    }

    /// The user tapping Done is leaving the sign-in. Without this the flow
    /// stayed "waiting" until the five-minute timeout with the sheet gone.
    func safariViewControllerDidFinish(_ controller: SFSafariViewController) {
        cancel()
    }

    func run<T: Sendable>(_ url: URL,
        work: @escaping @Sendable () async throws -> T) async throws -> T {
        let gate = SubscriptionLoginGate<T>()
        var producer: Task<Void, Never>?
        var timeout: Task<Void, Never>?
        defer {
            producer?.cancel(); timeout?.cancel(); cancelWork = nil
            controller?.dismiss(animated: true); controller = nil
        }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<T, Error>) in
                gate.wait(c)
                guard !cancelled, !cancellation.isCancelled, !Task.isCancelled else {
                    gate.finish(.failure(CancellationError())); return
                }
                guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene })
                    .first(where: { $0.activationState == .foregroundActive }),
                      let root = scene.windows.first(where: { $0.isKeyWindow })?.rootViewController else {
                    gate.finish(.failure(SubscriptionProviderError.invalidResponse("请保持 App 在前台后重试登录"))); return
                }
                var top = root
                while let next = top.presentedViewController { top = next }
                let vc = SFSafariViewController(url: url)
                vc.delegate = self
                controller = vc
                top.present(vc, animated: true)
                producer = Task { @MainActor in
                    do {
                        let value = try await work()
                        try Task.checkCancellation()
                        gate.finish(.success(value))
                    } catch { gate.finish(.failure(error)) }
                }
                cancelWork = { producer?.cancel(); gate.finish(.failure(CancellationError())) }
                timeout = Task { @MainActor in
                    do { try await Task.sleep(nanoseconds: 300_000_000_000) }
                    catch { return }
                    cancellation.cancel()
                    producer?.cancel()
                    gate.finish(.failure(OAuthLoginError.timedOut))
                }            }
        } onCancel: { [cancellation] in
            cancellation.cancel()
            Task { @MainActor [weak self] in self?.cancel() }
        }
    }
}

private enum SubscriptionTraeRefresh {
    static func refresh(_ old: OAuthCredentials, client: any HTTPClient) async throws -> OAuthCredentials {
        let user = TraeCredential(old)
        // Domestic credentials can renew only at the fixed domestic gate.
        guard user.oauthHost == nil || user.oauthHost == "https://api.trae.cn" else {
            throw SubscriptionProviderError.invalidResponse("账号授权站点不匹配，请使用国内 Trae 重新登录")
        }
        let result = try await TraeWire.exchangeToken(site: .china, refreshToken: old.refresh,
            userID: user.userID, gate: "https://api.trae.cn", client: client)
        var new = old
        new.access = result.access
        new.refresh = result.refresh.isEmpty ? old.refresh : result.refresh
        new.expires = result.expires
        return new
    }
}
