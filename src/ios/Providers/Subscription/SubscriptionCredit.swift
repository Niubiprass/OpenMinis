import CoreFoundation
import Foundation
import KWWKAI
import SwiftUI

// BEGIN SUBSCRIPTION_BILLING_PURE
// Adapted from LaoDing's MIT-licensed dsh-connect-trae/workbuddy.
// Exact source commits and license: docs/SUBSCRIPTION-BILLING-SOURCES.md.
struct SubscriptionCredit: Equatable, Sendable {
    let remaining: Double
    let total: Double
    let used: Double
    var generalRemaining: Double? = nil
    var workRemaining: Double? = nil
    var remainingFraction: Double { total > 0 ? min(1, max(0, remaining / total)) : 0 }
    var percent: Int { Int((remainingFraction * 100).rounded()) }
    var isLow: Bool { remainingFraction < 0.15 }

    static func text(_ value: Double) -> String {
        guard value.isFinite, value >= 0 else { return "—" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = value.rounded() == value ? 0 : 1
        return formatter.string(from: NSNumber(value: value)) ?? String(format: "%.1f", value)
    }
}

struct SubscriptionCheckin: Equatable, Sendable {
    let checkedIn: Bool
    let canClaim: Bool
    let reward: Double?
    var note: String? = nil
}

struct SubscriptionCheckinReceipt: Equatable, Sendable {
    // Only the claim response's actual grant; never the status's quoted reward.
    let granted: Double?
}

struct SubscriptionBillingError: LocalizedError, Sendable {
    let message: String
    var code: Int? = nil
    var errorDescription: String? { message }
}

enum SubscriptionBillingProtocol {
    static func fail(_ text: String) -> SubscriptionBillingError { .init(message: text) }
    static func number(_ raw: Any?) throws -> Double {
        let value: Double
        if let n = raw as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() {
            value = n.doubleValue
        } else if let text = raw as? String,
                  let n = Double(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
            value = n
        } else { throw fail("积分数据不完整，请稍后刷新") }
        guard value.isFinite, abs(value) <= 1e15 else { throw fail("积分数量无法识别") }
        return value
    }
    static func quantity(_ raw: Any?) throws -> Double {
        let value = try number(raw)
        guard value >= 0 else { throw fail("积分数量无法识别") }
        return value
    }
    static func flag(_ raw: Any?) -> Bool? {
        guard let n = raw as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }
        return n.boolValue
    }
    static func checked(_ root: [String: Any], wrapped: Bool, requireCode: Bool = true) throws -> [String: Any] {
        if let raw = root["code"] {
            let value = try number(raw)
            guard value.rounded() == value else { throw fail("服务返回了无法识别的状态") }
            let code = Int(value)
            if code != 0 {
                let text = code == 9095 ? "此设备今天已经参与签到" : "服务未接受本次请求（编号 \(code)）"
                throw SubscriptionBillingError(message: text, code: code)
            }
        } else if requireCode { throw fail("服务没有确认请求结果，请刷新状态") }
        if !wrapped { return root }
        guard let data = root["data"] as? [String: Any] else { throw fail("服务返回的数据不完整") }
        return data
    }

    static func workBuddyCredit(_ root: [String: Any]) throws -> SubscriptionCredit {
        let data = try checked(root, wrapped: true)
        guard let packages = data["Packages"] as? [[String: Any]] else {
            throw fail("没查到积分明细，请稍后刷新")
        }
        var total = 0.0, used = 0.0
        for pack in packages {
            total += try quantity(pack["CycleTotalCapacity"])
            used += try quantity(pack["CycleUsedCapacity"])
        }
        guard total.isFinite, used.isFinite else { throw fail("积分数量无法识别") }
        return SubscriptionCredit(remaining: max(0, total - used), total: total, used: used)
    }

