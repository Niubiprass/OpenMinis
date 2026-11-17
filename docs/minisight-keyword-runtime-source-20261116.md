# MiniSight keyword runtime: controlled CI source rebuild (2026-11-16)

## 2026-11-17 build316 真机崩溃修订（本地候选）

下文 2026-11-16 的静态 framework / standalone link probe 是旧封装记录，不再作为安全发布依据。匹配三份 IPS 与正式 build316 主程序后，已证新 Sherpa 请求 ORT API28，却从旧语音 VAD 动态库导入只支持 API1–20 的 `OrtGetApiBase`；初始化返回空接口，随后整个 App 崩溃。

本次保留所有固定版本与许可来源，将 Sherpa＋ORT 静态实现封装进一个真正的私有动态 `SherpaOnnxC.framework`，只暴露 Sherpa C 接口及专属运行前预检，ORT/MLAS/内部 C++ 不跨框架公开。SPM 不再让 ORT 独立进入 App。旧 VAD 代码与手动语音、名字 OFF/锁屏/取消、歌词动作余额均保留。源码构建完成必须检查真实动态类型、导出与绑定；完整 App 和最终 IPA 解压后二次验证新框架对应受控产物、旧 VAD 执行/数据 section 对应原基线。

这仍是本地修复候选：本地源码检查不等于 Apple 原生运行、CI 编译或 iOS15.5 真机验收。详见 `minisight-316-wake-runtime-crash-20261117.md`；旧 `standalone_link_probe.run=false` 不能再用来表示运行通过。

## Scope and status

Only the new build/checker scripts, the local `MiniSightKeywordRuntime` package manifest/version markers and this source note are changed. No app/project/workflow/model-resource manifest, feature/lifecycle policy, installer or device/microphone operation is changed. No native compilation is performed on iSH. Local static checks do not constitute a completed build, source-correspondence closure or runtime proof. The older licence agent's `FINAL.json` (`ready:false`), app closure notices and release blockers are deliberately retained.

Run on an authorized **GitHub macOS runner only**, after Xcode selection and **before `Verify fixed source`**, iOS Swift typechecking and any SPM resolution/Xcode build. `cmake` and `ninja` must already be available: move/add `brew install cmake ninja` before this new step; the later existing brew step is too late. The script does not install a generic toolchain, run official simulator builds, run inference, install or invoke a microphone.

## Fixed source and binary inputs

- Sherpa upstream `k2-fsa/sherpa-onnx`, commit `af2d8d81dbfa61c4cea4c568da78f3982edca005`, version API remains `2.0.1`.
- Source URL: `https://codeload.github.com/k2-fsa/sherpa-onnx/tar.gz/af2d8d81dbfa61c4cea4c568da78f3982edca005`.
- Source archive: **11,932,226 bytes** (actual 11.38 MiB, not an assumed 8 MiB); SHA256 `afcafe3c34bc2f15a363ad791fa1644a69bf0977a58c1b4f617468976c2faeb5`. A bounded stream was hashed for static pinning; no full Sherpa source was locally extracted/built.
- ORT stays the existing remote SPM binary target `onnxruntime`, version `1.28.2`, URL `https://github.com/csukuangfj/onnxruntime-libs/releases/download/v1.28.2/onnxruntime-ios-static-xcframework-1.28.2.xcframework.zip`, **33,821,118 bytes**, SHA256 `2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599`.
- Complete downloaded Sherpa/dependency source archives have an aggregate **50 MiB compressed source budget**. The separately fixed ORT binary archive has its independent exact size budget. All source/dependency downloads/extractions for building occur in CI, are SHA checked and use isolated source paths with `FETCHCONTENT_SOURCE_DIR_*` overrides / disconnected FetchContent; no mirror or host-installed dependency substitution is accepted.

The checker pins and cross-checks each URL/hash against the **effective fixed upstream CMake file**, before using it:

| Effective dependency | Version/ref | SHA256 |
|---|---|---|
| kaldi-native-fbank | 1.22.4 | `257fea639585ca6ee00860493bb9d7ab32488b8a5407ffe434c1f361ea545fae` |
| kissfft | febd4caeed32e33ad8b2e0bb5ea77542c40f18ec | `497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd` |
| utf8proc | 2.12.0 | `f564011d38b2888d583d510b08e69ffa15aa117155db1b9b49ef1dfe1fa25111` |
| kaldi-decoder | 0.3.0 | `b9f34cfb4fd3b1344100eead79ef4d37aa15962274b9e3056de345021f76a1b0` |
| kaldifst | 1.8.0 | `3f247b7e5a2409071202f5e2bc6200060f66728c0a3443c03923ad2723e040b3` |
| OpenFST | 1.8.5-2026-07-09 | `2ff712a32952fcb01d351121a6bc8ccf4fdc6b2aa06ce8df2b3095dedd518c0e` |
| Eigen | 5.0.1 | `e9c326dc8c05cd1e044c71f30f1b2e34a6161a3b6ecf445d56b53ff1669e3dec` |
| simple-sentencepiece | 0.7 | `1748a822060a35baa9f6609f84efc8eb54dc0e74b9ece3d82367b7119fdc75af` |
| nlohmann/json | 3.12.0 | `4b92eb0c06d10683f7447ce9406cb97cd4b453be18d7279320f7b2f025c10187` |

