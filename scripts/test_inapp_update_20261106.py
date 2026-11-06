#!/usr/bin/env python3
"""Regression guard for in-app update failure handling (2026-11-06).

Device evidence: build 206 installed; a persisted manifest for build 222 with an
empty transfer directory. The update flow must survive relaunch, bind cached
URLs to the exact asset, never discard a known update on a failed recheck, and
report real HTTP/hash/save errors. Static only.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
ABOUT = (ROOT / "src/ios/Views/Settings/AboutView.swift").read_text()
WF = (ROOT / ".github/workflows/ios15-v64-repair.yml").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


# Relaunch: taskIdentifier can change, transferID is stable.
need("tasks.first { $0.taskDescription == saved.transferID }" in ABOUT,
     "restore matches by stable transfer id")
need("$0.taskIdentifier == saved.taskIdentifier" not in ABOUT.split("let matching")[1][:300],
     "restore does not require the old process-local task identifier")
need("tasks.filter { fileExists || $0 !== matching }.forEach { $0.cancel() }" in ABOUT,
     "only non-matching tasks are cancelled")

# Failure carries a structured error with retry-after support.
need("case failed(UpdateManifest?, UpdateError)" in ABOUT, "state failed carries UpdateError")
need("phase = .failed(title: \"下载失败\", message: error.text)" in ABOUT,
     "download failure reaches the user as text")
need("recordFailure(error)" in ABOUT, "download failures feed the shared backoff")
need("if !manual,\n           let until = defaults.object" in ABOUT,
     "manual checks bypass a stale server backoff")
need("retryAction = manifest == nil ? .check : .download" in ABOUT,
     "a known update can be retried without re-losing it")
need("if let download { adoptDownload(download); hasUpdate = true }" in ABOUT,
     "a failed recheck does not erase a known update")

# URL binding: tag and exact asset, not just any release path.
need("private static func isReleaseURL(_ url: URL, asset: String?) -> Bool" in ABOUT,
     "asset-bound URL validator exists")
need("components[5] == channelTag && components[6] == asset" in ABOUT,
     "validator binds tag and asset")
need("Self.isReleaseURL(url, asset: cached.ipa)" in ABOUT,
     "cached manifest URL is validated against its asset")
need("!name.contains(\"?\"), !name.contains(\"#\")" in ABOUT,
     "asset names cannot smuggle a query/fragment")

# Integrity and install handoff remain.
need("guard (attributes[.size] as? NSNumber)?.int64Value == record.manifest.size" in ABOUT,
     "downloaded size is checked")
need("var hasher = SHA256()" in ABOUT and "hasher.finalize()" in ABOUT,
     "sha256 is verified")
need("moveItem(at: location, to: destination)" in ABOUT, "download is moved atomically enough")
need("apple-magnifier://install?url=" in ABOUT, "install is handed to TrollStore")
need("canOpenURL" in ABOUT, "scheme is checked first")
need("applicationState == .active" in ABOUT, "foreground-only install handoff")

# Recovery/cleanup are explicit and can be retried.
need("后台下载未完成，请重新下载" in ABOUT, "missing background task is reported")
need("清除旧下载失败" in ABOUT, "cleanup failure is reported")
need("func discardDownload()" in ABOUT, "stale download can be discarded")

# No API quota dependency; manifest and IPA use the fixed release path.
need("https://api.github.com" not in ABOUT, "no api.github.com")
need("releases/download/" in ABOUT, "fixed download path")
need("gh release create \"$TAG\"" in WF, "CI publishes")
need("latest.json" in WF, "CI publishes the manifest")
need("Set :MinisBuildNumber ${{ github.run_number }}" in WF, "CI stamps a monotonic build")

if fails:
    print("❌ update failure guard failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ update failure guard passed (static only)")