    static func traeCredit(_ root: [String: Any]) throws -> SubscriptionCredit {
        let data = try checked(root, wrapped: false, requireCode: false)
        guard flag(data["is_dollar_usage_billing"]) != true,
              flag(data["is_credits_billing"]) != false else {
            throw fail("这个账号返回的是其他计费方式，不能当作积分显示")
        }
        guard let summary = data["usage_summary"] as? [String: Any] else {
            throw fail("没查到积分汇总，请稍后刷新")
        }
        let total = try quantity(summary["total_amount"])
        let used = try quantity(summary["consumed_amount"])
        var result = SubscriptionCredit(remaining: max(0, total - used), total: total, used: used)
        if let packs = data["user_entitlement_pack_list"] as? [[String: Any]], !packs.isEmpty {
            var general = 0.0, work = 0.0
            var complete = true
            for pack in packs {
                guard let base = pack["entitlement_base_info"] as? [String: Any],
                      let endpoint = try? number(base["available_endpoint"]),
                      endpoint == 0 || endpoint == 1,
                      let usage = pack["usage"] as? [String: Any] else { complete = false; break }
                let product = base["product_extra"] as? [String: Any]
                let extra = product?["package_extra"] as? [String: Any]
                let quota = extra?["quota"] as? [String: Any] ?? base["quota"] as? [String: Any]
                guard let limit = try? quantity(quota?["credits_limit"]),
                      let spent = try? quantity(usage["credits_amount"]) else { complete = false; break }
                if endpoint == 0 { general += max(0, limit - spent) }
                else { work += max(0, limit - spent) }
            }
            if complete, general.isFinite, work.isFinite {
                result.generalRemaining = general
                result.workRemaining = work
            }
        }
        return result
    }

    static func workBuddyStatus(_ root: [String: Any]) throws -> SubscriptionCheckin {
        let data = try checked(root, wrapped: true)
        guard let active = flag(data["active"]), let done = flag(data["today_checked_in"]) else {
            throw fail("没查到今天的签到状态")
        }
        let reward = try data["daily_credit"].map { try quantity($0) }
        return SubscriptionCheckin(checkedIn: done, canClaim: active && !done, reward: reward,
            note: !active && !done ? "当前账号暂不能签到" : nil)
    }

    static func traeStatus(_ root: [String: Any]) throws -> SubscriptionCheckin {
        let data = try checked(root, wrapped: false)
        guard let done = flag(data["checked_in"]) else { throw fail("没查到今天的签到状态") }
        let enabled = flag(data["enable"]) ?? true
        let deviceUsed = flag(data["did_checked_in"]) == true
        let base = try data["credits"].map { try quantity($0) }
        let extra = try data["extra_credits"].map { try quantity($0) } ?? 0
        let reward = base.map { $0 + extra }
        let note: String? = deviceUsed && !done ? "此设备今天已参与签到"
            : !enabled && !done ? "暂未满足签到条件" : nil
        return SubscriptionCheckin(checkedIn: done, canClaim: enabled && !done && !deviceUsed,
                                   reward: reward, note: note)
    }

    static func workBuddyClaim(_ root: [String: Any]) throws -> SubscriptionCheckinReceipt {
        let data = try checked(root, wrapped: true)
        return SubscriptionCheckinReceipt(granted: try data["credit"].map { try quantity($0) })
    }
    static func traeClaim(_ root: [String: Any]) throws -> SubscriptionCheckinReceipt {
        let data = try checked(root, wrapped: false)
        // This endpoint often confirms only code=0. A quoted daily reward is
        // not proof of the amount actually granted on a repeated request.
        let raw = data["gained_credits"] ?? data["credits_gained"]
        return SubscriptionCheckinReceipt(granted: try raw.map { try quantity($0) })
    }
}
// END SUBSCRIPTION_BILLING_PURE

@MainActor
enum SubscriptionCreditAPI {
    struct Context: Sendable {
        let instanceId: String
        let type: ProviderType
        let epoch: UUID
        let credentials: KWWKAI.OAuthCredentials
    }
    // Shared across open views, so a double tap cannot dispatch two claims.
    private static var claiming: Set<String> = []

    static func context(_ instance: ProviderInstance) async throws -> Context {
        guard instance.providerType.isDomesticSubscription, instance.credentialType == .oauth else {
            throw SubscriptionBillingProtocol.fail("请先登录账号")
        }
        let epoch = SubscriptionOAuthManager.shared.accountEpoch(instanceId: instance.id)
        let credentials = try await SubscriptionOAuthManager.shared.validCredentials(
            instanceId: instance.id, type: instance.providerType)
        let context = Context(instanceId: instance.id, type: instance.providerType, epoch: epoch, credentials: credentials)
        try requireCurrent(context)
        return context
    }
    static func requireCurrent(_ context: Context) throws {
        try Task.checkCancellation()
        guard let instance = ProviderConfigStore.shared.instance(for: context.instanceId),
              instance.providerType == context.type, instance.credentialType == .oauth,
              SubscriptionOAuthManager.shared.accountEpoch(instanceId: context.instanceId) == context.epoch,
              !ProviderKeychainHelper.oauthNeedsReauth(instanceId: context.instanceId),
              let current = ProviderKeychainHelper.loadOAuthToken(instanceId: context.instanceId, as: SubscriptionTokenStorage.self),
              current.provider == context.type.rawValue, current.credentials == context.credentials else {
            throw CancellationError()
        }
    }

