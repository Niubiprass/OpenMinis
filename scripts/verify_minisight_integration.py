#!/usr/bin/env python3
"""Static and portable checks only; does not build for iOS or access a device."""
from pathlib import Path
import collections
import re
import subprocess

root = Path(__file__).resolve().parents[1]
issues = []
def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok: issues.append(name)

pbx = (root / "src/ios/Minis.xcodeproj/project.pbxproj").read_text()
app = (root / "src/ios/MinisApp.swift").read_text()
bridge = (root / "src/ios/MinisApp-Bridging-Header.h").read_text()
runtime = (root / "src/ios/MiniSightInAppRuntime.swift").read_text()
settings = (root / "src/ios/Views/Settings/MiniSightSettingsView.swift").read_text()
confirm = (root / "src/ios/Views/Settings/MiniSightConfirm.swift").read_text()
page = (root / "src/ios/Views/Settings/MiniSightAIPage.swift").read_text()
core = root / "src/ios/MiniSightCore"

# Xcode objects are 24-hex IDs; nested buildSettings/TargetAttributes keys are
# intentionally excluded by requiring the PBX object's two-tab indentation.
ids = re.findall(r'^\t\t([A-Fa-f0-9]{24})\s*(?:/\*.*?\*/\s*)?=\s*\{', pbx, re.M)
counts = collections.Counter(ids)
check("pbx_no_duplicate_object_ids", not [x for x, n in counts.items() if n > 1])
refs = set(re.findall(r'\b([A-Fa-f0-9]{24})\b', pbx))
check("pbx_references_resolve", refs <= set(ids))

for rel in ["MiniSightPet.m", "MiniSightPet.h", "MiniSightAI.m", "MiniSightAI.h",
            "MiniSightChatPanel.m", "MiniSightChatPanel.h", "MiniSightLog.m", "MiniSightLog.h",
            "MiniSightBridgeIO.h", "MiniSightGeometry.h", "MiniSightGravity.h",
            "tools/chat/ChatCore.c", "tools/chat/ChatCore.h", "tools/recorder/MiniSightRecorderFile.h",
            "MiniSightAppRecorder.m", "MiniSightAppRecorder.h", "MiniSightChatLayout.h"]:
    check("source_exists_" + rel, (core / rel).is_file())
for src in ["MiniSightPet.m", "MiniSightAI.m", "MiniSightChatPanel.m", "MiniSightLog.m",
            "ChatCore.c", "MiniSightAppRecorder.m", "MiniSightInAppRuntime.swift", "MiniSightRecorderModel.swift", "MiniSightSignal.swift", "MiniSightHostAdapter.swift"]:
    check("source_registered_" + src, src + " in Sources" in pbx)
check("root_overlay_mounted", "MiniSightInAppRuntime()" in app)
check("objc_bridging", all(x in bridge for x in ["MiniSightPet.h", "MiniSightAI.h", "MiniSightChatPanel.h", "MiniSightAppRecorder.h"]))
check("app_recorder_model_exists", (root / "src/ios/MiniSightRecorderModel.swift").is_file())
check("app_approval_fallback", "MiniSightHostAdapter.confirm(command: command)" in confirm and "probeJailbreakPlugin(id:" in confirm)
check("persona_saved_to_ai_json", "system_prompt" in settings and ("saveAI(url: config.endpoint" in settings or "saveAI(url: endpoint" in page))
check("persona_single_setting_page", 'static func savePersona(' in settings and 'replacingPersona(text, in: current)' in settings and '@AppStorage("minisight.ai.persona")' not in runtime)
check("no_swift_fullscreen_hit_test", ".allowsHitTesting(visible)" not in runtime)
check("foreground_protocol_notification", 'com.openminis.minisight.app-active' in runtime and 'postForegroundChanged' in runtime)
check("plugin_single_arch_source", 'ARCHS = arm64e' in (root / '../MiniSight-repair/debs/MiniSight/Makefile').read_text() if (root / '../MiniSight-repair/debs/MiniSight/Makefile').exists() else True)
check("plugin_probe_nonce", all(x in confirm for x in ['plugin-probe.txt', 'plugin-probe-reply.txt', 'com.openminis.minisight.plugin-probe']))
print("ISSUES", len(issues))
raise SystemExit(bool(issues))
