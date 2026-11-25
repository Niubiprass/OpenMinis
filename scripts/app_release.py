#!/usr/bin/env python3
"""One OpenMinis beta feed. Called only by the authorized GitHub workflow.
Pure policy functions and fake-host tests are portable; no device/installer API.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.request
import uuid

REPOSITORY = 'Niubiprass/OpenMinis'
BRANCH = 'refs/heads/ios15-160652-four-features'
CHANNEL = 'beta-latest'
ROOT = Path(__file__).resolve().parents[1]


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while data := f.read(1024 * 1024):
            h.update(data)
    return h.hexdigest()


def asset_name(value):
    return (isinstance(value, str) and 0 < len(value.encode()) <= 200
            and re.fullmatch(r'[A-Za-z0-9._-]+', value) is not None
            and value not in ('.', '..'))


def config(path):
    c = json.loads(Path(path).read_text())
    need(set(c) == {'build', 'version', 'notes'}, 'release config keys')
    need(type(c['build']) is int and 0 < c['build'] < 2**53, 'release build must be a positive integer')
    need(c['version'] == '1.16', 'marketing version requires a separate reviewed upgrade')
    need(isinstance(c['notes'], str) and 0 < len(c['notes'].encode()) <= 32768, 'release notes')
    return c


def ipa_name(c):
    return f'Minis-{c["version"]}-build{c["build"]}-iOS15.5.ipa'


def validate_manifest(m):
    need(set(m) == {'build', 'version', 'notes', 'ipa', 'sha256', 'size'}, 'manifest keys')
    need(type(m['build']) is int and m['build'] > 0, 'manifest build')
    need(type(m['size']) is int and m['size'] >= 4, 'manifest size')
    need(asset_name(m['ipa']) and m['ipa'].lower().endswith('.ipa'), 'manifest IPA asset')
    need(isinstance(m['sha256'], str) and re.fullmatch('[a-f0-9]{64}', m['sha256']) is not None, 'manifest SHA')
    need(isinstance(m['version'], str) and 0 < len(m['version'].encode()) <= 128, 'manifest version')
    need(isinstance(m['notes'], str) and len(m['notes'].encode()) <= 32768, 'manifest notes')
    return m


def validate_context(env):
    need(env.get('GITHUB_ACTIONS') == 'true', 'publication is GitHub CI only')
    need(env.get('GITHUB_REPOSITORY') == REPOSITORY, 'wrong repository')
    need(env.get('GITHUB_REF') == BRANCH, 'only the fixed App release branch may publish')
    need(env.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'wrong event')


def newer_or_same(m, old):
    validate_manifest(old)
    need(m['build'] >= old['build'], 'an older build cannot replace the live feed')
    if m['build'] == old['build']:
        need(m == old, 'the same build must never refer to different bytes or metadata')
        return False
    return True


def verify_ipa(ipa, evidence, sums, c, commit):
    """Bind CI-produced actual-IPA verification to the exact published bytes."""
    p = Path(ipa)
    need(p.name == ipa_name(c), 'wrong versioned IPA filename')
    need(evidence['ipa'] == p.name and evidence['commit'] == commit, 'evidence source/filename mismatch')
    need(re.fullmatch('[a-f0-9]{40}', commit) is not None, 'source commit')
    need(evidence['bytes'] == p.stat().st_size and evidence['sha256'] == sha(p), 'IPA evidence size/hash mismatch')
    need(Path(sums).read_text().strip() == f'{evidence["sha256"]}  {p.name}', 'CI SHA256SUMS mismatch')
    info = evidence['info']
    need(info['CFBundleIdentifier'] == 'com.openminis.app' and info['CFBundleExecutable'] == 'Minis', 'App identity')
    need(info['CFBundleShortVersionString'] == c['version'] and str(info['MinisBuildNumber']) == str(c['build']), 'App version/build')
    need(str(info['CFBundleVersion']) == '160652' and info['MinimumOSVersion'] == '15.5', 'App baseline changed')
    need(evidence['CRC'] == evidence['codesign_deep_strict'] == 'PASS', 'IPA CRC/signature verification failed')
    need(evidence['entitlements_exact_source'] is True, 'source entitlements mismatch')
    images = evidence['images']
    need(images and len({i['path'] for i in images}) == len(images) and any(i['path'] == 'Minis' for i in images), 'Mach-O images missing/duplicated')
    count = 0
    for image in images:
        need(image['slices'], 'missing Mach-O slice')
        for part in image['slices']:
            count += 1
            need(part['codeDirectories'] and all(d['codePagesVerified'] is True for d in part['codeDirectories']), 'code page verification failed')
    negatives = evidence['tampered_codepages_rejected']
    need(len(negatives) == count and sorted(i['image'] for i in negatives) == sorted(i['path'] for i in images for _ in i['slices']), 'tamper coverage missing')
    need(all('code page' in i['rejected'] for i in negatives), 'tamper negative did not reach code page check')
    return validate_manifest(dict(c, ipa=p.name, sha256=evidence['sha256'], size=evidence['bytes']))


class GitHub:
    """Use existing official gh CLI; tokens are environment-only, never printed."""
    def command(self, args, data=None):
        result = subprocess.run(['gh', *args], input=data, capture_output=True)
        if result.returncode:
            raise RuntimeError('GitHub operation failed; old feed is retained or rollback is attempted')
        return result.stdout

    def api(self, path, method='GET', body=None):
        args = ['api', f'repos/{REPOSITORY}/{path}', '--method', method,
                '-H', 'Accept: application/vnd.github+json']
        data = None
        if body is not None:
            args += ['--input', '-']
            data = json.dumps(body).encode()
        return json.loads(self.command(args, data))

    def release(self):
        r = self.api(f'releases/tags/{CHANNEL}')
        need(r['tag_name'] == CHANNEL and not r['draft'] and not r.get('immutable', False), 'fixed release unavailable')
        return r

    def content(self, a):
        b = self.command(['api', f'repos/{REPOSITORY}/releases/assets/{a["id"]}', '-H', 'Accept: application/octet-stream'])
        limit = 262144 if a['name'].endswith('.transaction.json') else 65536
        need(len(b) <= limit, 'release JSON asset too large')
        return b

    def upload(self, path):
        self.command(['release', 'upload', CHANNEL, str(path), '--repo', REPOSITORY])

    def rename(self, a, name):
        return self.api(f'releases/assets/{a["id"]}', 'PATCH', {'name': name})

    def metadata(self, r, body):
        return self.api(f'releases/{r["id"]}', 'PATCH', body)

    def tag(self):
        return self.api(f'git/ref/tags/{CHANNEL}')['object']

    def public_manifest(self):
        url = f'https://github.com/{REPOSITORY}/releases/download/{CHANNEL}/latest.json?v={uuid.uuid4()}'
        req = urllib.request.Request(url, headers={'User-Agent': 'OpenMinis-Updater/1.0 (iOS)', 'Accept': 'application/json', 'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=25) as response:
            need(response.status == 200, 'public feed HTTP failure')
            data = response.read(65537)
        need(len(data) <= 65536, 'public manifest too large')
        return data

    def public_ipa(self, m):
        url = f'https://github.com/{REPOSITORY}/releases/download/{CHANNEL}/{m["ipa"]}?v={uuid.uuid4()}'
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'OpenMinis-Updater/1.0 (iOS)'})
        with urllib.request.urlopen(req, timeout=25) as response:
            need(response.status == 200 and int(response.headers['Content-Length']) == m['size'], 'public IPA unavailable/wrong size')


def named(release, name, required=True):
    found = [a for a in release['assets'] if a['name'] == name]
    need(len(found) <= 1, 'duplicate release asset names')
    if required:
        need(bool(found), f'missing release asset {name}')
    return found[0] if found else None


def check_asset(a, size, digest):
    need(a['state'] == 'uploaded' and a['size'] == size and a.get('digest') == 'sha256:' + digest, 'release asset bytes/digest mismatch')


def live(host):
    r = host.release()
    a = named(r, 'latest.json')
    raw = host.content(a)
    check_asset(a, len(raw), hashlib.sha256(raw).hexdigest())
    m = validate_manifest(json.loads(raw))
    check_asset(named(r, m['ipa']), m['size'], m['sha256'])
    return r, a, raw, m


def ensure_asset(host, file, digest):
    a = named(host.release(), file.name, required=False)
    if a is None:
        host.upload(file)
        a = named(host.release(), file.name)
    check_asset(a, file.stat().st_size, digest)
    return a


def publish(host, ipa, manifest, output, commit=None):
    import app_release_transaction as tx
    with tx.trap_signals():
        return tx.publish(host, ipa, manifest, output, commit or os.environ.get('GITHUB_SHA', ''))


def prepare(host, c, env_file, commit=None, output=Path('release-evidence')):
    import app_release_transaction as tx
    with tx.trap_signals():
        return tx.prepare(host, c, env_file, commit or os.environ.get('GITHUB_SHA', ''), output)


def resume(host, c, output, commit):
    import app_release_transaction as tx
    with tx.trap_signals():
        return tx.resume(host, c, output, commit)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'publish', 'resume'))
    p.add_argument('--config', type=Path, default=ROOT / 'scripts/app-release.json')
    p.add_argument('--evidence', type=Path, default=Path('ipa-verification.json'))
    p.add_argument('--sums', type=Path, default=Path('SHA256SUMS'))
    p.add_argument('--output', type=Path, default=Path('release-evidence'))
    a = p.parse_args()
    try:
        validate_context(os.environ)
        c = config(a.config)
        host = GitHub()
        if a.action == 'prepare':
            prepare(host, c, os.environ['GITHUB_ENV'], os.environ['GITHUB_SHA'], a.output)
            print('ONE APP CHANNEL: version/recovery decision', c['build'])
        else:
            if a.action == 'resume':
                result = resume(host, c, a.output, os.environ['GITHUB_SHA'])
            else:
                manifest = verify_ipa(Path(ipa_name(c)), json.loads(a.evidence.read_text()), a.sums, c, os.environ['GITHUB_SHA'])
                result = publish(host, Path(ipa_name(c)), manifest, a.output, os.environ['GITHUB_SHA'])
            summary = f'App {c["version"]} / build {c["build"]}: {result["phase"]}\n应用更新通道已验证；安装与真机效果未验。\n'
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                    f.write(summary)
            print(summary, end='')
    except Exception as e:
        # Do not expose HTTP redirect URLs, credentials or raw subprocess errors.
        print('APP PUBLICATION BLOCKED:', str(e) if isinstance(e, (ValueError, RuntimeError)) else type(e).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
