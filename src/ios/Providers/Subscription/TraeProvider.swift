// Adapted from the user-provided Apelin-providers/trae/TraeProvider.swift archive.
// Protocol source only: NO Apelin runtime or registration dependency.
// SECURITY: trae-api-cn.mchost.guru is the host in that source, NOT a verified
// official trae.cn domain. It receives the account JWT. Do not silently swap
// it for a guessed domain; UI must disclose this trust boundary before login.
import CryptoKit
import Foundation
import KWWKAI

/// Trae, ByteDance's IDE, in its two builds: the China one (`trae`) and the
/// international one (`trae-intl`), each its own remote gate and sign-in the
/// way qoder and qoder.cn are.
public enum TraeSite: String, Sendable, CaseIterable, Hashable {
    case china
    case international

    /// The credential store id, in kwwk's shape.
    public var id: String {
        switch self {
        case .china: "trae"
        case .international: "trae-intl"
        }
    }

    public var name: String {
        switch self {
        case .china: "Trae CN"
        case .international: "Trae"
        }
    }

    /// The remote session gate. The agent and IDE endpoints hang off its
    /// origin, not off `/api/remote/v1`.
    public var remoteBase: String {
        switch self {
        case .china: "https://trae-api-cn.mchost.guru/api/remote/v1"
        case .international: "https://core-normal.trae.ai/api/remote/v1"
        }
    }

    /// Where `ExchangeToken` is posted. The international build's credential
    /// names its own account host (grow-normal.trae.ai among others); this is
    /// the one its remote gate publishes, used when the stored credential
    /// names none.
    public var oauthHost: String {
        switch self {
        case .china: "https://api.trae.cn"
        case .international: "https://core-normal.trae.ai"
        }
    }

    public init?(storeID: String) {
        guard let site = Self.allCases.first(where: { $0.id == storeID }) else { return nil }
        self = site
    }

    /// `https://host[:port]` of an address, which is what the agent and IDE
    /// endpoints hang off; nil when it names no host.
    public func origin(of address: String) -> String? {
        guard let components = URLComponents(string: address.trimmingCharacters(in: .whitespaces)),
              let host = components.host, !host.isEmpty
        else { return nil }
        let scheme = components.scheme?.lowercased() ?? "https"
        guard let port = components.port else { return "\(scheme)://\(host)" }
        return "\(scheme)://\(host):\(port)"
    }

    /// Source compatibility only: a stored base NEVER redirects credentials.
    /// The App additionally rejects a nonempty base before resolving auth.
    public func origin(base: String?) -> String {
        origin(of: remoteBase) ?? remoteBase
    }
}

/// What the account's stored key is, and how to renew it.
///
/// A browser sign-in stores the JWT, its refresh token and the device ids
/// that sign-in registered; a typed key stores the Cloud-IDE-JWT itself or
/// the account's refresh token, one opaque string in the API-key form. A
/// refresh token is exchanged once for a JWT when a request first needs one,
/// and the JWT is renewed the same way when it is about to lapse.
struct TraeCredential: Sendable {
    var access: String
    var refresh: String
    /// Unix ms of the access token's expiry; `.max` for one never lapses.
    var expires: Int64
    var userID: String
    /// The 64-hex machine id the browser sign-in sent, and the 16-digit
    /// device id it registered. Nil for a typed key: that sign-in made none,
    /// and the headers then derive both from the account.
    var machineID: String?
    var deviceID: String?
    /// The gate that accepted this sign-in, which its renewals go to: the
    /// international build has several and only one serves the account.
    var oauthHost: String?

    init(_ credentials: KWWKAI.OAuthCredentials) {
        access = credentials.access
        refresh = credentials.refresh
        expires = credentials.expires
        userID = TraeCredential.extra("userId", in: credentials) ?? ""
        machineID = TraeCredential.extra("machineId", in: credentials)
        deviceID = TraeCredential.extra("checkinDeviceId", in: credentials)
        oauthHost = TraeCredential.extra("oauthHost", in: credentials)
    }

    static func extra(_ key: String, in credentials: KWWKAI.OAuthCredentials) -> String? {
        guard case let .string(value)? = credentials.extras[key], !value.isEmpty else { return nil }
        return value
    }

