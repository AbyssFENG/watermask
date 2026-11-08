# -*- coding: utf-8 -*-
"""离屏跑通导入、预览、单张导出和批量导出。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
_existing = sys.modules.get("photo_watermark_studio")
if _existing is not None and not hasattr(_existing, "__path__"):
    del sys.modules["photo_watermark_studio"]

import photo_watermark_studio  # noqa: F401  先加载系统 ICU，再导入 Qt
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from photo_watermark_studio.app_window import MainWindow


def _wait_until(predicate, timeout_ms: int = 20000) -> bool:
    if predicate():
        return True
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(30)

    def poll() -> None:
        if predicate():
            loop.quit()

    timer.timeout.connect(poll)
    QTimer.singleShot(timeout_ms, loop.quit)
    timer.start()
    loop.exec()
    timer.stop()
    return bool(predicate())


class WindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_import_preview_and_export(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="pws-window-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        output_dir = root / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        photo = root / "photo.jpg"
        other = root / "other.png"
        damaged = root / "bad.jpg"
        Image.new("RGB", (240, 160), (40, 80, 120)).save(photo, quality=90)
        Image.new("RGB", (180, 120), (200, 160, 80)).save(other)
        damaged.write_bytes(b"not-an-image")
        original = photo.read_bytes()

        window = MainWindow(settings_path=root / "settings.json")
        window.suppress_dialogs = True
        window.show()
        self._app.processEvents()

        previews: list[object] = []
        window.controller.previewImage.connect(previews.append)
        window.controller.add_paths([str(photo), str(root / "note.txt")])
        self.assertEqual(window.photo_list.list_widget.count(), 1)
        self.assertIn("跳过", window.status_label.text())
        self.assertTrue(_wait_until(lambda: len(previews) >= 1))
        self.assertFalse(previews[-1].isNull())

        before = len(previews)
        window.settings.style_combo.setCurrentText("极简叠加")
        self.assertTrue(_wait_until(lambda: len(previews) > before))
        self.assertEqual(window.controller.options["style"], "极简叠加")

        state = window.settings.state()
        state["output_dir"] = str(output_dir)
        window.settings.set_state(state)
        window.controller.apply_settings(window.settings.state())
        window.controller.save_current()
        self.assertTrue(
            _wait_until(lambda: not window.controller._exporting, 30000),
            "单张导出超时",
        )
        saved = output_dir / "photo_watermark.jpg"
        self.assertTrue(saved.is_file())
        self.assertEqual(photo.read_bytes(), original)
        self.assertEqual(window.last_notice[0], "info")
        self.assertEqual(window.last_notice[1], "导出成功")
        with Image.open(saved) as image:
            self.assertEqual(image.size[0], 240)

        window.controller.add_paths([str(other), str(damaged)])
        window.controller.export_all()
        self.assertTrue(window.controller._exporting or (output_dir / "other_watermark.jpg").exists())
        self.assertTrue(_wait_until(lambda: not window.controller._exporting, 30000))
        self.assertTrue((output_dir / "other_watermark.jpg").is_file())
        self.assertEqual(photo.read_bytes(), original)
        self.assertEqual(window.last_notice[1], "批量导出完成（部分失败）")
        self.assertIn("bad.jpg", window.last_notice[2])
        self.assertFalse(window.controller._exporting)

        window.close()


if __name__ == "__main__":
    unittest.main()
