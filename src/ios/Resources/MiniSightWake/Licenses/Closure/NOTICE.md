# MiniSightWake — Eigen source-access and bundled JSON notice supplement

This supplement preserves original notices and makes the reviewed upstream source available. It supplements, and does not delete or rewrite, the earlier STATIC-NOTICE-WITH-GAPS.md and ThirdParty texts. **Publication gate remains open for the exact prebuilt-binary/source correspondence described below.** No project or device changes, compilation, CI, push, or installation were performed in this closure review.

## Complete source access (MPL-2.0 §3.2)

Eigen header code is included by the fixed Sherpa/decoder sources. Where Eigen Covered Software is distributed in Executable Form, the MPL-covered Source Code Form must also be made available, including any modifications actually used. Recipients may obtain, use, reproduce, modify and distribute that covered source under MPL-2.0. Product executable terms must not restrict those source rights. This notice is not a demand to publish unrelated application source, and MPL does not generally require LGPL-style relinkable proprietary application objects.

Complete unmodified upstream source archives, with their original file-level copyright headers, notices and licensing materials, are supplied alongside this notice:

| Archive in `Licenses/CorrespondingSource/` | Bytes | SHA-256 | Fixed upstream source |
| --- | ---: | --- | --- |
| `eigen-3.4.0.tar.gz` | 2705005 | `8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72` | https://gitlab.com/libeigen/eigen/-/tree/3147391d946bb4b6c68edd901f2add6ac1f31f8c |
| `eigen-5.0.1.tar.gz` | 2967272 | `e9c326dc8c05cd1e044c71f30f1b2e34a6161a3b6ecf445d56b53ff1669e3dec` | https://gitlab.com/libeigen/eigen/-/tree/bc3b39870ecb690a623a3f49149a358b95c5781d |

Public complete archive access, without depending on this app's private workspace:
- https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz
- https://gitlab.com/libeigen/eigen/-/archive/5.0.1/eigen-5.0.1.tar.gz

The files above were fetched publicly and their complete archive SHA-256 values match the fixed CMake declarations. Each archive is under 20 MiB. The entire original archives are supplied, not just a header subset or a pointer to a project's home page. Their redistribution preserves all original files and licensing texts, including licensing for optional modules not present in the inspected Dense include closure. No Eigen source was altered by this closure work.

## Important correction to the previous Eigen 3.4.0 inference

Sherpa commit `af2d8d81dbfa61c4cea4c568da78f3982edca005` adds its own `cmake/Modules` and `cmake` directories to CMAKE_MODULE_PATH at root CMakeLists.txt:521–522. Its `cmake/kaldi-decoder.cmake:51` APPENDs the decoder's cmake directory, then adds the decoder subdirectory. The decoder's CMakeLists.txt:57 calls `include(eigen)`. With the inspected unmodified module path, this resolves the earlier Sherpa `cmake/eigen.cmake`, which pins **5.0.1**, rather than the decoder standalone `cmake/eigen.cmake`, which pins **3.4.0**. The earlier 3.4.0-only inventory therefore cannot prove the prebuilt library's exact Eigen source version.

The official Sherpa binary archive's existing SHA-256 evidence is inherited; it was not re-downloaded or substituted. The reviewed build-ios.sh uses this CMake build. 779 newly fetched Sherpa build/source files were verified against their immutable Git blob objects; a complete decoder 0.3.0 archive was verified against its CMake SHA-256. 820 reviewed source/build files contained no Eigen patch command, Eigen plugin definition, MKL/BLAS override, or EIGEN_MPL2_ONLY definition. This proves what the fixed source recipe declares, **not** the absence of undisclosed release-runner changes in a previously compiled binary.

**Remaining publication gate:** identify the exact Eigen headers and modifications used for the distributed prebuilt Sherpa archive, using its build log/cache/compile_commands/header hashes or a controlled source rebuild. If modifications were used, provide those modified covered files as well. A signed attestation or bit-identical rebuild is not itself an MPL §3.2 document requirement; supplying the actually used covered source is the requirement. Supplying both pristine versions reduces the gap but does not assert that unknown modified source is covered.

