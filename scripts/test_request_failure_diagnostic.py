#!/usr/bin/env python3
"""Offline only. Source contracts are not a substitute for native Swift execution."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src/ios/Providers/OpenAI/OpenAIProvider.swift'
S=SOURCE.read_text()
BEGIN='// BEGIN REQUEST FAILURE DIAGNOSTIC (standalone Foundation test extraction)'
END='// END REQUEST FAILURE DIAGNOSTIC'
HELPER=S.split(BEGIN,1)[1].split(END,1)[0]
EXPECTED=json.loads((ROOT/'scripts/fixtures/request_diag_baseline.json').read_text())
class Contracts(unittest.TestCase):
    def test_01_failure_only_final_body(self):
        stream=S.split('    func streamRaw(',1)[1].split('    // MARK: - Request Building',1)[0]
        self.assertLess(stream.index('applyCodexClientMask(to: &body'),stream.index('func diagnoseFailure'))
        for marker in ('ProviderTurnLimitRejection.parse', 'ProviderChatEndpointRejection.target', 'if identityRetry <'):
            self.assertLess(stream.index('diagnoseFailure(.http,'),stream.index(marker))
        success=stream.split('let lineStream = AsyncThrowingStream',1)[1]
        self.assertNotIn('diagnoseFailure',success)
        self.assertNotIn('RequestFailureDiagnostic',success)
        self.assertEqual(S.count('logger.warning("[RequestFailureDiag]'),1)
    def test_02_cancellation_before_budget(self):
        self.assertLess(HELPER.index('error is CancellationError'),HELPER.index('gate.take(now: now)'))
        self.assertLess(HELPER.index('NSURLErrorCancelled'),HELPER.index('gate.take(now: now)'))
    def test_03_no_raw_logging_or_new_storage(self):
        for forbidden in ['localizedDescription','allHTTPHeaderFields','URLSession','UserDefaults','FileManager','.absoluteString','body.description','body.debugDescription']:
            self.assertNotIn(forbidden,HELPER)
        self.assertNotRegex(HELPER,r'\b(?:print|NSLog)\s*\(')
        self.assertNotRegex(HELPER,r'(?m)event\[[^\]]+\]\s*=\s*(body|responseBody|error)\s*$')
        self.assertIn('knownKeys.filter',HELPER)
        self.assertNotIn('for (key, value) in body',HELPER)
    def test_04_bounds(self):
        for needle in ['count < 8','now - started >= 60','data.count <= 4096','utf8.prefix(32769)','bytes.count <= 32768','messages.prefix(256)','tools.prefix(128)','parts.prefix(64)','var remainingText = 65536','remainingText -= sampled','utf8.prefix(budget + 1)','var remainingCalls = 256','remainingCalls -= 1','calls.prefix(sampled)','utf8.prefix(257)']:
            self.assertRegex(HELPER, re.escape(needle) + r'(?!\d)')
    def test_05_request_id_and_error_allowlists(self):
        for needle in ['fingerprint(requestID)','classify(detail["code"], allowed: allowed)','classify(detail["type"], allowed: allowed)','SymmetricKey(size: .bits256)','HMAC<SHA256>.authenticationCode(for: data, using: fingerprintKey)']:
            self.assertIn(needle,HELPER)
        for raw in ['event["requestID"]', 'safeRequestID', 'Data(processID.utf8)', 'detail["message"]']:
            self.assertNotIn(raw,HELPER)
        self.assertNotRegex(HELPER,r'event\[[^\]]+\].*=.*fingerprintKey')
    def test_06_types_limits_and_identity(self):
        for needle in ['CFGetTypeID(n) == CFBooleanGetTypeID()','CFGetTypeID(n) != CFBooleanGetTypeID()','n.doubleValue.isFinite','fingerprint(body["model"] as? String)','fingerprint(providerId)','fingerprint(url.host)','max_completion_tokens','max_output_tokens','"jsonEncoded": encodedBytes != nil']:
            self.assertIn(needle,HELPER)
    def test_07_lock_and_all_failure_stages(self):
        self.assertIn('lock.lock(); defer { lock.unlock() }',HELPER)
        for stage in ['sizeGuard','encoding','transport','http','httpRead']:
            self.assertEqual(S.count('diagnoseFailure(.'+stage+','),1)
    def test_08_original_logic_is_byte_identical_after_removing_diagnostics(self):
        released=subprocess.check_output(['git','show',EXPECTED['commit']+':'+EXPECTED['path']],cwd=ROOT)
        self.assertEqual(hashlib.sha256(released).hexdigest(),EXPECTED['released_sha256'])
        self.assertIn('import Foundation\nimport CoreFoundation\n', S)
        normalized=S.replace('import CoreFoundation\n','',1).replace(BEGIN+HELPER+END+'\n\n','',1)
        start=normalized.index('        // [T-request-failure-diagnostic]')
        end=normalized.index('        // Use .sortedKeys',start)
        self.assertEqual(hashlib.sha256(normalized[start:end].encode()).hexdigest(), 'e84a7f10a8cc835d0ee16e20cf8d4d1dc1fb21ad483992e2e5581a3613d4be1f', 'Unexpected extra logic in diagnostic hook')
        normalized=normalized[:start]+'        try guardRequestBodySize(body, context: "streamRaw")\n\n'+normalized[end:]
        normalized=normalized.replace('''        do {
            request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
        } catch {
            diagnoseFailure(.encoding, error: error)
            throw error
        }
''','''        request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
''',1)
        normalized=normalized.replace('            diagnoseFailure(.transport, error: error)\n','',1)
        read = """            do {
                for try await line in byteStream.lines {
                    guard (chatAPIContext == nil && (turnCompactionContext == nil || ProviderTurnRun.current == nil))
                            || body.utf8.count + line.utf8.count <= 16_384 else {
                        session.finishTasksAndInvalidate()
                        throw ProviderChatAPIError.unverified
                    }
                    body += line
                }
            } catch {
                diagnoseFailure(.httpRead, response: response as? HTTPURLResponse, error: error)
                throw error
            }
