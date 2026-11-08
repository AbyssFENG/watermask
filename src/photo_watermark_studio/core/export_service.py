# -*- coding: utf-8 -*-
"""导出路径、多格式保存与原图保护。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from photo_watermark_studio.core.renderer import render_watermark
from photo_watermark_studio.core.settings_store import EXPORT_FORMAT_EXTS, EXPORT_FORMATS


def normalize_export_format(raw: Any) -> str:
    fmt = str(raw or "jpg").strip().lower()
    if fmt == "jpeg":
        fmt = "jpg"
    if fmt == "tif":
        fmt = "tiff"
    return fmt if fmt in EXPORT_FORMATS else "jpg"


def export_extension(fmt: str) -> str:
    return EXPORT_FORMAT_EXTS.get(normalize_export_format(fmt), ".jpg")


def allocate_output_path(
    source: str | Path,
    output_dir: str | Path,
    conflict_policy: str = "number",
    ext: str = ".jpg",
) -> Path:
    """选择导出文件名。默认 `原名_watermark{ext}`，不覆盖原图。

    conflict_policy=number：目标已存在时追加 `_2`、`_3`。
    conflict_policy=overwrite：允许覆盖已有水印文件，仍不会写回原文件名。
    """
    source_path = Path(source)
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = ext if str(ext).startswith(".") else f".{ext}"
    out_path = folder / f"{source_path.stem}_watermark{suffix}"
    policy = str(conflict_policy or "number")
    if out_path.exists() and policy != "overwrite":
        stem = source_path.stem
        counter = 2
        while (folder / f"{stem}_watermark_{counter}{suffix}").exists():
            counter += 1
        out_path = folder / f"{stem}_watermark_{counter}{suffix}"
    try:
        if source_path.exists() and out_path.resolve() == source_path.resolve():
            stem = source_path.stem
            counter = 2
            while True:
                candidate = folder / f"{stem}_watermark_{counter}{suffix}"
                if candidate.resolve() != source_path.resolve() and not candidate.exists():
                    return candidate
                counter += 1
                if counter > 9999:
                    break
    except OSError:
        pass
    return out_path


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(hi, max(lo, parsed))


def _collect_source_metadata(
    source: Path,
    *,
    keep_exif: bool,
    keep_icc: bool,
) -> tuple[bytes | None, bytes | None]:
    """从原图读取 EXIF / ICC；任一步失败则对应项为 None。"""
    exif_bytes: bytes | None = None
    icc_bytes: bytes | None = None
    if not keep_exif and not keep_icc:
        return None, None
    try:
        with Image.open(source) as src:
            if keep_exif:
                try:
                    exif = src.getexif()
                    if exif:
                        # 渲染前已做方向校正。
                        try:
                            exif[274] = 1
                        except Exception:
                            pass
                        payload = exif.tobytes()
                        if payload:
                            exif_bytes = payload
                except Exception:
                    exif_bytes = None
            if keep_icc:
                try:
                    profile = src.info.get("icc_profile")
                    if isinstance(profile, (bytes, bytearray)) and profile:
                        icc_bytes = bytes(profile)
                except Exception:
                    icc_bytes = None
    except Exception:
        return None, None
    return exif_bytes, icc_bytes


def export_image(source: str | Path, output_dir: str | Path, options: dict[str, Any], quality: int) -> str:
    """按原图重新渲染并按所选格式保存。返回输出路径。"""
    image = render_watermark(source, options)
    policy = str(options.get("conflict_policy", "number") or "number")
    fmt = normalize_export_format(options.get("export_format", "jpg"))
    ext = export_extension(fmt)
    out_path = allocate_output_path(source, output_dir, conflict_policy=policy, ext=ext)

    keep_exif = bool(options.get("keep_exif", True))
    keep_icc = bool(options.get("keep_icc", True))
    exif_bytes, icc_bytes = _collect_source_metadata(
        Path(source),
        keep_exif=keep_exif,
        keep_icc=keep_icc,
    )

    rgb = image.convert("RGB")
    kwargs: dict[str, Any] = {}
    if exif_bytes:
        kwargs["exif"] = exif_bytes
    if icc_bytes:
        kwargs["icc_profile"] = icc_bytes

    if fmt == "jpg":
        q = _clamp_int(quality, 1, 100, 95)
        save_kwargs = {
            "quality": q,
            "optimize": True,
            "progressive": True,
            **kwargs,
        }
        try:
            rgb.save(out_path, "JPEG", **save_kwargs)
        except Exception:
            # 部分格式/Pillow 版本对 EXIF/ICC 组合敏感，降级为仅像素。
            rgb.save(out_path, "JPEG", quality=q, optimize=True, progressive=True)
    elif fmt == "png":
        level = _clamp_int(options.get("png_compress", 6), 0, 9, 6)
        save_kwargs = {"compress_level": level, **kwargs}
        try:
            rgb.save(out_path, "PNG", **save_kwargs)
        except Exception:
            rgb.save(out_path, "PNG", compress_level=level)
    elif fmt == "webp":
        wq = _clamp_int(options.get("webp_quality", 90), 1, 100, 90)
        save_kwargs = {"quality": wq, "method": 4, **kwargs}
        try:
            rgb.save(out_path, "WEBP", **save_kwargs)
        except Exception:
            rgb.save(out_path, "WEBP", quality=wq, method=4)
    else:
        try:
            rgb.save(out_path, "TIFF", **kwargs)
        except Exception:
            rgb.save(out_path, "TIFF")
    return str(out_path)
