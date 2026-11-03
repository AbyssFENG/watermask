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
from photo_watermark_studio.core.settings_store import coerce_settings


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

    def test_layout_patch(self) -> None:
        doc = WatermarkDocument()
        doc.set_layout(offset_x=0.1, offset_y=-0.05, anchor="top_center")
        # 文档仍可记录布局；渲染侧暂时强制默认位置（功能已关闭）。
        self.assertEqual(doc.layout["anchor"], "top_center")
        self.assertAlmostEqual(doc.layout["offset_x"], 0.1)
        self.assertEqual(doc.render_options()["anchor"], "bottom_center")
        self.assertAlmostEqual(doc.render_options()["offset_x"], 0.0)

    def test_coerce_keeps_conflict_policy(self) -> None:
        data = coerce_settings({"conflict_policy": "overwrite"})
        self.assertEqual(data["conflict_policy"], "overwrite")


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
