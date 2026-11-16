# Sherpa iOS static xcframework：第三方署名与发布通知准备稿

结论：**静态归档内的下列组件及许可文本已取证；生产发布许可仍未宣称完结。** 本稿与 `texts/` 内原文、既有 `../licenses/` 一起使用，不以本文代替完整许可证。

## 范围与证据基准

- 仅以 Sherpa v2.0.1 的固定 commit `af2d8d81dbfa61c4cea4c568da78f3982edca005` 为入口：<https://github.com/k2-fsa/sherpa-onnx/tree/af2d8d81dbfa61c4cea4c568da78f3982edca005>。
- 对照既有 `sherpa-onnx-v2.0.1-ios-static.xcframework.zip`，SHA256 `88aa569f71b7903e0bbdfbe6e2e114b3b95862b1ef0759eea3024f82926d7374`；仅新扫描其已下载 ios-arm64 `SherpaOnnxC` 的已定义符号，对照既有归档成员和未定义符号证据。**归档包含不等于最终 App 全部链接保留**，本次未读取最终 App link map。
- 固定源码 `build-ios.sh:139–149` 的 `libtool -static` 列表直接合并：kaldi-native-fbank-core、kissfft-float、sherpa-onnx-c-api/core、fstfar、fst、kaldifst-core、kaldi-decoder-core、ssentencepiece_core、utf8proc。`sherpa-onnx/csrc/CMakeLists.txt:392–397` 列出核心链接依赖。
- 依赖版本及 FetchContent SHA256 来自上述固定 CMake，不按项目名称推断许可。各依赖 tag 已经公开 API 解析为不可变提交；完整下载 URL、commit、文本 SHA256 保存在 `dependency-sources*.json`、`sources-*.json`、`header-notice-sources.json`；归档对象/符号例证见 `STATIC-LICENSE-EVIDENCE.json`。
- 仅下载和读取公开文本/构建元数据，解析本地静态符号。未执行上游代码、未安装包、未编译或触发 CI；未改 App/插件源码、依赖或 STATUS，未接触设备、麦克风、凭据，也未 push/install。

## 归档内静态确认的组件

下表的 GitHub 原文 URL 统一按 `https://raw.githubusercontent.com/{repo}/{commit}/{path}` 固定；`path` 是上游许可证路径。每个原文下载条目均保存了完整 URL，而非仅保存 tag。

| 组件 / 构建版本 | repo / 固定 commit | 许可与上游 path（本地文本） | 静态证据 |
|---|---|---|---|
| kaldi-native-fbank 1.22.4 | `csukuangfj/kaldi-native-fbank` / `95032e2223c73addc965bb84d2d1b11498eda4e9` | Apache-2.0；`LICENSE` → `texts/kaldi-native-fbank/LICENSE` | 合并清单、`feature-fbank.cc.o`、`knf` 定义及调用 |
| KissFFT 固定提交 | `mborgerding/kissfft` / `febd4caeed32e33ad8b2e0bb5ea77542c40f18ec` | BSD-3-Clause；`COPYING` + `LICENSES/BSD-3-Clause` → `texts/kissfft/` | fbank 的 `cmake/kissfft.cmake`、合并清单、5 个 FFT 对象及 `_kiss_fft*` |
| kaldi-decoder 0.3.0 | `k2-fsa/kaldi-decoder` / `62fda2d74246a90db9570e46fb16b012f813fae7` | Apache-2.0；`LICENSE` → `texts/kaldi-decoder/LICENSE` | 合并清单、`decodable-ctc.cc.o`、`eigen.cc.o` 及解码器对象 |
| kaldifst 1.8.0 | `k2-fsa/kaldifst` / `ab5bdd013bdf13921e6aeee77db5722ebf9955fb` | Apache-2.0；`LICENSE` → `texts/kaldifst/LICENSE` | decoder 的 `cmake/kaldifst.cmake`、合并清单、`context-fst.cc.o`、`kaldifst` 符号 |
| OpenFst 1.8.5-2026-04-10 | `csukuangfj/openfst` / `b3b4c7aa57e65ac32faec5648f45da9061490ddb` | Apache-2.0；`COPYING` → `texts/openfst/COPYING`；全文共用既有 Apache 原文 | kaldifst 的 `cmake/openfst.cmake`、合并 fst/fstfar、`far.cc.o`、`fst.cc.o` 等 |
| simple-sentencepiece 0.7 | `pkufool/simple-sentencepiece` / `62dd423df1d51da5ea06f1c3a046fc04f01b4f39` | Apache-2.0；`LICENSE` → `texts/simple-sentencepiece/LICENSE` | 合并清单、`ssentencepiece.cc.o` 与 `ssentencepiece` 符号 |
| Darts-clone（上述包内 darts.h） | 同一 simple-sentencepiece 固定提交；`ssentencepiece/csrc/darts.h` | BSD-2-Clause；完整嵌入版权通知提取为 `texts/simple-sentencepiece/Darts-BSD-2-Clause.txt` | 实际 `ssentencepiece.h` 包含；归档 `Darts` 符号 |
| ThreadPool（上述包内 threadpool.h） | 同一 simple-sentencepiece 固定提交；`ssentencepiece/csrc/threadpool.h` | zlib 风格原文；完整嵌入通知提取为 `texts/simple-sentencepiece/ThreadPool-zlib.txt` | 实际头文件包含；归档 `ThreadPool` 符号 |
| utf8proc 2.12.0 | `JuliaStrings/utf8proc` / `79cdd5ab40c79afa559f689ffc13b76812dee1ac` | MIT **及 Unicode 数据许可**；`LICENSE.md` → `texts/utf8proc/LICENSE.md`（保留整份三段通知） | 合并清单、`utf8proc.c.o`、`_utf8proc_*` 定义 |
| nlohmann/json 3.12.0（头文件代码） | `nlohmann/json` / `55f93686c01528224f448c19128836e7df245f72` | MIT；`LICENSE.MIT` → `texts/json/LICENSE.MIT` | Sherpa `cmake/json.cmake`；归档 `json_abi_v3_12_0` 模板定义；未另做全部 bundled header 的逐文件版权审计 |
| hclust-cpp 2026-02-25（头文件代码） | `csukuangfj/hclust-cpp` / `db76039198979ce8d03632ab6ef14fe6accb127c` | BSD-2-Clause；`LICENSE` → `texts/hclust-cpp/LICENSE` | Sherpa diarization 的 include；`fast-clustering.cc` 实际包含 `fastcluster-all-in-one.h`；归档 `fastclustercpp::hclust_fast` 定义 |

