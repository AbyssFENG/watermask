# -*- coding: utf-8 -*-
"""Photo Watermark Studio - Windows desktop MVP.

Features:
- Read available EXIF metadata from photos (camera, lens, focal length,
  aperture, shutter speed, ISO, capture time and GPS where present).
- Three watermark layouts: classic footer, minimal overlay and framed card.
- Optional logo, custom signature/caption, live preview and batch export.

Dependency: Pillow (pip install Pillow). Tkinter is included with standard Python on Windows.
"""
from __future__ import annotations

import math
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ExifTags, Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk

APP_NAME = "光影水印 · Photo Watermark Studio"
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}

# ---------- Metadata ----------
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
    s = str(value).strip()
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
        mapping = {"NIKON": "Nikon", "CANON": "Canon", "SONY": "Sony", "FUJIFILM": "FUJIFILM",
                   "OLYMPUS": "OM SYSTEM", "OM DIGITAL SOLUTIONS": "OM SYSTEM", "PANASONIC": "LUMIX",
                   "LEICA": "Leica", "RICOH": "RICOH", "PENTAX": "PENTAX", "APPLE": "Apple iPhone"}
        return mapping.get(make.upper(), make.title())


def read_photo_metadata(path: str | Path) -> PhotoMetadata:
    """Read common camera EXIF fields. Missing EXIF is normal and returns empty fields."""
    md = PhotoMetadata()
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return md
            md.make = str(exif.get(271, "") or "").strip()
            model = str(exif.get(272, "") or "").strip()
            if model and md.make and model.upper().startswith(md.make.upper()):
                md.camera = model.upper()
            elif model:
                md.camera = f"{md.make} {model}".strip().upper()
            else:
                md.camera = md.make.upper()

            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:
                exif_ifd = {}
            exif_ifd = exif_ifd or {}

            lens = exif_ifd.get(42036) or exif_ifd.get(0xA434) or exif.get(42036) or exif.get(0xA434)
            if lens:
                md.lens = str(lens).strip().upper()
            md.focal = _format_focal(exif_ifd.get(37386) or exif.get(37386))
            md.aperture = _format_aperture(exif_ifd.get(33437) or exif.get(33437))
            md.shutter = _format_shutter(exif_ifd.get(33434) or exif.get(33434))
            iso = exif_ifd.get(34855) or exif_ifd.get(0x8827) or exif.get(34855) or exif.get(0x8827)
            if isinstance(iso, (tuple, list)):
                iso = iso[0] if iso else None
            if iso is not None:
                md.iso = str(iso)
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


# ---------- Watermark rendering ----------
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
    return {"bar": (250, 250, 249), "text": (23, 27, 34), "muted": (96, 103, 114), "outer": (231, 237, 244)}


def _metadata_lines(md: PhotoMetadata, options: dict[str, Any]) -> tuple[str, str, str]:
    title_parts: list[str] = []
    if options.get("show_camera") and md.camera:
        title_parts.append(md.camera)
    if options.get("show_lens") and md.lens:
        title_parts.append(md.lens)
    title = "  ·  ".join(title_parts)

    detail_parts: list[str] = []
    if options.get("show_exif"):
        if md.iso:
            detail_parts.append(f"ISO {md.iso}")
        if md.focal:
            detail_parts.append(md.focal.upper())
        if md.aperture:
            detail_parts.append(md.aperture.upper())
        if md.shutter:
            detail_parts.append(md.shutter.upper())
    detail = "  |  ".join(detail_parts)
    extra_parts: list[str] = []
    if options.get("show_date") and md.date:
        extra_parts.append(md.date)
    if options.get("show_gps") and md.gps:
        extra_parts.append(md.gps)
    extra = "  ·  ".join(extra_parts)
    return title, detail, extra


