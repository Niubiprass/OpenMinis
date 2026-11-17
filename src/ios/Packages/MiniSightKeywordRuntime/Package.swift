// swift-tools-version: 5.9
import PackageDescription

// Local authored manifest, not the unlicensed ORT packaging repo's Swift code.
// Sherpa is rebuilt ONLY by scripts/build_minisight_keyword_runtime_20261116.sh
// on GitHub macOS (device arm64 / minOS15.5); generate Artifacts before SPM
// resolution/typecheck. Fixed ORT 1.28.2 lives privately INSIDE that dynamic
// image; never expose an ORT static target/module to the App (old VAD has ORT).
let package = Package(
    name: "MiniSightKeywordRuntime",
    platforms: [.iOS("15.5")],
    products: [.library(name: "MiniSightKeywordRuntime", targets: ["MiniSightKeywordRuntime"])],
    targets: [
        .binaryTarget(name: "SherpaOnnxC", path: "Artifacts/SherpaOnnxC.xcframework"),
        .target(name: "MiniSightKeywordRuntime", dependencies: ["SherpaOnnxC"],
            path: "Sources")
    ]
)
