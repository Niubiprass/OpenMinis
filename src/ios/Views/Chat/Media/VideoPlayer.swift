//
//  VideoPlayer.swift
//  MinisApp
//
//  Inline video thumbnail bubble + fullscreen player overlay +
//  AVPlayerLayer UIViewRepresentable. Extracted from AIChatView.swift.
//

import AVFoundation
import AVKit
import Photos
import SwiftUI
import UIKit

/// Shared by input preview and playback; messages intentionally omit private paths.
enum MinisVideoFileValidation {
    static func error(for url: URL) -> String? {
        guard url.isFileURL else { return "附件地址不是本地文件，请重新选择附件。" }
        let manager = FileManager.default
        guard manager.fileExists(atPath: url.path) else {
            return "附件文件已不存在，请重新选择附件。"
        }
        guard manager.isReadableFile(atPath: url.path) else {
            return "附件文件不可读取，请重新选择附件。"
        }
        guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey]),
              values.isRegularFile == true, let size = values.fileSize else {
            return "附件不是可读取的普通文件，请重新选择附件。"
        }
        guard size > 0 else { return "附件文件为空，请重新选择附件。" }
        return nil
    }
}

// MARK: - Inline Video Player

struct MinisVideoPlayerView: View {
    let url: URL
    let fileURL: URL
    @State private var thumbnail: UIImage?
    @State private var showPlayer = false
    @State private var fileReady = false
    // [T-attachment-size-invalidate] Guard against re-posting on cell
    // reconfigure / view rebuild. Two separate transitions can grow the
    // cell (placeholder→videoContent, then thumb-nil→thumb-set), so we
    // need an idempotent post-on-grow gate per transition, but each
    // transition must only fire its own notification once.
    @State private var didNotifyFileReady = false
    @State private var didNotifyThumbnail = false

    var body: some View {
        if fileReady {
            videoContent
        } else {
            placeholder
                .task { await waitForFile() }
        }
    }

    private var videoContent: some View {
        let maxH = UIScreen.main.bounds.height / 2
        return VStack(alignment: .leading, spacing: 0) {
            if let thumb = thumbnail {
                ZStack {
                    Image(uiImage: thumb)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                    Image(systemName: "play.circle.fill")
                        .font(.system(size: 48))
                        .foregroundStyle(.white.opacity(0.9))
                        .shadow(radius: 4)
                }
                .frame(maxWidth: 400, maxHeight: maxH)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8)
                    .stroke(Color(UIColor.separator).opacity(0.5), lineWidth: 0.5))
                .onTapGesture { showPlayer = true }
            } else {
                // Fixed-size placeholder matches mediaPlaceholderHeight to prevent layout jumps
                ZStack {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(ChatColors.secondaryBg)
                    VStack(spacing: 8) {
                        Image(systemName: "play.circle.fill")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text(url.lastPathComponent)
                            .lineLimit(1)
                            .font(.caption)
                            .foregroundColor(ChatColors.secondaryText)
                    }
                }
                .frame(maxWidth: 400, minHeight: mediaPlaceholderHeight, maxHeight: mediaPlaceholderHeight)
                .onTapGesture { showPlayer = true }
            }

            if thumbnail != nil {
                HStack(spacing: 4) {
                    Image(systemName: "film")
                        .font(.caption2)
                    Text(url.lastPathComponent)
                        .lineLimit(1)
                        .font(.caption)
                }
                .foregroundColor(ChatColors.secondaryText)
                .padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear {
            loadThumbnail()
        }
        .fullScreenCover(isPresented: $showPlayer) {
            MinisVideoFullscreenPlayer(fileURL: fileURL)
        }
    }

