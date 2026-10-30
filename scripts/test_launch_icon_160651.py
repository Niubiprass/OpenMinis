#!/usr/bin/env python3
"""Contract for the launch-screen icon (2026-10-30).

The launch screen used to reference a single `LaunchIcon` imageset carrying
light and dark photographs. On iOS 15 that appearance variant was resolved
with the wrong trait (light UI picked the dark plate) and flipped between
launches, so the icon could not be trusted.

The fix splits the artwork into two flat layers:

* `LaunchIconPlate` — a rounded square, template-rendered, tinted with the
  system's secondary background colour, so the card follows light/dark with
  no appearance-variant lookup at all.
* `LaunchIconMark` — the coloured M artwork, fixed in both modes.

This test pins that structure so a future asset edit cannot silently bring
the flaky two-photo variant back.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src/ios/Assets.xcassets"
STORYBOARD = (ROOT / "src/ios/Launch Screen.storyboard").read_text()
PLATE = ASSETS / "LaunchIconPlate.imageset"
MARK = ASSETS / "LaunchIconMark.imageset"


class LaunchIconContract(unittest.TestCase):
    def test_storyboard_uses_two_layers_not_the_old_single_image(self):
        self.assertIn('image="LaunchIconPlate"', STORYBOARD)
        self.assertIn('image="LaunchIconMark"', STORYBOARD)
        self.assertNotIn('image="LaunchIcon"', STORYBOARD)

    def test_plate_is_template_tinted_by_a_dynamic_system_colour(self):
        contents = json.loads((PLATE / "Contents.json").read_text())
        self.assertEqual(
            contents.get("properties", {}).get("template-rendering-intent"),
            "template",
        )
        self.assertIn(
            '<color key="tintColor" systemColor="secondarySystemBackgroundColor"/>',
            STORYBOARD,
        )

    def test_neither_layer_depends_on_appearance_variants(self):
        for imageset in (PLATE, MARK):
            contents = json.loads((imageset / "Contents.json").read_text())
            for image in contents["images"]:
                self.assertNotIn("appearances", image, imageset.name)
            files = {p.name for p in imageset.iterdir() if p.suffix == ".png"}
            self.assertEqual(
                files,
                {"Plate.png", "Plate@2x.png", "Plate@3x.png"}
                if imageset is PLATE
                else {"Mark.png", "Mark@2x.png", "Mark@3x.png"},
            )

    def test_old_variant_imageset_is_gone(self):
        self.assertFalse((ASSETS / "LaunchIcon.imageset").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
