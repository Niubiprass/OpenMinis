#!/usr/bin/env bash
# Controlled adaptation of fixed upstream build-ios.sh; never execute on iSH.
# GitHub macOS only, device arm64 only, no install, inference, device or mic.
set -euo pipefail
if [[ "$(uname -s)" != Darwin || "${GITHUB_ACTIONS:-}" != true || "${CI:-}" != true ]]; then
  echo 'ERROR: controlled keyword rebuild is GitHub macOS CI-only.' >&2
  exit 2
fi
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHECKER="$ROOT/scripts/test_minisight_keyword_provenance_20261116.py"
PACKAGE="$ROOT/src/ios/Packages/MiniSightKeywordRuntime"
ARTIFACTS="$PACKAGE/Artifacts"
WORK="${RUNNER_TEMP:?GitHub RUNNER_TEMP required}/minisight-keyword-private-dynamic-20261117-schema2"
mkdir -p "$WORK"
for tool in cmake ninja python3 xcrun xcodebuild; do
  command -v "$tool" >/dev/null || { echo "ERROR: CI requires $tool; install cmake/ninja before this step (brew install cmake ninja)." >&2; exit 2; }
done
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
[[ -d "$SDK" ]] || { echo 'ERROR: current iPhoneOS SDK missing.' >&2; exit 2; }
# Cache identity binds tools/SDK + BOTH build/checker scripts and package. No
# restore-key fallback may bypass the cryptographic artifact/proof gate.
python3 - "$WORK" "$ROOT" "$SDK" <<'PY'
import hashlib,json,pathlib,subprocess,sys
work,root,sdk=map(pathlib.Path,sys.argv[1:])
paths=['scripts/build_minisight_keyword_runtime_20261116.sh',
       'scripts/test_minisight_keyword_provenance_20261116.py',
       'scripts/test_minisight_keyword_isolation_20261117.py',
       'scripts/fixtures/minisight_runtime_isolation_20261117/vad-preserved-sections.json',
       'scripts/minisight_vad_identity_20261117.py',
       'scripts/test_minisight_vad_identity_20261117.py',
       'scripts/fixtures/minisight_runtime_isolation_20261117/vad-loader-identity.json',
       'src/ios/Packages/MiniSightKeywordRuntime/Package.swift',
       'src/ios/Packages/MiniSightKeywordRuntime/Sources/Version.swift']
identity={'schema':2,'binaryKind':'private-dynamic-framework',
 'installName':'@rpath/SherpaOnnxC.framework/SherpaOnnxC',
 'scripts':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
 'sdkPath':str(sdk),'sdkVersion':subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-version'],text=True).strip(),
 'xcode':subprocess.check_output(['xcodebuild','-version'],text=True).strip(),
 'clang':subprocess.check_output(['xcrun','clang','--version'],text=True).splitlines()[0],
 'cmake':subprocess.check_output(['cmake','--version'],text=True).splitlines()[0],
 'ninja':subprocess.check_output(['ninja','--version'],text=True).strip(),
 'target':'arm64-apple-ios15.5'}
(work/'identity.json').write_text(json.dumps(identity,sort_keys=True)+'\n')
PY
if [[ -f "$ARTIFACTS/provenance.json" ]] && python3 "$CHECKER" --cache-valid "$WORK/identity.json"; then
  echo 'PASS verified controlled keyword build cache; no recompilation.'
  exit 0
