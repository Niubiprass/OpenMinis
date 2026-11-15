// Compiled with the exact SUBSCRIPTION_BILLING_PURE production region.
var checks = 0
func check(_ value: @autoclosure () -> Bool, _ label: String) {
    precondition(value(), label); checks += 1
}
func rejects(_ label: String, _ body: () throws -> Void) {
    do { try body(); preconditionFailure(label) } catch { checks += 1 }
}
func json(_ value: String) -> [String: Any] {
    try! JSONSerialization.jsonObject(with: Data(value.utf8)) as! [String: Any]
}
let wb = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"code":0,"data":{"Packages":[{"CycleTotalCapacity":"3300","CycleUsedCapacity":"1458"},{"CycleTotalCapacity":200,"CycleUsedCapacity":25.25}]}}"#))
check(wb.total == 3500 && wb.used == 1483.25 && wb.remaining == 2016.75, "sum real packages")
check(wb.percent == 58 && !wb.isLow, "remaining percent")
let zero = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"code":0,"data":{"Packages":[]}}"#))
check(zero.total == 0 && zero.remaining == 0 && zero.percent == 0, "authoritative empty is zero")
let exhausted = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"code":0,"data":{"Packages":[{"CycleTotalCapacity":100,"CycleUsedCapacity":110}]}}"#))
check(exhausted.remaining == 0 && exhausted.isLow, "overspent clamps remaining")
rejects("missing envelope code") { _ = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"data":{"Packages":[]}}"#)) }
rejects("missing packages is unknown, not zero") { _ = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"code":0,"data":{}}"#)) }
rejects("half package") { _ = try SubscriptionBillingProtocol.workBuddyCredit(json(#"{"code":0,"data":{"Packages":[{"CycleTotalCapacity":100}]}}"#)) }
let invalidAmounts: [Any] = [true, NSNull(), "NaN", "Infinity", -1, "-10", "", ["x":1], 1e20]
for bad in invalidAmounts {
    rejects("invalid amount \(bad)") { _ = try SubscriptionBillingProtocol.quantity(bad) }
}
let stringCode = try SubscriptionBillingProtocol.number("0")
check(stringCode == 0, "string code")
rejects("fractional business code") { _ = try SubscriptionBillingProtocol.checked(json(#"{"code":0.1}"#), wrapped: false) }
rejects("business failure under HTTP 200") { _ = try SubscriptionBillingProtocol.traeClaim(json(#"{"code":9004}"#)) }
rejects("missing claim acknowledgment") { _ = try SubscriptionBillingProtocol.traeClaim([:]) }

let trae = try SubscriptionBillingProtocol.traeCredit(json(#"{"code":0,"is_credits_billing":true,"usage_summary":{"total_amount":7500,"consumed_amount":5879.63},"user_entitlement_pack_list":[{"entitlement_base_info":{"available_endpoint":1,"product_extra":{"package_extra":{"quota":{"credits_limit":2000}}}},"usage":{"credits_amount":2000}},{"entitlement_base_info":{"available_endpoint":0,"quota":{"credits_limit":200}},"usage":{"credits_amount":179.6288}}]}"#))
check(abs(trae.remaining - 1620.37) < 1e-8, "Trae total minus consumed")
check(trae.workRemaining == 0 && abs((trae.generalRemaining ?? 0) - 20.3712) < 1e-8, "endpoint buckets")
let noBuckets = try SubscriptionBillingProtocol.traeCredit(json(#"{"usage_summary":{"total_amount":100,"consumed_amount":0},"user_entitlement_pack_list":[{}]}"#))
check(noBuckets.remaining == 100 && noBuckets.generalRemaining == nil, "incomplete breakdown never pretends zero")
rejects("missing Trae summary") { _ = try SubscriptionBillingProtocol.traeCredit([:]) }
rejects("missing spent field") { _ = try SubscriptionBillingProtocol.traeCredit(json(#"{"usage_summary":{"total_amount":100}}"#)) }
rejects("USD is not credits") { _ = try SubscriptionBillingProtocol.traeCredit(json(#"{"is_dollar_usage_billing":true,"usage_summary":{"total_amount":100,"consumed_amount":0}}"#)) }

for (active, done) in [(true,false),(true,true),(false,false),(false,true)] {
    let status = try SubscriptionBillingProtocol.workBuddyStatus(["code":0,"data":["active":active,"today_checked_in":done,"daily_credit":100]])
    check(status.checkedIn == done && status.canClaim == (active && !done), "WorkBuddy claim gating")
}
for (done, enabled, deviceUsed) in [(false,true,false),(true,true,false),(false,false,false),(false,true,true)] {
    let status = try SubscriptionBillingProtocol.traeStatus(["code":0,"checked_in":done,"enable":enabled,"did_checked_in":deviceUsed,"credits":150,"extra_credits":50])
    check(status.checkedIn == done && status.canClaim == (enabled && !done && !deviceUsed), "Trae claim gating")
    check(status.reward == 200, "reported base plus bonus")
}
for enable in [NSNull(), "true", 1] as [Any] {
    let status = try SubscriptionBillingProtocol.traeStatus(["code":0,"checked_in":false,"enable":enable])
    check(status.eligibility == .unknown && !status.canClaim, "malformed enable stays unknown")
}
for payload in [["code":0], ["code":0,"checked_in":false], ["code":0,"enable":true]] as [[String: Any]] {
    let status = try SubscriptionBillingProtocol.traeStatus(payload)
    check(status.eligibility == .unknown && !status.checkedIn && !status.canClaim, "missing flags stay unknown")
}
let unknownWB = try SubscriptionBillingProtocol.workBuddyStatus(["code":0,"data":[:]])
check(unknownWB.eligibility == .unknown && !unknownWB.canClaim, "WorkBuddy missing flags unknown")
let inactive = try SubscriptionBillingProtocol.workBuddyStatus(["code":0,"data":["active":false]])
check(inactive.eligibility == .ineligible && !inactive.checkedIn, "explicit inactive is definitive without done")
let disabled = try SubscriptionBillingProtocol.traeStatus(["code":0,"enable":false])
check(disabled.eligibility == .ineligible && !disabled.checkedIn, "explicit disabled is definitive without done")
let malformedDevice = try SubscriptionBillingProtocol.traeStatus(["code":0,"enable":true,"checked_in":false,"did_checked_in":"false"])
check(malformedDevice.eligibility == .unknown && !malformedDevice.canClaim, "malformed device flag never permits claim")
let malformedReward = try SubscriptionBillingProtocol.traeStatus(["code":0,"enable":false,"checked_in":false,"credits":"bad"])
check(malformedReward.eligibility == .ineligible && malformedReward.reward == nil, "optional reward cannot erase ineligibility")
let doneWithoutEnable = try SubscriptionBillingProtocol.traeStatus(["code":0,"checked_in":true,"credits":"bad"])
check(doneWithoutEnable.checkedIn && !doneWithoutEnable.canClaim, "explicit completion survives missing eligibility/reward")
let optionalDevice = try SubscriptionBillingProtocol.traeStatus(["code":0,"checked_in":false,"enable":true])
check(optionalDevice.canClaim, "frozen tests permit absent optional device flag")
let noGrant = try SubscriptionBillingProtocol.traeClaim(["code":0,"credits":200])
check(noGrant.granted == nil, "quoted reward is not a grant")
let grant = try SubscriptionBillingProtocol.workBuddyClaim(["code":0,"data":["credit":100]])
check(grant.granted == 100, "only actual receipt grant shown")
let deviceNo = json(#"{"code":9095}"#)
do {
    _ = try SubscriptionBillingProtocol.traeClaim(deviceNo)
    preconditionFailure("device restriction must not be success")
} catch let e as SubscriptionBillingError {
    check(e.code == 9095, "device already used remains a refusal")
}
check(SubscriptionBillingProtocol.traeCheckinRefusal(SubscriptionBillingError(message: "untyped", code: 9095)) == nil,
      "9095 without business evidence is not a refusal")
check(!SubscriptionBillingError(message: "http", code: 503).businessRefusal, "HTTP code is not a business refusal")
print("subscription-billing-ok checks=\(checks)")