    static func credit(_ context: Context) async throws -> SubscriptionCredit {
        switch context.type {
        case .workBuddy:
            // Preserve the previously integrated, no-/v2 summary route.
            let root = try await post(context, host: "copilot.tencent.com",
                path: "/billing/meter/get-user-resource-summary", body: [:])
            return try SubscriptionBillingProtocol.workBuddyCredit(root)
        case .traeCN:
            let root = try await post(context, host: "api.trae.cn",
                path: "/trae/api/v2/pay/web_user_ent_usage", body: ["require_usage": true])
            return try SubscriptionBillingProtocol.traeCredit(root)
        default: throw SubscriptionBillingProtocol.fail("这个服务商不支持此查询")
        }
    }

    static func checkin(_ context: Context) async throws -> SubscriptionCheckin {
        switch context.type {
        case .workBuddy:
            let root = try await post(context, host: "www.codebuddy.cn",
                path: "/v2/billing/meter/checkin-activity-status", body: [:])
            return try SubscriptionBillingProtocol.workBuddyStatus(root)
        case .traeCN:
            let root = try await post(context, host: "api.trae.cn",
                path: "/trae/api/v2/ug/checkin_credits/status", body: [:])
            return try SubscriptionBillingProtocol.traeStatus(root)
        default: throw SubscriptionBillingProtocol.fail("这个服务商不支持签到查询")
        }
    }

    enum ClaimResult {
        case alreadyCheckedIn
        case accepted(SubscriptionCheckinReceipt)
    }
    static func claim(_ context: Context) async throws -> ClaimResult {
        try requireCurrent(context)
        guard claiming.insert(context.instanceId).inserted else {
            throw SubscriptionBillingProtocol.fail("正在签到，请稍等")
        }
        defer { claiming.remove(context.instanceId) }
        // A fresh status read is mandatory even when the displayed row is old.
        let current = try await checkin(context)
        if current.checkedIn { return .alreadyCheckedIn }
        guard current.canClaim else {
            throw SubscriptionBillingProtocol.fail(current.note ?? "当前账号暂不能签到")
        }
        try requireCurrent(context)
        switch context.type {
        case .workBuddy:
            let root = try await post(context, host: "www.codebuddy.cn",
                path: "/v2/billing/meter/daily-checkin", body: [:], mutation: true)
            return .accepted(try SubscriptionBillingProtocol.workBuddyClaim(root))
        case .traeCN:
            // Only use the identity recorded by this account's successful login.
            // A new/random id would misrepresent a device and bypass status.
            guard let device = TraeCredential(context.credentials).deviceID, !device.isEmpty else {
                throw SubscriptionBillingProtocol.fail("登录信息缺少签到所需的设备标识，请重新登录")
            }
            let root = try await post(context, host: "api.trae.cn",
                path: "/trae/api/v2/ug/checkin_credits/claim", body: [:], mutation: true)
            return .accepted(try SubscriptionBillingProtocol.traeClaim(root))
        default: throw SubscriptionBillingProtocol.fail("这个服务商不支持签到")
        }
    }

