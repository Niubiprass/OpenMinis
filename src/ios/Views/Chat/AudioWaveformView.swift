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

/// Dense square-particle cloud matching the reference composer wave.
/// The shared surface clips it; foreground controls naturally mask its peaks.
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.86
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let colorStops: [(Double, Double, Double)] = [
        (0.96, 0.48, 0.49), (0.88, 0.39, 0.72), (0.56, 0.43, 0.88),
        (0.34, 0.60, 0.94), (0.24, 0.79, 0.90), (0.32, 0.82, 0.68),
        (0.88, 0.77, 0.40)
    ]

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 18.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let root = size.height - 1.5
                let maxRise = min(size.height - 2, 54)
                let xStep: CGFloat = 2.35
                let yStep: CGFloat = 2.55
                let dot: CGFloat = 1.75
                let colorBucketCount = 28
                let columns = max(2, Int(ceil(size.width / xStep)))
                let rows = max(1, Int(maxRise / yStep))
                var particlePaths = Array(repeating: Path(), count: colorBucketCount)
                var highlightPaths = Array(repeating: Path(), count: colorBucketCount)

                let audio = sampledAudioEnergy()
                let centerA = 0.43 + 0.19 * sin(time * 0.43 + 0.35)
                let centerB = 0.73 + 0.12 * sin(time * 0.36 + 1.9)
                let centerC = 0.16 + 0.075 * cos(time * 0.51 + 0.8)
                let breath = 0.88 + 0.12 * sin(time * 1.35)

                for layer in 0..<2 {
                    let offset = layer == 0 ? 0.0 : xStep * 0.48
                    for column in 0..<columns {
                        let x = CGFloat(column) * xStep + offset
                        let u = min(1, max(0, Double(x / size.width)))
                        let edge = min(1.0, min(u / 0.022, (1 - u) / 0.022))
                        let broad = 0.20
                            + 0.92 * gaussian(u, centerA, 0.17)
                            + 0.83 * gaussian(u, centerB, 0.16)
                            + 0.66 * gaussian(u, centerC, 0.09)
                        let drift = 0.10 * (smoothNoise(position: u * 5.2 - time * 0.27) + 1)
                            + 0.05 * (smoothNoise(position: u * 10.6 + time * 0.19 + Double(layer) * 3.7) + 1)
                        let audioLift = Double(audio) * (0.42 + 0.58 * abs(sin(u * .pi * 2.4 + time * 1.8)))
                        let profile = min(1.0, max(0, (broad + drift + audioLift) * breath)) * edge
                        let peak = min(maxRise, max(yStep * 1.5, maxRise * CGFloat(profile)))
                        let bucket = min(colorBucketCount - 1, Int(u * Double(colorBucketCount)))

                        for row in 0...rows {
                            let distance = CGFloat(row) * yStep + CGFloat(layer) * 1.35
                            if distance > peak + 2 { continue }
                            let heightRatio = Double(distance / max(peak, 1))
                            let occupancy = min(1, max(0.16, 0.96 - heightRatio * 0.61))
                            let chance = hash(column: column + layer * 173, row: row + layer * 29)
                            if row > 1 && chance > occupancy { continue }

                            let ripple = sin(u * .pi * 7.5 - time * 1.35) * 1.25
                                + sin(u * .pi * 15.0 + time * 0.87 + Double(layer)) * 0.65
                            let y = root - distance + CGFloat(ripple)
                            let rect = CGRect(x: x - dot * 0.5, y: y - dot * 0.5, width: dot, height: dot)
                            particlePaths[bucket].addRect(rect)
                            if row < 4 && ((column + row + layer) % 4 == 0) {
                                let spark = CGRect(x: rect.midX - 0.55, y: rect.midY - 0.55, width: 1.1, height: 1.1)
                                highlightPaths[bucket].addRect(spark)
                            }
                        }
                    }
                }

                for index in 0..<colorBucketCount {
                    let unit = Double(index) / Double(colorBucketCount - 1)
                    let current = colorStop(at: unit + 0.003 * sin(time * 0.24 + unit * 3))
                    let color = Color(red: current.0, green: current.1, blue: current.2).opacity(opacity)
                    context.fill(particlePaths[index], with: .color(color))
                    context.fill(highlightPaths[index], with: .color(.white.opacity(opacity * 0.42)))
                }
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    private func gaussian(_ value: Double, _ center: Double, _ width: Double) -> Double {
        let distance = (value - center) / width
        return exp(-0.5 * distance * distance)
    }

    private func hash(column: Int, row: Int) -> Double {
        let raw = sin(Double(column) * 127.1 + Double(row) * 311.7) * 43758.5453123
        return raw - floor(raw)
    }

    private func smoothNoise(position: Double) -> Double {
        let cell = floor(position)
        let fraction = position - cell
        let eased = fraction * fraction * (3 - 2 * fraction)
        let a = hash(column: Int(cell), row: 911)
        let b = hash(column: Int(cell) + 1, row: 911)
        return (a + (b - a) * eased) * 2 - 1
    }

    private func sampledAudioEnergy() -> Double {
        guard !levels.isEmpty else { return 0 }
        let values = levels.suffix(12).map { min(1, max(0, Double($0))) }
        guard !values.isEmpty else { return 0 }
        let mean = values.reduce(0, +) / Double(values.count)
        return min(1, max(0, mean * 1.65))
    }

    private func colorStop(at position: Double) -> (Double, Double, Double) {
        let x = min(1, max(0, position)) * Double(colorStops.count - 1)
        let lower = min(colorStops.count - 2, Int(x))
        let fraction = x - Double(lower)
        let a = colorStops[lower]
        let b = colorStops[lower + 1]
        return (
            a.0 + (b.0 - a.0) * fraction,
            a.1 + (b.1 - a.1) * fraction,
            a.2 + (b.2 - a.2) * fraction
        )
    }
}
