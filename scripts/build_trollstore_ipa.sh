#!/usr/bin/env bash
#
# build_trollstore_ipa.sh — 在 macOS 上构建支持 TrollStore（巨魔）安装的 IPA
#
# 前置条件（GitHub macOS runner 已全部具备）：
#   • Xcode 16+（含 iOS SDK，支持 deployment target 15.0）
#   • Homebrew:  brew install ninja llvm libarchive pkg-config ldid
#   • Python3 + Meson:  pip3 install meson
#   • Go 1.25+（rclone 用）
#
# 用法：
#   ./scripts/build_trollstore_ipa.sh
#
# 产物：build-trollstore/OpenMinis-TrollStore.ipa
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

OUTPUT_DIR="$REPO_ROOT/build-trollstore"
XCODEPROJ="$REPO_ROOT/src/ios/Minis.xcodeproj"
ENTITLEMENTS="$REPO_ROOT/src/ios/Minis-TrollStore.entitlements"

step() { echo ""; echo "==> [$1] $2"; }

step "1/6" "初始化子模块（iSH / PRoot fork）"
git submodule update --init --recursive

step "2/6" "构建原生依赖"
# 顺序有依赖：FFmpeg 链接 LAME，所以 LAME 必须先存在，否则 MP3 编码被静默丢弃。
# rclone 是工程直接引用的 framework（备份功能的远端后端），缺失会链接失败。
./deps/build_lame.sh
./deps/build_ffmpeg.sh
./deps/build_ish.sh
./deps/prepare_alpine_rootfs.sh
./deps/build_rclone_ios.sh

step "3/6" "检查 Metal Toolchain"
# FFmpeg 的 configure 会探测 metal 编译器，缺失时**静默丢弃**
# yadif_videotoolbox 滤镜（不报错，但功能缺失）。这里只警告，不阻断构建。
if ! xcrun -sdk iphoneos metal --version >/dev/null 2>&1; then
  echo "    ⚠️  Metal Toolchain 缺失 — FFmpeg 将不包含 yadif_videotoolbox 滤镜"
fi

step "4/6" "xcodebuild 归档（不签名）"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

xcodebuild -project "$XCODEPROJ" \
  -scheme Minis \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$OUTPUT_DIR/Minis.xcarchive" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  AD_HOC_CODE_SIGNING_ALLOWED=NO \
  ONLY_ACTIVE_ARCH=NO \
  archive \
  2>&1 | tee "$OUTPUT_DIR/xcodebuild.log"

APP="$OUTPUT_DIR/Minis.xcarchive/Products/Applications/Minis.app"
if [ ! -d "$APP" ]; then
  echo "❌ 未产出 .app，详见 $OUTPUT_DIR/xcodebuild.log 中的 BUILD FAILED"
  exit 1
fi

step "5/6" "ldid 伪签名（注入 TrollStore entitlements，含 JIT）"
command -v ldid >/dev/null 2>&1 || {
  echo "❌ 缺少 ldid，请执行: brew install ldid"
  exit 1
}
ldid -S"$ENTITLEMENTS" "$APP"
# 扩展（Share / Widget / FileProvider）一并签名，否则嵌入失败
for ext in "$APP"/Plugins/*.appex; do
  [ -e "$ext" ] && ldid -S"$ENTITLEMENTS" "$ext" && echo "    已签名扩展: $(basename "$ext")"
done

step "6/6" "打包为 IPA"
mkdir -p "$OUTPUT_DIR/Payload"
cp -R "$APP" "$OUTPUT_DIR/Payload/"
rm -rf "$OUTPUT_DIR/Payload/Minis.app/_CodeSignature" 2>/dev/null || true

cd "$OUTPUT_DIR"
zip -r -q OpenMinis-TrollStore.ipa Payload

echo ""
echo "✅ 构建完成: $OUTPUT_DIR/OpenMinis-TrollStore.ipa"
echo ""
echo "   安装：TrollStore 打开/分享此 IPA 即可。"
echo "   ⚠️  首次运行前，在 TrollStore 里对该 App 点「Enable JIT」——"
echo "      iSH 沙盒需要 ARM64 JIT 才能在设备内跑 Linux。"
