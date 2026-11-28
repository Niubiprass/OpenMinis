#!/usr/bin/env python3
"""Source guards plus extracted Swift runtime fixture. No runtime substitute on iSH."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess,tempfile,os
R=Path(__file__).resolve().parents[1];P=R/'src/ios'

def sources():return {n:(P/path).read_text() for n,path in {'engine':'Providers/ProviderTurnCompaction.swift','network':'Providers/OpenAI/OpenAIProvider.swift','compact':'Agent/Chat/AIChatViewModel+Compaction.swift','agent':'Providers/OpenAI/OpenAIAgentProvider.swift','vm':'Agent/Chat/AIChatViewModel.swift'}.items()}
def function(s,start):
 a=s.index(start);b=s.index('{',a);i=b+1;d=1
 while d:
  if s[i]=='{':d+=1
  elif s[i]=='}':d-=1
  i+=1
 return s[a:i]
def checks(x):
 e,n,c,a,v=(x[k] for k in ['engine','network','compact','agent','vm'])
 trace=e.split('final class CompactLifecycleTrace:',1)[1].split('struct ProviderTurnObservation:',1)[0]
 retry=function(c,'static func isSegmentRetryableError(')
 return {
  'typed_empty_does_not_split':'if error is CompactSummaryFailure { return false }' in retry and 'throw CompactSummaryFailure.empty' in c,
  'cancel_not_blame_user':'[Compact] Cancelled by user' not in c and 'Cancelled origin=' in c,
  'explicit_stop_and_switch_distinct':'activeCompactionTrace?.cancel("user_stop")' in v and 'activeCompactionTrace?.cancel("model_switch")' in v,
  'parent_and_watchdog_sources':all(t in c for t in ['lifecycle?.cancel("parent_cancel")','lifecycle?.cancel("summary_stall")','lifecycle?.cancel("summary_overall")']),
  'gate_records_origin_before_finishing':e.index('run?.lifecycle()?.cancel(summaryExpired') < e.index('continuation.finish(throwing: ProviderTurnLimitRejection(limit: nil, confirmedServerRejection: false)'),
  'stop_covers_retry_after_summary':all(t in v for t in ['activeTurnRecoveryRun?.lifecycle()?.cancel("user_stop")','activeTurnRecoveryRun?.lifecycle()?.cancel("model_switch")','if activeTurnRecoveryRun === learnedRun { activeTurnRecoveryRun = nil }']),
  'tasklocal_reaches_network':'CompactLifecycle.$current.withValue(trace)' in c and 'let trace = CompactLifecycle.current' in n,
  'trace_single_terminal':'(!ended || lateNetwork)' in trace and 'if stage == "end" { ended = true }' in trace,
  'late_network_bounded':'lateNetworkEvents < 32' in trace and 'if lateNetwork { result["late"] = "1" }' in trace,
  'cancel_cannot_mutate_after_end':'guard !ended else { lock.unlock(); return }' in trace,
  'fixed_network_vocabulary':all('"'+word+'"' in trace for word in ['compact_summary','tool_calls','cancel']),
  'marker_commit_readback_rollback':all(t in c for t in ['trace.event("commit_begin"','trace.event("commit_end"','trace.event("rollback"','trace.event("history"','deleteCompactMarker(id: marker.id)']),
  'only_verified_recovery_is_success':'verifiedRecovery = recorded' in a and 'terminal = verifiedRecovery ? "restored" : "not_restored"' in a,
  'summary_grammar_and_rollup_retained':'previousSummary: summary1, depth: depth + 1' in c,
  'no_raw_error_in_trace':'error_domain_hash' in trace and 'localizedDescription' not in trace and 'logger.info("[Compact] Retry segments:' in c,
  'all_compact_returns_recorded':not re.search(r'return \.(?:success|failed|skipped|cancelled)\b',c.split('func compactBefore(',1)[1].split('/// Build a text representation',1)[0]),
 }

def harness(x):
 e=x['engine'];raw=e[e.index('enum CompactLifecycle {'):e.index('struct ProviderTurnObservation:')]
 n=x['network'].split('// BEGIN COMPACT NETWORK TRACE',1)[1].split('\n',1)[1].split('// END COMPACT NETWORK TRACE',1)[0]
 assert not n.lstrip().startswith('(also extracted')
 retry=function(x['compact'],'static func isSegmentRetryableError(')
 f=(R/'scripts/fixtures/compact_lifecycle_trace_20261128.swift').read_text()
 return f.replace('/* ACTUAL_LIFECYCLE */',raw).replace('/* ACTUAL_NETWORK_HELPER */',n).replace('/* ACTUAL_SPLIT_POLICY */',retry)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--require-native',action='store_true');parser.add_argument('--emit-harness',type=Path);args=parser.parse_args()
 x=sources();base=checks(x);print(json.dumps({'source_contracts':base},indent=2));assert all(base.values()),'source contract failure'
 variants=[('empty_splits','compact','if error is CompactSummaryFailure { return false }',''),('wrong_origin','vm','activeCompactionTrace?.cancel("model_switch")','activeCompactionTrace?.cancel("user_stop")'),('late_dropped','engine','(!ended || lateNetwork)','!ended'),('double_end','engine','if stage == "end" { ended = true }',''),('false_success','agent','terminal = verifiedRecovery ? "restored" : "not_restored"','terminal = "restored"')]
 for label,key,old,new in variants:
  assert x[key].count(old)==1,(label,'mutation seam not unique');y=x.copy();y[key]=x[key].replace(old,new)
  assert not all(checks(y).values()),label+' escaped';print('SOURCE MUTANT REJECTED',label)
 h=harness(x)
 if args.emit_harness:args.emit_harness.write_text(h)
 cc=shutil.which('swiftc')
 if not cc:
  print('NATIVE SKIP: no Swift compiler; source contracts are NOT runtime proof')
  return 1 if args.require_native or os.getenv('V64R_REQUIRE_SWIFT')=='1' else 0
 with tempfile.TemporaryDirectory(prefix='compact-shared-trace-') as d:
  p=Path(d);(p/'main.swift').write_text(h)
  for version in ['5','6']:
   subprocess.run([cc,'-swift-version',version,'-parse-as-library',str(p/'main.swift'),'-o',str(p/'run')],check=True,timeout=120)
   subprocess.run([str(p/'run')],check=True,timeout=30)
 return 0
if __name__=='__main__':raise SystemExit(main())
