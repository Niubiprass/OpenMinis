#!/usr/bin/env python3
"""Guard for the MiniSight "enable pet" switch (2026-11-06).

Device state was `shown=0` while `minisight.shown` was absent from the plist.
The switch had no didSet and the App never called saveShown(), so toggling it
only changed memory and the next scene-active refresh reverted it from the
shown file. This locks both persistence channels, the reload on page appear,
and the snapshot key. Static only.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
STORE = (ROOT / "src/ios/MiniSightConfigStore.swift").read_text()
SETTINGS = (ROOT / "src/ios/MiniSightSettings.swift").read_text()
HOME = (ROOT / "src/ios/Views/Settings/MiniSightHomePage.swift").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


need("@Published var shown: Bool { didSet { publishShown() } }" in STORE,
     "shown toggle publishes on change")
need("private func publishShown()" in STORE, "shown has a dedicated publisher")
need("try MiniSightAIConfigFile.saveShown(on)" in STORE,
     "shown writes the runtime file")
need("UserDefaults.standard.set(on, forKey: MiniSightSettingKey.shown)" in STORE,
     "shown writes the plist key")
need("publish(MiniSightSettingKey.shown)" in STORE, "shown goes through readback/deliver")
need("case MiniSightSettingKey.shown: return shown" in STORE,
     "shown is in raw() for readback")
need("MiniSightAIConfigFile.loadShown()" in STORE, "init takes the file as truth")
need("func reloadShownFromFile()" in STORE, "menu-hide state can be re-synced")
need("config.reloadShownFromFile()" in HOME, "home page re-syncs before showing the toggle")
need("try? MiniSightAIConfigFile.saveShown(shown)" in STORE,
     "persistAll also maintains the file")
need('"shown","style"' in SETTINGS, "shown is part of the snapshot key list")
need('case "shown": return MiniSightSettingKey.shown' in SETTINGS,
     "shown has a key mapping")

# The plugin must keep treating the file as the runtime truth.
need('appendingPathComponent("shown")' in
     (ROOT / "src/ios/MiniSightInAppRuntime.swift").read_text(),
     "runtime still reads the shown file")

if fails:
    print("❌ MiniSight shown-switch guard failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ MiniSight shown-switch guard passed (static only)")
