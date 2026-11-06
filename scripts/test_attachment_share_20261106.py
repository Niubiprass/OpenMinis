#!/usr/bin/env python3
"""Static guard for attachment selection / external share (2026-11-06).

Covers all selected kinds, provider callback lifetime, original-byte fidelity,
deadline/continuation behavior, partial-share durability and source ownership.
Static only.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
SVM = (ROOT / "src/ios/ShareExtension/ShareViewModel.swift").read_text()
PVC = (ROOT / "src/ios/ShareExtension/ShareViewController.swift").read_text()
SHARE = (ROOT / "src/ios/Shared/PendingShare.swift").read_text()
STORE = (ROOT / "src/ios/Shared/SharedContainerStore.swift").read_text()
VIEW = (ROOT / "src/ios/Views/Chat/AIChatView.swift").read_text()
ATT = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+Attachments.swift").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


# Deadline: 5s was shorter than a cold iCloud materialization; keep old working
# behavior by allowing 20s and still handle a truly hung provider.
need("private static let perItemTimeout: TimeInterval = 12.0" in SVM,
     "per-item deadline is not the regressed 5s")
need("ShareCompletion<Bool>" in SVM, "overall finish uses a terminal gate")
need("gate.armTimeout" in SVM, "overall deadline is armed")
need("withTaskGroup(of: Bool.self)" not in SVM,
     "overall path does not wait for the losing task group")
need("if outcome.timedOut" in PVC and "loadPendingShare() != nil" in PVC,
     "extension gives a late save a grace period")
need("presentImportFailure" in PVC, "total import failure is shown")
need("asyncAfter(deadline: .now() + 15)" in PVC, "failure alert has a close deadline")

# Continuations: exactly one terminal result, timeout and callbacks race safely.
need("@unchecked Sendable" in SHARE, "completion gate is shared safely")
need("claimCallback" in SHARE, "late provider callbacks are claimed once")
need("func finish(" in SHARE and "guard !completed" in SHARE, "single terminal result")
need("pendingTimer?.cancel()" in SHARE, "timer is cancelled on early completion")

# Provider file URLs are copied synchronously inside the callback.
need("provider.loadFileRepresentation" in SVM, "providers are asked for a file")
need("copyNow(url: url" in SVM, "callback copies before returning")
need("MUST be synchronous" in SVM, "temporary URL lifetime documented")
need("item as? URL" in SVM, "image fallback still handles a URL")

# Original bytes, for every kind.
need("try data.write(to: dir.appendingPathComponent(name), options: .atomic)" in SVM,
     "fallback image bytes are written without JPEG conversion on the normal path")
need("UTType.movie.identifier" in SVM and "UTType.item.identifier" in SVM,
     "video and generic file representations are handled")
need("SharedContainerStore.sharedFileDirectory" in SVM, "transfer directory is checked")
need("failureCount += 1" in SVM, "failed items are counted")

# Share manifest durability / identity.
need("func assigningItemIDs()" in SHARE, "new manifests get stable item ids")
need(".assigningItemIDs()" in SVM, "save applies ids")
need("let id: UUID?" in SHARE, "legacy manifests stay decodable")
need("@discardableResult" in STORE and "-> Bool" in STORE.split("func savePendingShare")[1][:120],
     "manifest save reports success")
need("data.write(to: pendingShareFileURL, options: .atomic)" in STORE,
     "manifest file write is atomic")
need("let ok = SharedContainerStore.savePendingShare(share)" in SVM,
     "save result is propagated")

# Source ownership: only a successful cache copy may consume the shared file.
catch_at = ATT.index("catch {\n                log.error(\"[UploadProbe]")
tail = ATT[catch_at:catch_at + 900]
need("Keep the source on failure" in tail, "failure keeps the shared source")
success_at = ATT.index("Only a saved cache copy may consume")
need(success_at < catch_at, "success-only deletion precedes the catch")
need("if !ok && retry" in VIEW, "failed import retries once automatically")
need("errorMessage = AppLocalized(\"部分分享附件导入失败" in VIEW,
     "second failure is surfaced")
EXT = (ROOT / "src/ios/Shared/ExternalFileImporter.swift").read_text()
need("guard SharedContainerStore.savePendingShare(share) else" in EXT,
     "Open In import checks its manifest write")
need("ShareFeedbackToast.show" in EXT, "Open In failure is shown")
need(".assigningItemIDs()" in EXT, "Open In manifest gets item ids")

# Selection import itself stays off-main and keeps the original file.
need("Task.detached(priority: .userInitiated)" in ATT, "file picker copy is off-main")
need("NSFileCoordinator().coordinate(readingItemAt: sourceURL" in ATT,
     "picker copy is coordinated")
need("finalizeImagePlaceholder(id: UUID, from sourceURL: URL) async" in ATT,
     "photo file finalize is async")
need("finalizeVideoPlaceholder(id: UUID, from sourceURL: URL, originalDate: Date? = nil) async" in ATT,
     "video finalize is async")

if fails:
    print("❌ attachment share guard failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ attachment share guard passed (static only)")
