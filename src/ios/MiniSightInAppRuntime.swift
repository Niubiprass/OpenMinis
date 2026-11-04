import Combine
import CoreFoundation
import CoreMotion
import SwiftUI
import UIKit

/// Jailbreak-free MiniSight runtime. This only renders inside Minis; the optional
/// SpringBoard tweak owns cross-app/Home Screen presentation.
struct MiniSightInAppRuntime: View {
    @AppStorage("minisight.style") private var style = 0
    @AppStorage("minisight.renderer") private var renderer = 0
    @AppStorage("minisight.mode") private var mode = 0
    @AppStorage("minisight.petSize") private var petSize = 96.0
    @AppStorage("minisight.gravity") private var gravityEnabled = false
    @AppStorage("minisight.diagnostics") private var diagnosticsEnabled = false
    @AppStorage("minisight.record") private var recordingEnabled = false
    @AppStorage("minisight.longPress") private var longPressEnabled = true
    @AppStorage("minisight.chat.height") private var chatHeight = 360.0
    @AppStorage("minisight.chat.theme") private var chatTheme = 0
    @AppStorage("minisight.chat.tintHex") private var chatTintHex = "8B5CF6"
    @AppStorage("minisight.chat.tintAlpha") private var chatTintAlpha = 0.22
    @AppStorage("minisight.pet.x") private var petX = 0.5
    @AppStorage("minisight.pet.y") private var petY = 0.52

    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject private var lockStore = SessionLockStore.shared
    @StateObject private var activity = MiniSightAppActivity()
    @StateObject private var motion = MiniSightAppMotion()
    @StateObject private var recorder = MiniSightAppRecorderModel()
    @State private var petImage: UIImage?
    @State private var petIdentity = ""
    @State private var preferencesLoaded = false
    @State private var toast: String?

    private var visible: Bool {
        preferencesLoaded && renderer == 1 && style == 1 && activity.shown && petImage != nil && scenePhase == .active
            && !lockStore.appIsLocked && (mode == 1 || activity.active)
    }

    var body: some View {
        Group {
            if visible, let petImage {
                MiniSightPetHost(image: petImage, displaySize: CGFloat(petSize), roll: motion.roll,
                                 activityActive: activity.active, gravityEnabled: gravityEnabled,
                                 shakeGeneration: motion.shakeGeneration,
                                 shakeDirection: motion.shakeDirection, shakeStrength: motion.shakeStrength,
                                 longPressEnabled: longPressEnabled, centerX: $petX, centerY: $petY,
                                 onSingleTap: showLocalLine, onDoubleTap: openChat,
                                 onLongPress: toggleRecording)
            .frame(width: 1, height: 1)
                    .opacity(0.001)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
        }
        .onAppear {
            petIdentity = MiniSightAppFiles.petIdentity
            petImage = MiniSightAppFiles.loadPet()
            activity.refresh()
            preferencesLoaded = true
            setAppForeground(scenePhase == .active)
            motion.configureDiagnostics(diagnosticsEnabled)
            motion.setEnabled(gravityEnabled && visible)
        }
        .onChange(of: scenePhase) { phase in
            let active = phase == .active
            setAppForeground(active)
            motion.setEnabled(gravityEnabled && visible)
            if active { activity.refresh() } else { recorder.stopIfNeeded() }
        }
        .onChange(of: renderer) { _ in updateOwnershipMarker() }
        .onChange(of: style) { _ in updateOwnershipMarker() }
        .onChange(of: mode) { _ in updateOwnershipMarker() }
        .onChange(of: activity.shown) { _ in updateOwnershipMarker() }
        .onChange(of: activity.active) { _ in updateOwnershipMarker() }
        .onChange(of: petImage != nil) { _ in updateOwnershipMarker() }
        .onChange(of: visible) { shown in motion.setEnabled(gravityEnabled && shown) }
        .onChange(of: gravityEnabled) { enabled in motion.setEnabled(enabled && visible) }
        .onChange(of: diagnosticsEnabled) { enabled in motion.configureDiagnostics(enabled) }
        .onChange(of: chatHeight) { _ in refreshChatPanelAppearance() }
        .onChange(of: chatTheme) { _ in refreshChatPanelAppearance() }
        .onChange(of: chatTintHex) { _ in refreshChatPanelAppearance() }
        .onChange(of: chatTintAlpha) { _ in refreshChatPanelAppearance() }
        .onChange(of: lockStore.appIsLocked) { locked in
            if locked { MiniSightChatPanel.existingPanel()?.close() }
        }
        .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { _ in
            if scenePhase == .active {
                activity.refresh()
                let identity = MiniSightAppFiles.petIdentity
                if identity != petIdentity {
                    petIdentity = identity
                    petImage = MiniSightAppFiles.loadPet()
                    updateOwnershipMarker()
                }
            }
        }
        .onReceive(activity.$executing.dropFirst()) { executing in
            guard recordingEnabled else { recorder.stopIfNeeded(); return }
            if executing { recorder.startIfNeeded() } else { recorder.stopIfNeeded() }
        }
        .onChange(of: recordingEnabled) { enabled in
            if !enabled { recorder.stopIfNeeded() }
        }
        .onReceive(recorder.$message.compactMap { $0 }) { text in
            toast = text
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                if toast == text { toast = nil }
            }
        }
    }

