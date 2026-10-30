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

from PIL import Image

from photo_watermark_studio.core.export_service import allocate_output_path, export_image
from photo_watermark_studio.core.settings_store import coerce_settings, load_settings, save_settings

OPTIONS = {
    "style": "经典底栏",
    "theme": "浅色",
    "brand": "",
    "caption": "",
    "scale": 1.0,
    "logo_path": "",
    "show_camera": True,
    "show_lens": True,
    "show_exif": True,
    "show_date": False,
    "show_gps": False,
    "show_brand_text": False,
}


class _TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class ExportPathTests(_TempCase):
    def test_numbers_when_another_folder_already_has_the_name(self) -> None:
        root = self.root / "names"
        source_dir = root / "in"
        output_dir = root / "out"
        source_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = source_dir / "photo.jpg"
        Image.new("RGB", (8, 8), "black").save(source, quality=90)
        (output_dir / "photo_watermark.jpg").write_bytes(b"old")
        (output_dir / "photo_watermark_2.jpg").write_bytes(b"old2")
        chosen = allocate_output_path(source, output_dir)
        self.assertEqual(chosen.name, "photo_watermark_3.jpg")

    def test_same_folder_keeps_the_watermark_name(self) -> None:
        folder = self.root / "same"
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "photo.jpg"
        Image.new("RGB", (8, 8), "black").save(source, quality=90)
        existing = folder / "photo_watermark.jpg"
        existing.write_bytes(b"old")
        chosen = allocate_output_path(source, folder)
        self.assertEqual(chosen.name, "photo_watermark.jpg")
        self.assertNotEqual(chosen.resolve(), source.resolve())


class ExportImageTests(_TempCase):
    def test_export_keeps_original_bytes_and_full_resolution(self) -> None:
        root = self.root / "image"
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        source = root / "scene.jpg"
        Image.new("RGB", (400, 300), (30, 60, 90)).save(source, quality=95)
        before = source.read_bytes()
        saved = Path(export_image(source, output_dir, OPTIONS, 90))
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(saved.name, "scene_watermark.jpg")
        with Image.open(saved) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size[0], 400)
            self.assertGreater(image.size[1], 300)

    def test_damaged_file_does_not_replace_the_original(self) -> None:
        root = self.root / "bad"
        root.mkdir(parents=True, exist_ok=True)
        source = root / "bad.jpg"
        source.write_bytes(b"not-a-jpeg")
        before = source.read_bytes()
        with self.assertRaises(Exception):
            export_image(source, root / "out", OPTIONS, 95)
        self.assertEqual(source.read_bytes(), before)

    def test_second_export_from_another_folder_does_not_overwrite_the_first(self) -> None:
        root = self.root / "two"
        first_dir = root / "a"
        second_dir = root / "b"
        output_dir = root / "out"
        for folder in (first_dir, second_dir):
            folder.mkdir(parents=True, exist_ok=True)
        first = first_dir / "photo.jpg"
        second = second_dir / "photo.jpg"
        Image.new("RGB", (40, 30), "red").save(first, quality=90)
        Image.new("RGB", (40, 30), "blue").save(second, quality=90)
        first_before = first.read_bytes()
        second_before = second.read_bytes()
        first_out = Path(export_image(first, output_dir, OPTIONS, 90))
        second_out = Path(export_image(second, output_dir, OPTIONS, 90))
        self.assertEqual(first_out.name, "photo_watermark.jpg")
        self.assertEqual(second_out.name, "photo_watermark_2.jpg")
        self.assertTrue(first_out.exists())
        self.assertTrue(second_out.exists())
        self.assertEqual(first.read_bytes(), first_before)
        self.assertEqual(second.read_bytes(), second_before)


class SettingsStoreTests(_TempCase):
    def test_round_trip_and_invalid_values(self) -> None:
        path = self.root / "settings.json"
        save_settings(
            {
                "output_dir": "D:/Photos/Out",
                "style": "不存在",
                "theme": "深色",
                "brand": "Ada",
                "caption": "说明",
                "scale": 9,
                "logo_path": "",
                "show_camera": False,
                "show_gps": True,
                "quality": 5,
            },
            path,
        )
        loaded = load_settings(path)
        self.assertEqual(loaded["style"], "经典底栏")
        self.assertEqual(loaded["theme"], "深色")
        self.assertEqual(loaded["scale"], 1.6)
        self.assertEqual(loaded["quality"], 80)
        self.assertEqual(loaded["brand"], "Ada")
        self.assertFalse(loaded["show_camera"])
        self.assertTrue(loaded["show_gps"])
        self.assertEqual(loaded["camera_text"], "")
        self.assertEqual(loaded["camera_scale"], 1.0)
        self.assertNotIn("files", loaded)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("photo.jpg", text)

    def test_metadata_text_and_scale_coercion(self) -> None:
        data = coerce_settings(
            {
                "camera_text": "  MyCam  ",
                "lens_text": None,
                "exif_text": "ISO 100",
                "camera_scale": 9,
                "lens_scale": "nope",
                "exif_scale": 0.2,
                "date_scale": 1.2,
            }
        )
        self.assertEqual(data["camera_text"], "  MyCam  ")
        self.assertEqual(data["lens_text"], "")
        self.assertEqual(data["exif_text"], "ISO 100")
        self.assertEqual(data["camera_scale"], 1.6)
        self.assertEqual(data["lens_scale"], 1.0)
        self.assertEqual(data["exif_scale"], 0.7)
        self.assertEqual(data["date_scale"], 1.2)

    def test_browse_dir_round_trip(self) -> None:
        path = self.root / "settings.json"
        save_settings({"browse_dir": "D:/Photos/Album", "output_dir": "D:/Out"}, path)
        loaded = load_settings(path)
        self.assertEqual(loaded["browse_dir"], "D:/Photos/Album")
        empty = coerce_settings({"browse_dir": "   "})
        self.assertTrue(str(empty["browse_dir"]).strip())

    def test_corrupt_file_falls_back_to_defaults(self) -> None:
        path = self.root / "broken.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        loaded = load_settings(path)
        self.assertEqual(loaded["style"], coerce_settings(None)["style"])
        self.assertEqual(loaded["quality"], 95)


if __name__ == "__main__":
    unittest.main()
