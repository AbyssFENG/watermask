# -*- coding: utf-8 -*-
"""后台预览。按高分辨率上限缩小，供画布缩放查看，而不是压成窗口大小。"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.renderer import render_watermark_with_hits

# 预览长边上限：兼顾清晰度与内存。大于此尺寸再缩小；小于则保留渲染尺寸。
PREVIEW_MAX_EDGE = 3200


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


def preview_scale_for(size: tuple[int, int], max_edge: int = PREVIEW_MAX_EDGE) -> float:
    width, height = size
    longest = max(width, height, 1)
    if longest <= max_edge:
        return 1.0
    return max_edge / float(longest)


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
        max_edge: int = PREVIEW_MAX_EDGE,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.path = path
        self.options = dict(options)
        # width/height 保留兼容；清晰度不再按窗口压图。
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.max_edge = max(800, int(max_edge))
        self.signals = signals

    def run(self) -> None:
        try:
            rendered, hits = render_watermark_with_hits(self.path, self.options)
            scale = preview_scale_for(rendered.size, self.max_edge)
            if scale < 1.0:
                size = (
                    max(1, int(rendered.width * scale)),
                    max(1, int(rendered.height * scale)),
                )
                view = rendered.resize(size, Image.Resampling.LANCZOS)
            else:
                size = rendered.size
                view = rendered
                scale = 1.0
            image = pil_to_qimage(view)
            scaled_hits = []
            for hit in hits:
                scaled_hits.append(
                    {
                        **hit,
                        "x": float(hit["x"]) * scale,
                        "y": float(hit["y"]) * scale,
                        "w": float(hit["w"]) * scale,
                        "h": float(hit["h"]) * scale,
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
