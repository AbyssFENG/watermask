# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
_existing = sys.modules.get("photo_watermark_studio")
if _existing is not None and not hasattr(_existing, "__path__"):
    del sys.modules["photo_watermark_studio"]

from photo_watermark_studio.core.edit_session import EditSessionStore, merge_photo_overrides


class EditSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "overrides.json"
        self.photo_a = Path(self._tmp.name) / "a.jpg"
        self.photo_b = Path(self._tmp.name) / "b.jpg"
        self.photo_a.write_bytes(b"a")
        self.photo_b.write_bytes(b"b")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_overrides_are_per_photo(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "camera", "Cam A", 1.25)
        store.set_field(self.photo_b, "camera", "Cam B", 0.9)
        self.assertEqual(store.get_field(self.photo_a, "camera")["text"], "Cam A")
        self.assertEqual(store.get_field(self.photo_b, "camera")["text"], "Cam B")
        merged_a = store.merge_into({"camera_text": ""}, self.photo_a)
        merged_b = store.merge_into({"camera_text": ""}, self.photo_b)
        self.assertEqual(merged_a["camera_text"], "Cam A")
        self.assertEqual(merged_b["camera_text"], "Cam B")
        # 未改过的第三张不应吃到上一张文案。
        other = Path(self._tmp.name) / "c.jpg"
        other.write_bytes(b"c")
        merged_c = store.merge_into({"camera_text": ""}, other)
        self.assertEqual(merged_c["camera_text"], "")

    def test_clear_removes_temp_file(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "exif", "ISO 100", 1.0)
        self.assertTrue(store.has_overrides())
        store.clear()
        self.assertFalse(self.path.exists())
        self.assertFalse(store.has_overrides())

    def test_merge_photo_overrides_helper(self) -> None:
        photos = {
            str(self.photo_a.resolve()): {"camera_text": "OnlyA", "camera_scale": 1.1}
        }
        merged = merge_photo_overrides({"camera_text": "", "lens_text": ""}, self.photo_a, photos)
        self.assertEqual(merged["camera_text"], "OnlyA")
        blank = merge_photo_overrides({"camera_text": ""}, self.photo_b, photos)
        self.assertEqual(blank["camera_text"], "")

    def test_field_font_is_per_field(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "camera", "Cam", 1.0, font="楷体")
        store.set_field(self.photo_a, "lens", "Lens", 1.0, font="隶书")
        cam = store.get_field(self.photo_a, "camera")
        lens = store.get_field(self.photo_a, "lens")
        self.assertEqual(cam["font"], "楷体")
        self.assertEqual(lens["font"], "隶书")
        merged = store.merge_into({}, self.photo_a)
        self.assertEqual(merged["camera_font"], "楷体")
        self.assertEqual(merged["lens_font"], "隶书")
        self.assertEqual(merged.get("brand_font", "默认"), "默认")

    def test_field_bold_is_per_field(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "camera", "Cam", 1.0, bold=False)
        store.set_field(self.photo_a, "exif", "ISO 100", 1.0, bold=True)
        cam = store.get_field(self.photo_a, "camera")
        exif = store.get_field(self.photo_a, "exif")
        self.assertFalse(cam["bold"])
        self.assertTrue(exif["bold"])
        merged = store.merge_into({}, self.photo_a)
        self.assertFalse(merged["camera_bold"])
        self.assertTrue(merged["exif_bold"])
        self.assertTrue(merged["lens_bold"])  # 默认加粗

    def test_field_italic_is_per_field(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "camera", "Cam", 1.0, italic=True)
        store.set_field(self.photo_a, "exif", "ISO 100", 1.0, italic=False)
        cam = store.get_field(self.photo_a, "camera")
        exif = store.get_field(self.photo_a, "exif")
        self.assertTrue(cam["italic"])
        self.assertFalse(exif["italic"])
        merged = store.merge_into({}, self.photo_a)
        self.assertTrue(merged["camera_italic"])
        self.assertFalse(merged["exif_italic"])
        self.assertFalse(merged["lens_italic"])

    def test_field_opacity_is_per_field(self) -> None:
        store = EditSessionStore(self.path)
        store.set_field(self.photo_a, "camera", "Cam", 1.0, opacity=0.5)
        store.set_field(self.photo_a, "lens", "Lens", 1.0, opacity=0.2)  # clamp to 0.3
        cam = store.get_field(self.photo_a, "camera")
        lens = store.get_field(self.photo_a, "lens")
        self.assertAlmostEqual(cam["opacity"], 0.5)
        self.assertAlmostEqual(lens["opacity"], 0.3)
        merged = store.merge_into({}, self.photo_a)
        self.assertAlmostEqual(merged["camera_opacity"], 0.5)
        self.assertAlmostEqual(merged["lens_opacity"], 0.3)
        self.assertAlmostEqual(merged["exif_opacity"], 1.0)


if __name__ == "__main__":
    unittest.main()
