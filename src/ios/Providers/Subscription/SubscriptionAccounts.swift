import Foundation
import SwiftUI
// JSONValue cases are matched via the credential's own type; importing the
// defining module keeps that lookup explicit rather than relying on inference.
import KWWKAI

/// [T-subscription-multi-account] Account helpers for domestic subscriptions.
///
/// A WorkBuddy / Trae instance can hold several accounts. Each account lives in
/// its own Keychain slot and the slot id IS the account id, so the OAuth,
/// refresh and billing code keeps working per "instance" — it is simply handed
/// the slot instead of the provider instance.
///
/// Nothing here decides policy on its own: the ordered list, the active account
/// and the failover switch all live on the ProviderInstance itself, so a synced
/// peer sees exactly the same configuration.
struct SubscriptionAccountDescriptor: Identifiable, Hashable {
    let id: String            // Keychain slot == account id
    var label: String         // sign-in account name, or a positional fallback
    var isActive: Bool
    var hasCredential: Bool
    var needsReauth: Bool
}

enum SubscriptionAccounts {
    /// Stable vendor identity, not the access token (which rotates on renewal).
    /// Unknown identity remains slot-scoped; never merge by a display nickname.
    static func identity(_ token: SubscriptionTokenStorage) -> String? {
        let fields = token.provider == ProviderType.workBuddy.rawValue ? ["uid", "enterpriseId", "domain"] : ["userId"]
        guard let first = fields.first, case .string(let user)? = token.credentials.extras[first], !user.isEmpty else { return nil }
        return token.provider + ":" + fields.map { field in
            if case .string(let value)? = token.credentials.extras[field] { return "\(value.utf8.count):\(value)" }
            return "0:"
        }.joined(separator: "|")
    }

    static func usable(_ instance: ProviderInstance, slot: String) -> Bool {
        guard instance.subscriptionAccountSlots.contains(slot),
              !ProviderKeychainHelper.oauthNeedsReauth(instanceId: slot),
              let token = ProviderKeychainHelper.loadOAuthToken(instanceId: slot, as: SubscriptionTokenStorage.self)
        else { return false }
        return token.provider == instance.providerType.rawValue && !token.accessToken.isEmpty
    }

    @MainActor
    static func requestInstance(_ id: String) throws -> ProviderInstance {
        guard let instance = ProviderConfigStore.shared.instance(for: id), instance.isEnabled,
              instance.providerType.isDomesticSubscription else { throw LLMError.cancelled }
        return instance
    }

    static func descriptors(for instance: ProviderInstance) -> [SubscriptionAccountDescriptor] {
        let slots = instance.subscriptionAccountSlots
        let active = instance.subscriptionActiveSlot
        return slots.enumerated().map { index, slot in
            let stored = ProviderKeychainHelper.loadOAuthToken(
                instanceId: slot, as: SubscriptionTokenStorage.self)
            let matches = stored?.provider == instance.providerType.rawValue
            let token = matches ? stored : nil
            let name = token?.loginAccount?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return SubscriptionAccountDescriptor(
                id: slot,
                label: name.isEmpty ? String(format: AppLocalized("账号 %d"), index + 1) : name,
                isActive: slot == active,
                hasCredential: !(token?.accessToken.isEmpty ?? true),
                needsReauth: ProviderKeychainHelper.oauthNeedsReauth(instanceId: slot))
        }
    }

    /// Whether an error means "this account has no credits left" rather than
    /// "the request was wrong", "the login expired" or "the network broke".
    ///
    /// Deliberately narrow: automatic failover spends another account's quota,
    /// so a false positive is worse than a missed switch. Unknown wording is
    /// NOT treated as exhaustion — the turn just reports the provider's error.
    static func isQuotaExhausted(_ error: Error) -> Bool {
        guard let error = error as? LLMError,
              case .providerError(let message) = error else { return false }
        // Only canonical markers produced by SubscriptionFailure.map from a
        // typed quota failure or a verified provider code, not arbitrary prose.
        let text = message.lowercased()
        return text.hasPrefix("insufficient_quota：")
            || text.hasPrefix("quota_exhausted / insufficient_quota：")
    }
}

/// Login sheets are hosted on ProviderInstanceDetailView, not this List section.
struct SubscriptionAccountLoginRequest: Identifiable {
    let id = UUID()
    let slot: String
}

