# Whole-group dragging — local candidate

User-approved behavior: retain the native List/Section UI. No new handle, no extra sorting section, no flat-row backgrounds. In explicit edit mode, long-press the full existing gray title strip, move the group, release in the requested slot. Provider rows keep their original native onMove within their own group.

## What was actually wrong in build 289

- The old receiver was attached only to a narrow header HStack: releasing over a card or above/below the list did not have a corresponding receiver.
- The old moveGroup always inserted before the target: A→B in ABC returned ABC, and A→C returned BAC, so moving the first group to the last slot was impossible with that function.
- There was no event trail proving performDrop was absent. The earlier claim that SwiftUI headers cannot receive drops was not established and must not be repeated as a fact.

## Reference and adaptation

Adam Shin's SwiftReorder, MIT, pinned commit `9553a0d805c68d2bdd1bc6e5385cf1d5e9c44a4c`:

- https://github.com/adamshin/SwiftReorder/blob/9553a0d805c68d2bdd1bc6e5385cf1d5e9c44a4c/Source/ReorderController%2BGestureRecognizer.swift
- https://github.com/adamshin/SwiftReorder/blob/9553a0d805c68d2bdd1bc6e5385cf1d5e9c44a4c/Source/ReorderController%2BAutoScroll.swift

Adapted: UILongPressGestureRecognizer handling, a floating native snapshot, CADisplayLink edge scrolling, explicit gesture cancellation. The MIT notice is retained beside the bridge source. This is an adaptation of its technique, not an assertion that the upstream row library supports SwiftUI section reordering.

A noninteractive background probe locates the existing native header and list scroll view. The bridge does not replace List's delegate, data source, pan recognizer, row reorder controls or section renderer. Only presses beginning in an existing header are claimed. Selection starts after 0.3s; no visible UI is added until an actual drag starts.

The destination is a final insertion slot among all other groups, measured from native whole-section rectangles; remeasure after scrolling and before release. Saving is synchronous into ProviderConfigStore.reorderInstances. Group membership and the starting order are rechecked before committing. Moving within the same slot does not save. Gesture cancellation, backgrounding, leaving the page, or a sync changing the member set does not save.

`ProviderGroupDrag` logs fixed stages (begin/release/saved/cancel) and type names/indices only; no credentials, account labels or model lists.

## Checks and limits

- Source contracts verify native Section structure, no flat rows/custom cards/extra icons, unchanged row onMove and save path.
- Swift fixture extracts the actual production policy, checks first/last/adjacent swap/invalid geometry and exhaustive source/touch combinations. It must run in CI; iSH has no swiftc.
- CI typechecks the actual UIKit bridge against the iOS15.5 deployment target. This checks Apple API names/signatures; it does not execute touch input.
- The drag preview captures the visible part of the native group. For a group taller than the viewport it is clipped to that visible part; the saved operation still moves every member, not only visible rows.
- No simulator gesture execution or on-device acceptance has occurred. Native List hierarchy discovery, long-press competition, snapshot/edge-scroll feel and persistence after reload still require the candidate build to be tested.
- Previous Python translations and HTML animations are not runtime evidence for the Swift implementation.

## Device baseline for this report

Read-only Info.plist check: installed Minis 1.15, CFBundleVersion160652, MinisBuildNumber289, minOS15.5. No device settings, credentials, installation or real provider requests were changed during this local task.
