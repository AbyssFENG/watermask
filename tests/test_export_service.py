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

from PIL import Image, ImageCms
from PIL.ExifTags import Base as ExifBase

from photo_watermark_studio.core.export_service import allocate_output_path, export_image
from photo_watermark_studio.core.settings_store import (
    coerce_settings,
    load_settings,
    reset_watermark_settings,
    save_settings,
)

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
    "export_format": "jpg",
    "png_compress": 6,
    "webp_quality": 90,
    "keep_exif": True,
    "keep_icc": True,
}


def _srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _save_jpeg_with_meta(path: Path, *, with_exif: bool = True, with_icc: bool = True) -> None:
    image = Image.new("RGB", (48, 36), (20, 40, 60))
    kwargs: dict = {"quality": 90}
    if with_exif:
        exif = Image.Exif()
        exif[ExifBase.Orientation] = 1
        exif[ExifBase.Make] = "TestCam"
        kwargs["exif"] = exif.tobytes()
    if with_icc:
        kwargs["icc_profile"] = _srgb_icc()
    image.save(path, "JPEG", **kwargs)


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

    def test_same_folder_numbers_by_default(self) -> None:
        folder = self.root / "same"
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "photo.jpg"
        Image.new("RGB", (8, 8), "black").save(source, quality=90)
        existing = folder / "photo_watermark.jpg"
        existing.write_bytes(b"old")
        chosen = allocate_output_path(source, folder)
        self.assertEqual(chosen.name, "photo_watermark_2.jpg")
        self.assertNotEqual(chosen.resolve(), source.resolve())

    def test_overwrite_policy_keeps_watermark_name(self) -> None:
        folder = self.root / "overwrite"
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "photo.jpg"
        Image.new("RGB", (8, 8), "black").save(source, quality=90)
        existing = folder / "photo_watermark.jpg"
        existing.write_bytes(b"old")
        chosen = allocate_output_path(source, folder, conflict_policy="overwrite")
        self.assertEqual(chosen.name, "photo_watermark.jpg")


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

    def test_export_formats_use_expected_extension_and_pillow_format(self) -> None:
        root = self.root / "formats"
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        source = root / "scene.jpg"
        Image.new("RGB", (64, 48), (10, 20, 30)).save(source, quality=90)
        cases = (
            ("jpg", "scene_watermark.jpg", "JPEG"),
            ("png", "scene_watermark.png", "PNG"),
            ("webp", "scene_watermark.webp", "WEBP"),
            ("tiff", "scene_watermark.tif", "TIFF"),
        )
        for fmt, name, pillow_fmt in cases:
            options = dict(OPTIONS)
            options["export_format"] = fmt
            saved = Path(export_image(source, output_dir, options, 90))
            self.assertEqual(saved.name, name)
            with Image.open(saved) as image:
                self.assertEqual(image.format, pillow_fmt)

    def test_allocate_output_path_respects_extension(self) -> None:
        folder = self.root / "ext"
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "photo.png"
        Image.new("RGB", (8, 8), "black").save(source)
        (folder / "photo_watermark.png").write_bytes(b"old")
        chosen = allocate_output_path(source, folder, ext=".png")
        self.assertEqual(chosen.name, "photo_watermark_2.png")

    def test_keep_exif_false_drops_exif(self) -> None:
        root = self.root / "exif"
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        source = root / "meta.jpg"
        _save_jpeg_with_meta(source, with_exif=True, with_icc=False)
        with Image.open(source) as src:
            self.assertTrue(bool(src.getexif()))
        options = dict(OPTIONS)
        options["keep_exif"] = False
        options["keep_icc"] = False
        saved = Path(export_image(source, output_dir, options, 90))
        with Image.open(saved) as image:
            self.assertFalse(bool(image.getexif()))

    def test_keep_icc_true_and_false(self) -> None:
        root = self.root / "icc"
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        source = root / "profile.jpg"
        _save_jpeg_with_meta(source, with_exif=False, with_icc=True)
        with Image.open(source) as src:
            self.assertTrue(bool(src.info.get("icc_profile")))

        kept = dict(OPTIONS)
        kept["keep_icc"] = True
        kept["keep_exif"] = False
        kept_path = Path(export_image(source, output_dir, kept, 90))
        with Image.open(kept_path) as image:
            self.assertTrue(bool(image.info.get("icc_profile")))

        dropped = dict(OPTIONS)
        dropped["keep_icc"] = False
        dropped["keep_exif"] = False
        dropped["conflict_policy"] = "number"
        # Force a distinct name by pre-creating the default target.
        (output_dir / "profile_watermark.jpg").write_bytes(b"x")
        dropped_path = Path(export_image(source, output_dir, dropped, 90))
        with Image.open(dropped_path) as image:
            self.assertFalse(bool(image.info.get("icc_profile")))

    def test_export_applies_orientation_and_marks_it_upright(self) -> None:
        root = self.root / "orient"
        output_dir = root / "out"
        output_dir.mkdir(parents=True)
        source = root / "side.jpg"
        image = Image.new("RGB", (30, 12), (255, 0, 0))
        image.paste((0, 0, 255), (0, 0, 8, 12))
        exif = Image.Exif()
        exif[274] = 6
        exif[271] = "TestCam"
        image.save(source, "JPEG", quality=95, exif=exif.tobytes())
        saved = Path(export_image(source, output_dir, OPTIONS, 90))
        with Image.open(saved) as out:
            self.assertEqual(out.size[0], 12)
            self.assertGreater(out.size[1], 30)
            saved_exif = out.getexif()
            self.assertEqual(int(saved_exif.get(274) or 0), 1)
            self.assertEqual(str(saved_exif.get(271) or ""), "TestCam")

    def test_bad_icc_bytes_still_export(self) -> None:
        root = self.root / "bad-icc"
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        source = root / "weird.jpg"
        image = Image.new("RGB", (32, 24), (1, 2, 3))
        image.save(source, "JPEG", quality=90, icc_profile=b"not-a-real-icc-profile")
        options = dict(OPTIONS)
        options["keep_icc"] = True
        saved = Path(export_image(source, output_dir, options, 90))
        self.assertTrue(saved.is_file())
        with Image.open(saved) as out:
            self.assertEqual(out.format, "JPEG")
            self.assertEqual(out.size[0], 32)


