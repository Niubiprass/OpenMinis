import SwiftUI
import QuartzCore
import Foundation

// Local adaptation target: composer-beam-mock.mp4, 2026-11-23.
// This numeric model is the one used by that preview, NOT the author's original
// implementation and NOT a claim that Pillow and SwiftUI render identical pixels.
// The old ComposerRainbowWave remains untouched for baseline/rollback comparison.
enum ComposerFlowModel {
    static let rowPitch = 2.35
    static let primaryPitch = 4.60
    static let maxColumns = 256
    static let maxRows = 11
    static let peak = 26.0
    static let profile: [Double] = [0.023, 0.018, 0.122, 0.236, 0.400, 0.544,
        0.640, 0.749, 0.855, 0.924, 0.898, 0.833, 0.756, 0.656, 0.518,
        0.269, 0.107, 0.056, 0.028, 0.051, 0.000]
    static let phaseStops: [Double] = [0, 0.12, 0.24, 0.32, 0.42, 0.50, 0.58, 0.70, 0.80, 0.90, 1]
    static let hueStops: [Double] = [0.94, 0.98, 0.09, 0.12, 0.56, 0.62, 0.49, 0.55, 0.88, 0.96, 1.02]

    struct RGB {
        var r: Double
        var g: Double
        var b: Double
        var color: Color { Color(.sRGB, red: r, green: g, blue: b, opacity: 1) }
        func lifted(_ amount: Double) -> RGB {
            RGB(r: r + (1 - r) * amount, g: g + (1 - g) * amount, b: b + (1 - b) * amount)
        }
        func scaled(_ amount: Double) -> RGB { RGB(r: r * amount, g: g * amount, b: b * amount) }
        func quantized() -> RGB {
            func byte(_ value: Double) -> Double { floor(min(255, max(0, value * 255))) / 255 }
            return RGB(r: byte(r), g: byte(g), b: byte(b))
        }
    }

    struct Dot {
        var x: Double
        var y: Double
        var diameter: Double
        var rgb: RGB
        var alpha: Double
        var light: Double
        var vertical: Double
    }

    static func noise(_ position: Double) -> Double {
        let cell = floor(position)
        let f = position - cell
        let eased = f * f * (3 - 2 * f)
        func lattice(_ value: Double) -> Double {
            let seed = sin(value * 127.1 + 311.7) * 43758.5453123
            return (seed - floor(seed)) * 2 - 1
        }
        let lower = lattice(cell)
        return lower + (lattice(cell + 1) - lower) * eased
    }

    static func interpolated(_ position: Double, stops: [Double], values: [Double]) -> Double {
        guard stops.count > 1, stops.count == values.count else { return 0 }
        if position <= stops[0] { return values[0] }
        for index in 1..<stops.count where position <= stops[index] {
            let f = (position - stops[index - 1]) / (stops[index] - stops[index - 1])
            return values[index - 1] * (1 - f) + values[index] * f
        }
        return values[values.count - 1]
    }

    static func height(unit: Double, time: Double) -> Double {
        let drift = 0.062 * sin(2 * .pi * 0.30 * time) + 0.022 * sin(2 * .pi * 0.64 * time + 1.1)
        let shifted = min(0.999, max(0.001, unit + drift))
        let position = shifted * Double(profile.count - 1)
        let index = min(profile.count - 2, Int(position))
        let f = position - Double(index)
        let base = profile[index] * (1 - f) + profile[index + 1] * f
        let envelope = max(base, 0.48 * exp(-pow((shifted - 0.75) / 0.14, 2)))
        let amount = 0.29 * sin(2 * .pi * (unit - 0.5 * time))
            + 0.14 * sin(2 * .pi * (2.2 * unit + 0.47 * time))
            + 0.07 * sin(2 * .pi * (4 * unit - 0.98 * time))
        return peak * envelope * (1 + amount * min(1, min(unit, 1 - unit) / 0.16))
    }

    // Frozen coefficients actually used to generate the approved mock. A local
    // fit to a short excerpt, not evidence of long-period reference behaviour.
    static func ridgeSeparation(_ time: Double) -> Double {
        0.15589688262518098 + 0.02770967193956731
            * cos(2 * .pi * 0.5105158859348189 * time - 0.49636529839549937)
    }

