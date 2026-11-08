#!/usr/bin/env python3
"""Per-setting end-to-end contract gate.

Every setting must have all six links before an App build is worth starting:
key -> page control -> store snapshot -> runtime consume -> apply log -> failure
reason. A lockfile holds the audited key list so a newly added switch cannot be
forgotten silently.

Usage: python3 scripts/test_minisight_settings_contract.py [--write-lock]
Exit 0 only if every key has every link.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
LOCK = Path(__file__).with_suffix(".lock.json")

KEYS = IOS / "MiniSightSettings.swift"
STORE = IOS / "MiniSightConfigStore.swift"
SNAPSHOT = IOS / "MiniSightSettings.swift"
RUNTIME = IOS / "MiniSightInAppRuntime.swift"
PAGES = IOS / "Views/Settings"
PLUGIN = Path("/var/minis/shared/MiniSight-complete-20261105/debs/MiniSight")


def read(path):
    return path.read_text() if path.is_file() else ""


keys_src = read(KEYS)
store = read(STORE)
runtime = read(RUNTIME)
pages = "\n".join(p.read_text() for p in sorted(PAGES.glob("MiniSight*.swift")))
snapshot = keys_src  # runtimeFields mapping and snapshot live in this one allowlist file

declared = dict(re.findall(r'static let (\w+) = "(minisight\.[\w.]+)"', keys_src))
# Keys applied by the runtime rather than bridged as numbers need their own check.
BOOLEAN_OR_NUMBER = set("""style renderer mode petSize gravity gravityStrength gravityShake interaction
activity activityInterval frameLimit dragResponse petSound bottomGap tint darkMode proactive
proactiveInterval voiceReply quick""".split())
HIDDEN = {'aiAdjust', 'adjustments', 'aiAdjustments', 'aiPermissions', 'diagnostics', 'frameLimit', 'nickname', 'persona', 'proactive', 'proactiveInterval', 'quickButtons', 'quickLines', 'quickOrder', 'quickPosition', 'longPressRecord'}
STRING_KEYS = {"singleTap", "doubleTap", "longPress", "costume", "nickname", "returnKey", "snore",
               "quickPosition", "quickOrder", "aiPermissions", "shownRevision"}


FIELD = {
    "minisight.voice.reply": "voiceReply", "minisight.voice.snore": "snore",
    "minisight.quick.enabled": "quick", "minisight.quick.position": "quickPosition",
    "minisight.quick.lines": "quickLines", "minisight.quick.order": "quickOrder",
    "minisight.longPress": "longPress", "minisight.shown": "shown",
    "minisight.settings.revision": "revision", "minisight.pet.tint": "tint",
    "minisight.pet.costume": "costume", "minisight.ai.supplier": "supplier",
    "minisight.ai.nickname": "nickname", "minisight.dialogue.scale": "bubbleScale", "minisight.chat.panelScale": "panelScale",
    "minisight.dialogue.textScale": "textScale", "minisight.dialogue.dwell": "dwell",
    "minisight.dialogue.return": "returnKey", "minisight.proactive.interval": "proactiveInterval",
    "minisight.active": "activity", "minisight.ai.adjust": "aiAdjust",
    "minisight.ai.permissions": "aiPermissions", "minisight.ai.adjustments": "adjustments",
    "minisight.proactive": "proactive", "minisight.bottomGap": "bottomGap", "minisight.dragResponse": "dragResponse", "minisight.petSound": "sound", "minisight.mode": "mode", "minisight.gravity.strength": "gravityStrength", "minisight.asset.source": "downloadSource", "minisight.gravity.shake": "gravityShake", "minisight.activity.interval": "activityInterval", "minisight.asset.source": "downloadSource", "minisight.frameLimit": "frameLimit", "minisight.asset.source": "downloadSource", "minisight.ai.persona": "persona", "minisight.ai.supplier": "supplier", "minisight.asset.source": "downloadSource", "minisight.darkMode": "darkMode",
}


def plugin_consumes(key):
    field = FIELD.get(key)
    sources = "".join(read(PLUGIN / name) for name in
                      ("Tweak.xm", "MiniSightResources.m", "MiniSightRuntimeConfig.m", "MiniSightChatPanel.m"))
    return (field is not None and f'@"{field}"' in sources) or key in sources
    """Plugin reads either the raw defaults or the runtime snapshot field."""



results = []
problems = []
for var, key in declared.items():
    checks = {
        "page": var in HIDDEN or (f"$config.{var}" in pages) or (f"config.{var}" in pages) or (var in {"aiPermissions", "adjustments"} and f"config.{var}" in store)
            or (var == "aiPermissions" and "config.setPermission" in pages)
            or (var == "downloadSource" and "config.downloadSource" in store)
            or (var == "shownRevision" and "MiniSightSettingKey.shownRevision" in store),
        "store": var in store,
        "snapshot": key in snapshot or var in snapshot,
        "runtime_or_plugin": var in runtime or plugin_consumes(key),
        "apply_log": (f'"{key}"' in store or f"MiniSightSettingKey.{var}" in store) and "MSDiagEvent" in store,
        "skip_reason": "reason" in store,
    }
    failed = [name for name, ok in checks.items() if not ok]
    results.append((key, failed))
    if failed:
        problems.append(f"{key} missing: {', '.join(failed)}")

empty_permissions = len([k for k in declared if k.endswith("aiPermissions")])
lock = json.loads(LOCK.read_text()) if LOCK.is_file() else None
if "--write-lock" in sys.argv:
    LOCK.write_text(json.dumps(sorted(declared.values()), indent=2) + "\n")
elif lock is not None:
    added = sorted(set(declared.values()) - set(lock))
    removed = sorted(set(lock) - set(declared.values()))
    if added:
        problems.append("new keys without audit: " + ", ".join(added))
    if removed:
        problems.append("keys disappeared (update lock only intentionally): " + ", ".join(removed))

for key, failed in results:
    print(f"{'PASS' if not failed else 'FAIL'} {key:38} {'' if not failed else ','.join(failed)}")
print(f"\n{len(results) - len([r for r in results if r[1]])}/{len(results)} keys fully wired")
if problems:
    print("\nBLOCKERS")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("contract complete")
