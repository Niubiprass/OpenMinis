#!/usr/bin/env python3
"""Static contracts for [T-multikey-quota-failover].

The user's report: 顺序优先 (priority) mode kept using the first key after it
ran out of balance instead of moving to the second key in the same request.

Asserts the production source keeps the three properties that make failover
work, and that the earlier "retry the same key twice whatever the error" and
"HTTP 429 always means throttle" paths are gone.

Source contracts only — this is NOT a Swift build and NOT device verification.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = (ROOT / "src/ios/Providers/ProviderMultiKeys.swift").read_text()
WRAP = (ROOT / "src/ios/Providers/AgentProvider.swift").read_text()
OPENAI = (ROOT / "src/ios/Providers/OpenAI/OpenAIProvider.swift").read_text()
GEMINI = (ROOT / "src/ios/Providers/Gemini/GeminiProvider.swift").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


# 1. Exhausted balance is recognised, in English and Chinese.
for token in ["insufficient_quota", "insufficient_user_quota", "billing_hard_limit_reached",
              "you exceeded your current quota", "余额不足", "欠费", "额度已用完"]:
    need(token in KEYS, "classifier recognises " + token)

# 2. A structured service error survives the HTTP envelope.
need("enum ProviderServiceError" in KEYS, "service-error decoder exists")
need("static func httpError(statusCode: Int, body: String) -> LLMError" in KEYS,
     "HTTP errors decode the body")
need("if statusCode == 429, MultiKeyFailureKind.classify(error) == .rateLimit { return .rateLimited }" in KEYS,
     "429 keeps throttle semantics unless the body proves otherwise")
need("OpenAIProvider" or True, "")
need("ProviderServiceError.httpError(statusCode: statusCode, body: body)" in OPENAI,
     "OpenAI 429 is no longer blindly rateLimited")
need("ProviderServiceError.httpError(statusCode: http.statusCode, body: body)" in GEMINI,
     "Gemini errors keep their body")
# HTTP 200 + structured SSE error must still fail the request.
need("enum ProviderServiceError" in KEYS and "static func streamError" in KEYS,
     "SSE error envelopes are decoded")
need("streamError(in: json)" in GEMINI, "Gemini checks 200-with-error")
need("streamError(in: event)" in OPENAI, "OpenAI checks 200-with-error")

# 3. The billing check must happen BEFORE the generic 429 downgrade, and the
#    per-minute wording must not be mistaken for debt.
quota_at = KEYS.find('"insufficient_quota"')
rate429_at = KEYS.find("if status == 429 { return .rateLimit }")
need(quota_at != -1 and rate429_at != -1 and quota_at < rate429_at,
     "billing wording is checked before the 429 fallback")
need('"per minute"' in KEYS and "shortWindow" in KEYS,
     "per-minute throttling is not treated as exhausted balance")

# 4. Only transient failures may re-use the same key in priority mode.
need("if kind == .transient, priorityRetries > 0, sameKeyRetries < priorityRetries" in WRAP,
     "same-key retry is limited to transient failures")
need("kind != .gatewayTimeout, priorityRetries > 0" not in WRAP,
     "the old retry-everything condition is gone")
need("guard kind.mayTryAnotherKey else { continuation.finish(throwing: error); return }" in WRAP,
     "non-credential failures still stop cleanly")

# 5. A same-key retry re-reads the live credential state (user may have deleted,
#    replaced or disabled it, or the cooldown may have started).
need("await manager.validatedRetryLeaseAsync(pending, for: instanceId)" in WRAP,
     "same-key retry revalidates identity/enabled/cooldown")
need("func validatedRetryLeaseAsync" in KEYS, "validator exists")
need("entry.isSelectable(recoveryInterval: Self.recoveryInterval)" in KEYS,
     "validator honours the cooldown")

# 6. Exhaustion parks the key for a while but never deletes it.
need("case .credential, .quota: return Self.recoveryInterval" in KEYS,
     "quota/credential park for the recovery interval only")
need("func recordFailure(lease: ProviderKeyLease, kind: MultiKeyFailureKind" in KEYS,
     "failure bookkeeping is still request-scoped")

# 7. Priority selection keeps list order and skips parked keys.
need("case .priority:" in KEYS and "return pool[0].lease" in KEYS,
     "priority still picks the first selectable key")
need("entry.isSelectable(recoveryInterval: Self.recoveryInterval, now: now)" in KEYS,
     "parked/disabled keys are skipped when leasing")

# 8. Returning an already-emitted answer on a second key stays forbidden.
need("if exposed {" in WRAP, "cannot splice a second answer after output")

if fails:
    print("❌ multikey quota failover contracts failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ multikey quota failover contracts passed")
print("   (static source contracts only: not compiled, not run on a device)")