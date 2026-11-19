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

/// Low-cost rainbow wave shared by text and voice composer modes.
/// TimelineView redraws only this decorative Canvas, not the text input state.
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.34
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let colors: [Color] = [
        Color(red: 0.98, green: 0.32, blue: 0.49),
        Color(red: 1.00, green: 0.55, blue: 0.31),
        Color(red: 0.98, green: 0.78, blue: 0.28),
        Color(red: 0.30, green: 0.82, blue: 0.61),
        Color(red: 0.20, green: 0.73, blue: 0.93),
        Color(red: 0.48, green: 0.49, blue: 0.96),
        Color(red: 0.78, green: 0.40, blue: 0.91)
    ]

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let center = size.height * 0.5
                let scale = size.height * 0.38
                let count = max(32, min(120, Int(size.width / 4)))
                let phase = time * 0.34

                for band in colors.indices {
                    var path = Path()
                    for index in 0...count {
                        let x = size.width * CGFloat(index) / CGFloat(count)
                        let unit = Double(index) / Double(count)
                        let audio = sampledLevel(at: unit)
                        let drift = smoothNoise(position: unit * 5.0 + phase + Double(band) * 7.13) * 0.34
                            + smoothNoise(position: unit * 11.0 - phase * 0.63 + Double(band) * 3.71) * 0.13
                        let amplitude = (drift + Double(audio) * 0.52) * Double(scale)
                        let y = center + CGFloat(amplitude) + CGFloat(band - colors.count / 2) * 1.45
                        if index == 0 { path.move(to: CGPoint(x: x, y: y)) }
                        else { path.addLine(to: CGPoint(x: x, y: y)) }
                    }
                    context.stroke(path, with: .color(colors[band].opacity(opacity)),
                                   style: StrokeStyle(lineWidth: 2.1, lineCap: .round, lineJoin: .round))
                }
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
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
