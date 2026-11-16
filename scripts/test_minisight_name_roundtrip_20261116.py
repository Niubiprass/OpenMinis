#!/usr/bin/env python3
"""Source-only guards + actual ObjC AppleFoundation -> file -> Swift Remote/Policy.
No Python/Swift copy of the production writer. No install/poll/permissions/audio.
Linux or missing Apple toolchain: native SKIP (never a behavior PASS). Fail closed
with --require-native or V64R_REQUIRE_SWIFT=1. Only local temporary synthetic data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/ios/MiniSightCore"
REMOTE = ROOT / "src/ios/MiniSightWakeRemote.swift"
POLICY = ROOT / "src/ios/MiniSightWakePolicy.swift"
CONTROLLER = ROOT / "src/ios/MiniSightWakeController.swift"
FIXTURE = ROOT / "scripts/fixtures/minisight_name_roundtrip_20261116"
DEFAULT_PLUGIN = ROOT.parent.parent / "MiniSight-complete-20261105"


def sourceguard(plugin):
    proof = json.loads((FIXTURE / 'PRODUCTION-WRITER.json').read_text())
    captured = (FIXTURE / 'production_bridge_state.inc').read_text()
    marker = '- (void)publishContainer:'
    captured_method = captured[captured.index(marker):].rstrip()
    if hashlib.sha256(captured_method.encode()).hexdigest() != proof['excerpt_sha256']:
        raise RuntimeError('production writer excerpt integrity mismatch')
    if plugin is None:
        plugin = DEFAULT_PLUGIN if (DEFAULT_PLUGIN / 'debs/MiniSight/MiniSightNameWakeState.h').is_file() else None
    if plugin is not None:
        header = plugin / "debs/MiniSight/MiniSightNameWakeState.h"
        production_bridge = (plugin / "debs/MiniSight/MiniSightNameWakeBridge.m").read_text(encoding='utf-8')
        actual_method = production_bridge[production_bridge.index(marker):production_bridge.index('\n- (void)readRequestInContainer:', production_bridge.index(marker))].rstrip()
        if actual_method != captured_method:
            raise RuntimeError('production state writer changed without updating literal fixture evidence')
    else:
        # Independent App CI uses the same pinned builder; it does not pretend
        # an unavailable companion tree was dynamically executed or compared.
        header = CORE / 'MiniSightNameWakeState.h'
        production_bridge = captured
        print('SKIP live companion mirror in independent App CI; literal production writer evidence retained', flush=True)
    data = header.read_bytes()
    if hashlib.sha256(data).hexdigest() != proof['header_sha256']:
        raise RuntimeError('production builder integrity mismatch')
    builder = data.decode("utf-8")
    remote = REMOTE.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    controller = CONTROLLER.read_text(encoding="utf-8")
    writer = (FIXTURE / "writer.m").read_text(encoding="utf-8")
    main = (FIXTURE / "main.swift").read_text(encoding="utf-8")
    support = (FIXTURE / "support.swift").read_text(encoding="utf-8")
    checks = {
        "production builder byte correspondence": data == (CORE / header.name).read_bytes(),
        "real builder signature": "MSNameWakeStateMessage(NSString *host, NSString *revision," in builder,
        "production bridge header import": '#import "MiniSightNameWakeState.h"' in production_bridge,
        "production bridge builder call": "MSNameWakeStateMessage(self.host, revision, unlocked, allowed, busy," in production_bridge,
        "writer actual header import": '#import "MiniSightNameWakeState.h"' in writer,
        "writer not a copied builder": writer.count("MSNameWakeStateMessage(") == 7 and "static inline NSDictionary" not in writer,
        "eight flags": "mask < 8" in writer and "expectedAllowed[8]" in writer,
        "real Foundation serialization": "[NSJSONSerialization dataWithJSONObject:message" in writer,
        "writer file boundary": "writeToFile:" in writer,
        "wire boolean types": "CFBooleanGetTypeID()" in writer and "reader wire CFBoolean" in main,
        "static real reader": "MiniSightWakeRemote.decodeState" in main and "MiniSightWakeRemote.decodeReply" in main,
        "real policy": all(s in main for s in ("MiniSightWakePolicy.decision", "c.updateCompanion", "MiniSightWakePolicy.remoteReplyCurrent", "MiniSightWakePolicy.validHit", "MiniSightWakePolicy.permitsContinuation")),
        "reader strict CFBoolean": "if type == CFBooleanGetTypeID() { return number.boolValue }" in remote,
        "reader strict legacy CFNumber": "guard type == CFNumberGetTypeID() else { return nil }" in remote,
        "reader rejects float": "guard !CFNumberIsFloatType(legacy) else { return nil }" in remote,
        "reader exact integers": all(s in remote for s in ("number.compare(NSNumber(value: 0))", "number.compare(NSNumber(value: 1))")),
        "policy unknown not locked": "companionLocked = fresh && unlocked == false" in policy,
        "policy ready proof": "companionReady = fresh && allowed == true" in policy,
        "controller local lock/protected data": "let unlocked = !appLocked && !protectedDataUnavailable && UIApplication.shared.isProtectedDataAvailable" in controller,
        "controller trusted companion update": "c.updateCompanion(fresh: fresh, unlocked: companion?.unlocked, allowed: companion?.allowed, busy: companion?.busy)" in controller,
        "bounded existing-input handoff": "MiniSightWakePolicy.mayHoldCompanionTransition(c," in controller and "pulse.setDetectionToken(nil); detector.stop(); phase = .holding" in controller and "deadline - c.now <= 3" in policy,
        "controller reply policy fencing": "MiniSightWakePolicy.remoteReplyCurrent" in controller and "active == cycle.token" in controller,
        "observer stub cannot poll": "fatalError(\"fixture must not poll remote state\")" in support,
        "fixture does not activate remote": all(s not in main for s in (".install(", ".poll(", ".post(", "MiniSightWakeRemote()", "MiniSightWakeController.shared")),
        "fixture no permission/audio/preferences/network": all(s not in writer + main + support for s in ("AVAudio", "SFSpeech", "requestPermission", "UserDefaults", "URLSession", "https://", "NSLog(")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("source-only conformance failed: " + ", ".join(failed))
    print(f"PASS source-only conformance: {len(checks)} guards; native behavior NOT executed by source checks", flush=True)
    print("SOURCE header SHA-256: " + hashlib.sha256(data).hexdigest(), flush=True)
    return header.parent


def command(args, timeout=120):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {Path(str(args[0])).name}")
    return result


def apple_toolchain(tmp):
    if sys.platform != "darwin":
        return None, "requires macOS AppleFoundation + Apple Swift; current platform=" + sys.platform
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return None, "xcrun/macOS SDK unavailable"
    values = []
    for flags in (("--show-sdk-path",), ("--find", "clang"), ("--find", "swiftc")):
        result = subprocess.run([xcrun, "--sdk", "macosx", *flags], capture_output=True, text=True, timeout=30)
        if result.returncode or not result.stdout.strip():
            return None, "macOS SDK / Apple clang / Swift unavailable"
        values.append(result.stdout.strip())
    sdk, clang, swift = values
    if not Path(sdk).is_dir() or not Path(clang).is_file() or not Path(swift).is_file():
        return None, "Apple compiler or explicit macOS SDK path missing"
    version = subprocess.run([swift, "--version"], capture_output=True, text=True, timeout=30)
    if version.returncode or "Apple Swift version" not in version.stdout + version.stderr:
        return None, "not a verified Apple Swift toolchain"
    objc_probe = tmp / "foundation-probe.m"
    swift_probe = tmp / "foundation-probe.swift"
    objc_probe.write_text('#import <Foundation/Foundation.h>\nint main(void) { @autoreleasepool { return [NSJSONSerialization isValidJSONObject:@{}] ? 0 : 1; } }\n')
    swift_probe.write_text('import CoreFoundation\nimport Foundation\nlet data = try JSONSerialization.data(withJSONObject: [:] as [String: Any])\nprint(data.count)\n')
    probes = ([clang, "-isysroot", sdk, "-fobjc-arc", objc_probe, "-framework", "Foundation", "-o", tmp / "objc-probe"],
              [swift, "-sdk", sdk, swift_probe, "-o", tmp / "swift-probe"])
    for args in probes:
        result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=120)
        if result.returncode:
            return None, "AppleFoundation/CoreFoundation availability probe could not compile/link (native behavior not run)"
    print("TOOLCHAIN: " + (version.stdout + version.stderr).strip(), flush=True)
    print("SDK (explicit macosx for both compilers): " + sdk, flush=True)
    return (sdk, clang, swift), ""


def native_roundtrip(tmp, header_dir, toolchain):
    sdk, clang, swift = toolchain
    writer_binary, reader_binary = tmp / "writer", tmp / "reader"
    wire = tmp / "wire"

    def compile_writer(include, binary):
        command([clang, "-isysroot", sdk, "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                 "-I", include, FIXTURE / "writer.m", "-framework", "Foundation",
                 "-framework", "CoreFoundation", "-o", binary])

    def compile_reader(remote, policy, binary):
        # Entire real Remote (no extraction); support supplies only its dormant
        # observer callback's controller symbol. No production App .m is needed.
        command([swift, "-sdk", sdk, "-swift-version", "5", "-warnings-as-errors",
                 remote, policy, FIXTURE / "support.swift", FIXTURE / "main.swift", "-o", binary])

    compile_writer(header_dir, writer_binary)
    compile_reader(REMOTE, POLICY, reader_binary)
    writer_result = command([writer_binary, wire], timeout=30)
    reader_result = command([reader_binary, wire], timeout=30)
    if "PASS native ObjC writer:" not in writer_result.stdout or "PASS native Swift reader/policy:" not in reader_result.stdout:
        raise RuntimeError("native baseline did not report its behavioral assertions")
    print("PASS native baseline: real production header -> NSJSONSerialization -> files -> full production Swift Remote/Policy", flush=True)

    # Mutants are TEMPORARY COPIES of actual production code. Baseline compiled
    # and executed above. Each mutant MUST compile successfully before an actual
    # assertion rejects it; build errors, crashes, or source guards do not count.
    def mutate(path, destination, old, new):
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise RuntimeError("negative mutation anchor not unique: " + path.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text.replace(old, new), encoding="utf-8")
        return destination

    def rejected(binary, directory, expected, label):
        result = subprocess.run([str(binary), str(directory)], capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if result.returncode != 1 or expected not in output:
            raise RuntimeError("negative did not fail at expected behavioral assertion: " + label + "\n" + output)
        print("PASS native negative behavioral rejection: " + label + " -> " + expected, flush=True)

    mutated_header_dir = tmp / "mutant-writer"
    mutate(header_dir / "MiniSightNameWakeState.h", mutated_header_dir / "MiniSightNameWakeState.h",
           '@"allowed": @((BOOL)(allowed && unlocked && revision.length > 0 && revision.length <= 128))',
           '@"allowed": @((int)(allowed && unlocked && revision.length > 0 && revision.length <= 128))')
    compile_writer(mutated_header_dir, tmp / "writer-mutant")
    rejected(tmp / "writer-mutant", tmp / "mutant-wire", "FAIL assertion: writer CFBoolean allowed", "actual writer BOOL cast removed")

    loose_remote = mutate(REMOTE, tmp / "mutant-reader/MiniSightWakeRemote.swift",
        "guard let number = value as? NSNumber else { return nil }",
        "if let text = value as? String { return !text.isEmpty }\n        guard let number = value as? NSNumber else { return nil }")
    compile_reader(loose_remote, POLICY, tmp / "reader-mutant")
    rejected(tmp / "reader-mutant", wire, "FAIL assertion: invalid boolean unlocked", "actual reader accepts string truthiness")

    locked_policy = mutate(POLICY, tmp / "mutant-policy/MiniSightWakePolicy.swift",
        "companionLocked = fresh && unlocked == false", "companionLocked = !fresh || unlocked == false")
    compile_reader(REMOTE, locked_policy, tmp / "policy-mutant")
    rejected(tmp / "policy-mutant", wire, "FAIL assertion: revision mismatch policy unknown not locked", "actual policy invents lock for unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path,
                        default=Path(os.environ['MINISIGHT_NAME_PLUGIN_ROOT']) if 'MINISIGHT_NAME_PLUGIN_ROOT' in os.environ else None,
                        help="optional local companion for live parity; independent App CI uses pinned production evidence")
    parser.add_argument("--require-native", action="store_true", help="fail closed if Apple native behavior cannot run")
    args = parser.parse_args()
    required = args.require_native or os.getenv("V64R_REQUIRE_SWIFT") == "1"
    try:
        header_dir = sourceguard(args.plugin_root.resolve() if args.plugin_root is not None else None)
        with tempfile.TemporaryDirectory(prefix="minisight-name-roundtrip-") as directory:
            tmp = Path(directory)
            toolchain, reason = apple_toolchain(tmp)
            if not toolchain:
                print(("FAIL" if required else "SKIP") + " native ObjC -> Swift behavior: " + reason, flush=True)
                print("SKIP native behavioral negative controls: baseline native compile/execution unavailable", flush=True)
                return 2 if required else 0
            native_roundtrip(tmp, header_dir, toolchain)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("FAIL: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
