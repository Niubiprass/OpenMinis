// Adapted from user-provided Apelin-providers archive; see SOURCE-PROVENANCE.md.
import CryptoKit
import Foundation
import KWWKAI
import Network

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// Trae's browser sign-in, for both builds: the two-step loopback flow its
/// desktop clients run, so a Trae account is signed in to the way Qoder's and
/// WorkBuddy's are rather than by pasting a token out of the Trae app.
///
/// The two builds share the shape of the flow and almost nothing else. The
/// China build opens a fixed `www.trae.cn`, exchanges with `api.trae.cn`, and
/// reports a Windows device. The international build asks
/// `GetLoginGuidance` where its sign-in page is, exchanges against the
/// account gate that serves its region, and reports `unknown` for the machine
/// it is not allowed to describe. `Profile` holds each build's values, so the
/// flow itself is written once.
///
/// Every constant is a client's own value, taken from captures of its login
/// and from its `main.js` (`buildLoginUrl`, `exchangeTokenByAuthCode`,
/// `_buildDeviceInfo`), as recorded by `dsh-account-hub`'s
/// `src/trae-cn-oauth.ts` and `src/trae-cn-product.ts` for the China build,
/// and by cockpit-tools' `trae-intl-oauth.rs` and 10router's
/// `trae-intl-oauth.js` for the international one. None is a secret: they are
/// public client ids, the builds the page is asked for, and the paths of the
/// two `ExchangeToken` endpoints.
///
/// The flow, in the order it happens:
/// 1. generate PKCE (S256), a machine id, a device id, a login trace id and
///    a fresh EC P-256 public key;
/// 2. ask `GetLoginGuidance` for the sign-in host (international only);
/// 3. bind `127.0.0.1:<port>/authorize` and open `<host>/authorization`;
/// 4. the page calls back with `authCodeInfo` (a JSON string holding
///    `AuthCode`), `userInfo` and, on the international build, `loginHost`;
/// 5. `POST <gate>/trae/api/v3/oauth/ExchangeToken` with
///    `{ClientID, AuthCode, CodeVerifier, DeviceInfo, IDEVersion}` answers
///    the JWT, its refresh token and, on the China build, `BoundDeviceID`.
///
/// Renewal is a different endpoint (`cloudide/api/v3/trae/oauth/ExchangeToken`,
/// with the refresh token), which `TraeWire.exchangeToken` posts to the gate
/// this sign-in recorded.
///
/// The spellings are load-bearing and are why this file repeats them:
/// `client_id` is snake_case on the page and `ClientID` PascalCase in the
/// exchange body; a page that does not find `client_id` shows "authenticating"
/// for ever, with no error and no callback. `auth_type=local`,
/// `login_channel=native_ide` and `login_version=1` each fail the same silent
/// way. `DeviceInfo.DevicePublicKey` must be a real EC P-256 SPKI PEM: an
/// empty string answers 400 "invalid parameter".
///
/// The builds' accounts do not cross over: a China refresh token traded on an
/// international gate answers `20101 refresh token is invalid`, and the other
/// way round too. A credential therefore records the gate that accepted it,
/// and a mismatch says so in words rather than as an HTTP status.
enum TraeOAuth {
    // MARK: - One build's values

    /// How a build's device identity is made.
    enum DeviceIdentity: Sendable {
        /// A fresh 64-hex machine id (the China client's `machine_id`).
        case hex64
        /// A UUID, which the international client sends as its `machine_id`.
        case uuid
    }

    /// Everything one build's flow needs that the other's does not share.
    struct Profile: Sendable {
        let site: TraeSite
        /// Where the sign-in page is, when it is known without asking. Nil
        /// asks `GetLoginGuidance` first, as the international client does:
        /// its page is not one fixed host.
        let fixedLoginHost: String?
        /// The gates to ask for a sign-in host. Empty for a build whose page
        /// is fixed.
        let guidanceURLs: [String]
        let pluginVersion: String
        let appVersion: String
        let appType: String
        let deviceBrand: String
        /// The `x_device_type` the page is told, which is also
        /// `DeviceInfo.OSInfo`.
        let osInfo: String
        let osVersion: String
        /// The page's `channel_name`; nil sends none, which the
        /// international client does.
        let channelName: String?
        let deviceIdentity: DeviceIdentity
        /// A device id the client sends as a constant; nil generates one.
        let fixedDeviceID: String?
        /// The account gates this build's exchange may use, in order. A
        /// sign-in only reaches the one that serves its region, so every one
        /// is tried before the sign-in is called failed.
        let exchangeOrigins: [String]

        static let china = Profile(
            site: .china,
            fixedLoginHost: "https://www.trae.cn",
            guidanceURLs: [],
            pluginVersion: "2.3.83560",
            appVersion: "3.3.100",
            appType: "stable",
            deviceBrand: "",
            osInfo: "windows",
            osVersion: "Windows 10 Home",
            channelName: "common",
            deviceIdentity: .hex64,
            fixedDeviceID: nil,
            exchangeOrigins: ["https://api.trae.cn"],
        )

