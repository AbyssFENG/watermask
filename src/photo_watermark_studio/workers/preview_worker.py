# -*- coding: utf-8 -*-
"""后台预览。先缩到长边上限再渲水印，供画布缩放查看。"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.renderer import render_watermark_layers
from photo_watermark_studio.core.settings_store import is_custom_style

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


# 只保留当前这一张预览底图。键是路径、mtime、大小和长边上限。
_preview_cache_lock = threading.Lock()
_preview_cache: tuple[tuple[str, int, int, int], Image.Image] | None = None


def clear_preview_base_cache() -> None:
    global _preview_cache
    with _preview_cache_lock:
        _preview_cache = None


def _preview_cache_key(path: str, max_edge: int) -> tuple[str, int, int, int] | None:
    try:
        file_path = Path(path).resolve()
        stat = file_path.stat()
        return (str(file_path), int(stat.st_mtime_ns), int(stat.st_size), int(max_edge))
    except OSError:
        return None


def _decode_preview_base(path: str, max_edge: int) -> Image.Image:
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


def load_preview_base(path: str, max_edge: int = PREVIEW_MAX_EDGE) -> Image.Image:
    """打开原图并缩到预览上限。同一文件未变化时复用已解码底图。"""
    global _preview_cache
    key = _preview_cache_key(path, max_edge)
    if key is not None:
        with _preview_cache_lock:
            cached = _preview_cache
            if cached is not None and cached[0] == key:
                return cached[1].copy()
    image = _decode_preview_base(path, max_edge)
    if key is not None:
        with _preview_cache_lock:
            _preview_cache = (key, image)
            return image.copy()
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


def _sprites_to_q(sprites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spr in sprites:
        img = spr.get("image")
        if img is None:
            continue
        out.append(
            {
                "key": str(spr.get("key", "")),
                "x": float(spr.get("x", 0)),
                "y": float(spr.get("y", 0)),
                "w": float(spr.get("w", 0)),
                "h": float(spr.get("h", 0)),
                "image": pil_to_qimage(img),
            }
        )
    return out


class PreviewSignals(QObject):
    # request_id, display_image(base 或 合成), hits, error, status, sprites(自定义字段层)
    finished = Signal(int, QImage, object, str, str, object)


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
            layers = render_watermark_layers(
                self.path,
                self.options,
                base_image=base,
                metadata=metadata,
            )
            # 自定义：画布底图用无字段 base；其它：base==composite。
            display = layers["base"] if is_custom_style(self.options) else layers["composite"]
            image = pil_rgb_to_qimage(display)
            sprites = _sprites_to_q(layers.get("sprites") or []) if is_custom_style(self.options) else []
            status = _status_from_metadata(metadata)
            self.signals.finished.emit(
                self.request_id, image, list(layers.get("hits") or []), "", status, sprites
            )
        except Exception as exc:
            self.signals.finished.emit(self.request_id, QImage(), [], str(exc), "", [])


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
