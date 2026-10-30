# -*- coding: utf-8 -*-
"""照片与水印用到的数据结构。"""
from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


@dataclass
class PhotoMetadata:
    make: str = ""
    camera: str = ""
    lens: str = ""
    focal: str = ""
    aperture: str = ""
    shutter: str = ""
    iso: str = ""
    date: str = ""
    gps: str = ""

    @property
    def brand(self) -> str:
        make = self.make.strip()
        if not make:
            return ""
        # Use the familiar brand styling in the signature area.
        mapping = {
            "NIKON": "Nikon",
            "CANON": "Canon",
            "SONY": "Sony",
            "FUJIFILM": "FUJIFILM",
            "OLYMPUS": "OM SYSTEM",
            "OM DIGITAL SOLUTIONS": "OM SYSTEM",
            "PANASONIC": "LUMIX",
            "LEICA": "Leica",
            "RICOH": "RICOH",
            "PENTAX": "PENTAX",
            "APPLE": "Apple iPhone",
        }
        return mapping.get(make.upper(), make.title())
