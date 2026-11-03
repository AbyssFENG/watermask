# -*- coding: utf-8 -*-
"""读取照片中实际存在的 EXIF，并格式化成水印文案。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PIL import ExifTags, Image

from photo_watermark_studio.core.models import PhotoMetadata


def _clean_exif_text(value: Any) -> str:
    """清理 EXIF 文本：截断空字节填充，去掉控制字符与首尾空白。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    else:
        text = str(value)
        if "\x00" in text:
            text = text.split("\x00", 1)[0]
    # 去掉其余控制字符（保留普通空白，最后再 strip）
    cleaned = "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)
    return cleaned.strip()


_CORP_SUFFIXES = (
    " CORPORATION",
    " CORP.",
    " CORP",
    " INCORPORATED",
    " INC.",
    " INC",
    " CO., LTD.",
    " CO.,LTD.",
    " CO LTD",
    " LTD.",
    " LTD",
    " COMPANY",
)


def _short_make(make: str) -> str:
    """去掉厂商名里的公司后缀，如 NIKON CORPORATION → NIKON。"""
    brand = make.strip().upper()
    for suffix in _CORP_SUFFIXES:
        if brand.endswith(suffix):
            return brand[: -len(suffix)].strip()
    return brand


def _format_camera(make: str, model: str) -> str:
    """组合相机型号；型号已含品牌时不再重复拼接厂商全称。"""
    make = make.strip()
    model = model.strip()
    if not model and not make:
        return ""
    if not model:
        return _short_make(make) or make.upper()
    model_u = model.upper()
    make_u = make.upper()
    brand = _short_make(make)
    if make_u and model_u.startswith(make_u):
        return model_u
    if brand and model_u.startswith(brand):
        return model_u
    if brand:
        return f"{brand} {model_u}".strip()
    return model_u


def _as_float(value: Any) -> Optional[float]:
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            den = float(value.denominator)
            return float(value.numerator) / den if den else None
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0]) / float(value[1]) if float(value[1]) else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def _format_focal(value: Any) -> str:
    n = _as_float(value)
    if n is None:
        return ""
    return f"{n:g}mm"


def _format_aperture(value: Any) -> str:
    n = _as_float(value)
    if n is None:
        return ""
    return f"F{n:.1f}" if n < 10 else f"F{n:g}"


def _format_shutter(value: Any) -> str:
    n = _as_float(value)
    if n is None or n <= 0:
        return ""
    if n >= 1:
        return f"{n:g}s"
    denom = round(1 / n)
    if denom > 0 and abs(1 / denom - n) < 0.003:
        return f"1/{denom}s"
    return f"{n:.4f}s".rstrip("0").rstrip(".")


def _format_datetime(value: Any) -> str:
    if not value:
        return ""
    s = _clean_exif_text(value)
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y.%m.%d  %H:%M:%S" if "%H" in fmt else "%Y.%m.%d")
        except ValueError:
            pass
    return s


def _gps_to_decimal(value: Any, ref: Any) -> Optional[float]:
    try:
        parts = [_as_float(x) for x in value]
        if len(parts) < 3 or any(x is None for x in parts[:3]):
            return None
        out = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        if str(ref).upper() in {"S", "W"}:
            out = -out
        return out
    except Exception:
        return None


def read_photo_metadata(path: str | Path) -> PhotoMetadata:
    """Read common camera EXIF fields. Missing EXIF is normal and returns empty fields."""
    md = PhotoMetadata()
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return md
            md.make = _clean_exif_text(exif.get(271, ""))
            model = _clean_exif_text(exif.get(272, ""))
            md.camera = _format_camera(md.make, model)

            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:
                exif_ifd = {}
            exif_ifd = exif_ifd or {}

            lens = exif_ifd.get(42036) or exif_ifd.get(0xA434) or exif.get(42036) or exif.get(0xA434)
            if lens:
                md.lens = _clean_exif_text(lens).upper()
            md.focal = _format_focal(exif_ifd.get(37386) or exif.get(37386))
            md.aperture = _format_aperture(exif_ifd.get(33437) or exif.get(33437))
            md.shutter = _format_shutter(exif_ifd.get(33434) or exif.get(33434))
            iso = exif_ifd.get(34855) or exif_ifd.get(0x8827) or exif.get(34855) or exif.get(0x8827)
            if isinstance(iso, (tuple, list)):
                iso = iso[0] if iso else None
            if iso is not None:
                md.iso = _clean_exif_text(iso)
            date = exif_ifd.get(36867) or exif_ifd.get(36868) or exif.get(36867) or exif.get(306)
            md.date = _format_datetime(date)

            try:
                gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            except Exception:
                gps_ifd = {}
            if gps_ifd:
                lat = _gps_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
                lon = _gps_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
                if lat is not None and lon is not None:
                    md.gps = f"{lat:.5f}, {lon:.5f}"
    except Exception:
        # Image may be damaged or an unsupported RAW format; the app still allows a custom caption.
        return md
    return md
