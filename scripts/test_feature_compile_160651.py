#!/usr/bin/env python3
"""Parse actual changed Swift files and execute the actual ask_user state.
Requires Apple's swiftc on CI; local iSH reports SKIP, never a compile PASS.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
BASE = '2ed178e'


class FeatureCompileTests(unittest.TestCase):
    def compiler(self):
        compiler = shutil.which('swiftc')
        if not compiler:
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('swiftc required; actual Swift validation did not run')
            self.skipTest('swiftc unavailable; actual Swift validation NOT run')
        return compiler

    def test_all_changed_swift_parses(self):
        compiler = self.compiler()
        changed = subprocess.check_output(
            ['git', 'diff', '--name-only', BASE, '--', 'src/ios'],
            cwd=ROOT, text=True).splitlines()
        paths = [p for p in changed if p.endswith('.swift') and (ROOT / p).is_file()]
        self.assertTrue(paths, 'No changed Swift files found')
        for path in paths:
            with self.subTest(path=path):
                result = subprocess.run([compiler, '-frontend', '-parse', path],
                                        cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_question_state_compiles_and_resumes_once(self):
        compiler = self.compiler()
        vm = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
        tools = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift').read_text()
        start = vm.index('    final class ActiveQuestionCard {')
        end = vm.index('\n    }\n\n    /// [T-115-ask-card] The user submitted', start) + len('\n    }')
        card = vm[start:end]
        start = tools.index('private final class AskUserContinuationState:')
        end = tools.index('\nextension AIChatViewModel', start)
        bridge = tools[start:end]
        harness = r'''
@main struct Run {
    static func main() async {
        let earlyCancel = AskUserContinuationState()
        earlyCancel.resume(nil)
        let early: String? = await withCheckedContinuation { earlyCancel.install($0) }
        precondition(early == nil)

        let answered = AskUserContinuationState()
        let answer: String? = await withCheckedContinuation { cont in
            answered.install(cont)
            answered.resume("answer")
            answered.resume(nil)
            answered.resume("duplicate")
        }
        precondition(answer == "answer")

        for _ in 0..<500 {
            let state = AskUserContinuationState()
            let _: String? = await withCheckedContinuation { cont in
                DispatchQueue.concurrentPerform(iterations: 3) { i in
                    if i == 0 { state.install(cont) }
                    else { state.resume(nil) }
                }
            }
        }

        let card = ActiveQuestionCard(toolUseId: "test", questions: [],
                                     timeoutAt: Date(), resume: { _ in })
        let publishedCard = card
        card.timeoutTask = Task {
            do { try await Task.sleep(nanoseconds: 60_000_000_000) }
            catch { return }
        }
        precondition(publishedCard === card)
        precondition(publishedCard.timeoutTask != nil)
        publishedCard.timeoutTask?.cancel()
        precondition(card.timeoutTask?.isCancelled == true)
        await card.timeoutTask?.value
        print("ask-user-state-ok")
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='minis-feature-compile-') as tmp:
            source = Path(tmp) / 'QuestionState.swift'
            binary = Path(tmp) / 'question-state'
            source.write_text('import Foundation\nimport Dispatch\n' + bridge + '\n' + card + harness)
            result = subprocess.run([compiler, '-swift-version', '5', '-parse-as-library',
                                     str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ask-user-state-ok', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
