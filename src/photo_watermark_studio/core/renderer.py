# -*- coding: utf-8 -*-
"""Pillow 水印合成。算法自 Tkinter 版本原样迁出，不依赖界面库。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.models import PhotoMetadata


def _font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
    size = max(9, int(size))
    candidates = []
    if os.name == "nt":
        if bold and italic:
            candidates += [r"C:\Windows\Fonts\arialbi.ttf", r"C:\Windows\Fonts\segoeuib.ttf"]
        elif bold:
            candidates += [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\msyhbd.ttc"]
        else:
            candidates += [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\msyh.ttc"]
    # Linux fallback for development/testing; Windows uses the system fonts above.
    if bold:
        candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    else:
        candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    candidates += ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
    for fp in candidates:
        try:
            return ImageFont.truetype(fp, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, preferred: int,
              bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
    size = max(9, int(preferred))
    while size > 9:
        f = _font(size, bold, italic)
        box = draw.textbbox((0, 0), text, font=f)
        if box[2] - box[0] <= max_width:
            return f
        size -= 1
    return _font(9, bold, italic)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _load_logo(logo_path: str, max_size: tuple[int, int]) -> Optional[Image.Image]:
    if not logo_path:
        return None
    try:
        with Image.open(logo_path) as logo:
            logo = logo.convert("RGBA")
            logo.thumbnail(max_size, Image.Resampling.LANCZOS)
            return logo.copy()
    except Exception:
        return None


def _color_theme(theme: str) -> dict[str, tuple[int, int, int]]:
    if theme == "深色":
        return {"bar": (20, 27, 38), "text": (246, 248, 252), "muted": (191, 200, 213), "outer": (24, 32, 45)}
    if theme == "蓝色":
        return {"bar": (232, 241, 253), "text": (27, 49, 79), "muted": (80, 103, 134), "outer": (117, 160, 211)}
    if theme == "高斯模糊":
        # 底栏/相框由模糊图填充；色值只作文字配色与回退。
        return {"bar": (28, 30, 34), "text": (250, 251, 252), "muted": (205, 212, 220), "outer": (22, 24, 28)}
    return {"bar": (250, 250, 249), "text": (23, 27, 34), "muted": (96, 103, 114), "outer": (231, 237, 244)}


def _is_frosted_theme(theme: str) -> bool:
    return theme in ("高斯模糊", "高斯模糊+变暗")


def _gaussian_blur(image: Image.Image, radius: float) -> Image.Image:
    """仅做高斯模糊，不变暗。"""
    src = image.convert("RGB")
    return src.filter(ImageFilter.GaussianBlur(radius=max(1.0, float(radius))))


def _frosted_bar(base: Image.Image, bar_h: int) -> Image.Image:
    """用照片底部区域生成高斯模糊底栏背景。"""
    w, h = base.size
    sample_h = min(h, max(bar_h, int(bar_h * 1.8)))
    sample = base.crop((0, h - sample_h, w, h)).resize((w, bar_h), Image.Resampling.LANCZOS)
    return _gaussian_blur(sample, radius=max(10.0, bar_h / 3.2))


def _frosted_frame(base: Image.Image, size: tuple[int, int], radius: float) -> Image.Image:
    """用整图铺满画布后高斯模糊，作为相框外底。"""
    cover = ImageOps.fit(base.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    return _gaussian_blur(cover, radius=radius)


def format_exposure_line(md: PhotoMetadata) -> str:
    detail_parts: list[str] = []
    if md.iso:
        detail_parts.append(f"ISO {md.iso}")
    if md.focal:
        detail_parts.append(md.focal.upper())
    if md.aperture:
        detail_parts.append(md.aperture.upper())
    if md.shutter:
        detail_parts.append(md.shutter.upper())
    return "  |  ".join(detail_parts)


def metadata_placeholders(md: PhotoMetadata) -> dict[str, str]:
    return {
        "camera": md.camera,
        "lens": md.lens,
        "exif": format_exposure_line(md),
        "date": md.date,
        "gps": md.gps,
    }


def _field_scale(options: dict[str, Any], key: str) -> float:
    try:
        value = float(options.get(key, 1.0))
    except (TypeError, ValueError):
        value = 1.0
    return min(1.6, max(0.7, value))


def _override_or_exif(custom: Any, exif_value: str) -> str:
    text = str(custom or "").strip()
    return text if text else str(exif_value or "").strip()


FIELD_LABELS = {
    "camera": "相机型号",
    "lens": "镜头型号",
    "exif": "曝光参数",
    "date": "拍摄时间",
    "gps": "GPS 坐标",
    "brand": "品牌 / 摄影署名",
    "caption": "自定义说明",
}


@dataclass(frozen=True)
class TextSegment:
    text: str
    scale: float
    key: str = ""
    sep_before: str = ""


def _metadata_segment_lines(
    md: PhotoMetadata, options: dict[str, Any]
) -> tuple[list[TextSegment], list[TextSegment], list[TextSegment]]:
    title: list[TextSegment] = []
    if options.get("show_camera"):
        camera = _override_or_exif(options.get("camera_text"), md.camera)
        if camera:
            title.append(TextSegment(camera, _field_scale(options, "camera_scale"), key="camera"))
    if options.get("show_lens"):
        lens = _override_or_exif(options.get("lens_text"), md.lens)
        if lens:
            sep = "  ·  " if title else ""
            title.append(TextSegment(lens, _field_scale(options, "lens_scale"), key="lens", sep_before=sep))

    detail: list[TextSegment] = []
    if options.get("show_exif"):
        custom = str(options.get("exif_text", "") or "").strip()
        exposure = custom if custom else format_exposure_line(md)
        if exposure:
            detail.append(TextSegment(exposure, _field_scale(options, "exif_scale"), key="exif"))

    extra: list[TextSegment] = []
    if options.get("show_date"):
        date = _override_or_exif(options.get("date_text"), md.date)
        if date:
            extra.append(TextSegment(date, _field_scale(options, "date_scale"), key="date"))
    if options.get("show_gps"):
        gps = _override_or_exif(options.get("gps_text"), md.gps)
        if gps:
            sep = "  ·  " if extra else ""
            extra.append(TextSegment(gps, _field_scale(options, "gps_scale"), key="gps", sep_before=sep))
    return title, detail, extra


def _line_plain_text(segments: list[TextSegment]) -> str:
    return "".join(f"{seg.sep_before}{seg.text}" for seg in segments)


def _measure_segments(
    draw: ImageDraw.ImageDraw,
    segments: list[TextSegment],
    texts: list[str],
    fonts: list[ImageFont.ImageFont],
) -> tuple[list[int], int]:
    widths: list[int] = []
    total = 0
    for seg, text, font in zip(segments, texts, fonts):
        if seg.sep_before:
            sep_box = draw.textbbox((0, 0), seg.sep_before, font=font)
            total += sep_box[2] - sep_box[0]
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        widths.append(width)
        total += width
    return widths, total


def _ellipsis_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> tuple[str, int]:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    if width <= max_width or not text:
        return text, width
    low, high = 0, len(text)
    best = "…"
    best_width = draw.textbbox((0, 0), best, font=font)
    best_w = best_width[2] - best_width[0]
    while low <= high:
        mid = (low + high) // 2
        candidate = (text[:mid].rstrip() + "…") if mid > 0 else "…"
        box = draw.textbbox((0, 0), candidate, font=font)
        cand_w = box[2] - box[0]
        if cand_w <= max_width:
            best, best_w = candidate, cand_w
            low = mid + 1
        else:
            high = mid - 1
    return best, best_w


def _fit_segment_fonts(
    draw: ImageDraw.ImageDraw,
    segments: list[TextSegment],
    max_width: int,
    preferred: int,
    bold: bool,
) -> list[tuple[TextSegment, str, ImageFont.ImageFont, int]]:
    """按目标字号适配；过长时先小幅缩小，再省略，避免被压死到固定 9px。"""
    if not segments:
        return []
    targets = [max(9, int(preferred * seg.scale)) for seg in segments]
    # 下限随水印大小变化，这样调大「水印大小」时相机/镜头也会变大。
    floors = [max(9, int(target * 0.55)) for target in targets]
    low, high = 0, max(targets) - min(floors)
    best_sizes = list(floors)
    while low <= high:
        shrink = (low + high) // 2
        trial = [max(floor, target - shrink) for target, floor in zip(targets, floors)]
        fonts = [_font(size, bold) for size in trial]
        texts = [seg.text for seg in segments]
        _widths, total = _measure_segments(draw, segments, texts, fonts)
        if total <= max_width:
            best_sizes = trial
            high = shrink - 1
        else:
            low = shrink + 1
    fonts = [_font(size, bold) for size in best_sizes]
    texts = [seg.text for seg in segments]
    widths, total = _measure_segments(draw, segments, texts, fonts)
    if total > max_width:
        sep_total = 0
        for seg, font in zip(segments, fonts):
            if seg.sep_before:
                sep_box = draw.textbbox((0, 0), seg.sep_before, font=font)
                sep_total += sep_box[2] - sep_box[0]
        budget = max(8 * len(segments), max_width - sep_total)
        weight = sum(widths) or 1
        for idx, (text, font, width) in enumerate(zip(texts, fonts, widths)):
            share = max(8, int(budget * (width / weight)))
            texts[idx], widths[idx] = _ellipsis_text(draw, text, font, share)
        widths, _total = _measure_segments(draw, segments, texts, fonts)
    return [
        (seg, text, font, width)
        for seg, text, font, width in zip(segments, texts, fonts, widths)
    ]


def _append_hit(
    hits: list[dict[str, Any]],
    key: str,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    if not key or width <= 0 or height <= 0:
        return
    hits.append(
        {
            "key": key,
            "label": FIELD_LABELS.get(key, key),
            "text": text,
            "x": float(x),
            "y": float(y),
            "w": float(width),
            "h": float(height),
        }
    )


def _draw_segments(
    draw: ImageDraw.ImageDraw,
    segments: list[TextSegment],
    y: int,
    max_width: int,
    preferred: int,
    fill: tuple[int, ...],
    bold: bool,
    *,
    align: str,
    anchor_x: int,
    hits: list[dict[str, Any]] | None = None,
) -> int:
    """Draw a segmented line. Returns the tallest font size used."""
    fitted = _fit_segment_fonts(draw, segments, max_width, preferred, bold)
    if not fitted:
        return 0
    pieces: list[tuple[str, ImageFont.ImageFont, int, str]] = []
    total = 0
    for seg, text, font, text_width in fitted:
        if seg.sep_before:
            sep_box = draw.textbbox((0, 0), seg.sep_before, font=font)
            sep_width = sep_box[2] - sep_box[0]
            pieces.append((seg.sep_before, font, sep_width, ""))
            total += sep_width
        pieces.append((text, font, text_width, seg.key))
        total += text_width
    if align == "right":
        x = float(anchor_x - total)
    elif align == "center":
        x = float(anchor_x - total / 2)
    else:
        x = float(anchor_x)
    tallest = 9
    for text, font, width, key in pieces:
        draw.text((x, y), text, font=font, fill=fill)
        font_size = int(getattr(font, "size", 9) or 9)
        tallest = max(tallest, font_size)
        if hits is not None and key:
            _append_hit(hits, key, text, x, float(y), float(width), float(font_size + 4))
        x += width
    return tallest


def _metadata_lines(md: PhotoMetadata, options: dict[str, Any]) -> tuple[str, str, str]:
    title_segs, detail_segs, extra_segs = _metadata_segment_lines(md, options)
    return _line_plain_text(title_segs), _line_plain_text(detail_segs), _line_plain_text(extra_segs)


def render_watermark(source_path: str | Path, options: dict[str, Any]) -> Image.Image:
    """Render the image with watermark and return an RGB image."""
    image, _hits = render_watermark_with_hits(source_path, options)
    return image


def render_watermark_with_hits(
    source_path: str | Path, options: dict[str, Any]
) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Render watermark and return clickable text regions in image coordinates."""
    with Image.open(source_path) as src:
        base = ImageOps.exif_transpose(src).convert("RGB")
        original_exif = src.getexif()
    del original_exif
    w, h = base.size
    theme_name = str(options.get("theme", "浅色"))
    theme = _color_theme(theme_name)
    frosted = _is_frosted_theme(theme_name)
    style = str(options.get("style", "经典底栏"))
    scale_setting = max(0.65, min(1.6, float(options.get("scale", 1.0))))
    md = read_photo_metadata(source_path)
    brand = str(options.get("brand", "")).strip()
    caption = str(options.get("caption", "")).strip()
    title_segs, detail_segs, extra_segs = _metadata_segment_lines(md, options)
    if caption:
        sep = "  ·  " if extra_segs else ""
        extra_segs = list(extra_segs) + [
            TextSegment(
                caption,
                _field_scale(options, "date_scale") if extra_segs else 1.0,
                key="caption",
                sep_before=sep,
            )
        ]
    line_groups = [group for group in (title_segs, detail_segs, extra_segs) if group]
    if not line_groups:
        line_groups = [[TextSegment("EXIF 参数暂缺，可添加自定义说明", 1.0)]]

    logo = _load_logo(str(options.get("logo_path", "")), (max(40, int(w * 0.19)), max(28, int(w * 0.055))))
    base = base.convert("RGB")
    hits: list[dict[str, Any]] = []

    if style == "极简叠加":
        rgba = base.convert("RGBA")
        # 底栏高度随「水印大小」变化，相机/镜头等字号才能一起变大。
        band_h = max(74, int(w * 0.092 * scale_setting))
        if frosted:
            rgba.paste(_frosted_bar(base, band_h), (0, h - band_h))
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        if not frosted:
            d.rectangle((0, h - band_h, w, h), fill=(7, 12, 20, 172))
        margin = max(20, int(w * 0.033))
        left_cap = int(w * 0.42)
        text_primary = (255, 255, 255, 255)
        text_muted = (211, 219, 230, 255)
        left_occupied = float(margin)
        if logo is not None:
            thumb = logo.copy()
            max_h = int(band_h * 0.64)
            if thumb.height > max_h:
                ratio = max_h / thumb.height
                thumb = thumb.resize((max(1, int(thumb.width * ratio)), max_h), Image.Resampling.LANCZOS)
            overlay.paste(thumb, (margin, h - band_h + (band_h - thumb.height) // 2), thumb)
            left_occupied = float(margin + thumb.width)
            if brand and options.get("show_brand_text", False):
                logo_gap = max(18, int(w * 0.012))
                small = _fit_font(d, brand, max(50, left_cap - thumb.width - logo_gap), int(band_h * 0.28), True, True)
                bx = margin + thumb.width + logo_gap
                by = h - band_h + (band_h - small.size) // 2
                d.text((bx, by), brand, font=small, fill=text_primary)
                bb = d.textbbox((bx, by), brand, font=small)
                _append_hit(hits, "brand", brand, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1])
                left_occupied = float(bb[2])
        elif brand:
            fbrand = _fit_font(d, brand, left_cap, int(band_h * 0.54), True, True)
            bx = float(margin)
            by = float(h - band_h + int(band_h * 0.14))
            d.text((bx, by), brand, font=fbrand, fill=text_primary)
            bb = d.textbbox((bx, by), brand, font=fbrand)
            _append_hit(hits, "brand", brand, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1])
            left_occupied = float(bb[2])

        right_x = w - margin
        gap = max(16, int(w * 0.02))
        max_right = max(48, int(right_x - left_occupied - gap))
        line_heights = [int(band_h * (0.31 if idx == 0 else 0.22)) for idx in range(len(line_groups))]
        total_h = sum(line_heights) + max(0, len(line_groups) - 1) * 1
        y = h - band_h + max(3, (band_h - total_h) // 2)
        for idx, segments in enumerate(line_groups[:3]):
            pref = int(band_h * (0.32 if idx == 0 else 0.21))
            _draw_segments(
                d,
                segments,
                y,
                max_right,
                pref,
                text_primary if idx == 0 else text_muted,
                idx == 0,
                align="right",
                anchor_x=right_x,
                hits=hits,
            )
            y += line_heights[idx] + 1
        return Image.alpha_composite(rgba, overlay).convert("RGB"), hits

    if style == "卡片相框":
        pad = max(22, int(min(w, h) * 0.052))
        footer_h = max(90, int(min(w, h) * 0.16 * scale_setting))
        out_w = w + 2 * pad
        out_h = h + 2 * pad + footer_h
        bg = theme["outer"]
        if frosted:
            canvas = _frosted_frame(base, (out_w, out_h), radius=max(16.0, pad * 1.4))
        else:
            canvas = Image.new("RGB", (out_w, out_h), bg)
        shadow = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((pad + 2, pad + 7, pad + w + 2, pad + h + 7),
                             radius=max(12, int(min(w, h) * .018)), fill=(16, 28, 45, 70))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(6, int(pad * .22))))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")
        mask = _rounded_mask((w, h), max(12, int(min(w, h) * .018)))
        canvas.paste(base, (pad, pad), mask)
        d = ImageDraw.Draw(canvas)
        cy = pad + h + max(14, int(footer_h * .10))
        center_x = out_w // 2
        if logo is not None:
            lx = center_x - logo.width // 2
            canvas.paste(logo, (lx, cy), logo)
            cy += logo.height + max(2, int(footer_h * .03))
            d = ImageDraw.Draw(canvas)
        elif brand:
            fbrand = _fit_font(d, brand, out_w - pad * 2, int(min(w, h) * .042 * scale_setting), True, True)
            bb = d.textbbox((0, 0), brand, font=fbrand)
            bx = center_x - (bb[2] - bb[0]) / 2
            d.text((bx, cy), brand, font=fbrand, fill=theme["text"])
            hit = d.textbbox((bx, cy), brand, font=fbrand)
            _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
            cy += int(fbrand.size * 1.18)
        for idx, segments in enumerate(line_groups[:3]):
            preferred = int(min(w, h) * (.022 if idx == 0 else .016) * scale_setting)
            tallest = _draw_segments(
                d,
                segments,
                cy,
                out_w - pad * 2,
                preferred,
                theme["text"] if idx == 0 else theme["muted"],
                idx == 0,
                align="center",
                anchor_x=center_x,
                hits=hits,
            )
            cy += int(max(tallest, preferred) * 1.32)
        return canvas, hits

    bar_h = max(74, int(w * .092 * scale_setting))
    if frosted:
        canvas = Image.new("RGB", (w, h + bar_h))
        canvas.paste(base, (0, 0))
        canvas.paste(_frosted_bar(base, bar_h), (0, h))
    else:
        canvas = Image.new("RGB", (w, h + bar_h), theme["bar"])
        canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas)
    margin = max(20, int(w * .033))
    left_cap = int(w * .42)
    left_occupied = float(margin)
    if logo is not None:
        thumb = logo.copy()
        max_h = int(bar_h * .64)
        if thumb.height > max_h:
            ratio = max_h / thumb.height
            thumb = thumb.resize((max(1, int(thumb.width * ratio)), max_h), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (margin, h + (bar_h - thumb.height) // 2), thumb)
        left_occupied = float(margin + thumb.width)
        if brand and options.get("show_brand_text", False):
            logo_gap = max(18, int(w * 0.012))
            small = _fit_font(d, brand, max(50, left_cap - thumb.width - logo_gap), int(bar_h * .28), True, True)
            bx = margin + thumb.width + logo_gap
            by = h + (bar_h - small.size) // 2
            d.text((bx, by), brand, font=small, fill=theme["text"])
            hit = d.textbbox((bx, by), brand, font=small)
            _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
            left_occupied = float(hit[2])
    elif brand:
        fbrand = _fit_font(d, brand, left_cap, int(bar_h * .54), True, True)
        bx = float(margin)
        by = float(h + int(bar_h * .14))
        d.text((bx, by), brand, font=fbrand, fill=theme["text"])
        hit = d.textbbox((bx, by), brand, font=fbrand)
        _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
        left_occupied = float(hit[2])

    right_x = w - margin
    gap = max(16, int(w * 0.02))
    max_right = max(48, int(right_x - left_occupied - gap))
    line_heights = [int(bar_h * (0.31 if idx == 0 else 0.22)) for idx in range(len(line_groups))]
    total_h = sum(line_heights) + max(0, len(line_groups) - 1) * 1
    y = h + max(3, (bar_h - total_h) // 2)
    for idx, segments in enumerate(line_groups[:3]):
        pref = int(bar_h * (0.32 if idx == 0 else 0.21))
        _draw_segments(
            d,
            segments,
            y,
            max_right,
            pref,
            theme["text"] if idx == 0 else theme["muted"],
            idx == 0,
            align="right",
            anchor_x=right_x,
            hits=hits,
        )
        y += line_heights[idx] + 1
    return canvas, hits