    static func light(unit: Double, row: Int, time: Double) -> Double {
        let r = Double(row)
        let separation = ridgeSeparation(time)
        let tilt = 0.024 * (r - 1)
        let left = 0.4979440789473883 - separation + tilt
        let right = 0.4979440789473883 + separation - tilt
        let first = exp(-pow((unit - left) / 0.043, 2))
        let second = exp(-pow((unit - right) / 0.050, 2))
        let ridge = max(first, second) * (0.58 + 0.42 * exp(-pow((r - 3) / 2.8, 2)))
        let wave = pow(0.5 + 0.5 * sin(2 * .pi * (3.2 * unit - 0.53 * time) + r * 0.48), 4)
        return min(1, ridge * 0.86 + wave * 0.32 * exp(-pow((r - 3) / 2.4, 2)))
    }

    static func rgb(hue: Double, saturation: Double, value: Double) -> RGB {
        let h = (hue - floor(hue)) * 6
        let sector = Int(h) % 6
        let f = h - floor(h)
        let p = value * (1 - saturation)
        let q = value * (1 - saturation * f)
        let t = value * (1 - saturation * (1 - f))
        switch sector {
        case 0: return RGB(r: value, g: t, b: p)
        case 1: return RGB(r: q, g: value, b: p)
        case 2: return RGB(r: p, g: value, b: t)
        case 3: return RGB(r: p, g: q, b: value)
        case 4: return RGB(r: t, g: p, b: value)
        default: return RGB(r: value, g: p, b: q)
        }
    }

    static func dots(width: Double, baseline: Double, time: Double) -> [Dot] {
        guard width.isFinite, width > 0, baseline.isFinite, time.isFinite else { return [] }
        let count = max(2, Int(min(Double(maxColumns), width / (primaryPitch * 0.5))))
        var result: [Dot] = []
        result.reserveCapacity(count * 6)
        for index in 0..<count {
            let unit = (Double(index) + 0.5) / Double(count)
            let h = height(unit: unit, time: time)
            let rows = max(1, min(maxRows, Int(ceil(h / rowPitch))))
            for row in 0..<rows {
                let primary = (index + row) % 2 == 1
                let r = Double(row)
                let vertical = r / Double(max(1, rows - 1))
                let sp = light(unit: unit, row: row, time: time)
                if !primary {
                    let gate = 0.5 + 0.5 * noise(Double(index) * 3.1 + r * 7.3 + time * 0.9)
                    if row > 3 || gate > (0.30 + 0.52 * sp) * min(1, h / 16) { continue }
                }
                let base = 0.64 - 0.12 * vertical
                let grain = 0.86 + 0.14 * (0.5 + 0.5 * noise(Double(index) * 1.7 + r * 3.9 + time * 0.7))
                let value = min(1, (base + (1 - base) * (0.92 * sp)) * grain)
                let saturation = max(0.22, (0.78 - 0.40 * vertical) * (1 - 0.40 * sp))
                var phase = unit * 1.06 - time * 0.115 + 0.015 * sin(2 * .pi * (2 * unit - 0.3 * time))
                phase -= floor(phase)
                var hue = interpolated(phase, stops: phaseStops, values: hueStops)
                hue -= floor(hue)
                let top = max(0, (vertical - 0.65) / 0.35) * min(1, h / 19)
                let rawDelta = 0.96 - hue + 0.5
                let delta = rawDelta - floor(rawDelta) - 0.5
                hue += delta * top * 0.82
                let color = rgb(hue: hue, saturation: saturation, value: value)
                var diameter = 2.05 * 0.88 * (0.82 + 0.24 * (0.5 + 0.5 * noise(Double(index) * 2.31 + r * 5.17))) * (1 + 0.12 * sp)
                if !primary { diameter *= 0.88 }
                let edge = min(1, max(0, (h - r * rowPitch) / 2))
                result.append(Dot(x: unit * width, y: baseline - r * rowPitch, diameter: diameter,
                                  rgb: color, alpha: row == rows - 1 ? edge : 1, light: sp, vertical: vertical))
            }
        }
        return result
    }
}

