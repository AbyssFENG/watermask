# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
_existing = sys.modules.get("photo_watermark_studio")
if _existing is not None and not hasattr(_existing, "__path__"):
    del sys.modules["photo_watermark_studio"]

from photo_watermark_studio.core.font_presets import (
    DEFAULT_FONT_FAMILY,
    available_font_names,
    available_font_presets,
    coerce_font_family,
    font_covers_cjk,
    resolve_font_path,
)
from photo_watermark_studio.core.renderer import _font, _resolved_font_path
from photo_watermark_studio.core.settings_store import coerce_field_opacity, coerce_settings


class FontPresetTests(unittest.TestCase):
    def test_coerce_font_family_defaults(self) -> None:
        self.assertEqual(coerce_font_family(""), DEFAULT_FONT_FAMILY)
        self.assertEqual(coerce_font_family(None), DEFAULT_FONT_FAMILY)
        self.assertEqual(coerce_font_family("不存在的字体"), DEFAULT_FONT_FAMILY)
        self.assertEqual(coerce_font_family("楷体"), "楷体")
        self.assertEqual(coerce_font_family("微软雅黑"), "微软雅黑")
        self.assertEqual(coerce_font_family("Georgia"), "Georgia")
        self.assertFalse(font_covers_cjk("Georgia"))
        self.assertTrue(font_covers_cjk("宋体"))
        self.assertTrue(font_covers_cjk(DEFAULT_FONT_FAMILY))

    def test_coerce_settings_keeps_valid_field_font(self) -> None:
        data = coerce_settings({"camera_font": "华文行楷", "brand_font": "楷体"})
        self.assertEqual(data["camera_font"], "华文行楷")
        self.assertEqual(data["brand_font"], "楷体")
        bad = coerce_settings({"lens_font": "Comic Sans"})
        self.assertEqual(bad["lens_font"], DEFAULT_FONT_FAMILY)

    def test_coerce_field_opacity_clamps(self) -> None:
        self.assertAlmostEqual(coerce_field_opacity(0.1), 0.3)
        self.assertAlmostEqual(coerce_field_opacity(1.5), 1.0)
        self.assertAlmostEqual(coerce_field_opacity(0.75), 0.75)
        data = coerce_settings({"camera_opacity": 0.05, "brand_opacity": 0.8})
        self.assertAlmostEqual(data["camera_opacity"], 0.3)
        self.assertAlmostEqual(data["brand_opacity"], 0.8)

    def test_available_names_start_with_default(self) -> None:
        names = available_font_names()
        self.assertEqual(names[0], DEFAULT_FONT_FAMILY)

    def test_resolve_default_is_none(self) -> None:
        self.assertIsNone(resolve_font_path(DEFAULT_FONT_FAMILY))

    @unittest.skipUnless(os.name == "nt", "Windows fonts only")
    def test_windows_artistic_fonts_detected(self) -> None:
        presets = available_font_presets()
        self.assertTrue(any(p.name == "楷体" for p in presets))
        path = resolve_font_path("楷体")
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(Path(path).is_file())

    @unittest.skipUnless(os.name == "nt" and Path(r"C:\Windows\Fonts\simkai.ttf").is_file(), "simkai required")
    def test_font_prefers_resolved_path(self) -> None:
        with mock.patch(
            "photo_watermark_studio.core.renderer.resolve_font_path",
            return_value=r"C:\Windows\Fonts\simkai.ttf",
        ):
            font = _font(24, text="测试", font_family="楷体")
            self.assertIsNotNone(font)
            path = getattr(font, "path", None)
            self.assertIsNotNone(path)
            self.assertTrue(str(path).lower().endswith("simkai.ttf"))

    @unittest.skipUnless(os.name == "nt" and Path(r"C:\Windows\Fonts\georgia.ttf").is_file(), "georgia required")
    def test_latin_font_falls_back_for_cjk(self) -> None:
        _resolved_font_path.cache_clear()
        latin = _resolved_font_path("Georgia", False, False, False)
        cjk = _resolved_font_path("Georgia", False, False, True)
        self.assertTrue(latin.lower().endswith("georgia.ttf"))
        self.assertTrue(cjk.lower().endswith("msyh.ttc"))

    @unittest.skipUnless(
        os.name == "nt" and Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf").is_file(),
        "noto sans sc required",
    )
    def test_variable_cjk_font_uses_regular_weight(self) -> None:
        from PIL import Image, ImageDraw, ImageFont

        def ink(font: ImageFont.ImageFont) -> int:
            image = Image.new("L", (80, 80), 0)
            ImageDraw.Draw(image).text((4, 4), "永", font=font, fill=255)
            return sum(1 for px in image.get_flattened_data() if px)

        regular = _font(48, text="永", font_family="思源黑体")
        thin = ImageFont.truetype(r"C:\Windows\Fonts\NotoSansSC-VF.ttf", 48)
        self.assertGreater(ink(regular), ink(thin))


if __name__ == "__main__":
    unittest.main()
