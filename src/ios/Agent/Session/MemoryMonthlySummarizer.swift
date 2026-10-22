import Foundation

// MARK: - [T-memory-monthly-ai] Monthly memory digest

/// One month of memory compressed by a model.
///
/// `month` uses the same `yyyy-MM` stamp that `MemoryMaintenance` puts on
/// `YYYY-MM.md`, so a digest can be written next to (or over) that file
/// without inventing a second naming scheme. `sourceDays` is how many
/// distinct daily files actually contributed text — the same number the
/// mechanical merge reports as 「由 N 份日记忆合并」.
struct MonthlyMemoryDigest: Equatable, Sendable {
    let month: String
    let summary: String
    let sourceDays: Int
}

/// Failures a caller can act on. Both are terminal for the attempt and
/// recoverable on the next one (more input, or another model), so neither
/// wraps an underlying error.
enum MonthlySummaryError: LocalizedError, Equatable {
    /// No daily file was passed, or every one of them was blank.
    case emptyInput
    /// The model returned successfully with nothing but whitespace.
    case emptySummary

    var errorDescription: String? {
        switch self {
        case .emptyInput:
            return "这个月还没有可用的日记忆，暂时无法生成月记忆摘要。"
        case .emptySummary:
            return "模型返回了空摘要，请重试或换一个模型。"
        }
    }
}

/// Prompt building and answer shaping for the 「月记忆」 AI summary.
/// The existing `MemoryMaintenance` pass is deliberately mechanical: it
/// concatenates older daily files into `YYYY-MM.md` and builds a first-line
/// index. This type is the other half — it decides WHAT to ask a model and
/// WHAT counts as a usable answer, and nothing else:
///
/// - no `LLMProvider`, no `URLSession`: the model call is injected as the
///   `summarize` closure, so the caller keeps choosing provider, model and
///   fallbacks (see `AIChatViewModel+Compaction.swift` for that policy);
/// - no `UserDefaults` and no `FileManager`: the caller reads the daily files
///   and decides when to write `YYYY-MM.md`;
/// - no `@MainActor`: a month of text is prepared off the main thread, and
///   awaiting a caller-supplied closure needs no actor hop of its own.
///
/// Keeping those three dependencies out is also what makes the whole thing
/// testable without a device: tests inject a fake `summarize` and assert on
/// the prompt string.
enum MemoryMonthlySummarizer {

    /// Appended to a day whose text did not fit. Short because it repeats for
    /// every clipped day, and the instruction block tells the model exactly
    /// what it means.
    static let truncationMarker = "…（已截断）"

    // MARK: Prompt

    /// Build the single user-role prompt for one month.
    ///
    /// `maxChars` (default 24000) is a ceiling on the whole prompt, counted in
    /// `Character`s — what the user perceives as characters — not UTF-8 bytes.
    /// A typical month of daily notes is far below it; the cap exists so one
    /// unusually chatty month cannot overflow a small model's context window.
    /// The rule block itself is never cut: when `maxChars` cannot fit the
    /// rules plus one day body, the prompt is the rule block alone.
    ///
    /// Each day keeps its `## YYYY-MM-DD` heading even when its body is
    /// clipped, because the date is what makes a summary checkable later
    /// against `archive/raw/YYYY-MM/`. The budget is spent in this order:
    /// instruction block, then headings, then day bodies. Bodies get an equal
    /// share first and whatever short days leave unused is handed to the long
    /// ones in one extra pass — two passes, no loop, no oscillation.
    ///
    /// Pure and total: no I/O, no throws, same input → same prompt.
    static func makePrompt(month: String,
                           dailyTexts: [(day: String, text: String)],
                           maxChars: Int = 24000) -> String {
        let stamp = month.trimmingCharacters(in: .whitespacesAndNewlines)
        let entries = normalized(dailyTexts)
        let instruction = instructionBlock(month: stamp, dayCount: entries.count)

        guard !entries.isEmpty else {
            // `digest` refuses this case; a direct caller still gets a
            // well-formed prompt instead of a rules-only string.
            return instruction + "\n\n（本月没有可用的日记忆。）"
        }

        // Everything fixed comes out of the budget before any body is
        // clipped, so a heading can never be cut in half.
        let headingCost = entries.reduce(0) { $0 + $1.day.count + 4 }   // "## " + day + "\n"
        let joinCost = 2 + 2 * (entries.count - 1)                     // gap after rules + between blocks
        let markerCost = entries.count * (truncationMarker.count + 1)  // every body may be clipped
        let bodyBudget = maxChars - instruction.count - headingCost - joinCost - markerCost
        guard bodyBudget > 0 else {
            // Degenerate budget: rules only. Never slice the rules to fit.
            return instruction
        }

        let share = bodyBudget / entries.count
        var spare = 0
        var longCount = 0
        for entry in entries {
            if entry.text.count > share {
                longCount += 1
            } else {
                spare += share - entry.text.count
            }
        }
        let cap = share + (longCount > 0 ? spare / longCount : 0)

        var blocks: [String] = []
        blocks.reserveCapacity(entries.count)
        for entry in entries {
            let body = entry.text.count > cap
                ? String(entry.text.prefix(cap)) + truncationMarker
                : entry.text
            blocks.append("## \(entry.day)\n\(body)")
        }

        let prompt = instruction + "\n\n" + blocks.joined(separator: "\n\n")

        // Backstop for the arithmetic above: clip the variable tail rather
        // than the rules. Never below the instruction block itself.
        guard prompt.count > maxChars else { return prompt }
        return String(prompt.prefix(max(maxChars, instruction.count)))
    }