        static let international = Profile(
            site: .international,
            fixedLoginHost: nil,
            guidanceURLs: [
                "https://api.marscode.com/cloudide/api/v3/trae/GetLoginGuidance",
                "https://api.trae.ai/cloudide/api/v3/trae/GetLoginGuidance",
                "https://www.trae.ai/cloudide/api/v3/trae/GetLoginGuidance",
            ],
            pluginVersion: "local",
            appVersion: "3.5.54",
            appType: "stable",
            deviceBrand: "unknown",
            osInfo: "unknown",
            osVersion: "unknown",
            channelName: nil,
            deviceIdentity: .uuid,
            fixedDeviceID: "0",
            // The gates the client's `product.json` publishes for its
            // account service: the default, Singapore and the US TTP gate,
            // then the ones the API's own hosts serve.
            exchangeOrigins: [
                "https://grow-normal.trae.ai",
                "https://growsg-normal.trae.ai",
                "https://grow-normal.traeapi.us",
                "https://api.marscode.com",
                "https://api.trae.ai",
                "https://www.trae.ai",
            ],
        )

        static func of(_ site: TraeSite) -> Profile {
            site == .china ? .china : .international
        }
    }

    // MARK: - Shared paths

    static let authorizationPath = "/authorization"
    static let callbackPath = "/authorize"
    /// The sign-in's `ExchangeToken`, which is not the renewal's.
    static let authExchangePath = "/trae/api/v3/oauth/ExchangeToken"

    static let clientID = "ono9krqynydwx5"
    static let loginRedirect = "0"
    static let platformCode = "IDE_PC"
    static let deviceType = "PC"

    // MARK: - The credential's extras

    /// The account's id, which the renewal body carries as `UserID` and
    /// `TraeCredential` reads back.
    static let userIDExtra = "userId"
    /// `Result.BoundDeviceID`: the device the service bound this sign-in to.
    static let boundDeviceIDExtra = "deviceId"
    /// The device id this sign-in registered, which the client sends as
    /// `x-device-id` on its own account calls.
    static let loginDeviceIDExtra = "checkinDeviceId"
    /// The machine id this sign-in sent.
    static let machineIDExtra = "machineId"
    /// The gate that accepted this sign-in, which its renewals go to: the
    /// international build has several, and only one serves the account.
    static let oauthHostExtra = "oauthHost"

    /// The listener `AccountDesk` binds for these providers: the port and
    /// path it asks for are the flow's, and this flow binds a free port of
    /// its own, which it reads back from `redirectURI` once it is listening.
    static let listener: OAuthLoopbackFactory = { _, _, _ in TraeLoopback() }

    // MARK: - The sign-in

    /// Runs the whole flow, ending with the credential to store.
    ///
    /// The listener comes from `callbacks.loopback`, which `AccountDesk`
    /// wraps in `PasteableLoopback` and records on the run — the same object
    /// a pasted redirect reaches, so the page's `authorize` event says one
    /// can stand in for it: the sheet may hand the redirect back to the
    /// system instead of to this server, and `AccountDesk.respond` then
    /// finishes the sign-in with the address Safari shows.
    static func login(
        profile: Profile,
        callbacks: OAuthLogin.Callbacks,
        client: HTTPClient = URLSessionHTTPClient(),
    ) async throws -> OAuthCredentials {
        try Task.checkCancellation()
        guard profile.site == .china, profile.fixedLoginHost == "https://www.trae.cn",
              profile.exchangeOrigins == ["https://api.trae.cn"] else {
            throw TraeOAuthError("仅支持固定国内 Trae 站点，不接受自定义登录域名。")
        }
        let loginTraceID = UUID().uuidString
        let listener = try callbacks.loopback("127.0.0.1", 0, callbackPath)
        if let local = listener as? TraeLoopback { local.expectTrace(loginTraceID) }
        defer { listener.stop() }
        try await listener.listen()
        try Task.checkCancellation()

        let pkce = PKCE.random()
        let machineID = profile.deviceIdentity == .uuid
            ? UUID().uuidString
            : PKCE.randomHex(bytes: 32)
        let deviceID = profile.fixedDeviceID ?? randomDeviceID()

        let loginHost = try await signInHost(
            profile: profile,
            loginTraceID: loginTraceID,
            client: client,
        )
        let page = try loginURL(
            loginHost: loginHost,
            redirect: listener.redirectURI,
            machineID: machineID,
            deviceID: deviceID,
            loginTraceID: loginTraceID,
            pkce: pkce,
            profile: profile,
        )
        callbacks.onProgress("waiting for the Trae sign-in to finish in the browser…")
        let parameters = try await present(page, callbacks: callbacks) {
            try await listener.waitForCallback()
        }
        guard try TraeCallbackRequest.traceID(parameters) == loginTraceID else {
            throw TraeOAuthError("登录回调与本次请求不匹配，请重新登录。")
        }
        try checkCallbackError(parameters)

        let payload = try callbackPayload(parameters)
        guard payload.loginHost.isEmpty || payload.loginHost == "https://api.trae.cn" else {
            throw TraeOAuthError("登录回调包含非固定国内授权域名，已拒绝。")
        }
        try Task.checkCancellation()
        let exchanged = try await exchange(
            authCode: payload.authCode,
            codeVerifier: pkce.verifier,
            machineID: machineID,
            deviceID: deviceID,
            profile: profile,
            client: client,
        )

        var credentials = OAuthCredentials(
            access: exchanged.access,
            refresh: exchanged.refresh,
            expires: exchanged.expires,
        )
        let userID = payload.userID.isEmpty ? jwtUserID(exchanged.access) : payload.userID
        if !userID.isEmpty {
            credentials.extras[userIDExtra] = .string(userID)
        }
        if !exchanged.boundDeviceID.isEmpty {
            credentials.extras[boundDeviceIDExtra] = .string(exchanged.boundDeviceID)
        }
        credentials.extras[loginDeviceIDExtra] = .string(deviceID)
        credentials.extras[machineIDExtra] = .string(machineID)
        credentials.extras[oauthHostExtra] = .string(exchanged.origin)
        return credentials
    }