@MainActor
struct SubscriptionAccountsSection: View {
    let instance: ProviderInstance
    let onAdd: () -> Void
    let onReauthenticate: (String) -> Void
    let onRemove: (String) -> Void
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var accounts: [SubscriptionAccountDescriptor] = []

    var body: some View {
        Section {
            Toggle("额度不足自动换号", isOn: Binding(
                get: { instance.subscriptionAutoFailover },
                set: { store.setSubscriptionAutoFailover(instanceId: instance.id, enabled: $0) }))
            Toggle("启动时自动签到", isOn: Binding(
                get: { instance.subscriptionAutoCheckin },
                set: { store.setSubscriptionAutoCheckin(instanceId: instance.id, enabled: $0) }))
            ForEach(accounts) { account in
                SubscriptionAccountRow(instance: instance, account: account,
                    onReauthenticate: { onReauthenticate(account.id) },
                    onRemove: { onRemove(account.id) })
            }
            Button(action: onAdd) { Label("添加账号", systemImage: "plus.circle") }
                .buttonStyle(.borderless)
        } header: {
            Text("账号 · \(accounts.count)")
        } footer: {
            Text("模型只显示一套，积分按实际使用的账号扣除。自动换号只在明确额度不足且尚未开始回复时发生。签到完成后当天不再查询；未完成时每两小时重试并轻提示。")
        }
        .task(id: "\(store.authRevision)-\(store.configRevision)") {
            let snapshot = instance
            // Keychain reads for a handful of accounts; cheap enough to do on
            // the main actor and avoids sending a non-Sendable instance across.
            let value = SubscriptionAccounts.descriptors(for: snapshot)
            guard !Task.isCancelled,
                  store.instance(for: snapshot.id)?.subscriptionAccountSlots == snapshot.subscriptionAccountSlots else { return }
            accounts = value
        }
    }
}

@MainActor
private struct SubscriptionAccountRow: View {
    let instance: ProviderInstance
    let account: SubscriptionAccountDescriptor
    let onReauthenticate: () -> Void
    let onRemove: () -> Void
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var credit: SubscriptionCredit?
    @State private var checkin: SubscriptionCheckin?
    @State private var note: String?
    @State private var creditNote: String?
    @State private var loading = false
    @State private var claiming = false
    @State private var loaded = false
    @State private var expanded = false
    @State private var generation = UUID()
    @State private var context: SubscriptionCreditAPI.Context?
    @State private var task: Task<Void, Never>?

