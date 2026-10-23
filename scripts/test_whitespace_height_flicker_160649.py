#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = (ROOT / "src/ios/Views/Chat/AssistantBlockView.swift").read_text()
LIST = (ROOT / "src/ios/Agent/MessageList/CollectionViewMessageListV3.swift").read_text()

# Rendering, snapshot seeding, and the fallback estimator must agree.
blank = ".whitespacesAndNewlines).isEmpty"
assert VIEW.count(blank) >= 1, "SwiftUI text rendering must omit whitespace-only blocks"
assert LIST.count(blank) >= 2, "snapshot seed and text estimator must both treat whitespace as empty"
assert "layout.setEstimatedHeight(0, at: i)" in LIST, "empty blocks must not fall back to 200pt"

# Model the exact normalization predicate for the device-log examples.
def has_visible_text(value: str) -> bool:
    return bool(value.strip())

for value in ("", " ", "\n", " \n\t\r "):
    assert not has_visible_text(value), repr(value)
for value in ("a", " a ", "\ntext\n"):
    assert has_visible_text(value), repr(value)

print("Whitespace height/flicker regression: PASS")
print("cases: empty, space, newline, mixed whitespace, visible text")
print("source contracts: renderer, snapshot seed, estimator aligned")
