# -*- coding: utf-8 -*-
"""原图像素坐标与画布显示坐标互转。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSize:
    width: int
    height: int


@dataclass(frozen=True)
class ViewRect:
    """图片在场景中的矩形（场景坐标）。"""

    x: float
    y: float
    width: float
    height: float


class CoordinateMapper:
    """归一化偏移与原图像素 / 场景坐标转换。"""

    def __init__(self, image: ImageSize, view: ViewRect) -> None:
        self.image = image
        self.view = view

    @property
    def scale_x(self) -> float:
        if self.image.width <= 0:
            return 1.0
        return self.view.width / float(self.image.width)

    @property
    def scale_y(self) -> float:
        if self.image.height <= 0:
            return 1.0
        return self.view.height / float(self.image.height)

    def image_to_scene(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.view.x + x * self.scale_x,
            self.view.y + y * self.scale_y,
        )

    def scene_to_image(self, x: float, y: float) -> tuple[float, float]:
        sx = self.scale_x or 1.0
        sy = self.scale_y or 1.0
        return ((x - self.view.x) / sx, (y - self.view.y) / sy)

    def norm_offset_to_pixels(self, nx: float, ny: float) -> tuple[float, float]:
        return (nx * self.image.width, ny * self.image.height)

    def pixels_to_norm_offset(self, dx: float, dy: float) -> tuple[float, float]:
        w = float(self.image.width) or 1.0
        h = float(self.image.height) or 1.0
        return (dx / w, dy / h)

    def hit_to_scene(self, hit: dict) -> tuple[float, float, float, float]:
        x = float(hit.get("x", 0))
        y = float(hit.get("y", 0))
        w = float(hit.get("w", 0))
        h = float(hit.get("h", 0))
        sx, sy = self.image_to_scene(x, y)
        return sx, sy, w * self.scale_x, h * self.scale_y
