# -*- coding: utf-8 -*-
"""Pillow 水印合成。算法自 Tkinter 版本原样迁出，不依赖界面库。"""
from __future__ import annotations

import math
import os
import re
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from photo_watermark_studio.core.font_presets import (
    DEFAULT_FONT_FAMILY,
    coerce_font_family,
    font_covers_cjk,
    resolve_font_path,
)
from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.models import PhotoMetadata
from photo_watermark_studio.core.settings_store import (
    DEFAULT_FIELD_BOLD,
    coerce_field_opacity,
    coerce_hex_color,
    default_field_positions,
    effective_style,
    is_custom_style,
)
from photo_watermark_studio.paths import resource_dir


def _needs_cjk(text: str) -> bool:
    """文案含中日韩字符时需选用支持 CJK 的字体，否则会显示为方框。"""
    for ch in text or "":
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xF900 <= code <= 0xFAFF
            or 0x3000 <= code <= 0x303F
            or 0xFF00 <= code <= 0xFFEF
        ):
            return True
    return False


def _font_candidate_paths(
    bold: bool,
    italic: bool,
    cjk: bool,
    font_family: str,
) -> tuple[str, ...]:
    candidates: list[str] = []
    preferred = resolve_font_path(font_family)
    # 英文衬线没有中文字形，含中文时改走后面的雅黑，避免方框。
    if preferred and (not cjk or font_covers_cjk(font_family)):
        candidates.append(preferred)
    if os.name == "nt":
        cjk_regular = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
        cjk_bold = [
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
        if cjk:
            candidates += cjk_bold if bold else cjk_regular
        # 英文加粗优先 SemiBold，避免 Arial Bold 过重。
        if bold and italic:
            candidates += [
                r"C:\Windows\Fonts\seguisbi.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\arialbi.ttf",
            ]
        elif bold:
            candidates += [
                r"C:\Windows\Fonts\seguisb.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
            ]
        else:
            candidates += [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]
        # 非中文路径也把雅黑放后面作兜底，避免偶发特殊符号缺字。
        if not cjk:
            candidates += cjk_bold if bold else cjk_regular
    # Linux / 跨平台兜底
    if bold:
        candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
    else:
        candidates += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    candidates += [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    return tuple(candidates)


def _tune_font(font: ImageFont.FreeTypeFont, bold: bool) -> ImageFont.FreeTypeFont:
    """可变字体默认常常是极细字重，水印改用 Regular，加粗时用 Bold。"""
    try:
        raw_names = font.get_variation_names()
    except Exception:
        return font
    names: list[str] = []
    for item in raw_names:
        if isinstance(item, bytes):
            names.append(item.decode("utf-8", "replace"))
        else:
            names.append(str(item))
    target = "Bold" if bold and "Bold" in names else ("Regular" if "Regular" in names else "")
    if not target:
        return font
    try:
        font.set_variation_by_name(target)
    except Exception:
        return font
    return font


@lru_cache(maxsize=48)
def _resolved_font_path(font_family: str, bold: bool, italic: bool, cjk: bool) -> str:
    """候选字体只探测一次，之后按路径复用。"""
    for fp in _font_candidate_paths(bold, italic, cjk, font_family):
        try:
            ImageFont.truetype(fp, size=9)
            return fp
        except Exception:
            continue
    return ""


_font_lock = threading.Lock()
_font_cache: dict[tuple[str, int, bool], ImageFont.ImageFont] = {}
_FONT_CACHE_LIMIT = 96


def _font(
    size: int,
    bold: bool = False,
    italic: bool = False,
    text: str = "",
    font_family: str = DEFAULT_FONT_FAMILY,
) -> ImageFont.ImageFont:
    size = max(9, int(size))
    family = coerce_font_family(font_family)
    path = _resolved_font_path(family, bool(bold), bool(italic), _needs_cjk(text))
    if not path:
        return ImageFont.load_default()
    key = (path, size, bool(bold))
    with _font_lock:
        cached = _font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = _tune_font(ImageFont.truetype(path, size=size), bool(bold))
        except Exception:
            return ImageFont.load_default()
        _font_cache[key] = font
        if len(_font_cache) > _FONT_CACHE_LIMIT:
            _font_cache.pop(next(iter(_font_cache)))
        return font


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    preferred: int,
    bold: bool = False,
    italic: bool = False,
    font_family: str = DEFAULT_FONT_FAMILY,
) -> ImageFont.ImageFont:
    preferred = max(9, int(preferred))

    def measure(size: int) -> tuple[ImageFont.ImageFont, int]:
        font = _font(size, bold, italic, text=text, font_family=font_family)
        box = draw.textbbox((0, 0), text, font=font)
        return font, box[2] - box[0]

    font, width = measure(preferred)
    if width <= max_width or preferred <= 9:
        return font
    low, high = 9, preferred - 1
    best: ImageFont.ImageFont | None = None
    while low <= high:
        mid = (low + high) // 2
        trial, trial_width = measure(mid)
        if trial_width <= max_width:
            best = trial
            low = mid + 1
        else:
            high = mid - 1
    if best is not None:
        return best
    return _font(9, bold, italic, text=text, font_family=font_family)


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


def _logo_badge(mark: str, diameter: int, color: tuple[int, int, int]) -> Image.Image:
    """无 Logo 文件时的圆形徽记，先放大绘制再缩小以抗锯齿。"""
    diameter = max(12, int(diameter))
    ss = 4
    size = diameter * ss
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    rgba = (*color[:3], 255)
    stroke = max(ss, int(size * 0.06))
    d.ellipse((stroke // 2, stroke // 2, size - 1 - stroke // 2, size - 1 - stroke // 2), outline=rgba, width=stroke)
    c = size / 2
    if mark == "◉":
        r = size * 0.2
        d.ellipse((c - r, c - r, c + r, c + r), fill=rgba)
    elif mark == "✦":
        outer, inner = size * 0.3, size * 0.075
        points = []
        for i in range(8):
            angle = math.pi / 4 * i - math.pi / 2
            radius = outer if i % 2 == 0 else inner
            points.append((c + radius * math.cos(angle), c + radius * math.sin(angle)))
        d.polygon(points, fill=rgba)
    else:
        font = _font(int(size * 0.5), True, text=mark or "L")
        box = d.textbbox((0, 0), mark or "L", font=font)
        tx = c - (box[0] + box[2]) / 2
        ty = c - (box[1] + box[3]) / 2
        d.text((tx, ty), mark or "L", font=font, fill=rgba)
    return badge.resize((diameter, diameter), Image.Resampling.LANCZOS)


def _with_opacity(image: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return image
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda v: int(round(v * opacity)))
    rgba.putalpha(alpha)
    return rgba


def _logo_scale(options: dict[str, Any]) -> float:
    try:
        return min(1.9, max(0.5, float(options.get("logo_scale", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _logo_opacity(options: dict[str, Any]) -> float:
    try:
        return min(1.0, max(0.2, float(options.get("logo_opacity", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _fit_logo(logo: Image.Image, max_h: float) -> Image.Image:
    thumb = logo.copy()
    max_h = max(1, int(max_h))
    if thumb.height > max_h:
        ratio = max_h / thumb.height
        thumb = thumb.resize((max(1, int(thumb.width * ratio)), max_h), Image.Resampling.LANCZOS)
    return thumb


def _card_radius(options: dict[str, Any], ref: int) -> int:
    """卡片照片圆角：0 表示默认圆角，其余按 760px 预览宽度等比换算。"""
    try:
        radius = float(options.get("corner_radius", 0) or 0)
    except (TypeError, ValueError):
        radius = 0.0
    if radius <= 0:
        return max(12, int(ref * 0.018))
    return max(1, int(round(ref * radius / 600)))


def _parse_hex_rgb(raw: Any) -> tuple[int, int, int] | None:
    color = coerce_hex_color(raw)
    if not color:
        return None
    body = color[1:]
    return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)


def _color_theme(theme: str, bg_color: Any = "") -> dict[str, tuple[int, int, int]]:
    if theme == "高斯模糊":
        # 底栏/相框由模糊图填充；色值只作文字配色与回退。
        return {"bar": (28, 30, 34), "text": (250, 251, 252), "muted": (205, 212, 220), "outer": (22, 24, 28)}
    rgb = _parse_hex_rgb(bg_color)
    if rgb is not None:
        r, g, b = rgb
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        if luma < 140:
            return {"bar": rgb, "text": (246, 248, 252), "muted": (191, 200, 213), "outer": rgb}
        return {"bar": rgb, "text": (23, 27, 34), "muted": (96, 103, 114), "outer": rgb}
    if theme in {"黑色", "深色"}:
        return {"bar": (12, 12, 14), "text": (246, 248, 252), "muted": (191, 200, 213), "outer": (8, 8, 10)}
    return {"bar": (255, 255, 255), "text": (23, 27, 34), "muted": (96, 103, 114), "outer": (255, 255, 255)}


def _shadow_params(options: dict[str, Any], frame: int) -> tuple[int, int]:
    """返回卡片阴影 (alpha, blur_radius)。strength=25 与旧固定值完全一致。"""
    try:
        strength = int(round(float(options.get("shadow_strength", 25))))
    except (TypeError, ValueError):
        strength = 25
    strength = max(0, min(100, strength))
    if strength <= 0:
        return 0, 0
    if strength == 25:
        return 70, max(6, int(frame * 0.22))
    scale = strength / 25.0
    alpha = max(1, min(190, int(round(70 * scale))))
    blur_scale = 0.65 + 0.35 * scale
    blur = max(3, int(round(max(6, int(frame * 0.22)) * blur_scale)))
    return alpha, blur


def _paste_card_shadow(
    canvas: Image.Image,
    out_size: tuple[int, int],
    box: tuple[int, int, int, int],
    radius: int,
    options: dict[str, Any],
    frame: int,
) -> Image.Image:
    alpha, blur = _shadow_params(options, frame)
    if alpha <= 0:
        return canvas
    shadow = Image.new("RGBA", out_size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(box, radius=radius, fill=(16, 28, 45, alpha))
    shadow = _scaled_blur(shadow, blur)
    return Image.alpha_composite(canvas.convert("RGBA"), shadow).convert("RGB")


def _is_frosted_theme(theme: str) -> bool:
    return theme in ("高斯模糊", "高斯模糊+变暗")


def _scaled_blur(image: Image.Image, radius: float) -> Image.Image:
    """大半径时先缩小再模糊，再拉回原尺寸。小图仍直接模糊，避免色带被压糊。"""
    radius = max(1.0, float(radius))
    if radius < 8.0 or max(image.size) < 640:
        return image.filter(ImageFilter.GaussianBlur(radius=radius))
    factor = 8 if radius >= 32.0 else 4
    width, height = image.size
    small_w = max(1, width // factor)
    small_h = max(1, height // factor)
    if small_w < 16 or small_h < 16:
        return image.filter(ImageFilter.GaussianBlur(radius=radius))
    small = image.resize((small_w, small_h), Image.Resampling.BILINEAR)
    blurred = small.filter(ImageFilter.GaussianBlur(radius=max(1.0, radius / factor)))
    return blurred.resize((width, height), Image.Resampling.BILINEAR)


def _gaussian_blur(image: Image.Image, radius: float) -> Image.Image:
    """仅做高斯模糊，不变暗。"""
    return _scaled_blur(image.convert("RGB"), radius)


def _frosted_bar(base: Image.Image, bar_h: int) -> Image.Image:
    """经典底栏：条在照片下方，从底边取样模糊作为页脚底色。"""
    w, h = base.size
    sample_h = min(h, max(bar_h, int(bar_h * 1.8)))
    sample = base.crop((0, h - sample_h, w, h)).resize((w, bar_h), Image.Resampling.LANCZOS)
    return _gaussian_blur(sample, radius=max(10.0, bar_h / 3.2))


def _frosted_overlay_strip(
    base: Image.Image,
    top: int,
    height: int,
    radius: float | None = None,
) -> Image.Image:
    """极简叠加：对底栏正下方原图像素 1:1 取样再模糊，形成磨砂玻璃，不缩放错位。"""
    w, h = base.size
    band_h = max(1, int(height))
    band_top = max(0, min(h - band_h, int(top)))
    blur_r = max(8.0, float(radius) if radius is not None else band_h / 3.2)
    # 上下多取一圈再模糊，避免边缘发硬；内容仍与原图对齐，不做 resize。
    pad = max(8, int(round(blur_r * 2)))
    sample_top = max(0, band_top - pad)
    sample_bottom = min(h, band_top + band_h + pad)
    sample = base.crop((0, sample_top, w, sample_bottom)).convert("RGB")
    blurred = _gaussian_blur(sample, radius=blur_r)
    crop_y0 = band_top - sample_top
    return blurred.crop((0, crop_y0, w, crop_y0 + band_h))


def _frosted_frame(base: Image.Image, size: tuple[int, int], radius: float) -> Image.Image:
    """用整图铺满画布后高斯模糊，作为相框外底。"""
    cover = ImageOps.fit(base.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    return _gaussian_blur(cover, radius=radius)


def format_exposure_line(md: PhotoMetadata) -> str:
    return compose_exposure_line(
        focal=md.focal,
        aperture=md.aperture,
        shutter=md.shutter,
        iso=md.iso,
    )


def compose_exposure_line(
    *,
    focal: str = "",
    aperture: str = "",
    shutter: str = "",
    iso: str = "",
) -> str:
    """把四格曝光拼成与 format_exposure_line 一致的字符串：ISO  |  焦距  |  光圈  |  快门。"""
    detail_parts: list[str] = []
    iso_clean = str(iso or "").strip()
    if iso_clean:
        iso_upper = iso_clean.upper()
        if iso_upper.startswith("ISO"):
            iso_num = iso_clean[3:].strip()
            detail_parts.append(f"ISO {iso_num}" if iso_num else "ISO")
        else:
            detail_parts.append(f"ISO {iso_clean}")
    for raw in (focal, aperture, shutter):
        text = str(raw or "").strip()
        if text:
            detail_parts.append(text.upper())
    return "  |  ".join(detail_parts)


def parse_exposure_line(text: str) -> dict[str, str]:
    """把曝光参数字符串拆回 focal / aperture / shutter / iso 四项。"""
    out = {"focal": "", "aperture": "", "shutter": "", "iso": ""}
    raw = str(text or "").strip()
    if not raw:
        return out
    tokens = [part.strip() for part in re.split(r"\s*[|·]\s*", raw) if part.strip()]
    leftovers: list[str] = []
    for token in tokens:
        upper = token.upper()
        if upper.startswith("ISO"):
            val = token[3:].strip()
            out["iso"] = val or token
        elif upper.endswith("MM") and not out["focal"]:
            out["focal"] = token
        elif (upper.startswith("F/") or upper.startswith("F")) and any(ch.isdigit() for ch in upper) and not out["aperture"] and "/" in upper and not upper.endswith("S"):
            out["aperture"] = token
        elif (upper.endswith("S") or "/" in upper) and any(ch.isdigit() for ch in upper) and not out["shutter"]:
            out["shutter"] = token
        elif upper.startswith("F") and any(ch.isdigit() for ch in upper) and not out["aperture"]:
            out["aperture"] = token
        else:
            leftovers.append(token)
    for key in ("focal", "aperture", "shutter", "iso"):
        if not out[key] and leftovers:
            out[key] = leftovers.pop(0)
    return out


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


def _field_font(options: dict[str, Any], key: str) -> str:
    return coerce_font_family(options.get(key, DEFAULT_FONT_FAMILY))


def _field_bold(options: dict[str, Any], field: str) -> bool:
    bold_key = f"{field}_bold"
    if bold_key in options:
        return bool(options.get(bold_key))
    return bool(DEFAULT_FIELD_BOLD.get(field, False))


def _field_italic(options: dict[str, Any], field: str) -> bool:
    return bool(options.get(f"{field}_italic", False))


def _field_opacity(options: dict[str, Any], field: str) -> float:
    return coerce_field_opacity(options.get(f"{field}_opacity", 1.0), 1.0)


def _apply_fill_opacity(fill: tuple[int, ...], opacity: float) -> tuple[int, int, int, int]:
    opacity = coerce_field_opacity(opacity, 1.0)
    if len(fill) >= 4:
        r, g, b, a = int(fill[0]), int(fill[1]), int(fill[2]), int(fill[3])
    else:
        r, g, b, a = int(fill[0]), int(fill[1]), int(fill[2]), 255
    return (r, g, b, max(0, min(255, int(round(a * opacity)))))


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
    font_family: str = DEFAULT_FONT_FAMILY
    bold: bool = False
    italic: bool = False
    opacity: float = 1.0


def _metadata_segment_lines(
    md: PhotoMetadata, options: dict[str, Any]
) -> tuple[list[TextSegment], list[TextSegment], list[TextSegment]]:
    title: list[TextSegment] = []
    if options.get("show_camera"):
        camera = _override_or_exif(options.get("camera_text"), md.camera)
        if camera:
            title.append(
                TextSegment(
                    camera,
                    _field_scale(options, "camera_scale"),
                    key="camera",
                    font_family=_field_font(options, "camera_font"),
                    bold=_field_bold(options, "camera"),
                    italic=_field_italic(options, "camera"),
                    opacity=_field_opacity(options, "camera"),
                )
            )
    if options.get("show_lens"):
        lens = _override_or_exif(options.get("lens_text"), md.lens)
        if lens:
            sep = "  ·  " if title else ""
            title.append(
                TextSegment(
                    lens,
                    _field_scale(options, "lens_scale"),
                    key="lens",
                    sep_before=sep,
                    font_family=_field_font(options, "lens_font"),
                    bold=_field_bold(options, "lens"),
                    italic=_field_italic(options, "lens"),
                    opacity=_field_opacity(options, "lens"),
                )
            )

    detail: list[TextSegment] = []
    if options.get("show_exif"):
        custom = str(options.get("exif_text", "") or "").strip()
        exposure = custom if custom else format_exposure_line(md)
        if exposure:
            detail.append(
                TextSegment(
                    exposure,
                    _field_scale(options, "exif_scale"),
                    key="exif",
                    font_family=_field_font(options, "exif_font"),
                    bold=_field_bold(options, "exif"),
                    italic=_field_italic(options, "exif"),
                    opacity=_field_opacity(options, "exif"),
                )
            )

    extra: list[TextSegment] = []
    if options.get("show_date"):
        date = _override_or_exif(options.get("date_text"), md.date)
        if date:
            extra.append(
                TextSegment(
                    date,
                    _field_scale(options, "date_scale"),
                    key="date",
                    font_family=_field_font(options, "date_font"),
                    bold=_field_bold(options, "date"),
                    italic=_field_italic(options, "date"),
                    opacity=_field_opacity(options, "date"),
                )
            )
    if options.get("show_gps"):
        gps = _override_or_exif(options.get("gps_text"), md.gps)
        if gps:
            sep = "  ·  " if extra else ""
            extra.append(
                TextSegment(
                    gps,
                    _field_scale(options, "gps_scale"),
                    key="gps",
                    sep_before=sep,
                    font_family=_field_font(options, "gps_font"),
                    bold=_field_bold(options, "gps"),
                    italic=_field_italic(options, "gps"),
                    opacity=_field_opacity(options, "gps"),
                )
            )
    return title, detail, extra


def _line_plain_text(segments: list[TextSegment]) -> str:
    return "".join(f"{seg.sep_before}{seg.text}" for seg in segments)


_DOT_SEP = "·"
_dot_support: dict[int, bool] = {}


def _mask_bytes(mask: Any) -> bytes:
    raw = getattr(mask, "tobytes", None)
    if callable(raw):
        try:
            return raw()
        except Exception:
            pass
    return bytes(mask)


def _font_has_dot(font: ImageFont.ImageFont) -> bool:
    """当前字体是否真有间隔点。缺字时 getmask 与 .notdef 相同，会画成空心方框。"""
    key = id(font)
    cached = _dot_support.get(key)
    if cached is not None:
        return cached
    try:
        wanted = font.getmask(_DOT_SEP)
        missing = font.getmask("\ue000")
        has = _mask_bytes(wanted) != _mask_bytes(missing)
    except Exception:
        has = False
    if len(_dot_support) > 128:
        _dot_support.pop(next(iter(_dot_support)))
    _dot_support[key] = has
    return has


def _is_dot_separator(sep: str) -> bool:
    return sep.strip() == _DOT_SEP


def _dot_diameter(font: ImageFont.ImageFont) -> int:
    size = max(9, int(getattr(font, "size", 16) or 16))
    return max(2, int(round(size * 0.18)))


def _needs_drawn_dot(sep: str, font: ImageFont.ImageFont) -> bool:
    return bool(sep) and _is_dot_separator(sep) and not _font_has_dot(font)


def _separator_width(draw: ImageDraw.ImageDraw, sep: str, font: ImageFont.ImageFont) -> int:
    """间隔宽度。字体没有间隔点时按两侧空格加实心圆计算，避免用缺字方框的宽度。"""
    if _needs_drawn_dot(sep, font):
        space = draw.textbbox((0, 0), "  ", font=font)
        gap = max(2, space[2] - space[0])
        return gap + _dot_diameter(font) + gap
    box = draw.textbbox((0, 0), sep, font=font)
    return box[2] - box[0]


def _blit_dot_separator(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, ...],
    *,
    outline: bool,
) -> None:
    """在大写字母中线画实心圆，左右留白与两个空格一致。"""
    rgba = fill if len(fill) == 4 else (*fill[:3], 255)
    dot = _dot_diameter(font)
    cap = draw.textbbox((0, 0), "H", font=font)
    cy = float(y) + (cap[1] + cap[3]) / 2.0
    cx = float(x) + width / 2.0
    radius = dot / 2.0
    ring = max(1, int(round(dot * 0.35))) if outline else 0
    pad = ring + 2
    left = int(math.floor(cx - radius - pad))
    top = int(math.floor(cy - radius - pad))
    right = int(math.ceil(cx + radius + pad))
    bottom = int(math.ceil(cy + radius + pad))
    sprite = Image.new("RGBA", (max(1, right - left), max(1, bottom - top)), (0, 0, 0, 0))
    sprite_draw = ImageDraw.Draw(sprite)
    local_x = cx - left
    local_y = cy - top
    box = (local_x - radius, local_y - radius, local_x + radius, local_y + radius)
    if ring:
        sprite_draw.ellipse(
            (box[0] - ring, box[1] - ring, box[2] + ring, box[3] + ring),
            fill=(0, 0, 0, min(160, rgba[3])),
        )
    sprite_draw.ellipse(box, fill=rgba)
    image.paste(sprite, (left, top), sprite)


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
            total += _separator_width(draw, seg.sep_before, font)
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
) -> list[tuple[TextSegment, str, ImageFont.ImageFont, int]]:
    """按目标字号适配；过长时先小幅缩小，再省略，避免被压死到固定 9px。"""
    if not segments:
        return []
    targets = [max(9, int(preferred * seg.scale)) for seg in segments]
    # 下限随水印大小变化，这样调大「水印大小」时相机/镜头也会变大。
    floors = [max(9, int(target * 0.55)) for target in targets]
    families = [coerce_font_family(seg.font_family) for seg in segments]
    bolds = [bool(seg.bold) for seg in segments]
    low, high = 0, max(targets) - min(floors)
    best_sizes = list(floors)
    while low <= high:
        shrink = (low + high) // 2
        trial = [max(floor, target - shrink) for target, floor in zip(targets, floors)]
        texts = [seg.text for seg in segments]
        fonts = [
            _font(size, bold, text=text, font_family=family)
            for size, text, family, bold in zip(trial, texts, families, bolds)
        ]
        _widths, total = _measure_segments(draw, segments, texts, fonts)
        if total <= max_width:
            best_sizes = trial
            high = shrink - 1
        else:
            low = shrink + 1
    texts = [seg.text for seg in segments]
    fonts = [
        _font(size, bold, text=text, font_family=family)
        for size, text, family, bold in zip(best_sizes, texts, families, bolds)
    ]
    widths, total = _measure_segments(draw, segments, texts, fonts)
    if total > max_width:
        sep_total = 0
        for seg, font in zip(segments, fonts):
            if seg.sep_before:
                sep_total += _separator_width(draw, seg.sep_before, font)
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


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, ...],
    outline: tuple[int, ...] = (0, 0, 0, 160),
    stroke: int = 1,
) -> None:
    """1px 描边，无色块底，保证浅色图上也看得清。"""
    if stroke > 0:
        draw.text(
            xy,
            text,
            font=font,
            fill=fill,
            stroke_width=int(stroke),
            stroke_fill=outline,
        )
        return
    draw.text(xy, text, font=font, fill=fill)


_ITALIC_SHEAR = 0.32


def _italic_extra(font: ImageFont.ImageFont) -> int:
    size = int(getattr(font, "size", 16) or 16)
    return max(2, int(round(size * _ITALIC_SHEAR)))


def _slant_image(image: Image.Image) -> Image.Image:
    """把文字精灵向右倾斜。底边不动，顶边右移，中文没有斜体字库时也有效。"""
    width, height = image.size
    extra = max(2, int(round(height * _ITALIC_SHEAR)))
    return image.transform(
        (width + extra, height),
        Image.Transform.AFFINE,
        (1, _ITALIC_SHEAR, -_ITALIC_SHEAR * height, 0, 1, 0),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def _blit_text(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, ...],
    *,
    outline: bool = False,
    italic: bool = False,
) -> None:
    """在 RGB/RGBA 画布上绘制文字；fill 含 alpha 时正确半透明。"""
    rgba = fill if len(fill) == 4 else (*fill[:3], 255)
    x, y = float(xy[0]), float(xy[1])
    if italic:
        spr = _slant_image(_make_text_sprite(text, font, rgba, use_outline=outline))
        bb = draw.textbbox((0, 0), text, font=font)
        pad = 2 if outline else 1
        image.paste(spr, (int(round(x + bb[0] - pad)), int(round(y + bb[1] - pad))), spr)
        return
    if rgba[3] >= 255:
        if outline:
            _draw_text_with_outline(draw, (x, y), text, font, rgba[:3] if image.mode != "RGBA" else rgba)
        else:
            draw.text((x, y), text, font=font, fill=rgba[:3] if image.mode != "RGBA" else rgba)
        return
    if image.mode == "RGBA":
        outline_fill = _apply_fill_opacity((0, 0, 0, 160), rgba[3] / 255.0)
        if outline:
            _draw_text_with_outline(draw, (x, y), text, font, rgba, outline=outline_fill)
        else:
            draw.text((x, y), text, font=font, fill=rgba)
        return
    # RGB 画布半透明：用精灵粘贴。
    spr = _make_text_sprite(text, font, rgba, use_outline=outline)
    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    bb = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    pad = 2 if outline else 1
    px = int(round(x + bb[0] - pad))
    py = int(round(y + bb[1] - pad))
    image.paste(spr, (px, py), spr)


def _draw_segments(
    draw: ImageDraw.ImageDraw,
    segments: list[TextSegment],
    y: int,
    max_width: int,
    preferred: int,
    fill: tuple[int, ...],
    bold: bool = False,
    *,
    align: str,
    anchor_x: int,
    hits: list[dict[str, Any]] | None = None,
    outline: bool = False,
) -> int:
    """Draw a segmented line. Returns the tallest font size used.

    bold 参数保留兼容；实际字重以各 TextSegment.bold 为准。
    """
    del bold  # 兼容旧调用签名，字重走 segment.bold
    fitted = _fit_segment_fonts(draw, segments, max_width, preferred)
    if not fitted:
        return 0
    pieces: list[tuple[str, ImageFont.ImageFont, int, str, float, bool]] = []
    total = 0
    for seg, text, font, text_width in fitted:
        opacity = coerce_field_opacity(seg.opacity, 1.0)
        if seg.sep_before:
            sep_width = _separator_width(draw, seg.sep_before, font)
            pieces.append((seg.sep_before, font, sep_width, "", opacity, False))
            total += sep_width
        slant = _italic_extra(font) if seg.italic else 0
        pieces.append((text, font, text_width + slant, seg.key, opacity, bool(seg.italic)))
        total += text_width + slant
    if align == "right":
        x = float(anchor_x - total)
    elif align == "center":
        x = float(anchor_x - total / 2)
    else:
        x = float(anchor_x)
    tallest = 9
    image = draw._image  # noqa: SLF001 — Pillow ImageDraw 绑定画布
    for text, font, width, key, opacity, italic in pieces:
        seg_fill = _apply_fill_opacity(fill, opacity)
        if not key and _needs_drawn_dot(text, font):
            _blit_dot_separator(image, draw, x, float(y), width, font, seg_fill, outline=outline)
        else:
            _blit_text(image, draw, (x, y), text, font, seg_fill, outline=outline, italic=italic)
        font_size = int(getattr(font, "size", 9) or 9)
        tallest = max(tallest, font_size)
        if hits is not None and key:
            _append_hit(hits, key, text, x, float(y), float(width), float(font_size + 4))
        x += width
    return tallest


def _segments_width(
    draw: ImageDraw.ImageDraw,
    segments: list[TextSegment],
    max_width: int,
    preferred: int,
) -> int:
    total = 0
    for seg, _text, font, width in _fit_segment_fonts(draw, segments, max_width, preferred):
        if seg.sep_before:
            total += _separator_width(draw, seg.sep_before, font)
        total += width + (_italic_extra(font) if seg.italic else 0)
    return total


def _draw_divider(
    draw: ImageDraw.ImageDraw,
    x: float,
    top: int,
    height: int,
    ref: int,
    fill: tuple[int, ...],
) -> float:
    """品牌与参数之间的细竖线，返回竖线右侧 x。"""
    width = max(1, int(round(ref * 0.002)))
    y0 = top + int(height * 0.24)
    y1 = top + int(height * 0.76)
    mode = getattr(draw, "_image", None)
    color = fill if mode is not None and mode.mode == "RGBA" else tuple(fill[:3])
    xi = int(round(x))
    draw.rectangle((xi, y0, xi + width - 1, y1), fill=color)
    return float(xi + width)


def _metadata_lines(md: PhotoMetadata, options: dict[str, Any]) -> tuple[str, str, str]:
    title_segs, detail_segs, extra_segs = _metadata_segment_lines(md, options)
    return _line_plain_text(title_segs), _line_plain_text(detail_segs), _line_plain_text(extra_segs)


def _layout_shift(options: dict[str, Any], width: int, height: int) -> tuple[int, int]:
    try:
        ox = float(options.get("offset_x", 0.0))
    except (TypeError, ValueError):
        ox = 0.0
    try:
        oy = float(options.get("offset_y", 0.0))
    except (TypeError, ValueError):
        oy = 0.0
    try:
        mx = float(options.get("margin_x", 0.0))
    except (TypeError, ValueError):
        mx = 0.0
    try:
        my = float(options.get("margin_y", 0.0))
    except (TypeError, ValueError):
        my = 0.0
    anchor = str(options.get("anchor", "bottom_center") or "bottom_center")
    # 九宫格对叠加条的垂直基准：上/中/下；水平偏移叠加 margin。
    if "top" in anchor:
        base_y = -int(height * 0.35)
    elif anchor in ("center", "middle_left", "middle_right"):
        base_y = -int(height * 0.18)
    else:
        base_y = 0
    dx = int((ox + mx) * width)
    dy = int((oy - my) * height) + base_y
    return dx, dy


def _bar_alpha(options: dict[str, Any], default: int = 172) -> int:
    try:
        opacity = float(options.get("bar_opacity", 0.72))
    except (TypeError, ValueError):
        opacity = 0.72
    return max(40, min(255, int(255 * opacity)))


def _layout_factor(
    options: dict[str, Any],
    key: str,
    lo: float,
    hi: float,
    default: float = 1.0,
) -> float:
    try:
        value = float(options.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(hi, max(lo, value))


def _pads_are_default(options: dict[str, Any]) -> bool:
    top = _layout_factor(options, "pad_top", 0.4, 2.2)
    bottom = _layout_factor(options, "pad_bottom", 0.4, 2.2)
    return abs(top - 1.0) < 1e-6 and abs(bottom - 1.0) < 1e-6


def _side_factors(options: dict[str, Any]) -> tuple[float, float]:
    """左右边距比例；旧配置没有 pad_left/pad_right 时沿用 side_pad。"""
    side = _layout_factor(options, "side_pad", 0.4, 2.2)
    left = _layout_factor(options, "pad_left", 0.4, 2.2, side)
    right = _layout_factor(options, "pad_right", 0.4, 2.2, side)
    return left, right


def _bar_size(base_bar: int, base_margin: int, options: dict[str, Any]) -> tuple[int, int, int]:
    """底栏高度和左右边距。比例为 1 时保持原来的像素。"""
    bar_h = max(36, int(round(base_bar * _layout_factor(options, "bar_height", 0.5, 2.0))))
    left_f, right_f = _side_factors(options)
    left = max(8, int(round(base_margin * left_f)))
    right = max(8, int(round(base_margin * right_f)))
    return bar_h, left, right


def _bar_insets(bar_h: int, content_h: int, options: dict[str, Any]) -> tuple[int, int, int]:
    """返回 (底栏高, 内容距上沿, 内容距下沿)。上下边距都是 100% 时仍垂直居中。"""
    if _pads_are_default(options):
        top = max(3, (bar_h - content_h) // 2)
        return bar_h, top, max(0, bar_h - content_h - top)
    top_factor = _layout_factor(options, "pad_top", 0.4, 2.2)
    bottom_factor = _layout_factor(options, "pad_bottom", 0.4, 2.2)
    base_inset = max(3, int(bar_h * 0.08))
    top = max(0, int(round(base_inset * top_factor)))
    bottom = max(0, int(round(base_inset * bottom_factor)))
    needed = max(1, content_h) + top + bottom
    if needed > bar_h:
        bar_h = needed
    return bar_h, top, bottom


def _frame_box(
    base_pad: int, base_footer: int, options: dict[str, Any]
) -> tuple[int, int, int, int, int]:
    """相框边距：左、上、页脚、下、右。比例为 1 时等于传入的基准像素。"""
    left_f, right_f = _side_factors(options)
    pad_left = max(8, int(round(base_pad * left_f)))
    pad_right = max(8, int(round(base_pad * right_f)))
    pad_top = max(8, int(round(base_pad * _layout_factor(options, "pad_top", 0.4, 2.2))))
    pad_bottom = max(8, int(round(base_pad * _layout_factor(options, "pad_bottom", 0.4, 2.2))))
    footer = max(36, int(round(base_footer * _layout_factor(options, "bar_height", 0.5, 2.0))))
    return pad_left, pad_top, footer, pad_bottom, pad_right


def _inner_item_y(
    bar_top: int,
    bar_h: int,
    item_h: int,
    top_pad: int,
    bottom_pad: int,
    *,
    default_pads: bool,
) -> int:
    if default_pads:
        return bar_top + (bar_h - item_h) // 2
    room = max(0, bar_h - top_pad - bottom_pad - item_h)
    return bar_top + top_pad + room // 2


def render_watermark(source_path: str | Path, options: dict[str, Any]) -> Image.Image:
    """Render the image with watermark and return an RGB image."""
    image, _hits = render_watermark_with_hits(source_path, options)
    return image


def render_from_document(source_path: str | Path, document: Any) -> Image.Image:
    """从 WatermarkDocument 或兼容对象渲染。"""
    if hasattr(document, "render_options"):
        options = document.render_options()
    else:
        options = dict(document)
    return render_watermark(source_path, options)


def _freeform_field_items(
    md: PhotoMetadata, options: dict[str, Any], brand: str, caption: str
) -> list[tuple[str, str, float, bool, bool]]:
    """自定义模式下的独立字段列表：(key, text, scale, bold, italic)。"""
    items: list[tuple[str, str, float, bool, bool]] = []
    if brand:
        items.append(("brand", brand, 1.0, _field_bold(options, "brand"), _field_italic(options, "brand")))
    if options.get("show_camera"):
        camera = _override_or_exif(options.get("camera_text"), md.camera)
        if camera:
            items.append(
                (
                    "camera",
                    camera,
                    _field_scale(options, "camera_scale"),
                    _field_bold(options, "camera"),
                    _field_italic(options, "camera"),
                )
            )
    if options.get("show_lens"):
        lens = _override_or_exif(options.get("lens_text"), md.lens)
        if lens:
            items.append(
                (
                    "lens",
                    lens,
                    _field_scale(options, "lens_scale"),
                    _field_bold(options, "lens"),
                    _field_italic(options, "lens"),
                )
            )
    if options.get("show_exif"):
        custom = str(options.get("exif_text", "") or "").strip()
        exposure = custom if custom else format_exposure_line(md)
        if exposure:
            items.append(
                (
                    "exif",
                    exposure,
                    _field_scale(options, "exif_scale"),
                    _field_bold(options, "exif"),
                    _field_italic(options, "exif"),
                )
            )
    if options.get("show_date"):
        date = _override_or_exif(options.get("date_text"), md.date)
        if date:
            items.append(
                (
                    "date",
                    date,
                    _field_scale(options, "date_scale"),
                    _field_bold(options, "date"),
                    _field_italic(options, "date"),
                )
            )
    if options.get("show_gps"):
        gps = _override_or_exif(options.get("gps_text"), md.gps)
        if gps:
            items.append(
                (
                    "gps",
                    gps,
                    _field_scale(options, "gps_scale"),
                    _field_bold(options, "gps"),
                    _field_italic(options, "gps"),
                )
            )
    if caption:
        items.append(
            ("caption", caption, 1.0, _field_bold(options, "caption"), _field_italic(options, "caption"))
        )
    return items


def _resolve_field_xy(
    key: str,
    positions: dict[str, dict[str, float]],
    defaults: dict[str, dict[str, float]],
) -> tuple[float, float]:
    pos = positions.get(key) or defaults.get(key) or {"x": 0.5, "y": 0.8}
    try:
        return float(pos["x"]), float(pos["y"])
    except (KeyError, TypeError, ValueError):
        return 0.5, 0.8


def _make_text_sprite(
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, ...],
    *,
    use_outline: bool,
) -> Image.Image:
    """透明底字段精灵：仅文字（可选描边），不含照片像素。"""
    probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(probe)
    bb = d.textbbox((0, 0), text, font=font)
    tw = max(1, bb[2] - bb[0])
    th = max(1, bb[3] - bb[1])
    pad = 2 if use_outline else 1
    spr_w = tw + pad * 2
    spr_h = th + pad * 2
    spr = Image.new("RGBA", (spr_w, spr_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spr)
    dx = pad - bb[0]
    dy = pad - bb[1]
    rgba_fill = fill if len(fill) == 4 else (*fill[:3], 255)
    if use_outline:
        _draw_text_with_outline(sd, (dx, dy), text, font, rgba_fill)
    else:
        sd.text((dx, dy), text, font=font, fill=rgba_fill)
    return spr


def render_custom_freeform_layers(
    base: Image.Image,
    options: dict[str, Any],
    md: PhotoMetadata,
    brand: str,
    caption: str,
    logo: Image.Image | None,
    theme: dict[str, tuple[int, int, int]],
    frosted: bool,
    scale_setting: float,
    ref: int,
) -> dict[str, Any]:
    """自定义双层：base_layer（无字段）+ RGBA sprites + composite。"""
    base_style = effective_style(options)
    w, h = base.size
    positions_raw = options.get("field_positions")
    if not isinstance(positions_raw, dict):
        positions_raw = {}
    defaults = default_field_positions()
    positions = {**defaults, **{k: v for k, v in positions_raw.items() if isinstance(v, dict)}}

    pad = 0
    photo_origin = (0, 0)
    out_w, out_h = w, h
    if base_style in ("卡片相框", "胶片边框"):
        film = base_style == "胶片边框"
        base_pad = max(16, int(ref * 0.036)) if film else max(22, int(ref * 0.052))
        base_footer = max(40, int(ref * 0.08))
        pad_x, pad_top, footer_h, pad_bottom, pad_right = _frame_box(base_pad, base_footer, options)
        out_w = w + pad_x + pad_right
        out_h = h + pad_top + footer_h + pad_bottom
        frame = max(pad_x, pad_right, pad_top, pad_bottom)
        bg = theme["outer"]
        if frosted:
            canvas = _frosted_frame(base, (out_w, out_h), radius=max(16.0, frame * 1.4))
        else:
            canvas = Image.new("RGB", (out_w, out_h), bg)
        if film:
            canvas.paste(base, (pad_x, pad_top))
        else:
            radius = _card_radius(options, ref)
            canvas = _paste_card_shadow(
                canvas,
                (out_w, out_h),
                (pad_x + 2, pad_top + 7, pad_x + w + 2, pad_top + h + 7),
                radius,
                options,
                frame,
            )
            mask = _rounded_mask((w, h), radius)
            canvas.paste(base, (pad_x, pad_top), mask)
        photo_origin = (pad_x, pad_top)
        use_outline = False
        text_primary = (*theme["text"], 255) if len(theme["text"]) == 3 else theme["text"]
        text_muted = (*theme["muted"], 255) if len(theme["muted"]) == 3 else theme["muted"]
        base_layer = canvas
    else:
        # 经典/极简/纯文字：自由摆放不画空底栏。
        use_outline = base_style in ("纯文字中下", "极简叠加") or frosted
        if use_outline:
            text_primary = (255, 255, 255, 255)
            text_muted = (230, 234, 240, 255)
        else:
            text_primary = (*theme["text"], 255) if len(theme["text"]) == 3 else theme["text"]
            text_muted = (*theme["muted"], 255) if len(theme["muted"]) == 3 else theme["muted"]
        base_layer = base.copy().convert("RGB")

    ox, oy = photo_origin
    max_text_w = max(80, int(w * 0.86))
    hits: list[dict[str, Any]] = [
        {
            "key": "photo_content",
            "label": "",
            "text": "",
            "x": float(ox),
            "y": float(oy),
            "w": float(w),
            "h": float(h),
        }
    ]
    sprites: list[dict[str, Any]] = []

    def _to_canvas(nx: float, ny: float) -> tuple[float, float]:
        return nx * out_w, ny * out_h

    # 用透明 probe 量字号，避免往底版上画。
    probe = Image.new("RGBA", (max_text_w + 8, 64), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe)

    if logo is not None and options.get("show_logo", True) is not False:
        thumb = _fit_logo(logo, max(28, int(ref * 0.08 * scale_setting)) * _logo_scale(options)).convert("RGBA")
        nx, ny = _resolve_field_xy("logo", positions, defaults)
        cx, cy = _to_canvas(nx, ny)
        lx = int(round(cx - thumb.width / 2))
        ly = int(round(cy - thumb.height / 2))
        sprites.append(
            {
                "key": "logo",
                "x": float(lx),
                "y": float(ly),
                "w": float(thumb.width),
                "h": float(thumb.height),
                "image": thumb,
            }
        )
        _append_hit(hits, "logo", "", float(lx), float(ly), float(thumb.width), float(thumb.height))

    for key, text, scale, bold, italic in _freeform_field_items(md, options, brand, caption):
        preferred = max(12, int(ref * (0.036 if bold else 0.026) * scale_setting * scale))
        font = _fit_font(
            probe_draw,
            text,
            max_text_w,
            preferred,
            bold,
            bold and key == "brand",
            font_family=_field_font(options, f"{key}_font"),
        )
        fill = text_primary if bold or key in ("brand", "camera") else text_muted
        fill = _apply_fill_opacity(fill, _field_opacity(options, key))
        spr = _make_text_sprite(text, font, fill, use_outline=use_outline)
        if italic:
            spr = _slant_image(spr)
        nx, ny = _resolve_field_xy(key, positions, defaults)
        cx, cy = _to_canvas(nx, ny)
        sx = int(round(cx - spr.width / 2))
        sy = int(round(cy - spr.height / 2))
        sprites.append(
            {
                "key": key,
                "x": float(sx),
                "y": float(sy),
                "w": float(spr.width),
                "h": float(spr.height),
                "image": spr,
            }
        )
        _append_hit(hits, key, text, float(sx), float(sy), float(spr.width), float(spr.height))

    composite = base_layer.convert("RGBA")
    for spr in sprites:
        img = spr["image"].convert("RGBA")
        x, y = int(spr["x"]), int(spr["y"])
        if x >= composite.width or y >= composite.height or x + img.width <= 0 or y + img.height <= 0:
            continue
        composite.paste(img, (x, y), img)

    return {
        "composite": composite.convert("RGB"),
        "base": base_layer.convert("RGB"),
        "sprites": sprites,
        "hits": hits,
    }


def _render_custom_freeform(
    base: Image.Image,
    options: dict[str, Any],
    md: PhotoMetadata,
    brand: str,
    caption: str,
    logo: Image.Image | None,
    theme: dict[str, tuple[int, int, int]],
    frosted: bool,
    scale_setting: float,
    ref: int,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    """自定义：返回合成图 + hits（导出/兼容路径）。"""
    layers = render_custom_freeform_layers(
        base, options, md, brand, caption, logo, theme, frosted, scale_setting, ref
    )
    return layers["composite"], layers["hits"]


def _prepare_render_context(
    source_path: str | Path,
    options: dict[str, Any],
    *,
    base_image: Image.Image | None = None,
    metadata: PhotoMetadata | None = None,
) -> dict[str, Any]:
    """打开底图、读 EXIF、装 logo，供单层/双层渲染共用。"""
    if base_image is not None:
        base = base_image.convert("RGB")
        if base is base_image:
            base = base.copy()
    else:
        with Image.open(source_path) as src:
            base = ImageOps.exif_transpose(src).convert("RGB")
            original_exif = src.getexif()
        del original_exif
    w, h = base.size
    ref = min(w, h)
    theme_name = str(options.get("theme", "白色"))
    theme = _color_theme(theme_name, options.get("bg_color", ""))
    frosted = _is_frosted_theme(theme_name)
    style = effective_style(options)
    scale_setting = max(0.65, min(1.6, float(options.get("scale", 1.0))))
    shift_x, shift_y = _layout_shift(options, w, h)
    md = metadata if metadata is not None else read_photo_metadata(source_path)
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
                font_family=_field_font(options, "caption_font"),
                bold=_field_bold(options, "caption"),
                italic=_field_italic(options, "caption"),
                opacity=_field_opacity(options, "caption"),
            )
        ]
    line_groups = [group for group in (title_segs, detail_segs, extra_segs) if group]
    if not line_groups:
        line_groups = [[TextSegment("EXIF 参数暂缺，可添加自定义说明", 1.0)]]
    logo_path = str(options.get("logo_path", "") or "")
    show_logo = options.get("show_logo", True) is not False
    logo_scale = _logo_scale(options)
    logo_box = (max(52, int(ref * 0.247)), max(36, int(ref * 0.0715)))
    logo = None
    if show_logo:
        logo = _load_logo(
            logo_path, (int(logo_box[0] * logo_scale), int(logo_box[1] * logo_scale))
        )
        mark = str(options.get("logo_mark", "") or "")
        if logo is None and mark == "nikon":
            logo = _load_logo(
                str(resource_dir() / "Nikon.webp"),
                (int(logo_box[0] * logo_scale), int(logo_box[1] * logo_scale)),
            )
        elif logo is None and mark:
            light = frosted or style in ("纯文字中下", "极简叠加")
            color = (255, 255, 255) if light else theme["text"]
            logo = _logo_badge(mark, int(logo_box[1] * logo_scale), color)
        if logo is not None:
            logo = _with_opacity(logo, _logo_opacity(options))
    return {
        "base": base.convert("RGB"),
        "w": w,
        "h": h,
        "ref": ref,
        "theme": theme,
        "frosted": frosted,
        "style": style,
        "scale_setting": scale_setting,
        "shift_x": shift_x,
        "shift_y": shift_y,
        "md": md,
        "brand": brand,
        "caption": caption,
        "line_groups": line_groups,
        "logo": logo,
    }


def render_watermark_layers(
    source_path: str | Path,
    options: dict[str, Any],
    *,
    base_image: Image.Image | None = None,
    metadata: PhotoMetadata | None = None,
) -> dict[str, Any]:
    """预览用：自定义返回 base+sprites；其它样式 sprites 为空、base=composite。"""
    ctx = _prepare_render_context(source_path, options, base_image=base_image, metadata=metadata)
    if is_custom_style(options):
        return render_custom_freeform_layers(
            ctx["base"],
            options,
            ctx["md"],
            ctx["brand"],
            ctx["caption"],
            ctx["logo"],
            ctx["theme"],
            ctx["frosted"],
            ctx["scale_setting"],
            ctx["ref"],
        )
    composite, hits = _render_prepared(ctx, options)
    return {"composite": composite, "base": composite.copy(), "sprites": [], "hits": hits}


def render_watermark_with_hits(
    source_path: str | Path,
    options: dict[str, Any],
    *,
    base_image: Image.Image | None = None,
    metadata: PhotoMetadata | None = None,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Render watermark and return clickable text regions in image coordinates.

    base_image / metadata 供预览和导出复用已解码图，避免再打开原图。
    """
    ctx = _prepare_render_context(source_path, options, base_image=base_image, metadata=metadata)
    return _render_prepared(ctx, options)


def _render_film(
    ctx: dict[str, Any],
    options: dict[str, Any],
    hits: list[dict[str, Any]],
    logo_scale: float,
    show_divider: bool,
) -> tuple[Image.Image, list[dict[str, Any]]]:
    """胶片边框：四边等宽留边，底部一行居中排 Logo/署名与参数。"""
    base = ctx["base"]
    w, h = ctx["w"], ctx["h"]
    ref = ctx["ref"]
    theme = ctx["theme"]
    scale_setting = ctx["scale_setting"]
    shift_x, shift_y = ctx["shift_x"], ctx["shift_y"]
    brand = ctx["brand"]
    logo = ctx["logo"]
    line_groups = ctx["line_groups"][:2]
    brand_font = _field_font(options, "brand_font")
    brand_bold = _field_bold(options, "brand")
    brand_italic = _field_italic(options, "brand")
    brand_opacity = _field_opacity(options, "brand")

    base_pad = max(16, int(ref * 0.036))
    base_footer = max(72, int(ref * 0.12 * scale_setting))
    pad_left, pad_top, footer_h, pad_bottom, pad_right = _frame_box(base_pad, base_footer, options)
    out_w = w + pad_left + pad_right
    out_h = h + pad_top + footer_h + pad_bottom
    if ctx["frosted"]:
        frame = max(pad_left, pad_right, pad_top, pad_bottom)
        canvas = _frosted_frame(base, (out_w, out_h), radius=max(16.0, frame * 1.4))
    else:
        canvas = Image.new("RGB", (out_w, out_h), theme["outer"])
    canvas.paste(base, (pad_left, pad_top))
    d = ImageDraw.Draw(canvas)

    footer_top = pad_top + h
    mid_y = footer_top + footer_h / 2 + shift_y
    center_x = pad_left + w / 2 + shift_x
    gap = max(12, int(ref * 0.02))

    thumb = _fit_logo(logo, int(footer_h * 0.5) * logo_scale) if logo is not None else None
    show_brand = bool(brand) and (thumb is None or bool(options.get("show_brand_text", False)))
    fbrand = None
    brand_box = (0, 0, 0, 0)
    if show_brand:
        fbrand = _fit_font(
            d, brand, max(60, int(out_w * 0.3)), int(footer_h * 0.24), brand_bold, brand_bold, font_family=brand_font
        )
        brand_box = d.textbbox((0, 0), brand, font=fbrand)
    brand_w = brand_box[2] - brand_box[0]
    if show_brand and brand_italic and fbrand is not None:
        brand_w += _italic_extra(fbrand)
    left_w = 0
    if thumb is not None:
        left_w += thumb.width
    if show_brand:
        left_w += brand_w + (gap if thumb is not None else 0)

    prefs = [max(10, int(footer_h * (0.2 if idx == 0 else 0.15))) for idx in range(len(line_groups))]
    max_line_w = max(60, int(out_w * 0.86) - left_w - gap * 2)
    right_w = max(
        (_segments_width(d, segs, max_line_w, pref) for segs, pref in zip(line_groups, prefs)),
        default=0,
    )
    divider = show_divider and left_w > 0
    middle = (gap * 2 if divider else gap) if left_w > 0 and right_w > 0 else 0
    x = center_x - (left_w + middle + right_w) / 2

    if thumb is not None:
        canvas.paste(thumb, (int(round(x)), int(round(mid_y - thumb.height / 2))), thumb)
        _append_hit(hits, "logo", "", x, mid_y - thumb.height / 2, float(thumb.width), float(thumb.height))
        x += thumb.width + (gap if show_brand else 0)
    if show_brand and fbrand is not None:
        bx = x - brand_box[0]
        by = mid_y - (brand_box[1] + brand_box[3]) / 2
        _blit_text(canvas, d, (bx, by), brand, fbrand, _apply_fill_opacity(theme["text"], brand_opacity), italic=brand_italic)
        hit = d.textbbox((bx, by), brand, font=fbrand)
        _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
        x += brand_w
    if middle:
        if divider:
            x += gap
            line_color = tuple((m + b) // 2 for m, b in zip(theme["muted"], theme["outer"]))
            x = _draw_divider(d, x, int(footer_top + shift_y), footer_h, ref, line_color)
        x += gap

    line_hs = [int(pref * 1.3) for pref in prefs]
    y = mid_y - sum(line_hs) / 2
    for idx, (segs, pref) in enumerate(zip(line_groups, prefs)):
        _draw_segments(
            d,
            segs,
            int(round(y)),
            max_line_w,
            pref,
            theme["text"] if idx == 0 else theme["muted"],
            idx == 0,
            align="left",
            anchor_x=int(round(x)),
            hits=hits,
        )
        y += line_hs[idx]
    _append_hit(hits, "watermark_bar", "", 0.0, float(footer_top), float(out_w), float(footer_h))
    return canvas, hits


def _render_prepared(
    ctx: dict[str, Any],
    options: dict[str, Any],
) -> tuple[Image.Image, list[dict[str, Any]]]:
    base = ctx["base"]
    w, h = ctx["w"], ctx["h"]
    ref = ctx["ref"]
    theme = ctx["theme"]
    frosted = ctx["frosted"]
    style = ctx["style"]
    scale_setting = ctx["scale_setting"]
    shift_x, shift_y = ctx["shift_x"], ctx["shift_y"]
    md = ctx["md"]
    brand = ctx["brand"]
    caption = ctx["caption"]
    line_groups = ctx["line_groups"]
    logo = ctx["logo"]
    hits: list[dict[str, Any]] = []
    brand_font = _field_font(options, "brand_font")
    brand_bold = _field_bold(options, "brand")
    brand_italic = _field_italic(options, "brand")
    brand_opacity = _field_opacity(options, "brand")
    logo_scale = _logo_scale(options)
    show_divider = bool(options.get("show_divider", False))

    if is_custom_style(options):
        return _render_custom_freeform(
            base,
            options,
            md,
            brand,
            caption,
            logo,
            theme,
            frosted,
            scale_setting,
            ref,
        )

    if style == "纯文字中下":
        rgba = base.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        text_primary = (255, 255, 255, 255)
        text_muted = (230, 234, 240, 255)
        max_text_w = max(80, int(w * 0.86))
        center_x = w // 2 + shift_x
        # 内容从画面中下部起排，可被自定义偏移上下移动。
        cy = int(h * 0.74) + shift_y
        block_top = cy
        block_left = float(w)
        block_right = 0.0
        if logo is not None:
            thumb = _fit_logo(logo, max(28, int(ref * 0.08 * scale_setting)) * logo_scale)
            lx = center_x - thumb.width // 2
            overlay.paste(thumb, (lx, cy), thumb)
            block_left = min(block_left, float(lx))
            block_right = max(block_right, float(lx + thumb.width))
            cy += thumb.height + max(6, int(ref * 0.012))
            if brand and options.get("show_brand_text", False):
                brand_size = max(14, int(ref * 0.028 * scale_setting))
                fbrand = _fit_font(
                    d, brand, max_text_w, brand_size, brand_bold, brand_bold, font_family=brand_font
                )
                bb = d.textbbox((0, 0), brand, font=fbrand)
                bx = center_x - (bb[2] - bb[0]) / 2
                brand_fill = _apply_fill_opacity(text_primary, brand_opacity)
                _blit_text(overlay, d, (bx, cy), brand, fbrand, brand_fill, outline=True, italic=brand_italic)
                hit = d.textbbox((bx, cy), brand, font=fbrand)
                _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
                block_left = min(block_left, float(hit[0]))
                block_right = max(block_right, float(hit[2]))
                cy += int(fbrand.size * 1.25)
        elif brand:
            brand_size = max(16, int(ref * 0.042 * scale_setting))
            fbrand = _fit_font(
                d, brand, max_text_w, brand_size, brand_bold, brand_bold, font_family=brand_font
            )
            bb = d.textbbox((0, 0), brand, font=fbrand)
            bx = center_x - (bb[2] - bb[0]) / 2
            brand_fill = _apply_fill_opacity(text_primary, brand_opacity)
            _blit_text(overlay, d, (bx, cy), brand, fbrand, brand_fill, outline=True, italic=brand_italic)
            hit = d.textbbox((bx, cy), brand, font=fbrand)
            _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
            block_left = min(block_left, float(hit[0]))
            block_right = max(block_right, float(hit[2]))
            cy += int(fbrand.size * 1.25)
        for idx, segments in enumerate(line_groups[:3]):
            preferred = max(12, int(ref * (0.032 if idx == 0 else 0.024) * scale_setting))
            before = cy
            tallest = _draw_segments(
                d,
                segments,
                cy,
                max_text_w,
                preferred,
                text_primary if idx == 0 else text_muted,
                idx == 0,
                align="center",
                anchor_x=center_x,
                hits=hits,
                outline=True,
            )
            # 用本行命中粗估左右边界
            for hit in hits:
                if hit.get("key") in {seg.key for seg in segments if seg.key}:
                    block_left = min(block_left, float(hit["x"]))
                    block_right = max(block_right, float(hit["x"]) + float(hit["w"]))
            cy = before + int(max(tallest, preferred) * 1.28)
        block_bottom = float(cy)
        if block_right <= block_left:
            block_left, block_right = w * 0.2, w * 0.8
        pad_box = max(8, int(ref * 0.01))
        _append_hit(
            hits,
            "watermark_bar",
            "",
            max(0.0, block_left - pad_box),
            max(0.0, float(block_top) - pad_box),
            min(float(w), block_right - block_left + 2 * pad_box),
            min(float(h), block_bottom - block_top + 2 * pad_box),
        )
        return Image.alpha_composite(rgba, overlay).convert("RGB"), hits

    if style == "极简叠加":
        rgba = base.convert("RGBA")
        # 底栏高度随「水印大小」与短边变化，相机/镜头等字号才能一起变大。
        base_band = max(96, int(ref * 0.1196 * scale_setting))
        base_margin = max(20, int(w * 0.033))
        band_h, side_margin, right_margin = _bar_size(base_band, base_margin, options)
        line_heights = [int(band_h * (0.31 if idx == 0 else 0.22)) for idx in range(len(line_groups))]
        total_h = sum(line_heights) + max(0, len(line_groups) - 1) * 1
        band_h, top_pad, bottom_pad = _bar_insets(band_h, total_h, options)
        if band_h > h:
            band_h = h
            if _pads_are_default(options):
                top_pad = max(3, (band_h - total_h) // 2)
            else:
                top_pad = min(top_pad, max(0, band_h - 1))
        default_pads = _pads_are_default(options)
        band_top = max(0, min(h - band_h, h - band_h + shift_y))
        if frosted:
            try:
                blur_radius = float(options.get("blur_radius", band_h / 3.2))
            except (TypeError, ValueError):
                blur_radius = band_h / 3.2
            frosted_strip = _frosted_overlay_strip(base, band_top, band_h, radius=blur_radius)
            rgba.paste(frosted_strip, (0, band_top))
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        if not frosted:
            alpha = _bar_alpha(options, 172)
            d.rectangle((0, band_top, w, band_top + band_h), fill=(7, 12, 20, alpha))
        margin = side_margin + shift_x
        left_cap = int(w * 0.42)
        text_primary = (255, 255, 255, 255)
        text_muted = (211, 219, 230, 255)
        left_occupied = float(max(8, margin))
        left_drawn = False
        if logo is not None:
            left_drawn = True
            thumb = _fit_logo(logo, int(band_h * 0.64) * logo_scale)
            lx = max(0, margin)
            overlay.paste(
                thumb,
                (lx, _inner_item_y(band_top, band_h, thumb.height, top_pad, bottom_pad, default_pads=default_pads)),
                thumb,
            )
            left_occupied = float(lx + thumb.width)
            if brand and options.get("show_brand_text", False):
                logo_gap = max(18, int(w * 0.012))
                small = _fit_font(
                    d,
                    brand,
                    max(50, left_cap - thumb.width - logo_gap),
                    int(band_h * 0.28),
                    brand_bold,
                    brand_bold,
                    font_family=brand_font,
                )
                bx = lx + thumb.width + logo_gap
                by = _inner_item_y(band_top, band_h, small.size, top_pad, bottom_pad, default_pads=default_pads)
                brand_fill = _apply_fill_opacity(text_primary, brand_opacity)
                _blit_text(overlay, d, (bx, by), brand, small, brand_fill, italic=brand_italic)
                bb = d.textbbox((bx, by), brand, font=small)
                _append_hit(hits, "brand", brand, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1])
                left_occupied = float(bb[2])
        elif brand:
            left_drawn = True
            fbrand = _fit_font(
                d, brand, left_cap, int(band_h * 0.54), brand_bold, brand_bold, font_family=brand_font
            )
            bx = float(max(8, margin))
            by = float(band_top + int(band_h * 0.14) if default_pads else band_top + top_pad)
            brand_fill = _apply_fill_opacity(text_primary, brand_opacity)
            _blit_text(overlay, d, (bx, by), brand, fbrand, brand_fill, italic=brand_italic)
            bb = d.textbbox((bx, by), brand, font=fbrand)
            _append_hit(hits, "brand", brand, bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1])
            left_occupied = float(bb[2])

        right_x = w - right_margin + shift_x
        gap = max(16, int(w * 0.02))
        if show_divider and left_drawn:
            left_occupied = _draw_divider(
                d, left_occupied + gap, band_top, band_h, ref, (255, 255, 255, 120)
            )
        max_right = max(48, int(right_x - left_occupied - gap))
        y = band_top + top_pad
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
        # 叠加层命中区元数据，便于画布拖动整条水印。
        _append_hit(hits, "watermark_bar", "", 0, float(band_top), float(w), float(band_h))
        return Image.alpha_composite(rgba, overlay).convert("RGB"), hits

    if style == "卡片相框":
        base_pad = max(22, int(min(w, h) * 0.052))
        # 页脚按原比例再收一截（约减少 1/5），避免底部留白过多。
        base_footer = max(94, int(min(w, h) * 0.1664 * scale_setting))
        # Logo + 署名纵向叠放时加高页脚，避免挤在一起。
        if logo is not None and brand:
            base_footer = max(base_footer, int(base_footer * 1.28))
        pad_x, pad_top, footer_h, pad_bottom, pad_right = _frame_box(base_pad, base_footer, options)
        out_w = w + pad_x + pad_right
        out_h = h + pad_top + footer_h + pad_bottom
        frame = max(pad_x, pad_right, pad_top, pad_bottom)
        bg = theme["outer"]
        if frosted:
            canvas = _frosted_frame(base, (out_w, out_h), radius=max(16.0, frame * 1.4))
        else:
            canvas = Image.new("RGB", (out_w, out_h), bg)
        radius = _card_radius(options, ref)
        canvas = _paste_card_shadow(
            canvas,
            (out_w, out_h),
            (pad_x + 2, pad_top + 7, pad_x + w + 2, pad_top + h + 7),
            radius,
            options,
            frame,
        )
        mask = _rounded_mask((w, h), radius)
        canvas.paste(base, (pad_x, pad_top), mask)
        d = ImageDraw.Draw(canvas)
        footer_top = pad_top + h
        cy = footer_top + max(14, int(footer_h * .10)) + shift_y
        center_x = pad_x + w // 2 + shift_x
        if logo is not None:
            lx = center_x - logo.width // 2
            canvas.paste(logo, (lx, cy), logo)
            cy += logo.height + max(2, int(footer_h * .03))
            d = ImageDraw.Draw(canvas)
        # 卡片为纵向排布：有署名就显示；有 Logo 时署名在 Logo 下方，不再被 elif 吞掉。
        if brand:
            brand_size = int(min(w, h) * (.0364 if logo is not None else .0546) * scale_setting)
            fbrand = _fit_font(
                d, brand, out_w - pad_x * 2, brand_size, brand_bold, brand_bold, font_family=brand_font
            )
            bb = d.textbbox((0, 0), brand, font=fbrand)
            bx = center_x - (bb[2] - bb[0]) / 2
            brand_fill = _apply_fill_opacity(theme["text"], brand_opacity)
            _blit_text(canvas, d, (bx, cy), brand, fbrand, brand_fill, italic=brand_italic)
            hit = d.textbbox((bx, cy), brand, font=fbrand)
            _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
            cy += int(fbrand.size * 1.18)
        for idx, segments in enumerate(line_groups[:3]):
            preferred = int(min(w, h) * (.0286 if idx == 0 else .0208) * scale_setting)
            tallest = _draw_segments(
                d,
                segments,
                cy,
                out_w - pad_x * 2,
                preferred,
                theme["text"] if idx == 0 else theme["muted"],
                idx == 0,
                align="center",
                anchor_x=center_x,
                hits=hits,
            )
            cy += int(max(tallest, preferred) * 1.32)
        _append_hit(hits, "watermark_bar", "", 0.0, float(footer_top), float(out_w), float(footer_h))
        return canvas, hits

    if style == "胶片边框":
        return _render_film(ctx, options, hits, logo_scale, show_divider)

    base_bar = max(96, int(ref * .1196 * scale_setting))
    base_margin = max(20, int(w * .033))
    bar_h, side_margin, right_margin = _bar_size(base_bar, base_margin, options)
    line_heights = [int(bar_h * (0.31 if idx == 0 else 0.22)) for idx in range(len(line_groups))]
    total_h = sum(line_heights) + max(0, len(line_groups) - 1) * 1
    bar_h, top_pad, bottom_pad = _bar_insets(bar_h, total_h, options)
    default_pads = _pads_are_default(options)
    if frosted:
        canvas = Image.new("RGB", (w, h + bar_h))
        canvas.paste(base, (0, 0))
        canvas.paste(_frosted_bar(base, bar_h), (0, h))
    else:
        canvas = Image.new("RGB", (w, h + bar_h), theme["bar"])
        canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas)
    margin = side_margin + shift_x
    left_cap = int(w * .42)
    left_occupied = float(max(8, margin))
    left_drawn = logo is not None or bool(brand)
    if logo is not None:
        thumb = _fit_logo(logo, int(bar_h * .64) * logo_scale)
        lx = max(0, margin)
        canvas.paste(
            thumb,
            (lx, _inner_item_y(h, bar_h, thumb.height, top_pad, bottom_pad, default_pads=default_pads)),
            thumb,
        )
        left_occupied = float(lx + thumb.width)
        if brand and options.get("show_brand_text", False):
            logo_gap = max(18, int(w * 0.012))
            small = _fit_font(
                d,
                brand,
                max(50, left_cap - thumb.width - logo_gap),
                int(bar_h * .28),
                brand_bold,
                brand_bold,
                font_family=brand_font,
            )
            bx = lx + thumb.width + logo_gap
            by = _inner_item_y(h, bar_h, small.size, top_pad, bottom_pad, default_pads=default_pads)
            brand_fill = _apply_fill_opacity(theme["text"], brand_opacity)
            _blit_text(canvas, d, (bx, by), brand, small, brand_fill, italic=brand_italic)
            hit = d.textbbox((bx, by), brand, font=small)
            _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
            left_occupied = float(hit[2])
    elif brand:
        fbrand = _fit_font(
            d, brand, left_cap, int(bar_h * .54), brand_bold, brand_bold, font_family=brand_font
        )
        bx = float(max(8, margin))
        by = float(h + int(bar_h * .14) if default_pads else h + top_pad)
        brand_fill = _apply_fill_opacity(theme["text"], brand_opacity)
        _blit_text(canvas, d, (bx, by), brand, fbrand, brand_fill, italic=brand_italic)
        hit = d.textbbox((bx, by), brand, font=fbrand)
        _append_hit(hits, "brand", brand, hit[0], hit[1], hit[2] - hit[0], hit[3] - hit[1])
        left_occupied = float(hit[2])

    right_x = w - right_margin + shift_x
    gap = max(16, int(w * 0.02))
    if show_divider and left_drawn:
        line_color = tuple((m + b) // 2 for m, b in zip(theme["muted"], theme["bar"]))
        left_occupied = _draw_divider(d, left_occupied + gap, h, bar_h, ref, line_color)
    max_right = max(48, int(right_x - left_occupied - gap))
    y = h + top_pad
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
    _append_hit(hits, "watermark_bar", "", 0, float(h), float(w), float(bar_h))
    return canvas, hits
