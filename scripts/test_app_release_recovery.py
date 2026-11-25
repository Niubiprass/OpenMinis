#!/usr/bin/env python3
"""Actual recovery/resume functions with fake Release; real signals, no network."""
from pathlib import Path
import json
import os
import signal
import unittest
import app_release as p
import app_release_transaction as tx
from test_app_release import PublicationTests as Base, Host


class RecoveryTests(Base):
    # Inherits the original 22 checks; these extend rather than replace them.
    def assert_old(self):
        self.assertEqual(json.loads(self.host.content(p.named(self.host.release(), 'latest.json'))), self.old)
        state = json.loads((self.out / 'publication.json').read_text())
        self.assertEqual(state['phase'], 'PUBLICATION_FAILED')

    def test_activate_success_response_lost_rolls_back(self):
        original = self.host.rename
        def lost(a, name):
            value = original(a, name)
            if name == 'latest.json' and a['name'].endswith('.ready.json'):
                raise RuntimeError('response lost after successful activation')
            return value
        self.host.rename = lost
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assert_old()

    def test_metadata_failure_rolls_back(self):
        self.host.metadata = lambda *args: (_ for _ in ()).throw(RuntimeError('metadata unavailable'))
        with self.assertRaises(RuntimeError):
            self.run_publish()
        self.assert_old()

    def test_cancel_after_activation_rolls_back(self):
        def cancel(*args):
            raise KeyboardInterrupt('cancel after activation')
        self.host.metadata = cancel
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        self.assert_old()

    def test_public_get_failure_restores_old_feed(self):
        self.host.public_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assert_old()

    def test_public_head_failure_restores_old_feed(self):
        self.host.head_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assert_old()

    def test_real_sigterm_between_renames_restores_old(self):
        original = self.host.rename
        def terminate(a, name):
            value = original(a, name)
            if name == 'latest-build384.json':
                os.kill(os.getpid(), signal.SIGTERM)
            return value
        self.host.rename = terminate
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        self.assert_old()
        # Signal handler must also have been restored by the public wrapper.
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)

    def test_real_sigint_after_activation_restores_old(self):
        original = self.host.rename
        def interrupt(a, name):
            value = original(a, name)
            if name == 'latest.json' and a['name'].endswith('.ready.json'):
                os.kill(os.getpid(), signal.SIGINT)
            return value
        self.host.rename = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        self.assert_old()

    def test_missing_latest_after_runner_loss_recovers_by_exact_transaction(self):
        self.run_publish()
        t = tx.record(self.host, self.c, self.commit)
        # Simulate persisted server state after uncatchable process loss. No new
        # full IPA is read/created by prepare/resume below.
        current = p.named(self.host.release(), 'latest.json')
        self.host.rename(current, t['ready_name'])
        self.assertIsNone(p.named(self.host.release(), 'latest.json', required=False))
        self.host.events.clear()
        mode = p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out)
        self.assertEqual(mode, 'resume')
        self.assertEqual(json.loads(self.host.public_manifest()), self.old)
        self.ipa.unlink()
        self.assertEqual(p.resume(self.host, self.c, self.out, self.commit)['phase'], 'PUBLISHED_PUBLIC_FEED_VERIFIED')
        self.assertEqual(json.loads(self.host.public_manifest()), self.m)
        self.assertFalse(any(e[0] == 'upload' for e in self.host.events))

    def test_whole_entry_prepare_failure_rerun_resumes_original_bytes(self):
        env = self.root / 'env'
        self.assertEqual(p.prepare(self.host, self.c, env, self.commit, self.out), 'build')
        self.host.head_bad = True
        with self.assertRaises(ValueError):
            self.run_publish()
        self.assert_old()
        self.host.head_bad = False
        self.host.events.clear()
        env.write_text('')
        self.assertEqual(p.prepare(self.host, self.c, env, self.commit, self.out), 'resume')
        self.assertIn('APP_MODE=resume', env.read_text())
        self.ipa.unlink()
        self.assertEqual(p.resume(self.host, self.c, self.out, self.commit)['phase'], 'PUBLISHED_PUBLIC_FEED_VERIFIED')
        self.assertFalse(any(e[0] == 'upload' for e in self.host.events))

    def test_same_source_completed_whole_workflow_is_verify_only(self):
        self.run_publish()
        self.host.events.clear()
        self.assertEqual(p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out), 'resume')
        p.resume(self.host, self.c, self.out, self.commit)
        self.assertFalse(any(e[0] in ('upload', 'rename') for e in self.host.events))

    def test_resume_wrong_source_or_modified_transaction_fails_closed(self):
        self.run_publish()
        with self.assertRaises(ValueError):
            p.prepare(self.host, self.c, self.root / 'env', 'b' * 40, self.out)
        t = p.named(self.host.release(), tx.record_name(self.c['build']))
        raw = self.host.bytes[t['id']] + b' '
        self.host.bytes[t['id']] = raw  # Wrong size/digest as well as modified bytes.
        with self.assertRaises(ValueError):
            p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out)

    def test_online_resume_get_failure_never_downgrades(self):
        self.run_publish()
        self.out = self.root / 'fresh-runner-get'
        self.assertEqual(p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out), 'resume')
        self.host.events.clear()
        self.host.public_bad = True
        with self.assertRaises(ValueError):
            p.resume(self.host, self.c, self.out, self.commit)
        self.assertEqual(p.live(self.host)[3], self.m)
        self.assertFalse(any(e[0] in ('rename', 'metadata', 'upload') for e in self.host.events))
        self.assertEqual(json.loads((self.out / 'publication.json').read_text())['phase'], 'PUBLICATION_REVERIFY_FAILED')

    def test_online_resume_head_failure_never_downgrades(self):
        self.run_publish()
        self.out = self.root / 'fresh-runner-head'
        self.assertEqual(p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out), 'resume')
        self.host.events.clear()
        self.host.head_bad = True
        with self.assertRaises(ValueError):
            p.resume(self.host, self.c, self.out, self.commit)
        self.assertEqual(p.live(self.host)[3], self.m)
        self.assertFalse(any(e[0] in ('rename', 'metadata', 'upload') for e in self.host.events))

    def test_online_resume_does_not_write_metadata_even_if_metadata_would_fail(self):
        self.run_publish()
        self.out = self.root / 'fresh-runner-metadata'
        self.host.events.clear()
        def forbidden(*args):
            self.fail('already-online revalidation must not change release metadata')
        self.host.metadata = forbidden
        self.assertEqual(p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out), 'resume')
        result = p.resume(self.host, self.c, self.out, self.commit)
        self.assertEqual(result['mode'], 'verify_only_already_online')
        self.assertEqual(p.live(self.host)[3], self.m)
        self.assertFalse(any(e[0] in ('rename', 'metadata', 'upload') for e in self.host.events))

    def test_online_resume_real_signal_does_not_downgrade(self):
        self.run_publish()
        self.out = self.root / 'fresh-runner-signal'
        self.assertEqual(p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out), 'resume')
        self.host.events.clear()
        def cancel(_manifest):
            os.kill(os.getpid(), signal.SIGTERM)
        self.host.public_ipa = cancel
        with self.assertRaises(KeyboardInterrupt):
            p.resume(self.host, self.c, self.out, self.commit)
        self.assertEqual(p.live(self.host)[3], self.m)
        self.assertFalse(any(e[0] in ('rename', 'metadata', 'upload') for e in self.host.events))

    def test_resume_cannot_replace_a_later_feed(self):
        self.run_publish()
        old = p.named(self.host.release(), 'latest.json')
        self.host.rename(old, 'after386-backup.json')
        self.host.add('latest.json', tx.raw_manifest(dict(self.m, build=400)))
        self.host.events.clear()
        with self.assertRaises(ValueError):
            p.prepare(self.host, self.c, self.root / 'env', self.commit, self.out)
        self.assertFalse(self.host.events)
        self.assertEqual(json.loads(self.host.public_manifest())['build'], 400)


if __name__ == '__main__':
    # Explicit loader avoids running imported Base a second time in this file.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
