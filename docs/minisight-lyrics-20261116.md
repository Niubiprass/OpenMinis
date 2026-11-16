# MiniSight Lyrics — local implementation / 2026-11-16

## Ownership / files

Only new files were added. No Pet/Tweak/HomeView/Settings/Config, project, Makefile, STATUS or workflow edits belong to this module. App `src/ios/MiniSightCore/MiniSightLyrics.h/.m` and plugin `debs/MiniSight/MiniSightLyrics.h/.m` are byte-identical. ARC, Foundation plus C/GCD only; minimum intended iOS 15.5. Parent owns target registration, consent gate, MediaRemote, lifecycle and rendering. No commit, push, CI dispatch, installation, device access or real-song request was performed.

## API / integration

- `MiniSightLyricsTrack -initWithTitle:artist:duration:` returns nil for invalid input. Title/artist are NFC + POSIX lowercase + collapsed whitespace, each input at most 512 UTF-16 units, valid UTF-8, no remaining control characters. No punctuation/accent/feature/artist-list stripping. Duration must be finite, 1…3600 seconds. `cacheKey` uses length-prefixed normalized fields and unrounded duration.
- `MiniSightLyricsTimeline +timelineWithLRC:duration:` parses only timed LRC. `lines` and each `MiniSightLyricLine.time/text` are immutable. `-lineAtTime:` is a binary search yielding **only one current line**, or nil. No loading/error/title text.
- `MiniSightLyricsClient -fetchTrack:completion:` cancels/replaces the prior generation. Completion is asynchronous on MAIN. `-cancel` invalidates the generation immediately from any queue, cancels the active task on MAIN and suppresses queued deliveries. Keep one client alive to preserve its cache/cooldown. Never instantiate a new client to bypass a rate limit.
- `+timelineForResponseData:response:track:` and `+retryDelayForResponse:now:attempt:` are pure production test seams. `-initWithProtocolClasses:` permits catch-all Fake NSURLProtocol injection; normal `init` uses no overrides.

Synthetic integration sketch (parent supplies consent/lifecycle gating):

```objc
MiniSightLyricsTrack *track = [[MiniSightLyricsTrack alloc]
    initWithTitle:@"Fixture Song" artist:@"Example Artist" duration:60];
// Do NOT run this snippet with default transport during local development.
[client fetchTrack:track completion:^(MiniSightLyricsTimeline *timeline) {
    // Retain the current timeline only; parent reads lineAtTime: using player time.
    // A nil timeline or nil current line means clear the dedicated lyric bubble.
}];
// Track change, consent disabled, hidden/locked or monitor shutdown:
[client cancel];
```

## Parsing and failure policy

BOM and CR/LF supported; timestamps `m:ss`, `mm:ss.f/ff/fff`, or colon fractions. Multiple leading timestamps are expanded. Metadata tags are ignored. Global `[offset:+/-milliseconds]` is bounded to ±600000 ms; the last valid offset wins. Negative shifted markers clamp to zero; markers at/after duration are discarded. Last source marker wins duplicate timestamps, including empty clearing markers. Before first marker, on a blank, at duration end, or 12 seconds after the current marker, the line is nil. Rewind/seek does not keep a stale cursor.

Malformed/untimed mixtures, invalid timestamps/offsets/duration/control text, input >1 MiB, >8192 physical split rows, >4096 expanded markers, raw row >2048 or text >1024 UTF-16 units fail closed. No invented timing for plain lyrics. This is line-level LRC, not word highlighting or beat detection. The 12-second cap deliberately clears prolonged lines/instrumental tails; long held lyric lines may disappear early. Colon fractions are not an hour-field format.

## Transport / privacy

Only `HTTPS https://lrclib.net/api/get` GET with `track_name`, `artist_name`, `duration`; no album/account/audio, search fallback, redirects, credentials, cookie jar, disk cache or lyric logging. User-Agent: `MiniSight-Lyrics/1.0 (+https://openminis.app)`. Standard system TLS verification, no trust bypass. Ephemeral session, one active data task, 12s request / 15s resource deadline, streamed accumulation <=1 MiB (also checks declared length); errors return nil. Request starts have a 350ms gap.

Only JSON HTTP 200 at the fixed endpoint is evaluated. `trackName`/`artistName` must exactly match the conservative normalization, numeric non-boolean duration must be finite and within ±2s, `instrumental` must be JSON false and `syncedLyrics` must be timed text. `plainLyrics` is never used.

NSCache: 16 entries / 4 MiB configured payload cost (Foundation may evict earlier; limits are its advisory eviction policy), in-memory only; success TTL 1h and HTTP 404 TTL 5m using uptime. No cache of 429 or mismatches. 429/503 obey delta-seconds or HTTP-date Retry-After, with fallback exponential 30/60/120/240/300s and up to 5s positive jitter; never shorten a longer server wait. Malformed Retry-After uses fallback; enormous numeric waits effectively suppress further calls for this client lifetime. No timer or automatic retry loop. A cache miss during cooldown returns nil, so parent may retry later under its own bounded lifecycle policy. Keep the same client for all tracks; cooldown is client-scoped, not a cross-process/global rate limiter.

## Tests / evidence

```
python3 scripts/test_minisight_lyrics_20261116.py
# On an authorized macOS runner, not dispatched by this task:
python3 scripts/test_minisight_lyrics_20261116.py --require-native
# Optional: --plugin-root /path/to/plugin-tree
```

The Python runner compiles the **unchanged production .m** together with `scripts/fixtures/minisight_lyrics_20261116.m`, Apple clang, ARC, and **Foundation only**. The JSON fixture contains invented names/text only. Catch-all NSURLProtocol intercepts every request; no real network fallback is permitted. Golden outputs cover offset/fractions/blanks/seek/duration, strict signatures/schema/content type, query/config privacy, declared/streamed body limits, positive/404 cache and expiry, 429 headers/cooldown, cancellation/replacement/late callbacks (including stale 429 and off-main cancel), redirect denial and weak delegate lifecycle. A few private callbacks/KVC fields are used solely for deterministic race/expiry tests.

Six production-source native mutants must fail independent assertions: duration tolerance removed, delivery generation ignored, task identity removed, Retry-After ignored, blanks returned as text, and body limit doubled. Baseline must pass before any mutant counts; compiler errors/crashes are not accepted as assertion-based kills.

Local result on Alpine: **4 source-conformance checks passed; native Foundation test class explicitly SKIPPED** because no Apple Foundation SDK/xcrun/swiftc exists. The fixture's macro preprocessing also passed; this is NOT Objective-C compilation. Source-level negative controls were detected, but they are not runtime proof. `--require-native` converts unavailable native execution to failure rather than success. No macOS/iOS build or native tests were run, and no CI configuration was edited. Native correctness and parent target registration remain unverified until the authorized build actually runs.
