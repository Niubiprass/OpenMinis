#!/usr/bin/env python3
"""Single active App compiler; preserve all build384 native checks. No CI trigger."""
from pathlib import Path
import json
import re
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / '.github/workflows/openminis-app.yml'


class WorkflowContract(unittest.TestCase):
    def setUp(self):
        self.text = WF.read_text()
        self.wf = yaml.load(self.text, Loader=yaml.BaseLoader)
        self.steps = self.wf['jobs']['build']['steps']

    def test_one_compiler_only(self):
        compilers = []
        for path in (ROOT / '.github/workflows').glob('*.y*ml'):
            if any(token in path.read_text() for token in ('xcodebuild -project', 'CODE_SIGNING_ALLOWED=NO', 'app_release.py publish')):
                compilers.append(path.name)
        self.assertEqual(compilers, ['openminis-app.yml'])
        for name in ('build-ipa.yml', 'build-trollstore.yml', 'port-and-build.yml', 'ios15-lyrics-qq.yml', 'ios15-v64-repair.yml'):
            self.assertFalse((ROOT / '.github/workflows' / name).exists())
            self.assertTrue((ROOT / '.github/archived-workflows' / (name + '.disabled')).is_file())

    def test_fixed_branch_and_fixed_concurrency(self):
        self.assertEqual(self.wf['on']['push']['branches'], ['ios15-160652-four-features'])
        self.assertIn('workflow_dispatch', self.wf['on'])
        self.assertEqual(self.wf['concurrency'], {'group': 'openminis-app-beta-latest', 'cancel-in-progress': 'false'})
        job_if = self.wf['jobs']['build']['if']
        self.assertIn("github.ref == 'refs/heads/ios15-160652-four-features'", job_if)
        self.assertNotIn('github.run_number', self.text)
        self.assertNotIn('LYRICS_BUILD', self.text)
        self.assertNotIn('Daily-Actions', self.text)
        self.assertIn("'deps/**'", self.text)
        self.assertIn("'scripts/**'", self.text)

    def test_version_configuration_is_only_source(self):
        c = json.loads((ROOT / 'scripts/app-release.json').read_text())
        self.assertEqual(c['version'], '1.16')
        self.assertGreater(c['build'], 385)
        self.assertIn('app_release.py prepare', self.text)
        self.assertIn('Set :MinisBuildNumber ${APP_BUILD}', self.text)
        self.assertIn('CURRENT_PROJECT_VERSION=160652', self.text)
        self.assertIn('${{ env.APP_IPA }}', self.text)

    def test_failed_gates_cannot_publish_and_evidence_is_preserved(self):
        gate = next(x for x in self.steps if x.get('id') == 'source_gate')
        self.assertEqual(gate['continue-on-error'], 'false')
        package = next(x for x in self.steps if x.get('name') == 'Package without adding elevated entitlements')['run']
        self.assertIn('${{ steps.source_gate.outcome }}', package)
        self.assertIn('exit 1', package)
        self.assertLess(package.index('Set :MinisBuildNumber'), package.index('python3 scripts/v64r_package.py'))
        self.assertLess(package.index('python3 scripts/v64r_package.py'), package.index('zip -qry'))
        self.assertLess(package.index('codesign --verify --deep --strict'), package.index('ci_verify_lyrics_ipa.py'))
        publish = next(x for x in self.steps if x.get('name') == 'Publish beta release for the in-app updater')
        self.assertEqual(publish['if'], "success() && env.APP_MODE == 'build'")
        resume = next(x for x in self.steps if x.get('name') == 'Resume verified publication without rebuilding')
        self.assertEqual(resume['if'], "env.APP_MODE == 'resume'")
        self.assertIn('app_release.py resume', resume['run'])
        for name in ('Verify fixed source (never fetch or re-port upstream)', 'Build native libraries',
                     'Build fixed v64 repair source', 'Package without adding elevated entitlements', 'Upload IPA'):
            step = next(x for x in self.steps if x.get('name') == name)
            self.assertEqual(step['if'], "env.APP_MODE == 'build'", name)
        self.assertEqual(publish['run'].strip().splitlines()[-1], 'python3 scripts/app_release.py publish')
        self.assertNotIn('gh release delete', self.text)
        self.assertTrue(any(x.get('if') == 'always()' and x.get('name') == 'Upload publication evidence' for x in self.steps))
        evidence = next(x for x in self.steps if x.get('name') == 'Upload build evidence')['with']['path']
        self.assertIn('ipa-verification.json', evidence)
        self.assertIn('SHA256SUMS', evidence)

    def test_all_build384_source_gate_commands_preserved(self):
        old = yaml.load((ROOT / '.github/archived-workflows/ios15-lyrics-qq.yml.disabled').read_text(), Loader=yaml.BaseLoader)
        previous = next(x['run'] for x in old['jobs']['build']['steps'] if x.get('id') == 'source_gate')
        current = next(x['run'] for x in self.steps if x.get('id') == 'source_gate')
        commands = lambda s: [x.strip() for x in s.splitlines() if x.strip() and not x.lstrip().startswith('#')]
        for cmd in commands(previous):
            self.assertIn(cmd, commands(current), cmd)
        self.assertIn('python3 scripts/test_app_release.py', commands(current))
        self.assertIn('python3 scripts/test_app_release_recovery.py', commands(current))
        self.assertIn('"$RUNNER_TEMP/openminis-workflow-tools/bin/python" scripts/test_single_app_workflow.py', commands(current))
        setup = next(x['run'] for x in self.steps if x.get('name') == 'Install isolated workflow-check dependency')
        self.assertIn('PyYAML==6.0.3', setup)
        self.assertNotIn('GITHUB_PATH', setup)  # Do not replace the Python used by old source/native gates.

    def test_shell_steps_parse_without_execution(self):
        for step in self.steps:
            if 'run' not in step:
                continue
            # Replace Actions expressions, not shell variables, for bash -n only.
            script = re.sub(r'\$\{\{.*?\}\}', 'ACTION_VALUE', step['run'])
            proc = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, step.get('name', '?') + ': ' + proc.stderr)

    def test_upstream_watcher_does_not_compile_or_reopen_legacy(self):
        text = (ROOT / '.github/workflows/upstream-watch.yml').read_text()
        self.assertIn('.github/archived-workflows/port-and-build.yml.disabled', text)
        self.assertNotIn('xcodebuild', text)
        self.assertNotIn('Actions → iOS15 移植并打包 IPA', text)
        self.assertIn('ios15-160652-four-features', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
