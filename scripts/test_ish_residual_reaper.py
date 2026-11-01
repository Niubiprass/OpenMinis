#!/usr/bin/env python3
"""Static contract for safely reaping children left by a normally exited shell."""
import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
src = (root / 'src/ios/iSH/ISHShellExecutor.m').read_text()
fails = []
def ok(c, label):
    print(('PASS ' if c else 'FAIL ') + label)
    if not c: fails.append(label)
ok('@property (nonatomic) pid_t_ guestGroup;' in src, 'group is retained on the context')
capture = src[src.index('struct task *task = current;'):]
capture = capture[:capture.index('task_start(task);')]
ok('ctx.guestGroup = task->group->pgid' in capture and 'task->group != NULL' in capture,
   'group captured while the root still exists')
body = src[src.index('+ (void)killRemainingInGroup:'):]
body = body[:body.index('\n}\n')]
ok('t->group->pgid != pgid' in body, 'only the exact captured group matches')
ok('t->pid == rootPid' in body, 'exited root is excluded')
ok('SIGTERM_' in body and 'SIGKILL_' in body, 'TERM then KILL escalation exists')
ok(body.index('SIGTERM_') < body.index('SIGKILL_'), 'escalation order is TERM -> KILL')
ok('dispatch_get_global_queue(QOS_CLASS_UTILITY, 0)' in body, 'pids_lock scan is off-main')
exit_body = src[src.index('+ (void)processDidExit:'):]
exit_body = exit_body[:exit_body.index('@end')]
ok('killRemainingInGroup:ctx.guestGroup excluding:pid' in exit_body,
   'normal-exit path reaps remaining children')
drain = exit_body[exit_body.index('dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 200'):]
ok(drain.index('killRemainingInGroup') < drain.index('finalizeContext'),
   'group sweep is started before finalization')
timeout = src[src.index('// Timeout - kill the whole process group'):]
timeout = timeout[:timeout.index('return result;')]
ok('killProcessGroup:pid' in timeout, 'timeout still uses full root-based group sweep')
if fails:
    print('FAILED', len(fails)); sys.exit(1)
print('PASS: normal-exit residual sweep contract')