    /// Where this build's sign-in page is: the host it publishes, or the one
    /// `GetLoginGuidance` names.
    ///
    /// The China build's page is one host and it does not ask. The
    /// international build's is not, so it asks and takes the answer; when
    /// no gate answers, the sign-in says so rather than opening a page that
    /// would not know the client.
    static func signInHost(
        profile: Profile,
        loginTraceID: String,
        client: HTTPClient = URLSessionHTTPClient(),
    ) async throws -> String {
        if let fixed = profile.fixedLoginHost { return fixed }
        var failures: [String] = []
        for address in profile.guidanceURLs {
            guard let url = URL(string: address) else { continue }
            do {
                let body = try JSONSerialization.data(withJSONObject: [
                    "loginTraceID": loginTraceID,
                    "login_trace_id": loginTraceID,
                ])
                let (response, data) = try await client.request(
                    url: url,
                    method: "POST",
                    headers: ["Accept": "application/json", "Content-Type": "application/json"],
                    body: body,
                )
                guard response.statusCode == 200, data.count <= 1024 * 1024,
                      let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                      let host = guidanceHost(root), !host.isEmpty
                else {
                    failures.append("\(address): no sign-in host")
                    continue
                }
                return host
            } catch {
                try Task.checkCancellation()
                if error is CancellationError { throw error }
                failures.append("sign-in guidance unavailable")
            }
        }
        throw TraeOAuthError(
            "The Trae sign-in page could not be found. \(failures.joined(separator: " · "))",
        )
    }

    /// `Result.LoginHost`, whichever spelling the gate answers with.
    static func guidanceHost(_ root: [String: Any]) -> String? {
        for key in ["Result", "result", "data"] {
            if let layer = root[key] as? [String: Any],
               let host = firstString(layer, ["LoginHost", "loginHost", "LoginURL", "loginUrl"])
            {
                return host
            }
        }
        return firstString(root, ["LoginHost", "loginHost", "loginUrl"])
    }

    /// `<host>/authorization?<query>`, its parameters in the order the client
    /// sends them so a capture can be compared line for line. `URLComponents`
    /// does the percent-encoding: the callback address carries `://` and `:`
    /// and a hand-built query loses them.
    static func loginURL(
        loginHost: String,
        redirect: String,
        machineID: String,
        deviceID: String,
        loginTraceID: String,
        pkce: PKCE,
        profile: Profile,
    ) throws -> URL {
        guard profile.site == .china, loginHost == "https://www.trae.cn",
              let callback = URLComponents(string: redirect), callback.scheme == "http",
              callback.host == "127.0.0.1", let port = callback.port, (1...65535).contains(port),
              callback.path == callbackPath, callback.user == nil, callback.password == nil,
              callback.query == nil, callback.fragment == nil else {
            throw TraeOAuthError("登录地址或本机回调地址不匹配，已拒绝。")
        }
        var components = URLComponents(string: "https://www.trae.cn" + authorizationPath)
        var items = [
            URLQueryItem(name: "login_version", value: "1"),
            URLQueryItem(name: "auth_from", value: "trae"),
            URLQueryItem(name: "login_channel", value: "native_ide"),
            URLQueryItem(name: "plugin_version", value: profile.pluginVersion),
            URLQueryItem(name: "auth_type", value: "local"),
            URLQueryItem(name: "client_id", value: clientID),
            URLQueryItem(name: "redirect", value: loginRedirect),
            URLQueryItem(name: "login_trace_id", value: loginTraceID),
            URLQueryItem(name: "auth_callback_url", value: redirect),
            URLQueryItem(name: "machine_id", value: machineID),
            URLQueryItem(name: "device_id", value: deviceID),
            URLQueryItem(name: "x_device_id", value: deviceID),
            URLQueryItem(name: "x_machine_id", value: machineID),
            URLQueryItem(name: "x_device_brand", value: profile.deviceBrand),
            URLQueryItem(name: "x_device_type", value: profile.osInfo),
            URLQueryItem(name: "x_os_version", value: profile.osVersion),
            URLQueryItem(name: "x_env", value: ""),
            URLQueryItem(name: "x_app_version", value: profile.appVersion),
            URLQueryItem(name: "x_app_type", value: profile.appType),
            URLQueryItem(name: "code_challenge", value: pkce.challenge),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
        ]
        // The international client sends no channel name; the China one
        // sends `common`, and a page given one too few parameters stops at
        // "authenticating" without saying why.
        if let channelName = profile.channelName {
            items.append(URLQueryItem(name: "channel_name", value: channelName))
        }
        components?.queryItems = items
        guard let url = components?.url else {
            throw TraeOAuthError("The Trae sign-in address could not be built.")
        }
        return url
    }

