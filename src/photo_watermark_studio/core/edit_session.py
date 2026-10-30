# -*- coding: utf-8 -*-
"""预览点击改文案/字号的临时会话。按照片路径分别保存；导出或退出时清除。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from photo_watermark_studio.core.settings_store import FIELD_SCALE_KEYS, TEXT_KEYS

_EDITABLE_META = ("camera", "lens", "exif", "date", "gps")


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
    """把某张照片的临时覆盖合并进渲染选项。"""
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
    return merged


class EditSessionStore:
    """按照片路径保存元数据文案/字号到临时 JSON。"""

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
            # 新格式：{"photos": {path: {...}}}
            source = raw.get("photos") if isinstance(raw.get("photos"), dict) else None
            if source is None and any(key in raw for key in TEXT_KEYS):
                # 兼容旧的全局格式：整份当作“未绑定路径”的无效数据，直接丢弃。
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

    def snapshot_photos(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._photos.items()}

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