    // MARK: Digest

    /// Ask the injected model call for a month summary.
    ///
    /// The only side effect is `summarize(prompt)`: this function performs no
    /// network request, touches no defaults and writes no file. It throws
    /// `.emptyInput` before calling the model when there is nothing to
    /// summarize (never spend a request on an empty month), and
    /// `.emptySummary` when the model answers with whitespace — a blank
    /// answer must not overwrite a real `YYYY-MM.md`.
    ///
    /// `sourceDays` counts distinct days whose text survived normalization,
    /// so it matches the number of `## day` headings in the prompt.
    static func digest(month: String,
                       dailyTexts: [(day: String, text: String)],
                       maxChars: Int = 24000,
                       summarize: (String) async throws -> String) async throws -> MonthlyMemoryDigest {
        let stamp = month.trimmingCharacters(in: .whitespacesAndNewlines)
        let entries = normalized(dailyTexts)
        guard !entries.isEmpty else { throw MonthlySummaryError.emptyInput }

        let prompt = makePrompt(month: stamp, dailyTexts: entries, maxChars: maxChars)
        let answer = try await summarize(prompt)
        let summary = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !summary.isEmpty else { throw MonthlySummaryError.emptySummary }

        return MonthlyMemoryDigest(month: stamp, summary: summary, sourceDays: entries.count)
    }

    // MARK: Helpers

    /// Trim every body, drop blank ones, and keep one entry per day (first
    /// occurrence wins).
    ///
    /// A duplicate day is a caller bug — an unsorted directory scan that saw
    /// the same file twice — and would otherwise be paid for twice in the
    /// prompt budget and counted twice in `sourceDays`. A blank date label
    /// becomes one shared 「未标注日期」 heading instead of dropping the text.
    private static func normalized(_ dailyTexts: [(day: String, text: String)]) -> [(day: String, text: String)] {
        var seen = Set<String>()
        var entries: [(day: String, text: String)] = []
        entries.reserveCapacity(dailyTexts.count)
        for item in dailyTexts {
            let text = item.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            let rawDay = item.day.trimmingCharacters(in: .whitespacesAndNewlines)
            let day = rawDay.isEmpty ? "未标注日期" : rawDay
            guard seen.insert(day).inserted else { continue }
            entries.append((day: day, text: text))
        }
        return entries
    }

    /// The rules half of the prompt, independent of the month's content.
    ///
    /// Four things are stated on purpose and must not be softened:
    /// summarize only (no preamble, no reasoning dump), keep decisions /
    /// preferences / unfinished work, never fabricate, and write in Chinese.
    private static func instructionBlock(month: String, dayCount: Int) -> String {
        let label = month.isEmpty ? "本月" : month
        return """
        你在整理月记忆：下面是 \(label) 的 \(dayCount) 份日记忆原文，每份以「## 日期」开头。

        请把整月内容压缩成一份月记忆摘要，规则如下：
        1. 只输出摘要正文，不要复述本提示，不要输出思考过程，不要加开场白，也不要用代码块包裹。
        2. 必须保留：已经做出的决定、用户的偏好与习惯、未完成的事项（待办、卡住的地方、说好要再做一次的）。
        3. 不得编造：只能依据下面的原文，不要补充原文没有的事实、日期、数字、链接或结论；原文没写清楚的就略过，不要推测，也不要虚构用户没有说过的偏好。
        4. 部分日记忆因为长度上限被截断，末尾标有「\(truncationMarker)」；看到这个标记就当作原文到这里为止，不要顺着猜测补全。
        5. 合并重复内容，按主题归类，同一件事只写一次。
        6. 用中文书写；引用具体事情时沿用原文的 YYYY-MM-DD 日期，例如（YYYY-MM-DD）。
        7. 篇幅控制在 400-800 字；原文信息很少时可以更短，但不要交白卷。

        建议结构（没有内容的段落直接省略，不要为了凑格式而编造）：
        ## \(label) 月记忆摘要
        ### 决定
        ### 偏好
        ### 未完成
        ### 其他
        """
    }
}