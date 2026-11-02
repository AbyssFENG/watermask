# -*- coding: utf-8 -*-
"""后台生成缩略图。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage
from PIL import Image, ImageOps


class ThumbnailSignals(QObject):
    finished = Signal(str, QImage, int, int, str)


class ThumbnailRunnable(QRunnable):
    def __init__(self, path: str, max_size: int, signals: ThumbnailSignals) -> None:
        super().__init__()
        self.path = path
        self.max_size = max(48, int(max_size))
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            with Image.open(self.path) as src:
                image = ImageOps.exif_transpose(src).convert("RGB")
                width, height = image.size
                image.thumbnail((self.max_size, self.max_size), Image.Resampling.LANCZOS)
                data = image.tobytes("raw", "RGB")
                qimage = QImage(data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888).copy()
            self.signals.finished.emit(self.path, qimage, width, height, "")
        except Exception as exc:
            self.signals.finished.emit(self.path, QImage(), 0, 0, str(exc))