## Header-level licensing and original notices

The conservative static literal-include unions beginning at Eigen/Dense contain 241 files for 3.4.0 and 295 files for 5.0.1, including optional platform/BLAS branches. No GPL/LGPL notice was found in either union. This is not an assertion that every optional file is compiled on iOS. Non-literal Eigen plugin includes are present in upstream headers, but no corresponding plugin definitions were found in the fixed build/source inputs. Optional unresolved mkl_lapacke.h/lapacke_config.h includes are behind feature/configuration branches not enabled in the inspected recipe. A release using unreviewed overrides needs a renewed check.

MPL-2.0 is the primary license. Actual included code also preserves individual permissive/BSD terms (including Fabian Giesen's conversion routines and Intel notices) and Apache-2.0 code such as TensorFlow's BFloat16.h. Do not replace these with one generic BSD copyright. `Licenses/Closure/Eigen/{3.4.0,5.0.1}/DENSE-TRANSITIVE-ORIGINAL-NOTICES.txt` preserves complete copyright/licensing comment blocks, with original file paths and line ranges. All root COPYING.* originals are also retained; 5.0.1's LICENSE is retained. GPL/LGPL texts in the complete 3.4.0 archive concern optional original source, not evidence that the inspected Dense code or app binary is GPL/LGPL.

## nlohmann/json 3.12.0 — complete bundled copyright capture

Source commit: `55f93686c01528224f448c19128836e7df245f72`. The publicly fetched complete archive matches fixed Sherpa json.cmake SHA-256 `4b92eb0c06d10683f7447ce9406cb97cd4b453be18d7279320f7b2f025c10187`. Sherpa includes its `include/` multi-header version; 46 files are in its literal include closure. All 48 multi-header/amalgamated headers were reviewed conservatively.

`Licenses/Closure/Json/BUNDLED-HEADER-ORIGINAL-NOTICES.txt` captures original leading and embedded copyright/licensing comments in full. In addition to Niels Lohmann, these expressly identify Florian Loitsch, Björn/Bjoern Hoehrmann, Evan Nemerson and The Abseil Authors. SPDX MIT text is read from the actual headers, not inferred merely from the project LICENSE.MIT.

The embedded cpp_future.hpp comment expressly identifies an Abseil Apache-2.0 fragment, despite the file's overall MIT SPDX marker. Its fixed original source is https://github.com/abseil/abseil-cpp/blob/10cb35e459f5ecca5b2ff107635da0bfa41011b4/absl/utility/utility.h . The original 2017 Abseil header notice, the bundled 2018 Abseil copyright, the full original Apache license and JSON MIT license are all retained. The fragment is in the pre-C++14 fallback branch; retaining its notice conservatively avoids relying on branch elimination. The fixed Abseil root tree contains LICENSE and no root NOTICE.

`Licenses/CorrespondingSource/json-3.12.0-headers-and-license.zip` additionally supplies the unmodified actual header files, both include forms, the JSON license and the accompanying Abseil notices. This is an additive permission/copyright capture, not a claim that JSON as a whole is Apache licensed.

## 本次发布许可状态

完整公开源归档、MPL 源码获取声明及两版 Dense/JSON 原文通知已补齐；不是只有许可标签或主页 URL。新发现的 CMake 模块搜索优先级将 Eigen 指向 5.0.1，纠正前次仅按 decoder 单独配置推断 3.4.0。预编译库实际使用的头文件版本/修改仍无构建实证，故不能把 MPL“对应实际源码”义务宣称完全闭合；这不是一概要求签名证明。需拿到具体构建输入记录或可控重建，确认对应源码无遗漏后，由发布负责人决定放行。旧 manifest/releaseBlockers 保持原样。