    private func setAppForeground(_ active: Bool) {
        MiniSightAppFiles.postForegroundChanged()
        if active { activity.refresh() }
    }

    private func updateOwnershipMarker() {
        MiniSightAppFiles.postForegroundChanged()
    }

    private func refreshChatPanelAppearance() {
        guard let panel = MiniSightChatPanel.existingPanel(), panel.isVisible else { return }
        panel.appearancePreferences = MiniSightAppFiles.appearancePreferences
    }

    private func showLocalLine() {
        let lines = ["你好呀，我在这里。", "想聊点什么？", "我听着呢。"]
        let line = lines[Int.random(in: 0..<lines.count)]
        toast = line
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) { if toast == line { toast = nil } }
    }

    private func openChat() {
        let panel = MiniSightChatPanel.sharedPanel()
        panel.containerPath = MiniSightAppFiles.containerPath
        panel.appearancePreferences = MiniSightAppFiles.appearancePreferences
        guard let scene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene })
            .first(where: { $0.activationState == .foregroundActive }) else {
            toast = "聊天窗口暂不可用。"
            return
        }
        if !panel.showInWindowScene(scene) { toast = "聊天窗口暂不可用。" }
    }

    private func toggleRecording() {
        guard longPressEnabled else { return }
        if recorder.isRecording { recorder.stop() }
        else { recorder.start() }
    }
}

private enum MiniSightAppFiles {
    static var directory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MiniSight", isDirectory: true)
    }
    static var containerPath: String { directory.deletingLastPathComponent().deletingLastPathComponent().path }
    static var petIdentity: String {
        let path = directory.appendingPathComponent("pet.png").path
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path) else { return "missing" }
        return "\(attrs[.size] ?? 0)|\(attrs[.modificationDate] ?? Date.distantPast)"
    }
    static func loadPet() -> UIImage? { UIImage(contentsOfFile: directory.appendingPathComponent("pet.png").path) }
    static var appearancePreferences: [AnyHashable: Any] {
        let defaults = UserDefaults.standard
        return [
            "minisight.chat.height": defaults.object(forKey: "minisight.chat.height") ?? 360,
            "minisight.chat.theme": defaults.object(forKey: "minisight.chat.theme") ?? 0,
            "minisight.chat.tintHex": defaults.string(forKey: "minisight.chat.tintHex") ?? "8B5CF6",
            "minisight.chat.tintAlpha": defaults.object(forKey: "minisight.chat.tintAlpha") ?? 0.22,
        ]
    }
    static func postForegroundChanged() {
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName("com.openminis.minisight.app-active" as CFString), nil, nil, true)
    }
}

@MainActor
private final class MiniSightAppActivity: ObservableObject {
    @Published private(set) var active = false
    @Published private(set) var executing = false
    @Published private(set) var shown = true
    private var refreshInFlight = false

    func refresh() {
        guard !refreshInFlight else { return }
        refreshInFlight = true
        let url = MiniSightAppFiles.directory.appendingPathComponent("activity.json")
        let shownURL = MiniSightAppFiles.directory.appendingPathComponent("shown")
        DispatchQueue.global(qos: .utility).async {
            let data = try? Data(contentsOf: url)
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let isActive = (object?["activeCount"] as? Int ?? 0) > 0 || (object?["visible"] as? Bool ?? false)
            let isExecuting = (object?["executingCount"] as? Int ?? 0) > 0
            let isShown = (try? String(contentsOf: shownURL, encoding: .utf8)) != "0"
            DispatchQueue.main.async {
                self.active = isActive
                self.executing = isExecuting
                self.shown = isShown
                self.refreshInFlight = false
            }
        }
    }
}

