import AVFoundation
import Foundation
import Darwin
import SherpaOnnxC

/// Local keyword spotter. Model/native calls live exclusively on `worker`.
/// Microphone callbacks copy small float buffers into this bounded mailbox;
/// neither the engine nor this component writes audio or contacts a server.
final class MiniSightWakeEngine: @unchecked Sendable {
    enum Failure: LocalizedError {
        case model, runtime, audioFormat, conversion
        var errorDescription: String? {
            switch self {
            case .runtime: return "离线名字检测组件不兼容，监听已停止，其他桌宠功能不受影响。"
            case .model: return "离线名字检测器暂时无法加载，未开启麦克风。"
            case .audioFormat: return "当前麦克风格式不适合名字唤醒，监听已停止。"
            case .conversion: return "麦克风音频转换失败，名字监听已停止。"
            }
        }
    }
    private struct Job {
        let token: UUID
        let name: String
        let pronunciation: String
        let completion: (Result<MiniSightWakeName.Prepared, Error>) -> Void
        let onHit: (UUID) -> Void
        let onFailure: (UUID, Error) -> Void
    }
    private let worker = DispatchQueue(label: "com.openminis.minisight.keyword", qos: .userInitiated)
    private let lock = NSLock()
    private var current: UUID?
    private var ready: UUID?
    private var latest: Job?
    private var preparing = false
    private var queuedBuffers = 0
    private var audioEpoch: UInt64 = 0
    // Worker-owned only. Never dereference these native objects on MAIN/tap.
    private var spotter: OpaquePointer?
    private var stream: OpaquePointer?
    private var builtToken: UUID?
    private var job: Job?
    private var cachedFiles: MiniSightWakeAssets.Files?
    private var converter: AVAudioConverter?
    private var converterRate: Double = 0
    private var processedEpoch: UInt64 = 0

