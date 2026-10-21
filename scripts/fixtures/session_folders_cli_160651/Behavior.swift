import Foundation

func expect(_ condition: @autoclosure () -> Bool, _ message: String,
            file: StaticString = #filePath, line: UInt = #line) {
    if !condition() {
        FileHandle.standardError.write(Data("FAIL \(file):\(line): \(message)\n".utf8))
        exit(1)
    }
}
func ok(_ result: NSDictionary) { expect(result["ok"] as? Bool == true, "expected success: \(result)") }
func error(_ result: NSDictionary, _ code: String) {
    expect(result["ok"] as? Bool == false, "expected failure: \(result)")
    expect(result["error"] as? String == code, "expected \(code): \(result)")
}

@MainActor func seed() {
    let store = ChatStore.shared
    store.folders = ["FA": ChatFolder(id: "FA", name: "Alpha", desc: "original"),
                     "FB": ChatFolder(id: "FB", name: "Beta")]
    store.rows = ["A": ChatSession(id: "A", title: "caller A", folderId: "FA"),
                  "B": ChatSession(id: "B", title: "active B", folderId: "FB"),
                  "U": ChatSession(id: "U", title: "unfiled"),
                  "H": ChatSession(id: "H", title: "helper", parentSessionId: "A"),
                  "G": ChatSession(id: "G", title: "grandchild", parentSessionId: "H")]
    var scoped = ChatFolderConfiguration.default
    scoped.memoryPolicy = .folder
    scoped.skillDefaults = ["keep": false, "remove": true]
    scoped.soulPrompt = "private A"
    store.configs = ["FA": scoped, "FB": .default]
    store.events = []; store.writes = []; store.faults = []
    store.expectedConfig = nil; store.casConcurrent = nil; store.serial = 0
    ViewModelCache.shared.cache = [:]; ViewModelCache.shared.drafts = []
    ViewModelCache.shared.submissions = []; ViewModelCache.shared.nextOutcome = .sent
    ProviderConfigStore.shared.bindings = [:]; ProviderConfigStore.shared.inference = [:]
    ProviderConfigStore.shared.writes = []
    FolderIconStore.shared.icons = [:]; FolderIconStore.shared.writes = 0
    FolderIconStore.shared.failMemory = false; FolderIconStore.shared.failPersistence = false
    UserDefaults.standard.icons = [:]
}

// Keep synchronous semaphore entry points on a worker queue. Async main leaves
// the main actor free to execute their *actual* Task { @MainActor in ... } body.
@MainActor func folders(_ action: String, _ args: [String: Any] = [:], caller: String? = "A") async -> NSDictionary {
    await withCheckedContinuation { continuation in
        DispatchQueue.global().async {
            continuation.resume(returning: SessionFoldersBridge.perform(action: action,
                args: args as NSDictionary, callerSessionId: caller))
        }
    }
}
@MainActor func send(_ selector: String? = nil, caller: String? = "A", existing: String? = nil,
                     inherit: Bool = false, model: String? = nil) async -> NSDictionary {
    await withCheckedContinuation { continuation in
        DispatchQueue.global().async {
            continuation.resume(returning: SessionsOffloadBridge.sendPrompt(sessionId: existing,
                prompt: "handoff", attachmentPaths: [], modelEntryId: model, source: "fixture",
                folder: selector, callerSessionId: caller, inheritModel: inherit))
        }
    }
}
@MainActor func noSend(noDraft: Bool = true) {
    expect(ViewModelCache.shared.submissions.isEmpty, "failed operation dispatched a prompt")
    if noDraft { expect(ViewModelCache.shared.drafts.isEmpty, "validation failure created a draft") }
    expect(ChatStore.shared.writes.isEmpty, "send mutated folder membership")
}
@MainActor func noMutation() {
    expect(ChatStore.shared.writes.isEmpty, "prevalidation changed storage: \(ChatStore.shared.writes)")
    expect(FolderIconStore.shared.writes == 0, "prevalidation changed icon")
}

