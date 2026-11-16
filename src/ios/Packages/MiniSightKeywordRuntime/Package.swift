// swift-tools-version: 5.9
import PackageDescription

// Local authored manifest, not the unlicensed ORT packaging repo's Swift code.
// Sherpa is rebuilt ONLY by scripts/build_minisight_keyword_runtime_20261116.sh
// on GitHub macOS (device arm64 / minOS15.5); generate Artifacts before SPM
// resolution/typecheck. ORT remains the separately pinned remote static target.
let package = Package(
    name: "MiniSightKeywordRuntime",
    platforms: [.iOS("15.5")],
    products: [.library(name: "MiniSightKeywordRuntime", targets: ["MiniSightKeywordRuntime"])],
    targets: [
        .binaryTarget(name: "SherpaOnnxC", path: "Artifacts/SherpaOnnxC.xcframework"),
        .binaryTarget(name: "onnxruntime",
            url: "https://github.com/csukuangfj/onnxruntime-libs/releases/download/v1.28.2/onnxruntime-ios-static-xcframework-1.28.2.xcframework.zip",
            checksum: "2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599"),
        .target(name: "MiniSightKeywordRuntime", dependencies: ["SherpaOnnxC", "onnxruntime"],
            path: "Sources", linkerSettings: [
                .linkedLibrary("c++"), .linkedFramework("Foundation"),
                .linkedFramework("CoreFoundation"), .linkedFramework("CoreML")])
    ]
)
