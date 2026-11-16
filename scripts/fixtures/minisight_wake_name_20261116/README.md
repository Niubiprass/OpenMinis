# MiniSight wake-name fixtures (2026-11-16)

`tokens.txt` is a byte-for-byte test copy of the already-downloaded
`sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile/tokens.txt`.
Source was read only from `/var/minis/workspace/pet-three-features/wake/provenance/`.
227 symbols; 1627 bytes; SHA-256:
`72316508d9119696145abc6f1f8cdc46287535c34e5ce7e595f845cb1499cf2e`.
The existing local official `source/sherpa-utils.py` specifies ppinyin with
`to_initials(..., strict=False)` / `to_finals_tone(..., strict=False)`.
This explains y/w initials, written u after j/q/x/y, and ü after n/l.
No model binary, library, permission request, license claim, or download is added.

From the repository root:

```sh
python3 -B scripts/test_minisight_wake_name_20261116.py
# Future macOS CI, verified Apple Swift only; missing compiler fails closed:
python3 -B scripts/test_minisight_wake_name_20261116.py --require-native
```

The runner checks source guards and the actual vocabulary hash everywhere.
Only macOS Apple Swift compiles the real module together with `main.swift`
and runs behavior assertions. Linux/iSH reports SKIP, never simulated Swift
success. `--require-native` returns 2 when native execution is unavailable;
source/compile/behavior failures return 1. Temporary binaries stay outside the repo.
No existing project file or workflow is modified.

API: `MiniSightWakeName.prepare(name:pronunciation:vocabulary:)` returns immutable
Equatable `Prepared(name, pronunciation, tokens, definition)`.
`vocabulary(from:)` strictly parses UTF-8 tokens with contiguous unique IDs,
unique NFC symbols and a 32 KiB bound. `definition` is only joined tokens plus
` @minisight`; no name or input grammar is interpolated.

Automatic mode deliberately allows only the reviewed common-character set in
the source. All unreviewed, polyphonic and rare characters require an explicit
space-separated reading. Names remain 2–8 unified Han characters; explicit
reading is a syntax/count/token check, not proof of glyph-to-reading semantics.
The caller must display the resulting pronunciation and have the user confirm it.
Tone 1–4 numbers or correct accent marks are supported; 0/5 or unmarked legal
syllables represent neutral tone and still must exist in the actual vocabulary.
`v`/`ü` are supported; `u:` and punctuation/control characters are rejected.
No greedy, whole-syllable or untoned fallback is used for missing tokens.

Native fixtures include automatic 小鱼/小肥鱼/eight Han characters, 重/行 correction,
review gates, rare-character correction, numeric tones, neutral tone, ü/v,
j/q/x/y and zero-initial syllables, invalid names/grammar/control/count,
NFC equivalence, OOV fail-closed behavior and malformed tokens.txt inputs.
Apple Swift compilation, iOS integration, audio/KWS accuracy and microphone
behavior are unverified here; no iOS build, device action or CI push is performed.
