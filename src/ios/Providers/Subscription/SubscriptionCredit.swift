import Foundation
import KWWKAI
import SwiftUI

/// One domestic subscription's credit summary.
///
/// WorkBuddy's own billing meter is the only source: it reports what the
/// account's packages grant this cycle and how much of it is spent. Nothing
/// here is derived from guesses — an account that grants nothing has no
/// summary and the UI says so.
struct SubscriptionCredit: Equatable, Sendable {
    let remaining: Double
    let total: Double
    let used: Double

    var remainingFraction: Double {
        guard total > 0 else { return 0 }
        return min(1, max(0, remaining / total))
    }
    var percent: Int { Int((remainingFraction * 100).rounded()) }
    /// The same 15% line the rest of the app uses for "running low".
    var isLow: Bool { remainingFraction < 0.15 }

    static func text(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = value.rounded() == value ? 0 : 1
        formatter.minimumFractionDigits = 0
        return formatter.string(from: NSNumber(value: value)) ?? String(Int(value))
    }
}

enum SubscriptionCreditAPI {
    /// `nil` when this provider publishes no credit figure at all, so the UI
    /// can say that instead of showing an error for a working account.
    static func fetch(instance: ProviderInstance) async throws -> SubscriptionCredit? {
        switch instance.providerType {
        case .workBuddy:
            let credentials = try await SubscriptionOAuthManager.shared.validCredentials(
                instanceId: instance.id, type: instance.providerType)
            return try await workBuddy(credentials)
        case .traeCN:
            return nil
        default:
            return nil
        }
    }

    /// `POST /billing/meter/get-user-resource-summary` — the meter
    /// WorkBuddy's desktop and web apps read. No `/v2` prefix.
    private static func workBuddy(_ credentials: KWWKAI.OAuthCredentials) async throws -> SubscriptionCredit {
        var headers = [
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": KWWKAI.WorkBuddyOAuth.userAgent,
            "X-Product": "SaaS",
            "X-IDE-Type": "WorkBuddy",
            "Authorization": "Bearer \(credentials.access)",
        ]
        for (name, value) in KWWKAI.WorkBuddyOAuth.accountHeaders(credentials, site: .china) {
            headers[name] = value
        }
        let client = SubscriptionHTTPClient(
            allowedHosts: SubscriptionEndpoints.workBuddyHosts, timeout: 15, maxResponseBytes: 1_048_576)
        let (response, data) = try await client.request(
            url: URL(string: "https://copilot.tencent.com/billing/meter/get-user-resource-summary")!,
            method: "POST",
            headers: headers,
            body: Data("{}".utf8))
        guard response.statusCode == 200 else {
            throw SubscriptionProviderError.invalidResponse("积分查询失败（HTTP \(response.statusCode)）")
        }
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw SubscriptionProviderError.invalidResponse("积分查询返回了无法识别的内容")
        }
        if let code = number(root["code"]), code != 0 {
            let said = root["msg"] as? String ?? "积分查询失败"
            throw SubscriptionProviderError.invalidResponse("\(said)（code \(Int(code))）")
        }
        let summary = root["data"] as? [String: Any] ?? [:]
        var total = 0.0
        var used = 0.0
        for package in summary["Packages"] as? [[String: Any]] ?? [] {
            total += try capacity(package["CycleTotalCapacity"])
            used += try capacity(package["CycleUsedCapacity"])
        }
        guard total > 0 else {
            throw SubscriptionProviderError.invalidResponse("这个账号本周期没有可用积分")
        }
        return SubscriptionCredit(remaining: max(0, total - used), total: total, used: used)
    }

    /// A capacity arrives as a JSON string ("3300", "438.88000002") and
    /// sometimes as a bare number; an empty one is zero.
    private static func capacity(_ value: Any?) throws -> Double {
        switch value {
        case nil, is NSNull: return 0
        case let number as NSNumber: return number.doubleValue
        case let text as String:
            let trimmed = text.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty { return 0 }
            guard let number = Double(trimmed), number.isFinite else {
                throw SubscriptionProviderError.invalidResponse("积分数量无法识别")
            }
            return number
        default:
            throw SubscriptionProviderError.invalidResponse("积分数量无法识别")
        }
    }

    private static func number(_ value: Any?) -> Double? {
        if let number = value as? NSNumber { return number.doubleValue }
        if let text = value as? String { return Double(text) }
        return nil
    }
}

/// The 积分 block on a subscription provider's detail page. It loads once when
/// the page appears and only queries again when the user asks: nothing in the
/// app spends a request on this behind their back.
struct SubscriptionCreditSection: View {
    let instance: ProviderInstance
    @State private var credit: SubscriptionCredit?
    @State private var loading = false
    @State private var message: String?
    @State private var loaded = false

    private var tint: Color {
        guard let credit else { return .secondary }
        return credit.isLow ? .orange : .green
    }

    var body: some View {
        Group {
            if instance.providerType == .workBuddy {
                Section {
                    Group {
                        if let credit {
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(alignment: .firstTextBaseline, spacing: 6) {
                                    Text(SubscriptionCredit.text(credit.remaining))
                                        .font(.system(size: 30, weight: .bold, design: .rounded))
                                    Text("/ \(SubscriptionCredit.text(credit.total))")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                    Spacer(minLength: 0)
                                    Text("剩 \(credit.percent)%")
                                        .font(.caption).fontWeight(.semibold)
                                        .foregroundStyle(tint)
                                }
                                ProgressView(value: credit.remainingFraction)
                                    .tint(tint)
                                HStack {
                                    Text("本轮已用 \(SubscriptionCredit.text(credit.used))")
                                    Spacer(minLength: 0)
                                    if credit.isLow { Text("积分快用完了").foregroundStyle(.orange) }
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 4)
                        } else if loading {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("正在查询积分…").foregroundStyle(.secondary)
                            }
                        } else {
                            Text(loaded ? (message ?? "没查到积分") : "登录后显示积分")
                                .foregroundStyle(.secondary)
                        }

                        Button(loading ? "查询中…" : "刷新积分") {
                            Task { await load(force: true) }
                        }
                        .disabled(loading)
                    }
                    .onAppear {
                        guard !loaded, !loading else { return }
                        Task { await load(force: false) }
                    }
                } header: {
                    Text("积分")
                } footer: {
                    Text("积分由服务商按你的账号计算；用它的模型就从这里扣，用完会被服务商拒绝。")
                }
            }
        }
    }

    @MainActor
    private func load(force: Bool) async {
        guard !loading else { return }
        if loaded && !force { return }
        loading = true
        message = nil
        defer { loading = false; loaded = true }
        do {
            credit = try await SubscriptionCreditAPI.fetch(instance: instance)
            if credit == nil { message = "该服务商不提供积分查询" }
        } catch {
            credit = nil
            message = (error as? LocalizedError)?.errorDescription ?? "没查到积分"
        }
    }
}
