# -*- coding: utf-8 -*-
"""后台批量导出。界面控件只在主线程更新。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from photo_watermark_studio.core.edit_session import merge_photo_overrides
from photo_watermark_studio.core.export_service import export_image


class CancelToken:
    def __init__(self) -> None:
        self.stop = False


class ExportSignals(QObject):
    progress = Signal(int, int, int)
    finished = Signal(int, int, object, int)


class ExportRunnable(QRunnable):
    def __init__(
        self,
        paths: list[str],
        output_dir: str,
        options: dict[str, Any],
        quality: int,
        cancel_token: CancelToken,
        signals: ExportSignals,
        photo_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.paths = list(paths)
        self.output_dir = output_dir
        self.options = dict(options)
        self.quality = int(quality)
        self.cancel_token = cancel_token
        self.signals = signals
        self.photo_overrides = dict(photo_overrides or {})

    def run(self) -> None:
        succeeded = 0
        errors: list[str] = []
        cancelled = 0
        total = len(self.paths)
        try:
            for index, path in enumerate(self.paths, start=1):
                if self.cancel_token.stop:
                    cancelled = total - index + 1
                    break
                try:
                    options = merge_photo_overrides(self.options, path, self.photo_overrides)
                    export_image(path, self.output_dir, options, self.quality)
                    succeeded += 1
                except Exception as exc:
                    errors.append(f"{Path(path).name}: {exc}")
                self.signals.progress.emit(index, total, succeeded)
        except Exception as exc:
            errors.append(str(exc))
        self.signals.finished.emit(succeeded, total, errors, cancelled)