    // MARK: - The callback

    /// What the page called back with.
    struct Callback: Sendable, Equatable {
        /// `authCodeInfo.AuthCode`, exchanged for the token.
        var authCode: String
        /// `userInfo.UserID`, empty when the page sent no user block.
        var userID: String
        /// `loginTraceID`, the value this sign-in generated.
        var loginTraceID: String
        /// `loginHost`: the gate this account belongs to, on the build that
        /// has more than one. Empty on the China build.
        var loginHost: String
    }

    /// Reads `authCodeInfo` out of the callback's query.
    ///
    /// The page is dual-mode: with a `code_challenge` it hands back an
    /// `authCodeInfo` for the client to exchange, without one it calls
    /// `GetRefreshToken` itself and hands back `refreshToken`. This flow
    /// always asks for PKCE, so a callback without an auth code is a failure
    /// the user can act on rather than a second flow.
    static func callbackPayload(_ parameters: [String: String]) throws -> Callback {
        guard let raw = parameters["authCodeInfo"], !raw.isEmpty,
              let data = raw.data(using: .utf8),
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let authCode = firstString(object, ["AuthCode", "authCode"]), !authCode.isEmpty
        else {
            throw TraeOAuthError("The Trae page did not return a sign-in code. Sign in again.")
        }
        var userID = ""
        if let raw = parameters["userInfo"], !raw.isEmpty,
           let data = raw.data(using: .utf8),
           let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        {
            userID = firstString(object, ["UserID", "UserId", "userId"]) ?? ""
        }
        return Callback(
            authCode: authCode,
            userID: userID,
            loginTraceID: try TraeCallbackRequest.traceID(parameters) ?? "",
            loginHost: firstString(parameters, ["loginHost", "login_host", "LoginHost"]) ?? "",
        )
    }

    // MARK: - The exchange

    struct Exchanged: Sendable {
        var access: String
        var refresh: String
        var boundDeviceID: String
        /// Unix ms of the access token's expiry; `.max` when it says none.
        var expires: Int64
        /// The gate that answered, which the credential keeps for renewal.
        var origin: String
    }