@MainActor func testSend(_ scenario: String) async {
    let store = ChatStore.shared
    let cache = ViewModelCache.shared
    switch scenario {
    case "caller_token":
        expect(MinisFsRouter.shared.activeSessionId == "B", "fixture active B")
        expect(SessionsOffloadBridge.callerSessionId(fsContext: 101) == "A", "caller must use guest token")
        expect(SessionsOffloadBridge.callerSessionId(fsContext: 202) == "B", "other caller")
        expect(SessionsOffloadBridge.callerSessionId(fsContext: 0) == nil, "unknown token must not fall back to active")
    case "send_default", "send_current", "send_explicit_name":
        let selector: String? = scenario == "send_current" ? "current" : scenario == "send_explicit_name" ? " alpha " : nil
        let result = await send(selector)
        ok(result)
        let id = result["session_id"] as! String
        expect(store.rows[id]?.folderId == "FA", "caller A folder, not globally active B")
        expect(result["folder_id"] as? String == "FA", "reported folder")
        expect(result["memory_policy"] as? String == "folder", "reported memory scope")
        expect(cache.drafts.first?.sessionSource == "fixture", "source preserved")
        let persistence = store.events.firstIndex(of: "persist:FA")!
        let refresh = store.events.firstIndex(of: "refresh:FA")!
        let dispatch = store.events.firstIndex(of: "send:" + id)!
        expect(persistence < refresh && refresh < dispatch, "persist and refresh must precede send")
        if scenario != "send_explicit_name" {
            expect(store.events.firstIndex(of: "resolve:A")! < store.events.firstIndex(of: "draft")!, "resolve caller before draft")
        }
        expect(!store.events.contains("resolve:B"), "no active UI fallback")
        expect(cache.submissions.count == 1 && cache.submissions[0].1 == "handoff", "dispatch exactly once")
    case "send_none":
        let result = await send("none")
        ok(result)
        expect(store.rows[result["session_id"] as! String]?.folderId == nil, "explicit none")
        expect(result["folder_id"] is NSNull && result["memory_policy"] as? String == "global", "none response")
        expect(!store.events.contains("resolve:A"), "none must not inherit caller group")
    case "send_current_missing":
        error(await send("current", caller: nil), "folder_resolution_failed"); noSend()
    case "send_current_unfiled":
        error(await send("current", caller: "U"), "folder_resolution_failed"); noSend()
    case "send_bad_caller":
        for selector in [String?.none, String?.some("current")] {
            seed()
            error(await send(selector, caller: "missing"), "folder_resolution_failed"); noSend()
        }
    case "send_ambiguous":
        store.folders["FC"] = ChatFolder(id: "FC", name: "ALPHA")
        error(await send("alpha"), "folder_resolution_failed"); noSend()
        ok(await send("FA")) // UUID still resolves in the presence of duplicate names.
    case "send_existing":
        for selector in [String?.none, String?.some("FB")] {
            seed()
            let before = store.rows
            ok(await send(selector, existing: "B"))
            expect(store.rows == before && store.writes.isEmpty, "existing send cannot move any session")
            expect(cache.drafts.isEmpty && cache.submissions.count == 1, "reuse existing VM")
        }
    case "send_existing_mismatch":
        for selector in ["FA", "none", "current"] {
            seed()
            let before = store.rows
            error(await send(selector, existing: "B"), "folder_resolution_failed")
            noSend(); expect(store.rows == before, "mismatch must not move")
        }
    case "send_store_failure", "send_missing_persistence", "send_context_failure":
        let faults = scenario == "send_store_failure" ? ["persistFolder"] :
            scenario == "send_missing_persistence" ? ["persistMissing", "sessionUnavailable"] : ["refresh", "staleContext"]
        for fault in faults {
            seed(); store.faults.insert(fault)
            error(await send("current"), fault == "sessionUnavailable" ? "session_unavailable" : "folder_verification_failed")
            noSend(noDraft: false)
            expect(ProviderConfigStore.shared.writes.isEmpty, "failed persistence must precede model mutation")
        }
    case "send_model_inheritance":
        let provider = ProviderConfigStore.shared
        let primary = BindingSource.directEntry(modelEntryId: "model-A")
        let secondary = BindingSource.directEntry(modelEntryId: "model-B")
        provider.bindings["A"] = SessionModelBinding(sessionId: "A", primarySource: primary, subModelSource: secondary)
        provider.bindings["B"] = SessionModelBinding(sessionId: "B", primarySource: secondary)
        provider.inference["A"] = "caller-reasoning"
        provider.inference["B"] = "active-reasoning"
        let result = await send("current", inherit: true)
        ok(result)
        let id = result["session_id"] as! String
        expect(provider.bindings[id]?.primarySource == primary && provider.bindings[id]?.subModelSource == secondary, "copy A complete binding")
        expect(provider.inference[id] == "caller-reasoning", "copy caller inference not active B")
        let override = await send("current", inherit: true, model: "model-B")
        ok(override)
        expect(provider.bindings[override["session_id"] as! String]?.primarySource == secondary, "explicit model wins inheritance")
    case "send_invalid_model":
        error(await send("current", model: "unknown"), "model_not_found"); noSend()
    case "send_inherit_invalid":
        error(await send("none", caller: nil, inherit: true), "folder_resolution_failed"); noSend()
        error(await send(existing: "B", inherit: true), "folder_resolution_failed"); noSend()
    case "send_outcomes":
        for outcome in [PromptOutcome.sent, .queued, .rejected("fixture busy")] {
            seed(); cache.nextOutcome = outcome
            let result = await send("current")
            if outcome == .rejected("fixture busy") {
                error(result, "send_rejected")
                expect(result["reason"] as? String == "fixture busy", "rejection detail")
            } else {
                ok(result)
                expect(result["status"] as? String == (outcome == .sent ? "Running" : "Queued"), "truthful result")
                expect(result["queued"] as? Bool == (outcome == .queued), "queue flag")
            }
            expect(cache.submissions.count == 1, "only one submit")
        }
    default: expect(false, "unknown send scenario \(scenario)")
    }
}

