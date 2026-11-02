# -*- coding: utf-8 -*-
"""按张保存的编辑覆盖。支持文案/字号与布局差分。"""
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from photo_watermark_studio.core.settings_store import FIELD_SCALE_KEYS, TEXT_KEYS, coerce_layout

_EDITABLE_META = ("camera", "lens", "exif", "date", "gps")
_DOC_KEYS = ("layout",)


def session_dir() -> Path:
    return Path(tempfile.gettempdir()) / "PhotoWatermarkStudio_edit_session"


def default_session_path() -> Path:
    return session_dir() / "overrides.json"


def empty_photo_overrides() -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key in TEXT_KEYS:
        data[key] = ""
    for key in FIELD_SCALE_KEYS:
        data[key] = 1.0
    data["layout"] = {}
    return data


def _coerce_photo_overrides(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = empty_photo_overrides()
    if not isinstance(raw, dict):
        return data
    for key in TEXT_KEYS:
        data[key] = str(raw.get(key, "") or "")
    for key in FIELD_SCALE_KEYS:
        try:
            value = float(raw.get(key, 1.0))
        except (TypeError, ValueError):
            value = 1.0
        data[key] = min(1.6, max(0.7, value))
    if isinstance(raw.get("layout"), dict) and raw["layout"]:
        data["layout"] = coerce_layout(raw["layout"])
    else:
        data["layout"] = {}
    return data


def normalize_photo_path(path: str | Path | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def merge_photo_overrides(
    options: dict[str, Any],
    photo_path: str | Path | None,
    photos: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    merged = dict(options)
    values = empty_photo_overrides()
    if isinstance(photos, dict):
        key = normalize_photo_path(photo_path)
        raw = photos.get(key) or photos.get(str(photo_path or ""))
        values = _coerce_photo_overrides(raw if isinstance(raw, dict) else None)
    for item in TEXT_KEYS:
        merged[item] = values.get(item, "")
    for item in FIELD_SCALE_KEYS:
        merged[item] = values.get(item, 1.0)
    layout_override = values.get("layout") or {}
    if layout_override:
        base_layout = coerce_layout(merged.get("layout") if isinstance(merged.get("layout"), dict) else None)
        base_layout.update({k: layout_override[k] for k in layout_override})
        merged["layout"] = base_layout
        for key in ("anchor", "margin_x", "margin_y", "offset_x", "offset_y", "bar_opacity", "corner_radius", "blur_radius"):
            if key in base_layout:
                merged[key] = base_layout[key]
    elif isinstance(merged.get("layout"), dict):
        for key in ("anchor", "margin_x", "margin_y", "offset_x", "offset_y", "bar_opacity", "corner_radius", "blur_radius"):
            if key in merged["layout"]:
                merged[key] = merged["layout"][key]
    return merged


class EditSessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_session_path()
        self._photos: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
            self._photos = {}
            return {}
        photos: dict[str, dict[str, Any]] = {}
        if isinstance(raw, dict):
            source = raw.get("photos") if isinstance(raw.get("photos"), dict) else None
            if source is None and any(key in raw for key in TEXT_KEYS):
                source = {}
            if isinstance(source, dict):
                for photo_path, values in source.items():
                    key = normalize_photo_path(photo_path)
                    if key:
                        photos[key] = _coerce_photo_overrides(values if isinstance(values, dict) else None)
        self._photos = photos
        return {key: dict(value) for key, value in self._photos.items()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"photos": self._photos}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self._photos = {}
        try:
            if self.path.is_file():
                self.path.unlink()
        except OSError:
            pass
        try:
            parent = self.path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    def clear_photo(self, photo_path: str | Path | None) -> None:
        key = normalize_photo_path(photo_path)
        if key in self._photos:
            self._photos.pop(key, None)
            if self._photos:
                self.save()
            else:
                self.clear()

    def snapshot_photos(self) -> dict[str, dict[str, Any]]:
        return {key: deepcopy(value) for key, value in self._photos.items()}

    def has_overrides(self, photo_path: str | Path | None = None) -> bool:
        if photo_path is None:
            return any(self._photo_has_overrides(values) for values in self._photos.values())
        values = self._photos.get(normalize_photo_path(photo_path))
        return bool(values) and self._photo_has_overrides(values)

    def _photo_has_overrides(self, values: dict[str, Any]) -> bool:
        for key in TEXT_KEYS:
            if str(values.get(key, "") or "").strip():
                return True
        for key in FIELD_SCALE_KEYS:
            if abs(float(values.get(key, 1.0)) - 1.0) > 1e-6:
                return True
        layout = values.get("layout") or {}
        if isinstance(layout, dict) and layout:
            return True
        return False

    def get_field(self, photo_path: str | Path | None, field: str) -> dict[str, Any]:
        values = self._photos.get(normalize_photo_path(photo_path), empty_photo_overrides())
        return {
            "text": str(values.get(f"{field}_text", "") or ""),
            "scale": float(values.get(f"{field}_scale", 1.0)),
        }

    def set_field(
        self,
        photo_path: str | Path | None,
        field: str,
        text: str,
        scale: float | None = None,
    ) -> None:
        if field not in _EDITABLE_META:
            raise KeyError(field)
        key = normalize_photo_path(photo_path)
        if not key:
            return
        values = dict(self._photos.get(key) or empty_photo_overrides())
        values[f"{field}_text"] = str(text or "")
        if scale is not None:
            try:
                value = float(scale)
            except (TypeError, ValueError):
                value = 1.0
            values[f"{field}_scale"] = min(1.6, max(0.7, value))
        self._store(key, values)

    def set_layout_patch(self, photo_path: str | Path | None, layout_patch: dict[str, Any]) -> None:
        key = normalize_photo_path(photo_path)
        if not key:
            return
        values = dict(self._photos.get(key) or empty_photo_overrides())
        current = dict(values.get("layout") or {})
        current.update(layout_patch)
        values["layout"] = coerce_layout(current)
        self._store(key, values)

    def _store(self, key: str, values: dict[str, Any]) -> None:
        if self._photo_has_overrides(values):
            self._photos[key] = values
        else:
            self._photos.pop(key, None)
        if self._photos:
            self.save()
        else:
            self.clear()

    def merge_into(self, options: dict[str, Any], photo_path: str | Path | None = None) -> dict[str, Any]:
        return merge_photo_overrides(options, photo_path, self._photos)