    private var placeholder: some View {
        VStack(spacing: 8) {
            ProgressView()
            Text(url.lastPathComponent).lineLimit(1).font(.caption)
        }
        .foregroundColor(ChatColors.secondaryText)
        .frame(maxWidth: 400, minHeight: mediaPlaceholderHeight, maxHeight: mediaPlaceholderHeight)
        .background(ChatColors.secondaryBg)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func waitForFile() async {
        for _ in 0..<12 {
            if FileManager.default.fileExists(atPath: fileURL.path) {
                fileReady = true
                notifyFileReadyOnce()
                return
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        fileReady = true
        notifyFileReadyOnce()
    }

    private func notifyFileReadyOnce() {
        guard !didNotifyFileReady else { return }
        didNotifyFileReady = true
        NotificationCenter.default.post(name: .minisAttachmentSizeChanged, object: url.absoluteString)
    }

    private func notifyThumbnailOnce() {
        guard !didNotifyThumbnail else { return }
        didNotifyThumbnail = true
        NotificationCenter.default.post(name: .minisAttachmentSizeChanged, object: url.absoluteString)
    }

    private func loadThumbnail() {
        let cacheKey = fileURL.path
        // Check cache first — avoids regenerating on cell recycle
        if let cached = MinisMediaCache.shared.thumbnail(for: cacheKey) {
            thumbnail = cached
            // [T-attachment-size-invalidate] Even cache hit changes layout
            // (placeholder fixed height → aspect-fit thumbnail).
            notifyThumbnailOnce()
            return
        }
        let asset = AVAsset(url: fileURL)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 400, height: 400)
        generator.generateCGImagesAsynchronously(
            forTimes: [NSValue(time: .zero)]
        ) { _, cgImage, _, _, _ in
            if let cgImage {
                let img = UIImage(cgImage: cgImage)
                MinisMediaCache.shared.setThumbnail(img, for: cacheKey)
                DispatchQueue.main.async {
                    self.thumbnail = img
                    self.notifyThumbnailOnce()
                }
            }
        }
    }
}

// MARK: - Fullscreen Video Player

struct MinisVideoFullscreenPlayer: View {
    let fileURL: URL
    /// Optional externally-managed AVPlayer (e.g. from PlayerOffloadBridge).
    /// When provided, the view skips creating its own player.
    let externalPlayer: AVPlayer?
    @Environment(\.dismiss) private var dismiss
    @State private var player: AVPlayer?
    @State private var showShareSheet = false
    @State private var saveStatus: SaveStatus = .idle

    init(fileURL: URL, externalPlayer: AVPlayer? = nil) {
        self.fileURL = fileURL
        self.externalPlayer = externalPlayer
    }

    // Custom controls state
    @State private var isPlaying = false
    @State private var currentTime: Double = 0
    @State private var duration: Double = 0
    @State private var showControls = true
    @State private var isScrubbing = false
    @State private var timeObserver: Any?
    @State private var hideTask: DispatchWorkItem?
    @State private var rateObservation: NSKeyValueObservation?
    @State private var currentItemObservation: NSKeyValueObservation?
    @State private var itemStatusObservation: NSKeyValueObservation?
    @State private var playbackFailureObserver: NSObjectProtocol?
    @State private var playbackError: String?
    @State private var isLoading = true
    @State private var isVisible = false
    @State private var playbackGeneration = UUID()
    @State private var itemGeneration = UUID()
    @State private var resolvedFileURL: URL?
    @State private var durationTask: Task<Void, Never>?
    @State private var loadingTimeoutTask: DispatchWorkItem?
    private let loadingTimeout: TimeInterval = 20

    // Pull-to-dismiss state
    @State private var dragOffset: CGFloat = 0
    private let dismissThreshold: CGFloat = 120

    private enum SaveStatus {
        case idle, saving, saved, failed
    }

    var body: some View {
        ZStack {
            Color.black.opacity(1.0 - Double(max(dragOffset, 0) / dismissThreshold) * 0.4)
                .ignoresSafeArea()
            if let player {
                MinisAVPlayerLayerView(player: player)
                    .ignoresSafeArea()
                    .offset(y: dragOffset)
            }
            // Tap target to toggle controls + drag to dismiss
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { toggleControls() }
                .gesture(
                    DragGesture()
                        .onChanged { value in
                            let ty = value.translation.height
                            // Only allow downward drag (rubber-band for upward)
                            dragOffset = ty > 0 ? ty : ty * 0.3
                        }
                        .onEnded { value in
                            if dragOffset > dismissThreshold * 0.5 {
                                closePlayer()
                            } else {
                                withAnimation(.spring(response: 0.3)) {
                                    dragOffset = 0
                                }
                            }
                        }
                )

            // Overlays
            if showControls {
                // Top bar overlay
                VStack {
                    HStack {
                        Button {
                            closePlayer()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(ChatColors.primaryText)
                                .frame(width: 44, height: 44)
                                .contentShape(Circle())
                                .background(Color(UIColor.tertiarySystemFill), in: Circle())
                        }

                        Spacer()

                        Button {
                            saveVideoToPhotos()
                        } label: {
                            Group {
                                switch saveStatus {
                                case .idle:
                                    Image(systemName: "square.and.arrow.down")
                                        .offset(y: -1)
                                case .saving:
                                    ProgressView()
                                        .tint(ChatColors.primaryText)
                                case .saved:
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(.green)
                                case .failed:
                                    Image(systemName: "exclamationmark.triangle")
                                }
                            }
                            .font(.body.weight(.semibold))
                            .foregroundStyle(ChatColors.primaryText)
                            .frame(width: 44, height: 44)
                            .contentShape(Circle())
                            .background(Color(UIColor.tertiarySystemFill), in: Circle())
                        }
                        .disabled(saveStatus == .saving || saveStatus == .saved || resolvedFileURL == nil)

                        Button {
                            showShareSheet = true
                        } label: {
                            Image(systemName: "square.and.arrow.up")
                                .offset(y: -1)
                                .font(.body.weight(.semibold))
                                .foregroundStyle(ChatColors.primaryText)
                                .frame(width: 44, height: 44)
                                .contentShape(Circle())
                                .background(Color(UIColor.tertiarySystemFill), in: Circle())
                        }
                        .disabled(resolvedFileURL == nil)
                    }
                    .padding(.horizontal)
                    .padding(.top, 7)
                    Spacer()
                }
                .zIndex(10)
                .transition(.opacity)

                // Bottom controls overlay
                VStack {
                    Spacer()
                    HStack(spacing: 16) {
                        // Play / Pause
                        Button {
                            if isPlaying {
                                player?.pause()
                                isPlaying = false
                            } else {
                                // If at end, seek to start
                                if currentTime >= duration - 0.5 && duration > 0 {
                                    player?.seek(to: .zero)
                                    currentTime = 0
                                }
                                player?.play()
                                isPlaying = true
                            }
                            scheduleHide()
                        } label: {
                            Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                                .font(.title2)
                                .foregroundStyle(.white)
                                .frame(width: 44, height: 44)
                        }

                        // Current time
                        Text(formatTime(currentTime))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.white.opacity(0.8))

                        // Progress slider
                        Slider(
                            value: $currentTime,
                            in: 0...max(duration, 1),
                            onEditingChanged: { editing in
                                isScrubbing = editing
                                if editing {
                                    hideTask?.cancel()
                                } else {
                                    let target = CMTime(seconds: currentTime, preferredTimescale: 600)
                                    player?.seek(to: target, toleranceBefore: .zero, toleranceAfter: .zero)
                                    scheduleHide()
                                }
                            }
                        )
                        .tint(.white)

                        // Duration
                        Text(formatTime(duration))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.white.opacity(0.8))
                    }
                    .disabled(isLoading || playbackError != nil)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(
                        LinearGradient(
                            colors: [.clear, .black.opacity(0.5)],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
                }
                .transition(.opacity)
            }

            if isLoading && playbackError == nil {
                ProgressView("正在加载视频…")
                    .tint(.white)
                    .foregroundStyle(.white)
                    .padding(20)
                    .background(.black.opacity(0.65), in: RoundedRectangle(cornerRadius: 14))
                    .allowsHitTesting(false)
            }

            // Above BOTH the gesture surface and the normal controls.
            if let playbackError {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill").font(.title2)
                    Text("无法播放此视频").font(.headline)
                    Text(playbackError)
                        .font(.callout)
                        .multilineTextAlignment(.center)
                    HStack(spacing: 28) {
                        Button("关闭") { closePlayer() }
                        Button("重试") { startPlayback() }
                    }
                    .buttonStyle(.bordered)
                }
                .foregroundStyle(.white)
                .padding(24)
                .frame(maxWidth: 360)
                .background(.black.opacity(0.9), in: RoundedRectangle(cornerRadius: 14))
                .padding(24)
                .zIndex(20)
            }
        }
        .animation(.easeInOut(duration: 0.25), value: showControls)
        .onAppear {
            isVisible = true
            startPlayback()
        }
        .onDisappear {
            isVisible = false
            stopPlayback()
        }
        .sheet(isPresented: $showShareSheet) {
            if let resolvedFileURL { MinisShareSheet(url: resolvedFileURL) }
        }
        .statusBar(hidden: true)
    }

    private func startPlayback() {
        guard isVisible else { return }
        stopPlayback()
        let generation = playbackGeneration
        playbackError = nil
        isLoading = true
        showControls = true
        isScrubbing = false
        dragOffset = 0
        currentTime = 0
        duration = 0
        if saveStatus == .saving { saveStatus = .idle }
        resolvedFileURL = nil

        let playable: URL?
        if fileURL.scheme?.lowercased() == "minis" {
            // Keep the existing resolver's session scope and decoding rules.
            playable = resolveMinisFileURLCached(url: fileURL)
        } else {
            playable = fileURL
        }
        let p: AVPlayer
        if let externalPlayer {
            // The bridge owns the player, current item, position and play state.
            // Retry re-attaches observers; it must never replace its item or play.
            p = externalPlayer
            if let playable, playable.isFileURL { resolvedFileURL = playable }
        } else {
            guard let playable else {
                failPlayback("找不到此会话中的视频文件，请重新选择视频。", stage: "resolve", generation: generation)
                return
            }
            if let error = MinisVideoFileValidation.error(for: playable) {
                failPlayback(error, stage: "invalid_file", generation: generation)
                return
            }
            resolvedFileURL = playable
            p = AVPlayer(url: playable)
        }
        player = p
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: [.mixWithOthers])
        try? AVAudioSession.sharedInstance().setActive(true)

        // An external owner may replace its item while this view is visible.
        currentItemObservation = p.observe(\.currentItem, options: [.new]) { _, _ in
            DispatchQueue.main.async {
                guard acceptsCallback(generation, player: p) else { return }
                observeItem(p.currentItem, player: p, generation: generation)
            }
        }
        rateObservation = p.observe(\.rate, options: [.new]) { _, _ in
            DispatchQueue.main.async {
                guard acceptsCallback(generation, player: p), playbackError == nil else { return }
                isPlaying = p.rate > 0
                if isPlaying { scheduleHide() } else { hideTask?.cancel() }
            }
        }
        let interval = CMTime(seconds: 0.25, preferredTimescale: 600)
        timeObserver = p.addPeriodicTimeObserver(forInterval: interval, queue: .main) { time in
            guard acceptsCallback(generation, player: p), playbackError == nil, !isScrubbing else { return }
            if time.isNumeric, time.seconds.isFinite { currentTime = max(0, time.seconds) }
            if let item = p.currentItem, item.duration.isNumeric, item.duration.seconds.isFinite {
                duration = max(0, item.duration.seconds)
                if duration > 0, currentTime >= duration - 0.1 { isPlaying = false }
            }
        }
        observeItem(p.currentItem, player: p, generation: generation)
        if externalPlayer == nil { p.play() }
        isPlaying = p.rate > 0
        InputVideoDiagnostics.trace("stage=player.start external=\(externalPlayer != nil)")
    }

