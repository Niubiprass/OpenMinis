#!/usr/bin/env python3
"""Exact production picker worker tests; native is mandatory on CI, never fake PASS."""
import argparse,hashlib,json,os,platform,shutil,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];I=R/'src/ios'
S=(I/'Views/Providers/UnifiedModelPicker.swift').read_text()
BASE='8262dc6bbe33cce382c2f8269984d1678a1131d7'
def decl(s, marker):
 a=s.index(marker); b=s.index('{',a); depth=1;c=b+1
 while depth:
  if s[c]=='{':depth+=1
  if s[c]=='}':depth-=1
  c+=1
 return s[a:c]
def old(path):return subprocess.check_output(['git','show',BASE+':src/ios/'+path],cwd=R).decode()
def contracts():
 baseline=old('Views/Providers/UnifiedModelPicker.swift')
 stable=['private func entryRow(', 'private func groupRow(', 'private var toolbarContent:',
 'private func loadSections()', 'private func candidateEntries(', 'private func buildSections(',
 'private func seedCollapse()', 'private func toggleAllEntries(', 'private func toggleSelection(',
 'private func orderedByLastUsedProvider(', 'private func rememberProvider(', 'private func isDanglingMember(',
 'private func removeDanglingMember(', 'private func unavailableMemberRow(']
 for name in stable:assert decl(S,name)==decl(baseline,name),name
 host=(I/'Views/Providers/SessionModelPicker.swift').read_text()
 assert host.replace('            useSessionDisplaySnapshots: true,\n','')==old('Views/Providers/SessionModelPicker.swift')
 for p in ['Views/Providers/ProviderInstancesView.swift','Providers/ProviderQuotaService.swift',
 'Providers/ProviderConfigStore.swift','Providers/ProviderMultiKeys.swift']:
  assert (I/p).read_text()==old(p),p
 provider=(I/'Providers/ProviderInstance.swift').read_text()
 assert provider.replace('enum ImageEndpointMode: String, Codable, Hashable, CaseIterable, Sendable {','enum ImageEndpointMode: String, Codable, Hashable, CaseIterable {').replace('struct ProviderInstance: Identifiable, Codable, Hashable, Sendable {','struct ProviderInstance: Identifiable, Codable, Hashable {')==old('Providers/ProviderInstance.swift')
 assert '@ObservedObject private var quotaService' not in S
 for name in ['SessionPickerQuotaBadge(scope: sessionQuotaScope(inst), inHeader: false)',
 'SessionPickerQuotaBadge(scope: sessionQuotaScope(item.instance), inHeader: true)',
 'ProviderQuotaRowProjectionLoader()', '.onDisappear { visible = false; loader.cancel() }',
 'if !config.useSessionDisplaySnapshots { legacyQuotaRevision = revision }',
 'scope.accepts(current: current, cancelled: Task.isCancelled)',
 'scope.generation == ProviderRowCredentialCache.shared.generation',
 'if snapshot != sessionCredentials { sessionCredentials = snapshot }']:
  assert name in S,name
 member=decl(S,'private func memberUnavailableReason(')
 assert member.index('if let scope = sessionCredentialScope') < member.index('if !instance.hasAnyCredential')
 assert 'guard sessionCredentials?.scope == scope' in member
 worker=decl(S,'private actor SessionPickerCredentialWorker')
 assert 'computeHasAnyCredential()' in worker and 'hasAnyCredential ' not in worker
 assert worker.count('Task.checkCancellation()')==3
 assert 'result[instance.id] == nil' in worker
 assert '.task(id: sessionCredentialScope)' in S
 assert S.count('quotaService.refreshAllIfNeeded(instances: store.instances)')==1
 print('PASS source contracts: 14 protected functions, session-only switch, management/storage unchanged')
