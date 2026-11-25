#!/usr/bin/env python3
"""Durable feed transaction and exact-source resume. No release/tag deletions."""
from pathlib import Path
import base64
from contextlib import contextmanager
import hashlib
import json
import os
import re
import signal
import app_release as p


def raw_manifest(m):
    return (json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def record_name(build):
    return f'update-build{build}.transaction.json'


def asset_id(r, ident):
    matches = [a for a in r['assets'] if a['id'] == ident]
    p.need(len(matches) == 1, 'transaction asset ID missing/duplicated')
    return matches[0]


def record(host, c, commit):
    a = p.named(host.release(), record_name(c['build']), required=False)
    if not a:
        return None
    raw = host.content(a)
    p.check_asset(a, len(raw), digest(raw))
    t = json.loads(raw)
    p.need(t['repository'] == p.REPOSITORY and t['channel'] == p.CHANNEL, 'wrong transaction destination')
    p.need(t['commit'] == commit and re.fullmatch('[a-f0-9]{40}', commit) is not None, 'transaction source mismatch')
    m = p.validate_manifest(t['manifest'])
    p.need(all(m[k] == c[k] for k in ('build', 'version', 'notes')) and m['ipa'] == p.ipa_name(c), 'transaction build/config mismatch')
    old_raw = base64.b64decode(t['old_manifest_b64'], validate=True)
    old = p.validate_manifest(json.loads(old_raw))
    p.need(m['build'] > old['build'], 'transaction cannot downgrade')
    r = host.release()
    p.need(r['id'] == t['release_id'] and host.tag() == t['tag_object'], 'release/tag transaction identity mismatch')
    p.check_asset(asset_id(r, t['old_asset_id']), len(old_raw), digest(old_raw))
    p.check_asset(p.named(r, old['ipa']), old['size'], old['sha256'])
    p.check_asset(asset_id(r, t['new_ipa_id']), m['size'], m['sha256'])
    p.check_asset(asset_id(r, t['ready_asset_id']), len(raw_manifest(m)), digest(raw_manifest(m)))
    return t


def recover_old(host, t):
    """Only undo this transaction's exact ready ID; never overwrite another writer."""
    r = host.release()
    p.need(r['id'] == t['release_id'] and host.tag() == t['tag_object'], 'recovery destination changed')
    old_raw = base64.b64decode(t['old_manifest_b64'], validate=True)
    old = asset_id(r, t['old_asset_id'])
    ready = asset_id(r, t['ready_asset_id'])
    p.check_asset(old, len(old_raw), digest(old_raw))
    p.check_asset(ready, len(raw_manifest(t['manifest'])), digest(raw_manifest(t['manifest'])))
    current = p.named(r, 'latest.json', required=False)
    if current and current['id'] == t['old_asset_id']:
        return 'old_feed_already_live'
    if current and current['id'] != t['ready_asset_id']:
        raise ValueError('another live publication exists; refusing rollback over it')
    if current:
        # A response can be lost after server-side success. Inspect server state
        # regardless of whether the rename call raised before restoring old.
        try:
            host.rename(current, t['ready_name'])
        finally:
            if p.named(host.release(), 'latest.json', required=False) is None:
                host.rename(old, 'latest.json')
    else:
        host.rename(old, 'latest.json')
    _, a, restored, _ = p.live(host)
    p.need(a['id'] == t['old_asset_id'] and restored == old_raw, 'rollback readback failed')
    try:
        host.metadata(r, t['old_metadata'])
    except Exception:
        return 'old_feed_restored_metadata_retry_required'
    return 'old_feed_restored'


@contextmanager
def trap_signals():
    def abort(signum, _frame):
        raise KeyboardInterrupt('publication interrupted by signal')
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for s in previous:
            signal.signal(s, abort)
        yield
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def save_state(output, **state):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    state['device_tested'] = False
    file = out / 'publication.json'
    tmp = file.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(file)
    return state


def verify_online(host, t, output):
    """An already-live asset is read-only: failed revalidation must not downgrade it.

    A fresh runner cannot infer completion from the previous runner's local file.
    Treat ready-already-live at entry conservatively as online, even if a prior
    runner died after activation; report a failed check but never rename/restore
    metadata in this path. Only this invocation's first activation may roll back.
    """
    m = t['manifest']
    raw = raw_manifest(m)
    try:
        _, active, live_raw, actual = p.live(host)
        p.need(active['id'] == t['ready_asset_id'] and live_raw == raw and actual == m,
               'already-online feed changed before revalidation')
        p.need(host.tag() == t['tag_object'], 'release tag changed')
        p.need(host.public_manifest() == raw, 'public App feed mismatch')
        host.public_ipa(m)
        _, final, final_raw, final_manifest = p.live(host)
        p.need(final['id'] == t['ready_asset_id'] and final_raw == raw and final_manifest == m,
               'already-online feed changed during revalidation')
        return save_state(output, phase='PUBLISHED_PUBLIC_FEED_VERIFIED', build=m['build'], commit=t['commit'],
                          mode='verify_only_already_online',
                          manifest_url=f'https://github.com/{p.REPOSITORY}/releases/download/{p.CHANNEL}/latest.json',
                          ipa_sha256=m['sha256'], ipa_bytes=m['size'], old_assets_retained=True)
    except BaseException:
        try:
            save_state(output, phase='PUBLICATION_REVERIFY_FAILED', build=m['build'], commit=t['commit'],
                       rollback='not_attempted_already_online')
        except OSError:
            pass
        raise


def activate(host, t, output):
    m = t['manifest']
    raw = raw_manifest(m)
    entry = p.named(host.release(), 'latest.json', required=False)
    if entry is not None and entry['id'] == t['ready_asset_id']:
        return verify_online(host, t, output)
    p.need(entry is None or entry['id'] == t['old_asset_id'],
           'newer or unrelated live publication exists; no mutations permitted')
    save_state(output, phase='transaction_verified', build=m['build'], commit=t['commit'])
    try:
        r = host.release()
        old = asset_id(r, t['old_asset_id'])
        ready = asset_id(r, t['ready_asset_id'])
        current = p.named(r, 'latest.json', required=False)
        if current is None:
            recover_old(host, t)
            r = host.release()
            current = p.named(r, 'latest.json')
        if current['id'] == old['id']:
            p.need(host.content(current) == base64.b64decode(t['old_manifest_b64']), 'live old feed changed')
            backup_name = f'latest-build{json.loads(base64.b64decode(t["old_manifest_b64"]))["build"]}.json'
            backup = p.named(r, backup_name, required=False)
            if backup:
                p.check_asset(backup, current['size'], current['digest'].removeprefix('sha256:'))
                backup_name = f'latest-build{json.loads(base64.b64decode(t["old_manifest_b64"]))["build"]}.previous-{old["id"]}.json'
            host.rename(old, backup_name)
            host.rename(ready, 'latest.json')
        else:
            p.need(current['id'] == ready['id'], 'newer or unrelated live publication exists')
        _, active, live_raw, actual = p.live(host)
        p.need(active['id'] == ready['id'] and live_raw == raw and actual == m, 'activation readback mismatch')
        save_state(output, phase='switched_public_verification_pending', build=m['build'], commit=t['commit'])
        host.metadata(r, {'name': f'测试版 {m["version"]} / build {m["build"]}',
                          'body': m['notes'] + '\n\nApp commit ' + t['commit']
                          + ' · CI ' + os.environ.get('GITHUB_RUN_ID', '')
                          + '\n保留旧版回退包；固定标签锚点不是当前源码。未代安装或真机验收。', 'prerelease': True})
        p.need(host.tag() == t['tag_object'], 'release tag changed')
        p.need(host.public_manifest() == raw, 'public App feed mismatch')
        host.public_ipa(m)
        _, final, final_raw, final_manifest = p.live(host)
        p.need(final['id'] == ready['id'] and final_raw == raw and final_manifest == m, 'final feed mismatch')
        return save_state(output, phase='PUBLISHED_PUBLIC_FEED_VERIFIED', build=m['build'], commit=t['commit'],
                          manifest_url=f'https://github.com/{p.REPOSITORY}/releases/download/{p.CHANNEL}/latest.json',
                          ipa_sha256=m['sha256'], ipa_bytes=m['size'], old_assets_retained=True)
    except BaseException:
        outcome = 'recovery_required_next_authorized_run'
        try:
            outcome = recover_old(host, t)
        except BaseException:
            # Durable record on Release allows the next authorized run to recover
            # the SAME asset IDs even after a runner is killed or loses networking.
            pass
        try:
            save_state(output, phase='PUBLICATION_FAILED', build=m['build'], commit=t['commit'], rollback=outcome)
        except OSError:
            pass
        raise


def publish(host, ipa, m, output, commit):
    p.need(re.fullmatch('[a-f0-9]{40}', commit) is not None, 'source commit missing')
    c = {k: m[k] for k in ('build', 'version', 'notes')}
    existing = record(host, c, commit)
    if existing:
        p.need(existing['manifest'] == m, 'staged transaction refers to other bytes')
        return activate(host, existing, output)
    r, old_asset, old_raw, old = p.live(host)
    p.need(p.newer_or_same(m, old), 'same build without matching source transaction cannot be republished')
    tag = host.tag()
    package = p.ensure_asset(host, Path(ipa), m['sha256'])
    ready_path = Path(output) / f'latest-build{m["build"]}.ready.json'
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.write_bytes(raw_manifest(m))
    ready = p.ensure_asset(host, ready_path, digest(ready_path.read_bytes()))
    # Stage immutable transaction before the first live-name mutation. Unlike a
    # local artifact this survives cancellation, runner loss and missing latest.
    t = {'schema': 1, 'repository': p.REPOSITORY, 'channel': p.CHANNEL,
         'release_id': r['id'], 'tag_object': tag, 'commit': commit, 'manifest': m,
        'old_asset_id': old_asset['id'], 'old_manifest_b64': base64.b64encode(old_raw).decode(),
         'old_metadata': {k: r.get(k, '' if k != 'prerelease' else True) for k in ('name', 'body', 'prerelease')},
         'new_ipa_id': package['id'], 'ready_asset_id': ready['id'], 'ready_name': ready_path.name}
    txfile = Path(output) / record_name(m['build'])
    txfile.write_text(json.dumps(t, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n')
    p.ensure_asset(host, txfile, p.sha(txfile))
    validated = record(host, c, commit)
    p.need(validated == t, 'durable transaction readback mismatch')
    _, now, current_raw, _ = p.live(host)
    p.need(now['id'] == old_asset['id'] and current_raw == old_raw, 'live feed changed while staging')
    return activate(host, t, output)


def prepare(host, c, env_file, commit, output):
    p.need(re.fullmatch('[a-f0-9]{40}', commit) is not None, 'source commit missing')
    t = record(host, c, commit)
    r = host.release()
    current = p.named(r, 'latest.json', required=False)
    if t:
        if current is None:
            recover_old(host, t)
        else:
            live_build = p.validate_manifest(json.loads(host.content(current)))['build']
            p.need(live_build <= c['build'], 'old transaction cannot replace a newer build')
            p.need(current['id'] in (t['old_asset_id'], t['ready_asset_id']), 'unrelated live publication')
        # Same source+build+hash transaction: verify/resume original bytes only.
        mode = 'resume'
    else:
        _, _, _, old = p.live(host)
        p.need(c['build'] > old['build'], 'increment the single app-release.json build; no same-build rebuild')
        mode = 'build'
    with Path(env_file).open('a') as f:
        f.write(f'APP_BUILD={c["build"]}\nAPP_IPA={p.ipa_name(c)}\nAPP_MODE={mode}\n')
    return mode


def resume(host, c, output, commit):
    t = record(host, c, commit)
    p.need(t is not None, 'exact-source publication transaction absent')
    return activate(host, t, output)
