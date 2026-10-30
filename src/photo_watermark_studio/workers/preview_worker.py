# -*- coding: utf-8 -*-
"""后台预览。只把缩小后的图像交回主线程。"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.renderer import render_watermark_with_hits


def pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes()
    qimage = QImage(
        data,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    return qimage.copy()


class PreviewSignals(QObject):
    finished = Signal(int, QImage, object, str, str)


class PreviewRunnable(QRunnable):
    def __init__(
        self,
        request_id: int,
        path: str,
        options: dict,
        width: int,
        height: int,
        signals: PreviewSignals,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.path = path
        self.options = dict(options)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.signals = signals

    def run(self) -> None:
        try:
            rendered, hits = render_watermark_with_hits(self.path, self.options)
            ratio = min(self.width / rendered.width, self.height / rendered.height)
            size = (
                max(1, int(rendered.width * ratio)),
                max(1, int(rendered.height * ratio)),
            )
            view = rendered.resize(size, Image.Resampling.LANCZOS)
            image = pil_to_qimage(view)
            sx = size[0] / rendered.width
            sy = size[1] / rendered.height
            scaled_hits = []
            for hit in hits:
                scaled_hits.append(
                    {
                        **hit,
                        "x": float(hit["x"]) * sx,
                        "y": float(hit["y"]) * sy,
                        "w": float(hit["w"]) * sx,
                        "h": float(hit["h"]) * sy,
                    }
                )
            metadata = read_photo_metadata(self.path)
            if not any((
                metadata.camera,
                metadata.lens,
                metadata.focal,
                metadata.aperture,
                metadata.shutter,
                metadata.iso,
                metadata.date,
            )):
                status = "预览已更新。当前图片没有可读取的 EXIF 参数，可通过自定义说明补充。"
            else:
                status = f"预览已更新。已读取相机信息：{metadata.camera or metadata.make or '部分参数'}"
            self.signals.finished.emit(self.request_id, image, scaled_hits, "", status)
        except Exception as exc:
            self.signals.finished.emit(self.request_id, QImage(), [], str(exc), "")
