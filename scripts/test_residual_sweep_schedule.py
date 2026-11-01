#!/usr/bin/env python3
"""Static contract for post-MCP orphan sweeps (conservative allow-list)."""
import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
p = root / 'src/ios/Agent/ISH/ISHExecutionCoordinator.swift'
if not p.exists():
    p = pathlib.Path('/var/minis/workspace/MiniSight-runtime-audit/mcp-entry-source/ISHExecutionCoordinator.swift')
src = p.read_text()
fails = []
def ok(c, label):
    print(('PASS ' if c else 'FAIL ') + label)
    if not c: fails.append(label)
release = src[src.index('private func releaseMCPSlot()'):]
release = release[:release.index('\n    }\n')]
ok('if mcpInFlight == 0 { scheduleResidualSweep() }' in release, 'last slot release schedules sweep')
ok(src.count('self.sweepStuckMCPProcesses()') + src.count('await sweepStuckMCPProcesses()') >= 2, 'new sweep reuses the existing bounded reaper')
sched = src[src.index('private func scheduleResidualSweep()'):]
sched = sched[:sched.index('\n    }\n')]
run = src[src.index('private func runResidualSweep('):]
run = run[:run.index('\n    }\n')]
ok('Task.sleep(nanoseconds: 800_000_000)' in sched, 'sweep waits for drain')
ok('mcpInFlight == 0' in run and 'mcpSlotWaiters.isEmpty' in run,
   'sweep re-checks idle before running')
ok('residualSweepTask?.cancel()' in sched, 'a newer call cancels the pending sweep')
ok('residualSweepSerial' in sched and 'residualSweepSerial == serial' in run,
   'an older finished task cannot clear the newer handle')
script = src[src.index('private static func reaperScript'):]
script = script[:script.index('\n    """\n', script.index('"""') + 4) + 8]
for name in ('minis-mcp-cli', 'mcp-root', 'mcp-appinst', 'mcp-ldid', 'mcp-logreader'):
    ok(name in script, f'allow-list includes {name}')
ok('minis-mcp-daemon*.pid' in script and 'case "$daemons"' in script,
   'reusable daemon pid is excluded')
ok('"$pp" = "1"' in script, 'only orphans are swept before the age limit')
ok('active=" \\(activeText) "' in script and '[ "$hit" = "1" ] && continue' in script,
   'descendants of a command still running are skipped')
ok('age" -gt 180' in script, 'aged helpers get a bounded fallback')
ok('kill -9 -' in script, 'whole helper group is signalled')
ok('key' not in script.lower(), 'script does not need secrets')
if fails:
    print('FAILED', len(fails)); sys.exit(1)
print('PASS: residual sweep contract')
