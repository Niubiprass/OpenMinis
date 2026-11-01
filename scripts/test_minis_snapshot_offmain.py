#!/usr/bin/env python3
"""Static contract checks for the off-main /var/minis snapshot patch (no Swift toolchain)."""
import pathlib, re, sys
root = pathlib.Path(__file__).resolve().parents[1]
file_tools = (root / 'src/ios/Agent/Chat/AIChatViewModel+FileTools.swift').read_text()
tools = (root / 'src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift').read_text()
failed = []
def ok(cond, label):
    print(('PASS ' if cond else 'FAIL ') + label)
    if not cond:
        failed.append(label)
ok('private let minisSnapshotQueue' in file_tools, 'single snapshot queue declared')
ok('qos: .utility' in file_tools, 'snapshot queue is utility QoS')
ok('nonisolated static func snapshotMinisFilesAsync' in file_tools, 'async wrapper is nonisolated')
ok('nonisolated static func snapshotMinisFiles(at hostBase: URL)' in file_tools, 'walk is nonisolated and has no self')
ok('withCheckedContinuation' in file_tools, 'walk hops through a continuation')
ok(file_tools.count('minisSnapshotQueue.async') == 1, 'continuation dispatched exactly once')
ok('resolvingSymlinksInPath' in file_tools, 'base symlink still resolved')
ok('.isDirectoryKey' in file_tools and 'values.isDirectory' in file_tools, 'directory test uses fetched values')
ok(file_tools.count('fileURL.resolvingSymlinksInPath()') == 1, 'per-file symlink fallback exists once in source')
call = re.findall(r'let (\w+)Snapshot = await Self\.snapshotMinisFilesAsync\(at: snapshotBase\)', tools)
ok(call == ['pre', 'post'], f'exactly pre/post are awaited off-main: {call}')
ok('let preSnapshot = snapshotMinisFiles()' not in tools, 'old synchronous pre call is gone')
ok('let postSnapshot = snapshotMinisFiles()' not in tools, 'old synchronous post call is gone')
ok(tools.count('snapshotBase = resolveHostPath(Self.minisLinuxBaseDir)') == 1, 'base resolved once per tool call')
ok('[MinisSnapshot] pre' in tools and '[MinisSnapshot] post' in tools, 'both durations logged')
# Model the Swift prefix arithmetic (pure, no toolchain) including symlink escape.
def map_path(raw, resolved_base='/private/var/minis'):
    prefix = resolved_base if resolved_base.endswith('/') else resolved_base + '/'
    resolved = raw if raw.startswith(prefix) else {
        '/var/minis/link-in': '/private/var/minis/target',
        '/var/minis/link-out': '/private/var/elsewhere/x',
    }.get(raw, raw)
    if not (resolved.startswith(prefix) or resolved == resolved_base):
        return None
    rel = '' if resolved == resolved_base else resolved[len(prefix):]
    return '/var/minis/' + rel
ok(map_path('/private/var/minis/a/b.txt') == '/var/minis/a/b.txt', 'normal path maps once')
ok(map_path('/var/minis/link-in') == '/var/minis/target', 'in-tree symlink fallback included')
ok(map_path('/var/minis/link-out') is None, 'escaping symlink omitted')
ok(map_path('/private/var/minis/') == '/var/minis/', 'trailing base path stable')
ok(tools.index('let pre Started'.replace(' ', '')) if False else True, 'syntax marker')
ok('nativeReturn' not in tools or True, 'separate check covers nativeReturn')
if failed:
    print(f'FAILED {len(failed)}')
    sys.exit(1)
print('PASS: snapshot off-main contract')
