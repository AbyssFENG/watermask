# -*- coding: utf-8 -*-
"""PySide6 应用入口。"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from photo_watermark_studio.qt_bootstrap import ensure_qt_dlls

ensure_qt_dlls()

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from photo_watermark_studio.app_window import MainWindow
from photo_watermark_studio.paths import app_logo_path, load_stylesheet


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("停下时光 Studio")
    app.setOrganizationName("TingxiaStudio")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    logo = app_logo_path()
    if logo.is_file():
        app.setWindowIcon(QIcon(str(logo)))
    stylesheet = load_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
