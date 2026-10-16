#!/usr/bin/env python3
"""Standalone real UIKit/SwiftUI probe; NOT an app build or an iOS 15 claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name("ios15_geometry_probe")
EXPECTED = {"text_long_short_long", "composer_intrinsic", "host_same_identity", "host_reuse_identity", "empty_footer"}


def declaration(source, marker, indent=""):
    """Extract one indentation-delimited declaration, never a stale fixture copy.

    Deliberately fail on missing/ambiguous signatures. Swift compilation is the
    final parser; changing source indentation/signatures requires review here.
    """
    starts = list(re.finditer(r"^" + re.escape(indent + marker), source, re.M))
    if len(starts) != 1:
        raise RuntimeError(f"Expected exactly one declaration: {marker!r}, got {len(starts)}")
    start = starts[0].start()
    end = re.search(r"^" + re.escape(indent) + r"\}[ \t]*$", source[starts[0].end():], re.M)
    if end is None:
        raise RuntimeError(f"No closing declaration boundary: {marker}")
    return source[start:starts[0].end() + end.end()]


def prepare(folder, run_id):
    host_path = ROOT / "src/ios/iOS15Compat.swift"
    text_path = ROOT / "src/ios/Views/Chat/SelectableMarkdownView.swift"
    composer_path = ROOT / "src/ios/Views/Chat/ChatInputBar.swift"
    host = host_path.read_text(encoding="utf-8")
    text = text_path.read_text(encoding="utf-8")
    composer_source = composer_path.read_text(encoding="utf-8")
    composer_class = declaration(composer_source, "class PastableUITextView:")
    composer_intrinsic = declaration(composer_class, "override var intrinsicContentSize: CGSize", "    ")
    composer = ("final class ProbeComposer: UITextView {\n"
                "    var maxHeight: CGFloat = 100\n    var pinnedHeight: CGFloat?\n"
                "    var scrollWrites = 0\n"
                "    override var isScrollEnabled: Bool {\n"
                "        get { super.isScrollEnabled }\n"
                "        set { scrollWrites += 1; super.isScrollEnabled = newValue }\n    }\n" +
                composer_intrinsic + "\n}\n")
    host_markers = ["private final class _V63Probe", "protocol IOS15HostingHeightResettable",
                    "private struct _IOS15HostRenderContext:", "private struct _IOS15HostRenderSample:",
                    "private struct _IOS15HostRenderHeightKey:",
                    "private final class _HostingContentCellView<", "public struct UIHostingConfiguration<"]
    pieces = [declaration(host, m) for m in host_markers]
    # Only rename the compatibility type to avoid the native iOS 16 name. No
    # availability rewriting, fitting arithmetic edits, or forced success paths.
    legacy = re.sub(r"\bUIHostingConfiguration\b", "ProbeLegacyHostingConfiguration", "\n\n".join(pieces))
    view = declaration(text, "final class SelectableMarkdownTextView:")
    methods = [declaration(view, "override func sizeThatFits(_ size: CGSize) -> CGSize", "    "),
               declaration(view, "override var intrinsicContentSize: CGSize", "    ")]
    # Include production file-scope helpers referenced by these two entries,
    # transitively. This supports the independently extracted measurement helper
    # without importing Markdown/media/native dependencies or copying its logic.
    globals_by_name = {}
    for match in re.finditer(r"^(?:(?:private|fileprivate|public|internal|final)\s+)*(?:func|enum|struct|class)\s+(\w+)[^\n]*", text, re.M):
        name = match.group(1)
        if name != "SelectableMarkdownTextView" and "{" in match.group(0):
            globals_by_name[name] = match.group(0).split("{", 1)[0].rstrip()
    helper_names = set()
    pending = "\n".join(methods)
    while True:
        names = {n for n in globals_by_name if re.search(r"\b" + re.escape(n) + r"\b", pending)} - helper_names
        if not names:
            break
        helper_names.update(names)
        pending += "\n" + "\n".join(declaration(text, globals_by_name[n]) for n in sorted(names))
    helpers = "\n\n".join(declaration(text, globals_by_name[n]) for n in sorted(helper_names))
    swift = ("import UIKit\nimport SwiftUI\nimport QuartzCore\n" +
             (FIXTURES / "Dependencies.swift").read_text(encoding="utf-8") + "\n" + legacy + "\n" + helpers +
             "\nfinal class ProbeProductionTextView: UITextView {\n" + "\n".join(methods) + "\n}\n" + composer +
             (FIXTURES / "Probe.swift").read_text(encoding="utf-8").replace("__RUN_ID__", run_id))
    (folder / "Probe.swift").write_text(swift, encoding="utf-8")
    manifest = {"host": str(host_path.relative_to(ROOT)), "text": str(text_path.relative_to(ROOT)),
                "composer": str(composer_path.relative_to(ROOT)), "composer_entries": ["intrinsicContentSize"],
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (host_path, text_path, composer_path)},
                "extracted_host_declarations": host_markers, "text_entries": ["sizeThatFits", "intrinsicContentSize"],
                "production_text_helpers": sorted(helper_names),
                "generated_swift_sha256": hashlib.sha256(swift.encode()).hexdigest(),
                "transformations": ["rename compatibility UIHostingConfiguration to ProbeLegacyHostingConfiguration",
                                    "compile only two text sizing overrides in a minimal UITextView subclass"],
                "stubbed": ["SelfSizingCell cache interface", "MessageListLayout cache/streaming interface",
                            "MessageListItem identity"],
                "not_covered": ["full app", "iOS 15 unless actual runtime reports 15.x", "real device",
                                "production collection/cell cache integration", "Markdown attachments/KVO/frame fixes",
                                "NSTextContainerSetSizeGuard Objective-C swizzle"]}
    (folder / "extraction.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def command(args, timeout=90, check=True):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str, args))}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def select_device(wanted):
    listing = json.loads(command(["xcrun", "simctl", "list", "devices", "available", "--json"]))["devices"]
    runtimes = {r["identifier"]: r for r in json.loads(command(["xcrun", "simctl", "list", "runtimes", "--json"]))["runtimes"]}
    candidates = []
    for runtime_id, group in listing.items():
        runtime = runtimes.get(runtime_id, {})
        if not runtime.get("isAvailable", False) or ".iOS-" not in runtime_id:
            continue
        for device in group:
            if device.get("isAvailable", True) and "iPhone" in device["name"]:
                candidates.append((device, runtime))
    if wanted:
        candidates = [c for c in candidates if c[0]["udid"] == wanted]
    if not candidates:
        raise RuntimeError("No available iPhone iOS simulator/runtime (install one in Xcode); no skip allowed")
    def rank(pair):
        d, r = pair
        version = tuple(int(n) for n in re.findall(r"\d+", r.get("version", "0")))
        return (d["state"] == "Booted", version, d["name"], d["udid"])
    return sorted(candidates, key=rank, reverse=True)[0]


def validate(report, run_id):
    if report.get("schema") != 1 or report.get("run_id") != run_id or report.get("status") != "passed":
        raise RuntimeError("Runtime report absent, stale, malformed or failed")
    runtime = report.get("runtime", {})
    if runtime.get("is_simulator") is not True or not runtime.get("system_version"):
        raise RuntimeError("Runtime did not identify its actual simulator OS")
    cases = report.get("cases", [])
    if len(cases) != len(EXPECTED) or {c.get("name") for c in cases} != EXPECTED:
        raise RuntimeError("Runtime case manifest is incomplete")
    for case in cases:
        assertions = case.get("assertions", [])
        if case.get("passed") is not True or not assertions or any(a.get("passed") is not True for a in assertions):
            raise RuntimeError(f"Missing/failed assertions: {case.get('name')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("ios15-geometry-result.json"))
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--udid", help="available iPhone simulator UDID; never a physical device")
    parser.add_argument("--timeout", type=float, default=90, help="runtime result deadline in seconds")
    parser.add_argument("--prepare-only", action="store_true", help="extract on any OS; NOT a runtime pass")
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 600:
        parser.error("--timeout must be in (0, 600]")
    run_id = uuid.uuid4().hex
    folder = (args.artifacts_dir or Path(".geometry-probe") / run_id).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema": 1, "run_id": run_id, "status": "failed", "runtime": None,
              "cases": [], "artifacts_dir": str(folder), "deployment_target": "15.5"}
    device = None
    booted_here = False
    bundle = "com.openminis.geometryprobe.p" + run_id
    exit_code = 1
    try:
        result["extraction"] = prepare(folder, run_id)
        if args.prepare_only:
            result["status"] = "prepared_only_not_executed"
            exit_code = 0
        else:
            if platform.system() != "Darwin" or not shutil.which("xcrun"):
                raise RuntimeError("Requires macOS + Xcode + an available iPhone simulator; not executed")
            arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64"}.get(platform.machine())
            if not arch:
                raise RuntimeError("Unsupported macOS host architecture: " + platform.machine())
            result["architecture"] = arch
            result["xcode"] = command(["xcodebuild", "-version"])
            sdk = command(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"])
            app = folder / "GeometryProbe.app"
            app.mkdir(exist_ok=True)
            with (app / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": bundle, "CFBundleExecutable": "GeometryProbe",
                              "CFBundleName": "GeometryProbe", "CFBundlePackageType": "APPL",
                              "CFBundleVersion": "1", "CFBundleShortVersionString": "1.0",
                              "MinimumOSVersion": "15.5", "UIDeviceFamily": [1],
                              "CFBundleSupportedPlatforms": ["iPhoneSimulator"],
                              "LSRequiresIPhoneOS": True, "UILaunchScreen": {}}, stream)
            build = ["xcrun", "--sdk", "iphonesimulator", "swiftc", "-swift-version", "5", "-parse-as-library",
                     "-sdk", sdk, "-target", arch + "-apple-ios15.5-simulator", "-framework", "UIKit",
                     "-framework", "SwiftUI", "-framework", "QuartzCore", str(folder / "Probe.swift"),
                     "-o", str(app / "GeometryProbe")]
            command(build, timeout=180)
            command(["codesign", "--force", "--sign", "-", "--timestamp=none", str(app)])
            device, runtime = select_device(args.udid)
            result["selected_simulator"] = {"udid": device["udid"], "name": device["name"],
                                            "runtime_identifier": runtime["identifier"], "runtime_version": runtime["version"]}
            udid = device["udid"]
            if device["state"] != "Booted":
                command(["xcrun", "simctl", "boot", udid])
                booted_here = True
            command(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=180)
            command(["xcrun", "simctl", "install", udid, str(app)])
            container = Path(command(["xcrun", "simctl", "get_app_container", udid, bundle, "data"]))
            runtime_result = container / "Documents" / (run_id + ".json")
            command(["xcrun", "simctl", "launch", "--terminate-running-process",
                     "--stdout=" + str(folder / "stdout.log"), "--stderr=" + str(folder / "stderr.log"), udid, bundle])
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline and not runtime_result.exists():
                time.sleep(0.25)
            if not runtime_result.exists():
                raise TimeoutError("Simulator did not produce a report before deadline (crash/hang/launch failure)")
            report = json.loads(runtime_result.read_text(encoding="utf-8"))
            (folder / "runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            result["runtime"] = report.get("runtime")
            result["cases"] = report.get("cases", [])
            validate(report, run_id)
            actual = tuple(int(n) for n in result["runtime"]["system_version"].split("."))
            selected = tuple(int(n) for n in runtime["version"].split("."))
            if actual[:2] != selected[:2]:
                raise RuntimeError("Reported OS does not match selected simulator runtime")
            result["status"] = "passed"
            result["is_ios15_runtime"] = actual[0] == 15
            exit_code = 0
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if device is not None:
            cleanup = []
            for action in ("terminate", "uninstall"):
                try:
                    command(["xcrun", "simctl", action, device["udid"], bundle], timeout=20, check=False)
                except Exception as error:
                    cleanup.append(str(error))
            if booted_here:
                try:
                    command(["xcrun", "simctl", "shutdown", device["udid"]], timeout=30)
                except Exception as error:
                    cleanup.append(str(error))
            if cleanup:
                result["cleanup_errors"] = cleanup
                result["status"] = "failed"
                exit_code = 1
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        output.write_text(payload, encoding="utf-8")
        print(payload, end="")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
