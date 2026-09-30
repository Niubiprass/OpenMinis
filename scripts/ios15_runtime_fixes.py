#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenMinis iOS 15 运行时修复补丁（在移植脚本之后运行）。

移植脚本只做「编译期 API 兼容」。本脚本补齐「运行期」在 iOS 15 + TrollStore
下必需但上游原版没有的修复，全部幂等（重复执行不叠加）：

  1. SwiftUI Material -> 实心系统色（iOS 15 把 Material 渲染成实心黑块）
  2. ToolLiveSheet 工具结果 chunks 容器 VStack -> LazyVStack（否则大输出 OOM）
  3. App Group 强解包 -> 沙盒兜底（TrollStore 无 provisioning profile，
     containerURL 返回 nil，原版 `!` 直接闪退）
  4. .photosPicker / .fileImporter 被移植脚本剥离后，用 UIKit 选择器桥接，
     恢复「选择照片/视频」与「添加文件」两个入口
"""
from __future__ import annotations

import os
import re

ROOT = "src/ios"

PICKER_CODE = r'''
/// iOS 15 photo + document pickers (UIKit-based; bypasses SwiftUI's broken
/// multi-sheet chain on iOS 15 which silently drops presentations).
enum UIKitPickerPresenter {
    static func present(_ vc: UIViewController) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard var top = scenes.flatMap({ $0.windows }).first(where: { $0.isKeyWindow })?.rootViewController else {
                return
            }
            while let presented = top.presentedViewController, !presented.isBeingDismissed {
                top = presented
            }
            top.present(vc, animated: true)
        }
    }
}

final class AttachmentPickerCoordinator: NSObject, PHPickerViewControllerDelegate, UIDocumentPickerDelegate {
    var onPhotos: (([PHPickerResult]) -> Void)?
    var onFiles: (([URL]) -> Void)?

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        picker.dismiss(animated: true)
        onPhotos?(results)
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        onFiles?(urls)
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {}
}

struct PHPickerView: UIViewControllerRepresentable {
    let onPicked: ([PHPickerResult]) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .any(of: [.images, .videos])
        config.selectionLimit = 0
        config.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPicked: ([PHPickerResult]) -> Void
        init(onPicked: @escaping ([PHPickerResult]) -> Void) { self.onPicked = onPicked }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            onPicked(results)
        }
    }
}
'''

BRIDGE_METHODS = r'''
    // MARK: iOS 15 UIKit pickers (port strips .photosPicker)

    private func presentPhotoPicker() {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .any(of: [.images, .videos])
        config.selectionLimit = 0
        config.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: config)
        attachmentPickerCoordinator.onPhotos = { [self] results in
            handlePHPickerResults(results)
        }
        picker.delegate = attachmentPickerCoordinator
        UIKitPickerPresenter.present(picker)
    }

    private func presentDocumentPicker() {
        let types: [UTType] = [.image, .pdf, .plainText, .json, .sourceCode, .presentation, .spreadsheet, .data]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        picker.allowsMultipleSelection = true
        attachmentPickerCoordinator.onFiles = { [self] urls in
            for url in urls { vm.addFileAttachment(from: url) }
        }
        picker.delegate = attachmentPickerCoordinator
        UIKitPickerPresenter.present(picker)
    }

    private func handlePHPickerResults(_ results: [PHPickerResult]) {
        guard !results.isEmpty else { return }
        let kinds: [InputAttachment.Kind] = results.map { r in
            r.itemProvider.hasItemConformingToTypeIdentifier(UTType.movie.identifier) ? .video : .image
        }
        let placeholderIDs = vm.addLoadingPlaceholders(kinds: kinds)
        let jobs = zip(placeholderIDs, results).map { (id: $0, result: $1,
            isVideo: $1.itemProvider.hasItemConformingToTypeIdentifier(UTType.movie.identifier)) }

        Task {
            await withTaskGroup(of: Void.self) { group in
                for job in jobs {
                    group.addTask {
                        let provider = job.result.itemProvider
                        if job.isVideo {
                            await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
                                provider.loadFileRepresentation(forTypeIdentifier: UTType.movie.identifier) { url, _ in
                                    defer { cont.resume() }
                                    guard let exported = url,
                                          let tmpDir = try? FileManager.default.url(for: .itemReplacementDirectory, in: .userDomainMask, appropriateFor: exported, create: true),
                                          let tmp = try? tmpDir.appendingPathComponent("picked-\(UUID().uuidString).\(exported.pathExtension)"),
                                          (try? FileManager.default.copyItem(at: exported, to: tmp)) != nil
                                    else {
                                        Task { @MainActor in vm.markPlaceholderFailed(id: job.id) }
                                        return
                                    }
                                    Task { @MainActor in vm.finalizeVideoPlaceholder(id: job.id, from: tmp) }
                                }
                            }
                        } else {
                            await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
                                provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                                    if let data = data {
                                        Task { @MainActor in vm.finalizeImagePlaceholder(id: job.id, data: data, fileExtension: nil) }
                                        cont.resume()
                                        return
                                    }
                                    provider.loadObject(ofClass: UIImage.self) { obj, _ in
                                        defer { cont.resume() }
                                        if let img = obj as? UIImage, let png = img.pngData() ?? img.jpegData(compressionQuality: 0.9) {
                                            Task { @MainActor in vm.finalizeImagePlaceholder(id: job.id, data: png, fileExtension: nil) }
                                        } else {
                                            Task { @MainActor in vm.markPlaceholderFailed(id: job.id) }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
'''


def walk_swift():
    for dp, dn, fn in os.walk(ROOT):
        for f in fn:
            if f.endswith(".swift"):
                yield os.path.join(dp, f)


def read(p):
    return open(p, encoding="utf-8").read()


def write(p, s):
    open(p, "w", encoding="utf-8").write(s)


def fix_materials():
    repl = [
        (".ultraThinMaterial", "Color(UIColor.tertiarySystemFill)"),
        (".ultraThickMaterial", "Color(UIColor.secondarySystemBackground)"),
        (".thinMaterial", "Color(UIColor.tertiarySystemFill)"),
        (".thickMaterial", "Color(UIColor.secondarySystemBackground)"),
        (".regularMaterial", "Color(UIColor.secondarySystemBackground)"),
        (".barMaterial", "Color(UIColor.secondarySystemBackground)"),
    ]
    total = 0
    for p in walk_swift():
        lines = read(p).splitlines()
        hit = 0
        for i, ln in enumerate(lines):
            s = ln.lstrip()
            if s.startswith("//") or s.startswith("///"):
                continue
            for k, v in repl:
                if k in ln:
                    ln = ln.replace(k, v)
                    hit += 1
            lines[i] = ln
        if hit:
            out = "\n".join(lines) + "\n"
            if "UIColor(" in out and "import UIKit" not in out:
                if "import SwiftUI" in out:
                    out = out.replace("import SwiftUI", "import SwiftUI\nimport UIKit", 1)
                else:
                    out = "import UIKit\n" + out
            write(p, out)
            total += hit
    print(f"  [runtime-fix] Material 替换 {total} 处")


def _compute_brace_safe(s):
    """Return a bytearray where index i == 1 if the char at i is a real
    brace (i.e. not inside a string literal or // /* */ comment)."""
    n = len(s)
    safe = bytearray(n)
    in_str = False
    in_block = False
    i = 0
    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
                i += 1
                continue
            i += 1
            continue
        if ch == "/" and nxt == "/":
            nl = s.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch in "{}":
            safe[i] = 1
        i += 1
    return safe


def _match_brace_spans(open_positions, s, safe):
    """Given absolute positions of each target container's '{', return a list
    of (open_pos, close_pos) using brace matching over real braces only."""
    events = []
    for i, ch in enumerate(s):
        if safe[i] and ch in "{}":
            events.append((i, 1 if ch == "{" else -1))
    spans = []
    for op in open_positions:
        depth = 0
        cp = None
        for (bpos, d) in events:
            if bpos < op:
                continue
            depth += d
            if depth == 0 and bpos > op:
                cp = bpos
                break
        spans.append((op, cp))
    return spans


def fix_tool_lazy():
    """Make tool-output chunk containers lazy, but NEVER nest a LazyVStack
    inside another LazyVStack — that triggers an iOS 15 height-measurement bug
    where the inner content silently disappears.

    Strategy (idempotent + self-correcting):
      * Treat both `VStack(...)` and `LazyVStack(...)` with the exact signature
        as the same "target container".
      * Brace-match to find which are nested inside another target container.
      * Inner containers -> VStack (never lazy).
      * Top-level containers -> LazyVStack.
    Re-running on an already-patched file converges to the same correct state.
    """
    p = os.path.join(ROOT, "Views/Chat/ToolLiveSheet.swift")
    if not os.path.exists(p):
        return
    s = read(p)
    pat = re.compile(r"(LazyVStack|VStack)\(alignment: \.leading, spacing: 0\) \{")
    matches = list(pat.finditer(s))
    if not matches:
        print("  [runtime-fix] ToolLiveSheet 无目标 VStack")
        return
    opens = [m.end() - 1 for m in matches]  # position of the '{'
    safe = _compute_brace_safe(s)
    spans = _match_brace_spans(opens, s, safe)
    nested = [False] * len(matches)
    for i in range(len(matches)):
        for j in range(len(matches)):
            if i == j:
                continue
            if spans[j][0] < spans[i][0] < spans[j][1]:
                nested[i] = True
                break
    out = s
    changed = 0
    for i in reversed(range(len(matches))):
        m = matches[i]
        full = m.group(0)
        want = "LazyVStack" if not nested[i] else "VStack"
        cur = "LazyVStack" if full.startswith("LazyVStack") else "VStack"
        if cur != want:
            out = out[:m.start()] + want + full[len(cur):] + out[m.end():]
            changed += 1
    if changed:
        write(p, out)
    top = sum(1 for x in nested if not x)
    inner = sum(1 for x in nested if x)
    print(f"  [runtime-fix] ToolLiveSheet: {top} 顶层→LazyVStack, {inner} 内层→VStack (改动 {changed})")


def fix_appgroup():
    p = os.path.join(ROOT, "Shared/SharedContainerStore.swift")
    if os.path.exists(p):
        s = read(p)
        if "containerDirectory" not in s:
            anchor = "    static var sharedDefaults: UserDefaults? {"
            add = (
                "    /// Best-effort container directory. TrollStore unsigned installs have no\n"
                "    /// provisioning profile, so App Groups are unavailable and\n"
                "    /// `containerURL(forSecurityApplicationGroupIdentifier:)` returns nil.\n"
                "    /// Fall back to the app's own Application Support directory.\n"
                "    static var containerDirectory: URL {\n"
                "        let fm = FileManager.default\n"
                "        if let url = fm.containerURL(forSecurityApplicationGroupIdentifier: appGroupID) {\n"
                "            return url\n"
                "        }\n"
                "        let fallback = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]\n"
                "            .appendingPathComponent(\"MinisAppGroupFallback\", isDirectory: true)\n"
                "        try? fm.createDirectory(at: fallback, withIntermediateDirectories: true)\n"
                "        return fallback\n"
                "    }\n\n"
            )
            if anchor in s:
                s = s.replace(anchor, add + anchor, 1)
                write(p, s)
                print("  [runtime-fix] SharedContainerStore + containerDirectory")
            else:
                print("  [runtime-fix][WARN] SharedContainerStore 锚点未命中")
        else:
            print("  [runtime-fix] SharedContainerStore 已有 containerDirectory")

    p = os.path.join(ROOT, "Agent/Chat/AIChatViewModel+RequestBudget.swift")
    if os.path.exists(p):
        s = read(p)
        a = (
            "    nonisolated static var minisAppGroupRoot: URL {\n"
            "        FileManager.default.containerURL(\n"
            "            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID\n"
            "        )!.appendingPathComponent(\"MinisFileProvider\", isDirectory: true)\n"
            "    }"
        )
        b = (
            "    nonisolated static var minisAppGroupRoot: URL {\n"
            "        SharedContainerStore.containerDirectory\n"
            "            .appendingPathComponent(\"MinisFileProvider\", isDirectory: true)\n"
            "    }"
        )
        if a in s:
            s = s.replace(a, b)
            write(p, s)
            print("  [runtime-fix] minisAppGroupRoot 兜底")
        a2 = (
            "    nonisolated static var minisConfigRoot: URL {\n"
            "        let url = FileManager.default.containerURL(\n"
            "            forSecurityApplicationGroupIdentifier: SharedContainerStore.appGroupID\n"
            "        )!.appendingPathComponent(\"MinisConfig\", isDirectory: true)\n"
            "        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)\n"
            "        return url\n"
            "    }"
        )
        b2 = (
            "    nonisolated static var minisConfigRoot: URL {\n"
            "        let url = SharedContainerStore.containerDirectory\n"
            "            .appendingPathComponent(\"MinisConfig\", isDirectory: true)\n"
            "        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)\n"
            "        return url\n"
            "    }"
        )
        if a2 in s:
            s = s.replace(a2, b2)
            write(p, s)
            print("  [runtime-fix] minisConfigRoot 兜底")

    p = os.path.join(ROOT, "MinisApp.swift")
    if os.path.exists(p):
        s = read(p)
        a = 'fm.containerURL(forSecurityApplicationGroupIdentifier: "group.com.openminis.app")!'
        if a in s:
            s = s.replace(a, "SharedContainerStore.containerDirectory")
            write(p, s)
            print("  [runtime-fix] MinisApp migrate 兜底")
        else:
            print("  [runtime-fix][WARN] MinisApp migrate 锚点未命中")


def fix_picker():
    p = os.path.join(ROOT, "iOS15Compat.swift")
    if os.path.exists(p):
        s = read(p)
        if "enum UIKitPickerPresenter" not in s:
            if "import PhotosUI" not in s:
                if "import UIKit" in s:
                    s = s.replace("import UIKit", "import UIKit\nimport PhotosUI", 1)
                else:
                    s = "import UIKit\nimport PhotosUI\n" + s
            s = s.rstrip() + "\n\n" + PICKER_CODE + "\n"
            write(p, s)
            print("  [runtime-fix] iOS15Compat + picker 类型")
        else:
            print("  [runtime-fix] iOS15Compat 已有 picker 类型")

    p = os.path.join(ROOT, "Views/Chat/AIChatView.swift")
    if os.path.exists(p):
        s = read(p)
        n1 = s.count("Button { showPhotoPicker = true }")
        n2 = s.count("Button { showDocumentPicker = true }")
        s = s.replace("Button { showPhotoPicker = true }", "Button { presentPhotoPicker() }")
        s = s.replace("Button { showDocumentPicker = true }", "Button { presentDocumentPicker() }")
        if "attachmentPickerCoordinator" not in s:
            anchor = "@State private var showPhotoPicker = false"
            if anchor in s:
                s = s.replace(anchor,
                              anchor + "\n    @State private var attachmentPickerCoordinator = AttachmentPickerCoordinator()",
                              1)
            mbody = "var body: some View {"
            idx = s.rfind(mbody)
            if idx != -1:
                s = s[:idx] + BRIDGE_METHODS + "\n    " + s[idx:]
        write(p, s)
        print(f"  [runtime-fix] AIChatView 桥接 (photo 按钮 {n1} / doc 按钮 {n2})")


def main():
    print("=== iOS 15 运行时修复补丁 ===")
    if not os.path.isdir(ROOT):
        print("  [WARN] 未找到 src/ios，跳过")
        return
    fix_materials()
    fix_tool_lazy()
    fix_appgroup()
    fix_picker()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()
