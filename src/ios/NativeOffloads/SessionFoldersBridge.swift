import Foundation
import CoreFoundation
import UIKit

private struct SessionFolderBridgeError: LocalizedError {
    let code: String
    let message: String
    var errorDescription: String? { message }
}

/// The guest thread waits on the semaphore; only its MainActor task writes this box.
private final class SessionFolderResult: @unchecked Sendable {
    var value: NSDictionary = [:]
}

@objc public class SessionFoldersBridge: NSObject {
    /// Synchronous native-offload entry point. Never block the main thread.
    @objc public static func perform(action: String, args: NSDictionary,
                                     callerSessionId: String?) -> NSDictionary {
        guard !Thread.isMainThread else {
            return failure("invalid_thread", "分组 CLI 必须由 guest thread 调用。")
        }
        do {
            let request = try Request(action: action, args: args, caller: callerSessionId)
            let semaphore = DispatchSemaphore(value: 0)
            let result = SessionFolderResult()
            Task { @MainActor in
                defer { semaphore.signal() }
                do { result.value = try await execute(request) as NSDictionary }
                catch let error as SessionFolderBridgeError {
                    result.value = failure(error.code, error.message)
                } catch {
                    result.value = failure("folder_operation_failed", error.localizedDescription)
                }
            }
            semaphore.wait()
            return result.value
        } catch let error as SessionFolderBridgeError {
            return failure(error.code, error.message)
        } catch {
            return failure("invalid_arguments", error.localizedDescription)
        }
    }

    private static func failure(_ code: String, _ message: String) -> NSDictionary {
        ["ok": false, "error": code, "message": message]
    }

    private static func require(_ condition: Bool, _ code: String, _ message: String) throws {
        if !condition { throw SessionFolderBridgeError(code: code, message: message) }
    }

    private static func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func sameName(_ lhs: String, _ rhs: String) -> Bool {
        trimmed(lhs).caseInsensitiveCompare(trimmed(rhs)) == .orderedSame
    }

    private struct Request: Sendable {
        let action: String
        let values: [String: String]
        let confirmed: Bool
        let caller: String?

        init(action: String, args: NSDictionary, caller: String?) throws {
            let keys: [String: Set<String>] = [
                "list": [], "get": ["id"], "create": ["name", "description"],
                "rename": ["id", "name", "description"], "pin": ["id", "pinned"],
                "move": ["ids", "target"], "merge": ["id", "target", "confirm"],
                "dissolve": ["id", "confirm"], "configure": ["id", "config-json"],
                "icon": ["id", "path"]
            ]
            guard let allowed = keys[action] else {
                throw SessionFolderBridgeError(code: "unknown_action", message: "未知分组命令：\(action)")
            }
            var strings: [String: String] = [:]
            var confirm = false
            for (key, value) in args {
                guard let key = key as? String, allowed.contains(key) else {
                    throw SessionFolderBridgeError(code: "invalid_arguments", message: "命令包含不支持的参数。")
                }
                if key == "confirm" {
                    guard let number = value as? NSNumber,
                          CFGetTypeID(number) == CFBooleanGetTypeID() else {
                        throw SessionFolderBridgeError(code: "invalid_arguments", message: "confirm 必须是布尔值。")
                    }
                    confirm = number.boolValue
                } else {
                    guard let string = value as? String else {
                        throw SessionFolderBridgeError(code: "invalid_arguments", message: "\(key) 必须是字符串。")
                    }
                    strings[key] = string
                }
            }
            self.action = action
            self.values = strings
            self.confirmed = confirm
            self.caller = caller
        }

        func required(_ key: String) throws -> String {
            let value = SessionFoldersBridge.trimmed(values[key] ?? "")
            try SessionFoldersBridge.require(!value.isEmpty, "invalid_arguments", "缺少 --\(key)。")
            return value
        }
    }

    @MainActor private static func resolve(_ selector: String, caller: String?,
                                           allowNone: Bool = false) async throws -> String? {
        if selector == "none" {
            try require(allowNone, "invalid_target", "none 仅用于 move --target none。")
            return nil
        }
        if selector == "current" {
            guard let caller else {
                throw SessionFolderBridgeError(code: "missing_caller", message: "无法识别调用会话。")
            }
            let context = try await ChatStore.shared.resolveFolderRuntimeContext(for: caller)
            guard let id = context.folderId else {
                throw SessionFolderBridgeError(code: "unfiled_caller", message: "调用会话没有当前分组。")
            }
            return id
        }
        let folders = await ChatStore.shared.listFolders()
        if let folder = folders.first(where: { $0.id.caseInsensitiveCompare(selector) == .orderedSame }) {
            return folder.id
        }
        let matches = folders.filter { sameName($0.name, selector) }
        try require(!matches.isEmpty, "folder_not_found", "分组不存在：\(selector)")
        try require(matches.count == 1, "ambiguous_folder", "分组名称重复，请使用明确的分组 UUID。")
        return matches[0].id
    }

