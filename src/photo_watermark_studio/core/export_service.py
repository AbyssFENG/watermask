# -*- coding: utf-8 -*-
"""导出路径、JPEG 质量和原图保护。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from photo_watermark_studio.core.renderer import render_watermark


def allocate_output_path(
    source: str | Path,
    output_dir: str | Path,
    conflict_policy: str = "number",
) -> Path:
    """选择导出文件名。默认 `原名_watermark.jpg`，不覆盖原图。

    conflict_policy=number：目标已存在时追加 `_2`、`_3`。
    conflict_policy=overwrite：允许覆盖已有水印文件，仍不会写回原文件名。
    """
    source_path = Path(source)
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / f"{source_path.stem}_watermark.jpg"
    policy = str(conflict_policy or "number")
    if out_path.exists() and policy != "overwrite":
        stem = source_path.stem
        counter = 2
        while (folder / f"{stem}_watermark_{counter}.jpg").exists():
            counter += 1
        out_path = folder / f"{stem}_watermark_{counter}.jpg"
    try:
        if source_path.exists() and out_path.resolve() == source_path.resolve():
            stem = source_path.stem
            counter = 2
            while True:
                candidate = folder / f"{stem}_watermark_{counter}.jpg"
                if candidate.resolve() != source_path.resolve() and not candidate.exists():
                    return candidate
                counter += 1
                if counter > 9999:
                    break
    except OSError:
        pass
    return out_path


def export_image(source: str | Path, output_dir: str | Path, options: dict[str, Any], quality: int) -> str:
    """按原图重新渲染并保存 JPEG。返回输出路径。"""
    image = render_watermark(source, options)
    policy = str(options.get("conflict_policy", "number") or "number")
    out_path = allocate_output_path(source, output_dir, conflict_policy=policy)
    try:
        q = int(quality)
    except (TypeError, ValueError):
        q = 95
    q = min(100, max(1, q))
    kwargs: dict[str, Any] = {"quality": q, "optimize": True, "progressive": True}
    try:
        with Image.open(source) as src:
            exif = src.getexif()
            if exif:
                # The image has already been orientation-corrected before drawing.
                try:
                    exif[274] = 1
                    kwargs["exif"] = exif.tobytes()
                except Exception:
                    pass
    except Exception:
        pass
    image.convert("RGB").save(out_path, "JPEG", **kwargs)
    return str(out_path)