@MainActor
private final class MiniSightAppMotion: ObservableObject {
    @Published private(set) var roll = 0.0
    @Published private(set) var shakeGeneration = 0
    @Published private(set) var shakeDirection = 1.0
    @Published private(set) var shakeStrength = 0.0

    private let manager = CMMotionManager()
    private var requestedEnabled = false
    private var lastSampleTime: CFTimeInterval = 0
    private var lastDiagnosticTime: CFTimeInterval = 0
    private var gravityX = 0.0
    private var gravityY = 0.0
    private var gravityZ = 0.0
    private var gravityEstimateReady = false
    private var shakeLatched = false

    func configureDiagnostics(_ enabled: Bool) {
        MSDiagConfigure(enabled, MiniSightAppFiles.containerPath)
    }

    func setEnabled(_ enabled: Bool) {
        requestedEnabled = enabled
        guard enabled else {
            manager.stopDeviceMotionUpdates()
            manager.stopAccelerometerUpdates()
            lastSampleTime = 0
            gravityEstimateReady = false
            gravityX = 0
            gravityY = 0
            gravityZ = 0
            shakeLatched = false
            roll = 0
            MSDiagMessage("gravity app stopped reason=disabled")
            return
        }
        guard !manager.isDeviceMotionActive && !manager.isAccelerometerActive else { return }
        guard manager.isDeviceMotionAvailable || manager.isAccelerometerAvailable else {
            MSDiagMessage("gravity app unavailable deviceMotion=0 accelerometer=0")
            return
        }
        if manager.isDeviceMotionAvailable {
            manager.deviceMotionUpdateInterval = 1.0 / 30.0
            manager.startDeviceMotionUpdates(to: .main) { [weak self] sample, error in
                guard let self, self.requestedEnabled else { return }
                if let error {
                    MSDiagMessage("gravity app deviceMotion error=\(error.localizedDescription)")
                    self.manager.stopDeviceMotionUpdates()
                    self.startAccelerometerFallback()
                    return
                }
                guard let sample else { return }
                self.apply(gravityX: sample.gravity.x, gravityY: sample.gravity.y,
                           userX: sample.userAcceleration.x, userY: sample.userAcceleration.y,
                           userZ: sample.userAcceleration.z)
            }
            MSDiagMessage("gravity app started source=deviceMotion interval=0.033")
        } else {
            startAccelerometerFallback()
        }
    }

    private func startAccelerometerFallback() {
        guard requestedEnabled, manager.isAccelerometerAvailable else {
            MSDiagMessage("gravity app unavailable accelerometer=0")
            return
        }
        gravityEstimateReady = false
        manager.accelerometerUpdateInterval = 1.0 / 30.0
        manager.startAccelerometerUpdates(to: .main) { [weak self] sample, error in
            guard let self, self.requestedEnabled else { return }
            if let error {
                MSDiagMessage("gravity app accelerometer error=\(error.localizedDescription)")
                self.manager.stopAccelerometerUpdates()
                return
            }
            guard let sample else { return }
            let a = sample.acceleration
            let dt = self.sampleDeltaTime()
            let alpha = 1.0 - exp(-dt / 0.8)
            if !self.gravityEstimateReady {
                self.gravityX = a.x
                self.gravityY = a.y
                self.gravityZ = a.z
                self.gravityEstimateReady = true
            } else {
                self.gravityX += alpha * (a.x - self.gravityX)
                self.gravityY += alpha * (a.y - self.gravityY)
                self.gravityZ += alpha * (a.z - self.gravityZ)
            }
            self.apply(gravityX: self.gravityX, gravityY: self.gravityY,
                       userX: a.x - self.gravityX, userY: a.y - self.gravityY,
                       userZ: a.z - self.gravityZ, deltaTime: dt)
        }
        MSDiagMessage("gravity app started source=accelerometer interval=0.033")
    }

    private func sampleDeltaTime() -> Double {
        let now = CACurrentMediaTime()
        let dt = lastSampleTime > 0 ? min(0.2, max(0.001, now - lastSampleTime)) : 1.0 / 30.0
        lastSampleTime = now
        return dt
    }