    private func observeItem(_ item: AVPlayerItem?, player p: AVPlayer, generation: UUID) {
        guard acceptsCallback(generation, player: p) else { return }
        itemStatusObservation?.invalidate()
        if let observer = playbackFailureObserver { NotificationCenter.default.removeObserver(observer) }
        playbackFailureObserver = nil
        durationTask?.cancel()
        durationTask = nil
        loadingTimeoutTask?.cancel()
        hideTask?.cancel()
        let itemToken = UUID()
        itemGeneration = itemToken
        playbackError = nil
        isLoading = true
        showControls = true
        currentTime = 0
        duration = 0
        let timeout = DispatchWorkItem {
            guard acceptsCallback(generation, player: p), itemGeneration == itemToken, isLoading else { return }
            failPlayback("视频加载超时，请重试；如果仍无法播放，请重新选择视频或检查文件格式。",
                         stage: "timeout", generation: generation)
        }
        loadingTimeoutTask = timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + loadingTimeout, execute: timeout)
        guard let item else { return } // An external owner can supply an item later.

        itemStatusObservation = item.observe(\.status, options: [.initial, .new]) { _, _ in
            DispatchQueue.main.async {
                guard acceptsCallback(generation, player: p), itemGeneration == itemToken,
                      p.currentItem === item, playbackError == nil else { return }
                switch item.status {
                case .readyToPlay:
                    isLoading = false
                    loadingTimeoutTask?.cancel()
                    loadingTimeoutTask = nil
                    if item.duration.isNumeric, item.duration.seconds.isFinite {
                        duration = max(0, item.duration.seconds)
                    }
                    isPlaying = p.rate > 0
                    scheduleHide()
                    InputVideoDiagnostics.trace("stage=player.ready")
                case .failed:
                    let code = (item.error as NSError?)?.code ?? 0
                    InputVideoDiagnostics.error("stage=player.item_failed code=\(code)")
                    failPlayback("视频文件可能已损坏，或系统不支持它的编码格式。请重试或重新选择视频。",
                                 stage: "item_failed", generation: generation)
                case .unknown:
                    break // Bounded by the item-scoped loading timeout.
                @unknown default:
                    break
                }
            }
        }
        playbackFailureObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemFailedToPlayToEndTime, object: item, queue: .main
        ) { _ in
            guard acceptsCallback(generation, player: p), itemGeneration == itemToken,
                  p.currentItem === item else { return }
            failPlayback("视频播放中断，文件可能已损坏或不可读取。请重试。",
                         stage: "failed_to_end", generation: generation)
        }
        durationTask = Task { @MainActor in
            let value = try? await item.asset.load(.duration)
            guard !Task.isCancelled, acceptsCallback(generation, player: p), itemGeneration == itemToken,
                  p.currentItem === item, playbackError == nil else { return }
            if let value, value.isNumeric, value.seconds.isFinite { duration = max(0, value.seconds) }
        }
    }

    private func failPlayback(_ message: String, stage: String, generation: UUID) {
        guard isVisible, playbackGeneration == generation, playbackError == nil else { return }
        hideTask?.cancel()
        hideTask = nil
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil
        durationTask?.cancel()
        durationTask = nil
        player?.pause()
        isLoading = false
        isPlaying = false
        isScrubbing = false
        showControls = true
        playbackError = message
        InputVideoDiagnostics.error("stage=player.\(stage)")
    }

    private func acceptsCallback(_ generation: UUID, player p: AVPlayer) -> Bool {
        isVisible && playbackGeneration == generation && player === p
    }

    private func stopPlayback() {
        // Invalidate FIRST: even callbacks already enqueued on main become inert.
        playbackGeneration = UUID()
        itemGeneration = UUID()
        itemStatusObservation?.invalidate()
        itemStatusObservation = nil
        currentItemObservation?.invalidate()
        currentItemObservation = nil
        rateObservation?.invalidate()
        rateObservation = nil
        if let observer = playbackFailureObserver { NotificationCenter.default.removeObserver(observer) }
        playbackFailureObserver = nil
        durationTask?.cancel()
        durationTask = nil
        loadingTimeoutTask?.cancel()
        loadingTimeoutTask = nil
        hideTask?.cancel()
        hideTask = nil
        if let observer = timeObserver { player?.removeTimeObserver(observer) }
        timeObserver = nil
        player?.pause()
        player = nil
        isPlaying = false
        isLoading = false
    }

    private func closePlayer() {
        isVisible = false
        stopPlayback()
        dismiss()
    }

    private func toggleControls() {
        showControls.toggle()
        if showControls { scheduleHide() }
    }

    private func scheduleHide() {
        hideTask?.cancel()
        guard isVisible, !isLoading, playbackError == nil, isPlaying, !isScrubbing else { return }
        let generation = playbackGeneration
        let task = DispatchWorkItem {
            guard isVisible, playbackGeneration == generation, !isLoading,
                  playbackError == nil, isPlaying, !isScrubbing else { return }
            showControls = false
        }
        hideTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: task)
    }

    private func formatTime(_ seconds: Double) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let total = Int(seconds)
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }

    private func saveVideoToPhotos() {
        guard isVisible, let localURL = resolvedFileURL else { return }
        let generation = playbackGeneration
        saveStatus = .saving
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            DispatchQueue.main.async {
                guard isVisible, playbackGeneration == generation else { return }
                guard status == .authorized || status == .limited else {
                    saveStatus = .failed
                    return
                }
                PHPhotoLibrary.shared().performChanges {
                    PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: localURL)
                } completionHandler: { success, _ in
                    DispatchQueue.main.async {
                        guard isVisible, playbackGeneration == generation else { return }
                        saveStatus = success ? .saved : .failed
                        if success {
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                guard isVisible, playbackGeneration == generation else { return }
                                saveStatus = .idle
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Raw AVPlayerLayer wrapper – renders video with no system controls.
struct MinisAVPlayerLayerView: UIViewRepresentable {
    let player: AVPlayer

    func makeUIView(context: Context) -> UIView {
        let view = PlayerLayerUIView()
        view.backgroundColor = .black
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {}

    class PlayerLayerUIView: UIView {
        override class var layerClass: AnyClass { AVPlayerLayer.self }
        var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
    }
}