    @MainActor private static func folderID(_ request: Request, key: String = "id") async throws -> String {
        guard let id = try await resolve(request.required(key), caller: request.caller) else {
            throw SessionFolderBridgeError(code: "folder_not_found", message: "未找到分组。")
        }
        return id
    }

    @MainActor private static func folder(_ id: String) async throws -> ChatFolder {
        guard let value = await ChatStore.shared.getFolder(id) else {
            throw SessionFolderBridgeError(code: "folder_not_found", message: "分组已不存在：\(id)")
        }
        return value
    }

    private static func configurationJSON(_ value: ChatFolderConfiguration) -> [String: Any] {
        ["skillDefaults": value.skillDefaults, "soulPrompt": value.soulPrompt as Any? ?? NSNull(),
         "memoryPolicy": value.memoryPolicy.rawValue, "readsGlobalMemory": value.readsGlobalMemory,
         "soulMode": value.soulMode as Any? ?? NSNull()]
    }

    @MainActor private static func summary(_ id: String, includeMembers: Bool = false) async throws -> [String: Any] {
        let value = try await folder(id)
        let config = try await ChatStore.shared.getFolderConfiguration(id)
        let ids = await ChatStore.shared.sessionIdsInFolder(id)
        var result: [String: Any] = ["id": id, "name": value.name,
            "description": value.desc as Any? ?? NSNull(), "member_count": ids.count,
            "pinned": value.isPinned, "memoryPolicy": config.memoryPolicy.rawValue]
        if includeMembers {
            result["members"] = try await sessions(ids).map { ["id": $0.id, "title": $0.title ?? "Untitled"] }
            result["configuration"] = configurationJSON(config)
        }
        return result
    }

    @MainActor private static func sessions(_ ids: [String], ordinaryOnly: Bool = false) async throws -> [ChatSession] {
        var result: [ChatSession] = []
        for id in ids {
            guard let session = await ChatStore.shared.getSession(id) else {
                throw SessionFolderBridgeError(code: "session_not_found", message: "会话不存在：\(id)")
            }
            try require(!ordinaryOnly || !session.isChild, "helper_session", "子代理会话不能作为普通会话移组：\(id)")
            result.append(session)
        }
        return result
    }

    @MainActor private static func verifyMembers(_ ids: [String], target: String?) async throws {
        for session in try await sessions(ids) {
            try require(session.folderId == target, "verification_failed",
                        "会话分组读回验证失败：\(session.id)；操作可能部分生效，请重新查询。")
        }
    }

    @MainActor private static func uniqueName(_ name: String, excluding id: String? = nil) async throws {
        let folders = await ChatStore.shared.listFolders()
        try require(!folders.contains { $0.id != id && sameName($0.name, name) },
                    "duplicate_name", "已有同名分组，请使用其他名称。")
    }

    private static func descriptionValue(_ text: String?) -> String? {
        guard let text else { return nil }
        let value = String(trimmed(text).prefix(100))
        return value.isEmpty ? nil : value
    }