版权原文特别保留：KissFFT ©2003–2010 Mark Borgerding；OpenFst ©2005–2026 Google LLC；Darts ©2008–2014 Susumu Yata；ThreadPool ©2012 Jakob Progsch、Václav Zeman；json ©2013–2025 Niels Lohmann；hclust 的 Daniel Müllner / Christoph Dalitz 两组声明；utf8proc 的维护者、Public Software Group 与 Unicode 三组声明。完整条件和免责条款以保存原文为准。

## Eigen：静态确认使用，但发布闭环仍有疑问

- 固定 kaldi-decoder 的 `cmake/eigen.cmake` 指向官方 Eigen 3.4.0，源码归档 SHA256 `8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72`。
- 官方 tag API 已解析 commit `3147391d946bb4b6c68edd901f2add6ac1f31f8c`。不可变源入口：<https://gitlab.com/libeigen/eigen/-/tree/3147391d946bb4b6c68edd901f2add6ac1f31f8c>。许可证原文 URL：`https://gitlab.com/libeigen/eigen/-/raw/3147391d946bb4b6c68edd901f2add6ac1f31f8c/COPYING.MPL2`，及同路径 `COPYING.BSD`、`COPYING.README`，保存为 `texts/eigen/*.fixed`；`.fixed` 是提交固定文本，未修改原文。
- decoder 明确 `target_link_libraries(... Eigen3::Eigen)`、编译 `eigen.cc`，实际 `eigen.h` 包含 `Eigen/Dense`；Sherpa `fast-clustering.cc` 也包含 Dense，归档存在 Eigen 模板定义。确认不是仅下载而未使用。
- 官方 `COPYING.README` 说明主要 MPL-2.0，部分文件另有 BSD/LGPL，并以 `EIGEN_MPL2_ONLY` 排除 LGPL。本次所读构建入口未见此宏；**这不证明 LGPL/GPL 被链接**。完整传递头文件逐文件许可范围尚未核完，且生产分发需要保留 MPL 全文并落实 §3.2 的对应 covered source 获取说明（包含实际修改，如有）。公开固定源码 URL 已保存，但本次没有二进制构建证明可保证它就是完整对应源码。因此此项仍是明确缺口，而非把 Eigen 或整包判成 GPL。

## 不纳入 / 继承既有证据

- **piper-phonemize、espeak-ng：本固定构建合并清单没有这些库；归档成员没有相关对象，已定义/未定义符号扫描没有 `_espeak_*`、`espeak_ng`、`piper_phonemize` 或 `piper` 命名空间线索。** 404 的旧式 CMake 路径仅作下载记录，不作为排除依据。此版本 TTS 对象存在也不能由名称反推链接 eSpeak/GPL；未发现它们进入本归档的肯定证据，所以不添加推测性 GPL 通知。负向扫描不是数学上的不存在证明。
- iOS build 明确关掉 portaudio、websocket、tests、Python/JNI、demo binaries；本次不把仅构建工具或未进入合并清单的测试依赖列为 binary 通知。
- 模型 README 的 Apache-2.0、Sherpa 的 Apache-2.0、ORT 核心 MIT 和 ORT 既有 `../licenses/ort-ThirdPartyNotices.txt` 都沿用既有证据；没有重做模型/库兼容审计，也没有重新逐项证明 ORT aggregate notices 对最终二进制的精确覆盖。发布需携带既有完整文本及模型来源声明，不能只写“ORT MIT”。
- `onnxruntime-libs` wrapper 没有 LICENSE：**不复制其 Swift wrapper/构建脚本源代码**；main 仅直接引用已证 static xcframework。上游 ORT MIT 不自动给该 wrapper 源代码授权；直接二进制使用仍须保留 ORT 与所含第三方通知。

## 分发动作与阻断项

1. 文档/包内携带本文、所列完整许可原文及既有模型/Sherpa/ORT 通知；保留各版权与免责。Apache 组件不得用单一“Apache”标签替代全文或遗漏实际 NOTICE；此轮公开 tree 中未发现另外的根级 NOTICE，但不宣称完成所有源文件版权逐项审计。
2. 静态归档本身含有非 KWS 组件；除非最终 link map 有证据，不因“只调用唤醒 API”便删去其通知。
3. 生产放行尚需：Eigen 传递文件范围与 MPL 对应源码说明；必要的 bundled header 版权范围核验；所分发二进制对应来源/实际变更证明。这里不要求重新做兼容审计或跑 CI。

**状态：NOTICE_COLLECTION_STATIC_EVIDENCE_WITH_GAPS；生产发布暂不能宣称许可完结。**
