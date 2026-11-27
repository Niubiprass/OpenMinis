#!/usr/bin/env python3
"""Production-extracted native tests. Portable assertions are SOURCE ONLY.
V64R_REQUIRE_SWIFT=1 or --require-native refuses to pass without Swift/CryptoKit.
No device, credentials or real provider requests.
"""
import argparse, json, os, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
P = ROOT/'src/ios'
ENGINE = (P/'Providers/ProviderTurnCompaction.swift').read_text()
AGENT = (P/'Providers/OpenAI/OpenAIAgentProvider.swift').read_text()
RAW = (P/'Providers/OpenAI/OpenAIProvider.swift').read_text()
VM = (P/'Agent/Chat/AIChatViewModel.swift').read_text()
COMPACT = (P/'Agent/Chat/AIChatViewModel+Compaction.swift').read_text()
WRAPPER = AGENT.split('    func streamAgentMessageClamped(',1)[1].split('    private func streamAgentMessageUncompacted(',1)[0]
checks = {
 'structured symbolic code, bounded body, no substring retry': all(t in ENGINE for t in ['[400,409,422].contains(status)','body.utf8.count <= 16_384','root["error"] as? [String:Any]','== "session_turn_limit_exceeded"']),
 'reject before identity retry or parser stream': RAW.index('ProviderTurnLimitRejection.parse') < RAW.index('if identityRetry < CodexClientMask.identityRetryLimit'),
 'fixed + auto configured without enabling format detection': 'defer { ProviderTurnCompaction.configure(provider' in (P/'Providers/ProviderChatAPI.swift').read_text(),
 'no key rotation or key failure penalty': (P/'Providers/AgentProvider.swift').read_text().index('if error is ProviderTurnLimitRejection') < (P/'Providers/AgentProvider.swift').read_text().index('let kind = MultiKeyFailureKind.classify(error)'),
 'always fallback stops': 'if error is ProviderTurnLimitRejection { throw error }' in (P/'Agent/Chat/AIChatViewModel+Fallback.swift').read_text(),
 'every event forbids replay': WRAPPER.index('exposed = true') < WRAPPER.index('guard !exposed, !retried, run.takeRecovery()'),
 'actual rejected endpoint used on recovery': all(t in WRAPPER for t in ['if let failure {','if failure.responses {','stream = try await streamResponsesAPI','stream = try await streamChatCompletions']),
 'verified only normal nonempty completed reduced history': all(t in WRAPPER+ENGINE for t in ['content && completed','completed = reason == .endTurn','reducedCount < observation.rejectedCount','rows[observation.scope]?.observationId == observation.observationId']),
 'observed alone never anticipates': 'guard verified, rejectedCount >= 6' in ENGINE,
 'request budget once per run not per key': 'let learnedRun = ProviderTurnRun(' in VM and 'ProviderTurnRun.$current.withValue(learnedRun)' in VM and 'guard !recoverySpent else' in ENGINE,
 'original tool results/current task retained': all(t in VM for t in ['budgetCompactionTarget(before: budgetProtectedRawId)','explicitRawAnchor: target.rawId','Self.limitedMessages(self.applyRequestImageBudget(history), entryId: entryId)']),
 'recursive summary disabled': 'ProviderTurnRun.$current.withValue(nil)' in VM,
 'cancel binding run fences': all(t in VM for t in ['self.sessionId == learnedSession','self.learnedTurnRunToken == learnedRunToken','!self.pendingModelSwitch','== learnedBinding']),
 'late marker rollback exact id': 'deleteCompactMarker(id: marker.id)' in COMPACT and 'guard removed else' in COMPACT,
 'original token budget/switch files not edited': '100_000_000' in (P/'Agent/Chat/ContextPolicy.swift').read_text(),
 'project registration': all((P/'Minis.xcodeproj/project.pbxproj').read_text().count(t)==1 for t in ['CB83F001 /* ProviderTurnCompaction.swift in Sources */ =','CB83F002 /* ProviderTurnCompaction.swift */ =','CB83F002 /* ProviderTurnCompaction.swift */,','CB83F001 /* ProviderTurnCompaction.swift in Sources */,']),
 'UI fixed index only after full wrapper prime': 'ProviderTurnOpenGate.prime(upstream)' in VM and VM.index('msgIdx = recoveredMsgIndex') < VM.index('let result = try await processStreamEvents(', VM.index('msgIdx = recoveredMsgIndex')),
 'summary rejection terminal not split': 'ProviderTurnRun.$isRecoverySummary.withValue(true)' in VM and 'ProviderTurnRun.isRecoverySummary' in RAW and 'error is CancellationError || error is ProviderTurnLimitRejection' in COMPACT,
 'partial recovered reply cannot invoke old empty retry': 'if let failure, !sawTool, (!content || !completed) { throw failure }' in WRAPPER,
 'observations applied on MainActor with final validity': '@MainActor\n    func observe(' in ENGINE and '@MainActor\n    func verify(' in ENGINE and 'confirm(), run.enabled(), !Task.isCancelled' in ENGINE,
 'workflow requires native test': 'V64R_REQUIRE_SWIFT=1 python3 scripts/test_turn_compaction_20261127.py' in (ROOT/'.github/workflows/openminis-app.yml').read_text(),
}

def harness():
    engine = ENGINE.split('@MainActor\nenum ProviderTurnCompaction',1)[0]
    # Only the fixture's shared store is redirected; algorithms are verbatim.
    engine = engine.replace('static let shared = ProviderTurnHistory()', 'static let shared = ProviderTurnHistory(defaults: UserDefaults(suiteName: "TurnFixture.isolated")!)')
    engine += '\nfinal class ProviderTurnOpenGate' + ENGINE.split('final class ProviderTurnOpenGate',1)[1]
    wrapper = '    func streamAgentMessageClamped(' + WRAPPER
    fixture = (ROOT/'scripts/fixtures/turn_compaction_20261127.swift').read_text()
    return engine + '\n' + fixture.replace('/* ACTUAL_WRAPPER */', wrapper)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--require-native',action='store_true'); parser.add_argument('--emit-harness'); args=parser.parse_args()
    print(json.dumps({'source_contracts':checks},indent=2))
    if not all(checks.values()): return 1
    source=harness()
    if args.emit_harness: Path(args.emit_harness).write_text(source)
    compiler=shutil.which('swiftc')
    if not compiler:
        print('NATIVE SKIP: no Swift compiler; source contracts are NOT runtime proof')
        return 1 if args.require_native or os.environ.get('V64R_REQUIRE_SWIFT')=='1' else 0
    with tempfile.TemporaryDirectory(prefix='minis-turn-fixture-') as directory:
        p=Path(directory); (p/'main.swift').write_text(source)
        for mode in ['5','6']:
            built=subprocess.run([compiler,'-swift-version',mode,'-parse-as-library',str(p/'main.swift'),'-o',str(p/'run')],timeout=120)
            if built.returncode: return built.returncode
            run=subprocess.run([str(p/'run')],timeout=60)
            if run.returncode: return run.returncode
    return 0
if __name__=='__main__': raise SystemExit(main())
