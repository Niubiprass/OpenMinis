#!/usr/bin/env python3
"""Source guards everywhere; real Foundation/Swift behavior ONLY on Apple macOS.
Use --require-native in future macOS CI. No Python transliteration/behavior surrogate.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/ios/MiniSightWakeName.swift"
FIXTURES = ROOT / "scripts/fixtures/minisight_wake_name_20261116"
TOKENS_SHA256 = "72316508d9119696145abc6f1f8cdc46287535c34e5ce7e595f845cb1499cf2e"


def sourceguard():
    source = SOURCE.read_text(encoding="utf-8")
    checks = {
        "Foundation only": re.findall(r"^import\s+(\w+)", source, re.M) == ["Foundation"],
        "enum API": "enum MiniSightWakeName {" in source,
        "Equatable result": "struct Prepared: Equatable {" in source,
        "immutable result": all(f"let {field}: {kind}" in source for field, kind in
                                [("name", "String"), ("pronunciation", "String"),
                                 ("tokens", "[String]"), ("definition", "String")]),
        "prepare API": bool(re.search(r'static func prepare\(name: String, pronunciation: String = "",\s*'
                                     r'vocabulary: Set<String>\) throws -> Prepared', source)),
        "vocabulary API": "static func vocabulary(from data: Data) throws -> Set<String>" in source,
        "local transliteration": "applyingTransform(.toLatin, reverse: false)" in source,
        "bounded vocabulary": "data.count <= 32 * 1024" in source,
        "unique symbols": "symbols.insert(symbol).inserted" in source,
        "unique IDs": "ids.insert(id).inserted" in source,
        "complete IDs": "ids == Set(0..<symbols.count)" in source,
        "strict columns": "columns.count == 2" in source,
        "Han/name limits": "(2...8).contains(count)" in source and "isHan($0.value)" in source,
        "NFC": "precomposedStringWithCanonicalMapping" in source,
        "review required": "normalizedName.allSatisfy({ automaticCharacters.contains($0) })" in source,
        "matching syllables": "syllables.count == count" in source,
        "each token validated": "vocabulary.contains(token)" in source,
        "fixed keyword tag": 'definition: tokens.joined(separator: " ") + " @minisight"' in source,
        "no side-effect APIs": not re.search(r'\b(?:URLSession|URLRequest|FileManager|Bundle|'
                                             r'AVAudio\w*|SFSpeech\w*|UserDefaults|Keychain|SecItem\w*|'
                                             r'Process|UIApplication)\b|Data\(contentsOf:|https?://', source),
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise RuntimeError("sourceguard: " + ", ".join(failures))
    data = (FIXTURES / "tokens.txt").read_bytes()
    if hashlib.sha256(data).hexdigest() != TOKENS_SHA256:
        raise RuntimeError("actual model tokens fixture SHA-256 mismatch")
    if len(data.splitlines()) != 227:
        raise RuntimeError("actual model tokens fixture count mismatch")
    if not (FIXTURES / "main.swift").is_file():
        raise RuntimeError("missing real Swift fixture")
    print(f"PASS sourceguard: {len(checks)} guards; actual tokens SHA-256 verified", flush=True)


def apple_swift():
    if sys.platform != "darwin":
        return None, "requires macOS Apple Swift; current platform is " + sys.platform
    compiler = shutil.which("swiftc")
    if shutil.which("xcrun"):
        found = subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True, text=True, timeout=30)
        if found.returncode == 0:
            compiler = found.stdout.strip()
    if not compiler:
        return None, "Apple swiftc not installed"
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=30)
    details = version.stdout + version.stderr
    if version.returncode != 0 or "Apple Swift version" not in details or "apple" not in details.lower():
        return None, "compiler is not a verified Apple Swift toolchain"
    return compiler, details.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-native", action="store_true", help="fail closed unless Apple Swift runs")
    args = parser.parse_args()
    try:
        sourceguard()
        compiler, reason = apple_swift()
        if not compiler:
            print(("FAIL" if args.require_native else "SKIP") + " native Swift behavior: " + reason,
                  flush=True)
            return 2 if args.require_native else 0
        print("TOOLCHAIN: " + reason, flush=True)
        sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                                      text=True, timeout=30).strip()
        if not Path(sdk).is_dir():
            raise RuntimeError("Apple macOS SDK unavailable; native behavior did not run")
        with tempfile.TemporaryDirectory(prefix="minisight-wake-name-") as directory:
            binary = str(Path(directory) / "wake-name-fixtures")
            subprocess.run([compiler, "-sdk", sdk, "-swift-version", "5", "-warnings-as-errors", str(SOURCE),
                            str(FIXTURES / "main.swift"), "-o", binary], check=True, timeout=120)
            subprocess.run([binary, str(FIXTURES)], check=True, timeout=30)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
