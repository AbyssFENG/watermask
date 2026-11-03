# -*- coding: utf-8 -*-
"""统一水印配置对象。预览与导出共用；可与旧 settings dict 互转。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from photo_watermark_studio.core.settings_store import (
    FIELD_SCALE_KEYS,
    OPTION_KEYS,
    TEXT_KEYS,
    coerce_layout,
    coerce_settings,
    default_layout,
)

ANCHORS = (
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
)

LAYOUT_KEYS = (
    "anchor",
    "margin_x",
    "margin_y",
    "offset_x",
    "offset_y",
    "bar_opacity",
    "corner_radius",
    "blur_radius",
)


class WatermarkDocument:
    """水印文档：内容/样式/布局。序列化为 JSON 友好 dict。"""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = self._normalize(data)

    @staticmethod
    def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
        settings = coerce_settings(raw if isinstance(raw, dict) else None)
        layout_src = None
        if isinstance(raw, dict):
            layout_src = raw.get("layout") if isinstance(raw.get("layout"), dict) else raw
        layout = coerce_layout(layout_src if isinstance(layout_src, dict) else None)
        data = {key: settings[key] for key in OPTION_KEYS}
        data["quality"] = settings["quality"]
        data["output_dir"] = settings["output_dir"]
        data["browse_dir"] = settings["browse_dir"]
        data["layout"] = layout
        return data

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def copy(self) -> "WatermarkDocument":
        return WatermarkDocument(self.to_dict())

    def update(self, patch: dict[str, Any]) -> None:
        merged = self.to_dict()
        for key, value in patch.items():
            if key == "layout" and isinstance(value, dict):
                current = dict(merged.get("layout") or {})
                current.update(value)
                merged["layout"] = current
            else:
                merged[key] = value
        self._data = self._normalize(merged)

    def set_layout(self, **kwargs: Any) -> None:
        layout = dict(self._data["layout"])
        layout.update(kwargs)
        self._data["layout"] = coerce_layout(layout)

    @property
    def layout(self) -> dict[str, Any]:
        return dict(self._data["layout"])

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def render_options(self) -> dict[str, Any]:
        """供 Pillow 渲染器使用的扁平 options（含 layout 字段展开）。"""
        options = {key: self._data[key] for key in OPTION_KEYS}
        layout = self.layout
        # 位置布局功能暂时关闭：固定默认底部，避免旧偏移/九宫格影响预览。
        options["anchor"] = "bottom_center"
        options["margin_x"] = 0.0
        options["margin_y"] = 0.0
        options["offset_x"] = 0.0
        options["offset_y"] = 0.0
        options["bar_opacity"] = layout["bar_opacity"]
        options["corner_radius"] = layout["corner_radius"]
        options["blur_radius"] = layout["blur_radius"]
        return options

    def settings_payload(self) -> dict[str, Any]:
        """持久化用：不含临时文案/字号覆盖。"""
        data = self.to_dict()
        for key in TEXT_KEYS:
            data[key] = ""
        for key in FIELD_SCALE_KEYS:
            data[key] = 1.0
        return data

    @classmethod
    def from_settings(cls, settings: dict[str, Any] | None) -> "WatermarkDocument":
        return cls(settings)