    /// `POST <gate>/trae/api/v3/oauth/ExchangeToken`, the body exactly the
    /// five fields the client sends. No `ClientSecret` and no `DeviceProof`:
    /// both belong to the renewal path, and this endpoint refuses them.
    ///
    /// Every gate in the build's list is tried, and only the one that answers
    /// ends the call. The builds' accounts do not cross over, so an answer
    /// naming `20101` is reported as signing in to the wrong build rather
    /// than as a failed exchange.
    static func exchange(
        authCode: String,
        codeVerifier: String,
        machineID: String,
        deviceID: String,
        profile: Profile,
        client: HTTPClient = URLSessionHTTPClient(),
        exchangeOrigins: [String]? = nil,
    ) async throws -> Exchanged {
        try Task.checkCancellation()
        guard profile.site == .china,
              (exchangeOrigins ?? profile.exchangeOrigins) == ["https://api.trae.cn"] else {
            throw TraeOAuthError("授权码只能发送到固定国内 Trae 授权站点。")
        }
        let body: [String: Any] = [
            "ClientID": clientID,
            "AuthCode": authCode,
            "CodeVerifier": codeVerifier,
            "DeviceInfo": deviceInfo(
                machineID: machineID,
                deviceID: deviceID,
                profile: profile,
            ),
            "IDEVersion": profile.appVersion,
        ]
        guard let payload = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]) else {
            throw TraeOAuthError("The Trae sign-in request could not be built.")
        }

        var failures: [String] = []
        var wrongBuild = false
        for origin in exchangeOrigins ?? profile.exchangeOrigins {
            guard let url = URL(string: origin + authExchangePath) else { continue }
            do {
                let (response, answer) = try await client.request(
                    url: url,
                    method: "POST",
                    headers: [
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-cloudide-token": "",
                    ],
                    body: payload,
                )
                guard answer.count <= 1024 * 1024,
                      let root = (try? JSONSerialization.jsonObject(with: answer)) as? [String: Any]
                else {
                    failures.append("\(origin): unreadable answer (HTTP \(response.statusCode))")
                    continue
                }
                if let failure = envelopeError(root) {
                    if failure.contains("20101")
                        || failure.lowercased().contains("refresh token is invalid")
                    {
                        wrongBuild = true
                    }
                    failures.append("exchange refused (HTTP \(response.statusCode))")
                    continue
                }
                guard response.statusCode == 200 else {
                    failures.append("\(origin): HTTP \(response.statusCode)")
                    continue
                }
                let result = (root["Result"] ?? root["result"]) as? [String: Any] ?? root
                guard let access = firstString(
                    result,
                    ["Token", "token", "AccessToken", "accessToken", "access_token"],
                ), !access.isEmpty
                else {
                    failures.append("\(origin): no token")
                    continue
                }
                return Exchanged(
                    access: access,
                    refresh: firstString(result, ["RefreshToken", "refreshToken", "refresh_token"]) ?? "",
                    boundDeviceID: firstString(result, ["BoundDeviceID", "BoundDeviceId", "boundDeviceId"]) ?? "",
                    expires: expiry(
                        result["TokenExpireAt"] ?? result["tokenExpireAt"]
                            ?? result["ExpiresAt"] ?? result["expiresAt"],
                    ),
                    origin: origin,
                )
            } catch {
                try Task.checkCancellation()
                if error is CancellationError { throw error }
                failures.append("exchange unavailable")
            }
        }
        if wrongBuild {
            throw TraeOAuthError(
                profile.site == .china
                    ? "This account belongs to the international build. Sign in to Trae instead."
                    : "This account belongs to the China build. Sign in to Trae CN instead.",
            )
        }
        throw TraeOAuthError("The Trae sign-in could not be completed. \(failures.joined(separator: " · "))")
    }

    /// The twelve fields the client sends, in its order. The ones it takes
    /// from the machine (brand, CPU, model) are empty rather than guessed,
    /// and the public key is a real one: the service validates it.
    static func deviceInfo(machineID: String, deviceID: String, profile: Profile) -> [String: Any] {
        [
            "DeviceID": deviceID,
            "MachineID": machineID,
            "PlatformCode": platformCode,
            "DeviceType": deviceType,
            "DeviceName": ProcessInfo.processInfo.hostName,
            "DeviceModel": profile.deviceBrand,
            "ClientVersion": profile.appVersion,
            "DevicePublicKey": P256.Signing.PrivateKey().publicKey.pemRepresentation,
            "DeviceBrand": profile.deviceBrand,
            "DeviceCPU": "",
            "OSInfo": profile.osInfo,
            "OSVersion": profile.osVersion,
        ]
    }

    // MARK: - Small helpers

    /// Sixteen decimal digits, the shape the China page checks for its
    /// `device_id` and the id the client sends as `x-device-id`.
    static func randomDeviceID() -> String {
        (0 ..< 16).map { _ in String(Int.random(in: 0 ... 9)) }.joined()
    }

    /// `https://host[:port]` of an address a page or a gate named; nil when
    /// it names no host.
    static func origin(of address: String) -> String? {
        var text = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") {
            text = "https://" + text.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        }
        guard let components = URLComponents(string: text), let host = components.host, !host.isEmpty
        else { return nil }
        let scheme = components.scheme?.lowercased() ?? "https"
        guard let port = components.port else { return "\(scheme)://\(host)" }
        return "\(scheme)://\(host):\(port)"
    }

    /// The user id a JWT carries, for a callback whose `userInfo` was absent.
    static func jwtUserID(_ token: String) -> String {
        let parts = token.split(separator: ".")
        guard parts.count > 1 else { return "" }
        var base64 = String(parts[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while base64.count % 4 != 0 { base64 += "=" }
        guard let data = Data(base64Encoded: base64),
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        else { return "" }
        return firstString(object, ["user_id", "userId", "uid", "sub", "UserID"]) ?? ""
    }

    /// `TokenExpireAt` is Unix seconds or milliseconds; an entry that says
    /// neither never lapses.
    static func expiry(_ raw: Any?) -> Int64 {
        guard let number = raw as? NSNumber else { return .max }
        let value = number.doubleValue
        guard value.isFinite, value > 0 else { return .max }
        let milliseconds = value > 1_000_000_000_000 ? value : value * 1000
        guard milliseconds.isFinite, milliseconds < Double(Int64.max) else { return .max }
        return Int64(milliseconds)
    }

    /// The first non-empty string among `keys`, numbers included as text.
    static func firstString(_ object: [String: Any], _ keys: [String]) -> String? {
        for key in keys {
            if let value = object[key] as? String, !value.isEmpty {
                return value
            }
            if let value = object[key] as? NSNumber {
                return value.stringValue
            }
        }
        return nil
    }

    static func firstString(_ parameters: [String: String], _ keys: [String]) -> String? {
        for key in keys where parameters[key]?.isEmpty == false {
            return parameters[key]
        }
        return nil
    }

    /// Trae's `{Code, Message}` envelope, either spelling; a body with no
    /// code is a success, which some of its services answer with.
    static func envelopeError(_ root: [String: Any]) -> String? {
        for key in ["Code", "code", "ErrCode", "errCode"] {
            guard let value = root[key] else { continue }
            let code: Int? = if let number = value as? NSNumber {
                number.intValue
            } else if let text = value as? String {
                Int(text)
            } else {
                nil
            }
            guard let code, code != 0 else { continue }
            let message = firstString(root, ["Message", "message", "Msg", "msg", "ErrMsg", "errMsg"])
            return message ?? "code \(code)"
        }
        if let error = root["Error"] as? String ?? root["error"] as? String, !error.isEmpty {
            return error
        }
        return nil
    }

    /// `access_denied` is the user leaving the page, which ends the sign-in
    /// `cancelled` rather than `failed`.
    static func checkCallbackError(_ parameters: [String: String]) throws {
        guard let error = firstString(parameters, ["error", "error_code", "errorCode"]) else { return }
        if error == "access_denied" { throw OAuthLoginError.cancelled }
        let description = firstString(parameters, ["error_description", "error_desc", "message"]) ?? ""
        throw OAuthLoginError.denied(
            "Trae \(error)\(description.isEmpty ? "" : ": \(description)")",
        )
    }

    /// kwwk's `OAuthLogin.present`, which is internal to its module: the
    /// host's presenter when it has one, otherwise the URL to the host and
    /// the work beside it.
    static func present<Outcome: Sendable>(
        _ url: URL,
        callbacks: OAuthLogin.Callbacks,
        while work: @escaping @Sendable () async throws -> Outcome,
    ) async throws -> Outcome {
        if let browser = callbacks.browser {
            return try await browser.run(url, while: work)
        }
        callbacks.onAuthURL(url)
        return try await work()
    }
}

/// One failure of the Trae sign-in, in words the user can act on.
struct TraeOAuthError: Error, LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

// BEGIN SUBSCRIPTION_CALLBACK_PURE
/// The reference callback uses loginTraceID; the authorize URL uses
/// login_trace_id. Accept either spelling, never contradictory aliases.
/// Invalid/foreign callbacks must NOT consume the active login.
enum TraeCallbackRequest {
    struct Rejected: Error {
        let status: String
        let message: String
    }
    enum Action {
        case preflight
        case callback([String: String])
    }
    static func traceID(_ parameters: [String: String]) throws -> String? {
        let values = ["loginTraceID", "login_trace_id"].compactMap { parameters[$0] }
        guard values.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 256 }),
              Set(values).count <= 1 else {
            throw Rejected(status: "400 Bad Request", message: "Invalid login correlation")
        }
        return values.first
    }
    static func parse(_ head: String, port: UInt16, expectedTrace: String) throws -> Action {
        func reject(_ status: String = "400 Bad Request", _ message: String = "Invalid callback") -> Rejected {
            Rejected(status: status, message: message)
        }
        guard !expectedTrace.isEmpty, port > 0, head.utf8.count <= 65536 else { throw reject() }
        let lines = head.components(separatedBy: "\r\n")
        let request = (lines.first ?? "").components(separatedBy: " ")
        guard request.count == 3, ["HTTP/1.0", "HTTP/1.1"].contains(request[2]) else { throw reject() }
        let method = request[0], target = request[1]
        guard method == "GET" || method == "OPTIONS" else { throw reject("405 Method Not Allowed") }
        guard target.hasPrefix("/"), !target.hasPrefix("//"), !target.contains("#"),
              target.utf8.allSatisfy({ $0 > 32 && $0 < 127 }), target.removingPercentEncoding != nil,
              let url = URLComponents(string: "http://127.0.0.1" + target) else { throw reject() }
        guard url.path == "/authorize" else { throw reject("404 Not Found") }
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { throw reject() }
            let name = String(line[..<colon]).lowercased()
            let value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty, name.utf8.allSatisfy({ (33...126).contains(Int($0)) }),
                  headers[name] == nil,
                  !value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else { throw reject() }
            headers[name] = value
        }
        // Reject DNS rebinding and cross-site fetches, but allow a whole-page
        // redirect (normally no Origin). Never echo an arbitrary origin.
        guard headers["host"] == "127.0.0.1:\(port)",
              headers["origin"] == nil || headers["origin"] == "https://www.trae.cn",
              headers["transfer-encoding"] == nil,
              headers["content-length"] == nil || headers["content-length"] == "0" else { throw reject() }
        if method == "OPTIONS" { return .preflight }
        var parameters: [String: String] = [:]
        for item in url.queryItems ?? [] {
            guard parameters[item.name] == nil else { throw reject() }
            parameters[item.name] = item.value ?? ""
        }
        guard try traceID(parameters) == expectedTrace else { throw reject() }
        let errors = ["error", "error_code", "errorCode"].compactMap { parameters[$0] }.filter { !$0.isEmpty }
        if errors.isEmpty {
            guard let raw = parameters["authCodeInfo"], let data = raw.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw reject() }
            let codes = ["AuthCode", "authCode"].compactMap { object[$0] as? String }
            guard !codes.isEmpty, codes.allSatisfy({ !$0.isEmpty }), Set(codes).count == 1 else { throw reject() }
        } else {
            guard Set(errors).count == 1 else { throw reject() }
        }
        let hosts = ["loginHost", "login_host", "LoginHost"].compactMap { parameters[$0] }.filter { !$0.isEmpty }
        guard hosts.allSatisfy({ $0 == "https://api.trae.cn" }) else { throw reject() }
        return .callback(parameters)
    }
}

