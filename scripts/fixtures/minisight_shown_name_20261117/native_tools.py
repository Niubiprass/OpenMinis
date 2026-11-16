import shutil,subprocess,sys
from pathlib import Path
FIXTURE=Path(__file__).resolve().parent/"roundtrip_baseline"
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
