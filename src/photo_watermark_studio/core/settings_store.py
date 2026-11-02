# -*- coding: utf-8 -*-
"""把导出目录和水印选项保存到本机 JSON。不保存照片。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

STYLES = ("经典底栏", "极简叠加", "卡片相框")
THEMES = ("浅色", "深色", "蓝色", "高斯模糊")

TEXT_KEYS = (
    "camera_text",
    "lens_text",
    "exif_text",
    "date_text",
    "gps_text",
)
FIELD_SCALE_KEYS = (
    "camera_scale",
    "lens_scale",
    "exif_scale",
    "date_scale",
    "gps_scale",
)

OPTION_KEYS = (
    "style",
    "theme",
    "brand",
    "caption",
    "scale",
    "logo_path",
    "show_camera",
    "show_lens",
    "show_exif",
    "show_date",
    "show_gps",
    "show_brand_text",
    *TEXT_KEYS,
    *FIELD_SCALE_KEYS,
)

_FIELD_SCALE_MIN = 0.7
_FIELD_SCALE_MAX = 1.6


def default_layout() -> dict[str, Any]:
    return {
        "anchor": "bottom_center",
        "margin_x": 0.0,
        "margin_y": 0.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "bar_opacity": 0.72,
        "corner_radius": 0,
        "blur_radius": 12.0,
    }


def default_settings() -> dict[str, Any]:
    return {
        "output_dir": str(Path.home() / "Pictures" / "PhotoWatermark"),
        "browse_dir": str(Path.home()),
        "style": "经典底栏",
        "theme": "浅色",
        "brand": "",
        "caption": "",
        "scale": 1.0,
        "logo_path": "",
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
        "quality": 95,
        "layout": default_layout(),
        "conflict_policy": "number",
    }


def default_settings_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home())
        return root / "PhotoWatermarkStudio" / "settings.json"
    return Path.home() / ".photo_watermark_studio" / "settings.json"


def _coerce_field_scale(raw: Any, default: float = 1.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return min(_FIELD_SCALE_MAX, max(_FIELD_SCALE_MIN, value))


def coerce_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_settings()
    if not isinstance(raw, dict):
        return base
    data = dict(base)
    style = str(raw.get("style", base["style"]) or "")
    data["style"] = style if style in STYLES else base["style"]
    theme = str(raw.get("theme", base["theme"]) or "")
    if theme == "高斯模糊+变暗":
        theme = "高斯模糊"
    data["theme"] = theme if theme in THEMES else base["theme"]
    data["brand"] = str(raw.get("brand", "") or "")
    data["caption"] = str(raw.get("caption", "") or "")
    try:
        scale = float(raw.get("scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    data["scale"] = min(1.6, max(0.65, scale))
    data["logo_path"] = str(raw.get("logo_path", "") or "")
    for key in ("show_camera", "show_lens", "show_exif", "show_date", "show_gps", "show_brand_text"):
        data[key] = bool(raw.get(key, base[key]))
    for key in TEXT_KEYS:
        data[key] = str(raw.get(key, "") or "")
    for key in FIELD_SCALE_KEYS:
        data[key] = _coerce_field_scale(raw.get(key, 1.0), 1.0)
    try:
        quality = int(float(raw.get("quality", 95)))
    except (TypeError, ValueError):
        quality = 95
    data["quality"] = min(100, max(80, quality))
    output_dir = str(raw.get("output_dir", "") or "").strip()
    data["output_dir"] = output_dir or str(base["output_dir"])
    browse_dir = str(raw.get("browse_dir", "") or "").strip()
    data["browse_dir"] = browse_dir or str(base["browse_dir"])
    layout_raw = raw.get("layout") if isinstance(raw.get("layout"), dict) else raw
    # 延迟导入避免循环；coerce_layout 在 document 中定义时用本地简化版。
    data["layout"] = coerce_layout(layout_raw if isinstance(layout_raw, dict) else None)
    policy = str(raw.get("conflict_policy", base.get("conflict_policy", "number")) or "number")
    data["conflict_policy"] = policy if policy in ("number", "overwrite") else "number"
    return data


def coerce_layout(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_layout()
    if not isinstance(raw, dict):
        return base
    data = dict(base)
    anchors = {
        "top_left",
        "top_center",
        "top_right",
        "middle_left",
        "center",
        "middle_right",
        "bottom_left",
        "bottom_center",
        "bottom_right",
    }
    anchor = str(raw.get("anchor", base["anchor"]) or base["anchor"])
    data["anchor"] = anchor if anchor in anchors else base["anchor"]

    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    for key, lo, hi in (
        ("margin_x", 0.0, 0.35),
        ("margin_y", 0.0, 0.35),
        ("offset_x", -0.45, 0.45),
        ("offset_y", -0.45, 0.45),
        ("bar_opacity", 0.15, 1.0),
        ("blur_radius", 1.0, 40.0),
    ):
        try:
            data[key] = _clamp(float(raw.get(key, base[key])), lo, hi)
        except (TypeError, ValueError):
            data[key] = base[key]
    try:
        data["corner_radius"] = int(_clamp(float(raw.get("corner_radius", 0)), 0, 48))
    except (TypeError, ValueError):
        data["corner_radius"] = 0
    return data


def load_settings(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_settings_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return default_settings()
    return coerce_settings(raw if isinstance(raw, dict) else None)


def save_settings(data: dict[str, Any], path: Path | None = None) -> None:
    target = Path(path) if path is not None else default_settings_path()
    payload = coerce_settings(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
