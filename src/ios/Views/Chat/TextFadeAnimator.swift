//  TextFadeAnimator.swift
//  Minis
//
//  Word-by-word fade-in animation for streaming Markdown output.
//
//  When the renderer appends new tokens to a message's textStorage via the
//  `[AttachHotPath]` append-only fast path in SelectableMarkdownView, instead
//  of the new glyphs popping in instantly we fade each word from alpha 0 → 1
//  with a small per-word stagger, producing a "ripple" reveal.
//
//  Design constraints:
//   - Display-layer only. Does NOT touch MinisMarkdownParser / AST /
//     MarkdownNSRenderer. We mutate the live NSTextStorage's `.foregroundColor`
//     attribute and rely on TextKit 1's behaviour that a foregroundColor change
//     does NOT invalidate layout (no `ensureLayout` reflow) — only a redraw.
//   - O(new words), never O(full text). Only the appended NSRange is scanned.
//   - A single CADisplayLink drives ALL in-flight words; it stops itself once
//     every word has settled, so an idle (non-streaming) view costs nothing.
//
//  This file deliberately owns no parsing or rendering logic; it is a pure
//  per-word alpha scheduler over an existing NSTextStorage.

import UIKit

/// Drives word-by-word alpha fade-in for newly appended text in an
/// NSTextStorage. Lives on the SelectableMarkdownView Coordinator; one
/// instance per on-screen textView.
@MainActor
final class TextFadeAnimator {

    // MARK: - Tunables

    /// How long a single word takes to fade from alpha 0 → 1. Matches
    /// Microsoft SwiftStreamingMarkdown's 0.5s; slightly shorter reads as more
    /// responsive on a phone without losing the smooth settle.
    private static let wordFadeDuration: CFTimeInterval = 0.45

    /// 单批淡入的最大单位数（词 + 词间空隙）。
    ///
    /// 之前是 160，且「超过就整批不动画」——中文场景下单位数≈字数，一段
    /// 300 字的输出整批跳过，于是一整段字在同一帧里蹦出来（用户 2026-10-26
    /// 报「一大段内容直接一片出来」）。现在：
    ///   · 上限抬到 400，一段正常段落能整批淡入；
    ///   · 仍然超限时不再整批放弃，改成只淡入**尾部** 400 个单位，
    ///     前面的立即显示（比整块硬贴自然得多）；
    ///   · 每帧写 attribute 的量是 O(在飞单位数)，400 个也是一帧几百次
    ///     属性写入，和重绘一次文本相比可忽略。
    private static let maxAnimatedWords = 400

    /// 一次最多切分多少个单位。超过这个量的大粘贴（几万字）没必要逐字淡入，
    /// 直接显示，避免一次性切出上万个区间。
    private static let maxAnimationUnits = 4000

    /// Total stagger window for ONE batch, divided across its words — the key
    /// to a steady reveal regardless of bursty token arrival (this is exactly
    /// Microsoft SwiftStreamingMarkdown's `0.1 / wordCount`). A 2-word batch
    /// staggers 0.05s apart; a 30-word burst staggers ~0.003s apart, so every
    /// batch finishes in ~`window + duration` (~0.55s) no matter its size. The
    /// per-batch baseStart is simply `now`, so consecutive batches overlap
    /// naturally rather than queueing into an ever-growing tail.
    private static let staggerWindow: CFTimeInterval = 0.28

    /// - Parameters:
    ///   - count: 这一批要淡入的单位数。
    ///   - backlog: 调用时还挂在队列里的旧单位数（上一批没淡完的量）。
    ///
    /// 批次越大摊得越久：固定 0.1 秒的窗口会让大批次在几十毫秒内整体冒出来
    /// （用户看到的就是「一大段直接一片出来」）。一批 300 字大约摊 0.9 秒，
    /// 和下一批（通常 0.5–1 秒后到）正好接上，观感是连续的流。
    ///
    /// 但如果上一批还没走完，说明数据来得比揭示快，这时改用 0.30 秒的短窗口
    /// 追赶，避免越积越落后（否则输出结束时屏幕上还在慢慢补字）。
    private static func stagger(forWordCount count: Int, backlog: Int) -> CFTimeInterval {
        guard count > 0 else { return 0 }
        let window: CFTimeInterval
        if backlog > 0 {
            window = 0.30
        } else {
            window = min(0.9, max(staggerWindow, CFTimeInterval(count) * 0.006))
        }
        return window / CFTimeInterval(count)
    }

    // MARK: - State

    private struct FadeWord {
        let range: NSRange
        let startTime: CFTimeInterval
        let duration: CFTimeInterval
        /// Original (fully-opaque) foreground color to restore on completion.
        let originalColor: UIColor
    }

