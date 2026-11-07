import CoreFoundation
import Foundation

/// Files belong only to MiniSight, not the App's general logs. Every response
/// must match this request's nonce. The pet is preferred in foreground too.
@MainActor
final class MiniSightConfirmBridge {
    static let shared = MiniSightConfirmBridge()
    private var busy = false
    private static let note = "com.openminis.minisight.confirm"
    private static let cancelNote = "com.openminis.minisight.confirm.cancel"

    private var directory: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MiniSight", isDirectory: true)
    }

    static func confirm(command: String) async -> Bool {
        await shared.confirmOwned(command)
    }

    private func confirmOwned(_ command: String) async -> Bool {
        // Concurrent tools queue rather than reject a second request silently.
        while busy {
            do { try await Task.sleep(nanoseconds: 100_000_000) } catch { return false }
        }
        guard !Task.isCancelled else { return false }
        busy = true
        defer { busy = false }
        let id = UUID().uuidString
        let dir = directory
        let defaults = UserDefaults.standard
        let shown = (try? String(contentsOf: dir.appendingPathComponent("shown"), encoding: .utf8)) ?? "0"
        let usesPlugin = defaults.integer(forKey: "minisight.renderer") == 0
        let petStyle = defaults.integer(forKey: "minisight.style") == 1
        if usesPlugin && petStyle && shown.trimmingCharacters(in: .whitespacesAndNewlines) == "1" {
            if let result = await requestPet(command, id: id, directory: dir) { return result }
        } else {
            log("route", "ok", id: id, reason: "pet_unavailable", route: "modal")
        }
        guard !Task.isCancelled else { return false }
        // This fallback is intentional: with no pet/plugin the App must still
        // be able to approve commands. An explicit denial never falls back.
        let result = await MiniSightHostAdapter.confirm(command: command)
        log("answer", "ok", id: id, reason: result ? "allow" : "deny", route: "modal")
        return !Task.isCancelled && result
    }

    /// nil = no visible pet UI (use App). false = explicit denial/cancel/timeout.
    private func requestPet(_ command: String, id: String, directory dir: URL) async -> Bool? {
        guard command.lengthOfBytes(using: .utf8) <= 65536 else {
            log("route", "skipped", id: id, reason: "oversized_command", route: "modal")
            return nil
        }
        guard await probeJailbreakPlugin(id: id, directory: dir) else {
            log("route", "skipped", id: id, reason: "plugin_no_reply", route: "modal")
            return nil
        }
        let action = MiniSightHostAdapter.commandTitle(command)
        do {
            try await Task.detached(priority: .userInitiated) {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let resultURL = dir.appendingPathComponent("confirm-result.txt")
                try? FileManager.default.removeItem(at: resultURL)
                try? FileManager.default.removeItem(at: dir.appendingPathComponent("confirm-shown.txt"))
                let data = try JSONSerialization.data(withJSONObject: ["id": id, "command": command, "action": action])
                try data.write(to: dir.appendingPathComponent("confirm.json"), options: .atomic)
            }.value
        } catch {
            log("request", "failed", id: id, reason: "write_failed", route: "modal")
            return nil
        }
        guard !Task.isCancelled else { await cancelPet(id, directory: dir); return false }
        // Post FIRST, then await an acknowledgment. The previous candidate did
        // the reverse, making every request time out without ever showing it.
        Self.post(Self.note)
        log("request", "pending", id: id, reason: "sent", route: "pet")
        let deadline = Date().addingTimeInterval(60)
        let ackDeadline = Date().addingTimeInterval(1.5)
        var acknowledged = false
        while Date() < deadline {
            if Task.isCancelled { await cancelPet(id, directory: dir); return false }
            let state = await Task.detached(priority: .utility) { () -> (Bool, Bool?) in
                let ack = (try? String(contentsOf: dir.appendingPathComponent("confirm-shown.txt"), encoding: .utf8))?
                    .trimmingCharacters(in: .whitespacesAndNewlines) == id
                let text = (try? String(contentsOf: dir.appendingPathComponent("confirm-result.txt"), encoding: .utf8)) ?? ""
                let parts = text.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: ":")
                let result: Bool? = parts.count == 2 && parts[0] == Substring(id) && (parts[1] == "1" || parts[1] == "0")
                    ? parts[1] == "1" : nil
                return (ack, result)
            }.value
            if let result = state.1 {
                log("answer", "ok", id: id, reason: result ? "allow" : "deny", route: "pet")
                return !Task.isCancelled && result
            }
            if state.0 && !acknowledged {
                acknowledged = true
                log("show", "ok", id: id, reason: "visible_ack", route: "pet")
            }
            if !acknowledged && Date() >= ackDeadline {
                await cancelPet(id, directory: dir)
                log("route", "skipped", id: id, reason: "no_visible_ack", route: "modal")
                return nil
            }
            do { try await Task.sleep(nanoseconds: 100_000_000) }
            catch { await cancelPet(id, directory: dir); return false }
        }
        await cancelPet(id, directory: dir)
        log("finish", "failed", id: id, reason: "timeout", route: "pet")
        return false
    }

    private func probeJailbreakPlugin(id: String, directory dir: URL) async -> Bool {
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try Data(id.utf8).write(to: dir.appendingPathComponent("plugin-probe.txt"), options: .atomic)
            Self.post("com.openminis.minisight.plugin-probe")
            for _ in 0..<5 {
                try Task.checkCancellation()
                try await Task.sleep(nanoseconds: 100_000_000)
                let reply = try? String(contentsOf: dir.appendingPathComponent("plugin-probe-reply.txt"), encoding: .utf8)
                if reply == id { return true }
            }
        } catch { return false }
        return false
    }

    private func cancelPet(_ id: String, directory dir: URL) async {
        await Task.detached(priority: .utility) {
            try? Data(id.utf8).write(to: dir.appendingPathComponent("confirm-cancel.txt"), options: .atomic)
        }.value
        Self.post(Self.cancelNote)
    }
    private static func post(_ name: String) {
        CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }
    private func log(_ stage: String, _ result: String, id: String, reason: String, route: String) {
        MSDiagEvent("approval", stage, result, ["source": "app", "request": id, "reason": reason, "route": route])
    }
}
