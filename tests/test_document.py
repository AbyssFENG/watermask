# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from PIL import Image

from photo_watermark_studio.core.coordinate_mapper import CoordinateMapper, ImageSize, ViewRect
from photo_watermark_studio.core.document import WatermarkDocument
from photo_watermark_studio.core.history import EditHistory
from photo_watermark_studio.core.renderer import render_from_document, render_watermark
from photo_watermark_studio.core.settings_store import (
    coerce_field_positions,
    coerce_layout,
    coerce_settings,
    snap_field_position,
)


class DocumentTests(unittest.TestCase):
    def test_roundtrip_legacy_settings(self) -> None:
        raw = {"style": "极简叠加", "theme": "高斯模糊", "brand": "Studio"}
        doc = WatermarkDocument(raw)
        options = doc.render_options()
        self.assertEqual(options["style"], "极简叠加")
        self.assertEqual(options["theme"], "高斯模糊")
        self.assertEqual(options["brand"], "Studio")
        self.assertIn("offset_x", options)
        self.assertEqual(options["anchor"], "bottom_center")
        self.assertAlmostEqual(options["bar_height"], 1.0)
        self.assertAlmostEqual(options["side_pad"], 1.0)

    def test_bar_metrics_are_clamped(self) -> None:
        layout = coerce_layout(
            {
                "bar_height": 9,
                "side_pad": 0,
                "pad_top": "bad",
                "pad_bottom": 1.5,
            }
        )
        self.assertAlmostEqual(layout["bar_height"], 2.0)
        self.assertAlmostEqual(layout["side_pad"], 0.4)
        self.assertAlmostEqual(layout["pad_top"], 1.0)
        self.assertAlmostEqual(layout["pad_bottom"], 1.5)
        options = WatermarkDocument({"layout": layout}).render_options()
        self.assertAlmostEqual(options["bar_height"], 2.0)
        self.assertAlmostEqual(options["pad_bottom"], 1.5)

    def test_layout_patch(self) -> None:
        doc = WatermarkDocument()
        doc.set_layout(offset_x=0.1, offset_y=-0.05, anchor="top_center")
        # 非自定义：文档可记录布局，渲染强制默认偏移。
        self.assertEqual(doc.layout["anchor"], "top_center")
        self.assertAlmostEqual(doc.layout["offset_x"], 0.1)
        self.assertEqual(doc.render_options()["anchor"], "bottom_center")
        self.assertAlmostEqual(doc.render_options()["offset_x"], 0.0)

    def test_custom_style_exports_field_positions(self) -> None:
        doc = WatermarkDocument({"style": "自定义", "base_style": "极简叠加"})
        doc.set_layout(field_positions={"brand": {"x": 0.3, "y": 0.7}})
        options = doc.render_options()
        self.assertEqual(options["style"], "自定义")
        self.assertEqual(options["base_style"], "极简叠加")
        self.assertAlmostEqual(options["offset_x"], 0.0)
        self.assertAlmostEqual(options["offset_y"], 0.0)
        self.assertAlmostEqual(options["field_positions"]["brand"]["x"], 0.3)
        self.assertAlmostEqual(options["field_positions"]["brand"]["y"], 0.7)

    def test_coerce_keeps_conflict_policy(self) -> None:
        data = coerce_settings({"conflict_policy": "overwrite"})
        self.assertEqual(data["conflict_policy"], "overwrite")

    def test_coerce_field_positions_clamps_and_filters(self) -> None:
        raw = {
            "brand": {"x": 1.5, "y": -0.2},
            "camera": {"x": 0.4, "y": 0.6},
            "nope": {"x": 0.5, "y": 0.5},
            "lens": "bad",
        }
        out = coerce_field_positions(raw)
        self.assertNotIn("nope", out)
        self.assertNotIn("lens", out)
        self.assertAlmostEqual(out["brand"]["x"], 0.98)
        self.assertAlmostEqual(out["brand"]["y"], 0.02)
        self.assertAlmostEqual(out["camera"]["x"], 0.4)
        layout = coerce_layout({"field_positions": raw})
        self.assertIn("brand", layout["field_positions"])
        sx, sy = snap_field_position(0.53, 0.77)
        self.assertAlmostEqual(sx, 0.53)
        self.assertAlmostEqual(sy, 0.77)


class MapperTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        mapper = CoordinateMapper(ImageSize(1000, 500), ViewRect(10, 20, 500, 250))
        sx, sy = mapper.image_to_scene(200, 100)
        ix, iy = mapper.scene_to_image(sx, sy)
        self.assertAlmostEqual(ix, 200, places=4)
        self.assertAlmostEqual(iy, 100, places=4)


class HistoryTests(unittest.TestCase):
    def test_undo_redo(self) -> None:
        history = EditHistory()
        history.reset({"a": 1})
        history.push({"a": 2})
        history.push({"a": 3})
        self.assertEqual(history.undo(), {"a": 2})
        self.assertEqual(history.undo(), {"a": 1})
        self.assertEqual(history.redo(), {"a": 2})


class RenderDocumentTests(unittest.TestCase):
    def test_render_matches_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.jpg"
            Image.new("RGB", (320, 200), (40, 80, 120)).save(path, quality=90)
            doc = WatermarkDocument({"style": "经典底栏", "theme": "浅色", "brand": "A"})
            img1 = render_from_document(path, doc)
            img2 = render_watermark(path, doc.render_options())
            self.assertEqual(img1.size, img2.size)


if __name__ == "__main__":
    unittest.main()
