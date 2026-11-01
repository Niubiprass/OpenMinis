#!/usr/bin/env python3
"""Guard the capability bit consumed by the tweak to avoid double foreground opens."""
import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
app = (root / 'src/ios/Agent/Chat/AIChatViewModel+ConcurrentTools.swift').read_text()
plugin = pathlib.Path('/var/minis/workspace/MiniSight-repair/debs/MiniSight/Tweak.xm').read_text()
fails = []
def ok(c, label):
    print(('PASS ' if c else 'FAIL ') + label)
    if not c: fails.append(label)
ok('let nativeReturn: Bool' in app, 'activity schema declares nativeReturn')
ok('nativeReturn: true' in app, 'activity writer sets nativeReturn')
ok('activity[@"nativeReturn"]' in plugin, 'tweak reads nativeReturn')
ok('if (gMiniSightAppNativeReturn) return;' in plugin, 'tweak skips its duplicate front open')
ok(plugin.count('MiniSightBringMinisFront();') == 2,
   'only endedExecution and stopped may request front open')
front = plugin[plugin.index('static void MiniSightBringMinisFront(void) {'):]
front = front[:front.index('\n}\n')]
ok(front.count('performSelector:@selector(openApplicationWithBundleID:') == 1, 'exactly one LaunchServices fallback remains')
ok('dispatch_block_cancel(gMiniSightPendingReturn)' in front, 'queue is single-flight')
if fails:
    print('FAILED', len(fails)); sys.exit(1)
print('PASS: nativeReturn contract')
