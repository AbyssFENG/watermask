# -*- coding: utf-8 -*-
from __future__ import annotations

import os
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

from photo_watermark_studio.core.models import PhotoMetadata
from photo_watermark_studio.core.renderer import (
    _font,
    _font_has_dot,
    _frosted_overlay_strip,
    _metadata_lines,
    _needs_cjk,
    _separator_width,
    format_exposure_line,
    metadata_placeholders,
    render_watermark,
    render_watermark_layers,
    render_watermark_with_hits,
)

OPTIONS = {
    "style": "经典底栏",
    "base_style": "经典底栏",
    "theme": "浅色",
    "brand": "测试署名",
    "caption": "城市",
    "scale": 1.0,
    "camera_font": "默认",
    "lens_font": "默认",
    "exif_font": "默认",
    "date_font": "默认",
    "gps_font": "默认",
    "brand_font": "默认",
    "caption_font": "默认",
    "camera_bold": True,
    "lens_bold": True,
    "exif_bold": False,
    "date_bold": False,
    "gps_bold": False,
    "brand_bold": True,
    "caption_bold": False,
    "camera_opacity": 1.0,
    "lens_opacity": 1.0,
    "exif_opacity": 1.0,
    "date_opacity": 1.0,
    "gps_opacity": 1.0,
    "brand_opacity": 1.0,
    "caption_opacity": 1.0,
    "logo_path": "",
    "show_logo": True,
    "show_camera": True,
    "show_lens": True,
    "show_exif": True,
    "show_date": True,
    "show_gps": True,
    "show_brand_text": False,
    "camera_text": "",
    "lens_text": "",
    "exif_text": "",
    "date_text": "",
    "gps_text": "",
    "camera_scale": 1.0,
    "lens_scale": 1.0,
    "exif_scale": 1.0,
    "date_scale": 1.0,
    "gps_scale": 1.0,
}


class RendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.source = self.folder / "plain.png"
        Image.new("RGB", (320, 240), (80, 110, 140)).save(self.source)
        self.logo = self.folder / "logo.png"
        Image.new("RGBA", (40, 16), (255, 0, 0, 180)).save(self.logo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_landscape_and_portrait_share_bar_height(self) -> None:
        # 同短边：4:3 横图与 3:4 竖图的经典底栏高度应一致。
        landscape = self.folder / "land_4x3.png"
        portrait = self.folder / "port_3x4.png"
        Image.new("RGB", (400, 300), (80, 110, 140)).save(landscape)
        Image.new("RGB", (300, 400), (80, 110, 140)).save(portrait)
        opts = {**OPTIONS, "style": "经典底栏", "scale": 1.0}
        _land, land_hits = render_watermark_with_hits(landscape, opts)
        _port, port_hits = render_watermark_with_hits(portrait, opts)
        land_bar = next(hit for hit in land_hits if hit.get("key") == "watermark_bar")
        port_bar = next(hit for hit in port_hits if hit.get("key") == "watermark_bar")
        self.assertAlmostEqual(float(land_bar["h"]), float(port_bar["h"]), delta=1.0)
        overlay_opts = {**OPTIONS, "style": "极简叠加", "scale": 1.0}
        _lo, lo_hits = render_watermark_with_hits(landscape, overlay_opts)
        _po, po_hits = render_watermark_with_hits(portrait, overlay_opts)
        lo_bar = next(hit for hit in lo_hits if hit.get("key") == "watermark_bar")
        po_bar = next(hit for hit in po_hits if hit.get("key") == "watermark_bar")
        self.assertAlmostEqual(float(lo_bar["h"]), float(po_bar["h"]), delta=1.0)

    def test_three_templates_change_canvas_size(self) -> None:
        overlay = render_watermark(self.source, {**OPTIONS, "style": "极简叠加"})
        classic = render_watermark(self.source, {**OPTIONS, "style": "经典底栏"})
        card = render_watermark(self.source, {**OPTIONS, "style": "卡片相框"})
        plain = render_watermark(self.source, {**OPTIONS, "style": "纯文字中下"})
        self.assertEqual(overlay.size, (320, 240))
        self.assertEqual(classic.size[0], 320)
        self.assertGreater(classic.size[1], 240)
        self.assertGreater(card.size[0], 320)
        self.assertGreater(card.size[1], 240)
        self.assertEqual(plain.size, (320, 240))
        self.assertEqual(overlay.mode, "RGB")
        self.assertEqual(classic.mode, "RGB")
        self.assertEqual(card.mode, "RGB")
        self.assertEqual(plain.mode, "RGB")

    def test_plain_text_style_keeps_source_size_and_bar_hit(self) -> None:
        image, hits = render_watermark_with_hits(self.source, {**OPTIONS, "style": "纯文字中下"})
        self.assertEqual(image.size, (320, 240))
        bar = next(hit for hit in hits if hit.get("key") == "watermark_bar")
        self.assertGreater(float(bar["h"]), 10)
        self.assertGreater(float(bar["y"]), 100)

    def test_custom_freeform_default_stack_hits_overlap_text(self) -> None:
        opts = {
            **OPTIONS,
            "style": "自定义",
            "base_style": "纯文字中下",
            "brand": "署名A",
            "field_positions": {},
        }
        image, hits = render_watermark_with_hits(self.source, opts)
        self.assertEqual(image.size, (320, 240))
        self.assertFalse(any(h.get("key") == "watermark_bar" for h in hits))
        brand = next(h for h in hits if h.get("key") == "brand")
        photo = next(h for h in hits if h.get("key") == "photo_content")
        self.assertAlmostEqual(float(photo["w"]), 320, delta=1)
        # 默认中下：命中框中心应接近默认 brand 坐标。
        cx = float(brand["x"]) + float(brand["w"]) / 2
        cy = float(brand["y"]) + float(brand["h"]) / 2
        self.assertAlmostEqual(cx / 320, 0.5, delta=0.08)
        self.assertGreater(cy / 240, 0.6)

    def test_custom_field_positions_place_hit_center(self) -> None:
        opts = {
            **OPTIONS,
            "style": "自定义",
            "base_style": "经典底栏",
            "brand": "定点",
            "show_camera": False,
            "show_lens": False,
            "show_exif": False,
            "show_date": False,
            "show_gps": False,
            "caption": "",
            "field_positions": {"brand": {"x": 0.25, "y": 0.35}},
        }
        img, hits = render_watermark_with_hits(self.source, opts)
        brand = next(h for h in hits if h.get("key") == "brand")
        cx = float(brand["x"]) + float(brand["w"]) / 2
        cy = float(brand["y"]) + float(brand["h"]) / 2
        self.assertAlmostEqual(cx / img.size[0], 0.25, delta=0.04)
        self.assertAlmostEqual(cy / img.size[1], 0.35, delta=0.04)

    def test_custom_layers_separate_base_and_sprites(self) -> None:
        opts = {
            **OPTIONS,
            "style": "自定义",
            "base_style": "纯文字中下",
            "brand": "LAYER",
            "show_camera": False,
            "show_lens": False,
            "show_exif": False,
            "show_date": False,
            "show_gps": False,
            "caption": "",
            "field_positions": {"brand": {"x": 0.5, "y": 0.4}},
        }
        layers = render_watermark_layers(self.source, opts)
        base = layers["base"]
        composite = layers["composite"]
        sprites = layers["sprites"]
        self.assertEqual(base.size, composite.size)
        self.assertTrue(any(s.get("key") == "brand" for s in sprites))
        brand_spr = next(s for s in sprites if s.get("key") == "brand")
        spr_img = brand_spr["image"]
        self.assertEqual(spr_img.mode, "RGBA")
        # 精灵应含非透明像素；底版对应区域不应等于整段合成（字段在精灵层）。
        bands = spr_img.split()
        self.assertGreater(sum(1 for a in bands[3].getdata() if a > 0), 10)
        cx = int(brand_spr["x"] + brand_spr["w"] / 2)
        cy = int(brand_spr["y"] + brand_spr["h"] / 2)
        self.assertNotEqual(base.getpixel((cx, cy)), composite.getpixel((cx, cy)))
        # 合成与 with_hits 尺寸一致，hit 中心对齐坐标。
        img, hits = render_watermark_with_hits(self.source, opts)
        self.assertEqual(img.size, composite.size)
        brand_hit = next(h for h in hits if h.get("key") == "brand")
        hx = float(brand_hit["x"]) + float(brand_hit["w"]) / 2
        hy = float(brand_hit["y"]) + float(brand_hit["h"]) / 2
        self.assertAlmostEqual(hx / img.size[0], 0.5, delta=0.05)
        self.assertAlmostEqual(hy / img.size[1], 0.4, delta=0.05)

    def test_non_custom_layers_has_empty_sprites(self) -> None:
        layers = render_watermark_layers(self.source, {**OPTIONS, "style": "经典底栏"})
        self.assertEqual(layers["sprites"], [])
        self.assertEqual(layers["base"].size, layers["composite"].size)

    def test_custom_card_allows_field_outside_photo(self) -> None:
        opts = {
            **OPTIONS,
            "style": "自定义",
            "base_style": "卡片相框",
            "brand": "边框",
            "show_camera": False,
            "show_lens": False,
            "show_exif": False,
            "show_date": False,
            "show_gps": False,
            "caption": "",
            "field_positions": {"brand": {"x": 0.5, "y": 0.95}},
        }
        img, hits = render_watermark_with_hits(self.source, opts)
        brand = next(h for h in hits if h.get("key") == "brand")
        photo = next(h for h in hits if h.get("key") == "photo_content")
        cx = float(brand["x"]) + float(brand["w"]) / 2
        cy = float(brand["y"]) + float(brand["h"]) / 2
        self.assertAlmostEqual(cx / img.size[0], 0.5, delta=0.04)
        self.assertAlmostEqual(cy / img.size[1], 0.95, delta=0.04)
        photo_bottom = float(photo["y"]) + float(photo["h"])
        self.assertGreater(cy, photo_bottom)
        self.assertLess(cy, float(img.size[1]))

    def test_non_custom_ignores_field_positions(self) -> None:
        base = {**OPTIONS, "style": "经典底栏", "brand": "B"}
        _a, hits_a = render_watermark_with_hits(self.source, base)
        _b, hits_b = render_watermark_with_hits(
            self.source,
            {**base, "field_positions": {"brand": {"x": 0.1, "y": 0.1}}},
        )
        bar_a = next(h for h in hits_a if h.get("key") == "watermark_bar")
        bar_b = next(h for h in hits_b if h.get("key") == "watermark_bar")
        self.assertAlmostEqual(float(bar_a["y"]), float(bar_b["y"]), delta=1.0)
        self.assertAlmostEqual(float(bar_a["h"]), float(bar_b["h"]), delta=1.0)

    def test_overlay_frosted_uses_aligned_strip(self) -> None:
        # 构造带明显横条的图，确保磨砂条与原图同宽同高、不因取样缩放错位。
        base = Image.new("RGB", (200, 120), (30, 30, 30))
        for y in range(80, 120):
            for x in range(200):
                base.putpixel((x, y), (200, 40, 40) if y < 100 else (40, 200, 40))
        strip = _frosted_overlay_strip(base, top=80, height=40, radius=4)
        self.assertEqual(strip.size, (200, 40))
        # 模糊后仍应偏红（上半取样区），而不是被整段底部压扁后的混合色主导错位。
        r, g, b = strip.getpixel((100, 5))
        self.assertGreater(r, g)
        self.assertGreater(r, b)
        image = render_watermark(
            self.source,
            {**OPTIONS, "style": "极简叠加", "theme": "高斯模糊"},
        )
        with Image.open(self.source) as src:
            self.assertEqual(image.size, src.size)

    def test_chinese_caption_uses_cjk_font_and_keeps_text(self) -> None:
        self.assertTrue(_needs_cjk("城市夜景"))
        self.assertFalse(_needs_cjk("ISO 100"))
        font = _font(18, text="城市夜景")
        font_path = str(getattr(font, "path", "") or "").lower()
        if os.name == "nt" and Path(r"C:\Windows\Fonts\msyh.ttc").is_file():
            self.assertTrue(
                any(name in font_path for name in ("msyh", "simhei", "simsun")),
                font_path,
            )
        _image, hits = render_watermark_with_hits(
            self.source,
            {**OPTIONS, "caption": "城市夜景", "show_date": False, "show_gps": False},
        )
        caption_hits = [hit for hit in hits if hit.get("key") == "caption"]
        self.assertTrue(caption_hits)
        self.assertEqual(caption_hits[0]["text"], "城市夜景")
        self.assertGreater(float(caption_hits[0]["w"]), 20)

    def test_card_style_keeps_brand_with_logo(self) -> None:
        _image, hits = render_watermark_with_hits(
            self.source,
            {
                **OPTIONS,
                "style": "卡片相框",
                "brand": "Studio Name",
                "logo_path": str(self.logo),
            },
        )
        keys = {hit["key"] for hit in hits}
        self.assertIn("brand", keys)
        brand_hit = next(hit for hit in hits if hit["key"] == "brand")
        self.assertEqual(brand_hit["text"], "Studio Name")

    def test_hidden_logo_keeps_path_but_skips_draw(self) -> None:
        visible = render_watermark(self.source, {**OPTIONS, "logo_path": str(self.logo), "show_logo": True})
        hidden = render_watermark(self.source, {**OPTIONS, "logo_path": str(self.logo), "show_logo": False})
        self.assertEqual(visible.size, hidden.size)
        self.assertEqual(hidden.mode, "RGB")

    def test_themes_logo_and_missing_logo_do_not_crash(self) -> None:
        for theme in ("白色", "黑色", "高斯模糊"):
            image = render_watermark(self.source, {**OPTIONS, "theme": theme, "logo_path": str(self.logo)})
            self.assertGreater(image.size[0], 0)
        for style in ("经典底栏", "极简叠加", "卡片相框", "纯文字中下"):
            image = render_watermark(
                self.source,
                {**OPTIONS, "style": style, "theme": "高斯模糊", "logo_path": str(self.logo)},
            )
            self.assertEqual(image.mode, "RGB")
            self.assertGreater(image.size[0], 0)
        missing = render_watermark(self.source, {**OPTIONS, "logo_path": str(self.folder / "gone.png")})
        self.assertEqual(missing.size[0], 320)
        broken = render_watermark(self.source, {**OPTIONS, "logo_path": str(self.source), "scale": 9})
        self.assertEqual(broken.size[0], 320)

    def test_image_without_exif_still_renders_caption(self) -> None:
        image = render_watermark(self.source, {**OPTIONS, "show_camera": False, "show_lens": False, "show_exif": False, "show_date": False, "show_gps": False})
        self.assertEqual(image.size[0], 320)

    def test_empty_brand_still_renders_all_styles(self) -> None:
        for style in ("经典底栏", "极简叠加", "卡片相框", "纯文字中下"):
            image = render_watermark(self.source, {**OPTIONS, "style": style, "brand": ""})
            self.assertGreater(image.size[0], 0)
            self.assertEqual(image.mode, "RGB")

    def test_custom_text_overrides_and_unchecked_fields(self) -> None:
        md = PhotoMetadata(
            camera="RAW CAM",
            lens="RAW LENS",
            iso="200",
            focal="50mm",
            aperture="f/2.8",
            shutter="1/200s",
            date="2020-01-01",
            gps="1.0, 2.0",
        )
        title, detail, extra = _metadata_lines(
            md,
            {
                **OPTIONS,
                "camera_text": "Custom Cam",
                "lens_text": "",
                "exif_text": "ISO 999 | MANUAL",
                "date_text": "My Date",
                "gps_text": "",
                "show_gps": False,
            },
        )
        self.assertIn("Custom Cam", title)
        self.assertIn("RAW LENS", title)
        self.assertEqual(detail, "ISO 999 | MANUAL")
        self.assertEqual(extra, "My Date")
        title2, detail2, extra2 = _metadata_lines(
            md,
            {**OPTIONS, "show_camera": False, "show_lens": False, "show_exif": False, "show_date": False, "show_gps": False},
        )
        self.assertEqual(title2, "")
        self.assertEqual(detail2, "")
        self.assertEqual(extra2, "")

    def test_placeholders_and_segment_scales_render(self) -> None:
        md = PhotoMetadata(camera="Cam", lens="Lens", iso="100", focal="35mm", aperture="f/1.8", shutter="1/60s")
        hints = metadata_placeholders(md)
        self.assertEqual(hints["camera"], "Cam")
        self.assertEqual(hints["exif"], format_exposure_line(md))
        image = render_watermark(
            self.source,
            {
                **OPTIONS,
                "camera_text": "BigCam",
                "lens_text": "TinyLens",
                "camera_scale": 1.4,
                "lens_scale": 0.75,
                "exif_scale": 1.2,
            },
        )
        self.assertEqual(image.mode, "RGB")
        self.assertGreater(image.size[0], 0)

    def test_render_returns_clickable_hits(self) -> None:
        image, hits = render_watermark_with_hits(
            self.source,
            {**OPTIONS, "brand": "tjf", "camera_text": "CamX", "lens_text": "LensY"},
        )
        self.assertEqual(image.mode, "RGB")
        keys = {hit["key"] for hit in hits}
        self.assertIn("brand", keys)
        self.assertIn("camera", keys)
        self.assertIn("lens", keys)
        for hit in hits:
            self.assertGreater(hit["w"], 0)
            self.assertGreater(hit["h"], 0)

    def test_default_bar_metrics_match_explicit_100_percent(self) -> None:
        implicit, implicit_hits = render_watermark_with_hits(self.source, {**OPTIONS, "style": "经典底栏"})
        explicit, explicit_hits = render_watermark_with_hits(
            self.source,
            {**OPTIONS, "style": "经典底栏", "bar_height": 1.0, "side_pad": 1.0, "pad_top": 1.0, "pad_bottom": 1.0},
        )
        implicit_bar = next(hit for hit in implicit_hits if hit["key"] == "watermark_bar")
        explicit_bar = next(hit for hit in explicit_hits if hit["key"] == "watermark_bar")
        self.assertEqual(implicit.size, explicit.size)
        self.assertAlmostEqual(float(implicit_bar["h"]), float(explicit_bar["h"]), delta=0.1)

    def test_bar_height_increases_classic_and_overlay_bars(self) -> None:
        for style in ("经典底栏", "极简叠加"):
            _, short_hits = render_watermark_with_hits(
                self.source, {**OPTIONS, "style": style, "bar_height": 0.6}
            )
            _, tall_hits = render_watermark_with_hits(
                self.source, {**OPTIONS, "style": style, "bar_height": 1.8}
            )
            short_bar = next(hit for hit in short_hits if hit["key"] == "watermark_bar")
            tall_bar = next(hit for hit in tall_hits if hit["key"] == "watermark_bar")
            self.assertGreater(float(tall_bar["h"]), float(short_bar["h"]))

    def test_card_side_pad_widens_canvas(self) -> None:
        narrow = render_watermark(self.source, {**OPTIONS, "style": "卡片相框", "side_pad": 0.4})
        default = render_watermark(self.source, {**OPTIONS, "style": "卡片相框"})
        wide = render_watermark(self.source, {**OPTIONS, "style": "卡片相框", "side_pad": 2.0})
        self.assertLess(narrow.size[0], default.size[0])
        self.assertGreater(wide.size[0], default.size[0])
        self.assertEqual(default.size[0], 320 + 44)

    def test_watermark_scale_affects_camera_and_lens(self) -> None:
        wide = self.folder / "wide.jpg"
        Image.new("RGB", (1600, 900), (80, 110, 140)).save(wide, quality=90)
        base_opts = {
            **OPTIONS,
            "brand": "tjf",
            "camera_text": "NIKON CORPORATION NIKON Z5_2",
            "lens_text": "NIKKOR Z 24-120MM F/4 S",
            "show_exif": False,
            "show_date": False,
            "show_gps": False,
        }
        _, small_hits = render_watermark_with_hits(wide, {**base_opts, "scale": 0.7})
        _, large_hits = render_watermark_with_hits(wide, {**base_opts, "scale": 1.5})
        small_cam = next(hit for hit in small_hits if hit["key"] == "camera")
        large_cam = next(hit for hit in large_hits if hit["key"] == "camera")
        small_lens = next(hit for hit in small_hits if hit["key"] == "lens")
        large_lens = next(hit for hit in large_hits if hit["key"] == "lens")
        self.assertGreater(large_cam["h"], small_cam["h"])
        self.assertGreater(large_lens["h"], small_lens["h"])

    def test_italic_shears_glyphs(self) -> None:
        base = {
            **OPTIONS,
            "style": "经典底栏",
            "brand": "",
            "caption": "",
            "show_logo": False,
            "show_camera": False,
            "show_lens": False,
            "show_date": False,
            "show_gps": False,
            "exif_text": "ISO 100",
        }
        upright = render_watermark(self.source, {**base, "exif_italic": False})
        slanted = render_watermark(self.source, {**base, "exif_italic": True})
        self.assertEqual(upright.size, slanted.size)
        self.assertNotEqual(upright.tobytes(), slanted.tobytes())

    def test_default_font_keeps_middle_dot_glyph(self) -> None:
        from PIL import ImageDraw

        font = _font(32, text="NIKKOR")
        self.assertTrue(_font_has_dot(font))
        draw = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        sep = "  ·  "
        box = draw.textbbox((0, 0), sep, font=font)
        self.assertEqual(_separator_width(draw, sep, font), box[2] - box[0])

    @unittest.skipUnless(
        os.name == "nt" and Path(r"C:\Windows\Fonts\LHANDW.TTF").is_file(),
        "lucida handwriting required",
    )
    def test_missing_middle_dot_is_filled_not_a_box(self) -> None:
        font = _font(32, text="NIKKOR", font_family="Lucida Handwriting")
        self.assertFalse(_font_has_dot(font))
        opts = {
            **OPTIONS,
            "style": "经典底栏",
            "brand": "",
            "caption": "",
            "show_logo": False,
            "show_exif": False,
            "show_date": False,
            "show_gps": False,
            "shadow_strength": 0,
            "camera_text": "NIKON",
            "lens_text": "NIKKOR",
            "lens_font": "Lucida Handwriting",
        }
        image, hits = render_watermark_with_hits(self.source, opts)
        camera = next(hit for hit in hits if hit["key"] == "camera")
        lens = next(hit for hit in hits if hit["key"] == "lens")
        x0 = int(camera["x"] + camera["w"])
        x1 = int(lens["x"])
        self.assertGreater(x1, x0 + 2)
        inset = max(1, (x1 - x0) // 5)
        y0 = max(0, int(camera["y"]))
        y1 = min(image.height, int(camera["y"] + camera["h"]))
        dark: list[tuple[int, int]] = []
        for y in range(y0, y1):
            for x in range(x0 + inset, x1 - inset):
                pixel = image.getpixel((x, y))
                if pixel[0] + pixel[1] + pixel[2] < 180 * 3:
                    dark.append((x, y))
        self.assertTrue(dark)
        min_x = min(px for px, _py in dark)
        max_x = max(px for px, _py in dark)
        min_y = min(py for _px, py in dark)
        max_y = max(py for _px, py in dark)
        center = ((min_x + max_x) // 2, (min_y + max_y) // 2)
        self.assertIn(center, set(dark))
        self.assertLess(max_y - min_y, (y1 - y0) * 0.55)


if __name__ == "__main__":
    unittest.main()
