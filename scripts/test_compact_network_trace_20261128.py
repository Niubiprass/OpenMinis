#!/usr/bin/env python3
"""Summary-only network trace contracts + source mutants + actual Swift helper.
No network, devices or existing tests are invoked. Source checks are NOT native
runtime proof. --require-native exits 1 when swiftc is unavailable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / 'src/ios/Providers/OpenAI/OpenAIProvider.swift'
FIXTURES = ROOT / 'scripts/fixtures'
BEGIN = '// BEGIN COMPACT NETWORK TRACE'
END = '// END COMPACT NETWORK TRACE'
STREAM_BEGIN = '    func streamMessage('
STREAM_END = '    // MARK: - Request body size guard'
STAGES = {'network_start', 'network_headers', 'network_first_event', 'network_cancel', 'network_end'}
KEYS = {'network', 'purpose', 'route', 'provider_hash', 'model_hash', 'request_hash', 'http',
        'events', 'text_events', 'text_chars', 'reasoning_events', 'usage_events',
        'unknown_events', 'malformed_events', 'bytes', 'finish', 'error_domain_hash',
        'error_code', 'elapsed_ms'}


def parts(source):
    helper = source.split(BEGIN, 1)[1].split(END, 1)[0]
    stream = source.split(STREAM_BEGIN, 1)[1].split(STREAM_END, 1)[0]
    untraced = source.split(BEGIN, 1)[0] + source.split(END, 1)[1].lstrip('\n')
    # Summary compatibility was separately approved and is covered by its own
    # actual-production fixture. Keep the original baseline outside both seams.
    assembler_begin = '// BEGIN COMPACT SUMMARY ASSEMBLER'
    assembler_end = '// END COMPACT SUMMARY ASSEMBLER'
    if assembler_begin in untraced:
        assert untraced.count(assembler_begin) == untraced.count(assembler_end) == 1
        untraced = untraced.split(assembler_begin, 1)[0] + untraced.split(assembler_end, 1)[1].lstrip('\n')
    prefix, suffix = untraced.split(STREAM_BEGIN, 1)
    suffix = suffix.split(STREAM_END, 1)[1]
    return helper, stream, prefix, suffix


def contracts(source):
    h, s, prefix, suffix = parts(source)
    baseline = json.loads((FIXTURES / 'compact_network_trace_20261128.baseline.json').read_text())
    initial = h.split('fields = [', 1)[1].split(']\n', 1)[0]
    counters = h.split('private var counts:', 1)[1].split(']\n', 1)[0]
    output_keys = set(re.findall(r'"([a-z_]+)"\s*:', initial + counters))
    output_keys |= set(re.findall(r'(?:fields|final)\["([a-z_]+)"\]\s*=', h))
    methods = [h.split('    func ' + name + '(', 1)[1].split('\n    }', 1)[0]
               for name in ['line', 'headers', 'done', 'malformed', 'event', 'end']]
    before_stream = s.split('return AsyncThrowingStream', 1)[0]
    pump = s.split('return AsyncThrowingStream', 1)[1]
    termination = pump.split('continuation.onTermination =', 1)[1]
    return {
        'only_helper_and_stream_changed': all(hashlib.sha256(x.encode()).hexdigest() == baseline[k]
                                              for k, x in [('prefix', prefix), ('suffix', suffix)]),
        'tasklocal_snapshot_before_build_and_optional_state': 'let trace = CompactLifecycle.current' in s
            and 'let network = trace.map {' in s and s.index('let trace =') < s.index('try await buildRequest'),
        'fixed_stages_and_no_chunk_sink': set(re.findall(r'trace\.event\("([^"]+)"', h)) == STAGES
            and len(re.findall(r'trace\.event\(', h)) == 5 and 'trace.event(' not in s,
        'only_approved_output_keys': output_keys == KEYS,
        'no_payload_or_raw_error_sink': not re.search(r'\b(?:print|logger|NSLog|os_log)\b', h + s)
            and not any(x in h + s for x in ['localizedDescription', 'String(describing:', 'allHeaderFields'])
            and 'fields["body"]' not in h and 'fields["text"]' not in h,
        'identity_hashed_at_entry': 'providerHash: CompactLifecycleTrace.fingerprint(providerInstanceId ?? "unscoped")' in s
            and 'modelHash: CompactLifecycleTrace.fingerprint(model.id)' in s
            and 'route: useChat ? "chat_completions" : "responses"' in s,
        'request_id_exact_headers_only_and_hash': '["x-request-id", "request-id", "openai-request-id", "x-ms-request-id"]' in h
            and 'fields["request_hash"] = requestID.map { CompactLifecycleTrace.fingerprint($0) } ?? "none"' in h
            and h.count('value(forHTTPHeaderField:') == 1 and 'request_id' not in h,
        'monotonic_duration': 'ProcessInfo.processInfo.systemUptime' in h and 'Date(' not in h,
        'all_state_mutations_locked_and_terminal_guarded': all('lock.lock(); defer { lock.unlock() }' in m
            and 'guard !ended' in m for m in methods) and '@unchecked Sendable' in h,
        'unique_terminal_before_callback': h.count('trace.event("network_end", final)') == 1
            and h.index('ended = true') < h.index('trace.event("network_cancel"') < h.index('trace.event("network_end"'),
        'all_six_exit_sites_close': s.count('network?.end(') == 6
            and before_stream.count('network?.end(error: error, cancelled: Task.isCancelled)') == 3
            and 'network?.end(cancelled: Task.isCancelled)\n                    continuation.finish()' in pump
            and 'network?.end(error: error, cancelled: Task.isCancelled)\n                    continuation.finish(throwing:' in pump,
        'headers_before_body_and_bounded_error_body': 'network?.headers(response)' in s
            and s.index('network?.headers(response)') < s.index('if !(200..<300)')
            and 'defer { session.finishTasksAndInvalidate() }' in before_stream
            and 'ProviderTurnRun.isRecoverySummary && body.utf8.count + line.utf8.count > 16_384' in s
            and 'ProviderTurnLimitRejection.parse(status: statusCode, body: body)' in s,
        'consumer_cancel_not_normal_finish': 'if case .cancelled = termination {\n                    network?.end(cancelled: true)\n                    task.cancel()' in termination
            and 'trace.cancel("network_cancel")' in h and 'trace.cancel("user' not in h
            and 'nsError?.code == NSURLErrorCancelled' in h and 'error is CancellationError' in h,
        'headers_first_and_bytes_counted': 'guard !ended, !headersSeen' in h and 'headersSeen = true' in h
            and 'if counts["events"] == 0 { trace.event("network_first_event", fields) }' in h
            and s.count('network?.line(line)') == 2 and 'increment("bytes", by: line.utf8.count)' in h,
        'saturating_counters_and_text_character_count': 'min(max(0, amount), Int.max - old)' in h
            and 'increment("text_chars", by: text.count)' in h,
        'data_done_malformed_paths_preserved': 'guard line.hasPrefix("data:") else { continue }' in s
            and 'after.first == " " ? String(after.dropFirst()) : String(after)' in s
            and 'network?.done()\n                            continuation.yield(.finished(stopReason: nil))\n                            break' in s
            and 'network?.malformed()\n                            continue' in s
            and s.count('continuation.yield(.finished(') == 1,
        'real_parsers_only_no_reasoning_text': 'let text = delta?["content"] as? String' in s
            and 'let text = self.parseResponsesAPITextDelta(event)' in s
            and 'let usage = self.parseResponsesAPIUsage(event)' in s and 'reasoning' not in s
            and 'network?.event(event, text: nil, usage: false, useChat: useChat)\n                            throw error' in s,
        'known_finish_labels_not_raw': 'case "length": noteFinish("length")' in h
            and 'case "content_filter": noteFinish("refusal")' in h
            and 'case "response.completed": noteFinish("completed")' in h
            and 'case "response.incomplete":' in h and 'default: noteFinish("incomplete")' in h
            and 'case "max_output_tokens": noteFinish("length")' in h
            and 'default: noteFinish("other")' in h and 'finish = reason' not in h,
        'done_and_eof_do_not_erase_explicit_finish': 'beginEvent(); noteFinish("done")' in h
            and 'priority[candidate, default: 0] > priority[finish, default: 0]' in h
            and 'finish = "eof"' not in h.split('func end(', 1)[1],
        'unknown_reasoning_usage_and_malformed_counted': 'if !known { increment("unknown_events") }' in h
            and 'increment("reasoning_events"); known = true' in h
            and 'if usage { increment("usage_events"); known = true }' in h
            and 'beginEvent(); increment("malformed_events")' in h,
        'error_domain_only_hashed': 'final["error_domain_hash"] = nsError.map { CompactLifecycleTrace.fingerprint($0.domain) } ?? "none"' in h
            and 'final["error_code"] = nsError.map { String($0.code) } ?? "none"' in h,
    }


# In-memory, deliberately broken variants: NEVER written over production sources.
MUTANTS = [
    ('trace_disabled', 'let trace = CompactLifecycle.current', 'let trace: CompactLifecycleTrace? = nil'),
    ('raw_request_id', 'requestID.map { CompactLifecycleTrace.fingerprint($0) } ?? "none"', 'requestID ?? "none"'),
    ('credential_header_as_id', '["x-request-id", "request-id", "openai-request-id", "x-ms-request-id"]', '["authorization", "x-request-id"]'),
    ('raw_error_domain', 'nsError.map { CompactLifecycleTrace.fingerprint($0.domain) } ?? "none"', 'nsError.map { $0.domain } ?? "none"'),
    ('raw_model', 'modelHash: CompactLifecycleTrace.fingerprint(model.id)', 'modelHash: model.id'),
    ('unlocked_line', 'func line(_ line: String) {\n        lock.lock(); defer { lock.unlock() }', 'func line(_ line: String) {'),
    ('late_terminal_flag', '        ended = true\n        let nsError', '        let nsError'),
    ('cancel_on_finished', 'if case .cancelled = termination {', 'if case .finished = termination {'),
    ('unknown_ignored', 'if !known { increment("unknown_events") }', 'if !known { /* broken */ }'),
    ('malformed_ignored', 'beginEvent(); increment("malformed_events")', 'beginEvent()'),
    ('reasoning_as_summary', 'let text = delta?["content"] as? String', 'let text = delta?["reasoning_content"] as? String'),
    ('done_not_counted', 'network?.done()', '/* omitted done */'),
    ('length_as_stop', 'case "length": noteFinish("length")', 'case "length": noteFinish("stop")'),
    ('incomplete_as_completed', 'default: noteFinish("incomplete")', 'default: noteFinish("completed")'),
    ('raw_payload_print', 'network?.malformed()', 'print(payload); network?.malformed()'),
    ('body_cap_lost', 'body.utf8.count + line.utf8.count > 16_384', 'body.utf8.count + line.utf8.count > Int.max'),
    ('body_bytes_lost', '                    network?.line(line)\n                    if ProviderTurnRun', '                    if ProviderTurnRun'),
    ('build_failure_end_lost', 'network?.end(error: error, cancelled: Task.isCancelled)\n            throw error\n        }\n\n        // [T-ios-stream', 'throw error\n        }\n\n        // [T-ios-stream'),
    ('done_erases_length', 'beginEvent(); noteFinish("done")', 'beginEvent(); finish = "done"'),
    ('clock_not_monotonic', 'private let started = ProcessInfo.processInfo.systemUptime', 'private let started = Date().timeIntervalSince1970'),
    ('cancel_presumed_user', 'trace.cancel("network_cancel")', 'trace.cancel("user_stop")'),
    ('unapproved_output', 'final["finish"] = finish', 'final["finish"] = finish; final["body"] = "raw"'),
]


def mutate(source, old, new):
    if source.count(old) != 1:
        raise ValueError('mutant anchor must be unique: ' + old)
    return source.replace(old, new, 1)


def harness(source):
    helper = parts(source)[0].split('\n', 1)[1]
    # The BEGIN marker's trailing comment is not Swift source.
    assert not helper.lstrip().startswith('(also extracted')
    # Extract the real Responses text parser too; only make the method static
    # to house it in a fixture namespace. No copied parser implementation.
    parser = '    static func parseResponsesAPITextDelta' + source.split('    func parseResponsesAPITextDelta', 1)[1].split('    func parseResponsesAPIUsage', 1)[0]
    fixture = (FIXTURES / 'compact_network_trace_20261128.swift').read_text()
    return fixture.replace('/* ACTUAL_HELPER */', helper).replace('/* ACTUAL_TEXT_PARSER */', parser)


def native_run(compiler, source, directory, version, expect_failure=False):
    directory = Path(directory)
    path = directory / 'main.swift'
    path.write_text(harness(source))
    binary = directory / 'network-fixture'
    built = subprocess.run([compiler, '-swift-version', version, '-parse-as-library', str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=120)
    if built.returncode:
        print(built.stdout + built.stderr)
        return False  # A build failure is NOT a killed runtime mutant.
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    if expect_failure:
        return run.returncode != 0
    print(run.stdout + run.stderr)
    return run.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-native', action='store_true')
    parser.add_argument('--emit-harness', type=Path)
    args = parser.parse_args()
    source = PROVIDER.read_text()
    checks = contracts(source)
    print(json.dumps({'source_contracts': checks}, indent=2))
    if not all(checks.values()):
        return 1
    results = {}
    for name, old, new in MUTANTS:
        changed = mutate(source, old, new)
        try:
            failed = [key for key, value in contracts(changed).items() if not value]
        except (ValueError, IndexError):
            failed = ['required_structure_missing']
        results[name] = failed
    print(json.dumps({'source_mutants_rejected': results}, indent=2))
    if not all(results.values()):
        print('FAIL: at least one destructive source mutant survived')
        return 1
    if args.emit_harness:
        args.emit_harness.write_text(harness(source))
    print(f'SOURCE PASS: {len(checks)} contracts; {len(results)} destructive mutants rejected')
    compiler = shutil.which('swiftc')
    if not compiler:
        print('NATIVE SKIP: no Swift compiler; source contracts are NOT runtime/iOS proof')
        return 1 if args.require_native or os.environ.get('V64R_REQUIRE_SWIFT') == '1' else 0
    with tempfile.TemporaryDirectory(prefix='compact-network-fixture-') as directory:
        for version in ['5', '6']:
            if not native_run(compiler, source, directory, version):
                return 1
        for name, old, new in MUTANTS:
            if name not in {'raw_request_id', 'raw_error_domain', 'unknown_ignored', 'malformed_ignored', 'done_erases_length'}:
                continue
            if not native_run(compiler, mutate(source, old, new), directory, '6', expect_failure=True):
                print('FAIL: native mutant not killed by execution: ' + name)
                return 1
            print('NATIVE MUTANT KILLED: ' + name)
    print('NATIVE PASS: actual counting helper + actual Responses text parser, Swift 5/6; no transport/iOS integration')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
