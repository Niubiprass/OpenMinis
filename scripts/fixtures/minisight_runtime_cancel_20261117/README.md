# Actual wake Engine cancellation fixture (2026-11-17)

Run from the repository root:

```sh
python3 scripts/test_minisight_runtime_cancel_20261117.py
# Required macOS CI gate; missing Apple SDK is an error:
python3 scripts/test_minisight_runtime_cancel_20261117.py --require-native
```

The runner reads the entire working-tree `MiniSightWakeEngine.swift`, retaining
all imports and every production method. Five standalone hook calls are inserted
into the generated temporary copy: worker entry, immediately before makeSpotter,
immediately after return/before the current-token guard, before dispatching a
completion, and inside that main-queue block before the token guard. Removing
exactly the listed hook strings must recover every original byte. Full original
Name and Assets sources are appended unchanged; an observing test extension
seeds the original `Assets.Files` into the original `cachedFiles` field to avoid
model/resource I/O. There is no separately implemented Worker state machine.

`harness.swift` invokes the original prepare/stop methods. Semaphore rendezvous
plus real worker/main FIFO drains establish deterministic ordering; timeouts
only diagnose a deadlock (no sleeps/polling as a scheduling surrogate). The
constructor hook is inside the C mock, after allocating its unique opaque
spotter and before returning. C tombstones track each model/stream separately,
wrong-kind or repeated destruction, and stream-before-model cleanup.

Six pause positions each exercise stop, stop+new token, and new-token-only
replacement. Four canceled/superseded stream-failure delivery cases plus deinit
make 23 native cases. Every old success/error callback is suppressed; stopped
state must stay unready; a replacement must have its own success callback,
ready token and live native handles. Repeated stop is idempotent. No audio is
offered. macOS AVFoundation types are linked only because the complete original
Engine is retained; no UIKit, AVAudioEngine, audio session, input node, microphone
permission, capture, model inference or actual ONNX runtime is exercised.

Four compiled native mutants remove the stopped/current-token guard, allow old
cleanup to destroy a new generation, substitute a wrong callback generation,
and call the wrong destructor on a late stream. Compile failure, timeout, or
an unrelated assertion is NOT accepted as a successful behavior negative.
Portable checks reject those source edits and three unlisted/broken hook edits;
portable PASS must not be described as native behavior PASS.

The source manifest pins the actual three production files and three native
support files, not an entire source tree or an unmodified HEAD. It is not
silently regenerated during test execution. C config structs are intentionally
test stand-ins, not an ABI assertion for the real Sherpa header. Existing real
C-module/iOS typecheck, runtime preflight, isolation/provenance and full-app
checks remain separate mandatory gates and are not modified by this test.