/// stop is terminal, including a callback delivered before waitForCallback.
/// Only the first answer wins; a listener cannot be reused for another login.
struct TraeCallbackState {
    private(set) var expectedTrace: String?
    private(set) var started = false
    private(set) var stopped = false
    private var answer: Result<[String: String], Error>?
    mutating func expectTrace(_ trace: String) {
        guard !started, !stopped, !trace.isEmpty else { return }
        expectedTrace = trace
    }
    mutating func begin() -> Bool {
        guard !started, !stopped, expectedTrace != nil else { return false }
        started = true
        return true
    }
    mutating func finish(_ result: Result<[String: String], Error>) -> Bool {
        guard started, !stopped, answer == nil else { return false }
        answer = result
        return true
    }
    mutating func stop() { stopped = true; answer = .failure(CancellationError()) }
    var result: Result<[String: String], Error>? { answer }
}
// END SUBSCRIPTION_CALLBACK_PURE

/// The loopback the Trae page calls back to.
///
/// kwwk's own `OAuthCallbackServer` only resolves a redirect that carries
/// `code=`, the authorization-code shape; Trae answers with `authCodeInfo`.
/// So this one binds `127.0.0.1` on a free port, answers `/authorize` once,
/// and leaves every other request unanswered — a browser probe or a scanner
/// must not end a sign-in the user is still completing.
///
/// It is a plain HTTP/1.1 server over `NWListener`: the page's redirect is a
/// whole-page navigation, so there is no request body to read and no
/// keep-alive to honour. `Access-Control-Allow-Origin` is set anyway, as the
/// client does, in case the page ever redirects from a fetch.
final class TraeLoopback: OAuthLoopbackListener, @unchecked Sendable {
    private let lock = NSLock()
    private var listener: NWListener?
    private var boundPort: UInt16?
    private var listeningContinuation: CheckedContinuation<Void, Error>?
    private var waiter: CheckedContinuation<[String: String], Error>?
    private var state = TraeCallbackState()
    private var connections: [ObjectIdentifier: NWConnection] = [:]

