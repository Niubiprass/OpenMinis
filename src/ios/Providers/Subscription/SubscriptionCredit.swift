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
    /// A definite business answer for today (already checked in, device used,
    /// not eligible). The automatic pass must not retry or remind again today.
    var terminal: Bool = false
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

    /// Only this explicit Trae business refusal is terminal for today. HTTP,
    /// transport, parsing and other business errors keep the normal retry path.
    static func traeCheckinRefusal(_ error: Error) -> SubscriptionCheckin? {
        guard let error = error as? SubscriptionBillingError, error.code == 9095 else { return nil }
        return SubscriptionCheckin(checkedIn: false, canClaim: false, reward: nil, note: error.message)
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
    /// [T-subscription-log] Credits and check-in had no logging at all.
    static let logger = AppLogger(category: "Subscription")

    static func elapsed(since start: Date) -> String {
        String(format: "%.2f", Date().timeIntervalSince(start))
    }

    struct Context: Sendable {
        /// Keychain slot of the account this result belongs to — the account id.
        let instanceId: String
        /// Owning provider instance, used for existence/ownership checks. A slot
        /// is not itself an instance, so the parent has to travel with it.
        let parentId: String
        let type: ProviderType
        let epoch: UUID
        let credentials: KWWKAI.OAuthCredentials
    }
    // Shared across open views, so a double tap cannot dispatch two claims.
    private static var claiming: Set<String> = []

    /// Billing for the instance's ACTIVE account. Used where no account was
    /// picked explicitly; the account list passes one instead.
    static func context(_ instance: ProviderInstance) async throws -> Context {
        guard let slot = instance.subscriptionActiveSlot else {
            throw SubscriptionBillingProtocol.fail("请先登录账号")
        }
        return try await context(instance, accountSlot: slot)
    }

    static func context(_ instance: ProviderInstance, accountSlot: String) async throws -> Context {
        guard instance.providerType.isDomesticSubscription, instance.credentialType == .oauth,
              instance.subscriptionAccountSlots.contains(accountSlot) else {
            throw SubscriptionBillingProtocol.fail("请先登录账号")
        }
        let epoch = SubscriptionOAuthManager.shared.accountEpoch(instanceId: accountSlot)
        let credentials = try await SubscriptionOAuthManager.shared.validCredentials(
            instanceId: accountSlot, type: instance.providerType)
        let context = Context(instanceId: accountSlot, parentId: instance.id,
                              type: instance.providerType, epoch: epoch, credentials: credentials)
        try requireCurrent(context)
        return context
    }
    static func requireCurrent(_ context: Context) throws {
        try Task.checkCancellation()
        guard let instance = ProviderConfigStore.shared.instance(for: context.parentId),
              instance.providerType == context.type, instance.credentialType == .oauth,
              instance.subscriptionAccountSlots.contains(context.instanceId),
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

    private static var statusTasks: [String: (id: UUID, day: String, task: Task<SubscriptionCheckin, Error>)] = [:]

    static func checkin(_ context: Context, forceRefresh: Bool = false) async throws -> SubscriptionCheckin {
        try requireCurrent(context)
        let key = SubscriptionCheckinLedger.key(context)
        if let cached = SubscriptionCheckinLedger.cachedStatus(key), cached.checkedIn || !forceRefresh {
            return cached
        }
        let requestDay = SubscriptionCheckinPolicy.day(Date())
        let id: UUID
        let task: Task<SubscriptionCheckin, Error>
        if let running = statusTasks[key], running.day == requestDay {
            id = running.id
            task = running.task
        } else {
            id = UUID()
            // The shared read is independent of any one waiter's cancellation.
            // Every waiter validates its own account and day before remembering.
            task = Task { @MainActor in
                do { return try await queryCheckin(context) }
                catch {
                    try requireCurrent(context)
                    guard context.type == .traeCN,
                          let refused = SubscriptionBillingProtocol.traeCheckinRefusal(error) else { throw error }
                    return refused
                }
            }
            statusTasks[key] = (id, requestDay, task)
        }
        defer { if statusTasks[key]?.id == id { statusTasks[key] = nil } }
        let value = try await task.value
        try requireCurrent(context)
        guard requestDay == SubscriptionCheckinPolicy.day(Date()) else { throw CancellationError() }
        SubscriptionCheckinLedger.remember(value, key: key, requestDay: requestDay)
        return value
    }

    private static func queryCheckin(_ context: Context) async throws -> SubscriptionCheckin {
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
    static func claim(_ context: Context, automatic: Bool = false) async throws -> ClaimResult {
        try requireCurrent(context)
        let key = SubscriptionCheckinLedger.key(context)
        if SubscriptionCheckinLedger.completed(key) { return .alreadyCheckedIn }
        guard claiming.insert(key).inserted else {
            throw SubscriptionBillingProtocol.fail("正在签到，请稍等")
        }
        defer { claiming.remove(key) }
        let requestDay = SubscriptionCheckinPolicy.day(Date())
        SubscriptionCheckinLedger.beginAttempt(key)
        // One fresh status query under the same lock for manual and automatic
        // paths. Cached completion above never dispatches another server request.
        let current = try await checkin(context)
        try requireCurrent(context)
        guard requestDay == SubscriptionCheckinPolicy.day(Date()) else { throw CancellationError() }
        if current.checkedIn {
            logger.info("check-in \(context.type.rawValue) already done today")
            return .alreadyCheckedIn
        }
        guard current.canClaim else {
            // "Device already used today" / "not eligible" is a definite answer
            // for today: remember it so the automatic pass stays quiet.
            let note = current.note ?? "当前账号暂不能签到"
            logger.info("check-in \(context.type.rawValue) not allowed today: \(note)")
            SubscriptionCheckinLedger.blocked(key, requestDay: requestDay, note: note)
            throw SubscriptionBillingError(message: note, terminal: true)
        }
        try requireCurrent(context)
        guard requestDay == SubscriptionCheckinPolicy.day(Date()) else { throw CancellationError() }
        if automatic {
            guard UIApplication.shared.applicationState == .active,
                  let parent = ProviderConfigStore.shared.instance(for: context.parentId),
                  parent.isEnabled, parent.subscriptionAutoCheckin else { throw CancellationError() }
        }
        let receipt: SubscriptionCheckinReceipt
        do {
            switch context.type {
            case .workBuddy:
                let root = try await post(context, host: "www.codebuddy.cn",
                    path: "/v2/billing/meter/daily-checkin", body: [:], mutation: true)
                receipt = try SubscriptionBillingProtocol.workBuddyClaim(root)
            case .traeCN:
                // Only use the identity recorded by this account's successful login.
                // A new/random id would misrepresent a device and bypass status.
                guard let device = TraeCredential(context.credentials).deviceID, !device.isEmpty else {
                    throw SubscriptionBillingProtocol.fail("登录信息缺少签到所需的设备标识，请重新登录")
                }
                let root = try await post(context, host: "api.trae.cn",
                    path: "/trae/api/v2/ug/checkin_credits/claim", body: [:], mutation: true)
                receipt = try SubscriptionBillingProtocol.traeClaim(root)
            default: throw SubscriptionBillingProtocol.fail("这个服务商不支持签到")
            }
        } catch {
            // 9095 is Trae's "this device already took part today" refusal: a
            // definite no for today, so remember it instead of nagging.
            try requireCurrent(context)
            guard requestDay == SubscriptionCheckinPolicy.day(Date()) else { throw CancellationError() }
            guard context.type == .traeCN,
                  let refused = SubscriptionBillingProtocol.traeCheckinRefusal(error) else {
                throw error
            }
            let note = refused.note ?? "此设备今天已参与签到"
            SubscriptionCheckinLedger.blocked(key, requestDay: requestDay, note: note)
            throw SubscriptionBillingError(message: note, terminal: true)
        }
        try requireCurrent(context)
        guard requestDay == SubscriptionCheckinPolicy.day(Date()) else { throw CancellationError() }
        SubscriptionCheckinLedger.confirmed(key, requestDay: requestDay, notify: true)
        logger.info("check-in \(context.type.rawValue) accepted granted=\(receipt.granted.map { String(format: "%.2f", $0) } ?? "-")")
        return .accepted(receipt)
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
        let started = Date()
        do {
            (response, data) = try await client.request(url: url, method: "POST", headers: headers,
                body: JSONSerialization.data(withJSONObject: body))
        } catch {
            try requireCurrent(context)
            // [T-subscription-log] Nothing in this module was ever logged, so a
            // failed check-in or credit read left no trace at all.
            Self.logger.warning("\(context.type.rawValue) \(path) failed after \(Self.elapsed(since: started))s: \(error.localizedDescription)")
            // Never replay a write whose reply was lost: it may have succeeded.
            throw SubscriptionBillingProtocol.fail(mutation
                ? "没收到签到结果，请先刷新状态确认，避免重复领取"
                : "查询失败，请检查网络后刷新")
        }
        Self.logger.info("\(context.type.rawValue) \(path) status=\(response.statusCode) took \(Self.elapsed(since: started))s")
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
