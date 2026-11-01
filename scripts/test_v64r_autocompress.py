from pathlib import Path
import os, re, shutil, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
policy = (root/'src/ios/Agent/Chat/ContextPolicy.swift').read_text()
vm = (root/'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
compaction = (root/'src/ios/Agent/Chat/AIChatViewModel+Compaction.swift').read_text()
ui = (root/'src/ios/Views/ContentView.swift').read_text()
assert 'AutoContextCompactionSettingsView()' in ui
assert 'AutoCompactionPreferences.enabledKey' in ui
assert 'AutoCompactionBudget.parse(text)' in ui
assert 'budgetCompactionTarget(before protectedRawId: String?)' in compaction
assert 'explicitRawAnchor: budgetOnly ? budgetTarget?.rawId : nil' in vm
assert 'agentHistory[..<start]' in compaction and 'guard pending.isEmpty else' in compaction
assert 'budgetCompactionMadeNoProgress = sizeAfter >= sizeBefore' in vm
branch = vm.split('budgetCompactionMadeNoProgress = sizeAfter >= sizeBefore',1)[1].split('} else {',1)[0]
assert 'continue' in branch and 'turnCount -= 1' in branch
assert 'if budgetCompactionMadeNoProgress { break }' not in vm
assert 'private var lastFooterReflowAt' in (root/'src/ios/Agent/MessageList/MessageListLayout.swift').read_text()
assert 'compactionQueueBlockedSessionId' in vm and 'guard !isQueueBlockedByCompaction' in vm
assert 'previousSummary: summary1' in compaction
assert '* 1.5' in policy
print('Automatic compression source contracts: PASS (not device tests)')
start = policy.index('struct AutoCompactionBudget {')
end = policy.index('// MARK: - Outbound context measurement', start)
body = policy[start:end]
checks = r'''
func check(_ condition: @autoclosure () -> Bool, _ name: String) {
    precondition(condition(), name)
}
let active = AutoCompactionBudget(enabled: true, tokens: 256_000)
check(active.threshold(window: 1_000_000) == 217_600, "85 percent")
check(!active.isReached(measured: 217_599, window: 1_000_000), "below")
check(active.isReached(measured: 217_600, window: 1_000_000), "boundary")
check(active.effectiveTokens(window: 64_000) == 64_000, "lower real cap wins")
check(active.threshold(window: 64_000) == 54_400, "lower cap threshold")
check(active.isReached(measured: 217_600, window: 0), "unknown real window uses soft budget")
check(!AutoCompactionBudget(enabled: false, tokens: 256_000).isReached(measured: Int.max, window: 64_000), "off")
check(AutoCompactionBudget.parse(" 256000 ") == 256_000, "trim")
for bad in ["", "-1", "NaN", "1.5", "1023", "9999999999999999999999999", String(AutoCompactionBudget.maximumTokens + 1)] {
    check(AutoCompactionBudget.parse(bad) == nil, "invalid \(bad)")
}
let domain = "OpenMinis-V64R-Tests-" + UUID().uuidString
let defaults = UserDefaults(suiteName: domain)!
defer { defaults.removePersistentDomain(forName: domain) }
let prefs = AutoCompactionPreferences(defaults: defaults)
check(!prefs.enabled && prefs.budgetTokens == 256_000, "old install defaults")
prefs.enabled = true
prefs.budgetTokens = 128_000
check(prefs.budget.isReached(measured: 108_800, window: 256_000), "saved")
defaults.set("NaN", forKey: AutoCompactionPreferences.budgetKey)
check(prefs.budgetTokens == 256_000, "bad persisted value")
print("Production Swift budget/preferences tests: PASS")
'''
if shutil.which('swift'):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)/'BudgetTests.swift'
        path.write_text('import Foundation\nextension String { func trimmed() -> String { trimmingCharacters(in: .whitespacesAndNewlines) } }\n'+body+'\n'+checks)
        subprocess.run(['swift',str(path)],check=True)
else:
    if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
        raise SystemExit('Swift is required in CI but not found')
    print('SKIP production Swift tests: no Swift here; mandatory on GitHub macOS')
