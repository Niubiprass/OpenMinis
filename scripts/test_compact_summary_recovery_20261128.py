#!/usr/bin/env python3
"""Extracted production Swift behavior; source checks never substitute runtime."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'src/ios'
FILES={'provider':P/'Providers/OpenAI/OpenAIProvider.swift','engine':P/'Providers/ProviderTurnCompaction.swift','compact':P/'Agent/Chat/AIChatViewModel+Compaction.swift'}
def region(s,start,end):return s.split(start,1)[1].split('\n',1)[1].split(end,1)[0]
def sources():return {k:p.read_text() for k,p in FILES.items()}
def checks(x):
 n,e,c=(x[k] for k in ['provider','engine','compact']);stream=n.split('    func streamMessage(',1)[1].split('    // MARK: - Request body size guard',1)[0]
 a=region(n,'// BEGIN COMPACT SUMMARY ASSEMBLER','// END COMPACT SUMMARY ASSEMBLER')
 b=region(e,'// BEGIN COMPACT SUMMARY BUDGET','// END COMPACT SUMMARY BUDGET')
 once=c.split('    private func generateCompactSummaryOnce(',1)[1].split('    /// Create an AgentMessage',1)[0]
 return {
  'summary_only_not_normal_stream':'trace == nil ? nil : CompactSummaryStreamAssembler()' in stream and 'summaryOutput == nil ? text :' in stream,
  'final_output_and_done_fallback':all(t in a for t in ['case "response.output_text.done":','case "response.output_item.done":','case "response.completed", "response.incomplete":']),
  'reasoning_and_tools_excluded':'item["type"] as? String == "message"' in a and 'item["role"] as? String == "assistant"' in a and 'block["type"] as? String == "output_text"' in a,
  'snapshot_prefix_checked_not_duplicated':'guard text.hasPrefix(part.text)' in a and 'String(text.dropFirst(part.text.count))' in a,
  'partial_not_saved_as_success':'_ = try summaryOutput?.finish()' in stream and '.outputLimit' in a and '.incomplete' in a,
  'bounded_text_and_parts':'maxBytes = 2 * 1024 * 1024' in a and 'parts.count < 256' in a and 'order.last == key' in a,
  'typed_errors_preserved':'(error as? CompactSummaryFailure).map { $0 as Error } ?? self.mapError(error)' in stream,
  'all_invalid_results_not_split':'if error is CompactSummaryFailure { return false }' in c,
  'retry_only_proven_output_limit':'failure == .outputLimit' in b and 'guard !outputRetryUsed' in once and 'outputRetryUsed = true' in once,
  'retry_uses_same_provider':once.count('makeLLMProvider(for: entry)')==1 and once.index('makeLLMProvider(for: entry)')<once.index('while true'),
  'explicit_model_cap_and_headroom':'declared: entry.overrides.maxOutputTokens ?? entry.model.maxOutputTokens' in once and 'min(32768, min(headroom, modelCap))' in b,
  'config_and_auth_snapshot_before_factory':once.index('let configRevision =')<once.index('makeLLMProvider(for: entry)') and once.count('ProviderConfigStore.shared.authRevision == authRevision')==2 and once.count('self.sessionId == summarySession')==2,
  'consumer_owns_connection':once.index('let consumeTask = Task')<once.index('provider.streamMessage('),
  'same_overall_deadline_across_retry':'let summaryStarted = ProcessInfo.processInfo.systemUptime' in once and '900. - max(0, ProcessInfo.processInfo.systemUptime - summaryStarted)' in once,
  'progress_from_real_data_not_reasoning_text':'@TaskLocal static var streamProgress:' in e and 'if let progressTouch { await progressTouch() }' in stream and 'CompactLifecycle.$streamProgress.withValue({ await progress.touch() })' in once,
  'no_tool_replay_in_retry':'tools: nil' in stream and 'streamRaw(' not in once and 'performCompaction(' not in once,
  'native_fixture_access_scope':'private static func tryFinish(_ s: CompactSummaryStreamAssembler)' in (ROOT/'scripts/fixtures/compact_summary_recovery_20261128.swift').read_text(),
  'summary_terminal_not_socket_close':'if !useChat, summaryOutput?.reachedTerminal == true { break }' in stream and 'var reachedTerminal: Bool { terminal != nil }' in a,
  'terminal_status_must_be_complete':'(status == nil || status == "completed") && reason == nil' in a,
 }

def harness(x):
 e=x['engine'];failure=e[e.index('enum CompactSummaryFailure:'):e.index('// BEGIN COMPACT SUMMARY BUDGET')]
 assembler=region(x['provider'],'// BEGIN COMPACT SUMMARY ASSEMBLER','// END COMPACT SUMMARY ASSEMBLER')
 budget=region(e,'// BEGIN COMPACT SUMMARY BUDGET','// END COMPACT SUMMARY BUDGET')
 f=(ROOT/'scripts/fixtures/compact_summary_recovery_20261128.swift').read_text()
 return f.replace('/* ACTUAL_SUMMARY_FAILURE */',failure).replace('/* ACTUAL_SUMMARY_ASSEMBLER */',assembler).replace('/* ACTUAL_SUMMARY_BUDGET */',budget)

def main():
 p=argparse.ArgumentParser();p.add_argument('--require-native',action='store_true');p.add_argument('--emit-harness',type=Path);args=p.parse_args();x=sources();c=checks(x)
 print(json.dumps({'source_contracts':c},indent=2));assert all(c.values()),'summary recovery source contracts'
 variants=[('lose_final','provider','case "response.output_text.done":','case "not-a-real-event":'),('duplicate_snapshot','provider','String(text.dropFirst(part.text.count))','text'),('promote_reasoning','provider','item["type"] as? String == "message"','true'),('retry_empty','engine','failure == .outputLimit','failure == .empty'),('retry_loop','compact','guard !outputRetryUsed,','guard true,'),('ignore_declared_cap','engine','min(32768, min(headroom, modelCap))','min(32768, headroom)'),('connection_not_guarded','compact','let consumeTask = Task','let consumeTaskBroken = Task')]
 for name,key,old,new in variants:
  assert x[key].count(old)==1,(name,'unique mutation anchor');y=x.copy();y[key]=x[key].replace(old,new)
  try:killed=not all(checks(y).values())
  except ValueError:killed=True
  assert killed,name+' escaped';print('SOURCE MUTANT REJECTED:',name)
 h=harness(x);assert '/* ACTUAL_' not in h
 if args.emit_harness:args.emit_harness.write_text(h)
 cc=shutil.which('swiftc')
 if not cc:
  print('NATIVE SKIP: missing Swift; no runtime proof, no network/model requests')
  return 1 if args.require_native or os.getenv('V64R_REQUIRE_SWIFT')=='1' else 0
 with tempfile.TemporaryDirectory(prefix='summary-recovery-') as d:
  d=Path(d);f=d/'main.swift';f.write_text(h)
  for version in ['5','6']:
   subprocess.run([cc,'-swift-version',version,'-parse-as-library',str(f),'-o',str(d/'run')],check=True,timeout=120)
   subprocess.run([str(d/'run')],check=True,timeout=30)
  for name,old,new in [('lose-final','return try append(text,key:key,snapshot:true)','return ""'),('length-as-stop','if terminal == "length" { throw CompactSummaryFailure.outputLimit }','if terminal == "length" { return "stop" }'),('retry-empty','failure == .outputLimit','failure == .empty')]:
   # No production file changes. A build failure cannot be credited as runtime rejection.
   assert h.count(old)==1,name;f.write_text(h.replace(old,new))
   subprocess.run([cc,'-swift-version','6','-parse-as-library',str(f),'-o',str(d/'run')],check=True,timeout=120)
   r=subprocess.run([str(d/'run')],capture_output=True,timeout=30);assert r.returncode!=0,name+' runtime mutant survived';print('NATIVE MUTANT REJECTED',name)
 return 0
if __name__=='__main__':raise SystemExit(main())