// A reference object, deliberately not ObservableObject: advancing a decorative
// Canvas must not publish an update to the text input's view tree every frame.
final class ComposerEffectClock {
    private(set) var elapsed: TimeInterval = 0
    private var last: TimeInterval?

    func resetAnchor() { last = nil }

    func advance(running: Bool, timestamp: TimeInterval = CACurrentMediaTime()) -> TimeInterval {
        guard running, timestamp.isFinite else { last = nil; return elapsed }
        if let previous = last { elapsed += max(0, timestamp - previous) }
        last = timestamp
        return elapsed
    }
}

// Three sibling canvases consume the SAME numeric frame. Keep one bounded,
// per-view cache; no timer, file I/O or per-point recomputation in each pass.
final class ComposerFlowFrameCache {
    private let lock = NSLock()
    private var size = CGSize.zero
    private var time: Double = -1
    private var stored: [ComposerFlowModel.Dot] = []

    func dots(size: CGSize, time: Double) -> [ComposerFlowModel.Dot] {
        lock.lock(); defer { lock.unlock() }
        if self.size == size && self.time == time { return stored }
        self.size = size; self.time = time
        stored = ComposerFlowModel.dots(width: Double(size.width), baseline: Double(size.height) - 2, time: time)
        return stored
    }
}

/// Per-dot light, not colour buckets with one fixed intensity for the whole wave.
/// iOS15 Canvas is used instead of iOS17 SwiftUI shaders. Native rendering still
/// needs Xcode/device verification; the preview's PIL compositing is not identical.
struct ComposerFlowingWave: View {
    var levels: [Float] = []
    var voiceActive: Bool = false
    @State private var frameCache = ComposerFlowFrameCache()
    static let canvasHeight: CGFloat = 74
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var visible = false
    @State private var clock = ComposerEffectClock()

    private var running: Bool { visible && scenePhase == .active && !reduceMotion }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !running)) { _ in
            let time = reduceMotion ? 0 : clock.advance(running: running)
            // Separate siblings preserve the target's compositing order:
            // background + wash -> normal-alpha squares -> added sheen.
            // Apply additive blending at the VIEW boundary, not inside one
            // transparent Canvas, where an opaque black buffer could obscure
            // the real material. No fixed dark surface is painted behind it.
            ZStack {
                Canvas(opaque: false, colorMode: .nonLinear) { wash, size in
                    let dots = frameCache.dots(size: size, time: time)
                    wash.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black))
                    for dot in dots {
                        let k = (0.14 + 0.22 * dot.light) * (1 - 0.30 * dot.vertical) * dot.alpha
                        let rect = CGRect(x: CGFloat(dot.x) - 2.5, y: CGFloat(dot.y) - 2.5, width: 5, height: 5)
                        wash.fill(Path(ellipseIn: rect), with: .color(dot.rgb.scaled(k).quantized().color))
                    }
                }
                .blur(radius: 2)
                .blendMode(.plusLighter)
                Canvas(opaque: false, colorMode: .nonLinear) { context, size in
                    let dots = frameCache.dots(size: size, time: time)
                    for dot in dots {
                        var point = context
                        point.opacity = floor(dot.alpha * 255) / 255
                        let rect = CGRect(x: CGFloat(dot.x - dot.diameter * 0.5), y: CGFloat(dot.y - dot.diameter * 0.5),
                                          width: CGFloat(dot.diameter), height: CGFloat(dot.diameter))
                        point.fill(Path(rect), with: .color(dot.rgb.quantized().color))
                    }
                }
                Canvas(opaque: false, colorMode: .nonLinear) { sheen, size in
                    let dots = frameCache.dots(size: size, time: time)
                    sheen.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black))
                    for dot in dots where dot.light > 0.22 {
                        let k = 0.22 * dot.light * dot.alpha
                        let radius = dot.diameter * 0.70
                        let rect = CGRect(x: CGFloat(dot.x - radius), y: CGFloat(dot.y - radius), width: CGFloat(radius * 2), height: CGFloat(radius * 2))
                        sheen.fill(Path(rect), with: .color(dot.rgb.lifted(0.13).scaled(k).quantized().color))
                    }
                }
                .blur(radius: 0.50)
                .blendMode(.plusLighter)
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
        .onAppear { clock.resetAnchor(); visible = true }
        .onDisappear { visible = false; clock.resetAnchor() }
        .onChange(of: scenePhase) { _ in clock.resetAnchor() }
        .onChange(of: reduceMotion) { _ in clock.resetAnchor() }
    }
}