    private static func post(_ context: Context, host: String, path: String,
                             body: [String: Any], mutation: Bool = false) async throws -> [String: Any] {
        try requireCurrent(context)
        let permitted = context.type == .workBuddy
            ? ["copilot.tencent.com", "www.codebuddy.cn"] : ["api.trae.cn"]
        guard permitted.contains(host), path.hasPrefix("/"), !path.hasPrefix("//"),
              let url = URL(string: "https://" + host + path) else {
            throw SubscriptionBillingProtocol.fail("积分服务地址不匹配")
        }
        var headers = ["Content-Type": "application/json", "Accept": "application/json"]
        if context.type == .workBuddy {
            headers["Authorization"] = "Bearer \(context.credentials.access)"
            headers["User-Agent"] = KWWKAI.WorkBuddyOAuth.userAgent
            headers["X-Product"] = "SaaS"
            headers["X-IDE-Type"] = "WorkBuddy"
            if host == "www.codebuddy.cn" {
                headers["X-Requested-With"] = "XMLHttpRequest"
                headers["X-CodeBuddy-Request"] = "1"
                headers["Origin"] = "https://www.codebuddy.cn"
                headers["Referer"] = "https://www.codebuddy.cn/"
            }
            for (name, value) in KWWKAI.WorkBuddyOAuth.accountHeaders(context.credentials, site: .china) {
                headers[name] = value
            }
        } else {
            headers["Authorization"] = "Cloud-IDE-JWT \(context.credentials.access)"
            headers["User-Agent"] = "Mozilla/5.0"
            headers["Origin"] = "https://www.trae.cn"
            headers["Referer"] = "https://www.trae.cn/"
            if let device = TraeCredential(context.credentials).deviceID { headers["x-device-id"] = device }
        }
        let client = SubscriptionHTTPClient(allowedHosts: [host], timeout: 15, maxResponseBytes: 1_048_576)
        let response: HTTPURLResponse, data: Data
        do {
            (response, data) = try await client.request(url: url, method: "POST", headers: headers,
                body: JSONSerialization.data(withJSONObject: body))
        } catch {
            try requireCurrent(context)
            // Never replay a write whose reply was lost: it may have succeeded.
            throw SubscriptionBillingProtocol.fail(mutation
                ? "没收到签到结果，请先刷新状态确认，避免重复领取"
                : "查询失败，请检查网络后刷新")
        }
        try requireCurrent(context)
        guard (200..<300).contains(response.statusCode) else {
            throw SubscriptionBillingError(message: "请求未完成（HTTP \(response.statusCode)），请刷新状态", code: response.statusCode)
        }
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SubscriptionBillingProtocol.fail(mutation
                ? "签到回复无法识别，请先刷新状态确认" : "查询回复无法识别，请稍后刷新")
        }
        return root
    }
}

/// Reuses the existing provider detail page's native Section and credit card.
/// Read-only refresh never claims; only the visible sign-in button can claim.
struct SubscriptionCreditSection: View {
    let instance: ProviderInstance
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var credit: SubscriptionCredit?
    @State private var checkin: SubscriptionCheckin?
    @State private var creditNote: String?
    @State private var checkinNote: String?
    @State private var claimNote: String?
    @State private var loading = false
    @State private var claiming = false
    @State private var loaded = false
    @State private var authenticated = false
    @State private var generation = UUID()
    @State private var context: SubscriptionCreditAPI.Context?
    @State private var task: Task<Void, Never>?

    private var tint: Color { credit?.isLow == true ? .orange : .green }
    private var busy: Bool { loading || claiming }
    private var statusText: String {
        guard authenticated else { return "登录后可签到" }
        guard let checkin else { return checkinNote ?? (loading ? "正在查询签到状态…" : "未查询签到状态") }
        if checkin.checkedIn { return "今日已签到" }
        return checkin.note ?? "今日未签到"
    }

