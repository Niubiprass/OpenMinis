#!/usr/bin/env python3
"""Static guard for the all-attachment send fix (2026-11-06).

The #222 crash stack was send -> MainActor closure -> UIImageJPEGRepresentation
-> ImageIO, but the same send body copied every file and read metadata on the
main actor. Photos, videos and documents therefore all froze, only with
different time budgets. These contracts keep the whole batch (copy, metadata,
decode, JPEG, XML assembly) on the AttachmentBatchProcessor worker and keep
drafts/queues recoverable.

Static source contracts only; no swiftc here, no device proof.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
VM = (ROOT / "src/ios/Agent/Chat/AIChatViewModel.swift").read_text()
MISC = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+Misc.swift").read_text()
ATT = (ROOT / "src/ios/Agent/Chat/AttachmentProcessing.swift").read_text()
EXT = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+Attachments.swift").read_text()
PBX = (ROOT / "src/ios/Minis.xcodeproj/project.pbxproj").read_text()
CLI = (ROOT / "src/ios/NativeOffloads/SessionsOffloadBridge.swift").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


def send_body():
    start = VM.index("func send(overrideText: String? = nil) {")
    end = VM.index("\n    func retry() {", start)
    return VM[start:end]


body = send_body()

# The batch, not the UI actor, does the expensive work.
need("AttachmentBatchProcessor.prepare(" in body, "send uses the worker batch")
need("await MainActor.run { Self.resizedImageData" not in body,
     "send no longer decodes/resizes inside MainActor.run")
need("try fm.copyItem(" not in body, "send no longer copies files on the main actor")
need("func addImageAttachment(_ image: UIImage, originalDate: Date? = nil) {\n        let dir = attachmentCacheDir\n        Task.detached" in (ROOT / "src/ios/Agent/Chat/AIChatViewModel+Attachments.swift").read_text(),
     "camera capture encodes off-main")
need("nonisolated static func downsampledCameraJPEG" in MISC,
     "camera downsample is nonisolated")
need("attributesOfItem" not in body, "send no longer reads file metadata on the main actor")

# All entry points share it.
need(ATT.count("static func prepare(") == 1, "one batch implementation")
need('phase: "queue-drain"' in VM, "queue drain uses the worker batch")
need('phase: "queue-inject"' in VM, "queue injection uses the worker batch")
need('phase: "retry"' in VM, "retry replacement uses the worker batch")
retry_start = VM.index("func retryFromMessage(")
retry_end = VM.index("func deleteFromMessage(", retry_start)
retry = VM[retry_start:retry_end]
need(retry.index("AttachmentBatchProcessor.prepare(") < retry.index("messages.removeSubrange"),
     "retry prepares replacements before truncating history")
need("abandonRetryPreparation" in retry, "retry preparation is cancellable")
need("retryPrepareToken = nil" in VM[VM.index("func cancel() {"):VM.index("private func resumeQueueAfterCancel")],
     "Stop abandons a retry that is still preparing")

# Incomplete attachments are kept, never silently dropped.
need("attachments.first(where: { $0.loadState != .ready })" in body,
     "send rejects non-ready attachments instead of pruning")
need("guard attachments.allSatisfy({ $0.loadState == .ready })" in
     (ROOT / "src/ios/Agent/Chat/AIChatViewModel+ProgrammaticPrompt.swift").read_text(),
     "programmatic submit rejects a not-ready batch")

# Failure restores both text and files, and keeps files added meanwhile.
need("self.inputText = text + \"\\n\" + self.inputText" in body,
     "failed send restores text without erasing new typing")
need("pendingAttachments.filter { !existingIDs.contains($0.id) }" in body,
     "failed send restores files without erasing new chips")
need("await AttachmentIO.remove(pendingAttachments.map(\\.cacheURL))" in body,
     "cache is cleaned only after the batch was persisted")
need(body.index("await AttachmentIO.remove(pendingAttachments.map(\\.cacheURL))")
     > body.index("self.agentHistory.append(userMessage)"),
     "cleanup happens after history append")

# Worker ownership, timeout, cancellation and cleanup.
need("@unchecked Sendable" in ATT, "work state is explicitly shared")
need("CheckedContinuation<Value, Error>" in ATT, "single continuation handoff")
need("DispatchQueue.global(qos: .userInitiated).async" in ATT, "blocking work uses a dispatch worker")
need("Task.detached" not in ATT, "worker is not a cooperative Task")
need("throw CancellationError()" in ATT, "cancel is observed between files")
need("NSFileCoordinator().coordinate" in ATT, "provider files are coordinated")
need("复制不完整" in ATT, "copies are size-verified")
need("if !committed { try? fm.removeItem(at: destination) }" in ATT,
     "partial destination is removed on failure")

# Images: ImageIO/CoreGraphics (not UIKit) + orientation/alpha/format.
need("CGImageSourceCreateThumbnailFromImageAlways" in ATT, "image path uses ImageIO thumbnails")
need("kCGImageSourceCreateThumbnailWithTransform" in ATT, "orientation is applied")
need("noneSkipLast" in ATT, "alpha is flattened for the inference copy")
need("CGImageDestinationAddImage" in ATT, "JPEG encoding is ImageIO")
need("imageDecodeFailed" in ATT, "decode failure is not a silent placeholder")
need("original: \\(linuxPath), use read_image" in ATT, "budget deferral keeps an explicit original pointer")

# Model-facing manifest is built on the worker and escaped.
need("AIChatViewModel.xmlEscaped(meta.path)" in ATT, "XML path is escaped")
need("user-attached-files" in ATT and "system-reminder" in ATT,
     "worker builds the same manifest/reminder as the old send body")
need("nonisolated static func xmlEscaped" in MISC, "escaping helper is nonisolated")

# Registration and programmatic handoff.
need(PBX.count("AttachmentProcessing.swift in Sources") == 2, "new source is in Sources exactly once")
need("preparedAttachments: [InputAttachment]? = nil" in
     (ROOT / "src/ios/Agent/Chat/AIChatViewModel+ProgrammaticPrompt.swift").read_text(),
     "programmatic channel can hand off an isolated batch")
need("preparedAttachments: staged" in
     (ROOT / "src/ios/Agent/Intents/SendPromptIntent.swift").read_text(),
     "Shortcut send hands off its staged batch")
need("preparedAttachments: staged" in
     (ROOT / "src/ios/Agent/Intents/FollowUpSessionIntent.swift").read_text(),
     "Shortcut follow-up does not consume the composer selection")
need("await stageAttachments(paths: attachmentPaths)" in CLI, "CLI stages off-main before dispatch")
need("func stageFile(" in ATT and "func stageData(" in ATT, "independent staging APIs exist")
need("return try await perform(timeout: 120" in ATT, "stageFile copy runs on the dispatch worker")

# Batch queue codec mirrors the old send body.
need("batch.parts.append(.text(\"[attached image: \\(linuxPath)]\"))" in ATT,
     "attached-image marker preserved")
need("batch.inlinedImages >= inlineLimit" in ATT, "count budget preserved")
need("messageBase64Limit - cumulativeBase64" in ATT, "message budget preserved")

# Programmatic swap is synchronous and restores the composer selection.
PROG = (ROOT / "src/ios/Agent/Chat/AIChatViewModel+ProgrammaticPrompt.swift").read_text()
need("let composerAttachments = attachments" in PROG, "programmatic keeps composer chips")
need("defer {\n            if preparedAttachments != nil { attachments = composerAttachments }" in PROG,
     "programmatic restores composer on every exit")
need("attachments.allSatisfy({ $0.loadState == .ready })" in PROG,
     "programmatic batch must be complete")
need("preparedAttachments: staged" in
     (ROOT / "src/ios/Agent/Intents/QuickTaskIntent.swift").read_text(),
     "quick task hands off an isolated batch")
need("Self.discardStaged(staged)" in
     (ROOT / "src/ios/Agent/Intents/SendPromptIntent.swift").read_text(),
     "rejected staged batches are cleaned up")

if fails:
    print("❌ attachment send guard failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ attachment send guard passed (static only)")