// BorderBeam palette, bell envelope and orbit/glow design adapted from
// https://github.com/ismnoiet/border-beam-ios (MIT, copyright2026 ismnoiet).
// Full licence is bundled in BorderBeam-LICENSE.txt. iOS17 colorEffect is NOT
// linked: iOS15 Canvas samples the same continuous20pt path as the actual clip.
enum ComposerBeamModel {
    static let lap = 2.4
    static let handover = 0.6
    static let arc = 0.36
    static let spectrum: [ComposerFlowModel.RGB] = [
        .init(r: 0.26, g: 0.50, b: 0.96), .init(r: 0.25, g: 0.70, b: 0.90),
        .init(r: 0.25, g: 0.82, b: 0.85), .init(r: 0.25, g: 0.78, b: 0.40),
        .init(r: 0.98, g: 0.74, b: 0.20), .init(r: 0.98, g: 0.52, b: 0.22),
        .init(r: 0.92, g: 0.28, b: 0.25)]
    static let neon: [ComposerFlowModel.RGB] = [
        .init(r: 0, g: 0.90, b: 1), .init(r: 0.30, g: 0.40, b: 1),
        .init(r: 0.85, g: 0.20, b: 1), .init(r: 1, g: 0.20, b: 0.60)]

    static func smoothstep(_ value: Double) -> Double {
        let x = min(1, max(0, value))
        return x * x * (3 - 2 * x)
    }

    // Full lap, then swap palette/direction through a short crossfade. Each
    // shape's position keeps moving continuously during handover. There are not
    // two permanently stacked rings; their weights always add up to one.
    static func spectrumWeight(_ elapsed: Double) -> Double {
        guard elapsed.isFinite else { return 1 }
        // Start with a complete spectrum lap. Later spectrum laps fade in
        // from neon at the same seam; the inner wave's time never resets.
        if elapsed < lap { return 1 }
        let cycle = elapsed / lap
        let position = cycle - floor(cycle / 2) * 2
        let blend = handover / lap
        if position < blend { return smoothstep(position / blend) }
        if position < 1 { return 1 }
        if position < 1 + blend { return 1 - smoothstep((position - 1) / blend) }
        return 0
    }

    static func phase(_ elapsed: Double) -> Double {
        let phase = 0.47 + elapsed / lap
        return phase - floor(phase)
    }

    static func palette(_ spectrum: Bool, position: Double) -> ComposerFlowModel.RGB {
        let colors = spectrum ? self.spectrum : neon
        let p = min(1, max(0, position)) * Double(colors.count - 1)
        let index = min(colors.count - 2, Int(p))
        let f = p - Double(index)
        let a = colors[index], b = colors[index + 1]
        return .init(r: a.r * (1 - f) + b.r * f, g: a.g * (1 - f) + b.g * f, b: a.b * (1 - f) + b.b * f)
    }
}

// Cache only per-view immutable geometry. No global mutable SwiftUI state and no
// GeometryReader preference writes/rebuild of the chat input on animation ticks.
final class ComposerBeamTrack {
    private var cachedSize = CGSize.zero
    private var points: [CGPoint] = []
    private var distances: [CGFloat] = []
    private(set) var length: CGFloat = 0