def render_watermark(source_path: str | Path, options: dict[str, Any]) -> Image.Image:
    """Render the image with watermark and return an RGB image."""
    with Image.open(source_path) as src:
        base = ImageOps.exif_transpose(src).convert("RGB")
        original_exif = src.getexif()
    w, h = base.size
    theme = _color_theme(str(options.get("theme", "浅色")))
    style = str(options.get("style", "经典底栏"))
    scale_setting = max(0.65, min(1.6, float(options.get("scale", 1.0))))
    md = read_photo_metadata(source_path)
    brand = str(options.get("brand", "")).strip() or md.brand or "摄影作品"
    caption = str(options.get("caption", "")).strip()
    title, detail, extra = _metadata_lines(md, options)
    if caption:
        extra = f"{extra}  ·  {caption}" if extra else caption
    if not title and not detail and not extra:
        title = "EXIF 参数暂缺，可添加自定义说明"

    logo = _load_logo(str(options.get("logo_path", "")), (max(40, int(w * 0.19)), max(28, int(w * 0.055))))
    base = base.convert("RGB")

    if style == "极简叠加":
        rgba = base.convert("RGBA")
        overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        band_h = max(74, int(h * 0.115))
        band_h = min(band_h, max(74, int(h * 0.22)))
        d.rectangle((0, h - band_h, w, h), fill=(7, 12, 20, 172))
        margin = max(18, int(w * 0.035))
        line_x = margin
        y = h - band_h + max(12, int(band_h * 0.16))
        main = title or brand
        f1 = _fit_font(d, main, w - margin * 2, int(w * .027 * scale_setting), True)
        d.text((line_x, y), main, font=f1, fill=(255, 255, 255, 255))
        y += int(f1.size * 1.35)
        if detail:
            f2 = _fit_font(d, detail, w - margin * 2, int(w * .018 * scale_setting))
            d.text((line_x, y), detail, font=f2, fill=(232, 237, 244, 255))
            y += int(f2.size * 1.35)
        sub = "  ·  ".join([v for v in (brand if title else "", extra) if v])
        if sub:
            f3 = _fit_font(d, sub, w - margin * 2, int(w * .014 * scale_setting))
            d.text((line_x, min(h - f3.size - 5, y)), sub, font=f3, fill=(211, 219, 230, 255))
        return Image.alpha_composite(rgba, overlay).convert("RGB")

    if style == "卡片相框":
        pad = max(22, int(min(w, h) * 0.052))
        footer_h = max(90, int(min(w, h) * 0.16))
        out_w = w + 2 * pad
        out_h = h + 2 * pad + footer_h
        bg = theme["outer"]
        canvas = Image.new("RGB", (out_w, out_h), bg)
        # Soft shadow under a rounded photo card.
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
        else:
            fbrand = _fit_font(d, brand, out_w - pad * 2, int(min(w, h) * .042 * scale_setting), True, True)
            bb = d.textbbox((0, 0), brand, font=fbrand)
            d.text((center_x - (bb[2] - bb[0]) / 2, cy), brand, font=fbrand, fill=theme["text"])
            cy += int(fbrand.size * 1.18)
        bottom_lines = [v for v in (title, detail, extra) if v]
        for idx, line in enumerate(bottom_lines[:3]):
            preferred = int(min(w, h) * (.022 if idx == 0 else .016) * scale_setting)
            f = _fit_font(d, line, out_w - pad * 2, preferred, idx == 0)
            bb = d.textbbox((0, 0), line, font=f)
            d.text((center_x - (bb[2] - bb[0]) / 2, cy), line, font=f,
                   fill=theme["text"] if idx == 0 else theme["muted"])
            cy += int(f.size * 1.32)
        return canvas

    # Classic footer bar, inspired by the horizontal Nikon sample.
    bar_h = max(74, int(w * .092))
    canvas = Image.new("RGB", (w, h + bar_h), theme["bar"])
    canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas)
    margin = max(20, int(w * .033))
    left_max = int(w * .32)
    if logo is not None:
        thumb = logo.copy()
        max_h = int(bar_h * .64)
        if thumb.height > max_h:
            ratio = max_h / thumb.height
            thumb = thumb.resize((max(1, int(thumb.width * ratio)), max_h), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (margin, h + (bar_h - thumb.height) // 2), thumb)
        if brand and options.get("show_brand_text", False):
            small = _fit_font(d, brand, max(50, left_max - thumb.width - 12), int(bar_h * .28), True, True)
            d.text((margin + thumb.width + 10, h + (bar_h - small.size) // 2), brand, font=small, fill=theme["text"])
    else:
        fbrand = _fit_font(d, brand, left_max, int(bar_h * .54 * scale_setting), True, True)
        d.text((margin, h + int(bar_h * .14)), brand, font=fbrand, fill=theme["text"])

    right_x = w - margin
    max_right = w - left_max - margin * 2
    lines = [v for v in (title, detail, extra) if v]
    if not lines:
        lines = ["EXIF 参数暂缺，可添加自定义说明"]
    line_heights = [int(bar_h * (0.31 if idx == 0 else 0.22)) for idx in range(len(lines))]
    total_h = sum(line_heights) + max(0, len(lines) - 1) * 1
    y = h + max(3, (bar_h - total_h) // 2)
    for idx, line in enumerate(lines[:3]):
        pref = int(bar_h * (0.32 if idx == 0 else 0.21) * scale_setting)
        f = _fit_font(d, line, max_right, pref, idx == 0)
        bb = d.textbbox((0, 0), line, font=f)
        d.text((right_x - (bb[2] - bb[0]), y), line, font=f,
               fill=theme["text"] if idx == 0 else theme["muted"])
        y += line_heights[idx] + 1
    return canvas


# ---------- Desktop UI ----------
class PhotoWatermarkStudioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1440x900")
        self.root.minsize(1120, 720)
        self.root.configure(bg="#F3F5F8")
        self.files: list[str] = []
        self.current_path: Optional[str] = None
        self.current_preview: Optional[ImageTk.PhotoImage] = None
        self.logo_path = ""
        self.output_dir = str(Path.home() / "Pictures" / "PhotoWatermark")
        self._resize_job = None

        self.style_var = tk.StringVar(value="经典底栏")
        self.theme_var = tk.StringVar(value="浅色")
        self.brand_var = tk.StringVar(value="")
        self.caption_var = tk.StringVar(value="")
        self.scale_var = tk.DoubleVar(value=1.0)
        self.show_camera_var = tk.BooleanVar(value=True)
        self.show_lens_var = tk.BooleanVar(value=True)
        self.show_exif_var = tk.BooleanVar(value=True)
        self.show_date_var = tk.BooleanVar(value=False)
        self.show_gps_var = tk.BooleanVar(value=False)
        self.show_brand_text_var = tk.BooleanVar(value=False)
        self.quality_var = tk.IntVar(value=95)
        self.status_var = tk.StringVar(value="添加照片开始制作水印。原图不会被修改。")

        self._setup_styles()
        self._build_ui()
        self._bind_events()

    def _setup_styles(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background="#F3F5F8")
        s.configure("Panel.TFrame", background="#FFFFFF")
        s.configure("TLabel", background="#F3F5F8", foreground="#182230", font=("Segoe UI", 10))
        s.configure("Panel.TLabel", background="#FFFFFF", foreground="#182230", font=("Segoe UI", 10))
        s.configure("Muted.TLabel", background="#FFFFFF", foreground="#768296", font=("Segoe UI", 9))
        s.configure("Heading.TLabel", background="#FFFFFF", foreground="#172033", font=("Segoe UI", 12, "bold"))
        s.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 9),
                    background="#275DDB", foreground="#FFFFFF", borderwidth=0)
        s.map("Primary.TButton", background=[("active", "#194FC6"), ("disabled", "#9BAED6")])
        s.configure("Soft.TButton", font=("Segoe UI", 9), padding=(10, 7), background="#EDF2F8", foreground="#24344A", borderwidth=0)
        s.map("Soft.TButton", background=[("active", "#DDE7F4")])
        s.configure("TCheckbutton", background="#FFFFFF", foreground="#2F3A4A", font=("Segoe UI", 9))
        s.configure("TCombobox", padding=6, fieldbackground="#FFFFFF")
        s.configure("Horizontal.TScale", background="#FFFFFF")

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg="#FFFFFF", height=72, highlightbackground="#E6EAF0", highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        logo_mark = tk.Canvas(header, width=38, height=38, bg="#FFFFFF", highlightthickness=0)
        logo_mark.create_rounded_rectangle = None
        logo_mark.create_rectangle(2, 2, 36, 36, fill="#275DDB", outline="", width=0)
        logo_mark.create_text(19, 19, text="光", font=("Microsoft YaHei UI", 16, "bold"), fill="white")
        logo_mark.pack(side="left", padx=(22, 10), pady=16)
        title_box = tk.Frame(header, bg="#FFFFFF")
        title_box.pack(side="left", pady=12)
        tk.Label(title_box, text="光影水印", bg="#FFFFFF", fg="#172033", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(title_box, text="PHOTO WATERMARK STUDIO  ·  本地照片元数据水印工具", bg="#FFFFFF", fg="#8792A3", font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))
        tk.Label(header, text="LOCAL · 离线处理", bg="#EAF7F0", fg="#217A4B", font=("Segoe UI", 9, "bold"), padx=10, pady=6).pack(side="right", padx=24, pady=20)

        # Main three-column layout
        body = tk.Frame(self.root, bg="#F3F5F8")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 12))
        body.grid_columnconfigure(0, minsize=238, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, minsize=304, weight=0)
        body.grid_rowconfigure(0, weight=1)

        self._build_assets_panel(body)
        self._build_preview_panel(body)
        self._build_settings_panel(body)

        # Bottom task bar
        bottom = tk.Frame(self.root, bg="#FFFFFF", height=66, highlightbackground="#E6EAF0", highlightthickness=1)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)
        self.status_label = tk.Label(bottom, textvariable=self.status_var, bg="#FFFFFF", fg="#758195", font=("Microsoft YaHei UI", 9), anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=24)
        ttk.Button(bottom, text="保存当前图片", style="Soft.TButton", command=self.save_current).pack(side="right", padx=(8, 12), pady=12)
        ttk.Button(bottom, text="批量导出水印", style="Primary.TButton", command=self.export_all).pack(side="right", padx=(8, 4), pady=10)

    def _build_assets_panel(self, parent):
        panel = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#E4E9F0", highlightthickness=1)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(panel, text="照片素材", bg="#FFFFFF", fg="#172033", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(17, 2))
        tk.Label(panel, text="导入照片后可逐张预览，也可批量套用", bg="#FFFFFF", fg="#8792A3", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=16, pady=(0, 13))
        actions = tk.Frame(panel, bg="#FFFFFF")
        actions.pack(fill="x", padx=13)
        ttk.Button(actions, text="＋ 添加照片", style="Primary.TButton", command=self.add_files).pack(fill="x", pady=(0, 7))
        row = tk.Frame(panel, bg="#FFFFFF")
        row.pack(fill="x", padx=13)
        ttk.Button(row, text="导入文件夹", style="Soft.TButton", command=self.add_folder).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="清空", style="Soft.TButton", command=self.clear_files).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.file_count_label = tk.Label(panel, text="待处理  0 张", bg="#FFFFFF", fg="#5D6B80", font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
        self.file_count_label.pack(fill="x", padx=16, pady=(19, 8))
        list_frame = tk.Frame(panel, bg="#FFFFFF")
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.file_list = tk.Listbox(list_frame, activestyle="none", selectmode=tk.EXTENDED,
                                    bg="#F8FAFC", fg="#344054", selectbackground="#DCE8FF", selectforeground="#1746A2",
                                    font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=1,
                                    highlightbackground="#E7ECF2", relief="flat", exportselection=False)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.file_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Button(panel, text="移除选中照片", style="Soft.TButton", command=self.remove_selected).pack(fill="x", padx=13, pady=(0, 14))

    def _build_preview_panel(self, parent):
        panel = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#E4E9F0", highlightthickness=1)
        panel.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        top = tk.Frame(panel, bg="#FFFFFF")
        top.pack(fill="x", padx=20, pady=(17, 10))
        left = tk.Frame(top, bg="#FFFFFF")
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="实时预览", bg="#FFFFFF", fg="#172033", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        self.preview_name_label = tk.Label(left, text="尚未选择照片", bg="#FFFFFF", fg="#8792A3", font=("Microsoft YaHei UI", 8))
        self.preview_name_label.pack(anchor="w", pady=(3, 0))
        ttk.Button(top, text="刷新预览", style="Soft.TButton", command=self.refresh_preview).pack(side="right")
        canvas_wrap = tk.Frame(panel, bg="#F1F4F8")
        canvas_wrap.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.preview_canvas = tk.Canvas(canvas_wrap, bg="#F1F4F8", highlightthickness=0, bd=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Configure>", self._on_preview_resize)
        self.preview_canvas.create_text(300, 220, text="添加一张照片\n开始设计你的专属水印", fill="#98A2B3",
                                       font=("Microsoft YaHei UI", 13), justify="center", tags="placeholder")

    def _build_settings_panel(self, parent):
        panel = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#E4E9F0", highlightthickness=1)
        panel.grid(row=0, column=2, sticky="nsew")
        tk.Label(panel, text="水印设置", bg="#FFFFFF", fg="#172033", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(17, 13))

        self._field_label(panel, "水印模板")
        self.style_combo = ttk.Combobox(panel, textvariable=self.style_var, values=["经典底栏", "极简叠加", "卡片相框"], state="readonly")
        self.style_combo.pack(fill="x", padx=16, pady=(0, 12))

        self._field_label(panel, "底栏 / 相框配色")
        self.theme_combo = ttk.Combobox(panel, textvariable=self.theme_var, values=["浅色", "深色", "蓝色"], state="readonly")
        self.theme_combo.pack(fill="x", padx=16, pady=(0, 11))

        self._field_label(panel, "品牌 / 摄影署名（留空自动读取相机品牌）")
        brand_entry = ttk.Entry(panel, textvariable=self.brand_var)
        brand_entry.pack(fill="x", padx=16, pady=(0, 10))

        self._field_label(panel, "自定义说明（可选）")
        ttk.Entry(panel, textvariable=self.caption_var).pack(fill="x", padx=16, pady=(0, 12))

        line = tk.Frame(panel, bg="#E9EDF3", height=1)
        line.pack(fill="x", padx=16, pady=(0, 11))
        self._field_label(panel, "自动读取并显示的照片信息")
        checks = tk.Frame(panel, bg="#FFFFFF")
        checks.pack(fill="x", padx=13, pady=(0, 8))
        ttk.Checkbutton(checks, text="相机型号", variable=self.show_camera_var, command=self.refresh_preview).grid(row=0, column=0, sticky="w", padx=3, pady=3)
        ttk.Checkbutton(checks, text="镜头型号", variable=self.show_lens_var, command=self.refresh_preview).grid(row=0, column=1, sticky="w", padx=3, pady=3)
        ttk.Checkbutton(checks, text="曝光参数", variable=self.show_exif_var, command=self.refresh_preview).grid(row=1, column=0, sticky="w", padx=3, pady=3)
        ttk.Checkbutton(checks, text="拍摄时间", variable=self.show_date_var, command=self.refresh_preview).grid(row=1, column=1, sticky="w", padx=3, pady=3)
        ttk.Checkbutton(checks, text="GPS 坐标", variable=self.show_gps_var, command=self.refresh_preview).grid(row=2, column=0, sticky="w", padx=3, pady=3)
        ttk.Checkbutton(checks, text="Logo 旁显示署名", variable=self.show_brand_text_var, command=self.refresh_preview).grid(row=2, column=1, sticky="w", padx=3, pady=3)

        self._field_label(panel, "水印大小")
        scale_row = tk.Frame(panel, bg="#FFFFFF")
        scale_row.pack(fill="x", padx=16, pady=(0, 9))
        ttk.Scale(scale_row, from_=0.65, to=1.6, variable=self.scale_var, command=lambda _v: self._schedule_preview()).pack(side="left", fill="x", expand=True)
        self.scale_label = tk.Label(scale_row, text="100%", bg="#FFFFFF", fg="#5D6B80", font=("Segoe UI", 9), width=5)
        self.scale_label.pack(side="right", padx=(8, 0))

        tk.Frame(panel, bg="#E9EDF3", height=1).pack(fill="x", padx=16, pady=(1, 11))
        self._field_label(panel, "自定义 Logo")
        logo_row = tk.Frame(panel, bg="#FFFFFF")
        logo_row.pack(fill="x", padx=16, pady=(0, 10))
        ttk.Button(logo_row, text="选择图片…", style="Soft.TButton", command=self.choose_logo).pack(side="left")
        ttk.Button(logo_row, text="移除", style="Soft.TButton", command=self.clear_logo).pack(side="left", padx=(6, 0))
        self.logo_name_label = tk.Label(panel, text="未选择 Logo（支持透明 PNG）", bg="#FFFFFF", fg="#8792A3", font=("Microsoft YaHei UI", 8), anchor="w", wraplength=260)
        self.logo_name_label.pack(fill="x", padx=16, pady=(0, 9))

        self._field_label(panel, "导出目录")
        outrow = tk.Frame(panel, bg="#FFFFFF")
        outrow.pack(fill="x", padx=16, pady=(0, 7))
        self.output_label = tk.Label(outrow, text=self.output_dir, bg="#F8FAFC", fg="#657184", font=("Segoe UI", 8), anchor="w", padx=7, pady=7, wraplength=190)
        self.output_label.pack(side="left", fill="x", expand=True)
        ttk.Button(outrow, text="选择", style="Soft.TButton", command=self.choose_output).pack(side="right", padx=(6, 0))
        tk.Label(panel, text="导出为 JPG · 质量", bg="#FFFFFF", fg="#7C8799", font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=16, pady=(2, 2))
        qrow = tk.Frame(panel, bg="#FFFFFF")
        qrow.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Scale(qrow, from_=80, to=100, variable=self.quality_var, command=lambda v: self._set_quality_label(v)).pack(side="left", fill="x", expand=True)
        self.quality_label = tk.Label(qrow, text="95", bg="#FFFFFF", fg="#526176", font=("Segoe UI", 9), width=4)
        self.quality_label.pack(side="right", padx=(8, 0))

    def _field_label(self, parent, text):
        tk.Label(parent, text=text, bg="#FFFFFF", fg="#526176", font=("Microsoft YaHei UI", 8, "bold"), anchor="w").pack(fill="x", padx=16, pady=(0, 5))

    def _bind_events(self):
        self.file_list.bind("<<ListboxSelect>>", self._on_select_file)
        for var in (self.style_var, self.theme_var, self.brand_var, self.caption_var,
                    self.show_camera_var, self.show_lens_var, self.show_exif_var,
                    self.show_date_var, self.show_gps_var, self.show_brand_text_var):
            var.trace_add("write", lambda *_: self._schedule_preview())
        self.scale_var.trace_add("write", lambda *_: self._update_scale_label())

    def _update_scale_label(self):
        self.scale_label.configure(text=f"{int(float(self.scale_var.get()) * 100)}%")
        self._schedule_preview()

    def _set_quality_label(self, value):
        self.quality_label.configure(text=str(int(float(value))))

    def _schedule_preview(self):
        if self._resize_job:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(220, self.refresh_preview)

    def _on_preview_resize(self, _event=None):
        self._schedule_preview()

    def _bind_options(self) -> dict[str, Any]:
        return {
            "style": self.style_var.get(), "theme": self.theme_var.get(),
            "brand": self.brand_var.get(), "caption": self.caption_var.get(),
            "scale": float(self.scale_var.get()), "logo_path": self.logo_path,
            "show_camera": bool(self.show_camera_var.get()), "show_lens": bool(self.show_lens_var.get()),
            "show_exif": bool(self.show_exif_var.get()), "show_date": bool(self.show_date_var.get()),
            "show_gps": bool(self.show_gps_var.get()), "show_brand_text": bool(self.show_brand_text_var.get()),
        }

    def add_files(self):
        paths = filedialog.askopenfilenames(title="选择照片", filetypes=[("照片文件", "*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp"), ("所有文件", "*.*")])
        self._append_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择照片文件夹")
        if not folder:
            return
        paths = []
        for p in Path(folder).rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                paths.append(str(p))
        self._append_paths(sorted(paths))

    def _append_paths(self, paths):
        existing = set(self.files)
        added = 0
        for p in paths:
            p = str(Path(p))
            if p not in existing and Path(p).suffix.lower() in SUPPORTED_EXTS:
                self.files.append(p)
                self.file_list.insert(tk.END, Path(p).name)
                existing.add(p)
                added += 1
        self._update_count()
        if self.files and self.current_path is None:
            self.file_list.selection_clear(0, tk.END)
            self.file_list.selection_set(0)
            self.file_list.activate(0)
            self._select_index(0)
        self.status_var.set(f"已添加 {added} 张照片；共 {len(self.files)} 张待处理。")

    def _update_count(self):
        self.file_count_label.configure(text=f"待处理  {len(self.files)} 张")

    def clear_files(self):
        self.files.clear()
        self.current_path = None
        self.file_list.delete(0, tk.END)
        self._update_count()
        self.preview_name_label.configure(text="尚未选择照片")
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(max(120, self.preview_canvas.winfo_width() // 2), max(120, self.preview_canvas.winfo_height() // 2),
                                       text="添加一张照片\n开始设计你的专属水印", fill="#98A2B3",
                                       font=("Microsoft YaHei UI", 13), justify="center")
        self.status_var.set("素材列表已清空。")

    def remove_selected(self):
        indexes = list(self.file_list.curselection())
        if not indexes:
            return
        for idx in reversed(indexes):
            del self.files[idx]
            self.file_list.delete(idx)
        self.current_path = None
        self._update_count()
        if self.files:
            self.file_list.selection_set(0)
            self._select_index(0)
        else:
            self.clear_files()
        self.status_var.set(f"已移除所选照片；剩余 {len(self.files)} 张。")

    def _on_select_file(self, _event=None):
        selected = self.file_list.curselection()
        if selected:
            self._select_index(selected[0])

    def _select_index(self, idx: int):
        if 0 <= idx < len(self.files):
            self.current_path = self.files[idx]
            self.preview_name_label.configure(text=Path(self.current_path).name)
            self.refresh_preview()

    def choose_logo(self):
        path = filedialog.askopenfilename(title="选择 Logo 图片", filetypes=[("透明或普通图片", "*.png *.webp *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        if path:
            self.logo_path = path
            self.logo_name_label.configure(text=Path(path).name, fg="#526176")
            self.refresh_preview()

    def clear_logo(self):
        self.logo_path = ""
        self.logo_name_label.configure(text="未选择 Logo（支持透明 PNG）", fg="#8792A3")
        self.refresh_preview()

    def choose_output(self):
        path = filedialog.askdirectory(title="选择水印图片导出目录", initialdir=self.output_dir if Path(self.output_dir).exists() else str(Path.home()))
        if path:
            self.output_dir = path
            self.output_label.configure(text=path)

    def refresh_preview(self):
        self._resize_job = None
        self.preview_canvas.delete("all")
        if not self.current_path or not Path(self.current_path).exists():
            self.preview_canvas.create_text(max(120, self.preview_canvas.winfo_width() // 2), max(120, self.preview_canvas.winfo_height() // 2),
                                           text="添加一张照片\n开始设计你的专属水印", fill="#98A2B3",
                                           font=("Microsoft YaHei UI", 13), justify="center")
            return
        try:
            rendered = render_watermark(self.current_path, self._bind_options())
            cw = max(200, self.preview_canvas.winfo_width() - 34)
            ch = max(180, self.preview_canvas.winfo_height() - 34)
            ratio = min(cw / rendered.width, ch / rendered.height)
            size = (max(1, int(rendered.width * ratio)), max(1, int(rendered.height * ratio)))
            view = rendered.resize(size, Image.Resampling.LANCZOS)
            self.current_preview = ImageTk.PhotoImage(view)
            self.preview_canvas.create_image(self.preview_canvas.winfo_width() // 2, self.preview_canvas.winfo_height() // 2,
                                             image=self.current_preview, anchor="center")
            md = read_photo_metadata(self.current_path)
            if not any((md.camera, md.lens, md.focal, md.aperture, md.shutter, md.iso, md.date)):
                self.status_var.set("预览已更新。当前图片没有可读取的 EXIF 参数，可通过自定义说明补充。")
            else:
                self.status_var.set(f"预览已更新。已读取相机信息：{md.camera or md.make or '部分参数'}")
        except Exception as exc:
            self.preview_canvas.create_text(self.preview_canvas.winfo_width() // 2, self.preview_canvas.winfo_height() // 2,
                                           text=f"无法预览此图片\n{exc}", fill="#B42318", font=("Microsoft YaHei UI", 10), justify="center")

    def _save_one(self, path: str, output_dir: str) -> str:
        image = render_watermark(path, self._bind_options())
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"{Path(path).stem}_watermark.jpg"
        # Avoid accidental overwrite when duplicate names come from different folders.
        if out_path.exists() and Path(path).resolve().parent != Path(output_dir).resolve():
            stem = Path(path).stem
            counter = 2
            while (Path(output_dir) / f"{stem}_watermark_{counter}.jpg").exists():
                counter += 1
            out_path = Path(output_dir) / f"{stem}_watermark_{counter}.jpg"
        kwargs: dict[str, Any] = {"quality": int(self.quality_var.get()), "optimize": True, "progressive": True}
        try:
            with Image.open(path) as src:
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

    def save_current(self):
        if not self.current_path:
            messagebox.showinfo("提示", "请先添加并选择一张照片。")
            return
        folder = self.output_dir
        if not folder:
            folder = filedialog.askdirectory(title="选择导出目录")
            if not folder:
                return
        try:
            saved = self._save_one(self.current_path, folder)
            self.status_var.set(f"已保存：{saved}")
            messagebox.showinfo("导出成功", f"水印图片已保存到：\n{saved}")
        except Exception as exc:
            messagebox.showerror("导出失败", f"处理图片时发生错误：\n{exc}")

    def export_all(self):
        if not self.files:
            messagebox.showinfo("提示", "请先添加需要处理的照片。")
            return
        folder = self.output_dir or filedialog.askdirectory(title="选择导出目录")
        if not folder:
            return
        errors: list[str] = []
        succeeded = 0
        total = len(self.files)
        self.root.configure(cursor="watch")
        self.status_var.set(f"正在批量处理 0/{total}…")
        self.root.update_idletasks()
        try:
            for idx, path in enumerate(self.files, start=1):
                try:
                    self._save_one(path, folder)
                    succeeded += 1
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
                self.status_var.set(f"批量处理中 {idx}/{total} · 成功 {succeeded} 张")
                self.root.update_idletasks()
        finally:
            self.root.configure(cursor="")
        if errors:
            details = "\n".join(errors[:8])
            if len(errors) > 8:
                details += f"\n……另有 {len(errors) - 8} 个错误"
            messagebox.showwarning("批量导出完成（部分失败）", f"成功 {succeeded} 张，失败 {len(errors)} 张。\n\n{details}\n\n输出目录：{folder}")
        else:
            messagebox.showinfo("批量导出完成", f"已成功导出 {succeeded} 张照片。\n\n输出目录：{folder}")
        self.status_var.set(f"批量导出完成：成功 {succeeded}/{total} 张。输出目录：{folder}")


def main():
    root = tk.Tk()
    try:
        # Optional high-DPI support on Windows.
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
    except Exception:
        pass
    PhotoWatermarkStudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
