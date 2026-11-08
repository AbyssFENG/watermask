# -*- coding: utf-8 -*-
from __future__ import annotations

import os
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

import photo_watermark_studio  # noqa: F401
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from photo_watermark_studio.workers.export_worker import CancelToken, ExportRunnable, ExportSignals


OPTIONS = {
    "style": "经典底栏",
    "base_style": "经典底栏",
    "theme": "浅色",
    "brand": "",
    "caption": "",
    "scale": 1.0,
    "logo_path": "",
    "show_logo": True,
    "show_camera": True,
    "show_lens": True,
    "show_exif": True,
    "show_date": False,
    "show_gps": False,
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
    "conflict_policy": "number",
}


class ExportWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_single_path_emits_saved_paths(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="pws-export-worker-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        out = root / "out"
        out.mkdir()
        photo = root / "one.jpg"
        Image.new("RGB", (64, 48), (30, 60, 90)).save(photo, quality=90)

        signals = ExportSignals()
        result: dict[str, object] = {}

        def on_finished(
            succeeded: int,
            total: int,
            errors: object,
            cancelled: int,
            saved_paths: object,
        ) -> None:
            result["succeeded"] = succeeded
            result["total"] = total
            result["errors"] = errors
            result["cancelled"] = cancelled
            result["saved_paths"] = saved_paths
            loop.quit()

        signals.finished.connect(on_finished)
        token = CancelToken()
        runnable = ExportRunnable(
            [str(photo)],
            str(out),
            OPTIONS,
            90,
            token,
            signals,
            {},
        )
        loop = QEventLoop()
        QTimer.singleShot(20000, loop.quit)
        from PySide6.QtCore import QThreadPool

        pool = QThreadPool.globalInstance()
        pool.start(runnable)
        loop.exec()
        QCoreApplication.processEvents()

        self.assertEqual(result.get("succeeded"), 1)
        self.assertEqual(result.get("total"), 1)
        self.assertEqual(result.get("cancelled"), 0)
        self.assertEqual(result.get("errors"), [])
        saved_paths = result.get("saved_paths")
        self.assertIsInstance(saved_paths, list)
        assert isinstance(saved_paths, list)
        self.assertEqual(len(saved_paths), 1)
        self.assertTrue(Path(str(saved_paths[0])).is_file())


if __name__ == "__main__":
    unittest.main()
