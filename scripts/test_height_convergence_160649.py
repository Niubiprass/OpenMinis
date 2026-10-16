from pathlib import Path
root = Path(__file__).resolve().parents[1]
infra = (root/'src/ios/Agent/MessageList/MessageListInfrastructure.swift').read_text()

# 1) Gen guard captured BEFORE any hosting measure can reconfigure/reuse the cell.
assert 'let gen = configGeneration' in infra, 'configGeneration snapshot missing'
# 2) A cancelled/stale pass must return the untouched proposal, never an old host fit.
assert 'let unmeasuredAttributes = layoutAttributes.copy()' in infra, \
    'unmeasured proposal copy missing'
assert 'guard configGeneration == gen else { return unmeasuredAttributes }' in infra, \
    'stale-pass guard missing after super measure'
# 3) Broad cache-hit path must not fire while debt/surplus ripening is pending,
#    so a corrected height is not instantly overwritten by an older cached one.
assert '!v53DebtIsRipe, !v53SurplusIsRipe' in infra, \
    'cache-hit bypass during runnable debt/surplus missing'
# 4) The TextKit floor reconciliation still runs and is what wins.
assert 'fittingSize.height = _ios15Reconciled' in infra, 'TextKit reconcile write missing'
# 5) Memoisation happens only on the reconciled value (no pre-reconcile record).
memo = infra.split('recordMeasuredHeight(forKey:',1)
assert len(memo) == 2 and 'height: fittingSize.height' in memo[1], \
    'reconciled height memoisation missing'

print('Height convergence source contracts: PASS (not device tests)')
print('checks: gen-guard, unmeasured-proposal return, cache-hit debt/surplus gate, reconciled memo')