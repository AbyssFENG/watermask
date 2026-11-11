# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
_existing = sys.modules.get("photo_watermark_studio")
if _existing is not None and not hasattr(_existing, "__path__"):
    del sys.modules["photo_watermark_studio"]

from PIL import Image, ImageOps

from photo_watermark_studio.core.renderer import _font, _gaussian_blur
from photo_watermark_studio.workers.folder_scan import list_supported_images
from photo_watermark_studio.workers.preview_worker import clear_preview_base_cache, load_preview_base
from photo_watermark_studio.workers.thumbnail_worker import load_thumbnail
import photo_watermark_studio.workers.preview_worker as preview_worker


class _TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        clear_preview_base_cache()
        self._tmp.cleanup()


class PreviewCacheTests(_TempCase):
    def test_second_load_does_not_reopen_the_file(self) -> None:
        path = self.root / "photo.jpg"
        Image.new("RGB", (80, 40), (10, 20, 30)).save(path, quality=90)
        clear_preview_base_cache()
        opens = {"n": 0}
        real_open = preview_worker.Image.open

        def counting(file, *args, **kwargs):
            opens["n"] += 1
            return real_open(file, *args, **kwargs)

        with patch.object(preview_worker.Image, "open", counting):
            first = load_preview_base(str(path), 400)
            second = load_preview_base(str(path), 400)
        self.assertEqual(opens["n"], 1)
        self.assertEqual(first.size, second.size)
        self.assertEqual(first.getpixel((0, 0)), second.getpixel((0, 0)))
        first.putpixel((0, 0), (255, 255, 255))
        self.assertNotEqual(second.getpixel((0, 0)), (255, 255, 255))

    def test_changed_file_is_decoded_again(self) -> None:
        path = self.root / "photo.jpg"
        Image.new("RGB", (40, 20), (1, 2, 3)).save(path, quality=90)
        clear_preview_base_cache()
        load_preview_base(str(path), 400)
        Image.new("RGB", (50, 20), (4, 5, 6)).save(path, quality=90)
        opens = {"n": 0}
        real_open = preview_worker.Image.open

        def counting(file, *args, **kwargs):
            opens["n"] += 1
            return real_open(file, *args, **kwargs)

        with patch.object(preview_worker.Image, "open", counting):
            again = load_preview_base(str(path), 400)
        self.assertEqual(opens["n"], 1)
        self.assertEqual(again.size, (50, 20))


class ThumbnailTests(_TempCase):
    def test_orientation_matches_exif_transpose_and_reports_full_size(self) -> None:
        path = self.root / "turned.jpg"
        image = Image.new("RGB", (40, 16), (255, 0, 0))
        image.paste((0, 0, 255), (0, 0, 10, 16))
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, "JPEG", quality=95, exif=exif.tobytes())
        thumb, width, height = load_thumbnail(str(path), 160)
        with Image.open(path) as src:
            reference = ImageOps.exif_transpose(src).convert("RGB")
        self.assertEqual((width, height), reference.size)
        self.assertEqual(thumb.size, reference.size)
        self.assertEqual(thumb.getpixel((0, 0)), reference.getpixel((0, 0)))
        self.assertEqual(thumb.getpixel((thumb.width - 1, thumb.height - 1)), reference.getpixel((-1, -1)))

    def test_large_jpeg_reports_full_size_and_small_thumb(self) -> None:
        path = self.root / "big.jpg"
        Image.new("RGB", (1600, 900), (30, 60, 90)).save(path, quality=85)
        thumb, width, height = load_thumbnail(str(path), 80)
        self.assertEqual((width, height), (1600, 900))
        self.assertLessEqual(max(thumb.size), 80)


class FolderScanTests(_TempCase):
    def test_lists_nested_supported_files_only(self) -> None:
        nested = self.root / "roll" / "day"
        nested.mkdir(parents=True)
        Image.new("RGB", (8, 8), "red").save(nested / "a.jpg", quality=90)
        Image.new("RGB", (8, 8), "blue").save(self.root / "roll" / "b.PNG")
        (nested / "note.txt").write_text("skip", encoding="utf-8")
        found = list_supported_images(str(self.root / "roll"))
        names = [Path(item).name for item in found]
        self.assertEqual(names, ["b.PNG", "a.jpg"])


class BlurTests(unittest.TestCase):
    def test_large_radius_keeps_size(self) -> None:
        image = Image.new("RGB", (800, 240), (20, 40, 80))
        blurred = _gaussian_blur(image, 40)
        self.assertEqual(blurred.size, image.size)
        self.assertEqual(blurred.mode, "RGB")


class FontCacheTests(unittest.TestCase):
    def test_same_size_reuses_font_object(self) -> None:
        first = _font(28, text="城市")
        second = _font(28, text="城市")
        font_path = str(getattr(first, "path", "") or "")
        if not font_path:
            self.skipTest("当前环境没有可用的 TrueType 字体")
        self.assertIs(first, second)
