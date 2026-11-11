# -*- coding: utf-8 -*-
"""后台生成缩略图。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage
from PIL import Image

# 与 Pillow ImageOps.exif_transpose 相同的方向表。先读标签再旋转，避免为了方向解码全图。
_ORIENTATION_TRANSFORMS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _orientation_value(src: Image.Image) -> int:
    try:
        value = int(src.getexif().get(274, 1) or 1)
    except Exception:
        return 1
    if value in _ORIENTATION_TRANSFORMS or value == 1:
        return value
    return 1


def _apply_orientation(image: Image.Image, orientation: int) -> Image.Image:
    transform = _ORIENTATION_TRANSFORMS.get(int(orientation))
    if transform is None:
        return image
    return image.transpose(transform)


def load_thumbnail(path: str, max_size: int) -> tuple[Image.Image, int, int]:
    """解码缩略图，并返回方向校正后的原图像素尺寸。

    JPEG 在解码前用 draft 降采样。返回的宽高仍是校正后的全图尺寸，不是缩略图尺寸。
    """
    limit = max(48, int(max_size))
    with Image.open(path) as src:
        full_w, full_h = src.size
        if src.format == "JPEG":
            # 必须在解码前调用，否则 draft 不会降采样。
            src.draft("RGB", (limit * 2, limit * 2))
        orientation = _orientation_value(src)
        image = src.convert("RGB")
    image = _apply_orientation(image, orientation)
    if orientation in (5, 6, 7, 8):
        full_w, full_h = full_h, full_w
    image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    return image, full_w, full_h


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
            image, width, height = load_thumbnail(self.path, self.max_size)
            data = image.tobytes("raw", "RGB")
            qimage = QImage(
                data,
                image.width,
                image.height,
                image.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
            self.signals.finished.emit(self.path, qimage, width, height, "")
        except Exception as exc:
            self.signals.finished.emit(self.path, QImage(), 0, 0, str(exc))
