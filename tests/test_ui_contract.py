# -*- coding: utf-8 -*-
"""停下时光工作台的公开 UI 契约。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from PySide6.QtWidgets import QApplication

from photo_watermark_studio.app_window import APP_NAME, MainWindow


class UiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="tingxia-ui-"))
        self.window = MainWindow(settings_path=root / "settings.json")
        self.window.suppress_dialogs = True
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()

    def test_studio_shell_contract(self) -> None:
        self.assertEqual(APP_NAME, "停下时光 · Studio")
        self.assertEqual(self.window.photo_list.objectName(), "ImageRail")
        self.assertEqual(self.window.preview.objectName(), "CanvasShell")
        self.assertEqual(self.window.sidebar.objectName(), "StudioSidebar")
        self.assertIsNotNone(self.window.photo_list.list_widget)
        self.assertIsNotNone(self.window.settings.style_combo)

    def test_inspector_tabs_and_template_sidebar(self) -> None:
        tabs = self.window.settings.tabs
        self.assertEqual(
            [tabs.tabText(i) for i in range(tabs.count())],
            ["Logo", "参数", "主题", "自定义", "导出"],
        )
        self.window.sidebar.styleRequested.emit("极简叠加")
        self.app.processEvents()
        self.assertEqual(self.window.settings.state()["style"], "极简叠加")
        self.assertTrue(self.window.sidebar.template_buttons["极简叠加"].isChecked())
        self.window.settings.show_tab("导出")
        self.assertEqual(tabs.tabText(tabs.currentIndex()), "导出")


if __name__ == "__main__":
    unittest.main()