    /// The base an account was given, when it typed one in.
    static func base(in credentials: KWWKAI.OAuthCredentials) -> String? {
        extra("baseUrl", in: credentials)
    }
}

/// One failure of the Trae wire, in words the user can act on.
struct TraeError: Error, LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// The token a request goes out with, renewed through `ExchangeToken`.
///
/// One per resolution, shared by every `authResolver` call, so a renewed JWT
/// is reused rather than exchanged again per request.
enum TraeTokenStore {
    struct Token: Sendable {
        var value: String
        var userID: String
        var refresh: String = ""
        var expires: Int64 = .max
        var machineID: String?
        var deviceID: String?
    }
}

// MARK: - The wire

/// Trae's chat channel and its model directory.
///
/// Chats go over `llm_utils_chat`, not `chat_sessions`: the latter runs the
/// model in Trae's own cloud sandbox, which executes tools itself and never
/// hands a `tool_calls` back. `llm_utils_chat` is the raw LLM proxy the IDE's
/// agent uses — the caller's tools pass through and pending calls stream
/// back to the caller.
public enum TraeWire {
    static let appID = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
    /// The SOLO generation's build, which the chat gate and the directory
    /// both read. The three version values are one set: a capture proved
    /// `x-ide-version-code: 20260820`, `x-ide-version: 0.1.61` and
    /// `User-Agent: Trae/0.1.61` together are what the gate accepts, and
    /// changing any one of them alone no longer matches its configuration
    /// table. The IDE generation's `3.3.x` is a different protocol line.
    static let ideVersion = "0.1.61"
    static let versionCode = 20260820

    /// The directory functions a model may be listed under. A model is
    /// callable only through the function whose roster publishes it.
    /// `solo_work_remote` first: it carries every model a user may pick
    /// (`glm-5.3` is only here, and asking through `solo_work_lite` answers
    /// `4001 param is invalid`). `solo_work_lite` lists internal agent
    /// entries too, so it stands in only when the first one fails.
    public static let directoryFunctions = ["solo_work_remote", "solo_work_lite"]

    /// The function a model is asked through when no roster named one.
    static let defaultFunction = "solo_work_remote"

    /// The model a session talks to when none was chosen.
    public static let defaultModel = "auto"

    static func chatURL(origin: String) -> URL? {
        URL(string: origin + "/api/agent/v3/llm_utils_chat")
    }

    static func directoryURL(origin: String) -> URL? {
        URL(string: origin + "/api/ide/v1/get_detail_param")
    }

    /// The headers every Trae request carries, whatever the account.
    static func clientHeaders() -> [String: String] {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        return [
            "x-plugin-channel": "icube-ai",
            "x-app-id": appID,
            "x-device-type": "ios",
            "x-device-cpu": "arm64",
            "x-os-version": "iOS \(version.majorVersion).\(version.minorVersion).\(version.patchVersion)",
            "x-ide-version-type": "stable",
            "x-app-version": ideVersion,
            "x-ide-version": ideVersion,
            "x-app-version-code": String(versionCode),
            "x-ide-version-code": String(versionCode),
            "request-traffic-type": "prod",
            "User-Agent": "Trae/\(ideVersion)",
        ]
    }

    /// The headers naming the account: its token in the three places the
    /// gate reads it, and the machine and device ids the browser sign-in
    /// registered. A typed key made neither, so both are derived from the
    /// account — there is no Trae install here to read them from.
    static func accountHeaders(
        token: String,
        userID: String,
        machineID registeredMachineID: String? = nil,
        deviceID: String? = nil,
    ) -> [String: String] {
        let trace = traceID()
        let machine = registeredMachineID ?? machineID(account: userID.isEmpty ? token : userID)
        return [
            "Authorization": "Cloud-IDE-JWT \(token)",
            "X-Ide-Token": token,
            "X-Cloudide-Token": token,
            "x-uid": userID,
            "x-machine-id": machine,
            "x-device-id": deviceID ?? machine,
            "x-custom-trace-id": trace,
            "x-flow-traceparent": "04-\(trace)-\(trace.prefix(16))-01",
        ]
    }