    /// The storage we mutate. Weak — the textView (and its storage) outlives
    /// us via the Coordinator, but we never want to keep it alive ourselves.
    private weak var storage: NSTextStorage?
    /// Called after each frame's attribute mutation so the textView repaints.
    /// Weak capture lives in the closure the owner supplies.
    private let requestRedraw: () -> Void

    private var words: [FadeWord] = []
    private var displayLink: CADisplayLink?

    // MARK: - Init

    /// - Parameter requestRedraw: invoked on the main thread after each frame's
    ///   alpha mutation. The owner should call `textView.setNeedsDisplay()`.
    init(requestRedraw: @escaping () -> Void) {
        self.requestRedraw = requestRedraw
    }

    deinit {
        // CADisplayLink retains its target; we invalidate in cancelAll, but
        // guard here too in case the owner is torn down mid-animation.
        displayLink?.invalidate()
    }

    // MARK: - Scheduling

    /// Begin fading the words inside `range` of `targetStorage` from alpha 0 → 1.
    ///
    /// Call this from the append-only fast path AFTER `replaceCharacters`, with
    /// the NSRange of the freshly-appended tail. Safe to call repeatedly while
    /// streaming — each call adds its words to the shared in-flight set.
    func scheduleAnimation(for range: NSRange, in targetStorage: NSTextStorage) {
        guard range.length > 0 else { return }
        let storageLen = targetStorage.length
        // Defensive clamp: the caller computed `range` from the same storage,
        // but a racing edit could have shrunk it. Never index out of bounds.
        guard range.location >= 0, range.location < storageLen else { return }
        let safeRange = NSRange(
            location: range.location,
            length: min(range.length, storageLen - range.location)
        )
        guard safeRange.length > 0 else { return }

        self.storage = targetStorage

        // Split the appended tail into reveal units. Unlike a bare
        // `.byWords` enumeration (which omits the punctuation / whitespace /
        // symbols / emoji BETWEEN words, leaving them to pop in instantly),
        // this also emits the inter-word gaps + leading/trailing separators so
        // EVERY character in the new range fades — matching Microsoft
        // SwiftStreamingMarkdown's `splitIntoWords`. We collect ranges first
        // (cheap, read-only) so we can bail before mutating on a huge paste.
        let nsString = targetStorage.string as NSString
        let wordRanges = Self.revealUnits(in: nsString, within: safeRange, cap: Self.maxAnimationUnits)

        // 超大批次不再整批放弃：只淡入尾部，前面的字立即显示。
        guard !wordRanges.isEmpty else { return }
        let units = wordRanges.count > Self.maxAnimatedWords
            ? Array(wordRanges.suffix(Self.maxAnimatedWords))
            : wordRanges

        let now = CACurrentMediaTime()
        let step = Self.stagger(forWordCount: units.count, backlog: words.count)
        // Each batch starts its ripple at `now` and overlaps any still-fading
        // earlier batch — this is what makes the reveal read as a steady,
        // natural flow rather than a queue that grows a longer and longer tail
        // the faster tokens arrive (Microsoft SwiftStreamingMarkdown does the
        // same: baseStartTime = CACurrentMediaTime() per batch).
        let baseStart = now

        // Batch all alpha-0 writes inside one begin/endEditing so TextKit only
        // posts a single processEditing pass for the whole appended tail.
        targetStorage.beginEditing()
        for (i, wr) in units.enumerated() {
            let original = currentForegroundColor(at: wr.location, in: targetStorage)
            let start = baseStart + CFTimeInterval(i) * step
            words.append(FadeWord(
                range: wr,
                startTime: start,
                duration: Self.wordFadeDuration,
                originalColor: original
            ))
            // Seed at alpha 0.
            targetStorage.addAttribute(
                .foregroundColor,
                value: original.withAlphaComponent(0),
                range: wr
            )
        }
        targetStorage.endEditing()

        requestRedraw()
        startDisplayLinkIfNeeded()
    }

    /// Cancel every in-flight fade and restore full opacity immediately. Called
    /// on a new message, rotation/width change, or any non-append update — the
    /// ranges we hold are no longer valid against the rebuilt storage.
    func cancelAll() {
        stopDisplayLink()
        // Snap any partially-faded words to their final color so nothing is
        // left stuck translucent. The owner MUST call this BEFORE replacing
        // storage contents or scheduling the next generation: a bounds check
        // cannot detect stale ranges that still fit inside the new text.
        if let storage, !words.isEmpty {
            let len = storage.length
            storage.beginEditing()
            for w in words where w.range.location + w.range.length <= len {
                storage.addAttribute(.foregroundColor, value: w.originalColor, range: w.range)
            }
            storage.endEditing()
            requestRedraw()
        }
        words.removeAll(keepingCapacity: true)
    }

