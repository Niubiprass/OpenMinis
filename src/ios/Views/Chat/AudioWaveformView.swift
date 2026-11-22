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
/// Geometry is taken from the reference recording rather than invented: in the
/// reference the composer card is 913 px wide with a 12 px dot pitch and 6 px
/// dots, i.e. dots/pitch = 0.5 and ~76 dots across. The previous build used a
/// 1.62 pt pitch (up to 180 columns) which read as a fine mesh instead of
/// grain. [T-composer-wave-video-match]
struct ComposerRainbowWave: View {
    var levels: [Float] = []
    var opacity: Double = 0.58
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let canvasHeight: CGFloat = 74
    // Video-matched grid (350 pt box → 76 dots across).
    private static let dotSize: CGFloat = 2.30
    private static let columnPitch: CGFloat = 4.60
    private static let rowPitch: CGFloat = 4.60
    private static let edgeInset: CGFloat = 2.0
    private static let maxRows = 8
    private static let maxColumns = 96
    private static let peakHeight: CGFloat = 26.0
    private static let transitionLife = 0.48
    @State private var transitionBeganAt: TimeInterval = -1
    var voiceActive: Bool = false

    // MARK: Flow
    //
    // Measured from the reference at 10 fps: the ridge height swings ~±20% and
    // the crest wanders ~10% of the width within a second, i.e. a few pixels of
    // change per frame. Three travelling waves at different speeds and
    // directions produce that: the surface churns instead of pulsing in place.
    // (wavelengths across the width, cycles/second, amplitude)
    private static let flow: [(Double, Double, Double)] = [
        (1.00, 0.640, 0.480),
        (2.20, -0.470, 0.240),
        (4.00, 0.980, 0.100)
    ]