    static func traceID() -> String {
        var generator = SystemRandomNumberGenerator()
        return String((0 ..< 32).map { _ in "0123456789abcdef".randomElement(using: &generator) ?? "0" })
    }

    /// 32 hex digits, the same for one account across requests and renewals.
    static func machineID(account: String) -> String {
        let digest = SHA256.hash(data: Data(account.utf8))
        return String(digest.map { String(format: "%02x", $0) }.joined().prefix(32))
    }

    /// `POST {gate}/cloudide/api/v3/trae/oauth/ExchangeToken`.
    ///
    /// `gate` is the one the sign-in recorded: the international build has
    /// several, and a refresh token only renews against the one that issued
    /// it. Without one — a typed key — the build's own default is used.
    static func exchangeToken(
        site: TraeSite,
        refreshToken: String,
        userID: String,
        gate: String? = nil,
        client: KWWKAI.HTTPClient,
    ) async throws -> (access: String, refresh: String, expires: Int64) {
        guard site == .china, gate == nil || gate == site.oauthHost,
              let url = URL(string: "\(site.oauthHost)/cloudide/api/v3/trae/oauth/ExchangeToken") else {
            throw TraeError("Only the fixed Trae CN authentication host is allowed.")
        }
        let body: [String: Any] = [
            "ClientID": "ono9krqynydwx5",
            "RefreshToken": refreshToken,
            "ClientSecret": "-",
            "UserID": userID,
        ]
        let (response, data) = try await client.request(
            url: url,
            method: "POST",
            headers: ["Content-Type": "application/json", "Accept": "application/json"],
            body: try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]),
            cancellation: nil,
        )
        guard response.statusCode == 200, data.count <= 1024 * 1024,
              let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let result = (root["Result"] ?? root["result"]) as? [String: Any],
              let access = (result["Token"] ?? result["token"]) as? String, !access.isEmpty
        else {
            throw TraeError(
                response.statusCode == 401 || response.statusCode == 403
                    ? "Trae refused this token. Sign in again with a new one."
                    : "The Trae token could not be renewed (HTTP \(response.statusCode)).",
            )
        }
        let refresh = (result["RefreshToken"] ?? result["refreshToken"]) as? String ?? refreshToken
        return (access, refresh, expiry(result["TokenExpireAt"] ?? result["tokenExpireAt"]))
    }

    /// `TokenExpireAt` is Unix seconds or milliseconds, or a date string; an
    /// entry that says neither never lapses.
    static func expiry(_ raw: Any?) -> Int64 {
        func unix(_ value: Double) -> Int64 {
            let milliseconds = Int64(value)
            return milliseconds > 1_000_000_000_000 ? milliseconds : milliseconds * 1000
        }
        if let number = raw as? NSNumber, number.int64Value > 0 {
            return unix(number.doubleValue)
        }
        guard let text = raw as? String, !text.isEmpty else { return .max }
        if let seconds = Double(text), seconds > 0 { return unix(seconds) }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: text) ?? ISO8601DateFormatter().date(from: text) {
            return Int64(date.timeIntervalSince1970 * 1000)
        }
        return .max
    }

    // MARK: Request body

    /// A request body as `llm_utils_chat` takes it.
    ///
    /// The OpenAI body kwwk encodes is kept for its messages, tools and
    /// reasoning effort; everything else is this wire's own: the model's
    /// `config_name`, the directory `function` that lists it, and the
    /// scalar fields the gate reads as ints and strings.
    // BEGIN SUBSCRIPTION_TRAE_PURE
    static func mending(_ root: inout [String: Any], function: String) throws {
        let model = root["model"] as? String ?? ""
        var body: [String: Any] = [
            "app_id": appID,
            "app_version_code": versionCode,
            "function": function,
            "model": model,
            "config_name": model,
            "stream": true,
            "messages": try mendMessages(root["messages"] as? [[String: Any]] ?? []),
        ]
        if let tools = root["tools"] as? [[String: Any]], !tools.isEmpty {
            body["tools"] = try mendTools(tools)
        }
        if let effort = root["reasoning_effort"] as? String, !effort.isEmpty {
            body["reasoning_effort"] = effort
        }
        root = body
    }

    /// `llm_utils_chat` takes every message's content as text blocks. These
    /// are the mends the reference client makes: `developer` becomes
    /// `system`; an interrupted assistant turn's null or empty content
    /// becomes an empty block, which the upstream's validator accepts where
    /// it refuses null for every later request of that conversation; an
    /// assistant turn with neither text nor calls goes; and its `tool_calls`
    /// are read back as `function_call`.
    static func mendMessages(_ messages: [[String: Any]]) throws -> [[String: Any]] {
        var out: [[String: Any]] = []
        for var message in messages {
            if (message["role"] as? String) == "developer" {
                message["role"] = "system"
            }
            let role = message["role"] as? String ?? "user"
            let calls = message["tool_calls"] as? [[String: Any]]
            let hasContent: Bool = {
                if let text = message["content"] as? String { return !text.isEmpty }
                if let blocks = message["content"] as? [[String: Any]] { return !blocks.isEmpty }
                return false
            }()
            if role == "assistant", !hasContent, (calls ?? []).isEmpty { continue }
            message["content"] = try textBlocks(message["content"])
            // Portable visible reasoning is preserved. Provider-specific
            // encrypted reasoning_details must never cross this boundary.
            message.removeValue(forKey: "reasoning_details")
            if role == "assistant", let calls, !calls.isEmpty {
                message["function_call"] = calls
                message.removeValue(forKey: "tool_calls")
            }
            out.append(message)
        }
        return out
    }

    /// A message's content as `[{type: "text", text: …}]`. A bare string is
    /// wrapped; text blocks are kept; unsupported media fails closed.
    static func textBlocks(_ content: Any?) throws -> [[String: Any]] {
        switch content {
        case let text as String:
            return [["type": "text", "text": text]]
        case let blocks as [[String: Any]]:
            return try blocks.map { block in
                guard (block["type"] as? String) == "text", let text = block["text"] as? String else {
                    throw TraeError("Trae CN only accepts text blocks; attachment was not sent.")
                }
                return ["type": "text", "text": text]
            }
        case nil, is NSNull:
            return [["type": "text", "text": ""]]
        default:
            throw TraeError("Trae CN message content has an unsupported shape.")
        }
    }

    /// `parameters` is a JSON *string* on this wire, not an object.
    static func mendTools(_ tools: [[String: Any]]) throws -> [[String: Any]] {
        try tools.map { tool in
            guard var function = tool["function"] as? [String: Any],
                  let name = function["name"] as? String, !name.isEmpty,
                  let parameters = function["parameters"] as? [String: Any] else {
                throw TraeError("Trae tool definition is incomplete; schema was not replaced with {}.")
            }
            let data = try JSONSerialization.data(withJSONObject: parameters, options: [.sortedKeys])
            function["parameters"] = String(decoding: data, as: UTF8.self)
            return ["type": "function", "function": function]
        }
    }

    // MARK: Response frames

    /// What one upstream frame became: the OpenAI data lines to yield, and
    /// whether it carried an answer, closed the turn, or failed.
    struct Translation {
        var lines: [Data] = []
        /// Text, thinking or tool calls the caller can read.
        var answers = false
        /// The turn is over: its finish reason or its refusal has gone out.
        var ends = false
        /// The stream must stop reading this turn.
        var finished = false
        var failed = false
    }

    /// One upstream SSE frame as the OpenAI data lines
    /// `OpenAICompletionsProvider` reads.
    ///
    /// Upstream is `event: output` with `{response, reasoning_content,
    /// tool_calls}`, `event: token_usage`, `event: error {code, message}` and
    /// `event: done {finish_reason}` — no `choices` anywhere, so nothing
    /// downstream would read it as it comes.
    static func translated(event: String, data: String) -> Translation {
        var out = Translation()
        // A frame with no event name is the gateway's default, `output`.
        let named = event.isEmpty || event == "message" ? "output" : event
        guard let root = (try? JSONSerialization.jsonObject(with: Data(data.utf8))) as? [String: Any] else {
            out.lines = [errorFrame("Trae returned malformed JSON in an SSE frame.")]
            out.ends = true; out.finished = true; out.failed = true
            return out
        }
        // A queue refusal arrives as a 200 frame carrying its own status.
        if let status = root["statusCodeValue"] as? Int, status != 200 {
            let body = String(describing: root["body"] ?? "")
            out.lines = [errorFrame("Trae answered \(status): \(body.prefix(240))", code: root["code"], status: status)]
            out.ends = true
            out.finished = true
            out.failed = true
            return out
        }
        if let error = root["error"], !(error is NSNull) {
            let detail = error as? [String: Any] ?? [:]
            out.lines = [errorFrame(detail["message"] as? String ?? String(describing: error),
                code: detail["code"], status: detail["status_code"] as? Int)]
            out.ends = true; out.finished = true; out.failed = true
            return out
        }
        if named != "error", let code = root["code"],
           String(describing: code) != "0", String(describing: code) != "200" {
            out.lines = [errorFrame(root["message"] as? String ?? "Trae rejected the request.", code: code,
                status: (root["code"] as? Int).flatMap { [401, 403].contains($0) ? $0 : nil })]
            out.ends = true; out.finished = true; out.failed = true
            return out
        }
        switch named {
        case "error":
            let code = root["code"].map { String(describing: $0) } ?? ""
            let message = root["message"] as? String ?? "unknown"
            let status = root["status_code"] as? Int
                ?? (root["code"] as? Int).flatMap { [401, 403].contains($0) ? $0 : nil }
            out.lines = [errorFrame("Trae \(code.isEmpty ? "error" : "code \(code)"): \(message)", code: root["code"], status: status)]
            out.ends = true
            out.finished = true
            out.failed = true
        case "token_usage":
            out.lines = [usageFrame(root)]
        case "done":
            guard let reason = root["finish_reason"] as? String,
                  !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                out.lines = [errorFrame("Trae completion frame is missing finish_reason.")]
                out.ends = true; out.finished = true; out.failed = true
                return out
            }
            out.lines = [finishFrame(finishReason(reason))]
            out.ends = true
            out.finished = true
        case "output":
            if let reasoning = root["reasoning_content"] as? String, !reasoning.isEmpty {
                out.lines.append(deltaFrame(["reasoning_content": reasoning]))
                out.answers = true
            }
            if let text = root["response"] as? String, !text.isEmpty {
                out.lines.append(deltaFrame(["content": text]))
                out.answers = true
            }
            if let calls = root["tool_calls"] as? [[String: Any]] {
                for (position, call) in calls.enumerated() {
                    guard let frame = toolCallFrame(call, position: position) else {
                        out.lines = [errorFrame("Trae returned an invalid tool-call fragment.")]
                        out.ends = true; out.finished = true; out.failed = true
                        return out
                    }
                    out.lines.append(frame)
                    out.answers = true
                }
            }
        default:
            break
        }
        return out
    }

    /// The finish reason the callers read. The gate labels a tool-call turn
    /// `stop` as often as `tool_calls`, so a turn that streamed calls says it
    /// called them.
    static func finishReason(_ raw: String?) -> String {
        let reason = raw?.trimmingCharacters(in: .whitespaces) ?? ""
        switch reason {
        case "", "stop", "end": return "stop"
        case "length", "max_tokens": return "length"
        case "tool_calls", "function_call": return "tool_calls"
        default: return reason
        }
    }

    static func toolCallFrame(_ call: [String: Any], position: Int) -> Data? {
        let function = (call["function_call"] ?? call["function"]) as? [String: Any] ?? [:]
        if let raw = function["arguments"], !(raw is String) { return nil }
        if let raw = function["name"], !(raw is String) { return nil }
        if let raw = call["id"], !(raw is String) { return nil }
        if let raw = call["index"], SubscriptionDirectoryProtocol.integer(raw).map({ $0 >= 0 }) != true { return nil }
        var fields: [String: Any] = [:]
        if let name = function["name"] as? String, !name.isEmpty { fields["name"] = name }
        if let arguments = function["arguments"] as? String, !arguments.isEmpty { fields["arguments"] = arguments }
        guard !fields.isEmpty || (call["id"] as? String)?.isEmpty == false else { return nil }
        var entry: [String: Any] = [
            "index": (call["index"] as? NSNumber)?.intValue ?? position,
            "type": "function",
            "function": fields,
        ]
        if let id = call["id"] as? String, !id.isEmpty { entry["id"] = id }
        return deltaFrame(["tool_calls": [entry]])
    }

    static func deltaFrame(_ delta: [String: Any]) -> Data {
        sseData(["choices": [["index": 0, "delta": delta, "finish_reason": NSNull()]]])
    }

    static func finishFrame(_ reason: String) -> Data {
        sseData(["choices": [["index": 0, "delta": [String: Any](), "finish_reason": reason]]])
    }

    static func usageFrame(_ root: [String: Any]) -> Data {
        func number(_ key: String) -> Int {
            (root[key] as? NSNumber)?.intValue ?? 0
        }
        let usage: [String: Any] = [
            "prompt_tokens": number("prompt_tokens"),
            "completion_tokens": number("completion_tokens"),
            "total_tokens": number("total_tokens"),
        ]
        return sseData(["choices": [Any](), "usage": usage])
    }

    static func errorFrame(_ message: String, code: Any? = nil, status: Int? = nil) -> Data {
        var error: [String: Any] = ["message": message, "type": "upstream_error"]
        if let code { error["code"] = String(describing: code) }
        if let status { error["status_code"] = status }
        return sseData(["error": error])
    }

    static func sseData(_ object: [String: Any]) -> Data {
        guard let json = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else {
            return Data("data: {}\n\n".utf8)
        }
        var out = Data("data: ".utf8)
        out.append(json)
        out.append(Data("\n\n".utf8))
        return out
    }

    static let doneFrame = Data("data: [DONE]\n\n".utf8)
    // END SUBSCRIPTION_TRAE_PURE

    // MARK: Model directory

    /// One model as the directory publishes it, with the function that lists
    /// it — the only one the model may be asked through.
    public struct Entry: Sendable, Hashable {
        public var id: String
        public var function: String
        public var reasoning: Bool
        public var contextWindow: Int
        public var maxTokens: Int
        /// nil = the directory did not declare effort tiers (do not guess).
        public var efforts: [String]?

        var model: KWWKAI.Model {
            var compat = KWWKAI.ModelCompat()
            compat.supportsStore = false
            compat.supportsDeveloperRole = false
            compat.supportsStrictMode = false
            compat.supportsLongCacheRetention = false
            compat.supportsReasoningEffort = efforts?.isEmpty == false
            compat.maxTokensField = "max_tokens"
            compat.thinkingFormat = "openai"
            var map: [String: String?]?
            if let efforts, !efforts.isEmpty {
                map = [:]
                for level in ["off", "minimal", "low", "medium", "high", "xhigh", "max"] {
                    let wire = level == "off" ? "none" : level
                    map?[level] = .some(efforts.contains(wire) ? wire : nil)
                }
            }
            return KWWKAI.Model(id: id, api: "openai-completions", provider: "trae",
                baseURL: SubscriptionEndpoints.traeOrigin, reasoning: reasoning, input: [.text],
                contextWindow: contextWindow, maxTokens: maxTokens, compat: compat, thinkingLevelMap: map)
        }
    }

    // No bundled/fallback roster: only this account's live directory grants routes.

    /// `POST {origin}/api/ide/v1/get_detail_param` for one function.
    static func directoryRequest(origin: String, function: String, headers: [String: String]) -> URLRequest? {
        guard let url = directoryURL(origin: origin) else { return nil }
        // Short: the account verification that reads this roster has 45
        // seconds for the whole sign-in.
        var request = URLRequest(url: url, timeoutInterval: 12)
        request.httpMethod = "POST"
        for (name, value) in headers where !value.isEmpty {
            request.setValue(value, forHTTPHeaderField: name)
        }
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "function": function,
            "config_names": NSNull(),
            "need_prompt": false,
            "current_config_info": NSNull(),
            "poly_prompt": true,
            "mode_type": NSNull(),
            "agent_type": NSNull(),
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
        return request
    }

    /// Every function's roster, the first listing of an id winning. Entries
    /// the IDE never shows an agent (sub-agents, summarizers, internal
    /// helpers) are left out.
    static func entries(in document: [String: Any], function: String) -> [Entry] {
        let list = document["config_info_list"] as? [[String: Any]] ?? []
        return list.compactMap { raw in
            guard let id = raw["config_name"] as? String, !id.isEmpty, !isHidden(id),
                  raw["is_invisible_to_user"] as? Bool != true
            else { return nil }
            let display = raw["display_config"] as? [String: Any] ?? [:]
            let context = raw["context_window_tokens"] as? [String: Any] ?? [:]
            let detail = (raw["model_detail_list"] as? [[String: Any]])?.first ?? [:]
            let window = (context["dev"] as? NSNumber)?.intValue
                ?? (detail["prompt_max_tokens"] as? NSNumber)?.intValue ?? 0
            let maxTokens = (detail["max_tokens"] as? NSNumber)?.intValue ?? 0
            return Entry(
                id: id,
                function: function,
                reasoning: (display["model_capability"] as? String) == "reasoning_model",
                contextWindow: max(0, window),
                maxTokens: max(0, maxTokens),
                efforts: (raw["reasoning"] as? [String: Any])?["supportedEfforts"] as? [String]
                    ?? detail["supported_efforts"] as? [String],
            )
        }
    }

    static func isHidden(_ id: String) -> Bool {
        if id.hasPrefix("custom_model_") || id.hasPrefix("search_agent") { return true }
        // The directory lists the agent's own internal entries beside the
        // models a user may pick; no user-facing id carries `agent` in it.
        if id.contains("agent") { return true }
        if id.contains("_advisor") || id.hasSuffix("_auto") { return true }
        for prefix in ["summary", "title_generation", "input_optimization", "fast_apply"] where id.hasPrefix(prefix) {
            return true
        }
        return id == "sagitta" || id == "aquila"
    }

    /// Each function is authoritative. A failed/partial reply throws instead
    /// of replacing the App's saved list with a silently truncated subset.
    /// Account-scoped caching belongs to SubscriptionCatalogCache, not here.
    static func roster(origin: String, token: TraeTokenStore.Token,
                       client: any KWWKAI.HTTPClient,
                       cancellation: KWWKAI.CancellationHandle? = nil) async throws -> [Entry] {
        guard origin == SubscriptionEndpoints.traeOrigin else {
            throw TraeError("Only the fixed domestic Trae directory host is allowed.")
        }
        let headers = clientHeaders().merging(accountHeaders(token: token.value, userID: token.userID,
            machineID: token.machineID, deviceID: token.deviceID)) { _, new in new }
        var seen: Set<String> = []
        var roster: [Entry] = []
        for function in directoryFunctions {
            try Task.checkCancellation()
            try cancellation?.throwIfCancelled()
            guard let request = directoryRequest(origin: origin, function: function, headers: headers),
                  let url = request.url else { throw TraeError("Invalid fixed Trae directory URL") }
            let (response, bytes) = try await client.stream(url: url, method: "POST",
                headers: request.allHTTPHeaderFields ?? [:], body: request.httpBody,
                cancellation: cancellation, timeoutSeconds: 12)
            let data = try await SubscriptionJSON.collect(bytes, limit: 4 * 1024 * 1024, cancellation: cancellation)
            guard response.statusCode == 200 else {
                var failure = KWWKAI.ProviderFailure.payload(try SubscriptionJSON.value(
                    (try? JSONSerialization.jsonObject(with: data)) ?? [:]), fallback: "Trae directory request failed")
                failure.httpStatus = response.statusCode
                throw failure
            }
            let rows = try SubscriptionDirectoryProtocol.traeRows(data)
            for entry in entries(in: ["config_info_list": rows], function: function) where seen.insert(entry.id).inserted {
                roster.append(entry)
            }
        }
        return roster
    }
}