    var body: some View {
        Group {
            if instance.providerType.isDomesticSubscription {
                Section {
                    creditContent
                    Button(loading ? "刷新中…" : "刷新积分与签到状态") { startRefresh() }
                        .disabled(busy || !authenticated)
                    HStack {
                        Text(statusText).foregroundStyle(.secondary)
                        Spacer(minLength: 8)
                        if claiming {
                            ProgressView().controlSize(.small)
                        } else if let checkin, authenticated, !checkin.checkedIn {
                            Button("签到领积分") { startClaim() }
                                .disabled(busy || !checkin.canClaim)
                        }
                    }
                    if let checkin, !checkin.checkedIn, let reward = checkin.reward, reward > 0 {
                        Text("今日可领 \(SubscriptionCredit.text(reward)) 积分")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if let checkinNote, checkin != nil {
                        Text(checkinNote).font(.caption).foregroundStyle(.secondary)
                    }
                    if let claimNote {
                        Text(claimNote).font(.footnote).foregroundStyle(.secondary)
                    }
                } header: {
                    Text("积分与签到")
                } footer: {
                    Text("只在点击签到时领取；领取后刷新积分。积分不足时，模型是否可用以服务商实际返回为准。")
                }
                .onAppear { if !loaded && !busy { startRefresh() } }
                .onDisappear { reset() }
                .onChange(of: store.authRevision) { _ in authenticationChanged() }
            }
        }
    }

    @ViewBuilder
    private var creditContent: some View {
        if let credit {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(SubscriptionCredit.text(credit.remaining))
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .minimumScaleFactor(0.6).lineLimit(1)
                    Text("/ \(SubscriptionCredit.text(credit.total))")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Spacer(minLength: 0)
                    Text("剩 \(credit.percent)%")
                        .font(.caption).fontWeight(.semibold).foregroundStyle(tint)
                }
                ProgressView(value: credit.remainingFraction).tint(tint)
                HStack {
                    Text("已用 \(SubscriptionCredit.text(credit.used))")
                    Spacer(minLength: 0)
                    if credit.isLow { Text("积分快用完了").foregroundStyle(.orange) }
                }.font(.caption).foregroundStyle(.secondary)
                if let general = credit.generalRemaining, let work = credit.workRemaining {
                    Text("通用积分 \(SubscriptionCredit.text(general)) · Work 专用 \(SubscriptionCredit.text(work))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.padding(.vertical, 4)
            if let creditNote { Text(creditNote).font(.caption).foregroundStyle(.secondary) }
        } else if loading {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("正在查询积分…").foregroundStyle(.secondary)
            }
        } else {
            Text(authenticated ? (creditNote ?? "积分尚未查询") : "登录后显示积分")
                .foregroundStyle(.secondary)
        }
    }

    @MainActor private func reset() {
        generation = UUID()
        task?.cancel(); task = nil
        credit = nil; checkin = nil; context = nil
        creditNote = nil; checkinNote = nil; claimNote = nil
        loading = false; claiming = false; loaded = false; authenticated = false
    }
    @MainActor private func authenticationChanged() {
        // Most auth notifications concern other providers. Do not query again
        // unless this card's account/credential actually moved.
        if let context, (try? SubscriptionCreditAPI.requireCurrent(context)) != nil { return }
        reset()
        startRefresh()
    }
    @MainActor private func startRefresh() {
        guard !busy else { return }
        authenticated = SubscriptionOAuthManager.shared.isAuthenticated(instanceId: instance.id, type: instance.providerType)
        guard authenticated else { loaded = true; return }
        loading = true
        claimNote = nil
        let request = generation
        task = Task { @MainActor in
            defer { if generation == request { loading = false; loaded = true } }
            do {
                let account = try await SubscriptionCreditAPI.context(instance)
                guard generation == request else { return }
                context = account
                await read(account, generation: request)
            } catch {
                guard generation == request else { return }
                credit = nil; checkin = nil
                creditNote = safeMessage(error); checkinNote = "签到状态未获取，请刷新后再试"
            }
        }
    }
    @MainActor private func read(_ account: SubscriptionCreditAPI.Context, generation request: UUID) async {
        // Independent outcomes: a broken check-in endpoint must not erase a
        // successfully fetched credit balance (or vice versa).
        do {
            let value = try await SubscriptionCreditAPI.credit(account)
            try SubscriptionCreditAPI.requireCurrent(account)
            guard generation == request else { return }
            credit = value; creditNote = nil
        } catch {
            guard generation == request else { return }
            credit = nil; creditNote = safeMessage(error)
        }
        do {
            let value = try await SubscriptionCreditAPI.checkin(account)
            try SubscriptionCreditAPI.requireCurrent(account)
            guard generation == request else { return }
            checkin = value; checkinNote = nil
        } catch {
            guard generation == request else { return }
            checkin = nil; checkinNote = safeMessage(error)
        }
    }
    @MainActor private func startClaim() {
        guard !busy, authenticated, checkin?.canClaim == true else { return }
        claiming = true
        claimNote = nil
        let request = generation
        task = Task { @MainActor in
            defer { if generation == request { claiming = false } }
            do {
                let account = try await SubscriptionCreditAPI.context(instance)
                context = account
                let outcome = try await SubscriptionCreditAPI.claim(account)
                try SubscriptionCreditAPI.requireCurrent(account)
                guard generation == request else { return }
                switch outcome {
                case .alreadyCheckedIn: claimNote = "今日已经签到，不会重复领取"
                case .accepted(let receipt):
                    if let granted = receipt.granted, granted > 0 {
                        claimNote = "签到成功，领取 \(SubscriptionCredit.text(granted)) 积分"
                    } else {
                        claimNote = "服务已接受签到，正在核对状态和积分"
                    }
                }
                checkin = nil
                await read(account, generation: request)
                if generation == request, case .accepted(let receipt) = outcome, receipt.granted == nil {
                    claimNote = checkin?.checkedIn == true
                        ? "签到成功，今日已签到"
                        : "服务已接受签到，到账结果还没查到，请稍后刷新确认"
                }
            } catch {
                guard generation == request else { return }
                claimNote = safeMessage(error)
                checkin = nil
                checkinNote = "请刷新签到状态后再试"
            }
        }
    }
    private func safeMessage(_ error: Error) -> String {
        if error is CancellationError { return "账号或页面已变化，请刷新后重试" }
        if let e = error as? SubscriptionBillingError { return e.message }
        if let e = error as? SubscriptionProviderError { return e.localizedDescription }
        return "请求未完成，请刷新状态后重试"
    }
}
