#!/usr/bin/env bash
#
# build_trollstore_ipa.sh — 在 macOS 上构建「支持 iOS 15 的 OpenMinis TrollStore IPA」
#
# 前置条件：
#   • macOS + Xcode 16+（含 iOS SDK，支持 deployment target 15.0）
#   • Homebrew:  brew install ninja llvm libarchive pkg-config ldid
#   • Python3 + Meson:  pip3 install meson
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

echo "==> [0/5] 初始化子模块（iSH / PRoot fork）"
git submodule update --init --recursive

echo "==> [1/5] 构建原生依赖（LAME → FFmpeg → iSH → Alpine rootfs）"
./deps/build_lame.sh
./deps/build_ffmpeg.sh
./deps/build_ish.sh
./deps/prepare_alpine_rootfs.sh

echo "==> [2/5] xcodebuild 归档（不签名，CODE_SIGNING_ALLOWED=NO）"
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

xcodebuild -project "$XCODEPROJ" \
  -scheme Minis \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$OUTPUT_DIR/Minis.xcarchive" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGN_IDENTITY="" \
  AD_HOC_CODE_SIGNING_ALLOWED=NO \
  archive

APP="$OUTPUT_DIR/Minis.xcarchive/Products/Applications/Minis.app"

echo "==> [3/5] ldid 伪签名（注入 TrollStore entitlements，含 JIT）"
if ! command -v ldid >/dev/null 2>&1; then
  echo "    缺少 ldid，请执行: brew install ldid"
  exit 1
fi
ldid -S"$ENTITLEMENTS" "$APP"
# 对扩展一并签名（Share / Widget / FileProvider）
for ext in "$APP"/Plugins/*.appex; do
  [ -e "$ext" ] && ldid -S"$ENTITLEMENTS" "$ext" && echo "    已签名扩展: $(basename "$ext")"
done

echo "==> [4/5] 打包为 IPA"
rm -rf "$OUTPUT_DIR/Payload"
mkdir -p "$OUTPUT_DIR/Payload"
cp -R "$APP" "$OUTPUT_DIR/Payload/"

# 清理无关产物，减小体积
rm -rf "$OUTPUT_DIR/Payload/Minis.app/_CodeSignature" 2>/dev/null || true

cd "$OUTPUT_DIR"
zip -r -q OpenMinis-TrollStore.ipa Payload

echo ""
echo "✅ 构建完成: $OUTPUT_DIR/OpenMinis-TrollStore.ipa"
echo "   安装方式：用 TrollStore 直接打开/分享此 IPA 安装；首次运行前在"
echo "   TrollStore 里对该 App 点「Enable JIT」（iSH 沙盒需要 JIT 才能跑 Linux）。"
