# -*- coding: utf-8 -*-
"""水印字体预设：展示名、本机路径、Qt 预览族名。"""
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
    cjk: bool = True


# 只收录适合水印的字体。本机没有的文件不会出现在下拉框里。
_WINDOWS_PRESETS: tuple[FontPreset, ...] = (
    FontPreset("微软雅黑", "msyh.ttc", "Microsoft YaHei"),
    FontPreset("黑体", "simhei.ttf", "SimHei"),
    FontPreset("宋体", "simsun.ttc", "SimSun"),
    FontPreset("仿宋", "simfang.ttf", "FangSong"),
    FontPreset("等线", "Deng.ttf", "DengXian"),
    FontPreset("楷体", "simkai.ttf", "KaiTi"),
    FontPreset("思源黑体", "NotoSansSC-VF.ttf", "Noto Sans SC"),
    FontPreset("思源宋体", "NotoSerifSC-VF.ttf", "Noto Serif SC"),
    FontPreset("汉仪中黑", "HYZhongHeiTi-197.ttf", "HYZhongHei"),
    FontPreset("隶书", "SIMLI.TTF", "LiSu"),
    FontPreset("幼圆", "SIMYOU.TTF", "YouYuan"),
    FontPreset("华文宋体", "STSONG.TTF", "STSong"),
    FontPreset("华文中宋", "STZHONGS.TTF", "STZhongsong"),
    FontPreset("华文细黑", "STXIHEI.TTF", "STXihei"),
    FontPreset("华文仿宋", "STFANGSO.TTF", "STFangsong"),
    FontPreset("华文楷体", "STKAITI.TTF", "STKaiti"),
    FontPreset("华文隶书", "STLITI.TTF", "STLiti"),
    FontPreset("华文行楷", "STXINGKA.TTF", "STXingkai"),
    FontPreset("华文新魏", "STXINWEI.TTF", "STXinwei"),
    FontPreset("华文琥珀", "STHUPO.TTF", "STHupo"),
    FontPreset("华文彩云", "STCAIYUN.TTF", "STCaiyun"),
    FontPreset("方正舒体", "FZSTK.TTF", "FZShuTi"),
    FontPreset("方正姚体", "FZYTK.TTF", "FZYaoTi"),
    FontPreset("微软正黑", "msjh.ttc", "Microsoft JhengHei"),
    FontPreset("Arial", "arial.ttf", "Arial", False),
    FontPreset("Calibri", "calibri.ttf", "Calibri", False),
    FontPreset("Candara", "Candara.ttf", "Candara", False),
    FontPreset("Corbel", "corbel.ttf", "Corbel", False),
    FontPreset("Verdana", "verdana.ttf", "Verdana", False),
    FontPreset("Trebuchet MS", "trebuc.ttf", "Trebuchet MS", False),
    FontPreset("Bahnschrift", "bahnschrift.ttf", "Bahnschrift", False),
    FontPreset("Consolas", "consola.ttf", "Consolas", False),
    FontPreset("Courier New", "cour.ttf", "Courier New", False),
    FontPreset("Georgia", "georgia.ttf", "Georgia", False),
    FontPreset("Times New Roman", "times.ttf", "Times New Roman", False),
    FontPreset("Palatino", "pala.ttf", "Palatino Linotype", False),
    FontPreset("Garamond", "GARA.TTF", "Garamond", False),
    FontPreset("Cambria", "cambria.ttc", "Cambria", False),
    FontPreset("Constantia", "constan.ttf", "Constantia", False),
    FontPreset("Book Antiqua", "BKANT.TTF", "Book Antiqua", False),
    FontPreset("Bookman Old Style", "BOOKOS.TTF", "Bookman Old Style", False),
    FontPreset("Century", "CENTURY.TTF", "Century", False),
    FontPreset("Century Gothic", "GOTHIC.TTF", "Century Gothic", False),
    FontPreset("Impact", "impact.ttf", "Impact", False),
    FontPreset("Segoe Script", "segoesc.ttf", "Segoe Script", False),
    FontPreset("Segoe Print", "segoepr.ttf", "Segoe Print", False),
    FontPreset("Gabriola", "Gabriola.ttf", "Gabriola", False),
    FontPreset("Ink Free", "Inkfree.ttf", "Ink Free", False),
    FontPreset("Freestyle Script", "FREESCPT.TTF", "Freestyle Script", False),
    FontPreset("French Script", "FRSCRIPT.TTF", "French Script MT", False),
    FontPreset("Lucida Handwriting", "LHANDW.TTF", "Lucida Handwriting", False),
    FontPreset("Mistral", "MISTRAL.TTF", "Mistral", False),
    FontPreset("Monotype Corsiva", "MTCORSVA.TTF", "Monotype Corsiva", False),
    FontPreset("Pristina", "PRISTINA.TTF", "Pristina", False),
    FontPreset("Papyrus", "PAPYRUS.TTF", "Papyrus", False),
    FontPreset("Bradley Hand", "BRADHITC.TTF", "Bradley Hand ITC", False),
    FontPreset("Kristen ITC", "ITCKRIST.TTF", "Kristen ITC", False),
    FontPreset("Tempus Sans", "TEMPSITC.TTF", "Tempus Sans ITC", False),
    FontPreset("Juice ITC", "JUICE___.TTF", "Juice ITC", False),
)


def _windows_fonts_dir() -> Path:
    windir = os.environ.get("WINDIR") or r"C:\Windows"
    return Path(windir) / "Fonts"


def all_font_presets() -> tuple[FontPreset, ...]:
    return _WINDOWS_PRESETS


@lru_cache(maxsize=1)
def available_font_presets() -> tuple[FontPreset, ...]:
    """返回本机存在的字体预设（不含「默认」）。"""
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


def font_covers_cjk(font_family: str) -> bool:
    """该预设能否画出中文。默认字体走雅黑，视为可以。"""
    name = coerce_font_family(font_family)
    if name == DEFAULT_FONT_FAMILY:
        return True
    for preset in _WINDOWS_PRESETS:
        if preset.name == name:
            return preset.cjk
    return True


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
