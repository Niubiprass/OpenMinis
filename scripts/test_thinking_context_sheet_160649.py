#!/usr/bin/env python3
"""Static regression checks for the thinking bottom sheet."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
view = (ROOT / "src/ios/Views/Chat/AssistantBlockView.swift").read_text()
chat = (ROOT / "src/ios/Views/Chat/AIChatView.swift").read_text()
catalog = json.loads((ROOT / "src/ios/Localizable.xcstrings").read_text())["strings"]

start = view.index("struct ThinkingLevelSheetView: View")
end = view.index("struct TypingIndicator", start) if "struct TypingIndicator" in view[start:] else len(view)
sheet = view[start:]
required = [
    "ThinkingSlider(levels: levels, selected: selectedBinding)",
    "ThinkingContextBar(system: fixed, messages: messages, window: window)",
    "contextUsage: ContextUsage?",
    "contextFixedTokens: Int",
    "@State private var thinkingEnabled: Bool",
    "private func commit()",
    "onSelect(result)",
    "UISheetPresentationController",
    "sheet.detents = [.medium(), .large()]",
    ".presentationDetents([.fraction(0.6), .large])",
]
for token in required:
    assert token in sheet, f"missing sheet contract: {token}"
assert "contextUsage: vm.contextUsage" in chat
assert "contextFixedTokens: vm.contextFixedTokens" in chat
assert ".thinkingLevelSheetPresentation()" in chat
assert "showThinkingLevelSheet = false" in chat

keys = [
    "Thinking Intensity", "Done", "Drag the slider or tap a dot. Levels follow the current model.",
    "Thinking Process", "Hide thinking process when off", "System & Settings",
    "Message Content", "Remaining Space",
]
for key in keys:
    assert key in catalog, f"missing localization key: {key}"
    loc = catalog[key].get("localizations", {})
    assert "en" in loc and "zh-Hans" in loc, f"missing locales for {key}"

# The old menu remains a separate surface; the new sheet is opened by its existing call site.
assert "Menu" in chat and "showThinkingLevelSheet" in chat
print("Thinking context bottom-sheet source contracts PASS")