fi
# Never trust old ready=false or erase it in app resources. Only this new
# generated Artifacts directory is replaced, after a cache verification miss.
rm -rf "$ARTIFACTS" "$WORK/build"
python3 "$CHECKER" --prepare "$WORK"
ORTFW="$WORK/ort/onnxruntime.xcframework/ios-arm64/onnxruntime.framework"
[[ -f "$ORTFW/onnxruntime" ]] || { echo 'ERROR: fixed ORT arm64 framework layout changed.' >&2; exit 1; }
export SHERPA_ONNXRUNTIME_LIB_DIR="$(dirname "$ORTFW")"
export SHERPA_ONNXRUNTIME_INCLUDE_DIR="$ORTFW/Headers"
# Native CMake iOS platform with current runner SDK; this is NOT the plugin's
# separately fixed 15.5 SDK. Audit/include files live OUTSIDE pristine sources.
cmake -S "$WORK/source" -B "$WORK/build" -G Ninja -C "$WORK/inputs.cmake" \
  --trace-expand --trace-format=json-v1 \
  --trace-source="$WORK/source/cmake/eigen.cmake" \
  --trace-source="$WORK/source/cmake/openfst.cmake" \
  --trace-redirect="$WORK/cmake-trace.jsonl" \
  -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_SYSTEM_PROCESSOR=arm64 \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_SYSROOT="$SDK" \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=15.5 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER="$(xcrun --find clang)" -DCMAKE_CXX_COMPILER="$(xcrun --find clang++)" \
  -DCMAKE_CXX_STANDARD=17 -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY -DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DBUILD_SHARED_LIBS=OFF \
  -DSHERPA_ONNX_ENABLE_C_API=ON -DSHERPA_ONNX_ENABLE_BINARY=OFF \
  -DSHERPA_ONNX_BUILD_C_API_EXAMPLES=OFF -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
  -DSHERPA_ONNX_ENABLE_TESTS=OFF -DSHERPA_ONNX_ENABLE_CHECK=OFF \
  -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF -DSHERPA_ONNX_ENABLE_JNI=OFF \
  -DSHERPA_ONNX_ENABLE_WEBSOCKET=OFF -DSHERPA_ONNX_ENABLE_TTS=OFF \
  -DSHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=OFF -DSHERPA_ONNX_ENABLE_GPU=OFF \
  -DSHERPA_ONNX_ENABLE_WASM=OFF -DSHERPA_ONNX_ENABLE_DIRECTML=OFF \
  -DSHERPA_ONNX_USE_PRE_INSTALLED_ONNXRUNTIME_IF_AVAILABLE=ON
JOBS=${MINISIGHT_KEYWORD_BUILD_JOBS:-4}
[[ "$JOBS" =~ ^[1-8]$ ]] || { echo 'ERROR: build jobs must be 1..8.' >&2; exit 2; }
cmake --build "$WORK/build" --target sherpa-onnx-c-api --parallel "$JOBS"
# Exact upstream ten-archive device closure plus fixed ORT, ALL linked only
# INSIDE a private MH_DYLIB. No static ORT or C++ globals reach the App image.
libraries=(libkaldi-native-fbank-core.a libkissfft-float.a libsherpa-onnx-c-api.a
  libsherpa-onnx-core.a libsherpa-onnx-fstfar.a libssentencepiece_core.a libutf8proc.a
  libsherpa-onnx-fst.a libsherpa-onnx-kaldifst-core.a libkaldi-decoder-core.a)
inputs=()
for name in "${libraries[@]}"; do
  [[ -f "$WORK/build/lib/$name" ]] || { echo "ERROR: required static archive missing: $name" >&2; exit 1; }
  inputs+=("$WORK/build/lib/$name")
done
mkdir -p "$ARTIFACTS"
python3 - "$WORK" "$SDK" "$ROOT" "${inputs[@]}" <<'PY'
import json,pathlib,plistlib,shutil,subprocess,sys
w=pathlib.Path(sys.argv[1]);sdk=sys.argv[2]
sys.path.insert(0,str(pathlib.Path(sys.argv[3])/'scripts'))
import test_minisight_keyword_isolation_20261117 as isolation
inputs=sys.argv[4:]
fw=w/'SherpaOnnxC.framework'
if fw.exists():shutil.rmtree(fw)
(fw/'Headers/sherpa-onnx/c-api').mkdir(parents=True);(fw/'Modules').mkdir()
shutil.copy2(w/'source/sherpa-onnx/c-api/c-api.h',fw/'Headers/sherpa-onnx/c-api/c-api.h')
# Authored bridge remains OUTSIDE pristine upstream trees and is never an SPM
# source target. It calls only the ORT defined inside this same private image.
(w/'minisight-runtime-isolation.c').write_text(isolation.BRIDGE_SOURCE)
(w/'minisight-runtime-isolation.h').write_text(isolation.BRIDGE_HEADER)
(fw/'Headers/minisight-runtime-isolation.h').write_text(isolation.BRIDGE_HEADER)
(fw/'Modules/module.modulemap').write_text(isolation.MODULE)
(fw/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.minis.minisight.SherpaOnnxC',
 'CFBundleName':'SherpaOnnxC','CFBundlePackageType':'FMWK','CFBundleExecutable':'SherpaOnnxC',
 'CFBundleVersion':'20261117','CFBundleShortVersionString':'2.0.1','MinimumOSVersion':'15.5',
 'CFBundleSupportedPlatforms':['iPhoneOS']}))
