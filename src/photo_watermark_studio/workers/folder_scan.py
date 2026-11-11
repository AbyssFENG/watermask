# -*- coding: utf-8 -*-
"""后台扫描文件夹里的照片，避免大目录卡住界面。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from photo_watermark_studio.core.models import SUPPORTED_EXTS


def list_supported_images(folder: str) -> list[str]:
    """递归列出文件夹中支持的图片，按路径排序。"""
    root = Path(folder)
    if not root.is_dir():
        return []
    try:
        return sorted(
            str(item)
            for item in root.rglob("*")
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTS
        )
    except OSError:
        return []


class FolderScanSignals(QObject):
    finished = Signal(int, object)


class FolderScanRunnable(QRunnable):
    def __init__(self, request_id: int, folder: str, signals: FolderScanSignals) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.folder = folder
        self.signals = signals

    def run(self) -> None:
        self.signals.finished.emit(self.request_id, list_supported_images(self.folder))
