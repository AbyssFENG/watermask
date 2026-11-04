# -*- coding: utf-8 -*-
"""后台预览。先缩到长边上限再渲水印，供画布缩放查看。"""
from __future__ import annotations

from PIL import Image, ImageOps
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


def pil_rgb_to_qimage(image: Image.Image) -> QImage:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    return QImage(
        data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888
    ).copy()


def preview_scale_for(size: tuple[int, int], max_edge: int = PREVIEW_MAX_EDGE) -> float:
    width, height = size
    longest = max(width, height, 1)
    if longest <= max_edge:
        return 1.0
    return max_edge / float(longest)


def load_preview_base(path: str, max_edge: int = PREVIEW_MAX_EDGE) -> Image.Image:
    """打开原图并缩到预览上限（EXIF 方向校正后）。"""
    with Image.open(path) as src:
        image = ImageOps.exif_transpose(src).convert("RGB")
    scale = preview_scale_for(image.size, max_edge)
    if scale < 1.0:
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def _status_from_metadata(metadata) -> str:
    if not any(
        (
            metadata.camera,
            metadata.lens,
            metadata.focal,
            metadata.aperture,
            metadata.shutter,
            metadata.iso,
            metadata.date,
        )
    ):
        return "预览已更新。当前图片没有可读取的 EXIF 参数，可通过自定义说明补充。"
    return f"预览已更新。已读取相机信息：{metadata.camera or metadata.make or '部分参数'}"


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
        # width/height 保留兼容；清晰度按 max_edge，不再按窗口压图。
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.max_edge = max(800, int(max_edge))
        self.signals = signals

    def run(self) -> None:
        try:
            # 先缩后渲：避免在全尺寸上做模糊/排版，导出仍走全分辨率路径。
            base = load_preview_base(self.path, self.max_edge)
            metadata = read_photo_metadata(self.path)
            rendered, hits = render_watermark_with_hits(
                self.path,
                self.options,
                base_image=base,
                metadata=metadata,
            )
            image = pil_to_qimage(rendered)
            status = _status_from_metadata(metadata)
            self.signals.finished.emit(self.request_id, image, list(hits), "", status)
        except Exception as exc:
            self.signals.finished.emit(self.request_id, QImage(), [], str(exc), "")


class SourceImageSignals(QObject):
    finished = Signal(int, str, QImage)


class SourceImageRunnable(QRunnable):
    """异步加载「原图对比」用位图，不阻塞切换。"""

    def __init__(
        self,
        request_id: int,
        path: str,
        signals: SourceImageSignals,
        max_edge: int = PREVIEW_MAX_EDGE,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.path = path
        self.signals = signals
        self.max_edge = max(800, int(max_edge))

    def run(self) -> None:
        try:
            image = load_preview_base(self.path, self.max_edge)
            self.signals.finished.emit(self.request_id, self.path, pil_rgb_to_qimage(image))
        except Exception:
            self.signals.finished.emit(self.request_id, self.path, QImage())