// MARK: - Provider

/// Trae's chat, over `OpenAICompletionsProvider`: its frames are rewritten
/// into OpenAI chunks on the way through the client, so the body shaping and
/// the stream decoding stay kwwk's.
struct TraeProvider: KWWKAI.APIProvider {
    let api = "openai-completions"
    let site: TraeSite
    private let origin: String
    private let functions: [String: String]
    private let completions: KWWKAI.OpenAICompletionsProvider

    init(site: TraeSite, origin: String, functions: [String: String], client: any KWWKAI.HTTPClient) {
        self.site = site; self.origin = origin; self.functions = functions
        var headers = TraeWire.clientHeaders()
        headers["Accept"] = "text/event-stream"
        // The encoded model/baseURL or credential can never select a host.
        let url = TraeWire.chatURL(origin: SubscriptionEndpoints.traeOrigin)!
        completions = KWWKAI.OpenAICompletionsProvider(
            client: TraeChatClient(inner: client, functions: functions), defaultBaseURL: url, extraHeaders: headers,
            urlBuilder: { _, _, fallback in fallback })
    }

    func stream(model: KWWKAI.Model, context: KWWKAI.Context,
                options: KWWKAI.StreamOptions?) -> KWWKAI.AssistantMessageStream {
        let error: String?
        if site != .china || origin != SubscriptionEndpoints.traeOrigin {
            error = "Only the fixed Trae CN chat endpoint is enabled."
        } else if functions[model.id] == nil {
            error = "The account directory did not grant a function for this model."
        } else if SubscriptionMessageMapping.containsImages(context.messages) {
            error = "Trae CN is text-only; images cannot be silently removed."
        } else if options?.temperature != nil || options?.maxTokens != nil {
            error = "Trae CN wire does not accept temperature or max_tokens overrides."
        } else { error = nil }
        if let error {
            let (stream, continuation) = KWWKAI.AssistantMessageStream.makeStream()
            let failure = KWWKAI.ProviderFailure(message: error, providerCode: "invalid_argument")
            let message = KWWKAI.AssistantMessage(content: [], api: api, provider: "trae", model: model.id,
                stopReason: .error, errorMessage: error, failure: failure)
            continuation.push(.error(reason: .error, error: message)); continuation.end(message)
            return stream
        }
        return completions.stream(model: model, context: context, options: options)
    }
}

