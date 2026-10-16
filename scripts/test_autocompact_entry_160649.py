"""Source-contract tests for REPAIR-160649: entry/restore auto-compaction.

Pure Python contract checks (no Swift runtime, no device): the entry hook must
sit at the two persistence load-completion points, gate on the SAME opt-in
switch / ContextPolicy verdict as the pre-send path, start exactly one
compaction per session visit through the existing compactAll() entry (no new
state machine, no auto-send), and keep every failure/success guarantee of the
existing compact path intact. Swift compilation and on-device behavior still
need Xcode CI / a real device.

Run: python3 scripts/test_autocompact_entry_160649.py
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
vm = (root/'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
compaction = (root/'src/ios/Agent/Chat/AIChatViewModel+Compaction.swift').read_text()
persistence = (root/'src/ios/Agent/Chat/AIChatViewModel+Persistence.swift').read_text()
policy = (root/'src/ios/Agent/Chat/ContextPolicy.swift').read_text()


def body_after(text, marker):
    """Slice from `marker` to the next top-level `    func ` / end-of-file."""
    i = text.index(marker)
    m = re.search(r'\n    func ', text[i+len(marker):])
    return text[i+len(marker): i+len(marker)+(m.start() if m else len(text))]


# ── 1. 挂钩位置：历史加载完成两处（loadSession 末尾 + SKIP-LOAD 分支） ──
calls = [m.start() for m in re.finditer(r'autoCompactOnEntryIfNeeded\(\)', persistence)]
assert len(calls) >= 2, 'entry check must be hooked at both load-completion points'
load_fn = persistence.index('func loadSession() async')
assert calls[0] < load_fn, 'first hook must be the SKIP-LOAD branch (before loadSession in file)'
assert calls[-1] > load_fn, 'second hook must be inside/after loadSession'
total_log = persistence.index('[SessionLoad] \\(sessionId) — TOTAL:')
assert calls[-1] > total_log, 'loadSession hook must run AFTER the history load fully completes'
skip_region = persistence[calls[0]-400:calls[0]]
assert 'recheckCanResumeFromHistory()' in skip_region, 'SKIP-LOAD hook must sit with the cached-VM re-enter recheck'
empty_guard = persistence.index('empty session, DB query took')
assert empty_guard < total_log, 'empty sessions must early-return before the hook (no trigger on no history)'

# ── 2. 入口函数存在且闸门顺序正确（开关开 → 单飞 → 失败闸门 → 每访一次 → 同一阈值） ──
fn_body = body_after(compaction, 'func autoCompactOnEntryIfNeeded()')
guards = [
    ('frontmost 限定', 'AIChatViewModel.activeSessionId == sessionId'),
    ('开关开启门控', 'guard autoCompactEnabled'),
    ('单飞：处理中/压缩中不叠加', 'guard !isProcessing, !isCompacting'),
    ('失败队列闸门', 'guard !isQueueBlockedByCompaction'),
    ('每次进入至多一次', 'guard !didCheckAutoCompactOnEntry'),
    ('同一 ContextPolicy 判定', 'checkContextBeforeSend(site: "entry") == .needsCompact'),
    ('消耗一次性闸门', 'didCheckAutoCompactOnEntry = true'),
    ('复用 compactAll 入口', 'compactAll()'),
]
pos = -1
for name, token in guards:
    if name == '复用 compactAll 入口':
        i = fn_body.rindex(token)  # the real call; earlier mentions are comments
    else:
        i = fn_body.index(token)
    assert i > pos, 'entry gate order violated: %s must come after the previous gates' % name
    pos = i
# 入口不得新建重复压缩状态机、不得自动发送消息
assert 'startCompactTask(' not in fn_body, 'entry must not create its own compact task (reuses compactAll)'
for forbidden in ['pendingSendText', 'promptQueue.append', 'showCompactBeforeSendPrompt = true', 'send(']:
    assert forbidden not in fn_body, 'entry must never auto-send or touch the prompt holding area: ' + forbidden

# ── 3. 关闭开关时行为完全不变 ──
assert '?? false' in policy, 'global default for autoCompactOnThreshold must stay OFF'
assert 'sessionSource == "shortcut" || autoCompactEnabled' in vm, 'pre-send auto/manual split must be unchanged'
assert 'showCompactBeforeSendPrompt = true' in vm, 'manual confirm prompt must remain for switch-off / no-auto sessions'
assert 'compactAndSend()' in vm, 'pre-send auto-compact-and-send path must remain'
# 窗口感知沿用发送前同一实现
assert 'resolvedContextWindow(for: entry.model)' in compaction, 'window-aware judgment must be the shared one'

# ── 4. 失败不丢内容 + 成功 marker 后顺序（既有契约未被破坏） ──
assert 'Compaction failed' in compaction and 'Compaction cancelled.' in compaction
assert 'insertCompactMarkerUnlessCancelled(marker)' in compaction
marker_i = compaction.index('insertCompactMarkerUnlessCancelled(marker)')
gate_release = compaction.index('compactionQueueBlockedSessionId = nil')
assert gate_release > marker_i, 'queue gate may be released only AFTER the marker commit'
success_tail = compaction[gate_release:gate_release+900]
assert 'schedulePostCompactDrain()' in success_tail, 'post-compact drain must be the success tail (after marker + gate release)'
assert 'compactionQueueBlockedSessionId = sessionId' in compaction, 'failure/cancel must still arm the queue gate (content preserved, no auto-retry)'

# ── 5. 一次性闸门的重武装点：send / resume / retry 均开始新一轮 ──
for name in ['func send(overrideText: String? = nil)', 'func retry()', 'func resume()']:
    body = body_after(vm, name)
    assert 'didCheckAutoCompactOnEntry = false' in body, name + ' must re-arm the entry auto-compact check'

# ── 6. 失败不无限重试：消耗先于启动，闸门兜底 ──
assert fn_body.index('didCheckAutoCompactOnEntry = true') < fn_body.rindex('compactAll()'), \
    'one-shot flag must be consumed BEFORE starting the compaction'

print('Entry auto-compaction source contracts: PASS (not device tests)')
print('Note: Swift compilation / actor isolation and on-device timing still need Xcode CI and a device; this run only validates source contracts.')