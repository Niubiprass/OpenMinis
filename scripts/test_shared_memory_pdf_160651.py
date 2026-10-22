#!/usr/bin/env python3
"""Source contract for read-only shared-memory PDF export."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW = (ROOT / "src/ios/Views/Settings/SoulSettingsView.swift").read_text(encoding="utf-8")


class SharedMemoryPDF(unittest.TestCase):
    def test_exporter_renders_a_pdf(self):
        self.assertIn("enum SharedMemoryPDFExporter", VIEW)
        self.assertIn("UIGraphicsPDFRenderer", VIEW)
        self.assertIn(".pdf", VIEW)
        self.assertIn("只读快照", VIEW)

    def test_detail_uses_pdf_not_markdown(self):
        i = VIEW.index("struct SharedMemoryDetailView")
        j = VIEW.index("struct PersonaShareSheet", i)
        body = VIEW[i:j]
        self.assertIn("SharedMemoryPDFExporter.export(record)", body)
        self.assertNotIn("store.exportURL(record)", body)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: shared memory PDF; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
