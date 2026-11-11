# -*- coding: utf-8 -*-
"""胶片边框、Logo 徽记、分隔线、四边边距、圆角，以及对应的面板与左栏联动。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from PIL import Image, ImageChops
from PySide6.QtWidgets import QApplication

from photo_watermark_studio.core import settings_store, template_store
from photo_watermark_studio.core.document import WatermarkDocument
from photo_watermark_studio.core.renderer import (
    _color_theme,
    compose_exposure_line,
    parse_exposure_line,
    render_watermark,
    render_watermark_with_hits,
)

BASE = {
    "style": "经典底栏",
    "theme": "白色",
    "brand": "停下时光",
    "caption": "",
    "show_brand_text": True,
}


def _opts(**overrides):
    return WatermarkDocument({**BASE, **overrides}).render_options()


def _opts_with_layout(layout, **overrides):
    return WatermarkDocument({**BASE, **overrides, "layout": layout}).render_options()


class StudioRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.source = self.folder / "plain.png"
        Image.new("RGB", (600, 400), (80, 110, 140)).save(self.source)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_film_border_all_themes(self) -> None:
        for theme in settings_store.THEMES:
            image, hits = render_watermark_with_hits(self.source, _opts(style="胶片边框", theme=theme))
            self.assertEqual(image.mode, "RGB")
            self.assertGreater(image.size[0], 600)
            self.assertGreater(image.size[1], 400)
            left = image.size[0] - 600
            self.assertEqual(left % 2, 0, "左右边框默认等宽")
            keys = {hit["key"] for hit in hits}
            self.assertIn("brand", keys)
            self.assertIn("watermark_bar", keys)

    def test_film_border_has_equal_side_pads_and_photo_inside(self) -> None:
        image = render_watermark(self.source, _opts(style="胶片边框", theme="黑色"))
        pad = (image.size[0] - 600) // 2
        self.assertEqual(image.getpixel((pad + 10, pad + 10)), (80, 110, 140))
        self.assertEqual(image.getpixel((2, 2)), (8, 8, 10))

    def test_nikon_mark_uses_bundled_logo(self) -> None:
        plain = render_watermark(self.source, _opts(logo_mark=""))
        nikon = render_watermark(self.source, _opts(logo_mark="nikon"))
        self.assertEqual(plain.size, nikon.size)
        self.assertIsNotNone(ImageChops.difference(plain, nikon).getbbox())

    def test_letter_logo_draws_badge_only_without_file(self) -> None:
        plain, plain_hits = render_watermark_with_hits(self.source, _opts(logo_mark=""))
        badge, badge_hits = render_watermark_with_hits(self.source, _opts(logo_mark="nikon"))
        self.assertEqual(plain.size, badge.size)
        self.assertIsNotNone(ImageChops.difference(plain, badge).getbbox())
        brand_plain = next(hit for hit in plain_hits if hit["key"] == "brand")
        brand_badge = next(hit for hit in badge_hits if hit["key"] == "brand")
        self.assertGreater(brand_badge["x"], brand_plain["x"], "有徽记时署名右移")

    def test_uploaded_logo_takes_priority_over_mark(self) -> None:
        logo = self.folder / "logo.png"
        Image.new("RGBA", (60, 20), (255, 0, 0, 255)).save(logo)
        with_file = render_watermark(self.source, _opts(logo_path=str(logo)))
        with_both = render_watermark(self.source, _opts(logo_path=str(logo), logo_mark="nikon"))
        self.assertIsNone(ImageChops.difference(with_file, with_both).getbbox())

    def test_logo_scale_and_opacity(self) -> None:
        small = render_watermark(self.source, _opts(style="卡片相框", logo_mark="nikon", logo_scale=0.6))
        large = render_watermark(self.source, _opts(style="卡片相框", logo_mark="nikon", logo_scale=1.8))
        self.assertGreater(large.size[1], small.size[1] - 1)
        _img, small_hits = render_watermark_with_hits(
            self.source, _opts(style="胶片边框", logo_mark="nikon", logo_scale=0.6)
        )
        _img, large_hits = render_watermark_with_hits(
            self.source, _opts(style="胶片边框", logo_mark="nikon", logo_scale=1.8)
        )
        small_logo = next(hit for hit in small_hits if hit["key"] == "logo")
        large_logo = next(hit for hit in large_hits if hit["key"] == "logo")
        self.assertGreater(large_logo["w"], small_logo["w"])
        solid = render_watermark(self.source, _opts(logo_mark="nikon", logo_opacity=1.0))
        faded = render_watermark(self.source, _opts(logo_mark="nikon", logo_opacity=0.3))
        self.assertIsNotNone(ImageChops.difference(solid, faded).getbbox())

    def test_divider_changes_output_only_when_enabled(self) -> None:
        for style in ("经典底栏", "极简叠加", "胶片边框"):
            off = render_watermark(self.source, _opts(style=style, logo_mark="nikon"))
            on = render_watermark(self.source, _opts(style=style, logo_mark="nikon", show_divider=True))
            self.assertEqual(off.size, on.size)
            self.assertIsNotNone(ImageChops.difference(off, on).getbbox(), style)

    def test_asymmetric_left_right_pads(self) -> None:
        default = render_watermark(self.source, _opts(style="卡片相框"))
        wide_left = render_watermark(
            self.source, _opts_with_layout({"pad_left": 2.0, "pad_right": 1.0}, style="卡片相框")
        )
        self.assertGreater(wide_left.size[0], default.size[0])
        _img, default_hits = render_watermark_with_hits(
            self.source, _opts(style="经典底栏", caption="城市")
        )
        _img, right_hits = render_watermark_with_hits(
            self.source, _opts_with_layout({"pad_right": 2.0}, style="经典底栏", caption="城市")
        )
        default_caption = next(hit for hit in default_hits if hit["key"] == "caption")
        moved_caption = next(hit for hit in right_hits if hit["key"] == "caption")
        self.assertLess(
            moved_caption["x"] + moved_caption["w"], default_caption["x"] + default_caption["w"]
        )

    def test_card_corner_radius(self) -> None:
        default = render_watermark(self.source, _opts(style="卡片相框"))
        square = render_watermark(self.source, _opts_with_layout({"corner_radius": 1}, style="卡片相框"))
        round_ = render_watermark(self.source, _opts_with_layout({"corner_radius": 40}, style="卡片相框"))
        self.assertEqual(default.size, round_.size)
        pad = (default.size[0] - 600) // 2
        corner = (pad + 1, pad + 1)
        self.assertEqual(square.getpixel(corner), (80, 110, 140))
        self.assertNotEqual(round_.getpixel(corner), (80, 110, 140))

    def test_defaults_keep_previous_output(self) -> None:
        for style in ("经典底栏", "极简叠加", "卡片相框", "纯文字中下"):
            legacy = {**BASE, "style": style}
            explicit = {
                **legacy,
                "logo_mark": "",
                "logo_scale": 1.0,
                "logo_opacity": 1.0,
                "show_divider": False,
                "layout": {"pad_left": 1.0, "pad_right": 1.0, "corner_radius": 0},
            }
            a = render_watermark(self.source, WatermarkDocument(legacy).render_options())
            b = render_watermark(self.source, WatermarkDocument(explicit).render_options())
            self.assertEqual(a.size, b.size, style)
            self.assertIsNone(ImageChops.difference(a, b).getbbox(), style)
        card = render_watermark(self.source, _opts(style="卡片相框"))
        self.assertEqual(card.size[0], 600 + 2 * max(22, int(400 * 0.052)))

    def test_bg_color_and_auto_contrast(self) -> None:
        warm = render_watermark(self.source, _opts(style="卡片相框", bg_color="#E9E5DC"))
        self.assertEqual(warm.getpixel((2, 2)), (0xE9, 0xE5, 0xDC))
        dark = render_watermark(self.source, _opts(style="卡片相框", bg_color="#22252B"))
        self.assertEqual(dark.getpixel((2, 2)), (0x22, 0x25, 0x2B))
        self.assertEqual(_color_theme("白色", "#E9E5DC")["text"], (23, 27, 34))
        self.assertEqual(_color_theme("白色", "#22252B")["text"], (246, 248, 252))

    def test_shadow_strength_zero_default_and_strong(self) -> None:
        default = render_watermark(self.source, _opts(style="卡片相框"))
        explicit_25 = render_watermark(
            self.source, _opts_with_layout({"shadow_strength": 25}, style="卡片相框")
        )
        self.assertIsNone(ImageChops.difference(default, explicit_25).getbbox())
        no_shadow = render_watermark(
            self.source, _opts_with_layout({"shadow_strength": 0}, style="卡片相框")
        )
        strong = render_watermark(
            self.source, _opts_with_layout({"shadow_strength": 80}, style="卡片相框")
        )
        self.assertIsNotNone(ImageChops.difference(no_shadow, default).getbbox())
        self.assertIsNotNone(ImageChops.difference(default, strong).getbbox())

    def test_exposure_compose_and_parse_roundtrip(self) -> None:
        line = compose_exposure_line(focal="24mm", aperture="f/2.8", shutter="1/250s", iso="100")
        self.assertEqual(line, "ISO 100  |  24MM  |  F/2.8  |  1/250S")
        parsed = parse_exposure_line(line)
        self.assertEqual(parsed, {"focal": "24MM", "aperture": "F/2.8", "shutter": "1/250S", "iso": "100"})
        parsed2 = parse_exposure_line("ISO 400 | 50mm | f/1.4 | 1/1000s")
        self.assertEqual(parsed2["iso"], "400")
        self.assertEqual(parsed2["focal"], "50mm")
        self.assertEqual(parsed2["aperture"], "f/1.4")
        self.assertEqual(parsed2["shutter"], "1/1000s")


class StudioConfigTests(unittest.TestCase):
    def test_new_defaults(self) -> None:
        data = settings_store.coerce_settings({})
        self.assertEqual(data["logo_mark"], "")
        self.assertEqual(data["logo_scale"], 1.0)
        self.assertEqual(data["logo_opacity"], 1.0)
        self.assertFalse(data["show_divider"])
        self.assertEqual(data["layout"]["pad_left"], 1.0)
        self.assertEqual(data["layout"]["pad_right"], 1.0)
        self.assertIn("胶片边框", settings_store.BUILTIN_STYLES)

    def test_clamping(self) -> None:
        data = settings_store.coerce_settings(
            {"logo_mark": "X", "logo_scale": 9, "logo_opacity": 0, "layout": {"pad_left": 9, "pad_right": 0}}
        )
        self.assertEqual(data["logo_mark"], "")
        self.assertEqual(data["logo_scale"], 1.9)
        self.assertEqual(data["logo_opacity"], 0.2)
        self.assertEqual(data["layout"]["pad_left"], 2.2)
        self.assertEqual(data["layout"]["pad_right"], 0.4)
        bad = settings_store.coerce_settings({"logo_scale": "abc"})
        self.assertEqual(bad["logo_scale"], 1.0)

    def test_side_pad_migrates_to_left_right(self) -> None:
        data = settings_store.coerce_settings({"layout": {"side_pad": 1.6}})
        self.assertEqual(data["layout"]["pad_left"], 1.6)
        self.assertEqual(data["layout"]["pad_right"], 1.6)
        options = WatermarkDocument({"layout": {"side_pad": 1.6}}).render_options()
        self.assertEqual(options["pad_left"], 1.6)

    def test_reset_restores_new_fields(self) -> None:
        state = settings_store.coerce_settings(
            {"logo_mark": "L", "logo_scale": 1.5, "show_divider": True, "layout": {"pad_left": 2.0}}
        )
        reset = settings_store.reset_watermark_settings(state)
        self.assertEqual(reset["logo_mark"], "")
        self.assertEqual(reset["logo_scale"], 1.0)
        self.assertFalse(reset["show_divider"])
        self.assertEqual(reset["layout"]["pad_left"], 1.0)

    def test_recent_templates_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "templates.json"
            template_store.save_template("A", {"style": "卡片相框"}, path=path)
            template_store.save_template("B", {"style": "极简叠加"}, path=path)
            entries = template_store.load_templates(path)
            entries[0]["updated_at"] = "2030-01-01T00:00:00+00:00"
            template_store.save_templates(entries, path)
            recent = template_store.recent_templates(2, path)
            self.assertEqual([entry["name"] for entry in recent], ["A", "B"])


class StudioUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from photo_watermark_studio.app_window import MainWindow

        self.root = Path(tempfile.mkdtemp(prefix="tingxia-studio-"))
        self.window = MainWindow(settings_path=self.root / "settings.json")
        self.window.suppress_dialogs = True
        self.window.show()
        self.app.processEvents()
        self.settings = self.window.settings

    def tearDown(self) -> None:
        self.window.close()

    def test_tab_pages_contain_expected_controls(self) -> None:
        self.settings.show_tab("Logo")
        self.assertTrue(self.settings.logo_presets.isVisibleTo(self.window))
        self.assertTrue(self.settings.show_divider.isVisibleTo(self.window))
        self.assertFalse(self.settings.brand_edit.isVisibleTo(self.window))
        self.settings.show_tab("参数")
        self.assertTrue(self.settings.brand_edit.isVisibleTo(self.window))
        self.assertTrue(self.settings.show_camera.isVisibleTo(self.window))
        self.settings.show_tab("主题")
        self.assertTrue(self.settings.theme_segment.isVisibleTo(self.window))
        self.assertTrue(self.settings.pad_left_slider.isVisibleTo(self.window))
        self.settings.show_tab("自定义")
        self.assertTrue(self.settings.style_combo.isVisibleTo(self.window))
        self.assertTrue(self.settings.user_template_combo.isVisibleTo(self.window))
        self.settings.show_tab("导出")
        self.assertTrue(self.settings.format_combo.isVisibleTo(self.window))
        self.assertTrue(self.settings.footer_export_button.isVisibleTo(self.window))

    def test_logo_preset_and_layout_linkage(self) -> None:
        self.settings.logo_presets.button("nikon").click()
        state = self.settings.state()
        self.assertEqual(state["logo_mark"], "nikon")
        self.assertEqual(self.window.controller.document.get("logo_mark"), "nikon")
        self.settings.logo_layout_segment.setCurrentIndex(0)
        state = self.settings.state()
        self.assertTrue(state["show_logo"])
        self.assertTrue(state["show_brand_text"])
        self.settings.logo_layout_segment.setCurrentIndex(1)
        self.assertFalse(self.settings.state()["show_brand_text"])
        self.settings.logo_layout_segment.setCurrentIndex(2)
        self.assertFalse(self.settings.state()["show_logo"])
        restored = dict(self.settings.state())
        restored.update({"show_logo": True, "show_brand_text": True})
        self.settings.set_state(restored)
        self.assertEqual(self.settings.logo_layout_segment.currentIndex(), 0)

    def test_theme_segment_drives_theme_combo(self) -> None:
        self.settings.theme_segment.setCurrentIndex(1)
        self.assertEqual(self.settings.state()["theme"], "黑色")
        self.settings.theme_combo.setCurrentText("高斯模糊")
        self.assertEqual(self.settings.theme_segment.currentIndex(), 2)

    def test_lock_pads_syncs_all_edges(self) -> None:
        self.settings.lock_pads.setChecked(True)
        self.settings.pad_top_slider.setValue(150)
        layout = self.settings.state()["layout"]
        self.assertEqual(layout["pad_left"], 1.5)
        self.assertEqual(layout["pad_right"], 1.5)
        self.assertEqual(layout["pad_bottom"], 1.5)

    def test_film_card_in_sidebar(self) -> None:
        card = self.window.sidebar.template_buttons["胶片边框"]
        card.click()
        self.app.processEvents()
        self.assertEqual(self.settings.state()["style"], "胶片边框")
        self.assertTrue(card.isChecked())

    def test_recent_template_applies(self) -> None:
        path = self.settings.templates_path()
        self.assertEqual(path.parent, self.root)
        saved = template_store.save_template(
            "旅行白边", {**self.settings.state(), "style": "卡片相框", "theme": "黑色"}, path=path
        )
        self.window._refresh_recent_templates()
        self.assertEqual(len(self.window.sidebar.recent_buttons), 1)
        self.window.sidebar.recent_buttons[0].click()
        self.app.processEvents()
        state = self.settings.state()
        self.assertEqual(state["style"], "卡片相框")
        self.assertEqual(state["theme"], "黑色")
        self.assertEqual(self.settings._selected_template_id(), saved["id"])

    def test_sidebar_nav_active_state(self) -> None:
        sidebar = self.window.sidebar
        sidebar.batch_button.click()
        self.assertEqual(sidebar.active_nav(), "batch")
        self.assertEqual(self.settings.current_tab(), "导出")
        self.assertTrue(self.window.nav_batch.isChecked())
        sidebar.all_templates_button.click()
        self.assertEqual(self.settings.current_tab(), "自定义")
        sidebar.photo_button.click()
        self.assertEqual(sidebar.active_nav(), "photos")

    def test_save_state_label_follows_debounce(self) -> None:
        self.settings.brand_edit.setText("新署名")
        self.assertIn("正在保存", self.window.saved_label.text())
        self.window.controller.save_settings()
        self.assertIn("已保存", self.window.saved_label.text())

    def test_bg_swatch_and_shadow_slider_state(self) -> None:
        self.settings.style_combo.setCurrentText("卡片相框")
        self.settings.show_tab("主题")
        self.assertTrue(self.settings.bg_swatches.isVisibleTo(self.window))
        self.assertTrue(self.settings.shadow_strength_slider.isVisibleTo(self.window))
        swatch = self.settings.bg_swatches.button("#E9E5DC")
        self.assertIsNotNone(swatch)
        swatch.click()
        self.assertEqual(self.settings.state()["bg_color"], "#E9E5DC")
        self.settings.shadow_strength_slider.setValue(80)
        self.assertEqual(self.settings.state()["layout"]["shadow_strength"], 80)
        self.settings.theme_segment.setCurrentIndex(1)
        self.assertEqual(self.settings.state()["bg_color"], "")
        self.assertEqual(self.settings.state()["theme"], "黑色")

    def test_params_exif_editor_two_way_sync(self) -> None:
        photo = self.root / "sample.jpg"
        Image.new("RGB", (600, 400), (90, 120, 150)).save(photo)
        self.window.controller.add_paths([str(photo)])
        self.app.processEvents()
        self.assertTrue(self.settings.camera_edit.isEnabled())
        self.settings.camera_edit.setText("SONY A7R V")
        self.settings.camera_edit.textEdited.emit("SONY A7R V")
        self.settings.focal_edit.setText("24mm")
        self.settings.aperture_edit.setText("f/2.8")
        self.settings.shutter_edit.setText("1/250s")
        self.settings.iso_edit.setText("100")
        self.settings.iso_edit.textEdited.emit("100")
        opts = self.window.controller.render_options(str(photo))
        self.assertEqual(opts["camera_text"], "SONY A7R V")
        self.assertEqual(opts["exif_text"], "ISO 100  |  24MM  |  F/2.8  |  1/250S")
        # 画布侧弹窗修改后，右侧面板四个曝光格同步更新
        self.window._on_field_changed("exif", "ISO 800  |  85MM  |  F/1.4  |  1/500S", None)
        self.assertEqual(self.settings.focal_edit.text(), "85MM")
        self.assertEqual(self.settings.aperture_edit.text(), "F/1.4")
        self.assertEqual(self.settings.shutter_edit.text(), "1/500S")
        self.assertEqual(self.settings.iso_edit.text(), "800")
        # 点击「恢复 EXIF」清空单张覆盖
        self.settings.reset_photo_exif_button.click()
        self.assertEqual(self.settings.camera_edit.text(), "")
        self.assertEqual(self.settings.focal_edit.text(), "")
        self.window.controller.shutdown()

    def test_field_editor_popup_does_not_shrink_canvas(self) -> None:
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QWidget

        image = QImage(800, 500, QImage.Format.Format_RGB32)
        image.fill(0xFF6688AA)
        self.window.resize(1280, 800)
        self.app.processEvents()
        self.window.preview.set_preview_image(image, [])
        self.app.processEvents()
        view = self.window.preview.view
        before = view.height()
        self.assertGreater(before, 200)
        self.assertTrue(self.window.preview.tools_bar.isVisible())
        self.assertEqual(self.window.preview.layout().indexOf(self.window.preview.tools_bar), -1)
        bar = self.window.preview.tools_bar.geometry()
        host = view.geometry()
        self.assertGreater(bar.width(), 80)
        self.assertGreaterEqual(bar.height(), 32)
        self.assertLessEqual(bar.height(), 40)
        self.assertEqual(view.viewportMargins().bottom(), 0)
        self.assertGreater(bar.top(), host.top())
        self.assertLessEqual(bar.bottom(), host.bottom())
        self.assertGreater(bar.bottom(), host.bottom() - 40)
        status = self.window.findChild(QWidget, "StatusBar")
        self.assertIsNotNone(status)
        self.assertEqual(status.height(), 22)
        received: list[tuple] = []
        self.window.preview.fieldChanged.connect(lambda *args: received.append(args))
        self.window.preview.open_field_editor(
            {"key": "lens", "label": "镜头", "text": "24-120", "has_scale": True, "scale": 1.0}
        )
        self.app.processEvents()
        self.assertTrue(self.window.preview.editor.isVisible())
        self.assertEqual(view.height(), before)
        self.assertEqual(self.window.preview.layout().indexOf(self.window.preview.editor), -1)
        self.window.preview.editor_text.setText("50mm")
        self.window.preview.editor_text.textEdited.emit("50mm")
        self.assertEqual(received[-1][0], "lens")
        self.assertEqual(received[-1][1], "50mm")
        self.window.preview.editor_text.setFocus()
        self.app.processEvents()
        self.window.preview.hide_field_editor()
        self.assertFalse(self.window.preview.editor.isVisible())
        self.assertLessEqual(self.window.photo_list.maximumHeight(), 72)
        self.assertFalse(self.window.photo_list.title_label.isVisible())
        self.assertFalse(hasattr(self.window, "current_template_label"))

    def test_canvas_scene_keeps_footer_background_identical_to_border(self) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QImage, QPainter

        source = self.root / "plain.png"
        Image.new("RGB", (600, 400), (80, 110, 140)).save(source)
        for style in ("卡片相框", "胶片边框"):
            for bg_color, expected in (("", (255, 255, 255)), ("#E9E5DC", (0xE9, 0xE5, 0xDC))):
                opts = _opts_with_layout(
                    {"shadow_strength": 0},
                    style=style,
                    theme="白色",
                    bg_color=bg_color,
                )
                pil_img, hits = render_watermark_with_hits(source, opts)
                bar_hit = next(hit for hit in hits if hit["key"] == "watermark_bar")
                points = {
                    "top": (2, 2),
                    "left": (2, pil_img.height // 2),
                    "bottom": (2, pil_img.height - 3),
                    "footer": (12, int(bar_hit["y"]) + int(bar_hit["h"] // 2)),
                }
                for name, pt in points.items():
                    self.assertEqual(pil_img.getpixel(pt), expected, f"{style} {bg_color} {name}")

                qimg = QImage(
                    pil_img.tobytes("raw", "RGB"),
                    pil_img.width,
                    pil_img.height,
                    pil_img.width * 3,
                    QImage.Format.Format_RGB888,
                ).copy()
                self.window.preview.set_preview_image(qimg, hits)
                self.assertTrue(self.window.preview._bar_item.isVisible())
                rendered = QImage(pil_img.width, pil_img.height, QImage.Format.Format_RGB32)
                rendered.fill(QColor(1, 2, 3))
                painter = QPainter(rendered)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                rect = QRectF(0, 0, pil_img.width, pil_img.height)
                self.window.preview.scene.render(painter, rect, rect)
                painter.end()
                for name, pt in points.items():
                    rgb = rendered.pixelColor(*pt).getRgb()[:3]
                    self.assertEqual(rgb, expected, f"{style} {bg_color} scene {name}")


if __name__ == "__main__":
    unittest.main()
