#!/usr/bin/env python3
"""Static checks locally; REAL production Objective-C tests only on an approved CI Mac.

Local: python3 scripts/test_minisight_action_library_20261116.py
CI:    CI=1 python3 scripts/test_minisight_action_library_20261116.py --ci \
          --ios-sdk /path/to/iPhoneOS15.5.sdk

No network, deployment, simulator/device launch or CI dispatch. --ci is only an
entrypoint for an already-authorized runner. iSH explicitly SKIPS Objective-C;
Python source assertions/fixture construction are NOT native parser execution.
Fixtures contain synthetic solid pixels, no character assets or adapted artwork.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures/minisight_action_library_20261116"
CORPUS = json.loads((FIXTURES / "cases.json").read_text())
ROLES = ["idle", "idleAlt", "tap", "drag", "shakeSoft", "shakeHard", "flight",
         "land", "walkLeft", "walkRight", "jump", "sleep", "wake", "music"]


def source_dir(root):
    for relative in ("src/ios/MiniSightCore", "debs/MiniSight"):
        directory = root / relative
        if (directory / "MiniSightActionLibrary.m").is_file():
            return directory
    raise SystemExit("Action-library sources not found in --root")


def patch(manifest, pointer, value=None, delete=False):
    parts = pointer.strip("/").split("/")
    cursor = manifest
    for part in parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    key = int(parts[-1]) if isinstance(cursor, list) else parts[-1]
    if delete:
        del cursor[key]
    else:
        cursor[key] = copy.deepcopy(value)


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def png(width=8, height=8, alpha=False, padding=0):
    compressor = zlib.compressobj()
    compressed = []
    for y in range(height):
        color = bytes((255, 0, 0, 255)) if y < height / 2 else bytes((0, 0, 255, 255))
        row = color * width
        if alpha and y < max(1, height // 4):
            row = bytes(4 * max(1, width // 4)) + row[4 * max(1, width // 4):]
        compressed.append(compressor.compress(b"\0" + row))
    compressed.append(compressor.flush())
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    # Valid unknown ancillary chunk, used only for a total-input-size negative.
    filler = chunk(b"msAL", bytes(padding)) if padding else b""
    return b"\x89PNG\r\n\x1a\n" + header + filler + chunk(b"IDAT", b"".join(compressed)) + chunk(b"IEND", b"")


def gif(count):
    # Full 2x2 frames; resetting the LZW dictionary per pixel keeps 3-bit codes.
    output = bytearray(b"GIF89a" + struct.pack("<HHBBB", 2, 2, 0x80, 0, 0) + b"\xff\0\0\0\0\xff")
    for frame in range(count):
        codes = [4, frame % 2] * 4 + [5]
        packed = sum(code << (3 * i) for i, code in enumerate(codes))
        payload = packed.to_bytes((len(codes) * 3 + 7) // 8, "little")
        output += b"\x21\xf9\x04\x08\x0a\x00\x00\x00"
        output += b"\x2c" + struct.pack("<HHHHB", 0, 0, 2, 2, 0)
        output += bytes((2, len(payload))) + payload + b"\0"
    return bytes(output + b"\x3b")


def apng():
    output = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0))
    output += chunk(b"acTL", struct.pack(">II", 2, 0))
    for i, color in enumerate((b"\xff\0\0\xff", b"\0\0\xff\xff")):
        control = struct.pack(">IIIIIHHBB", 0 if i == 0 else 1, 8, 8, 0, 0, 1, 10, 0, 0)
        output += chunk(b"fcTL", control)
        data = zlib.compress((b"\0" + color * 8) * 8)
        output += chunk(b"IDAT", data) if i == 0 else chunk(b"fdAT", struct.pack(">I", 2) + data)
    return output + chunk(b"IEND", b"")


def make_manifest(spec):
    manifest = copy.deepcopy(CORPUS["manifest"])
    for pointer, value in spec.get("set", {}).items():
        patch(manifest, pointer, value)
    for pointer in spec.get("delete", []):
        patch(manifest, pointer, delete=True)
    recipe = spec.get("make")
    first = manifest["clips"][0] if manifest.get("clips") and isinstance(manifest["clips"][0], dict) else None
    frame = copy.deepcopy(CORPUS["manifest"]["clips"][0]["frames"][0])
    if recipe in ("music", "all-roles"):
        for role in (["music"] if recipe == "music" else ROLES[1:]):
            clip = copy.deepcopy(first); clip.update(id=role, role=role); manifest["clips"].append(clip)
    elif recipe in ("64-clips", "65-clips", "6000-frames", "6001-frames"):
        count = 10 if "frames" in recipe else int(recipe.split("-")[0])
        manifest["clips"] = []
        for i in range(count):
            clip = copy.deepcopy(first); clip["id"] = "clip" + str(i)
            if "frames" in recipe:
                clip["frames"] = [dict(frame, duration=.02) for _ in range(600)]
            manifest["clips"].append(clip)
        if recipe == "6001-frames":
            extra = copy.deepcopy(first); extra["id"] = "extra"; manifest["clips"].append(extra)
    elif recipe == "duplicate-clips":
        manifest["clips"].append(copy.deepcopy(first))
    elif recipe == "long-id":
        first["id"] = "a" * 65
    elif recipe == "601-frames":
        first["frames"] = [dict(frame, duration=.02) for _ in range(601)]
    elif recipe in ("120-seconds", "over-120"):
        first["frames"] = [dict(frame, duration=10) for _ in range(12)]
        if recipe == "over-120":
            first["frames"].append(frame)
    elif recipe == "crop":
        first["frames"] = [dict(frame, rect=[0, y, 1, .5]) for y in (0, .5)]
    elif recipe in ("crop-aspect", "aspect-mismatch", "fractional-crop"):
        second = dict(frame, file="wide.png")
        if recipe == "crop-aspect":
            second["rect"] = [0, 0, .5, 1]
        elif recipe == "fractional-crop":
            first["frames"][0]["rect"] = [.0625, 0, .35, .4]
            second["rect"] = [.03125, 0, .175, .4]
        first["frames"].append(second)
    elif recipe in ("gif", "apng"):
        first["frames"] = [dict(frame, file="animation." + recipe, index=i) for i in range(2)]
    elif recipe in ("total-bytes", "source-frames"):
        count = 6 if recipe == "total-bytes" else 11
        first["frames"] = [dict(frame, file="source%d.png" % i) for i in range(count)]
    elif recipe is not None:
        raise AssertionError("Unhandled fixture recipe: " + recipe)
    return manifest


def build_fixture(base, spec):
    directory = base / spec["name"] / CORPUS["manifest"]["id"]
    directory.mkdir(parents=True)
    (directory / "nested").mkdir()
    image = png(alpha=bool(spec.get("alpha")))
    (directory / "pixels.png").write_bytes(image)
    (directory / "wide.png").write_bytes(png(16, 8))
    (directory / "nested/pixels.png").write_bytes(image)
    manifest = make_manifest(spec)
    recipe = spec.get("make")
    if recipe in ("gif", "apng"):
        (directory / ("animation." + recipe)).write_bytes(gif(2) if recipe == "gif" else apng())
    if recipe in ("total-bytes", "source-frames"):
        data = png(padding=23 * 1024 * 1024 - 200) if recipe == "total-bytes" else gif(600)
        for frame in manifest["clips"][0]["frames"]:
            (directory / frame["file"]).write_bytes(data)
    source = spec.get("source")
    target = directory / "pixels.png"
    if source in ("missing", "symlink", "directory", "fifo"):
        target.unlink()
        if source == "symlink":
            target.symlink_to(base / "outside.png")
        elif source == "directory":
            target.mkdir()
        elif source == "fifo":
            os.mkfifo(target)
    elif source == "directory-symlink":
        shutil.rmtree(directory / "nested")
        (directory / "nested").symlink_to(base / "outside", target_is_directory=True)
    elif source == "empty":
        target.write_bytes(b"")
    elif source == "bad-magic":
        target.write_bytes(b"not an image; no network or code is executed")
    elif source == "truncated":
        target.write_bytes(image[:35])
    elif source == "oversize":
        with target.open("r+b") as stream:
            stream.truncate(24 * 1024 * 1024 + 1)
    elif source == "wide":
        target.write_bytes(png(4097, 1))
    elif source == "pixels":
        target.write_bytes(png(4000, 2001))
    elif source == "gif-601":
        target.write_bytes(gif(601))
    elif source is not None:
        raise AssertionError("Unhandled source recipe: " + source)
    encoded = json.dumps(manifest, separators=(",", ":")).encode()
    raw = spec.get("raw")
    if raw == "oversize":
        encoded += b" " * (1024 * 1024 + 1)
    elif raw in ("duplicate", "escaped-duplicate"):
        key = b'"schema"' if raw == "duplicate" else b'"\\u0073chema"'
        encoded = encoded.replace(b'"schema":1', b'"schema":1,' + key + b':1', 1)
    elif raw == "nan":
        encoded = encoded.replace(b'"duration":0.08', b'"duration":NaN', 1)
    elif raw == "deep":
        encoded = b'{"x":' * 9 + b'0' + b'}' * 9
    elif raw == "truncated":
        encoded = encoded[:-3]
    elif raw == "array":
        encoded = b"[]"
    elif raw not in (None, "symlink", "root-symlink", "ancestor-symlink"):
        raise AssertionError("Unhandled JSON recipe: " + raw)
    path = directory / "actions.json"
    path.write_bytes(encoded)
    if raw == "symlink":
        outside = base / (spec["name"] + ".external.json")
        path.rename(outside); path.symlink_to(outside)
    elif raw in ("root-symlink", "ancestor-symlink"):
        link = base / (spec["name"] + "-link")
        link.symlink_to(directory if raw == "root-symlink" else directory.parent, target_is_directory=True)
        path = link / "actions.json" if raw == "root-symlink" else link / directory.name / "actions.json"
    result = copy.deepcopy(spec); result["path"] = str(path)
    return result


def build_plan(base):
    (base / "outside").mkdir()
    (base / "outside.png").write_bytes(png())
    (base / "outside/pixels.png").write_bytes(png())
    cases = [build_fixture(base, spec) for spec in CORPUS["cases"]]
    runtime = build_fixture(base, {"name": "runtime", "make": "crop", "valid": True})
    plan = base / "plan.json"
    plan.write_text(json.dumps({"cases": cases, "runtime": runtime["path"]}))
    return plan


class StaticContract(unittest.TestCase):
    """Source/fixture assertions only; deliberately NOT a Python parser surrogate."""
    def test_public_contract(self):
        for api in ("loadManifestAtPath:", "requestFrameForClip:", "purgeFrames", "cancelPendingFrameRequests",
                    "identifier", "role", "durations", "duration", "frameCount"):
            self.assertIn(api, HEADER)
        self.assertIn("readonly", HEADER)
        self.assertIn("Caller must fence superseded load results", HEADER)

    def test_native_bounds_and_supported_types(self):
        for text in ("MSALManifestBytes = 1024 * 1024", "MSALSourceBytes = 24 * 1024 * 1024",
                     "MSALInputBytes = 128 * 1024 * 1024", "MSALCacheBytes = 8 * 1024 * 1024",
                     "MSALCacheFrames = 32", "MSALDecodeSide = 384", "MSALMaxPixels = 8000000",
                     "count > 600", "[records count] > 64", "[entries count] > 600",
                     "public.png", "public.jpeg", "com.compuserve.gif", "kCGImageSourceShouldCache"):
            self.assertIn(text, SOURCE)
        for role in ROLES:
            self.assertIn('@"' + role + '"', SOURCE)
        self.assertNotIn("CGImageSourceCreateImageAtIndex", SOURCE)

    def test_native_strict_path_and_parser_guards(self):
        for text in ("openat(", "O_NOFOLLOW", "O_NONBLOCK", "S_ISREG", "MSALSameFile", "fstat(fd, &after)",
                     "CFBooleanGetTypeID", "MSALJSONEnvelope", "clips[identifier]", "[allowed containsObject:role]",
                     "CGRectGetMaxX(rect) > 1", "candidate / aspect", "kCGImageAlphaPremultipliedLast",
                     "CGContextClearRect", "MSALOrientedRect", "CGContextClipToRect",
                     "MSALOpenDirectory(state->rootPath)", "MSALOpenDirectory(rootPath)",
                     "canBeConvertedToEncoding:NSUTF8StringEncoding", "state->canvasWidth",
                     "CGImageRelease(value); // Taking ownership also covers initializer failure."):
            self.assertIn(text, SOURCE)
        for forbidden in ("NSURLSession", "dataWithContentsOfURL", "imageNamed:", "animatedImageWithImages:", "NSLog("):
            self.assertNotIn(forbidden, SOURCE)

    def test_error_ownership_crosses_inner_pool(self):
        # Source conformance only; real invalid-source cases + ASan execute this.
        loop = SOURCE.split('for (MSALSource *source in sources) {', 1)[1]
        self.assertLess(loop.index('NSError *sourceError = nil;'), loop.index('@autoreleasepool'))
        self.assertIn('&source->identity, &sourceError', loop)
        self.assertIn('MSALInspectSource(source, input, &sourceFrames, &sourceError)', loop)
        self.assertLess(loop.index('@autoreleasepool'), loop.index('if (!sourceOK)'))
        self.assertIn('if (error) *error = sourceError;', loop)

    def test_main_boundary_and_epoch_guards(self):
        self.assertEqual(SOURCE.count("[UIImage imageWithCGImage:"), 1)
        finish = SOURCE.split("- (void)finishFrame:(MSALBitmap * _Nullable)bitmap epoch:(uint64_t)epoch {", 1)[1]
        self.assertIn("NSThread.isMainThread", finish)
        self.assertIn("UIImage *image = bitmap", finish)
        self.assertIn("__weak MiniSightActionLibrary *weakSelf", SOURCE)
        self.assertIn("if (_busy || !_pendingCompletion) return", SOURCE)
        self.assertIn("callbacks.count >= 2", SOURCE)
        self.assertIn("epoch == _epoch", SOURCE)
        self.assertIn("MSALCacheCost + bitmap->cost > MSALCacheBytes", SOURCE)
        self.assertIn("static NSCache<NSString *, MSALBitmap *> *MSALCacheImages", SOURCE)
        self.assertIn("if (![key hasPrefix:_cachePrefix]) continue", SOURCE)
        self.assertIn("[_lock lock]", SOURCE)
        self.assertNotIn("NSCache<NSString *, UIImage", SOURCE)

    def test_fixture_definitions_not_parser_execution(self):
        names = [case["name"] for case in CORPUS["cases"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(sum(not c["valid"] for c in CORPUS["cases"]), 50)
        for case in CORPUS["cases"]:
            json.dumps(make_manifest(case), allow_nan=False)
        native = (FIXTURES / "native.m").read_text()
        self.assertIn('#import "MiniSightActionLibrary.m"', native)
        self.assertIn("Fixture(entry)", native)
        self.assertIn("Load(entry[@\"path\"], &error)", native)
        self.assertIn("SchedulerTests", native)
        self.assertIn("CacheTests", native)
        self.assertIn('__weak NSObject *weakActive;', native)
        self.assertIn('__weak NSObject *weakPending;', native)
        self.assertNotIn('__weak NSObject *weakActive, *weakPending;', native)
        self.assertIn('NSObject * __weak *probe', native)
        self.assertIn('objc_precise_lifetime', native)
        self.assertIn('CHECK(!weakPending)', native)

    def test_fixture_materialization_not_native_execution(self):
        # Exercise real fixture construction, not just manifest recipes. This does
        # NOT claim Foundation parsing, ImageIO decoding or Darwin path execution.
        with tempfile.TemporaryDirectory(prefix="msal-fixtures-") as temporary:
            base = Path(temporary)
            (base / "outside").mkdir()
            (base / "outside.png").write_bytes(png())
            (base / "outside/pixels.png").write_bytes(png())
            names = {"valid-png", "valid-crop-top-left", "valid-fractional-crop", "valid-gif", "valid-apng",
                     "source-symlink-escape", "directory-symlink-escape", "source-fifo",
                     "manifest-symlink", "pack-root-symlink", "pack-ancestor-symlink"}
            built = set()
            for spec in CORPUS["cases"]:
                if spec["name"] not in names:
                    continue
                built.add(spec["name"])
                result = build_fixture(base, spec)
                path = Path(result["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(json.loads(path.read_text()), make_manifest(spec))
                directory = path.parent
                if spec.get("source") == "symlink":
                    self.assertTrue((directory / "pixels.png").is_symlink())
                elif spec.get("source") == "directory-symlink":
                    self.assertTrue((directory / "nested").is_symlink())
                elif spec.get("source") == "fifo":
                    import stat
                    self.assertTrue(stat.S_ISFIFO((directory / "pixels.png").lstat().st_mode))
                if spec.get("raw") == "symlink":
                    self.assertTrue(path.is_symlink())
                elif spec.get("raw") in ("root-symlink", "ancestor-symlink"):
                    self.assertTrue((base / (spec["name"] + "-link")).is_symlink())
                if spec.get("make") in ("gif", "apng"):
                    image = directory / ("animation." + spec["make"])
                    self.assertTrue(image.read_bytes().startswith(b"GIF89a" if spec["make"] == "gif" else b"\x89PNG"))
            self.assertEqual(built, names)

    def test_mirror_byte_identity(self):
        if MIRROR is None:
            self.skipTest("mirror checkout absent; provide --mirror-root to enforce parity")
        for name in ("MiniSightActionLibrary.h", "MiniSightActionLibrary.m"):
            self.assertEqual((CORE / name).read_bytes(), (MIRROR / name).read_bytes(), name)
        # The contract mirrors the production .h/.m, not the App-owned harness.
        # This same script also validates the plugin via --root/--mirror-root;
        # do not require or create unrelated plugin scripts during a narrow fix.


def require_apple_ci():
    if platform.system() != "Darwin" or not shutil.which("xcrun"):
        raise SystemExit("SKIP/UNAVAILABLE: iSH/Linux cannot execute Objective-C/ImageIO or Apple SDK typechecks")
    if os.environ.get("CI", "").lower() not in ("1", "true", "yes"):
        raise SystemExit("Refusing Apple compilation outside an explicitly authorized CI runner (CI=1)")


def ios_typecheck(sdk_override):
    require_apple_ci()
    sdk = sdk_override or subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    if not Path(sdk).is_dir():
        raise SystemExit("iPhoneOS SDK path is unavailable")
    clang = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True).strip()
    for arch in ("arm64", "arm64e"):
        command = [clang, "-x", "objective-c", "-std=gnu11", "-fobjc-arc", "-fblocks", "-fsyntax-only",
                   "-Wall", "-Wextra", "-Werror", "-Werror=unguarded-availability-new", "-target",
                   arch + "-apple-ios15.5", "-isysroot", sdk, "-I", str(CORE),
                   str(CORE / "MiniSightActionLibrary.m")]
        subprocess.run(command, check=True, timeout=120)
    print("PASS iOS 15.5 ARC typecheck: arm64 + arm64e, real UIKit/ImageIO headers; NOT runtime validation")


def native_tests():
    require_apple_ci()
    with tempfile.TemporaryDirectory(prefix="msal-native-") as temporary:
        directory = Path(temporary)
        executable = directory / "action-library-tests"
        command = ["xcrun", "--sdk", "macosx", "clang", "-std=gnu11", "-fobjc-arc", "-fblocks",
                   "-g", "-O1", "-fsanitize=address", "-fno-omit-frame-pointer",
                   "-Wall", "-Wextra", "-Werror", "-I", str(FIXTURES), "-I", str(CORE),
                   str(FIXTURES / "native.m"), "-framework", "Foundation", "-framework", "ImageIO",
                   "-framework", "CoreGraphics", "-o", str(executable)]
        subprocess.run(command, check=True, timeout=120)
        plan = build_plan(directory)
        subprocess.run([str(executable), str(plan)], check=True, timeout=240)
        # Prove the old fixture's actual ownership error with Apple's compiler:
        # prefix __weak qualifies ONLY the first pointer declarator, leaving
        # weakPending strong. The exact weak** helper rejects that original form.
        native_source = (FIXTURES / 'native.m').read_text()
        correct = '__weak NSObject *weakActive;\n        __weak NSObject *weakPending;'
        assert native_source.count(correct) == 1
        bad_probe = directory / 'strong-pending-probe.m'
        bad_probe.write_text(native_source.replace(correct,
            '__weak NSObject *weakActive, *weakPending;', 1))
        ownership_command = command.copy()
        ownership_command[ownership_command.index(str(FIXTURES / 'native.m'))] = str(bad_probe)
        ownership_command[ownership_command.index(str(executable))] = str(directory / 'strong-probe-tests')
        ownership = subprocess.run(ownership_command, capture_output=True, text=True, timeout=120)
        if ownership.returncode == 0 or 'changes retain/release properties of pointer' not in ownership.stderr:
            raise AssertionError('Old strong probe was not type-rejected:\n' + ownership.stdout + ownership.stderr)
        print('NATIVE PASS ownership negative: original weakPending was strong; exact weak** rejects it', flush=True)
        # The same real harness must still reject missing production cancellation.
        start = SOURCE.index('- (void)cancelPendingFrameRequests {')
        end = SOURCE.index('- (void)purgeFrames {', start)
        cancel = SOURCE[start:end]
        assert cancel.count('_pendingCompletion = nil;') == 1
        mutant = directory / 'retained-callback'
        mutant.mkdir()
        (mutant / 'MiniSightActionLibrary.m').write_text(SOURCE[:start] +
            cancel.replace('_pendingCompletion = nil;', '', 1) + SOURCE[end:])
        mutant_executable = directory / 'retained-callback-tests'
        mutant_command = command.copy()
        at = mutant_command.index(str(CORE)) - 1
        mutant_command[at:at] = ['-I', str(mutant)]
        mutant_command[mutant_command.index(str(executable))] = str(mutant_executable)
        subprocess.run(mutant_command, check=True, timeout=120)
        killed = subprocess.run([str(mutant_executable), str(plan)], capture_output=True, text=True, timeout=240)
        if killed.returncode == 0 or 'FAIL line' not in killed.stderr or '!weakPending' not in killed.stderr:
            raise AssertionError('Native cancellation mutant not assertion-killed:\n' + killed.stdout + killed.stderr)
        print('NATIVE PASS mutation: cancellation releases pending callback immediately', flush=True)
    print("Native tests used actual production code; only UIImage delivery was shimmed on macOS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=HERE.parent)
    parser.add_argument("--mirror-root", type=Path)
    parser.add_argument("--ci", action="store_true", help="Run both native tests and iOS15 typechecks; does NOT dispatch CI")
    parser.add_argument("--native", action="store_true", help="Run real Objective-C tests on an authorized CI Mac")
    parser.add_argument("--ios15-typecheck", action="store_true")
    parser.add_argument("--ios-sdk", help="Explicit iPhoneOS15.5.sdk path; otherwise use the runner's active SDK")
    args = parser.parse_args()
    CORE = source_dir(args.root.resolve())
    candidates = [args.mirror_root] if args.mirror_root else [
        Path("/var/minis/shared/MiniSight-complete-20261105"),
        Path("/var/minis/shared/openminis/minisight-workbuddy-trae-20261112")]
    MIRROR = None
    for candidate in candidates:
        if candidate and candidate.is_dir() and candidate.resolve() != args.root.resolve():
            MIRROR = source_dir(candidate.resolve()); break
    if args.mirror_root and MIRROR is None:
        raise SystemExit("Explicit mirror root missing or identical to primary root")
    SOURCE = (CORE / "MiniSightActionLibrary.m").read_text()
    HEADER = (CORE / "MiniSightActionLibrary.h").read_text()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StaticContract))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS Python: static contracts, fixture definitions, and available mirror parity ONLY", flush=True)
    if args.ci or args.ios15_typecheck:
        ios_typecheck(args.ios_sdk)
    else:
        print("SKIP iOS15 Objective-C typecheck: Apple SDK compilation reserved for explicitly authorized CI")
    if args.ci or args.native:
        native_tests()
    else:
        host = "iSH/Linux" if platform.system() != "Darwin" else "local host"
        print("SKIP Objective-C parser/ImageIO/cache execution on " + host + "; use --native/--ci on an authorized CI Mac")