    // MARK: - Frame loop

    private func startDisplayLinkIfNeeded() {
        guard displayLink == nil, !words.isEmpty else { return }
        let link = CADisplayLink(target: self, selector: #selector(tick))
        // Allow the system to pick within 30–120Hz, preferring 60. The fade is
        // smooth at 30 and we don't need to force 120Hz battery cost.
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 30, maximum: 120, preferred: 60)
        link.add(to: .main, forMode: .common)
        displayLink = link
    }

    private func stopDisplayLink() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func tick() {
        guard let storage else {
            stopDisplayLink()
            words.removeAll(keepingCapacity: true)
            return
        }
        let now = CACurrentMediaTime()
        let storageLen = storage.length

        var completed: [Int] = []
        storage.beginEditing()
        for (i, w) in words.enumerated() {
            // Stale range guard — a racing edit could have invalidated it.
            guard w.range.location + w.range.length <= storageLen else {
                completed.append(i)
                continue
            }
            let elapsed = now - w.startTime
            if elapsed <= 0 {
                continue // not started yet (still inside its stagger delay)
            }
            let t = min(1, elapsed / w.duration)
            let eased = Self.easeOutCubic(t)
            let color = w.originalColor.withAlphaComponent(CGFloat(eased))
            storage.addAttribute(.foregroundColor, value: color, range: w.range)
            if t >= 1 {
                // Restore the exact original (avoids float-rounding leaving a
                // hair under full opacity) and retire the word.
                storage.addAttribute(.foregroundColor, value: w.originalColor, range: w.range)
                completed.append(i)
            }
        }
        storage.endEditing()

        if !completed.isEmpty {
            // Remove from the back so earlier indices stay valid.
            for i in completed.reversed() {
                words.remove(at: i)
            }
        }

        requestRedraw()

        if words.isEmpty {
            stopDisplayLink()
        }
    }

    // MARK: - Helpers

    /// ease-out cubic: `1 - (1 - t)³`. Fast start, gentle settle.
    private static func easeOutCubic(_ t: CFTimeInterval) -> CFTimeInterval {
        let inv = 1 - t
        return 1 - inv * inv * inv
    }

    /// Split `range` of `string` into contiguous reveal units that together
    /// cover EVERY character — words PLUS the punctuation / whitespace /
    /// symbol / emoji gaps between and around them. A bare `.byWords`
    /// enumeration skips those gaps, so they'd pop in at full opacity instead
    /// of fading; this mirrors Microsoft SwiftStreamingMarkdown's
    /// `splitIntoWords`, which appends leading / inter-word / trailing gaps as
    /// their own ranges. Returns empty if the unit count would exceed `cap`
    /// (caller then skips the animation for that oversized batch). Falls back
    /// to the whole range as a single unit when no word boundary is found
    /// (e.g. a pure-symbol / emoji-only tail).
    private static func revealUnits(in string: NSString, within range: NSRange, cap: Int) -> [NSRange] {
        var units: [NSRange] = []
        var overflow = false
        let appendGap = { (start: Int, end: Int) in
            if end > start { units.append(NSRange(location: start, length: end - start)) }
        }
        string.enumerateSubstrings(in: range, options: [.byWords, .localized, .substringNotRequired]) { _, wordRange, _, stop in
            // Gap before this word: trailing edge of the previous unit (or the
            // range start) up to the word's start.
            let gapStart = units.last.map { NSMaxRange($0) } ?? range.location
            appendGap(gapStart, wordRange.location)
            units.append(wordRange)
            if units.count > cap { overflow = true; stop.pointee = true }
        }
        if overflow { return [] }
        // Trailing separators after the last word (or the whole range if there
        // were no words at all — pure punctuation / emoji).
        let tailStart = units.last.map { NSMaxRange($0) } ?? range.location
        appendGap(tailStart, NSMaxRange(range))
        if units.count > cap { return [] }
        return units
    }

    /// The foreground color a glyph currently carries, defaulting to label.
    /// We read it (rather than assuming `.label`) so colored inline spans —
    /// links, syntax-highlighted code, custom-styled runs — fade back to their
    /// real color rather than to black.
    private func currentForegroundColor(at location: Int, in storage: NSTextStorage) -> UIColor {
        guard location >= 0, location < storage.length else { return .label }
        if let c = storage.attribute(.foregroundColor, at: location, effectiveRange: nil) as? UIColor {
            return c
        }
        return .label
    }
}
