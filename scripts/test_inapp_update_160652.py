#!/usr/bin/env python3
"""Static guard for [T-inapp-update-beta].

About → 应用更新 reads a GitHub Release tag `beta-latest` (manifest + IPA),
compares the CI build stamp, downloads in a background URLSession, verifies
sha256 and hands the file to TrollStore. CI republishes that tag on every
successful build.

Asserts the wiring exists in both halves and that no secret is shipped.
Static source contracts only — not a Swift build and not runtime proof.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABOUT = ROOT / "src/ios/Views/Settings/AboutView.swift"
CONTENT = ROOT / "src/ios/Views/ContentView.swift"
DELEGATE = ROOT / "src/ios/AppDelegate.swift"
PLIST = ROOT / "src/ios/Info.plist"
WORKFLOW = ROOT / ".github/workflows/ios15-v64-repair.yml"

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


def main():
    about = ABOUT.read_text()
    content = CONTENT.read_text()
    delegate = DELEGATE.read_text()
    plist = PLIST.read_text()
    wf = WORKFLOW.read_text()

    # App side — release feed.
    need("final class UpdateChecker" in about, "checker exists")
    need("static let repository = \"Niubiprass/OpenMinis\"" in about, "points at the right repo")
    need("static let channelTag = \"beta-latest\"" in about, "uses the fixed tag")
    need("apple-magnifier://install?url=" in about, "hands over through TrollStore")
    need("canOpenURL" in about, "checks the scheme before downloading")
    need("MinisBuildNumber" in about, "compares builds, not just versions")

    # Integrity of the downloaded package.
    need("nonisolated static func verifyFile" in about, "verification runs off the main actor")
    need("var hasher = SHA256()" in about and "hasher.finalize()" in about, "hashes the download")
    need("manifest.size" in about, "checks the size too")
    need("moveItem(at: location" in about, "saves the system download file")

    # [T-inapp-update-cache] The result survives leaving About and the daily gate.
    for key in ["cachedManifestKey", "cachedIPAURLKey", "checkedBuildKey", "lastAttemptKey"]:
        need(key in about, "persists/uses " + key)
    need("func autoCheckIfEnabled" in about, "one entry point for every trigger")
    need("enum UpdateCheckSchedule" in about, "checking policy is testable")
    need("successInterval: TimeInterval = 24 * 3600" in about, "daily gate is preserved")
    need("retryInterval: TimeInterval = 5 * 60" in about, "failures retry in minutes, not a day")

    # A failed recheck must not claim "latest" nor erase a known update.
    need("isLatest = false" in about, "checking/failure never claims latest")
    need("hasUpdate = manifest.build > build" in about, "the badge follows the real build number")

    # Settings entry badge (approved design: red dot + 有更新 / grey 已是最新).
    need("struct AboutUpdateBadge" in about, "badge component exists")
    need("Text(\"有更新\")" in about and "Text(\"已是最新\")" in about, "both badge states exist")
    need("AboutUpdateBadge()" in content, "Settings About row uses the badge")
    need("UpdateChecker.shared" in content, "Settings shares one updater instance")
    need("autoCheckIfEnabled()" in content, "opening Settings triggers the check")

    # Triggers outside About.
    need("UpdateChecker.shared.autoCheckIfEnabled()" in delegate, "cold launch restores state and checks")
    need("func sceneDidBecomeActive" in delegate and "becameActive()" in delegate,
         "returning to the foreground re-checks")
    need("handleEventsForBackgroundURLSession" in delegate, "background completion is forwarded")
    need("UpdateDownloadCoordinator.sessionIdentifier" in delegate, "only our own session is intercepted")

    # [T-inapp-update-background] Download keeps running off the About page.
    need("UpdateDownloadCoordinator" in about, "download coordinator exists")
    need("nonisolated static let sessionIdentifier" in about, "background session has a stable id")
    need("URLSessionConfiguration.background(withIdentifier:" in about, "uses a background session")
    need("sessionSendsLaunchEvents = true" in about, "finishes while suspended")
    need("func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask" in about,
         "uses the download-task delegate")
    need("totalBytesWritten" in about, "progress comes from real byte counts")
    need("func restore()" in about, "recovers a system-relaunched transfer")
    need("update.download.pending" in about, "the transfer is durable metadata")

    # Real HTTP status, not a blanket "no beta yet".
    need("func requireOK" in about and "statusCode == 200" in about, "status is inspected")
    need("\"User-Agent\"" in about, "GitHub requests carry a User-Agent")
    # The old byte-by-byte reader is gone.
    need("URLSession.shared.bytes(from:" not in about, "no byte-by-byte reader remains")

    # [T-inapp-update-no-api] The anonymous REST API is capped at 60 requests
    # per hour per IP; exhausting it broke every check on device 2026-11-05.
    # The fixed releases/download path serves the same bytes without that quota.
    need("https://api.github.com" not in about, "no api.github.com dependency")
    need("releases/download/" in about, "reads the release through the download path")
    need("func releaseAssetURL" in about, "asset URLs are built from fixed names")
    need("case 404, 410:" in about, "the publish gap is reported as such")

    # Affordances the UI contract asks for.
    need("立即更新" in about and "检查更新" in about, "the two affordances exist")
    need("安装更新" in about, "a ready download can be installed on demand")
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
    print("   (static source contracts only: not compiled, not run on a device)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