    @MainActor private static func execute(_ request: Request) async throws -> [String: Any] {
        // Even a failed nonthrowing store mutation may have partially changed rows.
        defer {
            if request.action != "list" && request.action != "get" {
                NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
            }
        }
        switch request.action {
        case "list":
            var rows: [[String: Any]] = []
            for value in await ChatStore.shared.listFolders() {
                rows.append(try await summary(value.id))
            }
            return ["ok": true, "count": rows.count, "folders": rows]
        case "get":
            let id = try await folderID(request)
            return ["ok": true, "folder": try await summary(id, includeMembers: true)]
        case "create":
            let name = try request.required("name")
            try await uniqueName(name)
            let desc = descriptionValue(request.values["description"])
            let created = await ChatStore.shared.createFolder(name: name, desc: desc)
            let stored = try await folder(created.id)
            try require(stored.name == name && stored.desc == desc, "verification_failed", "新建分组读回验证失败。")
            return ["ok": true, "folder": try await summary(created.id)]
        case "rename":
            let id = try await folderID(request)
            let original = try await folder(id)
            let name = try request.required("name")
            try await uniqueName(name, excluding: id)
            let desc = request.values["description"]
            await ChatStore.shared.renameFolder(id, name: name, desc: desc)
            let stored = try await folder(id)
            let expectedDesc = desc == nil ? original.desc : descriptionValue(desc)
            try require(stored.name == name && stored.desc == expectedDesc,
                        "verification_failed", "重命名读回验证失败。")
            return ["ok": true, "folder": try await summary(id)]
        case "pin":
            let id = try await folderID(request)
            let flag = try request.required("pinned")
            try require(flag == "true" || flag == "false", "invalid_arguments", "--pinned 只能是 true 或 false。")
            let pinned = flag == "true"
            if try await folder(id).isPinned != pinned { _ = await ChatStore.shared.toggleFolderPin(id) }
            let stored = try await folder(id)
            try require(stored.isPinned == pinned, "verification_failed", "置顶状态读回验证失败。")
            return ["ok": true, "folder": try await summary(id)]
        case "move":
            return try await move(request)
        case "merge", "dissolve":
            return try await removeContainer(request)
        case "configure":
            let id = try await folderID(request)
            let original = try await ChatStore.shared.getFolderConfiguration(id)
            let draft = try patch(original, json: request.required("config-json"))
            let saved = try await ChatStore.shared.saveFolderConfiguration(id, configuration: draft, expected: original)
            let stored = try await ChatStore.shared.getFolderConfiguration(id)
            try require(stored == saved, "verification_failed", "配置读回验证失败；请重新查询。")
            return ["ok": true, "id": id, "configuration": configurationJSON(stored),
                    "message": "配置已保存，下一轮生效；记忆策略修改不会搬迁或复制已有记忆。"]
        case "icon":
            let id = try await folderID(request)
            _ = try await folder(id)
            let path = try request.required("path")
            let uri: String?
            if path == "none" {
                uri = nil
            } else {
                // ObjC resolves the guest input path to a host path before this call.
                guard let image = UIImage(contentsOfFile: path) else {
                    throw SessionFolderBridgeError(code: "invalid_image", message: "无法读取图像：\(path)")
                }
                switch SidebarIconImage.encode(image) {
                case .success(let value): uri = value
                case .failure: throw SessionFolderBridgeError(code: "invalid_image", message: "无法编码分组图像。")
                }
            }
            FolderIconStore.shared.setIcon(uri, for: id)
            let persisted = UserDefaults.standard.dictionary(forKey: "folderCustomIcons")?[id] as? String
            try require(FolderIconStore.shared.icon(for: id) == uri && persisted == uri,
                        "verification_failed", "分组图像读回验证失败。")
            return ["ok": true, "id": id, "has_icon": uri != nil]
        default:
            throw SessionFolderBridgeError(code: "unknown_action", message: "未知分组命令。")
        }
    }

    @MainActor private static func move(_ request: Request) async throws -> [String: Any] {
        let target = try await resolve(request.required("target"), caller: request.caller, allowNone: true)
        let destinationConfig: ChatFolderConfiguration
        if let target { destinationConfig = try await ChatStore.shared.getFolderConfiguration(target) }
        else { destinationConfig = .default }
        var ids: [String] = []
        for part in try request.required("ids").components(separatedBy: ",") {
            var id = trimmed(part)
            try require(!id.isEmpty, "invalid_arguments", "--ids 包含空会话 ID。")
            if id == "current" {
                guard let caller = request.caller else {
                    throw SessionFolderBridgeError(code: "missing_caller", message: "无法识别调用会话。")
                }
                id = caller
            }
            if !ids.contains(id) { ids.append(id) }
        }
        let members = try await sessions(ids, ordinaryOnly: true)
        let destinationScope = destinationConfig.memoryPolicy == .folder ? target : nil
        var scopeChanges: [String] = []
        for member in members {
            let context = try await ChatStore.shared.resolveFolderRuntimeContext(for: member.id)
            let scope = context.configuration.memoryPolicy == .folder ? context.folderId : nil
            if scope != destinationScope { scopeChanges.append(member.id) }
        }
        // Helpers inherit the root's memory scope even when their own folder_id
        // is NULL. An idle parent must not move while a child is still working.
        let affectedRuntimeIds = await ChatStore.shared.sessionIdsWithDescendants(scopeChanges)
        for id in affectedRuntimeIds {
            try require(ViewModelCache.shared.get(for: id)?.isProcessing != true,
                        "session_running", "运行中的会话不能迁移到其他记忆作用域：\(id)")
        }
        await ChatStore.shared.setFolder(target, forSessions: ids)
        try await verifyMembers(ids, target: target)
        return ["ok": true, "ids": ids, "target": target as Any? ?? NSNull(),
                "message": "会话已移组；已有记忆未搬迁。"]
    }