/// Trae's transport: passes the shaped body through and rewrites the frame
/// stream into the OpenAI one `OpenAICompletionsProvider` reads.
struct TraeChatClient: KWWKAI.HTTPClient {
    let inner: KWWKAI.HTTPClient
    let functions: [String: String]

    func stream(
        url: URL,
        method: String,
        headers: [String: String],
        body: Data?,
        cancellation: CancellationHandle?,
    ) async throws -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        try Task.checkCancellation()
        try cancellation?.throwIfCancelled()
        guard let body, var root = try JSONSerialization.jsonObject(with: body) as? [String: Any],
              let model = root["model"] as? String, let function = functions[model] else {
            throw TraeError("Trae request has no account-granted model route.")
        }
        try TraeWire.mending(&root, function: function)
        let encoded = try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
        let (response, upstream) = try await inner.stream(
            url: url,
            method: method,
            headers: headers,
            body: encoded,
            cancellation: cancellation,
        )
        // A refusal is kwwk's `ProviderFailure` to read, in the wire's own
        // shape; only a stream is rewritten.
        guard response.statusCode < 400 else { return (response, upstream) }
        return (response, Self.rewritten(upstream))
    }

    /// A cut stream is an error, never an invented successful `length` turn.
    /// In particular it cannot release partial tool arguments for execution.
    static func rewritten(_ upstream: AsyncThrowingStream<Data, Error>) -> AsyncThrowingStream<Data, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var ended = false
                do {
                    for try await message in KWWKAI.parseSSE(bytes: upstream) {
                        try Task.checkCancellation()
                        let data = message.data.trimmingCharacters(in: .whitespacesAndNewlines)
                        if data.isEmpty { continue }
                        if data == "[DONE]" { ended = true; break }
                        let frame = TraeWire.translated(event: message.event, data: data)
                        for line in frame.lines { continuation.yield(line) }
                        if frame.ends { ended = true }
                        if frame.failed || frame.finished { break }
                    }
                } catch { continuation.finish(throwing: error); return }
                if !ended {
                    continuation.yield(TraeWire.errorFrame("Trae stream ended before the completion frame."))
                }
                continuation.yield(TraeWire.doneFrame)
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