    private func interfaceOrientation() -> Int32 {
        let scene = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first(where: { $0.activationState == .foregroundActive })
            ?? UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        return Int32(scene?.interfaceOrientation.rawValue ?? UIInterfaceOrientation.portrait.rawValue)
    }

    private func apply(gravityX: Double, gravityY: Double,
                       userX: Double, userY: Double, userZ: Double,
                       deltaTime suppliedDelta: Double? = nil) {
        let dt = suppliedDelta ?? sampleDeltaTime()
        let target = MiniSightGravityRollForDevice(gravityX, gravityY, interfaceOrientation())
        roll = MiniSightGravityFilterRoll(roll, target, dt)

        let magnitude = sqrt(userX * userX + userY * userY + userZ * userZ)
        if !shakeLatched && magnitude >= 0.75 {
            shakeLatched = true
            shakeDirection = abs(roll) >= 0.08 ? (roll >= 0 ? 1.0 : -1.0) : (userX >= 0 ? 1.0 : -1.0)
            shakeStrength = min(1.0, max(0.2, (magnitude - 0.35) / 1.5))
            shakeGeneration &+= 1
        } else if shakeLatched && magnitude <= 0.35 {
            shakeLatched = false
        }

        let now = CACurrentMediaTime()
        if now - lastDiagnosticTime >= 1.0 {
            lastDiagnosticTime = now
            MSDiagMessage(String(format: "gravity app sample orientation=%d gx=%.3f gy=%.3f roll=%.3f shakeG=%.3f", interfaceOrientation(), gravityX, gravityY, roll, magnitude))
        }
    }

    deinit { manager.stopDeviceMotionUpdates(); manager.stopAccelerometerUpdates() }
}

/// A zero-sized SwiftUI anchor owns a separate non-key pass-through pet window.
private struct MiniSightPetHost: UIViewRepresentable {
    let image: UIImage
    let displaySize: CGFloat
    let roll: Double
    let activityActive: Bool
    let gravityEnabled: Bool
    let shakeGeneration: Int
    let shakeDirection: Double
    let shakeStrength: Double
    let longPressEnabled: Bool
    @Binding var centerX: Double
    @Binding var centerY: Double
    let onSingleTap: () -> Void
    let onDoubleTap: () -> Void
    let onLongPress: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> UIView {
        let anchor = UIView(frame: CGRect(x: 0, y: 0, width: 1, height: 1))
        anchor.isUserInteractionEnabled = false
        context.coordinator.mount(image: image, size: displaySize)
        return anchor
    }

    func updateUIView(_ anchor: UIView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.update(image: image, size: displaySize, roll: roll,
                                   active: activityActive)
    }

    static func dismantleUIView(_ anchor: UIView, coordinator: Coordinator) {
        coordinator.teardown()
    }

    @MainActor
    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        var parent: MiniSightPetHost
        weak var host: MiniSightPassthroughView?
        weak var pet: MiniSightPetView?
        private var petWindow: UIWindow?
        private var panStart = CGPoint.zero
        private var handledShakeGeneration = 0

        init(_ parent: MiniSightPetHost) { self.parent = parent }

