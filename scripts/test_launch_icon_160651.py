#!/usr/bin/env python3
"""Contract for the launch-screen icon (2026-10-30).

History, twice over:

1. A single `LaunchIcon` imageset with light/dark photographs resolved with
   the wrong trait and flipped between launches.
2. Replacing it with a *template* plate tinted by
   `secondarySystemBackgroundColor` still flipped: a template tint is applied
   after the image is decoded, using whatever trait the launch snapshot
   happens to carry, so the same build showed a white card on a black
   background on some cold launches and a dark card on others.

The plate is therefore now a baked two-variant asset (light `Plate*`, dark
`Plate-Dark*`, `luminosity/dark`) rendered as-is — no template intent, no
tintColor — leaving variant lookup to the asset catalog, which resolves it
deterministically while decoding. `LaunchIconMark` stays single.

This test pins that structure.
"""
import json
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src/ios/Assets.xcassets"
STORYBOARD = (ROOT / "src/ios/Launch Screen.storyboard").read_text()
PLATE = ASSETS / "LaunchIconPlate.imageset"
MARK = ASSETS / "LaunchIconMark.imageset"


def _png_pixel(path, x, y):
    """Decode one pixel from an 8-bit RGBA PNG (no Pillow on CI runners)."""
    data = path.read_bytes()
    pos, idat = 8, b""
    width = height = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            assert (depth, ctype) == (8, 6), (depth, ctype)
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4
    prev = bytearray(stride)
    rows = []
    off = 0
    for _ in range(height):
        ftype = raw[off]
        off += 1
        line = bytearray(raw[off:off + stride])
        off += stride
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 0xFF
            elif ftype == 2:
                line[i] = (line[i] + b) & 0xFF
            elif ftype == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                p_ = a + b - c
                pa, pb, pc = abs(p_ - a), abs(p_ - b), abs(p_ - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append(line)
        prev = line
    row = rows[y]
    return tuple(row[x * 4:x * 4 + 4])


class LaunchIconContract(unittest.TestCase):
    def test_storyboard_uses_two_layers_not_the_old_single_image(self):
        self.assertIn('image="LaunchIconPlate"', STORYBOARD)
        self.assertIn('image="LaunchIconMark"', STORYBOARD)
        self.assertNotIn('image="LaunchIcon"', STORYBOARD)

    def test_plate_is_baked_not_tinted(self):
        contents = json.loads((PLATE / "Contents.json").read_text())
        self.assertNotIn("template-rendering-intent", contents.get("properties", {}))
        self.assertNotIn("tintColor", STORYBOARD)

    def test_plate_carries_a_dark_variant(self):
        contents = json.loads((PLATE / "Contents.json").read_text())
        dark = [
            i for i in contents["images"]
            if {"appearance": "luminosity", "value": "dark"} in i.get("appearances", [])
        ]
        self.assertEqual(len(dark), 3)
        files = {p.name for p in PLATE.iterdir() if p.suffix == ".png"}
        self.assertEqual(
            files,
            {"Plate.png", "Plate@2x.png", "Plate@3x.png",
             "Plate-Dark.png", "Plate-Dark@2x.png", "Plate-Dark@3x.png"},
        )

    def test_dark_plate_is_actually_dark(self):
        for name, width in (("Plate-Dark.png", 96), ("Plate-Dark@2x.png", 192),
                            ("Plate-Dark@3x.png", 288)):
            r, g, b, a = _png_pixel(PLATE / name, width // 2, 10)
            self.assertEqual(a, 255, name)
            self.assertLess(max(r, g, b), 60, name)

    def test_light_plate_is_still_light(self):
        r, g, b, a = _png_pixel(PLATE / "Plate@3x.png", 144, 10)
        self.assertEqual(a, 255)
        self.assertGreater(min(r, g, b), 200)

    def test_mark_stays_single(self):
        contents = json.loads((MARK / "Contents.json").read_text())
        for image in contents["images"]:
            self.assertNotIn("appearances", image)

    def test_old_variant_imageset_is_gone(self):
        self.assertFalse((ASSETS / "LaunchIcon.imageset").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
