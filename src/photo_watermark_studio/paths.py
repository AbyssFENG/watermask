# -*- coding: utf-8 -*-
"""开发环境与打包环境下的资源路径。"""
from __future__ import annotations

import sys
from pathlib import Path


def resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "photo_watermark_studio" / "resources"
    return Path(__file__).resolve().parent / "resources"


def app_logo_path() -> Path:
    return resource_dir() / "app_logo.jpg"


def load_stylesheet() -> str:
    path = resource_dir() / "styles.qss"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    # 样式表以字符串载入时，url() 相对的是进程工作目录，而不是 qss 文件所在目录。
    resources = resource_dir().resolve().as_posix()
    return text.replace('url("resources/', f'url("{resources}/')