    func expectTrace(_ trace: String) {
        lock.subscriptionWithLock { state.expectTrace(trace) }
    }

    var redirectURI: String {
        "http://127.0.0.1:\(lock.subscriptionWithLock { boundPort ?? 0 })\(TraeOAuth.callbackPath)"
    }

    func listen() async throws {
        try Task.checkCancellation()
        guard lock.subscriptionWithLock({ state.begin() }) else {
            throw TraeOAuthError("登录监听未准备好或已结束，请重新开始。")
        }
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        let local: NWListener
        do {
            local = try NWListener(using: parameters)
        } catch {
            stop()
            throw TraeOAuthError("登录无法建立本机回调地址，请重新开始。")
        }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                let refused = lock.subscriptionWithLock { () -> Bool in
                    guard !state.stopped, !Task.isCancelled else { return true }
                    listeningContinuation = continuation
                    listener = local
                    return false
                }
                guard !refused else {
                    local.cancel()
                    continuation.resume(throwing: CancellationError())
                    return
                }
                local.stateUpdateHandler = { [weak self, weak local] status in
                    guard let self else { return }
                    switch status {
                    case .ready:
                        if let port = local?.port?.rawValue, port > 0 {
                            self.resolveListening(port: port, error: nil)
                        } else {
                            self.resolveListening(port: nil, error: TraeOAuthError("登录未获得有效本机端口。"))
                            self.stop()
                        }
                    case .failed:
                        let error = TraeOAuthError("本机登录回调连接失败，请重新开始。")
                        self.resolveListening(port: nil, error: error)
                        _ = self.resolve(.failure(error))
                        self.stop()
                    case .cancelled:
                        self.stop()
                    default: break
                    }
                }
                local.newConnectionHandler = { [weak self] connection in
                    guard let self else { connection.cancel(); return }
                    self.accept(connection)
                }
                local.start(queue: DispatchQueue(label: "com.openminis.subscription.trae-loopback"))
            }
            try Task.checkCancellation()
        } onCancel: { self.stop() }
    }

    private func resolveListening(port: UInt16?, error: Error?) {
        let continuation: CheckedContinuation<Void, Error>? = self.lock.subscriptionWithLock {
            guard let continuation = self.listeningContinuation else { return nil }
            self.listeningContinuation = nil
            if let port { self.boundPort = port }
            return continuation
        }
        guard let continuation else { return }
        if let error {
            continuation.resume(throwing: error)
        } else {
            continuation.resume()
        }
    }

    func waitForCallback() async throws -> [String: String] {
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<[String: String], Error>) in
                let early: Result<[String: String], Error>? = lock.subscriptionWithLock {
                    if state.stopped || Task.isCancelled { return .failure(CancellationError()) }
                    if let result = state.result { return result }
                    guard state.started, waiter == nil else {
                        return .failure(TraeOAuthError("登录回调不能重复等待。"))
                    }
                    waiter = continuation
                    return nil
                }
                if let early {
                    continuation.resume(with: early)
                }
            }
        } onCancel: {
            stop()
        }
    }

    func stop() {
        let resources = lock.subscriptionWithLock { () -> (
            CheckedContinuation<[String: String], Error>?,
            CheckedContinuation<Void, Error>?, NWListener?, [NWConnection]) in
            state.stop()
            let resources = (waiter, listeningContinuation, listener, Array(connections.values))
            waiter = nil; listeningContinuation = nil; listener = nil; boundPort = nil
            connections.removeAll()
            return resources
        }
        resources.2?.cancel()
        for connection in resources.3 { connection.cancel() }
        resources.1?.resume(throwing: CancellationError())
        resources.0?.resume(throwing: CancellationError())
    }

    // MARK: - Requests

    private func accept(_ connection: NWConnection) {
        let accepted = lock.subscriptionWithLock { () -> Bool in
            guard !state.stopped, state.result == nil, connections.count < 16 else { return false }
            connections[ObjectIdentifier(connection)] = connection
            return true
        }
        guard accepted else { connection.cancel(); return }
        connection.stateUpdateHandler = { [weak self, weak connection] status in
            guard let self, let connection else { return }
            if case .cancelled = status { self.close(connection) }
            if case .failed = status { self.close(connection) }
        }
        let queue = DispatchQueue(label: "com.openminis.subscription.trae-connection")
        connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + 10) { [weak self, weak connection] in
            guard let connection else { return }
            self?.close(connection)
        }
        receive(connection, collected: Data())
    }

    private func close(_ connection: NWConnection) {
        _ = self.lock.subscriptionWithLock { self.connections.removeValue(forKey: ObjectIdentifier(connection)) }
        connection.cancel()
    }

    private func receive(_ connection: NWConnection, collected: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, ended, error in
            guard let self else {
                connection.cancel()
                return
            }
            guard !self.lock.subscriptionWithLock({ self.state.stopped }) else { self.close(connection); return }
            var collected = collected
            if let data { collected.append(data) }
            guard collected.count <= 65536 else { close(connection); return }
            // The head ends the request: a redirect carries no body.
            if let separator = collected.range(of: Data("\r\n\r\n".utf8)) {
                let head = String(decoding: collected[..<separator.lowerBound], as: UTF8.self)
                respond(connection, to: head)
                return
            }
            if ended || error != nil || collected.count > 65536 {
                connection.cancel()
                return
            }
            receive(connection, collected: collected)
        }
    }

    private func respond(_ connection: NWConnection, to head: String) {
        let active = lock.subscriptionWithLock { () -> (UInt16, String)? in
            guard !state.stopped, state.result == nil,
                  let port = boundPort, let trace = state.expectedTrace else { return nil }
            return (port, trace)
        }
        guard let active else {
            write(connection, status: "409 Conflict", body: "Login is no longer active")
            return
        }
        do {
            switch try TraeCallbackRequest.parse(head, port: active.0, expectedTrace: active.1) {
            case .preflight:
                write(connection, status: "204 No Content", body: "")
            case .callback(let parameters):
                guard resolve(.success(parameters)) else {
                    write(connection, status: "409 Conflict", body: "Login is no longer active")
                    return
                }
                // Receipt is not token exchange or Keychain success.
                write(connection, status: "200 OK", body: "<html><body>已收到登录结果，请返回 Minis 查看。</body></html>")
            }
        } catch let error as TraeCallbackRequest.Rejected {
            write(connection, status: error.status, body: error.message)
        } catch {
            write(connection, status: "400 Bad Request", body: "Invalid callback")
        }
    }

    private func write(_ connection: NWConnection, status: String, body: String) {
        let bytes = Array(body.utf8)
        let head = "HTTP/1.1 \(status)\r\n"
            + "Content-Type: text/html; charset=utf-8\r\n"
            + "Content-Length: \(bytes.count)\r\n"
            + "Cache-Control: no-store\r\n"
            + "Access-Control-Allow-Origin: https://www.trae.cn\r\n"
            + "Access-Control-Allow-Methods: GET,OPTIONS\r\n"
            + "Access-Control-Allow-Headers: content-type\r\n"
            + "Connection: close\r\n\r\n"
        var response = Data(head.utf8)
        response.append(Data(bytes))
        connection.send(content: response, completion: .contentProcessed { _ in
            connection.cancel()
        })
    }

    @discardableResult
    private func resolve(_ result: Result<[String: String], Error>) -> Bool {
        let delivery = lock.subscriptionWithLock { () -> (Bool, CheckedContinuation<[String: String], Error>?) in
            guard state.finish(result) else { return (false, nil) }
            let continuation = waiter
            waiter = nil
            return (true, continuation)
        }
        delivery.1?.resume(with: result)
        return delivery.0
    }
}
