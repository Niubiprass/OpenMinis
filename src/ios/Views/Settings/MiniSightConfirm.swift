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

import CoreFoundation
import Foundation
import UIKit

private enum MiniSightPetAvailability {
    static var appDirectory: URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("MiniSight", isDirectory: true)
    }

    static var isOnScreen: Bool {
        let defaults = UserDefaults.standard
        guard defaults.integer(forKey: "minisight.style") == 1,
              let dir = appDirectory else { return false }
        let shown = (try? String(contentsOf: dir.appendingPathComponent("shown"), encoding: .utf8)) ?? "1"
        return shown != "0" && FileManager.default.fileExists(atPath: dir.appendingPathComponent("pet.png").path)
    }

    static func probeJailbreakPlugin() async -> Bool {
        guard let dir = appDirectory else { return false }
        let nonce = UUID().uuidString
        let replyURL = dir.appendingPathComponent("plugin-probe-reply.txt")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: replyURL)
            try Data(nonce.utf8).write(to: dir.appendingPathComponent("plugin-probe.txt"), options: .atomic)
            CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                CFNotificationName("com.openminis.minisight.plugin-probe" as CFString), nil, nil, true)
            for _ in 0..<5 {
                try Task.checkCancellation()
                try await Task.sleep(nanoseconds: 100_000_000)
                if (try? String(contentsOf: replyURL, encoding: .utf8)) == nonce { return true }
            }
        } catch { return false }
        return false
    }
}

@MainActor
final class MiniSightConfirmBridge {
    static let shared = MiniSightConfirmBridge()

    private static let confirmName = "com.openminis.minisight.confirm"
    private static let resultName = "com.openminis.minisight.confirm.result"
    private static let cancelName = "com.openminis.minisight.confirm.cancel"

    private var continuation: CheckedContinuation<Bool, Never>?
    private var requestId: String?
    private var timeoutWork: DispatchWorkItem?
    private var observing = false
    private var requestInFlight = false

    private var dir: URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("MiniSight", isDirectory: true)
    }

    static func confirm(command: String) async -> Bool {
        let renderer = await MainActor.run {
            UserDefaults.standard.integer(forKey: "minisight.renderer")
        }
        guard renderer == 0 else {
            return await MCPApprovalDialog.confirm(command)
        }
        let pluginAvailable = await MiniSightPetAvailability.probeJailbreakPlugin()
        let petAvailable = MiniSightPetAvailability.isOnScreen && pluginAvailable
        guard petAvailable else {
            return await MCPApprovalDialog.confirm(command)
        }
        return await shared.request(command: command)
    }

    private func request(command: String) async -> Bool {
        guard !requestInFlight else { return false }
        guard command.lengthOfBytes(using: .utf8) <= 8192 else { return false }
        guard let dir else { return await MCPApprovalDialog.confirm(command) }
        requestInFlight = true
        installObserverIfNeeded()
        let id = UUID().uuidString
        requestId = id
        let action = AIChatViewModel.describeMCPCommand(command).title
        do {
            try await Task.detached(priority: .userInitiated) {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let resultURL = dir.appendingPathComponent("confirm-result.txt")
                try? FileManager.default.removeItem(at: resultURL)
                let payload: [String: String] = ["id": id, "command": command, "action": action]
                let data = try JSONSerialization.data(withJSONObject: payload)
                try data.write(to: dir.appendingPathComponent("confirm.json"), options: .atomic)
            }.value
        } catch {
            requestInFlight = false
            requestId = nil
            return await MCPApprovalDialog.confirm(command)
        }
        guard !Task.isCancelled else {
            requestInFlight = false
            requestId = nil
            return false
        }

        return await withTaskCancellationHandler {
            await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
                continuation = cont
                let work = DispatchWorkItem { [weak self] in self?.finish(false, cancelPet: true) }
                timeoutWork = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 60, execute: work)
                post(Self.confirmName)
            }
        } onCancel: { [weak self] in
            Task { @MainActor in self?.finish(false, cancelPet: true) }
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

    private func finish(_ allowed: Bool, cancelPet: Bool = false) {
        guard let cont = continuation else { return }
        let id = requestId
        if cancelPet, let id, let dir {
            let url = dir.appendingPathComponent("confirm-cancel.txt")
            let cancelName = Self.cancelName
            Task.detached(priority: .utility) {
                try? Data(id.utf8).write(to: url, options: .atomic)
                CFNotificationCenterPostNotification(
                    CFNotificationCenterGetDarwinNotifyCenter(),
                    CFNotificationName(cancelName as CFString), nil, nil, true)
            }
        }
        continuation = nil
        requestId = nil
        requestInFlight = false
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
