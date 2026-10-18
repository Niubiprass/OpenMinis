import SwiftUI
import Combine

// MARK: - [T-115-ask-card] Inline question card (App Store 1.15 "向用户提问")

/// Renders an `ask_user` block as a card.
///
/// Interactive while the vm still holds the matching `activeQuestionCard`
/// (status == "pending" and toolUseId matches): every question is answered by
/// free text or options, and "提交回答" resumes the suspended run with the
/// answers JSON. Afterwards the card is read-only: an answer summary on
/// success, an "unconfirmed" notice on timeout / cancel / run stop.
struct QuestionCardView: View {
    @ObservedObject var block: AssistantBlock
    @EnvironmentObject private var vm: AIChatViewModel

    struct CardQuestion {
        let id: String
        let text: String
        let options: [String]
    }

    struct CardPayload {
        let status: String
        let questions: [CardQuestion]
        let answers: [String: String]
    }

    @State private var textAnswers: [String: String] = [:]
    @State private var optionSelection: [String: String] = [:]

    private var payload: CardPayload? {
        guard let data = block.content.data(using: .utf8),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            return nil
        }
        let rawQuestions = (obj["questions"] as? [[String: Any]]) ?? []
        let questions = rawQuestions.compactMap { q -> CardQuestion? in
            guard let id = q["id"] as? String, let text = q["question"] as? String else { return nil }
            return CardQuestion(id: id, text: text, options: (q["options"] as? [String]) ?? [])
        }
        return CardPayload(
            status: (obj["status"] as? String) ?? "pending",
            questions: questions,
            answers: (obj["answers"] as? [String: String]) ?? [:]
        )
    }

    /// True while the run is genuinely waiting on THIS card.
    private var isLive: Bool {
        payload?.status == "pending"
            && block.toolUseId != nil
            && vm.activeQuestionCard?.toolUseId == block.toolUseId
    }

    private var allAnswered: Bool {
        guard let p = payload else { return false }
        return p.questions.allSatisfy { q in
            if let choice = optionSelection[q.id], !choice.isEmpty { return true }
            if let text = textAnswers[q.id], !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return true }
            return false
        }
    }

    private func submit() {
        guard let p = payload else { return }
        var merged: [String: String] = [:]
        for q in p.questions {
            if let choice = optionSelection[q.id], !choice.isEmpty {
                merged[q.id] = choice
            } else if let text = textAnswers[q.id] {
                merged[q.id] = text.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        vm.submitQuestionAnswers(merged)
    }

    var body: some View {
        Group {
            if let p = payload {
                cardBody(p)
            } else {
                // Malformed payload — a plain muted line is safer than a crash.
                HStack(spacing: 8) {
                    Image(systemName: "questionmark.circle")
                        .foregroundColor(.secondary)
                    Text("向你提问").font(.subheadline).foregroundColor(.secondary)
                }
                .padding(.vertical, 6)
            }
        }
    }

    @ViewBuilder
    private func cardBody(_ p: CardPayload) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            headerRow(p)
            if isLive {
                liveBody(p)
            } else if p.status == "answered" {
                answeredBody(p)
            } else {
                unconfirmedBody(p)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(.secondarySystemBackground))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Color(.separator).opacity(0.5), lineWidth: 0.5)
        )
    }

    // MARK: Header

    private func headerRow(_ p: CardPayload) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "questionmark.circle.fill")
                .foregroundColor(Color.accentColor)
                .font(.system(size: 16))
            Text("向你提问")
                .font(.subheadline.weight(.semibold))
                .foregroundColor(.primary)
            Spacer(minLength: 0)
            statusPill(p)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
    }

    @ViewBuilder
    private func statusPill(_ p: CardPayload) -> some View {
        let (label, tint): (String, Color) = {
            if isLive { return ("等待回答", Color.accentColor) }
            if p.status == "answered" { return ("已确认", Color.green) }
            if p.status == "timeout" { return ("未确认", Color.red) }
            return ("已结束", Color.gray)
        }()
        Text(label)
            .font(.caption2.weight(.semibold))
            .foregroundColor(tint)
            .padding(.horizontal, 9)
            .padding(.vertical, 3)
            .background(Capsule().fill(tint.opacity(0.12)))
    }

    // MARK: Live (interactive)

    private func liveBody(_ p: CardPayload) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(p.questions.enumerated()), id: \.element.id) { index, q in
                questionBlock(index: index, q: q)
            }
            Button(action: submit) {
                Text("提交回答")
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 9)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(allAnswered ? Color.accentColor : Color.accentColor.opacity(0.35))
                    )
            }
            .disabled(!allAnswered)
            Button(action: { vm.cancelQuestionCard() }) {
                Text("暂不回答，继续")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity)
            }
            .padding(.top, -2)
            Text("AI 会一直等待你的回答；10 分钟后未作答将视为「未确认」")
                .font(.caption2)
                .foregroundColor(.secondary)
                .frame(maxWidth: .infinity)
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
    }

    @ViewBuilder
    private func questionBlock(index: Int, q: CardQuestion) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(index + 1) · \(q.text)")
                .font(.subheadline)
                .foregroundColor(.primary)
                .fixedSize(horizontal: false, vertical: true)
            if q.options.isEmpty {
                TextField("输入回答…", text: Binding(
                    get: { textAnswers[q.id] ?? "" },
                    set: { textAnswers[q.id] = $0 }
                ))
                .font(.subheadline)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(Color(.systemBackground))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .strokeBorder(Color(.separator).opacity(0.6), lineWidth: 0.5)
                )
            } else {
                VStack(spacing: 5) {
                    ForEach(q.options, id: \.self) { opt in
                        let selected = optionSelection[q.id] == opt
                        Button {
                            optionSelection[q.id] = opt
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                                    .foregroundColor(selected ? Color.accentColor : Color(.secondaryLabel))
                                Text(opt)
                                    .font(.subheadline)
                                    .foregroundColor(.primary)
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: 9, style: .continuous)
                                    .fill(selected ? Color.accentColor.opacity(0.09) : Color(.systemBackground))
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 9, style: .continuous)
                                    .strokeBorder(
                                        selected ? Color.accentColor.opacity(0.7) : Color(.separator).opacity(0.6),
                                        lineWidth: selected ? 1 : 0.5
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    // MARK: Answered (read-only summary)

    private func answeredBody(_ p: CardPayload) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(p.questions, id: \.id) { q in
                let answer = p.answers[q.id] ?? "—"
                HStack(alignment: .top, spacing: 6) {
                    Text(q.text)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 8)
                    Text(answer)
                        .font(.caption.weight(.medium))
                        .foregroundColor(.primary)
                        .multilineTextAlignment(.trailing)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(Color(.systemBackground))
                )
            }
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
    }

    // MARK: Unconfirmed (timeout / cancel / run stopped)

    private func unconfirmedBody(_ p: CardPayload) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "clock.badge.exclamationmark")
                .foregroundColor(.orange)
            Text("没有收到回答，已按「未确认」继续。")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
    }
}