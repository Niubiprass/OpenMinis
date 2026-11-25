#!/usr/bin/env python3
"""Actual publication code, synthetic IPA/evidence and fake GitHub only. No network/device."""
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest
import app_release as p


def encode(m):
    return (json.dumps(m, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


class Host:
    def __init__(self, old):
        self.assets = []
        self.bytes = {}
        self.events = []
        self.fail_upload = None
        self.fail_activate = False
        self.fail_after_backup = False
        self.cancel_activate = False
        self.public_bad = False
        self.head_bad = False
        self.tag_bad = False
        self._tag = {'type': 'commit', 'sha': 'a' * 40}
        self.add(old['ipa'], b'old IPA', old['sha256'], old['size'])
        self.add('latest.json', encode(old))

    def add(self, name, raw, digest=None, size=None):
        item = {'id': len(self.assets) + 10, 'name': name, 'state': 'uploaded',
                'digest': 'sha256:' + (digest or hashlib.sha256(raw).hexdigest()),
                'size': len(raw) if size is None else size}
        self.assets.append(item)
        self.bytes[item['id']] = raw
        return copy.deepcopy(item)

    def release(self):
        return {'id': 1, 'tag_name': p.CHANNEL, 'draft': False, 'assets': copy.deepcopy(self.assets)}

    def content(self, a):
        return self.bytes[a['id']]

    def upload(self, path):
        self.events.append(('upload', path.name))
        if self.fail_upload and self.fail_upload in path.name:
            raise RuntimeError('controlled upload failure')
        self.add(path.name, path.read_bytes())

    def rename(self, a, name):
        self.events.append(('rename', a['id'], name))
        is_activate = name == 'latest.json' and '.ready.json' in a['name']
        if is_activate and self.cancel_activate:
            raise KeyboardInterrupt('controlled cancellation')
        if is_activate and self.fail_activate:
            raise RuntimeError('controlled rename failure')
        target = next(x for x in self.assets if x['id'] == a['id'])
        if any(x['name'] == name and x['id'] != a['id'] for x in self.assets):
            raise RuntimeError('duplicate live name')
        target['name'] = name
        if name.endswith('.json') and name.startswith('latest-build') and self.fail_after_backup:
            self.fail_after_backup = False
            raise RuntimeError('response lost after successful backup rename')
        return copy.deepcopy(target)

    def metadata(self, r, body):
        self.events.append(('metadata', body['name']))

    def tag(self):
        if self.tag_bad and any(e[0] == 'metadata' for e in self.events):
            return {'type': 'commit', 'sha': 'b' * 40}
        return self._tag

    def public_manifest(self):
        if self.public_bad:
            return b'old cached body'
        return self.content(p.named(self.release(), 'latest.json'))

    def public_ipa(self, m):
        self.events.append(('public_head', m['ipa']))
        if self.head_bad:
            raise ValueError('wrong public IPA size')


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = {'build': 386, 'version': '1.16', 'notes': '受控测试，不是真实发布'}
        self.ipa = self.root / p.ipa_name(self.c)
        self.ipa.write_bytes(b'PK\x03\x04 synthetic bytes only')
        self.m = dict(self.c, ipa=self.ipa.name, size=self.ipa.stat().st_size, sha256=p.sha(self.ipa))
        self.old = dict(self.m, build=384, ipa='Minis-1.16-build384-Daily-Actions-iOS15.5.ipa', sha256='f' * 64, size=90409498)
        self.host = Host(self.old)
        self.out = self.root / 'out'
        self.commit = 'c' * 40
        self.evidence = {'ipa': self.ipa.name, 'commit': self.commit, 'bytes': self.m['size'], 'sha256': self.m['sha256'],
                         'CRC': 'PASS', 'codesign_deep_strict': 'PASS', 'entitlements_exact_source': True,
                         'info': {'CFBundleIdentifier': 'com.openminis.app', 'CFBundleExecutable': 'Minis',
                                  'CFBundleShortVersionString': '1.16', 'CFBundleVersion': '160652',
                                  'MinisBuildNumber': '386', 'MinimumOSVersion': '15.5'},
                         'images': [{'path': 'Minis', 'slices': [{'codeDirectories': [{'codePagesVerified': True}]}]}],
                         'tampered_codepages_rejected': [{'image': 'Minis', 'rejected': 'code page 1 rejected'}]}
        self.sums = self.root / 'SHA256SUMS'
        self.sums.write_text(f'{self.m["sha256"]}  {self.ipa.name}\n')

    def tearDown(self):
        self.tmp.cleanup()

    def run_publish(self):
        return p.publish(self.host, self.ipa, self.m, self.out, self.commit)

    def test_success_stages_before_switch_and_preserves_old(self):
        initial_bytes = dict(self.host.bytes)
        self.assertEqual(self.run_publish()['phase'], 'PUBLISHED_PUBLIC_FEED_VERIFIED')
        names = {a['name'] for a in self.host.assets}
        self.assertIn(self.old['ipa'], names)
        self.assertIn('latest-build384.json', names)
        self.assertEqual(initial_bytes[11], self.host.bytes[11])
        events = self.host.events
        self.assertLess(events.index(('upload', self.ipa.name)), next(i for i, e in enumerate(events) if e[0] == 'rename'))
        self.assertEqual(json.loads(self.host.public_manifest()), self.m)
        self.assertEqual(self.host.tag(), {'type': 'commit', 'sha': 'a' * 40})

    def test_idempotent_retry_never_reuploads_or_switches(self):
        self.run_publish()
        self.host.events.clear()
        self.run_publish()
        self.assertFalse(any(e[0] in ('upload', 'rename') for e in self.host.events))
        self.assertIn(('public_head', self.m['ipa']), self.host.events)

    def test_ipa_upload_failure_keeps_old(self):
        self.host.fail_upload = '.ipa'
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)
        self.assertFalse(any(e[0] == 'rename' for e in self.host.events))

    def test_ready_upload_failure_keeps_old(self):
        self.host.fail_upload = '.ready.json'
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)

    def test_activate_failure_restores_old_name(self):
        self.host.fail_activate = True
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)

    def test_cancel_restores_old_name(self):
        self.host.cancel_activate = True
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)

    def test_lost_backup_response_restores_old_name(self):
        self.host.fail_after_backup = True
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)

    def test_existing_backup_remains_untouched(self):
        backup = self.host.add('latest-build384.json', encode(self.old))
        self.run_publish()
        self.assertEqual(self.host.content(backup), encode(self.old))
        self.assertIn('latest-build384.previous-11.json', {a['name'] for a in self.host.assets})

    def test_existing_mismatching_asset_fails_before_live_switch(self):
        self.host.add(self.ipa.name, b'bad bytes')
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)

    def test_old_run_cannot_downgrade(self):
        self.m['build'] = 383
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertFalse(self.host.events)

    def test_same_build_with_different_bytes_rejected(self):
        self.m['build'] = 384
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertFalse(self.host.events)

    def test_changed_feed_during_staging_is_not_overwritten(self):
        original = self.host.upload
        def concurrent(path):
            original(path)
            if path.name.endswith('.ready.json'):
                current = p.named(self.host.release(), 'latest.json')
                self.host.bytes[current['id']] = encode(dict(self.old, build=400))
                next(a for a in self.host.assets if a['id'] == current['id'])['digest'] = 'sha256:' + hashlib.sha256(self.host.bytes[current['id']]).hexdigest()
        self.host.upload = concurrent
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertEqual(json.loads(self.host.public_manifest())['build'], 400)
        self.assertFalse(any(e[0] == 'rename' for e in self.host.events))

    def test_public_manifest_failure_not_reported_as_success(self):
        self.host.public_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()
        state = json.loads((self.out / 'publication.json').read_text())
        self.assertNotEqual(state['phase'], 'PUBLISHED_PUBLIC_FEED_VERIFIED')

    def test_public_ipa_failure_not_reported_as_success(self):
        self.host.head_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assertNotEqual(json.loads((self.out / 'publication.json').read_text())['phase'], 'PUBLISHED_PUBLIC_FEED_VERIFIED')

    def test_tag_mutation_rejected(self):
        self.host.tag_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()

    def test_verifier_positive(self):
        self.assertEqual(p.verify_ipa(self.ipa, self.evidence, self.sums, self.c, self.commit), self.m)

    def test_evidence_tamper_source_permissions_and_build_negatives(self):
        variants = [('sha256', 'e' * 64), ('bytes', 1), ('commit', 'b' * 40),
                    ('CRC', 'FAIL'), ('codesign_deep_strict', 'FAIL'),
                    ('entitlements_exact_source', False), ('images', []), ('tampered_codepages_rejected', [])]
        for key, value in variants:
            with self.subTest(key=key):
                e = copy.deepcopy(self.evidence)
                e[key] = value
                with self.assertRaises(ValueError):
                    p.verify_ipa(self.ipa, e, self.sums, self.c, self.commit)
        for key, value in [('CFBundleIdentifier', 'wrong.app'), ('MinisBuildNumber', '385'), ('CFBundleVersion', '386'), ('MinimumOSVersion', '16.0')]:
            e = copy.deepcopy(self.evidence)
            e['info'][key] = value
            with self.subTest(info=key), self.assertRaises(ValueError):
                p.verify_ipa(self.ipa, e, self.sums, self.c, self.commit)
        self.ipa.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            p.verify_ipa(self.ipa, self.evidence, self.sums, self.c, self.commit)

    def test_bad_signature_page_cannot_publish(self):
        self.evidence['images'][0]['slices'][0]['codeDirectories'][0]['codePagesVerified'] = False
        with self.assertRaises(ValueError):
            p.verify_ipa(self.ipa, self.evidence, self.sums, self.c, self.commit)

    def test_workflow_context_cannot_publish_other_ref(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': p.REPOSITORY, 'GITHUB_REF': p.BRANCH, 'GITHUB_EVENT_NAME': 'push'}
        p.validate_context(env)
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'elsewhere/repo'),
                           ('GITHUB_REF', 'refs/heads/some-feature'), ('GITHUB_EVENT_NAME', 'pull_request')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                p.validate_context(dict(env, **{key: value}))

    def test_config_rejects_invalid_build_and_marketing_version(self):
        file = self.root / 'config.json'
        for c in (dict(self.c, build=True), dict(self.c, build=0), dict(self.c, build=-1),
                  dict(self.c, version='1.17'), dict(self.c, notes='')):
            file.write_text(json.dumps(c))
            with self.subTest(config=c), self.assertRaises(ValueError):
                p.config(file)

    def test_prepare_writes_only_single_source_version(self):
        env = self.root / 'GITHUB_ENV'
        p.prepare(self.host, self.c, env, self.commit, self.out)
        self.assertEqual(env.read_text(), 'APP_BUILD=386\nAPP_IPA=Minis-1.16-build386-iOS15.5.ipa\nAPP_MODE=build\n')
        self.c['build'] = 384
        with self.assertRaises(ValueError):
            p.prepare(self.host, self.c, env, self.commit, self.out)

    def test_asset_path_query_and_unicode_rejected(self):
        for name in ('../file.ipa', 'bad?x.ipa', 'bad#x.ipa', 'a%20b.ipa', '中文.ipa', 'x\\file.ipa', 'x' * 201, ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.validate_manifest(dict(self.m, ipa=name))


if __name__ == '__main__':
    unittest.main(verbosity=2)
