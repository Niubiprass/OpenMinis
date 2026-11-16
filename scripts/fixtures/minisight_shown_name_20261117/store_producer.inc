    private func publishShown() {
        guard loaded, !readingShown else { return }
        let on = shown
        do {
            try MiniSightPetFile.saveShown(on) {
                UserDefaults.standard.set(on, forKey: MiniSightSettingKey.shown)
            }
            publish(MiniSightSettingKey.shown)
        } catch {
            reloadShownFromFile()
            lastError = "桌宠显示状态没能保存，请重试。"
            saveState = "保存失败"
            let rev = UUID().uuidString
            MSDiagEvent("settings", "save", "failed",
                        ["setting": MiniSightSettingKey.shown, "source": "settings",
                         "revision": rev, "code": (error as NSError).code])
        }
    }
    func reloadShownFromFile() {
        let fileValue = MiniSightPetFile.loadShown()
        readingShown = true
        defer { readingShown = false }
        if shown != fileValue { shown = fileValue }
        UserDefaults.standard.set(fileValue, forKey: MiniSightSettingKey.shown)
    }
    func persistAll() {
        // Unrelated page exits may save their settings, but must NEVER write
        // shown. Only publishShown (the explicit switch edit) owns that file.
        // A reload alone would still leave a read->write race with menu hide.
        reloadShownFromFile()
        let d = UserDefaults.standard
        d.set(UUID().uuidString, forKey: MiniSightSettingKey.shownRevision)
        for key in MiniSightConfig.all { d.set(raw(key), forKey: key) }
        publishGeneration &+= 1
        deliver(generation: publishGeneration,
                revision: d.string(forKey: MiniSightSettingKey.shownRevision) ?? "", attempt: 0)
    }
