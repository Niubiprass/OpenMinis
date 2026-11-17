import SherpaOnnxC

/// One pinned private dynamic image, including its isolated ORT 1.28.2.
/// App code calls the same-image C preflight before model/stream construction.
/// No ORT Swift module, wrapper/example program or microphone startup is copied.
public enum MiniSightKeywordRuntime {
    public static let version = "2.0.1"
    public static let sourceCommit = "af2d8d81dbfa61c4cea4c568da78f3982edca005"
    public static let buildProvenance = "SherpaOnnxC-ci-private-dynamic-arm64-ios15.5-20261117-schema2"
    public static let onnxRuntimeVersion = "1.28.2"
}