exports=isolation.archive_exports((w/'build/lib/libsherpa-onnx-c-api.a').read_bytes())
(w/'exported-symbols.txt').write_text(''.join(n+'\n' for n in exports))
ort=w/'ort/onnxruntime.xcframework/ios-arm64/onnxruntime.framework'
compile_bridge=['xcrun','clang','-target','arm64-apple-ios15.5','-isysroot',sdk,'-std=c11',
 '-fvisibility=hidden','-fPIC','-I'+str(ort/'Headers'),'-I'+str(w),
 '-c',str(w/'minisight-runtime-isolation.c'),'-o',str(w/'minisight-runtime-isolation.o')]
subprocess.run(compile_bridge,check=True)
(w/'bridge-compile-command.json').write_text(json.dumps(compile_bridge)+'\n')
# Apple ld exported_symbols_list localizes ALL other globals (including weak
# C++/ORT/MLAS); no_weak_exports makes any surviving coalescible export an error.
# Legacy dyld-info rebases keep pinned API-base pointers directly inspectable.
args=['xcrun','clang++','-target','arm64-apple-ios15.5','-isysroot',sdk,'-dynamiclib',
 '-Wl,-twolevel_namespace','-Wl,-undefined,error','-Wl,-no_weak_exports','-Wl,-no_fixup_chains',
 '-Wl,-install_name,'+isolation.INSTALL_NAME,'-Wl,-exported_symbols_list,'+str(w/'exported-symbols.txt'),
 '-Wl,-map,'+str(w/'framework-link.map'),str(w/'minisight-runtime-isolation.o')]
args+=['-Wl,-force_load,'+p for p in inputs+[str(ort/'onnxruntime')]]
args+=['-framework','Foundation','-framework','CoreFoundation','-framework','CoreML',
 '-lc++','-lpthread','-o',str(fw/'SherpaOnnxC')]
(w/'framework-link-command.json').write_text(json.dumps(args)+'\n')
subprocess.run(args,check=True)
isolation.framework_gate(isolation.Image((fw/'SherpaOnnxC').read_bytes()),exports)
isolation.native_inspect(fw/'SherpaOnnxC')
# Separate App-like link probe imports ONLY public Sherpa symbols. Not executed;
# cannot initialize models/audio or force ORT into a main executable.
(w/'link-probe.cc').write_text('#include "sherpa-onnx/c-api/c-api.h"\n#include "minisight-runtime-isolation.h"\nint main() { if (!SherpaOnnxMiniSightRuntimeIsCompatible()) return 1; SherpaOnnxKeywordSpotterConfig c = {}; return SherpaOnnxCreateKeywordSpotter(&c) == nullptr; }\n')
probe=['xcrun','clang++','-target','arm64-apple-ios15.5','-isysroot',sdk,'-std=c++17',
 '-I'+str(fw/'Headers'),str(w/'link-probe.cc'),'-F'+str(w),'-framework','SherpaOnnxC',
 '-Wl,-twolevel_namespace','-Wl,-undefined,error','-Wl,-rpath,@executable_path/Frameworks',
 '-o',str(w/'link-probe')]
(w/'link-command.json').write_text(json.dumps(probe)+'\n')
subprocess.run(probe,check=True) # Link only; NEVER execute this iOS binary.
PY
xcodebuild -create-xcframework -framework "$WORK/SherpaOnnxC.framework" \
  -output "$ARTIFACTS/SherpaOnnxC.xcframework"
python3 "$CHECKER" --finalize "$WORK"
