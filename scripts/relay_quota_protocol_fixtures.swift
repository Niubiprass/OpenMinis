// Compiled together with the actual Foundation-only production protocol.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

typealias Q = RelayQuotaProtocol
let now = Date(timeIntervalSince1970: 1_800_000_000)
let root = "https://relay.invalid/prefix"
func data(_ s: String) -> Data { Data(s.utf8) }
var count = 0
func check(_ test: @autoclosure () -> Bool, _ message: String) {
    precondition(test(), message); count += 1
}
func rejects(_ message: String, _ fn: () throws -> Void) {
    do { try fn(); preconditionFailure(message) } catch { count += 1 }
}
let wallet = try Q.parseSub2API(data(#"{"isValid":true,"balance":"0","usage":{"total":{"actual_cost":"4.2"}}}"#), root: root, now: now)
check(wallet.count == 2, "wallet and key spend are separate")
check(wallet[0].scope == .accountBalance && wallet[0].remaining == 0, "real zero preserved")
check(wallet[0].used == nil && wallet[1].used == 4.2, "key spend not account spend")
check(wallet[0].unit.isUSD && wallet[0].endpoint == root + "/v1/usage", "documented USD and endpoint")
let limited = try Q.parseSub2API(data(#"{"isValid":true,"mode":"quota_limited","quota":{"limit":"20","used":"2","remaining":"18"}}"#), root: root, now: now)
check(limited[0].scope == .keyQuota && limited[0].total == 20 && limited[0].remaining == 18, "limited key")
let plan = try Q.parseSub2API(data(#"{"isValid":true,"remaining":12,"usage":{"total":{"actual_cost":3}}}"#), root: root, now: now)
check(plan[0].scope == .subscription && plan[0].remaining == 12, "subscription")
check(plan[0].usedLabel?.contains("非套餐") == true, "usage scope is explicit")
let unlimited = try Q.parseSub2API(data(#"{"isValid":true,"remaining":-1}"#), root: root, now: now)
check(unlimited[0].unlimited && unlimited[0].remaining == nil && unlimited[0].used == nil, "unlimited not zero")
let rejected = try Q.parseSub2API(data(#"{"isValid":false,"balance":100}"#), root: root, now: now)
check(rejected[0].rejected, "isValid false is rejected")
rejects("numeric isValid not boolean") { _ = try Q.parseSub2API(data(#"{"isValid":1,"balance":1}"#), root: root, now: now) }
rejects("absent amounts not zero") { _ = try Q.parseSub2API(data(#"{"isValid":true}"#), root: root, now: now) }
rejects("negative unknown plan sentinel") { _ = try Q.parseSub2API(data(#"{"isValid":true,"remaining":-2}"#), root: root, now: now) }
rejects("HTML not quota") { _ = try Q.parseSub2API(data("<html>login</html>"), root: root, now: now) }
for raw: Any in [true, "NaN", "Infinity", "12USD", "1..2", "1e999", "", NSNull()] {
    check(Q.number(raw) == nil, "malformed amount \(raw)")
}
check(Q.number("1.25e2") == 125, "strict numeric strings")
check(Q.number(NSNumber(value: 0)) == 0, "NSNumber zero")
check(Q.boolean(NSNumber(value: 1)) == nil, "NSNumber one not Bool")
let scale = Q.scale(data(#"{"data":{"quota_per_unit":"500000","usd_exchange_rate":7.2}}"#), root: root, now: now)
check(scale?.quotaPerUnit == 500000 && scale?.observedAt == now, "explicit scale")
check(Q.scale(data(#"{"data":{}}"#), root: root, now: now) == nil, "missing scale not 500000")
check(Q.scale(data(#"{"data":{"quota_per_unit":0}}"#), root: root, now: now) == nil, "invalid scale")
let tokenData = data(#"{"success":true,"data":{"total_granted":1000000,"total_used":250000,"total_available":750000}}"#)
let rawToken = try Q.parseNewAPI(tokenData, root: root, now: now, scale: nil)[0]
let usdToken = try Q.parseNewAPI(tokenData, root: root, now: now, scale: scale)[0]
check(rawToken.scope == .keyQuota && rawToken.unit == .quota && rawToken.remaining == 750000, "token endpoint is quota")
check(usdToken.remaining == 1.5 && usdToken.unit.isUSD && usdToken.scaleObservedAt == now, "site rate evidence")
let unlimitedToken = try Q.parseNewAPI(data(#"{"data":{"total_granted":-1,"total_available":-1}}"#), root: root, now: now, scale: nil)[0]
check(unlimitedToken.unlimited && unlimitedToken.used == nil && unlimitedToken.remaining == nil, "unlimited used absent stays absent")
let derived = try Q.parseNewAPI(data(#"{"data":{"total_granted":10,"total_used":2}}"#), root: root, now: now, scale: nil)[0]
check(derived.remaining == 8, "derive only from two known values")
let noUsage = try Q.parseNewAPI(data(#"{"data":{"total_granted":10}}"#), root: root, now: now, scale: nil)[0]
check(noUsage.remaining == nil && noUsage.used == nil && noUsage.total == 10, "missing usage not zero")
rejects("success false rejected") { _ = try Q.parseNewAPI(data(#"{"success":false,"data":{"total_available":10}}"#), root: root, now: now, scale: nil) }
let account = try Q.parseAccount(data(#"{"data":{"quota":1000000,"used_quota":250000}}"#), root: root, now: now, scale: scale)[0]
check(account.scope == .accountBalance && account.remaining == 2 && account.used == 0.5, "account ledger")
let rawAccount = try Q.parseAccount(data(#"{"quota":42}"#), root: root, now: now, scale: nil)[0]
check(rawAccount.unit == .quota && rawAccount.remaining == 42, "account unknown scale also raw")
let billing = try Q.parseBilling(data(#"{"data":{"hard_limit_usd":"20"}}"#), usage: data(#"{"total_usage":250}"#), root: root, now: now)[0]
check(billing.total == 20 && billing.used == 2.5 && billing.remaining == 17.5, "billing cents")
check(billing.scope == .spendingLimit, "cap is not account wallet")
let capOnly = try Q.parseBilling(data(#"{"hard_limit_usd":20}"#), usage: nil, root: root, now: now)[0]
check(capOnly.remaining == nil && capOnly.total == 20, "failed usage no invented balance")
let fakeCap = try Q.parseBilling(data(#"{"hard_limit_usd":100000000}"#), usage: data(#"{"total_usage":0}"#), root: root, now: now)[0]
check(fakeCap.unlimited && fakeCap.remaining == nil && fakeCap.used == 0, "placeholder never becomes huge balance")
rejects("generic balance lacks USD evidence") { _ = try Q.parseBilling(data(#"{"balance":12}"#), usage: nil, root: root, now: now) }
let usdBalance = try Q.parseBilling(data(#"{"balance":12,"currency":"USD"}"#), usage: nil, root: root, now: now)[0]
check(usdBalance.scope == .accountBalance && usdBalance.remaining == 12, "explicit USD evidence")
rejects("Anthropic missing usd is unknown") { _ = try Q.parseAnthropic(data(#"{"cost_breakdown":{"samples":[{"cost":{}}]}}"#), root: root, now: now) }
let zeroSpend = try Q.parseAnthropic(data(#"{"cost_breakdown":{"samples":[{"cost":{"usd":0}}]}}"#), root: root, now: now)[0]
check(zeroSpend.used == 0, "real zero spend survives")

check(Q.root(" https://relay.invalid/prefix/V1/// ") == root, "normalize trailing slash and v1")
for bad in ["file:///tmp/a", "https://user:secret@relay.invalid", "https://relay.invalid?x=y", "https://relay.invalid/#x"] {
    check(Q.root(bad) == nil, "invalid URL rejected")
}
let chat = try Q.request(root: root, source: .sub2api, chatKey: "fixture-chat", accountToken: "fixture-management", userID: "99")
check(chat.value(forHTTPHeaderField: "Authorization") == "Bearer fixture-chat", "chat key only")
check(chat.value(forHTTPHeaderField: "New-Api-User") == nil && !chat.httpShouldHandleCookies, "no account identity on chat request")
let management = try Q.request(root: "https://panel.invalid", source: .newAPIAccount, chatKey: "fixture-chat", accountToken: "fixture-management", userID: "99")
check(management.url?.absoluteString == "https://panel.invalid/api/user/self", "explicit panel only")
check(management.value(forHTTPHeaderField: "Authorization") == "Bearer fixture-management", "management token retained")
check(management.value(forHTTPHeaderField: "New-Api-User") == "99", "management user id retained")
rejects("chat key must not substitute account token") { _ = try Q.request(root: root, source: .newAPIAccount, chatKey: "fixture-chat", accountToken: nil, userID: "99") }
rejects("management token requires user id") { _ = try Q.request(root: root, source: .newAPIAccount, chatKey: "fixture-chat", accountToken: "fixture-management", userID: nil) }
let cookieReq = try Q.request(root: root, source: .newAPIAccount, chatKey: "fixture-chat", accountToken: nil, userID: nil, cookie: "fixture=1")
check(cookieReq.value(forHTTPHeaderField: "Authorization") == nil && cookieReq.value(forHTTPHeaderField: "Cookie") == "fixture=1", "cookie legacy auth remains isolated")
let combined = Q.Snapshot(owner: "owner-a", readings: [account, usdToken], attempts: [
    .init(source: .newAPIAccount, endpoint: account.endpoint, attemptedAt: now, succeeded: true, failureNote: nil),
    .init(source: .newAPIKey, endpoint: usdToken.endpoint, attemptedAt: now, succeeded: true, failureNote: nil)])
check(combined.readings.count == 2 && combined.primary?.remaining == 2, "account wins primary without summing")
check(combined.isLow(thresholdUSD: 1.75, now: now), "low key cannot hide behind account")
check(!combined.isLow(thresholdUSD: 1.0, now: now), "configured threshold only")
check(!combined.isLow(thresholdUSD: 3, now: now.addingTimeInterval(301)), "stale figures don't raise fresh low warning")
let rawSnapshot = Q.Snapshot(owner: "owner-a", readings: [rawToken], attempts: [])
check(!rawSnapshot.isLow(thresholdUSD: 1_000_000, now: now), "unknown unit not compared with USD")
let failedAt = now.addingTimeInterval(120)
let failed = Q.Snapshot(owner: "owner-a", readings: [], attempts: [
    .init(source: .newAPIAccount, endpoint: account.endpoint, attemptedAt: failedAt, succeeded: false, failureNote: "fixture failure")])
let retained = failed.merging(previous: combined)
check(retained.readings.count == 2 && retained.readings[0].remaining == 2, "failure retains amounts")
check(retained.readings[0].observedAt == now && retained.lastAttemptAt == failedAt, "failed attempt never rewrites observed time")
check(retained.readings.allSatisfy(\.refreshFailed), "retained values marked stale")
let foreign = Q.Snapshot(owner: "owner-b", readings: [], attempts: failed.attempts).merging(previous: combined)
check(foreign.readings.isEmpty, "changed credentials can't inherit old account")
let changedFamily = Q.Snapshot(owner: "owner-a", readings: plan, attempts: [
    .init(source: .sub2api, endpoint: root + "/v1/usage", attemptedAt: failedAt, succeeded: true, failureNote: nil)]).merging(previous: combined)
check(changedFamily.readings.count == 2 && !changedFamily.readings.contains { $0.source == .newAPIKey }, "new authoritative family retires old key protocol only")
check(changedFamily.readings.contains { $0.source == .newAPIAccount && $0.refreshFailed }, "independent account remains stale")
let oldWallet = Q.Snapshot(owner: "owner-a", readings: wallet, attempts: [])
let switched = Q.Snapshot(owner: "owner-a", readings: plan, attempts: changedFamily.attempts).merging(previous: oldWallet)
check(switched.readings.count == 1 && switched.readings[0].scope == .subscription, "wallet-to-plan replacement")
print("RelayQuotaProtocol Foundation fixtures PASS: \(count)")
