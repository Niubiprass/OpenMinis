import SwiftUI

struct AudioWaveformView: View {
    let levels: [Float]

    private let barWidth: CGFloat = 3
    private let barSpacing: CGFloat = 3
    private let minHeight: CGFloat = 4
    private let maxHeight: CGFloat = 32

    var body: some View {
        GeometryReader { geo in
            let availableWidth = geo.size.width * 0.8
            let barCount = max(1, Int(availableWidth / (barWidth + barSpacing)))
            let waveWidth = CGFloat(barCount) * barWidth + CGFloat(barCount - 1) * barSpacing
            HStack(spacing: barSpacing) {
                ForEach(0..<barCount, id: \.self) { i in
                    let level = sampleLevel(at: i, barCount: barCount)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.accentColor)
                        .frame(width: barWidth, height: minHeight + CGFloat(level) * (maxHeight - minHeight))
                        .animation(.easeOut(duration: 0.1), value: level)
                }
            }
            .frame(width: waveWidth, height: maxHeight)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(height: maxHeight)
    }

    private func sampleLevel(at index: Int, barCount: Int) -> Float {
        guard !levels.isEmpty else { return 0 }
        let mapped = Int(Float(index) / Float(barCount) * Float(levels.count))
        let clamped = min(mapped, levels.count - 1)
        return levels[clamped]
    }
}