    private var authenticated: Bool { account.hasCredential && !account.needsReauth }
    private var summary: String {
        guard authenticated else { return account.needsReauth ? "登录已失效" : "尚未登录" }
        if let credit {
            return "\(SubscriptionCredit.text(credit.remaining)) / \(SubscriptionCredit.text(credit.total)) · 剩 \(credit.percent)%"
        }
        return loading ? "正在查询积分…" : creditNote ?? "积分尚未查询"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 8) {
                Circle().fill(authenticated ? Color.green : Color.gray).frame(width: 7, height: 7)
                Button { expanded.toggle() } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 5) {
                            Text(account.label).font(.body).lineLimit(1)
                            if account.isActive {
                                Text("当前").font(.caption2.weight(.semibold))
                                    .padding(.horizontal, 4).padding(.vertical, 2)
                                    .foregroundColor(.accentColor)
                                    .background(Color.accentColor.opacity(0.12))
                                    .cornerRadius(4)
                            }
                        }
                        Text(summary).font(.caption).foregroundColor(.secondary).lineLimit(1)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }.buttonStyle(.plain)
                if !account.isActive && authenticated {
                    Button("切换") { store.setActiveSubscriptionAccount(instanceId: instance.id, slot: account.id) }
                        .font(.caption).buttonStyle(.borderless)
                }
                if claiming {
                    ProgressView().controlSize(.small)
                } else if authenticated {
                    Button(checkin?.checkedIn == true ? "已签到" : "签到") { claim() }
                        .font(.caption).buttonStyle(.borderless)
                        .disabled(loading || checkin?.checkedIn == true || checkin?.canClaim == false)
                } else {
                    Button("登录", action: onReauthenticate).font(.caption).buttonStyle(.borderless)
                }
            }
            if let note { Text(note).font(.caption).foregroundColor(.secondary) }
            if expanded {
                if let credit {
                    ProgressView(value: credit.remainingFraction).tint(credit.isLow ? .orange : .green)
                    Text("已用 \(SubscriptionCredit.text(credit.used))").font(.caption).foregroundColor(.secondary)
                    if let general = credit.generalRemaining, let work = credit.workRemaining {
                        Text("通用积分 \(SubscriptionCredit.text(general)) · Work 专用 \(SubscriptionCredit.text(work))")
                            .font(.caption).foregroundColor(.secondary)
                    }
                }
                HStack {
                    Button("刷新") { refresh() }.disabled(loading || claiming || !authenticated)
                    Spacer()
                    Button("重新登录", action: onReauthenticate)
                    Spacer()
                    Button("退出", role: .destructive, action: onRemove)
                }.font(.caption).buttonStyle(.borderless)
            }
        }
        .padding(.vertical, 2)
        .onAppear { if !loaded { refresh() } }
        .onDisappear { reset() }
        .onChange(of: store.authRevision) { _ in authChanged() }
    }

    private func reset() {
        generation = UUID()
        task?.cancel(); task = nil
        credit = nil; checkin = nil; context = nil
        loading = false; claiming = false; loaded = false
        note = nil; creditNote = nil
    }

    private func authChanged() {
        if let context, (try? SubscriptionCreditAPI.requireCurrent(context)) != nil {
            if SubscriptionCheckinLedger.completed(SubscriptionCheckinLedger.key(context)) {
                checkin = SubscriptionCheckin(checkedIn: true, canClaim: false, reward: nil)
                note = nil
            }
            return
        }
        reset()
        refresh()
    }

    private func safeMessage(_ error: Error) -> String {
        if let billing = error as? SubscriptionBillingError { return billing.message }
        if error is CancellationError { return "账号状态已变化，请刷新" }
        return FriendlyErrorText.sanitize(error) ?? "查询未完成，请稍后刷新"
    }

    private func refresh() {
        guard !loading && !claiming else { return }
        guard authenticated else { loaded = true; return }
        loading = true
        note = nil
        let request = generation
        task = Task { @MainActor in
            defer { if generation == request { loading = false; loaded = true; task = nil } }
            do {
                let ctx = try await SubscriptionCreditAPI.context(instance, accountSlot: account.id)
                guard generation == request else { return }
                context = ctx
                await read(ctx, generation: request)
            } catch {
                guard generation == request else { return }
                creditNote = safeMessage(error)
            }
        }
    }

    private func read(_ ctx: SubscriptionCreditAPI.Context, generation request: UUID) async {
        do {
            let value = try await SubscriptionCreditAPI.credit(ctx)
            try SubscriptionCreditAPI.requireCurrent(ctx)
            guard generation == request else { return }
            credit = value; creditNote = nil
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            creditNote = safeMessage(error)
        }
        do {
            let value = try await SubscriptionCreditAPI.checkin(ctx)
            try SubscriptionCreditAPI.requireCurrent(ctx)
            guard generation == request else { return }
            checkin = value
            note = value.checkedIn ? nil : value.note
        } catch {
            guard generation == request, !Task.isCancelled else { return }
            note = safeMessage(error)
        }
    }

    private func claim() {
        guard !loading && !claiming && authenticated else { return }
        claiming = true
        note = nil
        let request = generation
        task = Task { @MainActor in
            defer { if generation == request { claiming = false; task = nil } }
            do {
                let ctx = try await SubscriptionCreditAPI.context(instance, accountSlot: account.id)
                guard generation == request else { return }
                context = ctx
                let result = try await SubscriptionCreditAPI.claim(ctx)
                try SubscriptionCreditAPI.requireCurrent(ctx)
                guard generation == request else { return }
                checkin = SubscriptionCheckin(checkedIn: true, canClaim: false, reward: nil)
                let key = SubscriptionCheckinLedger.key(ctx)
                if SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record(key), now: Date()) {
                    SubscriptionCheckinLedger.markNotified(key)
                    switch result {
                    case .alreadyCheckedIn: MinisToast.show("今日已签到")
                    case .accepted(let receipt):
                        MinisToast.show(receipt.granted.map { "签到成功，领到 \(SubscriptionCredit.text($0)) 积分" } ?? "签到成功")
                    }
                }
                // Refresh only the balance; completion is already confirmed.
                let value = try await SubscriptionCreditAPI.credit(ctx)
                try SubscriptionCreditAPI.requireCurrent(ctx)
                guard generation == request else { return }
                credit = value; creditNote = nil
            } catch {
                guard generation == request, !Task.isCancelled else { return }
                note = safeMessage(error)
            }
        }
    }
}
