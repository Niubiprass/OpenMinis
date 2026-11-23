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
///
/// Geometry & luminance are calibrated directly against the reference recording:
/// staggered 2.35 pt row steps / 2.30 pt half-column steps (~152 staggered columns
/// across 350 pt, i.e. 4.60 pt primary column pitch), colored ambient bloom
/// underneath crisp saturated dots, and a travelling specular band ("亮面")
/// matching the measured V percentiles (p50 ~0.43, p90 ~0.85, p98 ~0.98) and
/// <1% white core so the dots read crisp and luminous rather than hazy.
/// [T-composer-wave-video-match]
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.58
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let canvasHeight: CGFloat = 74
    // Video-matched staggered grid (350 pt box -> 4.60 pt primary pitch, 2.35 pt row pitch).
    private static let dotSize: CGFloat = 2.05
    private static let columnPitch: CGFloat = 4.60
    private static let rowPitch: CGFloat = 2.35
    private static let edgeInset: CGFloat = 2.0
    private static let maxRows = 11
    private static let maxColumns = 192
    private static let peakHeight: CGFloat = 26.0
    private static let transitionLife = 0.48
    @State private var transitionBeganAt: TimeInterval = -1
    var voiceActive: Bool = false

    // MARK: Flow
    //
    // Three travelling waves at different speeds and directions so the ridge
    // churns instead of pulsing in place. (wavelengths, cycles/sec, amplitude)
    private static let flow: [(Double, Double, Double)] = [
        (1.00, 0.640, 0.480),
        (2.20, -0.470, 0.240),
        (4.00, 0.980, 0.100)
    ]

    // MARK: Colour
    //
    // Measured hue share from the reference recording (bottom band, 9 frames).
    private static let cycle: [(hue: Double, weight: Double)] = [
        (0.94, 27.5), (0.02, 16.2), (0.12, 9.1),
        (0.43, 13.0), (0.55, 23.5), (0.68, 5.4), (0.82, 4.1)
    ]
    private static let cycleSpan = 1.15
    private static let cycleSpeed = 0.20      // cycles per second
    private static let crestHue = 0.105

    // MARK: Specular band ("亮面")
    //
    // Travelling specular highlight along the middle-lower rows (~36% of column
    // height) that lifts brightness cleanly toward 1.0 while keeping hue vivid.
    private static let rowLightIndex = 0.36
    private static let rowLightSigma = 1.45
    private static let rowLightCentre = 0.54
    private static let rowLightCentreDrift = 0.08
    private static let rowLightLength = 0.18
    private static let rowLightLengthPulse = 0.06
    private static let rowLightWhite = 0.16

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let baseline = size.height - 1.5
                let columns = columnCount(in: size.width)
                guard columns > 1 else { return }

                var xs = [CGFloat](repeating: 0, count: columns)
                var heights = [Double](repeating: 0, count: columns)
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    xs[index] = columnCenter(at: unit, width: size.width)
                    heights[index] = waveHeight(at: unit, time: time)
                }

                // Pass 1: Colored ambient wash beneath the dots (buckets keep hue pure).
                var washBuckets = [Path](repeating: Path(), count: 12)
                // Pass 2: Sharp crisp square dots + tight specular sheen buckets.
                var specBuckets = [Path](repeating: Path(), count: 12)

                struct DotDraw {
                    let rect: CGRect
                    let color: Color
                }
                var dotDraws: [DotDraw] = []
                dotDraws.reserveCapacity(columns * 6)

                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let height = heights[index]
                    guard height > 0.001 else { continue }
                    let rows = rowCount(for: height)
                    for row in 0..<rows {
                        let isPrimary = ((index + row) % 2 == 1)
                        if !isPrimary {
                            if row > 2 { continue }
                            let fillProb = (row <= 1 ? 0.72 : 0.25) * min(1.0, height / (Double(Self.peakHeight) * 0.65))
                            let gate = 0.5 + 0.5 * smoothNoise(
                                position: Double(index) * 3.1 + Double(row) * 7.3 + time * 0.9)
                            if gate > fillProb { continue }
                        }

                        let vertical = rows > 1 ? Double(row) / Double(rows - 1) : 0.0
                        let warmth = warmAmount(row: row, rows: rows, height: height)
                        let hue = dotHue(unit: unit, row: row, rows: rows, height: height, time: time)

                        let satBase = max(0.20, min(0.90, (0.78 - 0.46 * pow(vertical, 0.80)) + 0.08 * warmth))
                        let grainBright = 0.78 + 0.22 * (0.5 + 0.5 * smoothNoise(
                            position: Double(index) * 1.7 + Double(row) * 3.9 + time * 0.7))

                        var baseVal = (0.94 - 0.38 * pow(vertical, 0.82)) * grainBright
                        if !isPrimary {
                            baseVal *= 0.86
                        }

                        let sp = rowLight(unit: unit, row: row, rows: rows, height: height, time: time)
                        var val = min(1.0, baseVal + (1.0 - baseVal) * (0.84 * sp) + 0.08 * warmth)
                        let sat = max(0.22, satBase * (1.0 - 0.30 * sp))

                        if row >= rows - 2 {
                            let edgeFade = min(1.0, max(0.32, (height - Double(row) * Double(Self.rowPitch)) / (Double(Self.rowPitch) * 1.6)))
                            val *= edgeFade
                        }

                        let whiten = max(0.0, (sp - 0.68) / 0.32) * Self.rowLightWhite
                        let dotColor = Self.color(hue: hue, sat: sat, val: val, whiten: whiten)

                        let grain = 0.76 + 0.34 * (0.5 + 0.5 * smoothNoise(
                            position: Double(index) * 2.31 + Double(row) * 5.17))
                        var dia = (Self.dotSize * 0.88) * CGFloat(grain * (0.94 + 0.22 * sp))
                        if !isPrimary {
                            dia *= 0.88
                        }

                        let centre = dotCenter(x: xs[index], baseline: baseline,
                                               unit: unit, row: row, height: height, time: time)
                        let rect = CGRect(x: centre.x - dia * 0.5, y: centre.y - dia * 0.5,
                                          width: dia, height: dia)
                        dotDraws.append(DotDraw(rect: rect, color: dotColor))

                        let sector = min(11, max(0, Int(hue * 12) % 12))
                        if val > 0.20 {
                            let wDia: CGFloat = 4.8
                            washBuckets[sector].addEllipse(in: CGRect(
                                x: centre.x - wDia * 0.5, y: centre.y - wDia * 0.5,
                                width: wDia, height: wDia))
                        }
                        if sp > 0.30 || (row <= 1 && val > 0.80) {
                            let sDia = dia * CGFloat(1.25 + 0.25 * sp)
                            specBuckets[sector].addRect(CGRect(
                                x: centre.x - sDia * 0.5, y: centre.y - sDia * 0.5,
                                width: sDia, height: sDia))
                        }
                    }
                }

                // 1) Colored ambient wash underneath (.plusLighter so dark card shows rich gap glow)
                context.drawLayer { wash in
                    wash.addFilter(.blur(radius: 2.6))
                    wash.blendMode = .plusLighter
                    wash.opacity = min(1.0, opacity * 0.36)
                    for sector in 0..<12 {
                        guard !washBuckets[sector].isEmpty else { continue }
                        let hue = (Double(sector) + 0.5) / 12.0
                        wash.fill(washBuckets[sector],
                                  with: .color(Self.color(hue: hue, sat: 0.78, val: 0.90)))
                    }
                }

                // 2) Crisp, unblurred dot matrix on top
                var dotContext = context
                dotContext.opacity = opacity
                for item in dotDraws {
                    dotContext.fill(Path(item.rect), with: .color(item.color))
                }

                // 3) Tight specular sheen on the bright band & bottom core
                context.drawLayer { spec in
                    spec.addFilter(.blur(radius: 0.8))
                    spec.blendMode = .plusLighter
                    spec.opacity = min(1.0, opacity * 0.32)
                    for sector in 0..<12 {
                        guard !specBuckets[sector].isEmpty else { continue }
                        let hue = (Double(sector) + 0.5) / 12.0
                        spec.fill(specBuckets[sector],
                                  with: .color(Self.color(hue: hue, sat: 0.42, val: 1.0, whiten: 0.14)))
                    }
                }

                if !reduceMotion {
                    let age = time - transitionBeganAt
                    if age >= 0 && age < Self.transitionLife {
                        let progress = age / Self.transitionLife
                        var trace = Path()
                        for streak in 0..<3 {
                            let unit = min(0.94, max(0.06, 0.18 + progress * 0.62 + Double(streak) * 0.035))
                            let x = columnCenter(at: unit, width: size.width)
                            let height = waveHeight(at: unit, time: time)
                            let y = baseline - CGFloat(height) - CGFloat(progress * 3.5)
                            let length = CGFloat(5.0 + Double(streak) * 1.2)
                            trace.move(to: CGPoint(x: x - length, y: y + 2.0))
                            trace.addQuadCurve(to: CGPoint(x: x + 1.5, y: y),
                                               control: CGPoint(x: x - 1.5, y: y - 3.2))
                        }
                        context.drawLayer { glow in
                            glow.addFilter(.blur(radius: 3.0))
                            glow.opacity = opacity * (1.0 - progress) * 0.68
                            glow.stroke(trace, with: .color(Self.color(hue: Self.crestHue, sat: 0.85, val: 0.98)),
                                        style: StrokeStyle(lineWidth: 2.8, lineCap: .round))
                        }
                        var traceContext = context
                        traceContext.opacity = opacity * (1.0 - progress)
                        traceContext.stroke(trace, with: .color(Self.color(hue: Self.crestHue, sat: 0.85, val: 0.98)),
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

    // MARK: - Grid

    private func columnCount(in width: CGFloat) -> Int {
        let usable = max(0, width - Self.edgeInset * 2)
        // Staggered half-column pitch (2.30 pt) -> ~152 staggered columns across 350 pt,
        // matching the 76 primary columns per row (6.17 px sub-grid in reference).
        let raw = Int(round(usable / (Self.columnPitch * 0.5))) + 1
        return min(Self.maxColumns, max(2, raw))
    }

    private func columnCenter(at unit: Double, width: CGFloat) -> CGFloat {
        return Self.edgeInset + (width - Self.edgeInset * 2) * CGFloat(unit)
    }

    private func rowCount(for height: Double) -> Int {
        return min(Self.maxRows, max(1, Int(ceil(height / Double(Self.rowPitch)))))
    }

    private func dotCenter(x: CGFloat, baseline: CGFloat, unit: Double, row: Int,
                           height: Double, time: Double) -> CGPoint {
        let jx = smoothNoise(position: unit * 41.0 + Double(row) * 7.3 + time * 0.6) * 0.20
        let jy = smoothNoise(position: unit * 37.0 + Double(row) * 9.1 - time * 0.5) * 0.18
        let y = baseline - CGFloat(row) * Self.rowPitch + CGFloat(jy)
        return CGPoint(x: x + CGFloat(jx), y: max(Self.dotSize * 0.5, min(baseline, y)))
    }

    // MARK: - Shape

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
        let base = lower * (1 - frac) + upper * frac
        // Secondary right lobe & left wing measured across reference active frames.
        let rightLobe = 0.56 * exp(-pow((unit - 0.74) / 0.13, 2))
        let leftWing = 0.24 * exp(-pow((unit - 0.20) / 0.12, 2))
        return inside ? min(1.0, max(base, max(rightLobe, leftWing))) : 0
    }

    private func drift(_ time: Double) -> Double {
        return 0.062 * sin(2 * .pi * 0.30 * time) + 0.022 * sin(2 * .pi * 0.64 * time + 1.1)
    }

    private func flowScale(unit: Double, time: Double) -> Double {
        var amount = 0.0
        for (wavelengths, speed, amplitude) in Self.flow {
            amount += amplitude * sin(2 * .pi * (wavelengths * unit - speed * time))
        }
        let edge = min(1.0, min(unit, 1 - unit) / 0.16)
        return max(0.22, 1.0 + amount * edge)
    }

    private func waveHeight(at unit: Double, time: Double) -> Double {
        let shifted = min(0.999, max(0.001, unit + drift(time)))
        let shape = profileUnit(shifted)
        let scale = flowScale(unit: unit, time: time)
        let breath = 0.97 + 0.06 * smoothNoise(position: unit * 7.0 + time * 0.8)
        return shape > 0.001 ? Double(Self.peakHeight) * shape * scale * breath : 0
    }

    // MARK: - Colour

    private func phase(unit: Double, time: Double) -> Double {
        var value = (unit * Self.cycleSpan - time * Self.cycleSpeed)
        value = value - floor(value)
        return value
    }

    private static func paletteHue(_ phase: Double) -> Double {
        let total = cycle.reduce(0) { $0 + $1.weight }
        var travelled = 0.0
        let target = (phase - floor(phase)) * total
        for index in 0..<cycle.count {
            let current = cycle[index]
            let next = cycle[(index + 1) % cycle.count]
            if travelled + current.weight >= target {
                let local = current.weight > 0 ? (target - travelled) / current.weight : 0
                var delta = (next.hue - current.hue).truncatingRemainder(dividingBy: 1)
                if delta > 0.5 { delta -= 1 }
                if delta < -0.5 { delta += 1 }
                var hue = current.hue + delta * local
                hue = hue - floor(hue)
                return hue
            }
            travelled += current.weight
        }
        return cycle[0].hue
    }

    /// 0...1 weight of the travelling specular bright band ("亮面") at this dot.
    private func rowLight(unit: Double, row: Int, rows: Int, height: Double, time: Double) -> Double {
        guard rows >= 3 else { return 0 }
        let targetRow = Self.rowLightIndex * Double(rows)
        let rowDistance = (Double(row) - targetRow) / Self.rowLightSigma
        let rowWeight = exp(-rowDistance * rowDistance)
        guard rowWeight >= 0.05 else { return 0 }
        let centre = Self.rowLightCentre
            + Self.rowLightCentreDrift * sin(2 * .pi * 0.13 * time)
        let halfLength = Self.rowLightLength
            + Self.rowLightLengthPulse * sin(2 * .pi * 0.19 * time + 0.7)
        let distance = (unit - centre) / max(0.04, halfLength)
        let span = exp(-distance * distance * 2.6)
        return rowWeight * span * min(1.0, height / (Double(Self.peakHeight) * 0.55))
    }

    private func warmAmount(row: Int, rows: Int, height: Double) -> Double {
        guard rows > 1 else { return 0 }
        let crest = max(0.0, min(1.0, (height / Double(Self.peakHeight) - 0.60) / 0.40))
        let vertical = pow(Double(row) / Double(rows - 1), 3.2)
        return min(1.0, vertical * crest)
    }

    private func dotHue(unit: Double, row: Int, rows: Int, height: Double, time: Double) -> Double {
        var hue = Self.paletteHue(phase(unit: unit, time: time))
        let warmth = warmAmount(row: row, rows: rows, height: height)
        var delta = (Self.crestHue - hue).truncatingRemainder(dividingBy: 1)
        if delta > 0.5 { delta -= 1 }
        if delta < -0.5 { delta += 1 }
        hue += delta * min(1.0, warmth * 1.15)
        return hue - floor(hue)
    }

    private static func color(hue: Double, sat: Double, val: Double, whiten: Double = 0) -> Color {
        let h = (hue - floor(hue)) * 6
        let sector = Int(h) % 6
        let f = h - floor(h)
        let p = val * (1 - sat)
        let q = val * (1 - sat * f)
        let t = val * (1 - sat * (1 - f))
        let rgb: (Double, Double, Double)
        switch sector {
        case 0: rgb = (val, t, p)
        case 1: rgb = (q, val, p)
        case 2: rgb = (p, val, t)
        case 3: rgb = (p, q, val)
        case 4: rgb = (t, p, val)
        default: rgb = (val, p, q)
        }
        let mix = min(1.0, max(0.0, whiten))
        return Color(red: rgb.0 + (1 - rgb.0) * mix,
                     green: rgb.1 + (1 - rgb.1) * mix,
                     blue: rgb.2 + (1 - rgb.2) * mix)
    }

    // MARK: - Noise

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
