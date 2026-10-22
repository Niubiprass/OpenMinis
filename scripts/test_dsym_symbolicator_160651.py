#!/usr/bin/env python3
"""Source contracts for the dSYM symbol-table reader and its .ips UI."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
DSYM = (IOS / "Views/Settings/DSYMSymbolicator.swift").read_text(encoding="utf-8")
LOGS = (IOS / "Views/Settings/LogManagementView.swift").read_text(encoding="utf-8")
PROJECT = (IOS / "Minis.xcodeproj/project.pbxproj").read_text(encoding="utf-8")


class DSYMContracts(unittest.TestCase):
    def test_reads_uuid_symtab_and_nlist64(self):
        for token in ("LC_UUID", "LC_SYMTAB", "nlist_64", "LC_SEGMENT_64", "textVMAddress"):
            self.assertIn(token, DSYM)
        self.assertIn("func symbol(at address: UInt64) -> String?", DSYM)

    def test_symbolication_requires_uuid_and_keeps_existing_symbols(self):
        self.assertIn("store.matches(uuid: frame.imageUUID)", DSYM)
        self.assertIn("if let symbol = frame.symbol, !symbol.isEmpty { return frame }", DSYM)
        self.assertIn("static func symbolicate(_ report: CrashIPSReport, store: DSYMStore)", DSYM)

    def test_ui_imports_dsym_and_renders_result(self):
        i = LOGS.index("struct CrashIPSDetailView")
        j = LOGS.index("// MARK: - [T-crash-report-groups]", i)
        body = LOGS[i:j]
        self.assertIn("showDSYMPicker", body)
        self.assertIn("DSYMStore(dsymURL: url)", body)
        self.assertIn("DSYMSymbolicator.symbolicate(report, store: store)", body)
        self.assertIn("displayReport", body)

    def test_source_is_in_the_app_target(self):
        name = "DSYMSymbolicator.swift"
        refs = re.findall(r"^\s*(\w+) /\* " + re.escape(name) + r" \*/ = \{isa = PBXFileReference;", PROJECT, re.M)
        self.assertEqual(len(refs), 1)
        builds = re.findall(r"^\s*(\w+) /\* " + re.escape(name) + r" in Sources \*/ = \{isa = PBXBuildFile;", PROJECT, re.M)
        self.assertTrue(builds)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: dSYM symbol table/UI; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
