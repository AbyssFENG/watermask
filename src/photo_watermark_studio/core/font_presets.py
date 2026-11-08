# -*- coding: utf-8 -*-
"""水印艺术字体预设：展示名、本机路径、Qt 预览族名。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

DEFAULT_FONT_FAMILY = "默认"


class FontPreset(NamedTuple):
    name: str
    filename: str
    qt_family: str


# Windows Fonts 目录下常见艺术中文字体（按展示名）。
_WINDOWS_PRESETS: tuple[FontPreset, ...] = (
    FontPreset("楷体", "simkai.ttf", "KaiTi"),
    FontPreset("隶书", "SIMLI.TTF", "LiSu"),
    FontPreset("幼圆", "SIMYOU.TTF", "YouYuan"),
    FontPreset("华文行楷", "STXINGKA.TTF", "STXingkai"),
    FontPreset("华文楷体", "STKAITI.TTF", "STKaiti"),
    FontPreset("华文隶书", "STLITI.TTF", "STLiti"),
    FontPreset("华文新魏", "STXINWEI.TTF", "STXinwei"),
    FontPreset("华文琥珀", "STHUPO.TTF", "STHupo"),
    FontPreset("方正舒体", "FZSTK.TTF", "FZShuTi"),
    FontPreset("方正姚体", "FZYTK.TTF", "FZYaoTi"),
)


def _windows_fonts_dir() -> Path:
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    return Path(windir) / "Fonts"


def all_font_presets() -> tuple[FontPreset, ...]:
    return _WINDOWS_PRESETS


@lru_cache(maxsize=1)
def available_font_presets() -> tuple[FontPreset, ...]:
    """返回本机存在的艺术字体预设（不含「默认」）。"""
    if os.name != "nt":
        return ()
    fonts_dir = _windows_fonts_dir()
    found: list[FontPreset] = []
    for preset in _WINDOWS_PRESETS:
        if (fonts_dir / preset.filename).is_file():
            found.append(preset)
    return tuple(found)


def available_font_names() -> tuple[str, ...]:
    return (DEFAULT_FONT_FAMILY, *(p.name for p in available_font_presets()))


def coerce_font_family(raw: object) -> str:
    name = str(raw or "").strip() or DEFAULT_FONT_FAMILY
    if name == DEFAULT_FONT_FAMILY:
        return DEFAULT_FONT_FAMILY
    known = {p.name for p in _WINDOWS_PRESETS}
    if name not in known:
        return DEFAULT_FONT_FAMILY
    # 预设合法但本机缺失时仍保留名称，渲染会回退默认链。
    return name


def resolve_font_path(font_family: str) -> str | None:
    """将展示名解析为绝对字体路径；「默认」或缺失返回 None。"""
    name = coerce_font_family(font_family)
    if name == DEFAULT_FONT_FAMILY:
        return None
    if os.name != "nt":
        return None
    fonts_dir = _windows_fonts_dir()
    for preset in _WINDOWS_PRESETS:
        if preset.name != name:
            continue
        path = fonts_dir / preset.filename
        if path.is_file():
            return str(path)
        return None
    return None


def qt_family_for(font_family: str) -> str:
    name = coerce_font_family(font_family)
    for preset in _WINDOWS_PRESETS:
        if preset.name == name:
            return preset.qt_family
    return ""
