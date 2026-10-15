# 160644: TextKit 2000pt container truncation

## Direct evidence

Session ADA98F51-EC00-4A6A-B04D-AABF94B05E31, PID 51447. `workspace/test-160644/persisted.json` contains an assistant response of 2804 characters, all 40 numbered paragraphs and END160644. This is not data loss.

Read-only log extraction is in `test-160644/layout-freeze-onset-log.json` and `layout-log.json`. The structured `output` strings contain:

| Time | textStorage length | tcW | tcH | usedH | freshly measured needH |
|---|---:|---:|---:|---:|---:|
| 18:13:02.617 | 1445 | 358 | 1836 | 1836 | 1946 |
| 18:13:03.710 | 1479 | 358 | 2000 | 1994.3 | 2003 |
| 18:13:07.151 | 1569 | 358 | 2000 | 1998.1 | 2007 |
| 18:13:10.171 | 1684 | 358 | 1999 | 1998.1 | 2007 |
| 18:13:16.421 | 1869 | 358 | 1999 | 1998.1 | 2007 |
| 18:14:59.539 | 2764 | 358 | 1999 | 1998.1 | 2007 |

The first five include V42-MISS selfMeasured, not just stale cache hits. V43-WIDTH reports hDirty == hNet, dh=0 at the correct 358pt width. Later IOS15Size reports idealH=2058 and h=2058, consistent with 2007pt text plus 51pt row chrome. UI evidence shows paragraph 22 occupies only 45pt and queued content immediately follows. Fresh session entry does not repair it.

The 2764 TextKit storage length differs from persisted 2804 because rendered markdown need not retain source markers. Storage continues growing after the height freezes; no assumption that rendered and raw lengths must match is needed for the diagnosis.

## Exact cause and propagation

`src/ios/Shared/NSTextContainerSetSizeGuard.m`, former V38C block, unconditionally transformed *every* setSize height >=3000 to 2000. It ran before the already-existing 100000pt cap and before duplicate/storm suppression. Thus both greatestFiniteMagnitude proposals and legitimate 3000..100000pt geometries became a 2000pt text container.

`SelectableMarkdownTextView.sizeThatFits` calls super with greatestFiniteMagnitude. The global swizzle silently converts that into a finite 2000pt layout. TextKit can only fit the initial glyphs; usedRect stops at the last fitting line (1998.1), and UITextView fitting returns 2007 including vertical insets/rounding. Subsequent fresh measurements see the same constrained layout and caches faithfully retain the wrong result. Hosting/cell fitting receives 2058; the examined trace does not show hosting imposing an independent 2058pt cap. The existing text batch invalidation cannot repair an incorrectly constrained upstream measurement.

This explains both the exact plateau and why reentry, correct width, full storage and cache misses coexist with truncation. Historical comments inferred a universal maximum from short samples; that inference is invalid for long responses.

## Minimal patch

- Remove only the V38C >=3000 ->2000 rewrite and its unused counter.
- Retain the existing 100000pt finite bound, width sanitation, invalid geometry rejection, duplicate suppression and 40/160 per-tick storm limits.
- Correct the header documentation to describe the actual finite bound.
- Do not alter Markdown parsing, fitting overrides, cell caching, compression, ChatStore, workflow or prior textBlockLayoutSignal/thinking subscription changes.

## Regression coverage

`src/ios/MinisTests/LongTextContainerLayoutTests.swift` is auto-included by the existing synchronized MinisTests group:

1. Real heights 1999/2000/2999/3000/4000/12000/100000 survive the actual installed swizzle, and greatestFiniteMagnitude maps to 100000.
2. An actual TextKit stack lays out every character of a 40-paragraph Chinese response including END160644, with used height >3000.
3. Production SelectableMarkdownTextView fitting grows from 10 to25 to40 paragraphs beyond 2007, and a fresh view agrees with the incrementally updated view.

`scripts/test_longtext_container_layout.py` checks that the only remaining height rewrite is the existing 100000 bound, verifies storm defences remain, and checks runtime-test registration. All three source-contract tests pass. Existing `scripts/test_v64r_text_layout.py` also passes. These checks are not UIKit execution.

## Validation boundary and remaining risks

No xcodebuild, Swift compiler or UIKit SDK is available in this Alpine environment. The new XCTest cases have not been compiled or run; no IPA was built, pushed or installed. Device interaction was limited to authorized read-only grep of the existing log; no UI operation, restart or app modification was performed.

The larger permitted container may expose the prior long TextKit layout/watchdog performance problem; the existing finite bound and storm protections remain, but no performance claim is made. Content exceeding 100000pt still has a separate pre-existing limit. Attachment-heavy rows, scrolling/deferred correction and hosting caches may have independent issues not eliminated by this patch. Reapplying scripts/ios15_fallback.py would reintroduce the historical V38C rule; it was intentionally not modified under the no-workflow scope. The source-contract regression must run after any such regeneration.

Required later acceptance: run the XCTest cases on iOS, then explicitly authorized fresh-install/manual testing of 40 paragraphs plus a queued user message, all content through END160644 before/after completion/reentry, repeated scrolls, no overlap/gaps, and no prolonged TextKit stalls. This patch is source-fixed, not on-device verified.

## Additional real thinking/tool evidence on installed 160644

DeepSeek high-thinking session AFEC89BF-C25F-4A2A-86F2-49A4A83F185B includes real 1593- and 243-character thinking blocks plus a completed Python tool card. This is independent of the GPT mixed-tools session, which did not return thinking.

ThinkingBlockView deliberately uses an inner ScrollView with `.frame(maxHeight: 300)`, followed by an enclosing rounded clip. Its Text accessibility rect is the full scroll CONTENT, not the clipped viewport. In ds-first-expanded.json the long Text is y423/h1034; after inner scrolling, ds-expanded-settled.json reports y-227/h1034 while its header stays y397 and following prose stays y739. These rects alone are not proof of overlap.

Actual host changes are confirmed by ds-thinking-toggle-height-log.json (read-only existing device log): E3575F75 at 18:22:59 expands 40 ->340pt (+300), at 18:23:08 collapses 340 ->40pt (-300), and at 18:23:24 expands 40 ->340pt again. The following prose in ds-first-collapsed.json moves from y739 to y439, exactly -300pt, while the thinking header remains y397. This matches the estimated 40pt header plus capped 300pt viewport and does not show an unconsumed 300pt blank after collapse. The 243-character block 1ED61360 expands 40 ->262pt (+222) at 18:22:25; both real blocks auto-collapse to40pt when streaming ends.

The source path posts thinkingBlockToggled on manual change and explicitly on auto-collapse; its receiver clears cell, layout and precalc heights, invalidates block memos, reconfigures the row and invalidates layout. The measured transitions show that path applied on these installed-build interactions. No additional thinking layout fix is justified by these captures. This is baseline 160644 evidence, not a post-patch test of the removed TextKit cap. Thinking's SwiftUI Text/inner ScrollView is distinct from SelectableMarkdownTextView's TextKit container; preserve its intentional 300pt viewport rather than enlarging it to the full accessibility text height.
