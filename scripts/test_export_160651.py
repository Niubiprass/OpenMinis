#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract tests: [T-115-export] 分享对话为长图或 PDF (App Store 1.15).

Port scope v1 (iOS 15.5): full-conversation long-image export + multi-page
PDF export, header (icon / model / date), light&dark following, zoomable
preview + share sheet. NOT ported: drag-select range, fold/hide tool calls,
width presets — documented in ChatExportView.swift.
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


print("== [T-115-export] contract tests ==")

exp_path = ROOT / "src/ios/Views/Chat/ChatExportView.swift"
check("ChatExportView.swift exists", exp_path.exists())
exp = exp_path.read_text(encoding="utf-8", errors="replace") if exp_path.exists() else ""

# 1) Renderer
check("renderer builds rows from RawMessage", "static func buildRows(from messages: [RawMessage])" in exp)
check("user rows extracted", 'rows.append(Row(kind: .user' in exp)
check("assistant text rows extracted", 'Row(kind: .assistant' in exp)
check("thinking collapsed to meta row", 'rows.append(Row(kind: .meta, text: "思考 ·' in exp)
check("tool calls collapsed to meta lines", '"⚙︎ \\(tu.name)"' in exp or '"⚙︎ " + tu.name' in exp)
check("long image renderer", "static func renderLongImage(" in exp)
check("PDF renderer", "static func renderPDF(" in exp)
check("header draws icon+model+date", "drawHeader(" in exp and "Minis · " in exp)
check("light/dark via systemBackground", "UIColor.systemBackground" in exp)
check("renderer uses supported trait initializer", "UIGraphicsImageRendererFormat(for: UITraitCollection.current)" in exp)
check("no nonexistent renderer trait property", "format.traitCollection =" not in exp)

# 2) Preview + share
check("zoomable preview", "ZoomableImageScrollView" in exp)
check("QuickLook PDF preview", "QLPreviewWrapper" in exp)
check("share sheet", "UIActivityViewController" in exp)
check("share entry button", 'Image(systemName: "square.and.arrow.up")' in exp)

# 3) Entry: menu → export sheet
cv = read("src/ios/Views/Chat/AIChatView.swift")
check("@State exportKind", "@State private var exportKind: ChatExportKind? = nil" in cv)
check("menu onExportImage closure", "onExportImage: { exportKind = .longImage }" in cv)
check("menu onExportPDF closure", "onExportPDF: { exportKind = .pdf }" in cv)
check("sheet presents ChatExportSheet", re.search(r'sheet\(item: \$exportKind\)[\s\S]{0,400}?ChatExportSheet\(kind: kind', cv) is not None)
check("UIKit menu has both export actions", 'AppLocalized("导出长图")' in cv and 'AppLocalized("导出 PDF")' in cv)
check("export actions disabled on empty session", "key.messagesEmpty ? [.disabled]" in cv)
check("export loads full history from store", "loadMessages(sessionId: sessionId)" in exp)

# 4) iOS15 safety
check("no LabeledContent in export view", "LabeledContent" not in exp)
check("no iOS16-only API used", "navigationDestination" not in exp and "contentUnavailable" not in exp)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL PASS")