import SherpaOnnxC
import onnxruntime

/// Bundles the two pinned native targets. App code calls the guarded C API
/// directly; no Swift wrapper/example program or microphone startup is copied.
public enum MiniSightKeywordRuntime {
    public static let version = "2.0.1"
    public static let sourceCommit = "af2d8d81dbfa61c4cea4c568da78f3982edca005"
    public static let buildProvenance = "SherpaOnnxC-ci-static-arm64-ios15.5-20261116"
    public static let onnxRuntimeVersion = "1.28.2"
}
