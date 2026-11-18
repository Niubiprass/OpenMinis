# Bubble edge regression (2026-11-18)

Run from the repository root (P: `debs/MiniSight`, A: repository root):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_minisight_bubble_edge_20261118.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_minisight_bubble_edge_20261118.py --require-native
```

- `portable_cases.h` executes actual `MiniSightLayout.h` / `MiniSightGeometry.h` C functions, 24 added checks. It is also included by P's existing `tests/layout_test.c`; no existing test is replaced. This is geometry evidence only, not a Python reimplementation of Show/Follow state.
- `native.mm` compiles exact production Show/Place/Follow, BodySize/Reserve/LayoutNow, Hide/Cancel/Answer and button target classes with macOS Foundation, CoreGraphics and QuartzCore. UIKit, font measurement, result writing and other external dependencies are mocks. Only DestroyUI's bubble reset statements and the confirm timeout block are extracted, not the complete teardown or ShowConfirm I/O path.
- Native cases cover first top-hidden 160x52 -> middle, hidden long/short text, stationary viewport clipping/restoration, landscape rotation, safe-area changes, stationary body resize, hide/show/rebuild, unchanged capsule/approval headroom, same-size approval button bar second pass, cancellation/idempotent cancellation, explicit deny/allow and timeout denial. They are NOT a real UIKit/phone/manual approval verification.
- Native baseline must compile AND pass before any mutation is tried. All mutants must compile and fail a named runtime assertion: original no-size/early-return, center-only cache, clipped-bounds reuse, stale tail. Build failure is never counted as a killed mutation.
- The portable `fit-always-true` mutation independently compiles after its C baseline and is rejected by C assertions; it does not stand in for native state/cache mutants.
- Linux/iSH skips native explicitly. `--require-native` exits nonzero there; no fake Apple compiler, no pass claimed.

## Mirrored provenance

`source.json` contains byte-exact function/statement excerpts from P's working tree. `provenance.json` records P base HEAD, full working-source SHA, pre-repair SHA, each excerpt SHA and both header SHAs. Base HEAD is NOT claimed to contain the uncommitted repair. P reads/extracts current Tweak and demands equality with the audited snapshot; A validates and uses the local snapshot only. Neither test invokes nor reads any external P path. A uses its own production Geometry header; fixture Layout is an exact, hash-checked P copy. The mirrored Layout is not a replacement App production header.

Approval ShowConfirm/result-writer/Answer/Cancel are SHA-identical to the delegated pre-repair snapshot. ShowBubbleWidth minus the single desired-size assignment is likewise byte-identical: no width/font/cap/style changes. Parent bounds test's frame-before-no-fit contract remains unchanged.

This test has NOT been added to workflow files. Suggested later registration: both repositories run the default command; Apple-host gates additionally run `--require-native`. P retains the full layout suite and existing bounds test. No CI/device dispatch is performed by this fixture.
