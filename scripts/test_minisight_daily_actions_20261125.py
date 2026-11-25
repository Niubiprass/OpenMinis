#!/usr/bin/env python3
"""Portable source/fixture gate for daily pet actions; no external assets or device."""
import argparse
import json
from pathlib import Path
import unittest


def locate_core(root):
    for candidate in (root / "src/ios/MiniSightCore", root / "debs/MiniSight", root):
        if (candidate / "MiniSightPet.m").is_file() and (candidate / "MiniSightActionLibrary.m").is_file():
            return candidate
    raise SystemExit("MiniSight production sources not found under --root")


def section(source, start, end):
    if start not in source or end not in source:
        raise AssertionError("missing source boundary: " + start)
    return source.split(start, 1)[1].split(end, 1)[0]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
ROOT = args.root.resolve()
CORE = locate_core(ROOT)
PET = (CORE / "MiniSightPet.m").read_text()
EFFECTS = (CORE / "MiniSightPetEffects.m").read_text()
LIBRARY = (CORE / "MiniSightActionLibrary.m").read_text()


class DailyActionContracts(unittest.TestCase):
    def test_scheduler_is_independent_of_roaming(self):
        frame = section(PET, "- (void)frameTick:(NSTimer *)timer {", "- (NSInteger)frameCountForRow:")
        daily = section(PET, "- (void)tryDailyActionAt:(CFTimeInterval)now {", "- (void)scheduleRoam {")
        roam = section(PET, "- (void)roamOnce {", "- (void)holdState:")
        self.assertIn("[self tryDailyActionAt:now]", frame)
        self.assertNotIn("mayRoam", daily)
        self.assertNotIn("_roamPace", daily)
        self.assertNotIn("performDailyAction", roam)

    def test_cadence_and_priority_owners(self):
        schedule = section(PET, "- (void)scheduleDailyActionFrom:(CFTimeInterval)now {", "- (void)tryDailyActionAt:")
        daily = section(PET, "- (void)tryDailyActionAt:(CFTimeInterval)now {", "- (void)scheduleRoam {")
        self.assertIn("MSPetRandomRange(8.0, 14.0)", schedule)
        self.assertIn("MSPetRandomRange(14.0, 25.0)", daily)
        self.assertIn("MSPetRandomRange(24.0, 36.0)", daily)
        for token in ("_resident.sleeping", "_resident.waking", "_activityActive", "_lyricsSuppressed",
                      "_motionLockReasons", "_interactionActive", "presentationBlocked",
                      "_effects.musicPlaying", "UIAccessibilityIsReduceMotionEnabled"):
            self.assertIn(token, daily)

    def test_weighted_categories_and_no_repeat(self):
        for token in ('@"micro": @55', '@"play": @30', '@"food": @15',
                      '@"seasonal": @10', '@"social": @10', 'clip.category ?: @"micro"',
                      "_lastClip", "allUsablePool", "_lastDailyClip",
                      'NSString *avoidClip = [actual isEqualToString:@"idleAlt"] ? _lastDailyClip : _lastClip;',
                      'if ([actual isEqualToString:@"idleAlt"]) _lastDailyClip = next.identifier;'):
            self.assertIn(token, EFFECTS)
        self.assertIn("_lastDailyClip = nil", EFFECTS)

    def test_legacy_single_action_keeps_wave_fallback(self):
        roam = section(PET, "- (void)roamOnce {", "- (void)holdState:")
        self.assertIn('- (BOOL)hasDailyActions { return _library.roles[@"idleAlt"].count > 0; }', EFFECTS)
        self.assertIn("if (!_effects.hasDailyActions && roll < 90)", roam)
        self.assertIn("MiniSightPetStateWaving", roam)

    def test_failed_daily_clip_returns_to_base_idle_without_travel(self):
        perform = section(EFFECTS, "- (NSTimeInterval)performDailyAction {", "- (void)tick:")
        self.assertIn('[_role isEqualToString:@"idleAlt"]', perform)
        self.assertIn("All daily clips failed: visibly fall back to the base idle", perform)
        self.assertIn("[self chooseRole]", perform)
        self.assertIn("return 0.;", perform)
        self.assertNotIn("center =", perform)
        self.assertNotIn("setCenter", perform)

    def test_measured_music_keeps_life_and_reports_real_first_frame(self):
        daily = section(PET, "- (void)tryDailyActionAt:(CFTimeInterval)now {", "- (void)scheduleRoam {")
        self.assertIn("[self measuredMusicInputAt:now]", daily)
        self.assertIn("_dailyPausedRemaining", daily)
        self.assertIn("_dailyBlockers", daily)
        self.assertNotIn('reason\": @\"daily_first_frame', daily)
        crop = section(PET, "- (void)applySpriteFrame {", "- (void)restorePosterFrame {")
        self.assertIn("if (cell && _dailyFirstFramePending", crop)
        self.assertLess(crop.index("_gravityLayer.contents ="), crop.index('@"daily_first_frame"'))
        prepared = section(EFFECTS, "- (void)requestFrame:(NSUInteger)index {", "- (void)advanceActions:")
        self.assertLess(prepared.index("if (!image.CGImage)"), prepared.index('@"daily_first_frame"'))
        self.assertLess(prepared.index("self->_sprite.contents ="), prepared.index('@"daily_first_frame"'))
        perform = section(EFFECTS, "- (NSTimeInterval)performDailyAction {", "- (void)cancelDailyAction {")
        self.assertIn("_musicPlaying && (!_rhythmFollowing", perform)
        policy = (CORE / "MiniSightPetDailyPolicy.h").read_text()
        self.assertIn("static const int look[]", policy)
        self.assertIn("static const int wave[]", policy)

    def test_optional_category_schema_preserves_old_packs(self):
        for category in ("micro", "play", "food", "seasonal", "social"):
            self.assertIn(category, LIBRARY)
        self.assertIn('@[@"id", @"role", @"frames"], @[@"category"]', LIBRARY)
        catalog = ROOT / "src/ios/Agent/Chat/MiniSightCatalog.swift"
        if catalog.is_file():
            swift = catalog.read_text()
            self.assertIn("var category: String? = nil", swift)
            self.assertIn('keys == ["id", "role", "frames"]', swift)
            self.assertIn('keys == ["id", "role", "frames", "category"]', swift)

    def test_daily_diagnostic_stage_is_whitelisted(self):
        log = CORE / "MiniSightLog.m"
        source = log.read_text()
        stages = source.split("MSDiagStages =", 1)[1].split("MSDiagResults =", 1)[0]
        self.assertIn('@"daily_action"', stages)
        self.assertIn('@"0.8.55"', source.split('@"version":', 1)[1])

    def test_checked_in_synthetic_category_fixture(self):
        app_fixture = ROOT / "scripts/fixtures/minisight_action_import/actions.json"
        plugin_fixture = CORE / "scripts/fixtures/minisight_action_library_20261116/cases.json"
        if app_fixture.is_file():
            clips = json.loads(app_fixture.read_text())["clips"]
            self.assertTrue(any(c.get("role") == "idle" and "category" not in c for c in clips))
            self.assertTrue(any(c.get("role") == "idleAlt" and c.get("category") == "play" for c in clips))
        else:
            cases = json.loads(plugin_fixture.read_text())["cases"]
            self.assertTrue(any(c["name"] == "valid-daily-category" and c["valid"] for c in cases))
            self.assertTrue(any(c["name"] == "unknown-category" and not c["valid"] for c in cases))

    def test_repeat_runtime_fixture_forces_both_category_choices(self):
        fixture = CORE / "scripts/fixtures/minisight_effects_runtime_20261116/runtime.m"
        if not fixture.is_file():
            fixture = ROOT / "scripts/fixtures/minisight_effects_runtime_20261116/runtime.m"
        source = fixture.read_text()
        for token in ("FixtureFixedDailyRandom", "FixtureDailyRandomValue", "@[@0, @84]",
                      "cycle < 8", "CHECK(![previous isEqualToString:selected.identifier])",
                      'isEqual:@"fixture-idle"', 'valueForKey:@"lastDailyClip"',
                      "endDragCancelled:YES", "musicPlaying = YES"):
            self.assertIn(token, source)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DailyActionContracts))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS: portable daily-action source and synthetic-fixture contracts; no local asset paths")