The main Sherpa `CMAKE_MODULE_PATH` takes priority over nested decoder/kaldifst declarations: **Eigen 5.0.1** and **OpenFST 2026-07-09**, not standalone decoder Eigen 3.4.0/OpenFST 2026-04-10. A CI CMake trace records the actual modules. An external deferred CMake observer reads the actual Eigen directory's `EIGEN_VERSION_NUMBER` into cache `MINISIGHT_EIGEN_VERSION`, actual path into `MINISIGHT_EIGEN_SOURCE_DIR`, and the original display string into `MINISIGHT_EIGEN_CMAKE_VERSION_STRING`. The pristine Eigen 5.0.1 CMake defaults its display suffix to `-dev` although `Eigen/Version` declares 5.0.1; record both rather than altering covered source or pretending the suffix is absent.

ORT's preserved upstream notice contains an Eigen MPL-2.0 section **without an exact version statement**. It supplies the original MPL text, not evidence that any Sherpa header is 3.4.0. Keep both already packaged complete Eigen sources (3.4.0 and 5.0.1), JSON 48-header/amalgamated licence bundle and all existing notices. CI compares every actual Eigen/JSON original header against the exact download and the shipped covered-source bundle. It also compares every original downloaded file before/after CMake/build; changes fail closed. The official source's `version.cc` has a historical embedded git string `96255a1b`; it is not rewritten or treated as provenance. The pinned archive/full-tree manifest and new Swift `sourceCommit` are authoritative.

## Build and stable interfaces

```sh
bash scripts/build_minisight_keyword_runtime_20261116.sh
python3 scripts/test_minisight_keyword_provenance_20261116.py --artifact
```

- Native CMake iOS system, `arm64`, **current runner iPhoneOS SDK**, deployment **15.5**; no relationship to the plugin's separately fixed 15.5 SDK requirement.
- C API ON. Demos, binaries, tests, checks, Python, JNI, websocket/PortAudio, TTS and speaker diarization OFF. Their upstream C-API implementation blocks have stable compile guards; keyword APIs remain unchanged. No app-facing feature/lifecycle is retargeted.
- Target only `sherpa-onnx-c-api`; merge exactly the ten static archives listed in checker `LIBRARIES`, matching the fixed official `build-ios.sh` device closure. Do **not** merge ORT or unbuilt C++ wrapper archive. A force-load iOS link probe covers all merged objects plus the fixed ORT archive, but is **never executed**.
- Actual ORT undefined symbols require **Foundation, CoreFoundation, CoreML and libc++**. Both the local SPM target and the probe declare these links; no upstream Swift wrapper is copied.
- Output: `src/ios/Packages/MiniSightKeywordRuntime/Artifacts/SherpaOnnxC.xcframework` with one `ios-arm64/SherpaOnnxC.framework` slice; static Mach-O arm64 objects with minOS15.5. Exact module `SherpaOnnxC`, public header `Headers/sherpa-onnx/c-api/c-api.h`, SHA256 `5698f38ba09ad2bdf085c56a6cbbd7741acf15e25f4ce5c7097b9702cadf437f`.
- Provenance: adjacent `Artifacts/provenance.json`, schema 1; archive pins, actual CMake Eigen version/path, source-root hash, original/compiled-header SHA proof, exact merge list, CMake trace/cache/compiler commands, symbol and link proof, file hash inventory, complete corresponding source archives and fixed ORT input. Written only after successful build, static link and pristine/bundled-source checks. `correspondenceVerified:true` means **build-source correspondence**, not runtime/global licence/release readiness: `runtimeTested:false`, `releaseReady:false` remain.
- Existing `MiniSightKeywordRuntime.version` stays `2.0.1`; additive `sourceCommit`, `buildProvenance` and `onnxRuntimeVersion` markers do not start audio.

## Parent integration still required

1. Add these CI steps **before fixed-source verification**, after selecting Xcode. Keep job's 65-minute limit. Cache `src/ios/Packages/MiniSightKeywordRuntime/Artifacts` via `actions/cache@v4`; key includes runner OS/architecture, Xcode build, current iOS SDK version and `hashFiles` for both new scripts, Package.swift and Version.swift. Do not use a generic restored prebuilt Sherpa fallback. Internal `--cache-valid` also binds exact tool/SDK/script identity and recomputes artifact/full-source/header hashes; a miss triggers a clean CI rebuild. `MINISIGHT_KEYWORD_BUILD_JOBS` defaults to 4 (allowed 1..8).
2. The current `scripts/test_minisight_wake_ios_20261116.py` still downloads remote Sherpa headers. Parent must remove the Sherpa row from its `PINS`, require the new checker `--artifact`, and use `-F src/ios/Packages/MiniSightKeywordRuntime/Artifacts/SherpaOnnxC.xcframework/ios-arm64`; keep only its fixed ORT download. No fallback to old Sherpa is permitted. This file was deliberately **not** changed by this subtask.
3. After CI produces/verifies evidence, parent may bind the new provenance to app Resources/manifest and handle release blockers/notices. Do not merely delete old `ready:false`, claim exact Eigen from older prebuilt metadata, or mark corresponding source complete before the deterministic CMake/header proof exists. Upload/cache Artifacts evidence with the build; do not bundle the ORT binary input/source proof into app model resources accidentally. Generated Artifacts should not be committed (parent may add scoped gitignore if needed).
4. Main owns workflow/project/manifest edits and separately authorized push/CI/retries. This subtask performs **no push or CI dispatch**. Earliest remaining execution dependency is this parent wiring plus first authorized GitHub macOS build; local checker `--artifact` must currently fail for missing output.