    @MainActor private static func removeContainer(_ request: Request) async throws -> [String: Any] {
        try require(request.confirmed, "confirmation_required", "此操作需要 --confirm。")
        let source = try await folderID(request)
        let target = request.action == "merge" ? try await folderID(request, key: "target") : nil
        try require(source != target, "invalid_target", "源分组和目标分组不能相同。")
        _ = try await ChatStore.shared.getFolderConfiguration(source)
        if let target { _ = try await ChatStore.shared.getFolderConfiguration(target) }
        let ids = await ChatStore.shared.sessionIdsInFolder(source)
        _ = try await sessions(ids, ordinaryOnly: true)
        // Descendants inherit their parent's scope even if their own folder_id is NULL.
        let runtimeIds = await ChatStore.shared.sessionIdsWithDescendants(ids)
        for id in runtimeIds {
            try require(ViewModelCache.shared.get(for: id)?.isProcessing != true,
                        "session_running", "源分组存在运行中的会话：\(id)")
        }
        await ChatStore.shared.setFolder(target, forSessions: ids)
        try await verifyMembers(ids, target: target)
        let remaining = await ChatStore.shared.sessionIdsInFolder(source)
        try require(remaining.isEmpty, "verification_failed", "源分组仍有成员；未解散，请重新查询。")
        // Never dissolve before the entire move has been verified. Only the container is removed.
        _ = await ChatStore.shared.dissolveFolder(source)
        let deleted = await ChatStore.shared.getFolder(source) == nil
        let empty = await ChatStore.shared.sessionIdsInFolder(source).isEmpty
        try require(deleted && empty, "verification_failed", "分组解散读回验证失败；操作可能部分生效。")
        try await verifyMembers(ids, target: target)
        if let target { _ = try await folder(target) }
        return ["ok": true, "id": source, "ids": ids, "target": target as Any? ?? NSNull(),
                "message": "分组已解散，会话保留；未删除、搬迁或复制记忆，未复制分组配置。"]
    }

    private static func jsonBool(_ value: Any, field: String) throws -> Bool {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else {
            throw SessionFolderBridgeError(code: "invalid_configuration", message: "\(field) 必须是布尔值。")
        }
        return number.boolValue
    }

    private static func patch(_ original: ChatFolderConfiguration, json: String) throws -> ChatFolderConfiguration {
        guard let object = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] else {
            throw SessionFolderBridgeError(code: "invalid_configuration", message: "config-json 必须是 JSON 对象。")
        }
        let allowed: Set<String> = ["skillDefaults", "soulPrompt", "memoryPolicy", "readsGlobalMemory", "soulMode"]
        try require(Set(object.keys).isSubset(of: allowed), "invalid_configuration", "配置包含未知字段。")
        var result = original
        for (key, value) in object {
            switch key {
            case "skillDefaults":
                guard let overrides = value as? [String: Any] else {
                    throw SessionFolderBridgeError(code: "invalid_configuration", message: "skillDefaults 必须是对象。")
                }
                for (id, override) in overrides {
                    if override is NSNull { result.skillDefaults.removeValue(forKey: id) }
                    else { result.skillDefaults[id] = try jsonBool(override, field: "skillDefaults.\(id)") }
                }
            case "soulPrompt", "soulMode":
                if value is NSNull {
                    if key == "soulPrompt" { result.soulPrompt = nil } else { result.soulMode = nil }
                } else {
                    guard let text = value as? String else {
                        throw SessionFolderBridgeError(code: "invalid_configuration", message: "\(key) 必须是字符串或 null。")
                    }
                    if key == "soulPrompt" { result.soulPrompt = text }
                    else {
                        try require(["inherit", "replace", "append", "clear"].contains(text),
                                    "invalid_configuration", "非法 soulMode；允许 inherit/replace/append/clear。")
                        result.soulMode = text
                    }
                }
            case "memoryPolicy":
                guard let text = value as? String, let policy = ChatFolderMemoryPolicy(rawValue: text) else {
                    throw SessionFolderBridgeError(code: "invalid_configuration", message: "memoryPolicy 只能是 global 或 folder。")
                }
                result.memoryPolicy = policy
            case "readsGlobalMemory":
                result.readsGlobalMemory = try jsonBool(value, field: key)
            default: break // Unknown keys were rejected before applying any field.
            }
        }
        return result
    }
}
