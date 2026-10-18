#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests: [T-ios15-nav-pop] iOS15 列表刷新不再把当前会话弹回主界面。

Root cause: the iOS 15 NavigationStack shim (iOS15Compat.swift) drives the
push with a per-row `NavigationLink(value:)` whose state lives inside the
List row. Any session-list refresh (any other session finishing output
posts .sessionDidUpdate -> refreshSessionList) re-renders the rows and iOS 15
drops the active row-link state -> the open chat pops back to the root.

Fix: the compact-path row tap now routes into `openSession` /
`commitNavigationPath` (the root-level hidden isActive link performs the
push). The row's background NavigationLink(value:) is retained for the
split/iPad path (it never fires on compact: empty label).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


print("== [T-ios15-nav-pop] contract tests ==")

cv = read("src/ios/Views/ContentView.swift")
compat = read("src/ios/iOS15Compat.swift")

# 1) The compact row tap must route through openSession (not row-link state).
m = re.search(
    r"erasedSessionRow\(session, group: group\)\s*\.contentShape\(Rectangle\(\)\)\s*\.onTapGesture\s*\{\s*openSession\(session\.id\)\s*\}",
    cv,
)
check("row tap routes to openSession via path commit", bool(m),
      "expect .onTapGesture { openSession(session.id) } after erasedSessionRow")

# 2) The fix must be scoped to the non-selecting branch of stackListBody.
seg = cv[cv.find("private func stackListBody"):]
check("onTap appears inside stackListBody row branch", "onTapGesture" in seg)

# 3) The comment documents the iOS15 pop root cause next to the fix.
check("root-cause comment present", "[T-ios15-nav-pop]" in cv)

# 4) The row background NavigationLink(value:) must STAY (iPad/split path).
check("row NavigationLink(value:) retained for split layout",
      "NavigationLink(value: session.id) { EmptyView() }" in cv
      or re.search(r"NavigationLink\(value: session\.id\)", cv) is not None)

# 5) iOS15Compat's root isActive link semantics unchanged (path-driven).
m = re.search(r"get:\s*\{\s*!path\.isEmpty\s*\}", compat)
check("iOS15Compat isActive get stays !path.isEmpty", bool(m))

# 6) openSession still commits through the background-aware gate.
m = re.search(r"commitNavigationPath\(next\)", cv)
check("openSession compact branch uses commitNavigationPath", bool(m))

# 7) Negative: no blind delay-based push was introduced for row taps.
check("no delayed row-tap push added",
      "asyncAfter" not in seg.split("Section {")[0][-2000:])

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL PASS")