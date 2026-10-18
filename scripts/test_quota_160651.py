#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests: [T-115-quota] 额度与余额一目了然 (App Store 1.15).

Official spec: supported providers show remaining quota/balance (Claude &
ChatGPT subscription limits) in the model picker, the provider page and the
input field; the model dot turns yellow when quota is low. Data source is
the OpenAI /v1/dashboard/billing/* pair (same as the official Android
port); Anthropic shows month spend. Unsupported hosts show nothing.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


print("== [T-115-quota] contract tests ==")

q_path = ROOT / "src/ios/Providers/ProviderQuotaService.swift"
check("ProviderQuotaService.swift exists", q_path.exists())
q = q_path.read_text(encoding="utf-8", errors="replace") if q_path.exists() else ""

# 1) Service shape
check("ObservableObject + revision", "@Published private(set) var revision" in q)
check("sync cached read for UI", "func cachedQuota(instanceId:" in q)
check("missing/stale gate", "func isMissing(instanceId:" in q)
check("batch refresh", "func refreshAllIfNeeded(instances:" in q)
check("5-minute TTL", "let ttl: TimeInterval = 300" in q)
check("API-key instances only", "case .apiKey:" in q and "keychain" in q.lower() or "loadAPIKey" in q)

# 2) Data source = OpenAI billing endpoints
check("subscription endpoint", '"/dashboard/billing/subscription"' in q)
check("usage endpoint", '"/dashboard/billing/usage"' in q)
check("usage is in cents (/100)", "/ 100.0" in q)
check("hard/soft limit parsing", 'obj["hard_limit_usd"]' in q)
check("usage failure does not become zero usage", "guard let totalUsed else { return nil }" in q)
check("numeric usage accepts NSNumber", 'obj["total_usage"] as? NSNumber' in q)
check("low-quota rule (<15% or <$3)", "remaining < 3.0" in q and "* 0.15" in q)
check("Anthropic starts at current month", "monthComponents.day = 1" in q)
check("Anthropic month spend path", '"/organizations/usage/costs"' in q)
check("unsupported hosts return nil", "default: return nil" in q)

# 3) UI site 1: model picker rows
picker = read("src/ios/Views/Providers/UnifiedModelPicker.swift")
check("picker observes quota service", "quotaService = ProviderQuotaService.shared" in picker)
check("picker warms quota onAppear", "quotaService.refreshAllIfNeeded(instances: store.instances)" in picker)
check("picker row shows quota pill", re.search(r"cachedQuota\(instanceId: inst\.id\)[\s\S]{0,200}?Text\(q\.displayText\)", picker) is not None)
check("picker pill yellow when low", "q.highlighted ? Color.yellow" in picker)

# 4) UI site 2: provider page rows
prov = read("src/ios/Views/Providers/ProviderInstancesView.swift")
check("provider page observes quota service", "quotaService = ProviderQuotaService.shared" in prov)
check("provider page dot yellow when low", "quota?.highlighted == true ? Color.yellow" in prov)
check("provider page row pill", re.search(r"if let quota \{[\s\S]{0,150}?Text\(quota\.displayText\)", prov) is not None)
check("provider row refresh onAppear", "quotaService.refreshAllIfNeeded(instances: [instance])" in prov)

# 5) UI site 3: input-field model capsule
cv = read("src/ios/Views/Chat/AIChatView.swift")
check("chat observes quota service", "quotaService = ProviderQuotaService.shared" in cv)
check("capsule dot yellow when low", "quotaInfo?.highlighted == true" in cv)
check("capsule shows quota text", re.search(r"if let quotaText = quotaInfo\?\.displayText", cv) is not None)
check("chat warms quota onAppear", "quotaService.refreshAllIfNeeded(instances: [inst])" in cv)

# 6) Safety
check("no hardcoded secret handling", "print" not in q or "Keychain" in q)
check("no iOS16-only API", "navigationDestination" not in q)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL PASS")