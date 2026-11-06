# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from photo_watermark_studio.core import template_store


class TemplateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "templates.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_list_rename_delete(self) -> None:
        saved = template_store.save_template(
            "晨光",
            {"style": "纯文字中下", "theme": "深色", "brand": "Studio"},
            path=self.path,
        )
        self.assertEqual(saved["name"], "晨光")
        self.assertEqual(saved["settings"]["style"], "纯文字中下")
        self.assertEqual(saved["settings"]["brand"], "Studio")

        listed = template_store.list_templates(self.path)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], saved["id"])

        renamed = template_store.rename_template(saved["id"], "夜色", self.path)
        self.assertEqual(renamed["name"], "夜色")
        self.assertEqual(template_store.get_template(saved["id"], self.path)["name"], "夜色")

        self.assertTrue(template_store.delete_template(saved["id"], self.path))
        self.assertEqual(template_store.list_templates(self.path), [])

    def test_save_overwrites_same_name(self) -> None:
        first = template_store.save_template(
            "同一名",
            {"style": "经典底栏", "brand": "A"},
            path=self.path,
        )
        second = template_store.save_template(
            "同一名",
            {"style": "自定义", "base_style": "卡片相框", "brand": "B"},
            path=self.path,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(template_store.list_templates(self.path)), 1)
        self.assertEqual(second["settings"]["brand"], "B")
        self.assertEqual(second["settings"]["base_style"], "卡片相框")


if __name__ == "__main__":
    unittest.main()
