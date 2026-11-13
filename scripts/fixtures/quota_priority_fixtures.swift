import Foundation

// Production `RelayQuotaProtocol` and `QuotaInfo` projection are concatenated
// above this fixture. No network, keys or iOS services are involved.

func check(_ condition: Bool, _ message: String) {
    if !condition {
        print("FAIL: \(message)")
        exit(1)
    }
}

let now = Date()

func reading(_ source: RelayQuotaProtocol.Source,
             _ scope: RelayQuotaProtocol.Scope,
             remaining: Double? = nil,
             used: Double? = nil,
             total: Double? = nil,
             unlimited: Bool = false,
             rejected: Bool = false) -> RelayQuotaProtocol.Reading {
    RelayQuotaProtocol.Reading(source: source,
        scope: scope,
        endpoint: "/probe",
        relayHost: "relay.example",
        unit: .currency("USD"),
        unitEvidence: "usd",
        quotaPerUnit: nil,
        scaleObservedAt: nil,
        remaining: remaining,
        used: used,
        total: total,
        unlimited: unlimited,
        rejected: rejected,
        observedAt: now)
}

// A real account wallet must win over a Key's spent usage.
let wallet = reading(.newAPIAccount, .accountBalance, remaining: 12.5, used: 3)
let keyUsage = reading(.newAPIKey, .keyQuota, used: 4)
let plan = reading(.sub2api, .subscription, remaining: 40, total: 50)
let primary = RelayQuotaProtocol.Snapshot.primary(in: [keyUsage, wallet, plan])
check(primary?.scope == .accountBalance, "account balance outranks usage")
check(primary?.remaining == 12.5, "the balance amount is not rewritten")

// Usage-only readings never claim to be a balance.
let usageOnly = RelayQuotaProtocol.Snapshot.primary(in: [keyUsage])
check(usageOnly?.scope == .keyQuota && usageOnly?.remaining == nil, "usage-only stays usage")
let unlimited = RelayQuotaProtocol.Snapshot.primary(in: [reading(.newAPIKey, .keyQuota, unlimited: true)])
check(unlimited?.unlimited == true && unlimited?.remaining == nil, "unlimited is not zero balance")

// A rejected key is never presented as a healthy primary.
let rejected = RelayQuotaProtocol.Snapshot.primary(in: [
    reading(.newAPIKey, .keyQuota, remaining: 9, rejected: true),
    reading(.openAIBilling, .accountBalance, remaining: 1),
])
check(rejected?.scope == .accountBalance, "rejected reading cannot outrank a real balance")

// Projection keeps every reading; only the primary drives the big number.
let snapshot = RelayQuotaProtocol.Snapshot(owner: "fixture",
    readings: [wallet, keyUsage, plan],
    attempts: [RelayQuotaProtocol.Attempt(source: .newAPIKey, endpoint: "/api/usage/token/",
        attemptedAt: now, succeeded: false, failureNote: "Key 额度接口返回 HTTP 503")])
let projected = Projection.project(snapshot)!
check(projected.kind == .balance && projected.balanceUSD == 12.5, "primary balance projected")
check(projected.readings.count == 3, "a failed probe does not discard other readings")
check(projected.secondaryText?.contains("Key 额度") == true, "secondary pool is labelled")
check(projected.secondaryText?.contains("账户余额") == false, "primary amount is not repeated")
check(projected.failureText?.contains("HTTP 503") == true, "failure reason is surfaced")

// Missing usage stays unknown instead of becoming a zero spend.
let noUsage = RelayQuotaProtocol.Snapshot.primary(in: [reading(.openAIBilling, .spendingLimit, total: 100)])
check(noUsage?.used == nil && noUsage?.remaining == nil, "cap without usage is not spent-zero")

print("quota-priority-ok")