def native_source():
 worker=S.split('// BEGIN SESSION_PICKER_CREDENTIAL_WORKER',1)[1].split('// END SESSION_PICKER_CREDENTIAL_WORKER',1)[0]
 return '''import Foundation
struct ProviderInstance: Sendable { let id: String; let usable: Bool; func computeHasAnyCredential() -> Bool { usable } }
''' + worker + '''
@main struct Run {
 static func main() async throws {
  let worker=SessionPickerCredentialWorker()
  let values=try await worker.read([.init(id:"a",usable:true),.init(id:"b",usable:false),.init(id:"a",usable:false)])
  precondition(values==["a":true,"b":false])
  let one=SessionPickerCredentialScope(sessionId:"s",authRevision:1,configRevision:2,snapshotRevision:3,generation:4)
  precondition(one.accepts(current:one,cancelled:false))
  precondition(!one.accepts(current:one,cancelled:true))
  let variants=[SessionPickerCredentialScope(sessionId:"x",authRevision:1,configRevision:2,snapshotRevision:3,generation:4),
   SessionPickerCredentialScope(sessionId:"s",authRevision:2,configRevision:2,snapshotRevision:3,generation:4),
   SessionPickerCredentialScope(sessionId:"s",authRevision:1,configRevision:3,snapshotRevision:3,generation:4),
   SessionPickerCredentialScope(sessionId:"s",authRevision:1,configRevision:2,snapshotRevision:4,generation:4),
   SessionPickerCredentialScope(sessionId:"s",authRevision:1,configRevision:2,snapshotRevision:3,generation:5)]
  for variant in variants { precondition(!one.accepts(current:variant,cancelled:false)) }
  let t=Task { () throws -> Bool in
   try await Task.sleep(nanoseconds:10_000_000_000)
   _=try await worker.read([.init(id:"a",usable:true)])
   return true
  }; t.cancel()
  do { _=try await t.value; preconditionFailure("cancellation ignored") } catch is CancellationError {}
  print("PASS native production picker worker and scope invalidation; synthetic providers only")
 }
}
'''
def ui_typecheck(directory):
 if platform.system() != 'Darwin' or not shutil.which('xcrun'):
  raise RuntimeError('iOS SwiftUI native typecheck required; Xcode missing')
 # Extract the actual reused loader and new badge, with synthetic dependencies.
 provider=(I/'Views/Providers/ProviderInstancesView.swift').read_text()
 stub=(R/'scripts/fixtures/provider_quota_row_projection.swift').read_text().split('// PRODUCTION_LOADER',1)[0]
 stub=stub.replace('    var revision = 0 // test writes on MainActor only','    @Published var revision = 0 // test writes on MainActor only')
 badge=decl(S,'@MainActor private struct SessionPickerQuotaBadge: View')
 loader=decl(provider,'@MainActor final class ProviderQuotaRowProjectionLoader:')
 worker=S.split('// BEGIN SESSION_PICKER_CREDENTIAL_WORKER',1)[1].split('// END SESSION_PICKER_CREDENTIAL_WORKER',1)[0]
 stub=stub.replace('struct ProviderInstance {','struct ProviderInstance: Sendable {\n    func computeHasAnyCredential() -> Bool { true }')
 fixture=Path(directory)/'PickerUI.swift'
 fixture.write_text('import SwiftUI\n'+stub+'\n'+worker+'\n'+loader+'\n'+badge+'''
@MainActor struct PickerCallSite: View {
 let scope: ProviderQuotaRowProjectionLoader.Scope
 var body: some View { SessionPickerQuotaBadge(scope: scope, inHeader: true) }
}
''')
 sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
 subprocess.run(['xcrun','--sdk','iphoneos','swiftc','-swift-version','5','-typecheck','-sdk',sdk,'-target','arm64-apple-ios15.5',str(fixture)],check=True,timeout=120)
 print('PASS iOS15.5 actual badge + reused loader typecheck, no rendered UI claim')

def main():
 p=argparse.ArgumentParser();p.add_argument('--require-native',action='store_true');a=p.parse_args()
 contracts()
 if not shutil.which('swiftc'):
  print('NATIVE NOTRUN: swiftc unavailable')
  return 1 if a.require_native or os.getenv('V64R_REQUIRE_SWIFT')=='1' else 0
 with tempfile.TemporaryDirectory() as d:
  s=Path(d)/'main.swift';s.write_text(native_source());b=Path(d)/'worker'
  for mode in ['5','6']:
   subprocess.run(['swiftc','-swift-version',mode,'-parse-as-library',str(s),'-o',str(b)],check=True,timeout=120)
   subprocess.run([str(b)],check=True,timeout=30)
  ui_typecheck(d)
 return 0
if __name__=='__main__':raise SystemExit(main())
