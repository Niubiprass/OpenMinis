#!/usr/bin/env python3
"""Byte-preserved production Engine + deterministic Apple host cancellation tests.

Default: source/SHA/hook/portable-mutation gates, then native if Apple is present.
--require-native: absence of macOS SDK/Swift is FAIL, never a successful skip.
No production edits, alternate state machine, microphone, device or inference.
"""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'scripts/fixtures/minisight_runtime_cancel_20261117'
ENGINE = 'src/ios/MiniSightWakeEngine.swift'
NAME = 'src/ios/MiniSightWakeName.swift'
ASSETS = 'src/ios/MiniSightWakeAssets.swift'
# Only insert standalone test calls; stripping exactly these calls must recover
# every byte of the production file, including imports and unrelated methods.
HOOKS = (
    ('    private func prepareLatest() {\n',
     '        CancelHooks.at("workerEntry", token: nil) // CANCEL-FIXTURE-HOOK\n'),
    ('                let handles = try makeSpotter(files: files, definition: name.definition)\n',
     '                CancelHooks.at("beforeMake", token: next.token) // CANCEL-FIXTURE-HOOK\n'),
    ('                guard state({ current == next.token }) else {\n',
     '                CancelHooks.at("afterMake", token: next.token) // CANCEL-FIXTURE-HOOK\n'),
    ('    private func deliver(_ job: Job, result: Result<MiniSightWakeName.Prepared, Error>) {\n',
     '        CancelHooks.at("beforeDelivery", token: job.token) // CANCEL-FIXTURE-HOOK\n'),
    ('            guard let self, self.state({ self.current == job.token }) else { return }\n',
     '            CancelHooks.at("mainDelivery", token: job.token) // CANCEL-FIXTURE-HOOK\n'),
)
AFTER_ANCHOR = {0, 3}
MUTATIONS = (
    ('removed_stopped_token_guard',
     'guard state({ current == next.token }) else {',
     'guard state({ true }) else {'),
    ('destroy_newer_generation',
     'guard let self, self.builtToken == old else { return }',
     'guard let self else { return }'),
    ('wrong_callback_generation',
     'guard let self, self.state({ self.current == job.token }) else { return }',
     'guard let self, self.state({ self.current != nil }) else { return }'),
    ('wrong_late_handle_destroy',
     'SherpaOnnxDestroyOnlineStream(handles.stream)',
     'SherpaOnnxDestroyKeywordSpotter(handles.stream)'),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def inject(source):
    result = source
    for index, (anchor, call) in enumerate(HOOKS):
        require(result.count(anchor) == 1, 'hook anchor not unique: ' + str(index))
        result = result.replace(anchor, anchor + call if index in AFTER_ANCHOR else call + anchor, 1)
    return result


def remove_hooks(generated):
    for _, call in HOOKS:
        require(generated.count(call) == 1, 'missing/duplicate test hook')
        generated = generated.replace(call, '', 1)
    require('CANCEL-FIXTURE-HOOK' not in generated, 'unlisted test modification')
    return generated


def guard_engine(source, generated, manifest):
    require(sha(source.encode()) == manifest['sources'][ENGINE], 'production Engine SHA changed')
    require(remove_hooks(generated) == source, 'generated Engine is not byte-identical after hook removal')
    for _, old, _ in MUTATIONS:
        require(source.count(old) == 1, 'production cancellation guard not unique: ' + old)
    require('current = nil; ready = nil; latest = nil;' in source, 'stop invalidation missing')
    require('if let stream { SherpaOnnxDestroyOnlineStream(stream) }' in source, 'stream cleanup missing')
    require('if let spotter { SherpaOnnxDestroyKeywordSpotter(spotter) }' in source, 'model cleanup missing')


def mutate(source, old, new):
    require(source.count(old) == 1, 'mutation must target exactly one real production statement')
    return source.replace(old, new, 1)


def portable_negatives(source, generated, manifest):
    for label, old, new in MUTATIONS:
        changed = mutate(source, old, new)
        # Must reject even if an adversary updates only the Engine SHA: the
        # retained production guard contract still disallows these mutations.
        changed_manifest = dict(manifest, sources=dict(manifest['sources']))
        changed_manifest['sources'][ENGINE] = sha(changed.encode())
        rejected = False
        try:
            guard_engine(changed, inject(changed), changed_manifest)
        except AssertionError:
            rejected = True
        require(rejected, 'portable mutation accepted: ' + label)
        print('PASS portable source negative:', label, '(not native behavior proof)')
    for label, changed in (
        ('unlisted_excerpt_edit', generated.replace('ready = next.token', 'ready = nil', 1)),
        ('extra_hook', generated + '\n// CANCEL-FIXTURE-HOOK\n'),
        ('missing_hook', generated.replace(HOOKS[0][1], '', 1)),
    ):
        rejected = False
        try:
            guard_engine(source, changed, manifest)
        except AssertionError:
            rejected = True
        require(rejected, 'excerpt integrity mutation accepted: ' + label)
        print('PASS portable excerpt negative:', label)


def native_toolchain(required):
    if platform.system() != 'Darwin' or not shutil.which('xcrun'):
        print('FAIL native REQUIRED: Apple macOS SDK/Swift unavailable' if required else
              'SKIP native: Apple macOS SDK/Swift unavailable; Swift compilation/behavior unverified')
        return None
    try:
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        compiler = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--find', 'swiftc'], text=True).strip()
        clang = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--find', 'clang'], text=True).strip()
        require(Path(sdk).is_dir() and Path(compiler).is_file() and Path(clang).is_file(), 'incomplete Apple toolchain')
        return sdk, compiler, clang
    except (subprocess.SubprocessError, AssertionError) as error:
        # A purported native host with a broken toolchain is always an error.
        raise AssertionError('Apple toolchain discovery failed: ' + str(error)) from error


def native_cases(source, generated, toolchain):
    sdk, compiler, clang = toolchain
    with tempfile.TemporaryDirectory(prefix='minisight-runtime-cancel-') as tmp:
        folder = Path(tmp)
        module = folder / 'SherpaOnnxC'
        module.mkdir()
        shutil.copyfile(FIXTURES / 'mock.h', module / 'mock.h')
        (module / 'module.modulemap').write_text('module SherpaOnnxC { header "mock.h" export * }\n')
        obj = folder / 'mock.o'
        subprocess.run([clang, '-std=c11', '-pthread', '-isysroot', sdk, '-I', str(module),
                        '-c', str(FIXTURES / 'mock.c'), '-o', str(obj)], check=True, timeout=120)
        suffix = '\n' + (ROOT / NAME).read_text() + '\n' + (ROOT / ASSETS).read_text()
        suffix += '\n' + (FIXTURES / 'harness.swift').read_text()
        variants = [('production', generated, True)]
        variants += [(label, mutate(generated, old, new), False) for label, old, new in MUTATIONS]
        for label, body, accepted in variants:
            # This is a generated copy ONLY; source guards ran before mutations.
            swift = folder / 'main.swift'
            binary = folder / label
            swift.write_text(body + suffix)
            result = subprocess.run([compiler, '-swift-version', '5', '-sdk', sdk,
                                     '-I', str(module), str(swift), str(obj), '-o', str(binary)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
            require(result.returncode == 0, 'native compile failed (never count as rejected behavior): ' +
                    label + '\n' + result.stderr[-6000:])
            run = subprocess.run([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=150)
            if accepted:
                require(run.returncode == 0, 'native baseline failed:\n' + run.stdout[-6000:] + run.stderr[-6000:])
                require('23 barrier cases' in run.stdout, 'native matrix did not finish')
                print(run.stdout.strip())
            else:
                require(run.returncode != 0, 'native behavior mutation unexpectedly passed: ' + label)
                # Reject crash/timeout for an unrelated reason, rather than
                # counting a compile failure or semaphore deadlock as sensitivity.
                expected = {
                    'removed_stopped_token_guard': 'stopped generation became ready',
                    'destroy_newer_generation': 'late old cleanup damaged new usable generation',
                    'wrong_callback_generation': 'wrong success generation',
                    'wrong_late_handle_destroy': 'double/wrong-kind/parent-first destroy',
                }[label]
                require(expected in run.stderr, 'mutation failed for unexpected reason: ' + label + '\n' + run.stderr[-3000:])
                print('PASS native BEHAVIOR negative:', label, '(expected lifecycle assertion)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-native', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((FIXTURES / 'source-manifest.json').read_text())
    require(manifest['schema'] == 1 and manifest['sourceRoot'] == 'src/ios', 'wrong source-root manifest')
    require(set(manifest['sources']) == {ENGINE, NAME, ASSETS}, 'unexpected production source scope')
    require(set(manifest['fixtures']) == {'mock.h', 'mock.c', 'harness.swift'}, 'unexpected fixture scope')
    for path, expected in manifest['sources'].items():
        require(sha((ROOT / path).read_bytes()) == expected, 'production source SHA mismatch: ' + path)
    for path, expected in manifest['fixtures'].items():
        require(sha((FIXTURES / path).read_bytes()) == expected, 'fixture SHA mismatch: ' + path)
    source = (ROOT / ENGINE).read_text()
    generated = inject(source)
    guard_engine(source, generated, manifest)
    print('PASS source guard: entire real Engine unchanged after five enumerated hook insertions')
    print('PASS manifest: production Engine/Name/Assets and native fixture SHA256')
    portable_negatives(source, generated, manifest)
    tools = native_toolchain(args.require_native)
    if tools is None:
        return 1 if args.require_native else 0
    native_cases(source, generated, tools)
    print('PASS required native cancellation matrix + four compiled behavior negatives')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, subprocess.SubprocessError, ValueError) as error:
        print('FAIL:', error)
        raise SystemExit(1)