    // MARK: Colour
    //
    // The reference is NOT a uniform rainbow. Measured share of dots by hue:
    // magenta 27.5%, red 16.2%, cyan-blue 23.5%, green-cyan 13.0%, orange 9.1%,
    // blue-violet 5.4%, violet 4.1%, yellow-green only 1.2%. A uniform spectrum
    // spends far too much on yellow-green and violet. These weights reproduce
    // the measured proportions.
    private static let cycle: [(hue: Double, weight: Double)] = [
        (0.94, 27.5), (0.02, 16.2), (0.12, 9.1),
        (0.43, 13.0), (0.55, 23.5), (0.68, 5.4), (0.82, 4.1)
    ]
    /// Palette cycles across the box. The reference pattern is roughly one
    /// cycle wide and slides sideways, which is what makes the colour read as
    /// flowing water rather than a painted gradient.
    private static let cycleSpan = 1.15
    private static let cycleSpeed = 0.20      // cycles per second
    /// Median hue at the top of a crest in the reference: orange.
    private static let crestHue = 0.105

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: reduceMotion)) { timeline in
            Canvas(opaque: false, colorMode: .linear) { context, size in
                guard size.width > 0, size.height > 0 else { return }
                let time = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                let baseline = size.height - Self.dotSize * 0.5
                let columns = columnCount(in: size.width)
                guard columns > 1 else { return }

                // Height/envelope for every column, computed once and reused by
                // the bloom pass and the sharp pass.
                var xs = [CGFloat](repeating: 0, count: columns)
                var heights = [Double](repeating: 0, count: columns)
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    xs[index] = columnCenter(at: unit, width: size.width)
                    heights[index] = waveHeight(at: unit, time: time)
                }

                // Bloom: six hue sextants so the glow keeps the colour of the
                // dots underneath it. A single-colour bloom looked grey.
                var buckets = [Path](repeating: Path(), count: 6)
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let height = heights[index]
                    guard height > 0 else { continue }
                    let rows = rowCount(for: height)
                    for row in 0..<rows {
                        let centre = dotCenter(x: xs[index], baseline: baseline,
                                               unit: unit, row: row, height: height, time: time)
                        let diameter = Self.dotSize * 1.5
                        let rect = CGRect(x: centre.x - diameter * 0.5, y: centre.y - diameter * 0.5,
                                          width: diameter, height: diameter)
                        let hue = dotHue(unit: unit, row: row, rows: rows, height: height, time: time)
                        buckets[Int(hue * 6) % 6].addRect(rect)
                    }
                }
                context.drawLayer { glow in
                    glow.addFilter(.blur(radius: 3.4))
                    glow.opacity = opacity * 0.42
                    for sector in 0..<6 {
                        guard !buckets[sector].isEmpty else { continue }
                        let hue = (Double(sector) + 0.5) / 6.0
                        glow.fill(buckets[sector],
                                  with: .color(Self.color(hue: hue, sat: 0.80, val: 0.92)))
                    }
                }

                // Sharp grain.
                for index in 0..<columns {
                    let unit = Double(index) / Double(columns - 1)
                    let height = heights[index]
                    guard height > 0 else { continue }
                    let rows = rowCount(for: height)
                    for row in 0..<rows {
                        let centre = dotCenter(x: xs[index], baseline: baseline,
                                               unit: unit, row: row, height: height, time: time)
                        let remainder = height - Double(row) * Double(Self.rowPitch)
                        let topScale = row == rows - 1 ? min(1, max(0.58, remainder / Double(Self.rowPitch))) : 1
                        // Grain: individual beads differ in size and brightness,
                        // which is what gives the reference its speckled look.
                        let grain = 0.74 + 0.52 * (0.5 + 0.5 * smoothNoise(
                            position: Double(index) * 2.31 + Double(row) * 5.17))
                        let diameter = Self.dotSize * CGFloat(topScale * grain)
                        let rect = CGRect(x: centre.x - diameter * 0.5, y: centre.y - diameter * 0.5,
                                          width: diameter, height: diameter)
                        let hue = dotHue(unit: unit, row: row, rows: rows, height: height, time: time)
                        let warmth = warmAmount(row: row, rows: rows, height: height)
                        let brightness = 0.80 + 0.20 * smoothNoise(
                            position: Double(index) * 1.7 + Double(row) * 3.9 + time * 0.7)
                        context.fill(Path(rect),
                                     with: .color(Self.color(hue: hue,
                                                             sat: 0.78 + 0.10 * warmth,
                                                             val: min(1.0, 0.86 + 0.14 * warmth)
                                                                  * brightness)))
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
        return max(2, min(Self.maxColumns, Int(floor((width - Self.edgeInset * 2) / Self.columnPitch)) + 1))
    }

    private func columnCenter(at unit: Double, width: CGFloat) -> CGFloat {
        return Self.edgeInset + (width - Self.edgeInset * 2) * CGFloat(unit)
    }

    private func rowCount(for height: Double) -> Int {
        return min(Self.maxRows, max(1, Int(ceil(height / Double(Self.rowPitch)))))
    }

    /// Dot position with a small grain jitter. Kept tiny on purpose: the
    /// reference grid is regular, only the bead sizes vary.
    private func dotCenter(x: CGFloat, baseline: CGFloat, unit: Double, row: Int,
                           height: Double, time: Double) -> CGPoint {
        let jx = smoothNoise(position: unit * 41.0 + Double(row) * 7.3 + time * 0.6) * 0.28
        let jy = smoothNoise(position: unit * 37.0 + Double(row) * 9.1 - time * 0.5) * 0.26
        let y = baseline - CGFloat(row) * Self.rowPitch + CGFloat(jy)
        return CGPoint(x: x + CGFloat(jx), y: max(Self.dotSize * 0.5, min(baseline, y)))
    }

    // MARK: - Shape

    // Silhouette measured from the reference frame: a broad mound peaking just
    // past half width with a slightly flattened crown, tapering to nothing at
    // both edges. Values are the normalized height sampled across the composer.
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

    /// Whole-surface sway: the crest (and the colour riding on it) travels
    /// across the box instead of breathing in place.
    private func drift(_ time: Double) -> Double {
        return 0.062 * sin(2 * .pi * 0.30 * time) + 0.022 * sin(2 * .pi * 0.64 * time + 1.1)
    }

    /// Multiplier on the fixed silhouette from the travelling waves. Never
    /// negative: the surface may rise and fall but must not open holes.
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

    /// Position inside the scrolling palette cycle.
    private func phase(unit: Double, time: Double) -> Double {
        var value = (unit * Self.cycleSpan - time * Self.cycleSpeed)
        value = value - floor(value)
        return value
    }

    /// Base hue from the measured cycle weights.
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

    /// How warm (crest-orange) this dot should be: only the top row or two of
    /// a genuinely tall column. A gradual blend would sweep the hue through
    /// green on its way from cyan to orange, which the reference lacks.
    private func warmAmount(row: Int, rows: Int, height: Double) -> Double {
        guard rows > 1 else { return 0 }
        // Only genuinely tall columns warm up: below ~60% of the peak the band
        // stays cool, which is what the reference does.
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

    /// HSV → RGB, kept local so no UIKit import is needed.
    private static func color(hue: Double, sat: Double, val: Double) -> Color {
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
        return Color(red: rgb.0, green: rgb.1, blue: rgb.2)
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
