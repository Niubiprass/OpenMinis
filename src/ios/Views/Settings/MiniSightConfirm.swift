//
//  MiniSightConfirm.swift
//  Minis
//
//  Destructive MCP calls (run_command / write_file / uninstall_app) need a
//  yes/no. When the desktop pet is on screen the question is asked **in its
//  speech bubble** (the tweak draws the buttons); when there is no pet we fall
//  back to the modal dialog so the call can never hang without a UI.
//
//  App <-> tweak protocol (files in Documents/MiniSight, Darwin notifications):
//    confirm.json  {id, command, action}   app -> tweak
//    com.openminis.minisight.confirm       app -> tweak "show it"
//    confirm-result.txt  "<id>:1|0"        tweak -> app
//    com.openminis.minisight.confirm.result tweak -> app "answered"
//

import Foundation
import UIKit

enum MiniSightPetAvailability {
    static var isOnScreen: Bool {
        let defaults = UserDefaults.standard
        guard defaults.integer(forKey: "minisight.style") == 1 else { return false }
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("MiniSight", isDirectory: true)
        guard let dir else { return false }
        let shown = (try? String(contentsOf: dir.appendingPathComponent("shown"), encoding: .utf8)) ?? "1"
        guard shown != "0" else { return false }
        return FileManager.default.fileExists(atPath: dir.appendingPathComponent("pet.png").path)
    }
}

final class MiniSightConfirmBridge {
    static let shared = MiniSightConfirmBridge()

    private static let confirmName = "com.openminis.minisight.confirm"
    private static let resultName = "com.openminis.minisight.confirm.result"

    private var continuation: CheckedContinuation<Bool, Never>?
    private var requestId: String?
    private var timeoutWork: DispatchWorkItem?
    private var observing = false

    private var dir: URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("MiniSight", isDirectory: true)
    }

    static func confirm(command: String) async -> Bool {
        guard MiniSightPetAvailability.isOnScreen else {
            return await MCPApprovalDialog.confirm(command)
        }
        return await shared.request(command: command)
    }

    private func request(command: String) async -> Bool {
        installObserverIfNeeded()
        let id = UUID().uuidString
        requestId = id
        guard let dir else { return await MCPApprovalDialog.confirm(command) }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let payload: [String: String] = [
            "id": id,
            "command": command,
            "action": AIChatViewModel.describeMCPCommand(command).title,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: payload) {
            try? data.write(to: dir.appendingPathComponent("confirm.json"), options: .atomic)
        }
        post(Self.confirmName)

        return await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            continuation = cont
            let work = DispatchWorkItem { [weak self] in self?.finish(false) }
            timeoutWork = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 60, execute: work)
        }
    }

    private func installObserverIfNeeded() {
        guard !observing else { return }
        observing = true
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let observer = Unmanaged.passUnretained(self).toOpaque()
        CFNotificationCenterAddObserver(center, observer, { _, observer, _, _, _ in
            guard let observer else { return }
            let bridge = Unmanaged<MiniSightConfirmBridge>.fromOpaque(observer).takeUnretainedValue()
            DispatchQueue.main.async { bridge.readResult() }
        }, Self.resultName as CFString, nil, .deliverImmediately)
    }

    private func readResult() {
        guard let dir, let id = requestId else { return }
        guard let text = try? String(contentsOf: dir.appendingPathComponent("confirm-result.txt"), encoding: .utf8) else { return }
        let parts = text.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: ":")
        guard parts.count == 2, String(parts[0]) == id else { return }
        finish(parts[1] == "1")
    }

    private func finish(_ allowed: Bool) {
        guard let cont = continuation else { return }
        continuation = nil
        requestId = nil
        timeoutWork?.cancel()
        timeoutWork = nil
        cont.resume(returning: allowed)
    }

    private func post(_ name: String) {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }
}
