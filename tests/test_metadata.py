# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
_existing = sys.modules.get("photo_watermark_studio")
if _existing is not None and not hasattr(_existing, "__path__"):
    del sys.modules["photo_watermark_studio"]

from PIL import Image
from PIL.ExifTags import IFD
from PIL.TiffImagePlugin import IFDRational

from photo_watermark_studio.core.metadata import (
    _as_float,
    _clean_exif_text,
    _format_aperture,
    _format_datetime,
    _format_focal,
    _format_shutter,
    _gps_to_decimal,
    read_photo_metadata,
)
from photo_watermark_studio.core.models import PhotoMetadata


class FormatTests(unittest.TestCase):
    def test_as_float_accepts_rational_and_pair(self) -> None:
        self.assertEqual(_as_float(IFDRational(1, 250)), 0.004)
        self.assertEqual(_as_float((1, 4)), 0.25)
        self.assertIsNone(_as_float("nope"))
        self.assertIsNone(_as_float((1, 0)))

    def test_focal_aperture_and_shutter(self) -> None:
        self.assertEqual(_format_focal(50), "50mm")
        self.assertEqual(_format_focal(None), "")
        self.assertEqual(_format_aperture(2.8), "F2.8")
        self.assertEqual(_format_aperture(11), "F11")
        self.assertEqual(_format_shutter(1), "1s")
        self.assertEqual(_format_shutter(2.5), "2.5s")
        self.assertEqual(_format_shutter(1 / 250), "1/250s")
        self.assertEqual(_format_shutter(0), "")

    def test_datetime_and_gps(self) -> None:
        self.assertEqual(_format_datetime("2024:05:01 12:30:00"), "2024.05.01  12:30:00")
        self.assertEqual(_format_datetime("2024:05:01"), "2024.05.01")
        self.assertEqual(_format_datetime(""), "")
        self.assertEqual(_format_datetime("not-a-date"), "not-a-date")
        lat = _gps_to_decimal((30, 15, 0), "S")
        lon = _gps_to_decimal((120, 30, 0), "W")
        self.assertAlmostEqual(lat, -30.25)
        self.assertAlmostEqual(lon, -120.5)
        self.assertIsNone(_gps_to_decimal(None, "N"))

    def test_brand_mapping(self) -> None:
        self.assertEqual(PhotoMetadata(make="NIKON").brand, "Nikon")
        self.assertEqual(PhotoMetadata(make="OM Digital Solutions").brand, "OM SYSTEM")
        self.assertEqual(PhotoMetadata(make="Hasselblad").brand, "Hasselblad")
        self.assertEqual(PhotoMetadata().brand, "")

    def test_clean_exif_text_strips_null_padding(self) -> None:
        self.assertEqual(
            _clean_exif_text("NIKKOR Z 24-120mm f/4 S" + ("\x00" * 20)),
            "NIKKOR Z 24-120mm f/4 S",
        )
        self.assertEqual(_clean_exif_text(b"NIKKOR Z\x00\x00\x00"), "NIKKOR Z")
        self.assertEqual(_clean_exif_text("  lens \x07\x08 name  "), "lens  name")
        self.assertEqual(_clean_exif_text(None), "")


class ReadMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_present_exif_fields(self) -> None:
        path = self.folder / "exif.jpg"
        image = Image.new("RGB", (32, 24), (20, 30, 40))
        exif = image.getexif()
        exif[271] = "NIKON"
        exif[272] = "NIKON Z 6"
        exif_ifd = exif.get_ifd(IFD.Exif)
        exif_ifd[42036] = "NIKKOR Z 24-70mm f/2.8 S"
        exif_ifd[37386] = IFDRational(50, 1)
        exif_ifd[33437] = IFDRational(28, 10)
        exif_ifd[33434] = IFDRational(1, 250)
        exif_ifd[34855] = 200
        exif_ifd[36867] = "2024:05:01 12:30:00"
        gps = exif.get_ifd(IFD.GPSInfo)
        gps[1] = "N"
        gps[2] = (IFDRational(30, 1), IFDRational(15, 1), IFDRational(0, 1))
        gps[3] = "E"
        gps[4] = (IFDRational(120, 1), IFDRational(30, 1), IFDRational(0, 1))
        image.save(path, format="JPEG", exif=exif)

        metadata = read_photo_metadata(path)
        self.assertEqual(metadata.camera, "NIKON Z 6")
        self.assertEqual(metadata.brand, "Nikon")
        self.assertEqual(metadata.lens, "NIKKOR Z 24-70MM F/2.8 S")
        self.assertEqual(metadata.focal, "50mm")
        self.assertEqual(metadata.aperture, "F2.8")
        self.assertEqual(metadata.shutter, "1/250s")
        self.assertEqual(metadata.iso, "200")
        self.assertEqual(metadata.date, "2024.05.01  12:30:00")
        self.assertEqual(metadata.gps, "30.25000, 120.50000")

    def test_lens_null_padding_is_removed(self) -> None:
        path = self.folder / "lens-pad.jpg"
        image = Image.new("RGB", (32, 24), (20, 30, 40))
        exif = image.getexif()
        exif_ifd = exif.get_ifd(IFD.Exif)
        exif_ifd[42036] = "NIKKOR Z 24-120mm f/4 S" + ("\x00" * 24)
        image.save(path, format="JPEG", exif=exif)
        metadata = read_photo_metadata(path)
        self.assertEqual(metadata.lens, "NIKKOR Z 24-120MM F/4 S")
        self.assertNotIn("\x00", metadata.lens)
        self.assertTrue(metadata.lens.isprintable())

    def test_missing_or_damaged_image_returns_empty_fields(self) -> None:
        folder = self.folder
        plain = folder / "plain.png"
        Image.new("RGB", (8, 8), "white").save(plain)
        empty = read_photo_metadata(plain)
        self.assertEqual(empty, PhotoMetadata())

        damaged = folder / "damaged.jpg"
        damaged.write_bytes(b"this is not a photo")
        self.assertEqual(read_photo_metadata(damaged), PhotoMetadata())
        self.assertEqual(read_photo_metadata(folder / "missing.jpg"), PhotoMetadata())


class CoreBoundaryTests(unittest.TestCase):
    def test_core_modules_do_not_import_gui_libraries(self) -> None:
        core = _SRC / "photo_watermark_studio" / "core"
        for path in core.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                self.assertFalse(any(name in {"tkinter", "PySide6", "PyQt6"} for name in names), path.name)


if __name__ == "__main__":
    unittest.main()
