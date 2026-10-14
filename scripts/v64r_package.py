#!/usr/bin/env python3
"""CI-only, unsigned/ad-hoc distribution packaging. Does not install anything."""
import pathlib
import plistlib
import re
import subprocess
import sys

app = pathlib.Path(sys.argv[1]).resolve()
source = pathlib.Path('src/ios').resolve()
limit = (15, 5)

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout

def version(raw):
    parts = [int(x) for x in raw.split('.')]
    return tuple((parts + [0, 0])[:2])

info = plistlib.loads((app / 'Info.plist').read_bytes())
assert version(info['MinimumOSVersion']) <= limit, info['MinimumOSVersion']
assert info['CFBundleIdentifier'] == 'com.openminis.app'
main = app / info['CFBundleExecutable']
images = []
for p in app.rglob('*'):
    if not p.is_file() or p.is_symlink():
        continue
    with p.open('rb') as f:
        magic = f.read(4)
    if magic not in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
        continue
    desc = run('file', '-b', str(p))
    if 'Mach-O' not in desc:
        continue
    headers = run('xcrun', 'vtool', '-show-build', str(p))
    minimums = re.findall(r'^\s*minos\s+(\d+(?:\.\d+)+)', headers, re.M)
    assert minimums, f'No verifiable deployment version: {p}'
    relative = p.relative_to(app).as_posix()
    # The exact prebuilt VAD framework was already embedded in the user's original
    # 160v64 iOS 15.5 IPA (main executable minOS 15.5, VAD binary/plist minOS 15.6).
    # Keep its honest 15.6 metadata; never relabel or silently waive other images.
    legacy_vad = relative == 'Frameworks/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary'
    if legacy_vad:
        assert minimums == ['15.6'], f'Unexpected legacy VAD version: {minimums}'
        vad_info = plistlib.loads((p.parent / 'Info.plist').read_bytes())
        assert vad_info['CFBundleIdentifier'] == 'io.code-concept.RealTimeCutVADCXXLibrary'
        assert vad_info['MinimumOSVersion'] == '15.6'
        print('KNOWN BASELINE EXCEPTION: prebuilt VAD minOS 15.6; iOS 15.5 load/voice behavior unverified')
    else:
        assert all(version(v) <= limit for v in minimums), f'Incompatible deployment: {p}: {minimums}'
    links = run('otool', '-L', str(p))
    assert '_AppIntents_SwiftUI.framework' not in links, f'Unavailable framework: {p}'
    images.append(p)
    print(f'CHECKED {p.relative_to(app)} minOS={minimums}')
assert main in images

# Do not add no-sandbox/platform/library-validation/Keychain wildcard privileges.
# Sign inner images, then framework resources, then extensions, then the app.
def sign(path, ent=None):
    cmd = ['codesign', '--force', '--sign', '-', '--timestamp=none']
    if ent is not None:
        cmd += ['--entitlements', str(ent)]
    run(*cmd, str(path))

for image in images:
    if image != main:
        sign(image)
for framework in sorted(app.rglob('*.framework'), key=lambda p: len(p.parts), reverse=True):
    sign(framework)
for extension in sorted(app.rglob('*.appex'), key=lambda p: len(p.parts), reverse=True):
    metadata = plistlib.loads((extension / 'Info.plist').read_bytes())
    suffix = metadata['CFBundleIdentifier'].split('.')[-1].lower()
    candidates = [p for p in source.rglob('*.entitlements') if p.stem.lower() == suffix]
    assert len(candidates) == 1, f'Ambiguous/missing extension entitlements: {extension}: {suffix}'
    sign(extension, candidates[0])
sign(app, source / 'Minis.entitlements')
run('codesign', '--verify', '--deep', '--strict', str(app))
ent = subprocess.run(['codesign', '-d', '--entitlements', ':-', str(app)], check=True, capture_output=True).stdout
metadata = plistlib.loads(ent)
assert 'group.com.openminis.app' in metadata.get('com.apple.security.application-groups', [])
for forbidden in ('com.apple.private.security.no-sandbox', 'platform-application', 'com.apple.private.skip-library-validation'):
    assert forbidden not in metadata, forbidden
print(f'Verified {len(images)} Mach-O images: all except baseline VAD minOS <= 15.5; original VAD minOS 15.6 remains unverified on iOS 15.5; source App Group and signatures verified.')
