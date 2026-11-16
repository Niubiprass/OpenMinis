#!/usr/bin/env python3
"""Execute real MiniSightPetEffects.m + pure lyrics timeline on a macOS runner.

    python3 scripts/test_minisight_effects_runtime_20261116.py --require-native

No CI dispatch, iOS compilation, network, MediaRemote, device or microphone use.
UIKit host/drawing/display-link and ActionLibrary delivery are fixture shims;
PetEffects' state machine, callbacks and Liveliness functions are NOT copied.
Linux/iSH or a missing Apple SDK must SKIP; --require-native turns that into failure.
There are no Python behavioral substitutes. UIKit is synthesized in a temporary
include directory: no production import seam or project changes are needed.
"""
import argparse
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys
import tempfile

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
    core = args.root.resolve() / "src/ios/MiniSightCore"
    if not (core / "MiniSightPetEffects.m").is_file() and (args.root / "MiniSightPetEffects.m").is_file():
        core = args.root.resolve()  # Same production source and fixture runner for the plugin.
    needed = [core / name for name in ("MiniSightPetEffects.m", "MiniSightPetEffects.h",
              "MiniSightPet.h", "MiniSightActionLibrary.h", "MiniSightLiveliness.h",
              "MiniSightLyrics.m", "MiniSightLyrics.h")]
    needed += [FIXTURE / "support.h", FIXTURE / "runtime.m"]
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
                       str(FIXTURE / "runtime.m"), "-framework", "Foundation",
                       "-framework", "CoreGraphics", "-framework", "QuartzCore",
                       "-o", str(binary)]
            subprocess.run(command, check=True, timeout=120)
            subprocess.run([str(binary)], check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        # A compile error/assertion/timeout on an available SDK is NEVER a skip.
        print("FAIL: native PetEffects build/execution: " + str(error), file=sys.stderr)
        return 1
    print("PASS: actual production Objective-C behavior; UIKit host + library delivery shimmed. "
          "Not iOS/visual validation.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