@MainActor func testCRUD(_ scenario: String) async {
    let store = ChatStore.shared
    switch scenario {
    case "crud":
        let listing = await folders("list"); ok(listing)
        expect(listing["count"] as? Int == 2, "list folders")
        let detail = await folders("get", ["id": "current"]); ok(detail)
        let summary = detail["folder"] as! [String: Any]
        expect(summary["id"] as? String == "FA" && summary["member_count"] as? Int == 1, "get caller A members")
        expect((summary["members"] as? [[String: Any]])?.first?["id"] as? String == "A", "get member identities")
        let created = await folders("create", ["name": "  New  ", "description": "  " + String(repeating: "x", count: 110) + "  "])
        ok(created)
        let id = (created["folder"] as! [String: Any])["id"] as! String
        expect(store.folders[id]?.name == "New" && store.folders[id]?.desc?.count == 100, "trim name and bound description")
        ok(await folders("rename", ["id": id, "name": "Renamed"]))
        expect(store.folders[id]?.desc?.count == 100, "omitted desc must survive")
        ok(await folders("rename", ["id": id, "name": "Renamed", "description": "  "]))
        expect(store.folders[id]?.desc == nil, "blank desc clears")
        ok(await folders("pin", ["id": id, "pinned": "true"]))
        let writes = store.writes.count
        ok(await folders("pin", ["id": id, "pinned": "true"]))
        expect(store.writes.count == writes, "pin idempotent")
        ok(await folders("pin", ["id": id, "pinned": "false"]))
        expect(store.folders[id]?.isPinned == false, "unpin")
    case "crud_failures":
        for action in ["create", "rename", "pin"] {
            seed(); store.faults.insert(action)
            let args: [String: Any] = action == "create" ? ["name": "New"] :
                action == "rename" ? ["id": "FA", "name": "New"] : ["id": "FA", "pinned": "true"]
            error(await folders(action, args), action == "create" ? "folder_not_found" : "verification_failed")
            expect(store.writes == [action], "one attempted mutation")
        }
        seed(); store.faults.insert("config:FA")
        error(await folders("list"), "folder_operation_failed")
        error(await folders("get", ["id": "FA"]), "folder_operation_failed")
    case "request_validation":
        let invalid: [(String, [String: Any], String)] = [
            ("unknown", [:], "unknown_action"), ("create", [:], "invalid_arguments"),
            ("create", ["name": 1], "invalid_arguments"), ("list", ["unexpected": "x"], "invalid_arguments"),
            ("create", ["name": " alpha "], "duplicate_name"),
            ("rename", ["id": "FA", "name": "Beta"], "duplicate_name"),
            ("pin", ["id": "FA", "pinned": "1"], "invalid_arguments"),
            ("pin", ["id": "FA", "pinned": "True"], "invalid_arguments"),
            ("merge", ["id": "FA", "target": "FB", "confirm": NSNumber(value: 1)], "invalid_arguments"),
            ("dissolve", ["id": "FA", "confirm": "true"], "invalid_arguments")]
        for (action, args, code) in invalid {
            seed(); error(await folders(action, args), code); noMutation()
        }
    case "selector_errors":
        error(await folders("get", ["id": "current"], caller: nil), "missing_caller")
        error(await folders("get", ["id": "current"], caller: "U"), "unfiled_caller")
        error(await folders("get", ["id": "none"]), "invalid_target")
        error(await folders("get", ["id": "missing"]), "folder_not_found")
        store.folders["FC"] = ChatFolder(id: "FC", name: " ALPHA ")
        error(await folders("get", ["id": "alpha"]), "ambiguous_folder")
        ok(await folders("get", ["id": "fa"]))
        noMutation()
    case "configure_patch":
        let original = store.configs["FA"]!
        let json = #"{"skillDefaults":{"remove":null,"added":true},"soulPrompt":null,"soulMode":"append","readsGlobalMemory":true}"#
        ok(await folders("configure", ["id": "FA", "config-json": json]))
        let saved = store.configs["FA"]!
        expect(saved.skillDefaults == ["keep": false, "added": true], "partial skill patch incl null delete")
        expect(saved.soulPrompt == nil && saved.soulMode == "append" && saved.readsGlobalMemory, "typed patch")
        expect(saved.memoryPolicy == .folder && store.expectedConfig == original, "preserve absent fields, CAS original")
        expect(store.configs["FB"] == .default, "do not mutate other/global config")
        for mode in ["inherit", "replace", "clear"] {
            ok(await folders("configure", ["id": "FA", "config-json": "{\"soulMode\":\"\(mode)\"}"]))
        }
        ok(await folders("configure", ["id": "FA", "config-json": #"{"soulMode":null,"memoryPolicy":"global","readsGlobalMemory":false}"#]))
        expect(store.configs["FA"]?.soulMode == nil && store.configs["FA"]?.memoryPolicy == .global, "reset/enum patch")
    case "configure_invalid":
        let values = [#"{"readsGlobalMemory":1}"#, #"{"readsGlobalMemory":0}"#,
            #"{"readsGlobalMemory":"true"}"#, #"{"readsGlobalMemory":null}"#,
            #"{"skillDefaults":{"x":1}}"#, #"{"skillDefaults":{"x":0}}"#,
            #"{"skillDefaults":{"x":"false"}}"#, #"{"skillDefaults":[]}"#,
            #"{"memoryPolicy":"private"}"#, #"{"soulMode":"unknown"}"#,
            #"{"soulPrompt":3}"#, #"{"readsGlobalMemory":true,"unknown":false}"#, "[]", "null"]
        for json in values {
            seed(); let before = store.configs
            error(await folders("configure", ["id": "FA", "config-json": json]), "invalid_configuration")
            noMutation(); expect(store.configs == before, "invalid JSON patch must not save: \(json)")
        }
        seed()
        error(await folders("configure", ["id": "FA", "config-json": "{bad"]), "folder_operation_failed")
        noMutation()
    case "configure_cas":
        let original = store.configs["FA"]!
        var concurrent = original; concurrent.soulPrompt = "concurrent write"
        store.casConcurrent = concurrent
        error(await folders("configure", ["id": "FA", "config-json": #"{"soulPrompt":"mine"}"#]), "folder_operation_failed")
        expect(store.expectedConfig == original && store.configs["FA"] == concurrent, "CAS conflict must retain concurrent save")
    case "configure_storage_failure":
        for fault in ["configure", "configureReadback", "config:FA"] {
            seed(); store.faults.insert(fault)
            error(await folders("configure", ["id": "FA", "config-json": #"{"soulPrompt":"new"}"#]),
                  fault == "configureReadback" ? "verification_failed" : "folder_operation_failed")
            expect(store.configs["FA"]?.soulPrompt == "private A", "failed save keeps original config")
        }
    default: expect(false, "unknown CRUD scenario \(scenario)")
    }
}

@MainActor func testMove(_ scenario: String) async {
    let store = ChatStore.shared
    switch scenario {
    case "move_prevalidation":
        for ids in ["A,missing", "A,", "A,H"] {
            seed()
            let result = await folders("move", ["ids": ids, "target": "FB"])
            expect(result["ok"] as? Bool == false, "invalid batch rejected")
            noMutation()
            expect(store.rows["A"]?.folderId == "FA", "whole batch validated before any move")
        }
        seed()
        error(await folders("move", ["ids": "A", "target": "missing"]), "folder_not_found")
        noMutation()
    case "move_none_current":
        ok(await folders("move", ["ids": "current,A", "target": "none"]))
        expect(store.rows["A"]?.folderId == nil && store.writes == ["move"], "dedup and unfile caller")
        seed()
        ok(await folders("move", ["ids": "B,U", "target": "current"]))
        expect(store.rows["B"]?.folderId == "FA" && store.rows["U"]?.folderId == "FA", "move to caller folder")
        expect(store.configs["FA"]?.soulPrompt == "private A", "no config migration")
    case "move_running_scope":
        for runningID in ["A", "H", "G"] {
            seed()
            let (vm, _) = ViewModelCache.shared.getOrCreate(for: runningID)
            vm.isProcessing = true
            error(await folders("move", ["ids": "A", "target": "FB"]), "session_running")
            noMutation()
        }
        seed()
        let (vm, _) = ViewModelCache.shared.getOrCreate(for: "B")
        vm.isProcessing = true
        // Both are global memory; moving is allowed without changing scope.
        ok(await folders("move", ["ids": "B", "target": "none"]))
    case "move_storage_failure":
        for fault in ["move", "partialMove"] {
            seed(); store.faults.insert(fault)
            error(await folders("move", ["ids": "A,U", "target": "FB"]), "verification_failed")
            expect(store.folders["FA"] != nil && store.writes == ["move"], "no container deletion after partial move")
        }
    case "helper_rejected":
        error(await folders("move", ["ids": "H", "target": "FB"]), "helper_session")
        noMutation()
    case "remove_confirmation":
        for action in ["merge", "dissolve"] {
            seed()
            var args: [String: Any] = ["id": "FA"]
            if action == "merge" { args["target"] = "FB" }
            error(await folders(action, args), "confirmation_required")
            noMutation()
        }
    case "merge_preserves", "dissolve_preserves":
        let action = scenario == "merge_preserves" ? "merge" : "dissolve"
        let originalIDs = Set(store.rows.keys)
        let targetConfig = store.configs["FB"]
        var args: [String: Any] = ["id": "FA", "confirm": true]
        if action == "merge" { args["target"] = "FB" }
        ok(await folders(action, args))
        expect(store.folders["FA"] == nil, "source container removed")
        expect(Set(store.rows.keys) == originalIDs, "all conversations preserved")
        expect(store.rows["A"]?.folderId == (action == "merge" ? "FB" : nil), "verified destination")
        expect(store.rows["H"]?.parentSessionId == "A", "helper lineage unchanged")
        expect(store.configs["FB"] == targetConfig, "target settings never overwritten")
        expect(store.writes == ["move", "dissolve"], "move precedes dissolution, no memory operation")
    case "remove_running_descendant":
        for action in ["merge", "dissolve"] {
            for runningID in ["A", "H", "G"] {
                seed()
                let (vm, _) = ViewModelCache.shared.getOrCreate(for: runningID)
                vm.isProcessing = true
                var args: [String: Any] = ["id": "FA", "confirm": true]
                if action == "merge" { args["target"] = "FB" }
                error(await folders(action, args), "session_running")
                noMutation()
            }
        }
    case "remove_storage_failure":
        for fault in ["move", "partialMove", "dissolve"] {
            seed()
            store.rows["U"]?.folderId = "FA"
            store.faults.insert(fault)
            error(await folders("merge", ["id": "FA", "target": "FB", "confirm": true]), "verification_failed")
            expect(store.rows.count == 5, "failure never deletes conversations")
            expect(store.folders["FA"] != nil, "failed container remains inspectable")
            if fault != "dissolve" { expect(!store.writes.contains("dissolve"), "no dissolve after failed move") }
        }
    case "icon":
        error(await folders("icon", ["id": "FA", "path": "/fixture/missing.png"]), "invalid_image")
        noMutation()
        error(await folders("icon", ["id": "FA", "path": "/fixture/unencodable.png"]), "invalid_image")
        noMutation()
        ok(await folders("icon", ["id": "FA", "path": "/fixture/valid.png"]))
        expect(FolderIconStore.shared.icon(for: "FA") == "fixture:data:png", "sets folder photo")
        ok(await folders("icon", ["id": "FA", "path": "none"]))
        expect(FolderIconStore.shared.icon(for: "FA") == nil, "restores default")
        for fault in ["memory", "persistence"] {
            seed()
            FolderIconStore.shared.failMemory = fault == "memory"
            FolderIconStore.shared.failPersistence = fault == "persistence"
            error(await folders("icon", ["id": "FA", "path": "/fixture/valid.png"]), "verification_failed")
        }
    default: expect(false, "unknown move scenario \(scenario)")
    }
}

@main struct FolderBehaviorMain {
    static func main() async {
        guard CommandLine.arguments.count == 2 else { fatalError("scenario required") }
        let scenario = CommandLine.arguments[1]
        await seed()
        if scenario == "caller_token" || scenario.hasPrefix("send_") {
            await testSend(scenario)
        } else if scenario.hasPrefix("move_") || scenario.hasPrefix("remove_") ||
                    ["helper_rejected", "merge_preserves", "dissolve_preserves", "icon"].contains(scenario) {
            await testMove(scenario)
        } else {
            await testCRUD(scenario)
        }
        print("PASS native " + scenario)
    }
}
