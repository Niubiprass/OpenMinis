#!/usr/bin/env python3
"""Execute real MiniSightPetEffects.m + pure lyrics timeline on a macOS runner.

    python3 scripts/test_minisight_effects_runtime_20261116.py --require-native

No CI dispatch, iOS compilation, network, MediaRemote, device or microphone use.
UIKit host/drawing/display-link and ActionLibrary delivery are fixture shims;
PetEffects and Liveliness are current production code, not reimplemented logic.
13 Pet methods, its state enum and grid constants are extracted verbatim at run
time; unrelated host wiring is shimmed. Source guards run even on Linux/iSH.
Linux/iSH or a missing Apple SDK must SKIP; --require-native turns that into failure.
There are no Python behavioral substitutes. UIKit is synthesized in a temporary
include directory: no production import seam or project changes are needed.
"""
import argparse
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from test_minisight_atlas_restore_20261118 import core_path, source_checks, excerpt, mutations

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures/minisight_effects_runtime_20261116"


def unavailable(reason, required):
    print(("FAIL" if required else "SKIP") + ": native PetEffects not executed: " + reason,
          file=sys.stderr if required else sys.stdout, flush=True)
    return 1 if required else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=HERE.parent,
                        help="App checkout; reads src/ios/MiniSightCore only")
    parser.add_argument("--require-native", action="store_true",
                        help="Fail closed if macOS/Apple SDK execution is unavailable")
    args = parser.parse_args(argv)
    core = core_path(args.root.resolve())
    try:
        source_checks(core)
    except (AssertionError, OSError) as error:
        print('FAIL: atlas source gate: ' + str(error), file=sys.stderr)
        return 1
    if platform.system() != "Darwin" or not shutil.which("xcrun"):
        return unavailable("macOS + xcrun/Apple SDK unavailable (iSH/Linux never compiles)",
                           args.require_native)
    if os.environ.get("CI", "").lower() not in ("1", "true", "yes"):
        return unavailable("Apple native execution is reserved for an authorized CI runner", args.require_native)
    try:
        sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"],
                                      text=True, stderr=subprocess.PIPE, timeout=20).strip()
        clang = subprocess.check_output(["xcrun", "--sdk", "macosx", "--find", "clang"],
                                        text=True, stderr=subprocess.PIPE, timeout=20).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return unavailable("macOS SDK/toolchain discovery failed: " + str(error),
                           args.require_native)
    if not Path(sdk).is_dir() or not Path(clang).is_file():
        return unavailable("macOS SDK or clang path missing", args.require_native)
    needed = [core / name for name in ("MiniSightPetEffects.m", "MiniSightPetEffects.h",
              "MiniSightPet.h", "MiniSightActionLibrary.h", "MiniSightLiveliness.h",
              "MiniSightLyrics.m", "MiniSightLyrics.h")]
    needed += [core / 'MiniSightPet.m', core / 'MiniSightGeometry.h',
               FIXTURE / 'support.h', FIXTURE / 'runtime.m', FIXTURE / 'atlas_cases.inc']
    if any(not path.is_file() for path in needed):
        print("FAIL: missing production/fixture input", file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="minisight-effects-runtime-") as temporary:
            work = Path(temporary)
            (work / "UIKit").mkdir()
            # The actual production .h files still compile. Only UIKit and the
            # already-guarded chat-panel declaration are replaced by support.h.
            (work / "UIKit/UIKit.h").write_text('#import "support.h"\n')
            binary = work / "effects-runtime"
            command = [clang, "-isysroot", sdk, "-mmacosx-version-min=11.0",
                       "-std=gnu11", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra",
                       "-Werror=return-type", "-Werror=objc-method-access",
                       "-Werror=implicit-function-declaration", "-Wno-unused-parameter",
                       "-I", str(work), "-I", str(FIXTURE), "-I", str(core),
                       str(FIXTURE / "runtime.m"), str(core / "MiniSightLog.m"), "-framework", "Foundation",
                       "-framework", "CoreGraphics", "-framework", "QuartzCore",
                       "-o", str(binary)]
            pet = (core / 'MiniSightPet.m').read_text()
            effects = (core / 'MiniSightPetEffects.m').read_text()
            variants = {'baseline': (pet, effects)}
            unsafe = mutations(pet, effects)
            for name in ('getter', 'same-image-early-return', 'restore-cache-not-invalidated',
                         'poster-ratio-miscrop', 'stop-no-restore'):
                variants[name] = unsafe[name]
            # Compile-success + runtime-rejection is required, not a syntax-error negative.
            variants['whole-atlas-restore'] = (pet, effects.replace('[_pet restorePosterFrame];',
                '_sprite.contents = (__bridge id)((UIImage *)[_pet valueForKey:@"sheet"]).CGImage;'))
            fitted = 'transform = CGAffineTransformMake(fitted.a, fitted.b, fitted.c, fitted.d, fitted.tx, fitted.ty);'
            assert effects.count(fitted) == 1
            variants['visual-edge-overflow'] = (pet, effects.replace(fitted, '(void)fitted;'))
            for name, (pet_source, effects_source) in variants.items():
                (work / 'pet_atlas_excerpt.inc').write_text(excerpt(pet_source))
                (work / 'MiniSightPetEffects.m').write_text(effects_source)
                subprocess.run(command, check=True, timeout=120)
                result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
                if name == 'baseline':
                    print(result.stdout, end='')
                    if result.returncode:
                        raise RuntimeError('baseline runtime failed: ' + result.stderr)
                    # The fixture prints one `NATIVE PASS: <case>` line per case
                    # and a FINAL SUMMARY LINE that starts with the same prefix
                    # ("NATIVE PASS: 11 original … + 6 … groups; …"). Counting the
                    # raw prefix therefore always came out one too high, and the
                    # hardcoded 18 drifted out of sync the moment a case was
                    # added (b429e95 wrote 18 against 16 cases + summary = 17).
                    # Compare against the fixture's own case table instead, so the
                    # expectation follows the fixture and the summary line cannot
                    # be mistaken for a case.
                    expected = re.findall(
                        r'\{"([A-Za-z0-9-]+)",\s*[A-Za-z]',
                        (FIXTURE / 'runtime.m').read_text())
                    reported = [line[len('NATIVE PASS: '):].strip()
                                for line in result.stdout.splitlines()
                                if line.startswith('NATIVE PASS: ')]
                    seen = [name for name in reported if name in set(expected)]
                    if sorted(seen) != sorted(expected):
                        missing = sorted(set(expected) - set(seen))
                        extra = sorted(set(seen) - set(expected))
                        raise RuntimeError(
                            'native groups did not match the fixture case table: '
                            'missing=%s extra=%s' % (missing, extra))
                elif result.returncode != 1 or 'FAIL:' not in result.stderr:
                    raise RuntimeError(name + ' did not fail by a runtime assertion: ' + result.stderr)
                else:
                    print('NATIVE NEGATIVE REJECT (compiled): ' + name + ': ' + result.stderr.strip())
    except (OSError, subprocess.SubprocessError, RuntimeError, AssertionError) as error:
        # A compile error/assertion/timeout on an available SDK is NEVER a skip.
        print("FAIL: native PetEffects build/execution: " + str(error), file=sys.stderr)
        return 1
    print("PASS: actual production Objective-C behavior; UIKit host + library delivery shimmed. "
          "Not iOS/visual validation.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