    func prepare(size: CGSize) {
        guard size != cachedSize || points.isEmpty else { return }
        cachedSize = size
        points.removeAll(keepingCapacity: true)
        distances.removeAll(keepingCapacity: true)
        length = 0
        guard size.width.isFinite, size.height.isFinite, size.width > 2, size.height > 2 else { return }
        let path = RoundedRectangle(cornerRadius: 20, style: .continuous)
            .path(in: CGRect(origin: .zero, size: size))
        var contour: [CGPoint] = []
        var current = CGPoint.zero
        var start = CGPoint.zero
        func append(_ p: CGPoint) { contour.append(p); current = p }
        // Flatten SwiftUI's actual continuous path, not a circular-corner
        // approximation. All inputs are clamped to make tiny views harmless.
        path.forEach { element in
            switch element {
            case .move(to: let p): start = p; append(p)
            case .line(to: let p): append(p)
            case .quadCurve(to: let p, control: let c):
                let from = current
                for step in 1...24 {
                    let t = CGFloat(step) / 24, u = 1 - t
                    append(CGPoint(x: u * u * from.x + 2 * u * t * c.x + t * t * p.x,
                                   y: u * u * from.y + 2 * u * t * c.y + t * t * p.y))
                }
            case .curve(to: let p, control1: let a, control2: let b):
                let from = current
                for step in 1...32 {
                    let t = CGFloat(step) / 32, u = 1 - t
                    append(CGPoint(x: u * u * u * from.x + 3 * u * u * t * a.x + 3 * u * t * t * b.x + t * t * t * p.x,
                                   y: u * u * u * from.y + 3 * u * u * t * a.y + 3 * u * t * t * b.y + t * t * t * p.y))
                }
            case .closeSubpath: append(start)
            }
        }
        guard contour.count > 2 else { return }
        if contour.first == contour.last { contour.removeLast() }
        // Positive signed area is clockwise in UIKit's downward y coordinates.
        var area: CGFloat = 0
        for i in contour.indices {
            let next = contour[(i + 1) % contour.count]
            area += contour[i].x * next.y - next.x * contour[i].y
        }
        if area < 0 { contour.reverse() }
        // Stable seam at the right edge. The curve remains closed when a beam
        // wraps through it; no nearest-edge fan or rotating square gradient.
        let target = CGPoint(x: size.width, y: size.height * 0.5)
        var seamIndex = 0
        var seamPoint = contour[0]
        var nearest = CGFloat.greatestFiniteMagnitude
        for i in contour.indices {
            let a = contour[i], b = contour[(i + 1) % contour.count]
            let dx = b.x - a.x, dy = b.y - a.y
            let square = dx * dx + dy * dy
            let t = square > 0 ? min(1, max(0, ((target.x - a.x) * dx + (target.y - a.y) * dy) / square)) : 0
            let p = CGPoint(x: a.x + t * dx, y: a.y + t * dy)
            let distance = hypot(p.x - target.x, p.y - target.y)
            if distance < nearest { nearest = distance; seamIndex = i; seamPoint = p }
        }
        let next = (seamIndex + 1) % contour.count
        contour = [seamPoint] + Array(contour[next...]) + Array(contour[..<next]) + [seamPoint]
        points = [contour[0]]; distances = [0]
        for p in contour.dropFirst() {
            guard let last = points.last else { break }
            let distance = hypot(p.x - last.x, p.y - last.y)
            guard distance > 0.0001 else { continue }
            length += distance; points.append(p); distances.append(length)
        }
    }

    func point(at fraction: Double) -> CGPoint {
        guard points.count > 1, length > 0, fraction.isFinite else { return .zero }
        let wrapped = fraction - floor(fraction)
        let target = CGFloat(wrapped) * length
        var low = 0, high = distances.count - 1
        while low + 1 < high {
            let mid = (low + high) / 2
            if distances[mid] < target { low = mid } else { high = mid }
        }
        let span = distances[high] - distances[low]
        let t = span > 0 ? (target - distances[low]) / span : 0
        return CGPoint(x: points[low].x + (points[high].x - points[low].x) * t,
                       y: points[low].y + (points[high].y - points[low].y) * t)
    }
}

struct ComposerBorderBeam: View {
    var active = true
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @State private var visible = false
    @State private var clock = ComposerEffectClock()
    @State private var track = ComposerBeamTrack()

