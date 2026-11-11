# -*- coding: utf-8 -*-
"""本机用户水印模板：保存 / 应用 / 重命名 / 删除。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from photo_watermark_studio.core.settings_store import (
    FIELD_SCALE_KEYS,
    OPTION_KEYS,
    TEXT_KEYS,
    coerce_settings,
    default_settings_path,
)


def default_templates_path() -> Path:
    return default_settings_path().with_name("templates.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _template_settings_snapshot(raw: dict[str, Any] | None) -> dict[str, Any]:
    """只保留模板相关字段，去掉导出目录等会话态。"""
    data = coerce_settings(raw if isinstance(raw, dict) else None)
    keep = {key: data[key] for key in OPTION_KEYS}
    keep["layout"] = data["layout"]
    keep["quality"] = data["quality"]
    keep["export_format"] = data["export_format"]
    keep["png_compress"] = data["png_compress"]
    keep["webp_quality"] = data["webp_quality"]
    keep["keep_exif"] = data["keep_exif"]
    keep["keep_icc"] = data["keep_icc"]
    keep["conflict_policy"] = data["conflict_policy"]
    for key in TEXT_KEYS:
        keep[key] = ""
    for key in FIELD_SCALE_KEYS:
        keep[key] = 1.0
    return keep


def _normalize_entry(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "") or "").strip()
    if not name:
        return None
    entry_id = str(raw.get("id", "") or "").strip() or uuid.uuid4().hex
    settings = _template_settings_snapshot(raw.get("settings") if isinstance(raw.get("settings"), dict) else raw)
    updated = str(raw.get("updated_at", "") or "") or _now_iso()
    return {"id": entry_id, "name": name, "updated_at": updated, "settings": settings}


def load_templates(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else default_templates_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError):
        return []
    items = raw.get("templates") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        entry = _normalize_entry(item if isinstance(item, dict) else None)
        if entry is not None:
            out.append(entry)
    return out


def save_templates(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    target = Path(path) if path is not None else default_templates_path()
    normalized: list[dict[str, Any]] = []
    for item in entries:
        entry = _normalize_entry(item if isinstance(item, dict) else None)
        if entry is not None:
            normalized.append(entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "templates": normalized}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_templates(path: Path | None = None) -> list[dict[str, Any]]:
    return load_templates(path)


def recent_templates(limit: int = 2, path: Path | None = None) -> list[dict[str, Any]]:
    """按更新时间倒序返回最近的用户模板。"""
    entries = load_templates(path)
    entries.sort(key=lambda entry: str(entry.get("updated_at", "")), reverse=True)
    return entries[: max(0, int(limit))]


def get_template(template_id: str, path: Path | None = None) -> dict[str, Any] | None:
    tid = str(template_id or "").strip()
    if not tid:
        return None
    for entry in load_templates(path):
        if entry["id"] == tid:
            return entry
    return None


def find_by_name(name: str, path: Path | None = None) -> dict[str, Any] | None:
    needle = str(name or "").strip()
    if not needle:
        return None
    for entry in load_templates(path):
        if entry["name"] == needle:
            return entry
    return None


def save_template(
    name: str,
    settings: dict[str, Any],
    *,
    template_id: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """按名称保存；若同名或指定 id 则覆盖。"""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("模板名称不能为空")
    entries = load_templates(path)
    snapshot = _template_settings_snapshot(settings)
    tid = str(template_id or "").strip()
    existing = None
    if tid:
        existing = next((e for e in entries if e["id"] == tid), None)
    if existing is None:
        existing = next((e for e in entries if e["name"] == clean_name), None)
    if existing is not None:
        existing["name"] = clean_name
        existing["settings"] = snapshot
        existing["updated_at"] = _now_iso()
        save_templates(entries, path)
        return existing
    entry = {
        "id": tid or uuid.uuid4().hex,
        "name": clean_name,
        "updated_at": _now_iso(),
        "settings": snapshot,
    }
    entries.append(entry)
    save_templates(entries, path)
    return entry


def rename_template(template_id: str, new_name: str, path: Path | None = None) -> dict[str, Any]:
    clean = str(new_name or "").strip()
    if not clean:
        raise ValueError("模板名称不能为空")
    entries = load_templates(path)
    target = next((e for e in entries if e["id"] == template_id), None)
    if target is None:
        raise KeyError("模板不存在")
    clash = next((e for e in entries if e["name"] == clean and e["id"] != template_id), None)
    if clash is not None:
        raise ValueError("已有同名模板")
    target["name"] = clean
    target["updated_at"] = _now_iso()
    save_templates(entries, path)
    return target


def delete_template(template_id: str, path: Path | None = None) -> bool:
    tid = str(template_id or "").strip()
    entries = load_templates(path)
    kept = [e for e in entries if e["id"] != tid]
    if len(kept) == len(entries):
        return False
    save_templates(kept, path)
    return True