    private func state<T>(_ body: () -> T) -> T {
        lock.lock(); defer { lock.unlock() }; return body()
    }
    func prepare(name: String, pronunciation: String, token: UUID,
                 onHit: @escaping (UUID) -> Void, onFailure: @escaping (UUID, Error) -> Void,
                 completion: @escaping (Result<MiniSightWakeName.Prepared, Error>) -> Void) {
        let launch = state { () -> Bool in
            current = token; ready = nil; audioEpoch &+= 1
            latest = Job(token: token, name: name, pronunciation: pronunciation, completion: completion,
                         onHit: onHit, onFailure: onFailure)
            if preparing { return false }
            preparing = true; return true
        }
        if launch { worker.async { [weak self] in self?.prepareLatest() } }
    }
    private func prepareLatest() {
        while let next = state({ () -> Job? in
            let value = latest; latest = nil
            if value == nil { preparing = false }
            return value
        }) {
            destroyNative()
            do {
                let files = try cachedFiles ?? MiniSightWakeAssets.load()
                cachedFiles = files
                let name = try MiniSightWakeName.prepare(name: next.name, pronunciation: next.pronunciation,
                                                        vocabulary: files.vocabulary)
                let handles = try makeSpotter(files: files, definition: name.definition)
                guard state({ current == next.token }) else {
                    SherpaOnnxDestroyOnlineStream(handles.stream)
                    SherpaOnnxDestroyKeywordSpotter(handles.spotter)
                    continue
                }
                spotter = handles.spotter; stream = handles.stream; builtToken = next.token; job = next
                converter = nil; converterRate = 0
                processedEpoch = state { audioEpoch }
                state { ready = next.token }
                deliver(next, result: .success(name))
            } catch {
                state { if current == next.token { ready = nil } }
                deliver(next, result: .failure(error))
            }
        }
    }
    private func deliver(_ job: Job, result: Result<MiniSightWakeName.Prepared, Error>) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.state({ self.current == job.token }) else { return }
            job.completion(result)
        }
    }
    private func makeSpotter(files: MiniSightWakeAssets.Files, definition: String) throws
        -> (spotter: OpaquePointer, stream: OpaquePointer) {
        // This preflight and Sherpa's inference code belong to the same isolated image.
        // A nil ORT API is a setup error, never an Env null dereference.
        guard SherpaOnnxMiniSightRuntimeIsCompatible() == 1 else { throw Failure.runtime }
        // C strings stay alive through the native constructor. Do not use the
        // example helper's temporary NSString UTF8 pointer in an escaped struct.
        return try files.encoder.path.withCString { encoder in
            try files.decoder.path.withCString { decoder in
                try files.joiner.path.withCString { joiner in
                    try files.tokens.path.withCString { tokens in
                        try definition.withCString { keywords in
                            try "cpu".withCString { cpu in
                                var config = SherpaOnnxKeywordSpotterConfig()
                                config.feat_config.sample_rate = 16000; config.feat_config.feature_dim = 80
                                config.model_config.transducer.encoder = encoder
                                config.model_config.transducer.decoder = decoder
                                config.model_config.transducer.joiner = joiner
                                config.model_config.tokens = tokens
                                config.model_config.num_threads = 1
                                config.model_config.provider = cpu
                                config.model_config.debug = 0
                                config.max_active_paths = 4; config.num_trailing_blanks = 2
                                config.keywords_score = 1.5; config.keywords_threshold = 0.6
                                config.keywords_buf = keywords
                                config.keywords_buf_size = Int32(definition.utf8.count)
                                guard let spotter = SherpaOnnxCreateKeywordSpotter(&config) else { throw Failure.model }
                                guard let stream = SherpaOnnxCreateKeywordStream(spotter) else {
                                    SherpaOnnxDestroyKeywordSpotter(spotter); throw Failure.model
                                }
                                return (spotter, stream)
                            }
                        }
                    }
                }
            }
        }
    }
    /// May be called from the real-time tap; admits at most THREE copied chunks.
    /// A dropped chunk invalidates the queued audio window rather than splicing
    /// syllables across missing audio and manufacturing a wake result.
    func breakAudioWindow(token: UUID) {
        state { if current == token { audioEpoch &+= 1 } }
    }
    func offer(_ samples: [Float], sampleRate: Double, token: UUID) {
        guard !samples.isEmpty, samples.count <= 8192, sampleRate.isFinite,
              (8000...192000).contains(sampleRate), samples.allSatisfy(\.isFinite) else {
            breakAudioWindow(token: token); return
        }
        let epoch: UInt64? = state {
            guard current == token, ready == token else { return nil }
            guard queuedBuffers < 3 else { audioEpoch &+= 1; return nil }
            queuedBuffers += 1; return audioEpoch
        }
        guard let epoch else { return }
        worker.async { [weak self] in
            guard let self else { return }
            defer { self.state { self.queuedBuffers -= 1 } }
            guard self.state({ self.current == token && self.ready == token && self.audioEpoch == epoch }),
                  self.builtToken == token, let spotter = self.spotter else { return }
            if self.processedEpoch != epoch {
                // Upstream Reset only resets decoder/encoder state; it leaves
                // queued feature frames. A real gap requires a NEW stream.
                if let previous = self.stream { SherpaOnnxDestroyOnlineStream(previous) }
                self.stream = SherpaOnnxCreateKeywordStream(spotter)
                self.converter = nil; self.converterRate = 0; self.processedEpoch = epoch
            }
            guard let stream = self.stream else { self.reportFailure(Failure.model, token: token); return }
            do {
                let converted = try self.convert(samples, sampleRate: sampleRate)
                guard !converted.isEmpty else { return }
                converted.withUnsafeBufferPointer { buffer in
                    SherpaOnnxOnlineStreamAcceptWaveform(stream, 16000, buffer.baseAddress, Int32(buffer.count))
                }
                var steps = 0
                while SherpaOnnxIsKeywordStreamReady(spotter, stream) == 1 && steps < 32 {
                    guard self.state({ self.current == token && self.ready == token && self.audioEpoch == epoch }) else { return }
                    steps += 1; SherpaOnnxDecodeKeywordStream(spotter, stream)
                    guard let result = SherpaOnnxGetKeywordResult(spotter, stream) else { throw Failure.model }
                    let hit: Bool
                    if let text = result.pointee.keyword, strnlen(text, 32) < 32 {
                        hit = String(cString: text) == "minisight"
                    } else { hit = false }
                    SherpaOnnxDestroyKeywordResult(result)
                    if hit {
                        SherpaOnnxResetKeywordStream(spotter, stream)
                        self.state { if self.current == token { self.ready = nil } }
                        let callback = self.job?.onHit
                        DispatchQueue.main.async { [weak self] in
                            guard let self, self.state({ self.current == token }) else { return }
                            callback?(token)
                        }
                        return
                    }
                }
            } catch { self.reportFailure(error, token: token) }
        }
    }
    private func convert(_ samples: [Float], sampleRate: Double) throws -> [Float] {
        if converter == nil || converterRate != sampleRate {
            guard let input = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate,
                                            channels: 1, interleaved: false),
                  let output = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000,
                                             channels: 1, interleaved: false),
                  let converter = AVAudioConverter(from: input, to: output) else { throw Failure.audioFormat }
            converter.primeMethod = .none
            self.converter = converter; converterRate = sampleRate
        }
        guard let converter,
              let input = AVAudioPCMBuffer(pcmFormat: converter.inputFormat, frameCapacity: AVAudioFrameCount(samples.count)),
              let channel = input.floatChannelData?[0] else { throw Failure.audioFormat }
        input.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            if let pointer = source.baseAddress { channel.update(from: pointer, count: source.count) }
        }
        let capacity = Int(ceil(Double(samples.count) * 16000 / sampleRate)) + 64
        guard capacity > 0, capacity <= 16448,
              let output = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: AVAudioFrameCount(capacity)) else {
            throw Failure.audioFormat
        }
        var supplied = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, outStatus in
            if supplied { outStatus.pointee = .noDataNow; return nil }
            supplied = true; outStatus.pointee = .haveData; return input
        }
        guard error == nil, status != .error, let result = output.floatChannelData?[0],
              output.frameLength <= output.frameCapacity else { throw Failure.conversion }
        let floats = Array(UnsafeBufferPointer(start: result, count: Int(output.frameLength)))
        guard floats.allSatisfy(\.isFinite) else { throw Failure.conversion }
        return floats
    }
    private func reportFailure(_ error: Error, token: UUID) {
        guard state({ () -> Bool in
            guard current == token, ready == token else { return false }
            ready = nil; return true
        }) else { return }
        let callback = job?.onFailure
        DispatchQueue.main.async { [weak self] in
            guard let self, self.state({ self.current == token }) else { return }
            callback?(token, error)
        }
    }
    func stop() {
        let old: UUID? = state {
            let old = current
            current = nil; ready = nil; latest = nil; audioEpoch &+= 1
            return old
        }
        guard let old else { return }
        // A late cleanup must never destroy a newer model which replaced it.
        worker.async { [weak self] in
            guard let self, self.builtToken == old else { return }
            self.destroyNative()
        }
    }
    private func destroyNative() {
        if let stream { SherpaOnnxDestroyOnlineStream(stream) }
        if let spotter { SherpaOnnxDestroyKeywordSpotter(spotter) }
        stream = nil; spotter = nil; builtToken = nil; job = nil
        converter = nil; converterRate = 0
    }
    deinit {
        // In-flight blocks retain this object before using native pointers. The
        // final release cannot race with those worker calls.
        if let stream { SherpaOnnxDestroyOnlineStream(stream) }
        if let spotter { SherpaOnnxDestroyKeywordSpotter(spotter) }
    }
}
