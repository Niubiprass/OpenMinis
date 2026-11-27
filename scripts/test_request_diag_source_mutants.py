#!/usr/bin/env python3
"""Source-contract mutation tests ONLY; these do not execute/compile Swift."""
import contextlib,hashlib,importlib.util,io,json,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('contracts',HERE/'test_request_failure_diagnostic.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.S
cases={
 'dump_unknown_fields':('for key in knownKeys { fields[key] = shape(body[key]) }','for (key, value) in body { fields[key] = String(describing: value) }'),
 'raw_request_id':('event["requestIDPresent"] = true','event["requestID"] = requestID'),
 'public_fingerprint_key':('let data = Data(value.utf8.prefix(256))','let data = Data(processID.utf8) + Data(value.utf8.prefix(256))'),
 'remove_task_cancel_guard':('if Task.isCancelled || error is CancellationError { return nil }','if false { return nil }'),
 'raise_event_budget':('count < 8','count < 80'),
 'raise_line_limit':('data.count <= 4096','data.count <= 8192'),
 'raise_text_scan':('var remainingText = 65536','var remainingText = 100000000'),
 'change_request_body':('        // Use .sortedKeys so every request with the same body produces byte-identical','        body["diagnostic"] = true\n        // Use .sortedKeys so every request with the same body produces byte-identical')}
results={}
for name,(old,new) in cases.items():
    assert original.count(old)==1,(name,original.count(old))
    m.S=original.replace(old,new,1)
    m.HELPER=m.S.split(m.BEGIN,1)[1].split(m.END,1)[0]
    log=io.StringIO()
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log).run(unittest.defaultTestLoader.loadTestsFromTestCase(m.Contracts))
    rejected=not result.wasSuccessful()
    results[name]={'rejected_by_source_contract':rejected,'failing_checks':[t.id().split('.')[-1] for t,_ in result.failures+result.errors]}
    print(name, 'REJECTED' if rejected else 'SURVIVED')
m.S=original
out={'kind':'SOURCE_CONTRACT_ONLY_NOT_SWIFT_RUNTIME','production_sha256':hashlib.sha256(original.encode()).hexdigest(),'cases':results,'native_mutations':'NOTRUN'}
if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(out,indent=2))
raise SystemExit(0 if all(v['rejected_by_source_contract'] for v in results.values()) else 1)
