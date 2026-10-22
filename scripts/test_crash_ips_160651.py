#!/usr/bin/env python3
"""Source contracts for Apple .ips parsing/symbolication and its UI wiring.

Not Swift compilation and not a device test. The parser is intentionally
best-effort: UUID-matched images only; raw reports are still shareable.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
PARSER = (IOS / "Views/Settings/CrashIPSSymbolicator.swift").read_text(encoding="utf-8")
LOGS = (IOS / "Views/Settings/LogManagementView.swift").read_text(encoding="utf-8")
MANAGER = (IOS / "Shared/LoggingManager.swift").read_text(encoding="utf-8")
PROJECT = (IOS / "Minis.xcodeproj/project.pbxproj").read_text(encoding="utf-8")


class CrashIPSContracts(unittest.TestCase):
    def test_parser_handles_two_line_and_single_json(self):
        self.assertIn("maxSplits: 1", PARSER)
        self.assertIn("jsonObject", PARSER)
        self.assertIn("usedImages", PARSER)
        self.assertIn("faultingThread", PARSER)
        self.assertIn("imageOffset", PARSER)

    def test_symbolicator_requires_matching_uuid(self):
        self.assertIn("image.uuid.caseInsensitiveCompare(frame.imageUUID)", PARSER)
        self.assertIn("dladdr(pointer, &info)", PARSER)
        self.assertIn("_dyld_get_image_header", PARSER)
        self.assertIn("LC_UUID", PARSER)

    def test_ips_is_listed_as_crash_and_importable(self):
        self.assertIn('$0.pathExtension == "log" || $0.pathExtension == "ips"', MANAGER)
        self.assertIn('name.hasSuffix(".ips")', MANAGER)
        self.assertIn("func importCrashReport(from url: URL) -> Bool", MANAGER)
        self.assertIn("showIPSPicker", LOGS)
        self.assertIn(".fileImporter(isPresented: $showIPSPicker", LOGS)
        self.assertIn("importCrashReport(from: url)", LOGS)

    def test_ips_uses_parsed_detail_not_raw_only(self):
        self.assertIn("let ipsReport: CrashIPSReport?", LOGS)
        self.assertIn("CrashIPSParser.parse(url: file.url)", LOGS)
        self.assertIn("CrashSymbolicator.symbolicate(parsed)", LOGS)
        self.assertIn("CrashIPSDetailView(entry: entry)", LOGS)
        self.assertIn("ExternalFileImporter.ingest(entry.url", LOGS)

    def test_source_files_are_in_the_app_target(self):
        for name in ("CrashIPSSymbolicator.swift", "LogManagementView.swift"):
            refs = re.findall(r"^\s*(\w+) /\* " + re.escape(name) + r" \*/ = \{isa = PBXFileReference;", PROJECT, re.M)
            self.assertEqual(len(refs), 1, name)
            builds = re.findall(r"^\s*(\w+) /\* " + re.escape(name) + r" in Sources \*/ = \{isa = PBXBuildFile;", PROJECT, re.M)
            self.assertTrue(builds, name)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: .ips parser/UI; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)