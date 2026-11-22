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

/// Single-layer square wave based on 62657c0's separated, bottom-anchored blocks.
/// Only the crests reach five rows; valleys stay low instead of filling a carpet.
/// TimelineView redraws this decorative Canvas, never the text input state.
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.58
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    // Points, not pixels. A fifth row adds height, not more/smaller particles.
    static let canvasHeight: CGFloat = 42
    // The wave stays bottom-anchored. The additional canvas above is an
    // effects-only flight corridor, not extra rows or bottom padding.
    private static let squareSize: CGFloat = 3
    private static let columnPitch: CGFloat = 6
    private static let rowPitch: CGFloat = 5.5
    private static let edgeInset: CGFloat = 0.75
    private static let maxRows = 5
    private static let movingSparkEmitters = 8
    private static let sparkLife = 0.72
    private static let sparkMaxRise: CGFloat = 15.0
    @State private var transitionBeganAt: TimeInterval = -10
    var voiceActive: Bool = false

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
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let columns = columnCount(in: size.width)

                var ridge = Path()
                var centers: [CGFloat] = []
                var profiles: [Double] = []
                centers.reserveCapacity(columns); profiles.reserveCapacity(columns)
                var peakUnits: [Double] = []
                peakUnits.reserveCapacity(8)
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let x = columnCenter(at: unit, width: size.width)
                    let audio = reduceMotion ? 0 : sampledLevel(at: unit)
                    let profile = waveProfile(at: unit, time: time, audio: audio)
                    let rows = rowCount(for: profile)
                    let crest = rowCenter(at: rows - 1, height: size.height)
                    profiles.append(profile)
                    centers.append(crest)
                    if index == 0 { ridge.move(to: CGPoint(x: x, y: crest)) }
                    else { ridge.addLine(to: CGPoint(x: x, y: crest)) }
                }
                if columns > 2 {
                    for index in 1..<(columns - 1) where profiles[index] > 0.62 &&
                        profiles[index] >= profiles[index - 1] && profiles[index] > profiles[index + 1] {
                        if peakUnits.last.map({ Double(index) / Double(columns - 1) - $0 > 0.08 }) ?? true {
                            peakUnits.append(Double(index) / Double(columns - 1))
                        }
                    }
                }
                // If the smooth contour has no single-column local maximum,
                // sample the high envelope across the whole width so a broad
                // rounded crest still emits a small moving particle family.
                if peakUnits.count < 2 {
                    let samples = 8
                    for sample in 0..<samples {
                        let unit = 0.08 + 0.84 * Double(sample) / Double(samples - 1)
                        if waveProfile(at: unit, time: time, audio: 0) < 0.62 { continue }
                        if peakUnits.last.map({ unit - $0 > 0.08 }) ?? true { peakUnits.append(unit) }
                    }
                }
                if peakUnits.isEmpty { peakUnits.append(0.5) }

                // A subtle low RGB halo belongs to the moving crest, not a
                // rectangle-sized glow layer. It is painted before the blocks.
                for (band, blur, alpha) in [(Color.red, 6.0, 0.17), (Color.cyan, 4.0, 0.15), (Color.purple, 3.0, 0.12)] {
                    context.drawLayer { glow in
                        glow.addFilter(.blur(radius: blur))
                        glow.stroke(ridge, with: .color(band.opacity(alpha * opacity)),
                                    style: StrokeStyle(lineWidth: 3, lineCap: .round))
                    }
                }

                // The principal shape remains four/five crisp square cells.
                // Soft spectral light wraps the crest; it does not add rows.
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let x = columnCenter(at: unit, width: size.width)
                    let audio = reduceMotion ? 0 : sampledLevel(at: unit)
                    let profile = waveProfile(at: unit, time: time, audio: audio)
                    let rows = rowCount(for: profile)
                    let color = colors[min(colors.count - 1, Int(unit * Double(colors.count)))]
                    let crest = centers[index]
                    if rows >= 3 {
                        let halo = Path(ellipseIn: CGRect(x: x - 4, y: crest - 2, width: 8, height: 4))
                        context.fill(halo, with: .color(color.opacity(0.20 * opacity)))
                    }
                    for row in 0..<rows {
                        let y = rowCenter(at: row, height: size.height)
                        let edgeFade = max(0.56, 1.0 - Double(row) * 0.11)
                        let square = Path(CGRect(x: x - Self.squareSize * 0.5,
                                                 y: y - Self.squareSize * 0.5,
                                                 width: Self.squareSize, height: Self.squareSize))
                        context.fill(square, with: .color(color.opacity(opacity * edgeFade)))
                    }
                }

                // Sparse cursor-proximal sparks rise and fall, then dissolve
                // into the crest. Emitters are visual-only and never hit-test.
                if !reduceMotion {
                    for emitter in 0..<Self.movingSparkEmitters {
                        let peakIndex = emitter % peakUnits.count
                        let peakUnit = peakUnits[peakIndex]
                        let packet = floor(time * 1.35 - peakUnit * 1.7)
                        let birth = packet / 1.35 + Double(peakIndex) * 0.09
                        let life = (time - birth) / Self.sparkLife
                        guard life >= 0 && life < 1 else { continue }
                        let drift = smoothNoise(position: time * 0.19 + Double(emitter) * 5.3)
                        // Keep the rising highlights in the visible middle
                        // corridor; the square crest itself still spans full
                        // width and remains naturally occluded by controls.
                        let safePeak = min(0.74, max(0.26, peakUnit))
                        let travel = sin(time * 0.52 + Double(emitter) * 1.31) * 0.065
                        let clusterOffset = (Double(emitter % 3) - 1.0) * 0.012
                        let sparkUnit = min(0.74, max(0.26, safePeak + travel + clusterOffset + drift * 0.008))
                        let column = min(columns - 1, max(0, Int(sparkUnit * Double(columns - 1))))
                        let baseY = centers[column]
                        let audio = sampledLevel(at: sparkUnit)
                        let sparkColumn = min(columns - 1, max(0, Int(sparkUnit * Double(columns - 1))))
                        let sparkBaseY = centers[sparkColumn]
                        let rise = CGFloat(sparkEnvelope(life: life, audio: audio))
                        let x = columnCenter(at: sparkUnit, width: size.width) + CGFloat(drift * 4.0)
                        let y = max(-Self.sparkMaxRise, sparkBaseY - rise * Self.sparkMaxRise)
                        let color = colors[min(colors.count - 1, Int(sparkUnit * Double(colors.count)))]
                        let fade = sparkFade(life: life)
                        let size = CGFloat(2.8 + 0.6 * (1.0 - life))
                        let spark = Path(CGRect(x: x - size * 0.5, y: y - size * 0.5,
                                                width: size, height: size))
                        let halo = Path(ellipseIn: CGRect(x: x - 4, y: y - 4, width: 8, height: 8))
                        let trail = Path { path in
                            path.move(to: CGPoint(x: x - CGFloat(drift * 2), y: y + 7))
                            path.addQuadCurve(to: CGPoint(x: x, y: y + 1),
                                              control: CGPoint(x: x + CGFloat(drift * 2), y: y + 3))
                        }
                        context.stroke(trail, with: .color(color.opacity(0.42 * fade)),
                                       style: StrokeStyle(lineWidth: 1.2, lineCap: .round))
                        context.drawLayer { glow in
                            glow.addFilter(.blur(radius: 2.2))
                            glow.fill(halo, with: .color(color.opacity(0.32 * fade)))
                            glow.stroke(trail, with: .color(color.opacity(0.30 * fade)),
                                        style: StrokeStyle(lineWidth: 2.6, lineCap: .round))
                        }
                        context.fill(spark, with: .color(Color.white.opacity(0.82 * fade)))
                        context.fill(spark, with: .color(color.opacity(0.95 * fade)))
                    }

                    if transitionBeganAt > 0 {
                        let age = time - transitionBeganAt
                        if age >= 0 && age < 0.52 {
                            let fade = 1.0 - age / 0.52
                            let unit = 0.5 + 0.38 * sin(age * 9.0)
                            let column = min(columns - 1, max(0, Int(unit * Double(columns - 1))))
                            let x = columnCenter(at: unit, width: size.width)
                            let y = centers[column] - CGFloat((1.0 - age / 0.52) * 8.0)
                            let trace = Path { path in
                                path.move(to: CGPoint(x: x - 4, y: y + 2))
                                path.addQuadCurve(to: CGPoint(x: x + 3, y: y),
                                                  control: CGPoint(x: x, y: y - 5))
                            }
                            context.drawLayer { glow in
                                glow.addFilter(.blur(radius: 3.0))
                                glow.stroke(trace, with: .color(Color.white.opacity(0.48 * fade)),
                                            style: StrokeStyle(lineWidth: 2.0, lineCap: .round))
                            }
                            context.stroke(trace, with: .color(Color.white.opacity(0.8 * fade)),
                                           style: StrokeStyle(lineWidth: 0.8, lineCap: .round))
                        }
                    }
                }
            }
            .onChange(of: voiceActive) { active in
                guard !reduceMotion else { return }
                transitionBeganAt = timeline.date.timeIntervalSinceReferenceDate
                _ = active
            }
        }
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    private func sparkEnvelope(life: Double, audio: Double) -> Double {
        let bell = sin(.pi * min(1, max(0, life)))
        return min(1, max(0, bell * (0.30 + audio * 0.70)))
    }

    private func sparkFade(life: Double) -> Double {
        return min(1, max(0, (1 - life) * min(1, life * 5)))
    }

    private func columnCount(in width: CGFloat) -> Int {
        return max(2, Int(floor((width - Self.edgeInset * 2 - Self.squareSize) / Self.columnPitch)) + 1)
    }

    private func columnCenter(at unit: Double, width: CGFloat) -> CGFloat {
        return Self.edgeInset + Self.squareSize * 0.5 + (width - Self.edgeInset * 2 - Self.squareSize) * CGFloat(unit)
    }

    private func rowCenter(at row: Int, height: CGFloat) -> CGFloat {
        return height - Self.squareSize * 0.5 - CGFloat(row) * Self.rowPitch
    }

    private func rowCount(for profile: Double) -> Int {
        return min(Self.maxRows, max(1, Int(ceil(profile * Double(Self.maxRows)))))
    }

    private func waveProfile(at unit: Double, time: Double, audio: Double) -> Double {
        // Two broad wave groups, slowly translating across the full bar.
        // Local ripple and grain alter their contour without multiplying rows.
        let phase = time * 0.34
        let broadDrift = smoothNoise(position: phase * 1.7 + 19.4) * 0.03
        let moved = min(0.97, max(0.03, unit - broadDrift))
        let broad = 0.5 + 0.5 * cos((moved - 0.12) * .pi * 3.2)
        let slowNoise = smoothNoise(position: unit * 3.4 + phase * 0.9)
        let middleNoise = smoothNoise(position: unit * 7.1 - phase * 1.1 + 6.3)
        let detailNoise = smoothNoise(position: unit * 15.0 + phase * 1.6 + 13.7)
        return min(1, max(0, 0.12 + broad * 0.75 + slowNoise * 0.06 + middleNoise * 0.035 + detailNoise * 0.02 + audio * 0.12))
    }

    // The same smooth lattice noise and per-column audio sampling as 62657c0.
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
