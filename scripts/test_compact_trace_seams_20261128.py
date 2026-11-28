from pathlib import Path
import re,unittest
R=Path(__file__).resolve().parents[1];P=R/'src/ios'
E=P/'Providers/ProviderTurnCompaction.swift';N=P/'Providers/OpenAI/OpenAIProvider.swift';F=R/'scripts/fixtures/turn_compaction_20261127.swift'
def allowed(s):
 body=s.split('private static let words: Set<String> = [',1)[1].split(']',1)[0]
 return set(re.findall(r'"([a-z_]+)"',body))
def source_contract(engine,network,fixture):
 w=allowed(engine)
 for value in ['compact_summary','tool_calls','responses','chat_completions','network_cancel']:
  assert value in w, 'trace sink drops '+value
 assert '"purpose": "compact_summary"' in network or '"purpose":"compact_summary"' in network
 assert 'case "tool_calls", "function_call": noteFinish("tool_calls")' in network
 logger=fixture.split('struct AppLogger:',1)[1].split('\nlet logger',1)[0]
 assert 'func info(_ message: String)' in logger, 'native logger seam missing'
class Tests(unittest.TestCase):
 def test_real_sender_and_sink_align(self):source_contract(E.read_text(),N.read_text(),F.read_text())
 def test_source_negatives_rejected(self):
  e,n,f=E.read_text(),N.read_text(),F.read_text();source_contract(e,n,f)
  for a,b in [('"compact_summary", ',''),('"tool_calls", ','')]:
   self.assertEqual(e.count(a),1)
   with self.assertRaises(AssertionError):source_contract(e.replace(a,b),n,f)
  with self.assertRaises(AssertionError):source_contract(e,n,f.replace('func info(_ message: String) {}',''))
if __name__=='__main__':unittest.main(verbosity=2)