    private var running: Bool { active && visible && scenePhase == .active && !reduceMotion }
    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: 20, style: .continuous) }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !running)) { _ in
            Canvas(opaque: false, colorMode: .nonLinear) { context, size in
                // Context warnings own the wall immediately; they remain above
                // this overlay and the internal wave is not hidden with it.
                guard active else { return }
                track.prepare(size: size)
                guard track.length > 1 else { return }
                let elapsed = reduceMotion ? 0 : clock.advance(running: running)
                let phase = ComposerBeamModel.phase(elapsed)
                let mix = ComposerBeamModel.spectrumWeight(elapsed)
                context.clip(to: shape.path(in: CGRect(origin: .zero, size: size)))
                if mix > 0.0001 {
                    drawBeam(context: context, phase: phase, spectrum: true, weight: mix)
                }
                if mix < 0.9999 {
                    drawBeam(context: context, phase: phase, spectrum: false, weight: 1 - mix)
                }
            }
        }
        .clipShape(shape)
        .accessibilityHidden(true)
        .allowsHitTesting(false)
        .onAppear { clock.resetAnchor(); visible = true }
        .onDisappear { visible = false; clock.resetAnchor() }
        .onChange(of: active) { _ in clock.resetAnchor() }
        .onChange(of: scenePhase) { _ in clock.resetAnchor() }
        .onChange(of: reduceMotion) { _ in clock.resetAnchor() }
    }

    private func drawBeam(context: GraphicsContext, phase: Double, spectrum: Bool, weight: Double) {
        let direction = spectrum ? 1.0 : -1.0
        let arc = ComposerBeamModel.arc
        // Same overlapping-Gaussian idea as upstream orbitGlowBlobs; gradients
        // replace the iOS17 shader. Keep a single shape clip outside all passes.
        let samples = 24
        let delta = Double(track.length) * arc / Double(samples)
        let sigma = max(14.0, delta * 0.8)
        let normalization = delta / (sigma * 2.50663)
        for index in 0..<samples {
            let t = (Double(index) + 0.5) / Double(samples)
            let center = track.point(at: 1 - arc + t * arc + direction * phase)
            let rgb = ComposerBeamModel.palette(spectrum, position: t)
            let gain = 0.55 * normalization * pow(sin(.pi * t), 1.6) * weight
            // Exact Gaussian samples as a small radial LUT. Full per-fragment
            // shader saturation/overlap remains a native visual verification item.
            let stops = stride(from: 0.0, through: 1.0, by: 0.125).map { radius in
                Gradient.Stop(color: rgb.color.opacity(gain * exp(-4.5 * radius * radius)),
                              location: CGFloat(radius))
            }
            let radius = CGFloat(sigma * 3)
            let rect = CGRect(x: center.x - radius, y: center.y - radius,
                              width: radius * 2, height: radius * 2)
            var glow = context
            glow.blendMode = colorScheme == .dark ? .plusLighter : .normal
            glow.fill(Path(ellipseIn: rect),
                      with: .radialGradient(Gradient(stops: stops), center: center,
                                            startRadius: 0, endRadius: radius))
        }
        // Fine coloured edge plus a tight halo; no rotating rectangle gradient,
        // no enlarged content frame or padding/hit-test changes.
        let segments = 96
        context.drawLayer { halo in
            halo.addFilter(.blur(radius: 0.70))
            for index in 0..<segments {
                let t0 = Double(index) / Double(segments)
                let t1 = Double(index + 1) / Double(segments)
                let t = (t0 + t1) * 0.5
                var path = Path()
                path.move(to: track.point(at: 1 - arc + t0 * arc + direction * phase))
                path.addLine(to: track.point(at: 1 - arc + t1 * arc + direction * phase))
                let color = ComposerBeamModel.palette(spectrum, position: t).color
                let gain = weight * 0.60 * pow(sin(.pi * t), 1.2)
                halo.stroke(path, with: .color(color.opacity(gain)),
                            style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
            }
        }
        for index in 0..<segments {
            let t0 = Double(index) / Double(segments)
            let t1 = Double(index + 1) / Double(segments)
            let t = (t0 + t1) * 0.5
            var path = Path()
            path.move(to: track.point(at: 1 - arc + t0 * arc + direction * phase))
            path.addLine(to: track.point(at: 1 - arc + t1 * arc + direction * phase))
            let color = ComposerBeamModel.palette(spectrum, position: t).color
            let gain = weight * pow(sin(.pi * t), 1.2)
            context.stroke(path, with: .color(color.opacity(gain)),
                           style: StrokeStyle(lineWidth: 2.0, lineCap: .round))
        }
    }
}