class SettingsStoreTests(_TempCase):
    def test_reset_watermark_keeps_export_and_restores_design(self) -> None:
        current = {
            "output_dir": "D:/Photos/Out",
            "browse_dir": "D:/Photos/In",
            "style": "卡片相框",
            "base_style": "极简叠加",
            "theme": "深色",
            "brand": "Ada",
            "caption": "城市",
            "scale": 1.4,
            "logo_path": "D:/logo.png",
            "show_camera": False,
            "show_date": True,
            "quality": 80,
            "export_format": "png",
            "png_compress": 2,
            "webp_quality": 70,
            "keep_exif": False,
            "keep_icc": False,
            "conflict_policy": "overwrite",
            "layout": {
                "bar_height": 1.8,
                "side_pad": 1.6,
                "pad_top": 1.4,
                "pad_bottom": 0.6,
                "bar_opacity": 0.4,
                "field_positions": {"brand": {"x": 0.2, "y": 0.3}},
            },
        }
        reset = reset_watermark_settings(current)
        self.assertEqual(reset["output_dir"], "D:/Photos/Out")
        self.assertEqual(reset["browse_dir"], "D:/Photos/In")
        self.assertEqual(reset["quality"], 80)
        self.assertEqual(reset["export_format"], "png")
        self.assertEqual(reset["png_compress"], 2)
        self.assertEqual(reset["webp_quality"], 70)
        self.assertFalse(reset["keep_exif"])
        self.assertFalse(reset["keep_icc"])
        self.assertEqual(reset["conflict_policy"], "overwrite")
        self.assertEqual(reset["style"], "经典底栏")
        self.assertEqual(reset["theme"], "白色")
        self.assertEqual(reset["brand"], "")
        self.assertEqual(reset["caption"], "")
        self.assertEqual(reset["logo_path"], "")
        self.assertAlmostEqual(reset["scale"], 1.0)
        self.assertTrue(reset["show_camera"])
        self.assertFalse(reset["show_date"])
        self.assertAlmostEqual(reset["layout"]["bar_height"], 1.0)
        self.assertAlmostEqual(reset["layout"]["side_pad"], 1.0)
        self.assertAlmostEqual(reset["layout"]["pad_top"], 1.0)
        self.assertAlmostEqual(reset["layout"]["pad_bottom"], 1.0)
        self.assertAlmostEqual(reset["layout"]["bar_opacity"], 0.72)
        self.assertEqual(reset["layout"]["field_positions"], {})

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
        self.assertEqual(loaded["theme"], "黑色")
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
        self.assertEqual(loaded["export_format"], "jpg")
        self.assertTrue(loaded["keep_exif"])
        self.assertTrue(loaded["keep_icc"])

    def test_export_settings_coercion(self) -> None:
        data = coerce_settings(
            {
                "export_format": "JPEG",
                "png_compress": 99,
                "webp_quality": 0,
                "keep_exif": 0,
                "keep_icc": 1,
            }
        )
        self.assertEqual(data["export_format"], "jpg")
        self.assertEqual(data["png_compress"], 9)
        self.assertEqual(data["webp_quality"], 1)
        self.assertFalse(data["keep_exif"])
        self.assertTrue(data["keep_icc"])
        bad = coerce_settings({"export_format": "bmp", "png_compress": "x", "webp_quality": "y"})
        self.assertEqual(bad["export_format"], "jpg")
        self.assertEqual(bad["png_compress"], 6)
        self.assertEqual(bad["webp_quality"], 90)


if __name__ == "__main__":
    unittest.main()