"""
        self.assertIn(read,normalized)
        normalized=normalized.replace(read,"""            for try await line in byteStream.lines {
                guard (chatAPIContext == nil && (turnCompactionContext == nil || ProviderTurnRun.current == nil))
                        || body.utf8.count + line.utf8.count <= 16_384 else {
                    session.finishTasksAndInvalidate()
                    throw ProviderChatAPIError.unverified
                }
                body += line
            }
""",1)
        normalized=normalized.replace('            diagnoseFailure(.http, response: response as? HTTPURLResponse, responseBody: body)\n','',1)
        self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), EXPECTED['turn_integrated_sha256'],
                         'Unapproved change outside diagnostic hooks in released 389 plus exact reviewed turn change')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-native',action='store_true');parser.add_argument('--result');parser.add_argument('--native-mutations',action='store_true')
    args=parser.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
    summary={'source_checks':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'source_sha256':hashlib.sha256(S.encode()).hexdigest(),'native':'NOTRUN','native_mutations':'NOTRUN','network_requests':0}
    code=0 if result.wasSuccessful() else 1
    compiler=shutil.which('swiftc')
    required=args.require_native or os.getenv('V64R_REQUIRE_SWIFT')=='1' or sys.platform=='darwin'
    summary['native_required']=required
    if compiler and sys.platform=='darwin' and code==0:
        fixture=(ROOT/'scripts/request_failure_diag_fixture.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='request-diag-') as tmp:
            p=Path(tmp)/'main.swift';exe=Path(tmp)/'fixture'
            p.write_text('import Foundation\nimport CoreFoundation\nimport CryptoKit\n'+HELPER+'\n'+fixture)
            c=subprocess.run([compiler,'-swift-version','5','-warnings-as-errors',str(p),'-o',str(exe)],capture_output=True,text=True,timeout=90)
            summary['compile_exit']=c.returncode
            if c.returncode:print(c.stderr);code=1;summary['native']='COMPILE_FAILED'
            else:
                r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=45)
                print(r.stdout);print(r.stderr)
                summary['native']='PASS' if r.returncode==0 else 'FAILED';code=max(code,int(r.returncode!=0))
                summary['native_checks']=int(re.search(r'NATIVE_CHECKS (\d+)',r.stdout).group(1)) if r.returncode==0 else 0
                if args.native_mutations and r.returncode==0:
                    mutants={'leak':('event["effort"] = classify(body["reasoning_effort"], allowed:','event["modelLeak"] = body["model"]; event["effort"] = classify(body["reasoning_effort"], allowed:'),'unlimited':('count < 8','count < 80'),'no_cancel':('if Task.isCancelled || error is CancellationError { return nil }','if false { return nil }'),'bad_pair':('if pending.remove(id) == nil','if false'),'short_scan':('messages.prefix(256)','messages.prefix(200)')}
                    outcomes={}
                    for name,(old,new) in mutants.items():
                        assert old in HELPER
                        p.write_text('import Foundation\nimport CoreFoundation\nimport CryptoKit\n'+HELPER.replace(old,new,1)+'\n'+fixture)
                        c=subprocess.run([compiler,'-swift-version','5',str(p),'-o',str(exe)],capture_output=True,text=True,timeout=90)
                        if c.returncode:outcomes[name]='COMPILE_FAILED_NOT_A_REJECTION';code=1;continue
                        r=subprocess.run([str(exe)],capture_output=True,text=True,timeout=45)
                        outcomes[name]='ASSERTION_REJECTED' if r.returncode else 'SURVIVED';code=max(code,int(r.returncode==0))
                    summary['native_mutations']=outcomes
    else:
        print('NATIVE NOTRUN: requires Apple Swift/Foundation/CryptoKit; source checks do not execute Swift.')
        if required:print('REQUIRED NATIVE UNAVAILABLE: fail closed');code=1
    if args.result:Path(args.result).write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2));return code
if __name__=='__main__':raise SystemExit(main())
