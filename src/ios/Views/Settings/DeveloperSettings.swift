//
//  DeveloperSettings.swift
//  Minis
//
//  [T-developer-section] Developer & reverse-engineering settings, modelled on
//  the layout the user asked for: one "开发者" section (terminal identity,
//  GitHub connection, context window, host access) and one "逆向工具" section
//  (reverse analysis, proxy capture). Icons deliberately reuse this app's own
//  row style — a white SF Symbol in a 21pt coloured circle — not the other
//  app's artwork.
//

import Foundation
import SwiftUI
import UIKit

/// iOS 15-safe replacement for `LabeledContent` (iOS 16+).
private struct InfoRow: View {
    let title: String
    let value: String
    var body: some View {
        HStack {
            Text(title)
            Spacer(minLength: 12)
            Text(value).foregroundStyle(.secondary)
        }
    }
}

// MARK: - 逆向分析

struct ReverseAnalysisView: View {
    @State private var copied = false

    private let prompt = "帮我做逆向分析：先用越狱 MCP 列出已安装 App，取目标 App 的二进制，再用 radare2 输出函数列表和关键函数的伪代码。"

    var body: some View {
        List {
            Section("引擎") {
                InfoRow(title: "反汇编", value: "radare2 5.9.8")
                InfoRow(title: "伪代码", value: "pdc（r2ghidra 需另编）")
                InfoRow(title: "目标来源", value: "越狱 MCP：已安装 App")
            }

            Section {
                Button {
                    UIPasteboard.general.string = prompt
                    copied = true
                } label: {
                    Label(copied ? "已复制，去对话里粘贴" : "复制分析指令",
                          systemImage: copied ? "checkmark.circle.fill" : "doc.on.doc")
                }
            } footer: {
                Text("把指令粘贴到对话里，AI 会通过越狱 MCP 枚举 App、提取二进制并调用 radare2。需要越狱环境在线。")
            }

            Section("用法") {
                Text("1. 在对话里说「分析 <App 名>」")
                Text("2. AI 用 MCP 找到 .app 的主二进制")
                Text("3. r2 执行 aaa → afl → pdf/pdc")
                Text("4. 输出函数列表与关键路径伪代码")
            }
            .font(.footnote)
            .foregroundStyle(.secondary)
        }
        .navigationTitle("逆向分析")
        .navigationBarTitleDisplayMode(.inline)
    }
}