        func mount(image: UIImage, size: CGFloat) {
            guard let scene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive }) else { return }
            let window = UIWindow(windowScene: scene)
            window.frame = scene.coordinateSpace.bounds
            window.windowLevel = .normal + 1
            window.backgroundColor = .clear
            window.isOpaque = false
            let root = MiniSightPassthroughView(frame: window.bounds)
            root.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            root.normalizedCenter = CGPoint(x: parent.centerX, y: parent.centerY)
            let controller = UIViewController()
            controller.view = root
            window.rootViewController = controller
            self.petWindow = window
            self.host = root
            let pet = MiniSightPetView(sprite: image, displaySize: CGSize(width: size, height: size))
            handledShakeGeneration = parent.shakeGeneration
            pet.isUserInteractionEnabled = true
            pet.gravityEnabled = parent.gravityEnabled
            pet.longPressEnabled = parent.longPressEnabled
            pet.activityActive = parent.activityActive
            host.pet = pet
            host.addSubview(pet)
            self.pet = pet
            let single = UITapGestureRecognizer(target: self, action: #selector(singleTap))
            let double = UITapGestureRecognizer(target: self, action: #selector(doubleTap))
            double.numberOfTapsRequired = 2
            single.require(toFail: double)
            let longPress = UILongPressGestureRecognizer(target: self, action: #selector(longPress(_:)))
            longPress.minimumPressDuration = 0.8
            let pan = UIPanGestureRecognizer(target: self, action: #selector(pan(_:)))
            pan.delegate = self
            pet.addGestureRecognizer(single); pet.addGestureRecognizer(double)
            pet.addGestureRecognizer(longPress); pet.addGestureRecognizer(pan)
            pet.startPlaying()
            window.isHidden = false
        }

        func update(image: UIImage, size: CGFloat, roll: Double, active: Bool) {
            guard let host else { mount(image: image, size: size); return }
            guard let pet else { mount(image: image, size: size); return }
            if pet.frame.size != CGSize(width: size, height: size) {
                pet.bounds = CGRect(x: 0, y: 0, width: size, height: size)
            }
            pet.gravityEnabled = parent.gravityEnabled
            pet.longPressEnabled = parent.longPressEnabled
            pet.gravityRoll = roll
            pet.activityActive = active
            pet.reducedWork = ProcessInfo.processInfo.isLowPowerModeEnabled
            if parent.shakeGeneration != handledShakeGeneration {
                handledShakeGeneration = parent.shakeGeneration
                pet.triggerGravityImpulse(withDirection: CGFloat(parent.shakeDirection),
                                          strength: CGFloat(parent.shakeStrength))
            }
            host.setNeedsLayout()
            host.layoutIfNeeded()
        }

        @objc private func singleTap() { parent.onSingleTap() }
        @objc private func doubleTap() { parent.onDoubleTap() }
        @objc private func longPress(_ gesture: UILongPressGestureRecognizer) {
            guard gesture.state == .began, parent.longPressEnabled else { return }
            pet?.interactionActive = true
            parent.onLongPress()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak pet] in pet?.interactionActive = false }
        }
        @objc private func pan(_ gesture: UIPanGestureRecognizer) {
            guard let host, let pet else { return }
            switch gesture.state {
            case .began:
                panStart = pet.center
                pet.interactionActive = true
            case .changed:
                let delta = gesture.translation(in: host)
                let bounds = pet.centerBounds
                let x = min(bounds.maxX, max(bounds.minX, panStart.x + delta.x))
                let y = min(bounds.maxY, max(bounds.minY, panStart.y + delta.y))
                pet.center = CGPoint(x: x, y: y)
            case .ended, .cancelled, .failed:
                pet.interactionActive = false
                let width = max(host.bounds.width, 1), height = max(host.bounds.height, 1)
                parent.centerX = Double(pet.center.x / width)
                parent.centerY = Double(pet.center.y / height)
            default: break
            }
        }

        func teardown() {
            pet?.stopPlaying()
            pet = nil
            host?.pet = nil
            host = nil
            petWindow?.isHidden = true
            petWindow?.rootViewController = nil
            petWindow = nil
        }

        func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                               shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer) -> Bool { false }
    }
}

private final class MiniSightPassthroughView: UIView {
    weak var pet: MiniSightPetView?
    var normalizedCenter = CGPoint(x: 0.5, y: 0.52)
    private var didPlaceInitialCenter = false
    override func layoutSubviews() {
        super.layoutSubviews()
        guard let pet else { return }
        let body = pet.gravitySafeSize
        let left = safeAreaInsets.left + body.width / 2
        let right = bounds.width - safeAreaInsets.right - body.width / 2
        let top = safeAreaInsets.top + body.height / 2 + 24
        let bottom = bounds.height - safeAreaInsets.bottom - body.height / 2
        pet.centerBounds = CGRect(x: min(left, right), y: min(top, bottom),
                                  width: max(0, right - left), height: max(0, bottom - top))
        if !didPlaceInitialCenter {
            let target = CGPoint(x: bounds.width * min(1, max(0, normalizedCenter.x)),
                                 y: bounds.height * min(1, max(0, normalizedCenter.y)))
            let range = pet.centerBounds
            pet.center = CGPoint(x: min(range.maxX, max(range.minX, target.x)),
                                 y: min(range.maxY, max(range.minY, target.y)))
            didPlaceInitialCenter = true
        } else {
            pet.center = pet.center
        }
    }
    override func point(inside point: CGPoint, with event: UIEvent?) -> Bool {
        guard let pet else { return false }
        return pet.frame.insetBy(dx: -8, dy: -8).contains(point)
    }
    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
        guard point(inside: point, with: event), let pet else { return nil }
        return pet.hitTest(convert(point, to: pet), with: event) ?? pet
    }
}