/// Animated, bottom-anchored spectral particles for the composer background.
/// Canvas owns the redraw; it never invalidates the text field or controls.
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.58
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let canvasHeight: CGFloat = 74
    private static let dotSize: CGFloat = 1.21
    private static let columnPitch: CGFloat = 1.62
    private static let rowPitch: CGFloat = 1.42
    private static let edgeInset: CGFloat = 1.15
    private static let maxRows = 18
    private static let maxColumns = 180
    private static let peakHeight: CGFloat = 24.3
    private static let transitionLife = 0.48
    @State private var transitionBeganAt: TimeInterval = -1
    var voiceActive: Bool = false

    private static let spectrum = Gradient(colors: [
        Color(red: 0.98, green: 0.27, blue: 0.51),
        Color(red: 1.00, green: 0.48, blue: 0.28),
        Color(red: 0.99, green: 0.76, blue: 0.27),
        Color(red: 0.35, green: 0.84, blue: 0.55),
        Color(red: 0.18, green: 0.76, blue: 0.94),
        Color(red: 0.38, green: 0.54, blue: 0.99),
        Color(red: 0.77, green: 0.39, blue: 0.94)
    ])

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let baseline = size.height - Self.dotSize * 0.5
                let columns = columnCount(in: size.width)
                let motionTime = reduceMotion ? 0 : time
                let paletteTravel = CGFloat(sin(motionTime * 0.10)) * size.width * 0.065
                let gradient = GraphicsContext.Shading.linearGradient(
                    Self.spectrum,
                    startPoint: CGPoint(x: size.width * 0.18 - paletteTravel, y: 0),
                    endPoint: CGPoint(x: size.width * 1.18 - paletteTravel, y: 0)
                )

                var ridge = Path()
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let audio = reduceMotion ? 0 : sampledLevel(at: unit)
                    let height = waveHeight(at: unit, time: time, audio: audio)
                    let point = CGPoint(x: columnCenter(at: unit, width: size.width),
                                        y: baseline - CGFloat(height))
                    if index == 0 { ridge.move(to: point) }
                    else { ridge.addLine(to: point) }
                }

                context.drawLayer { glow in
                    glow.addFilter(.blur(radius: 5.0))
                    glow.opacity = opacity * 0.52
                    glow.stroke(ridge, with: gradient,
                                style: StrokeStyle(lineWidth: 5.0, lineCap: .round, lineJoin: .round))
                }
                context.stroke(ridge, with: .color(Color.white.opacity(opacity * 0.17)),
                               style: StrokeStyle(lineWidth: 0.7, lineCap: .round, lineJoin: .round))

                var row0 = Path()
                var row1 = Path()
                var row2 = Path()
                var row3 = Path()
                var row4 = Path()
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let audio = reduceMotion ? 0 : sampledLevel(at: unit)
                    let height = waveHeight(at: unit, time: time, audio: audio)
                    let rows = height > 0 ? rowCount(for: height) : 0
                    let baseX = columnCenter(at: unit, width: size.width)
                    for row in 0..<rows {
                        let remainder = height - Double(row) * Double(Self.rowPitch)
                        let topScale = row == rows - 1 ? min(1, max(0.58, remainder / Double(Self.rowPitch))) : 1
                        let jitter = smoothNoise(position: Double(index) * 0.73 + time * 0.24 + Double(row) * 4.7)
                        let x = baseX + CGFloat(jitter) * 0.70
                        let yNoise = smoothNoise(position: unit * 12.0 + time * 0.28 + Double(row) * 6.1)
                        let y = min(baseline, max(0, baseline - CGFloat(row) * Self.rowPitch + CGFloat(yNoise) * 0.48))
                        let shimmer = 0.92 + 0.08 * (0.5 + 0.5 * sin(time * 2.1 + Double(index) * 1.7 + Double(row)))
                        // Grain: individual beads differ in size, which is what
                        // gives the reference its speckled look rather than a grid.
                        let grain = 0.72 + 0.55 * (0.5 + 0.5 * smoothNoise(position: Double(index) * 2.31 + Double(row) * 5.17))
                        let diameter = Self.dotSize * CGFloat(shimmer * topScale * grain)
                        let dot = CGRect(x: x - diameter * 0.5, y: y - diameter * 0.5,
                                         width: diameter, height: diameter)
                        switch row {
                        case 0: row0.addRect(dot)
                        case 1: row1.addRect(dot)
                        case 2: row2.addRect(dot)
                        case 3: row3.addRect(dot)
                        default: row4.addRect(dot)
                        }
                    }
                }
                paint(row0, row: 0, shading: gradient, in: context)
                paint(row1, row: 1, shading: gradient, in: context)
                paint(row2, row: 2, shading: gradient, in: context)
                paint(row3, row: 3, shading: gradient, in: context)
                paint(row4, row: 4, shading: gradient, in: context)

                if !reduceMotion {
                    let age = time - transitionBeganAt
                    if age >= 0 && age < Self.transitionLife {
                        let progress = age / Self.transitionLife
                        var trace = Path()
                        for streak in 0..<3 {
                            let unit = min(0.94, max(0.06, 0.18 + progress * 0.62 + Double(streak) * 0.035))
                            let x = columnCenter(at: unit, width: size.width)
                            let height = waveHeight(at: unit, time: time, audio: 0)
                            let y = baseline - CGFloat(height) - CGFloat(progress * 3.5)
                            let length = CGFloat(5.0 + Double(streak) * 1.2)
                            trace.move(to: CGPoint(x: x - length, y: y + 2.0))
                            trace.addQuadCurve(to: CGPoint(x: x + 1.5, y: y),
                                               control: CGPoint(x: x - 1.5, y: y - 3.2))
                        }
                        context.drawLayer { glow in
                            glow.addFilter(.blur(radius: 3.0))
                            glow.opacity = opacity * (1.0 - progress) * 0.68
                            glow.stroke(trace, with: gradient,
                                        style: StrokeStyle(lineWidth: 2.8, lineCap: .round))
                        }
                        var traceContext = context
                        traceContext.opacity = opacity * (1.0 - progress)
                        traceContext.stroke(trace, with: gradient,
                                            style: StrokeStyle(lineWidth: 0.9, lineCap: .round))
                    }
                }
            }
            .onChange(of: voiceActive) { _ in
                guard !reduceMotion else { return }
                transitionBeganAt = timeline.date.timeIntervalSinceReferenceDate
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    private func paint(_ path: Path, row: Int, shading: GraphicsContext.Shading,
                       in context: GraphicsContext) {
        guard !path.isEmpty else { return }
        var layer = context
        layer.opacity = opacity * (row == 0 ? 0.92 : max(0.40, 1.0 - Double(row) * 0.035))
        layer.fill(path, with: shading)
    }

    private func columnCount(in width: CGFloat) -> Int {
        return max(2, min(Self.maxColumns, Int(floor((width - Self.edgeInset * 2) / Self.columnPitch)) + 1))
    }

    private func columnCenter(at unit: Double, width: CGFloat) -> CGFloat {
        return Self.edgeInset + (width - Self.edgeInset * 2) * CGFloat(unit)
    }

    private func rowCount(for height: Double) -> Int {
        return min(Self.maxRows, max(1, Int(ceil(height / Double(Self.rowPitch)))))
    }

    // Silhouette measured from the reference frame: a broad mound peaking at
    // ~55% width with a slightly flattened crown, tapering to nothing at both
    // edges. Values are the normalized height sampled across the composer.
    private static let profile: [Double] = [0.023, 0.018, 0.122, 0.236, 0.400, 0.544,
                                            0.640, 0.749, 0.855, 0.924, 0.898, 0.833,
                                            0.756, 0.656, 0.518, 0.269, 0.107, 0.056,
                                            0.028, 0.051, 0.000]

    private func profileUnit(_ unit: Double) -> Double {
        let inside = unit > 0 && unit < 1
        let scaled = inside ? unit * Double(Self.profile.count - 1) : 0
        let index = Int(scaled)
        let valid = inside && index < Self.profile.count - 1
        let frac = scaled - Double(index)
        let lower = valid ? Self.profile[index] : 0
        let upper = valid ? Self.profile[index + 1] : 0
        return lower * (1 - frac) + upper * frac
    }

    private func waveHeight(at unit: Double, time: Double, audio: Double) -> Double {
        // The reference composer wave undulates by itself; it never reads the
        // microphone. The whole silhouette drifts slowly so it keeps moving,
        // and each column gets a small breathing offset.
        let drift = 0.012 * sin(time * 0.6)
        let shape = profileUnit(unit + drift)
        let breath = 0.97 + 0.06 * smoothNoise(position: unit * 7.0 + time * 0.8)
        return shape > 0.001 ? Double(Self.peakHeight) * shape * breath : 0
    }

    private func smoothNoise(position: Double) -> Double {
        let cell = floor(position)
        let fraction = position - cell
        let eased = fraction * fraction * (3.0 - 2.0 * fraction)
        let lower = latticeNoise(cell)
        let upper = latticeNoise(cell + 1.0)
        return lower + (upper - lower) * eased
    }

    private func latticeNoise(_ value: Double) -> Double {
        let seed = sin(value * 127.1 + 311.7) * 43758.5453123
        return (seed - floor(seed)) * 2.0 - 1.0
    }

    private func sampledLevel(at position: Double) -> Double {
        guard !levels.isEmpty else { return 0 }
        let index = min(levels.count - 1, max(0, Int(position * Double(levels.count))))
        return min(1, max(0, Double(levels[index])))
    }
}
