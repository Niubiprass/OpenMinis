#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / 'src/ios'

def read(rel):
    return (IOS / rel).read_text()

def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    return cond

fallback = read('Agent/Chat/AIChatViewModel+Fallback.swift')
network = read('Shared/NetworkMonitor.swift')
error = read('Providers/LLMError.swift')
keys = read('Providers/ProviderMultiKeys.swift')
agent = read('Providers/AgentProvider.swift')
openai = read('Providers/OpenAI/OpenAIProvider.swift')
oai = read('Providers/OpenAI/OpenAIAgentProvider.swift')
gate = read('Agent/Chat/SessionWorkflowGate.swift')
vm = read('Agent/Chat/AIChatViewModel.swift')
workflow = (ROOT / '.github/workflows/ios15-v64-repair.yml').read_text()
localizable = json.loads((IOS / 'Localizable.xcstrings').read_text())

checks = []
checks += [
    check('path generation exists', 'pathGeneration' in network and 'pathSnapshot()' in network),
    check('active interface uses usesInterfaceType', 'usesInterfaceType' in network),
    check('connection pools evict on path transition', 'evictAllConnections' in network and 'satisfactionChanged' in network),
    check('network retry keeps entry identity', 'networkEntryId' in fallback and 'retryEntryId' in fallback),
    check('network success requires visible progress', 'networkObservedStream' in fallback and 'observedProgress' in fallback),
    check('network failures are not key failures', 'kind != .network' in keys and 'diagnostic-only' in keys),
    check('error taxonomy separates 401/403/408/524/413', all(x in keys for x in ['case .forbidden', 'case .gatewayTimeout', 'case .requestTooLarge', 'case .network'])),
    check('Responses identity is optional and resource-scoped', 'resourceIdentity: String?' in agent and 'credentialResourceIdentity: String?' in openai),
    check('Responses replay requires same resource', 'sameResource' in oai and 'echo.resourceIdentity != nil' in oai),
    check('synthetic function ids preserve call pairing', 'fc_syn_' in oai and 'safeCallId' in oai),
    check('workflow has separate external gates', all(x in gate for x in ['case edit, push, ci, install, uninstall, respring, reboot', 'case .uninstall', 'case .respring', 'case .reboot'])),
    check('workflow uses composer-only approval', 'usingComposer' in vm and 'invalidateWorkflowApproval' in vm),
    check('workflow rejects generic approvals', 'allowed = ["批准推送", "确认推送"]' in gate and 'isApprovalText(text, for: pending)' in gate),
    check('build number is 160653', 'CURRENT_PROJECT_VERSION=160653' in workflow and '160653-MiniSightRepair' in workflow),
]

# The user explicitly excluded #185 body-size budgeting and automatic 413 shrinking.
excluded = ['RequestBodyByteBudget', 'bodyCapRetryRemaining', 'byteBudgetedMessages', 'trimRequestBody', 'kPerImageMaxBytes = 640', 'kRequestImageMaxBytes = 768']
all_swift = '\n'.join(p.read_text() for p in IOS.rglob('*.swift'))
checks.append(check('excluded body-budget feature absent', not any(x in all_swift for x in excluded)))

for key in ['Access denied', 'Gateway timed out', 'Request too large', 'Network line failed', '当前网络线路失败']:
    checks.append(check('localization: ' + key, key in localizable['strings']))

failed = [name for name, ok in zip([], []) if not ok]
# Recompute without relying on names stored separately.
# Each check already printed; count failures by rerunning the boolean list is unnecessary.
# The script exits from the captured output count below.
# Keep explicit result count for CI consumers.
# (The booleans are held in a local list through the expressions above.)
# Python's list contains only bools because check returns cond.
passed = sum(1 for x in checks if x)
print(f'{passed}/{len(checks)} passed')
raise SystemExit(0 if passed == len(checks) else 1)
