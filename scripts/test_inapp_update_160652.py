#!/usr/bin/env python3
"""Static guard for [T-inapp-update-beta].

About → 应用更新 reads a GitHub Release tag `beta-latest` (manifest + IPA),
compares the CI build stamp, downloads, verifies sha256 and hands the file to
TrollStore. CI republishes that tag on every successful build.

Asserts the wiring exists in both halves and that no secret is shipped.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABOUT = ROOT / "src/ios/Views/Settings/AboutView.swift"
PLIST = ROOT / "src/ios/Info.plist"
WORKFLOW = ROOT / ".github/workflows/ios15-v64-repair.yml"

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


def main():
    about = ABOUT.read_text()
    plist = PLIST.read_text()
    wf = WORKFLOW.read_text()

    # App side.
    need("final class UpdateChecker" in about, "checker exists")
    need("static let repository = \"Niubiprass/OpenMinis\"" in about, "points at the right repo")
    need("static let channelTag = \"beta-latest\"" in about, "uses the fixed tag")
    need("apple-magnifier://install?url=" in about, "hands over through TrollStore")
    need("canOpenURL" in about, "checks the scheme before downloading")
    need("var hasher = SHA256()" in about and "hasher.finalize()" in about, "hashes the download as it streams")
    need("manifest.size" in about, "checks the size too")
    need("MinisBuildNumber" in about, "compares builds, not just versions")
    need("24 * 3600" in about, "automatic check is throttled to one a day")
    need("立即更新" in about and "检查更新" in about, "the two affordances exist")
    need("需要 TrollStore 已启用 URL Scheme" in about, "footer names the prerequisite")

    # No token shipped.
    need("Authorization" not in about, "anonymous API only (no token)")

    # Plist.
    need("apple-magnifier" in plist, "query scheme declared")
    need("MinisBuildNumber" in plist, "build key has a default")

    # CI side.
    need("contents: write" in wf, "workflow may create releases")
    need("Publish beta release for the in-app updater" in wf, "publish step exists")
    need("gh release create \"$TAG\"" in wf, "release is created")
    need("latest.json" in wf, "manifest is published")
    need("--prerelease" in wf, "tagged as a test channel")
    need("Set :MinisBuildNumber ${{ github.run_number }}" in wf, "run number is injected")

    if fails:
        print("❌ in-app update guard failed:")
        for f in fails:
            print("   -", f)
        return 1
    print("✅ in-app update guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
