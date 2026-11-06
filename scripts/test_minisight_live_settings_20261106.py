#!/usr/bin/env python3
"""Guard for live MiniSight settings (2026-11-06).

The old path waited 250 ms then forced a full atlas refresh and destroyed the
window before rebuilding; every switch took 10+ seconds. Settings must now be
applied in place immediately, with a full rebuild only for renderer/style.

Static source contracts only.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = Path("/var/minis/shared/MiniSight-complete-20261105/debs/MiniSight")
TWEAK = (PLUGIN / "Tweak.xm").read_text()
PANEL = (PLUGIN / "MiniSightChatPanel.m").read_text()

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


# No artificial wait on the settings notification.
need('kMiniSightSettingsChanged]) {\n        // App 在发通知前已经写好' in TWEAK,
     "settings notification no longer waits a beat")
need('dispatch_async(dispatch_get_main_queue(), ^{ MiniSightReloadSettings(); });' in TWEAK,
     "settings reload is dispatched immediately")

# Preferences-only refresh; no forced atlas/destroy for an ordinary switch.
need('static void MiniSightApplySettingsLive(void)' in TWEAK, "live apply exists")
need('[MiniSightResources refreshPreferences:' in TWEAK, "reload uses preferences-only read")
reload = TWEAK[TWEAK.index('static void MiniSightReloadSettings(void) {'):]
reload = reload[:reload.index('static void MiniSightApplySettingsLive') if False else reload.index('MiniSightApplySettingsLive') if 'static void MiniSightApplySettingsLive' in reload else 6000]
need('BOOL structural = renderer != gMiniSightAppliedRenderer || style != gMiniSightAppliedStyle;' in TWEAK,
     "full rebuild is limited to structural changes")
need('if (structural) {' in TWEAK and 'MiniSightDestroyUI();' in TWEAK,
     "destroy only on structural change")
need('MiniSightApplySettingsLive();' in TWEAK, "non-structural changes use live apply")
need('gMiniSightAppliedRenderer = MiniSightRenderer();' in TWEAK, "renderer is tracked")

# The live path applies the controls the user actually flips.
for token, label in [
    ('gMiniSightPet.gravityEnabled = MiniSightGravityEnabled();', "gravity"),
    ('gMiniSightPet.longPressEnabled = MiniSightLongPressEnabled();', "long press"),
    ('panel.appearancePreferences = gMiniSightPreferences', "bubble/sound/voice appearance"),
    ('appearanceMode == 1 ? UIUserInterfaceStyleLight', "dark mode"),
    ('MiniSightApplyRuntimeConfig();', "size/activity/tint"),
]:
    need(token in TWEAK, label + " applied live")

# Shown file is re-read on the settings path, so the enable switch is live too.
need('Documents/MiniSight/shown' in TWEAK, "shown file is read on reload")
need('gMiniSightShown = ![shownText isEqualToString:@"0"];' in TWEAK,
     "shown state follows the file immediately")

# Compact composer + motion, not a wide card.
need('CGFloat barWidth = MIN(212 *' in PANEL, "composer is compact")
need('- (void)animatePresentationIn' in PANEL, "presentation animates")
need('animatePresentationIn];' in PANEL, "animation is called on show/reveal")
need('bubble.transform = CGAffineTransformConcat' in PANEL, "new bubbles animate")
need('UIViewAnimationOptionRepeat | UIViewAnimationOptionAutoreverse' in PANEL,
     "typing indicator pulses")
need('self.quickScroll.hidden = YES;' in PANEL, "quick row hidden in the simplified UI")

if fails:
    print("❌ MiniSight live-settings guard failed:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ MiniSight live-settings guard passed (static only)")
