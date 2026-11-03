# -*- coding: utf-8 -*-
"""导入、选中、预览和导出流程。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage
from PIL import Image, ImageOps

from photo_watermark_studio.core.document import WatermarkDocument
from photo_watermark_studio.core.edit_session import EditSessionStore
from photo_watermark_studio.core.export_service import export_image
from photo_watermark_studio.core.history import EditHistory
from photo_watermark_studio.core.metadata import read_photo_metadata
from photo_watermark_studio.core.models import SUPPORTED_EXTS
from photo_watermark_studio.core.renderer import metadata_placeholders
from photo_watermark_studio.core.settings_store import (
    FIELD_SCALE_KEYS,
    OPTION_KEYS,
    TEXT_KEYS,
    coerce_settings,
    load_settings,
)
from photo_watermark_studio.core import settings_store
from photo_watermark_studio.widgets.preview_widget import PLACEHOLDER_TEXT
from photo_watermark_studio.workers.export_worker import CancelToken, ExportRunnable, ExportSignals
from photo_watermark_studio.workers.preview_worker import PreviewRunnable, PreviewSignals


class PhotoController(QObject):
    statusChanged = Signal(str)
    filesChanged = Signal(object)
    currentChanged = Signal(str)
    metadataHints = Signal(object)
    previewImage = Signal(QImage)
    previewHits = Signal(object)
    previewMessage = Signal(str, bool)
    sourceImage = Signal(QImage)
    notice = Signal(str, str, str)
    exportRunningChanged = Signal(bool)
    editSessionCleared = Signal()
    photoStatusesChanged = Signal(object)
    historyChanged = Signal(bool, bool)
    summaryChanged = Signal(object)

    def __init__(
        self,
        settings_path: Path | None = None,
        edit_session_path: Path | None = None,
        restore_session: bool = True,
    ) -> None:
        super().__init__()
        self._settings_path = settings_path
        stored = load_settings(settings_path)
        self.output_dir = str(stored["output_dir"])
        self.browse_dir = str(stored.get("browse_dir") or Path.home())
        self.quality = int(stored["quality"])
        self.conflict_policy = str(stored.get("conflict_policy", "number") or "number")
        self.document = WatermarkDocument(stored)
        self.options = self.document.render_options()
        for key in TEXT_KEYS:
            self.options[key] = ""
        for key in FIELD_SCALE_KEYS:
            self.options[key] = 1.0
        self.edit_session = EditSessionStore(edit_session_path)
        self._had_session = self.edit_session.has_overrides()
        if not restore_session or not self._had_session:
            self.edit_session.clear()
            self._had_session = False
        self.files: list[str] = []
        self.current_path: str | None = None
        self.photo_status: dict[str, str] = {}
        self.photo_errors: dict[str, str] = {}
        self._history = EditHistory()
        self._history.reset(self.document.settings_payload())
        self._request_id = 0
        self._preview_running = False
        self._preview_size = (800, 600)
        self._closing = False
        self._exporting = False
        self._export_token = CancelToken()
        self._active_preview: PreviewRunnable | None = None
        self._active_export: ExportRunnable | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._on_preview_timeout)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_settings)

        self._preview_pool = QThreadPool(self)
        self._preview_pool.setMaxThreadCount(1)
        self._export_pool = QThreadPool(self)
        self._export_pool.setMaxThreadCount(1)

    def render_options(self, photo_path: str | None = None) -> dict[str, Any]:
        base = self.document.render_options()
        base["conflict_policy"] = self.conflict_policy
        merged = self.edit_session.merge_into(base, photo_path or self.current_path)
        # 位置布局暂关闭：合并单张覆盖后仍强制默认位置。
        merged["anchor"] = "bottom_center"
        merged["margin_x"] = 0.0
        merged["margin_y"] = 0.0
        merged["offset_x"] = 0.0
        merged["offset_y"] = 0.0
        if isinstance(merged.get("layout"), dict):
            layout = dict(merged["layout"])
            layout.update(
                {
                    "anchor": "bottom_center",
                    "margin_x": 0.0,
                    "margin_y": 0.0,
                    "offset_x": 0.0,
                    "offset_y": 0.0,
                }
            )
            merged["layout"] = layout
        return merged

    def snapshot(self) -> dict[str, Any]:
        data = self.document.settings_payload()
        data["quality"] = self.quality
        data["output_dir"] = self.output_dir
        data["browse_dir"] = self.browse_dir
        data["conflict_policy"] = self.conflict_policy
        return data

    def save_settings(self) -> None:
        try:
            settings_store.save_settings(self.snapshot(), self._settings_path)
        except OSError as exc:
            self.statusChanged.emit(f"设置未能保存：{exc}")

    def set_browse_dir(self, path: str) -> None:
        candidate = Path(path)
        folder = str(candidate if candidate.is_dir() else candidate.parent)
        if not folder or folder == self.browse_dir:
            return
        self.browse_dir = folder
        self._save_timer.start()

    def apply_settings(self, state: dict[str, Any], *, record_history: bool = True) -> None:
        normalized = coerce_settings(state)
        browse_dir = str(normalized.get("browse_dir") or self.browse_dir)
        next_doc = WatermarkDocument(normalized)
        changed = next_doc.settings_payload() != self.document.settings_payload()
        changed_other = (
            int(normalized["quality"]) != self.quality
            or str(normalized["output_dir"]) != self.output_dir
            or browse_dir != self.browse_dir
            or str(normalized.get("conflict_policy", "number")) != self.conflict_policy
        )
        if not changed and not changed_other:
            return
        self.document = next_doc
        self.options = self.document.render_options()
        self.quality = int(normalized["quality"])
        self.output_dir = str(normalized["output_dir"])
        self.browse_dir = browse_dir
        self.conflict_policy = str(normalized.get("conflict_policy", "number") or "number")
        if changed and record_history:
            self._history.push(self.document.settings_payload())
            self._emit_history()
        if changed:
            self.schedule_preview()
        self._emit_summary()
        self._save_timer.start()

    def apply_layout_offset(self, ox: float, oy: float) -> None:
        # 位置布局功能暂时关闭。
        return

    def apply_edit_session_field(self, field: str, text: str, scale: float | None = None) -> None:
        if not self.current_path:
            return
        self.edit_session.set_field(self.current_path, field, text, scale)
        self._mark_edited(self.current_path)
        self.schedule_preview()
        self._emit_summary()

    def reset_photo_overrides(self, path: str | None = None) -> None:
        target = path or self.current_path
        if not target:
            return
        self.edit_session.clear_photo(target)
        if self.photo_status.get(target) == "edited":
            self.photo_status[target] = "pending"
            self._emit_statuses()
        self.schedule_preview()
        self._emit_summary()

    def clear_edit_session(self) -> None:
        self.edit_session.clear()
        for path, status in list(self.photo_status.items()):
            if status == "edited":
                self.photo_status[path] = "pending"
        self._emit_statuses()
        self.editSessionCleared.emit()
        self.schedule_preview()
        self._emit_summary()

    def undo(self) -> None:
        data = self._history.undo()
        if data is None:
            return
        self.apply_settings({**self.snapshot(), **data}, record_history=False)
        self._emit_history()

    def redo(self) -> None:
        data = self._history.redo()
        if data is None:
            return
        self.apply_settings({**self.snapshot(), **data}, record_history=False)
        self._emit_history()

    def _emit_history(self) -> None:
        self.historyChanged.emit(self._history.can_undo(), self._history.can_redo())

    def _mark_edited(self, path: str) -> None:
        if self.photo_status.get(path) not in ("exporting", "done"):
            self.photo_status[path] = "edited"
            self._emit_statuses()

    def _emit_statuses(self) -> None:
        self.photoStatusesChanged.emit(dict(self.photo_status))

    def _emit_summary(self) -> None:
        pending = sum(1 for p in self.files if self.photo_status.get(p, "pending") in ("pending", "edited"))
        self.summaryChanged.emit(
            {
                "total": len(self.files),
                "pending": pending,
                "selected": 1 if self.current_path else 0,
                "style": str(self.document.get("style", "")),
                "output_dir": self.output_dir,
            }
        )

    def add_paths(self, paths: list[str]) -> None:
        existing = set(self.files)
        added = 0
        skipped = 0
        for raw in paths:
            path = str(Path(raw))
            suffix = Path(path).suffix.lower()
            if suffix not in SUPPORTED_EXTS or not Path(path).is_file():
                skipped += 1
                continue
            if path in existing:
                continue
            self.files.append(path)
            existing.add(path)
            self.photo_status[path] = "edited" if self.edit_session.has_overrides(path) else "pending"
            added += 1
        self.filesChanged.emit(list(self.files))
        self._emit_statuses()
        self._emit_summary()
        if self.current_path is None and self.files:
            self.select(self.files[0])
        if added:
            message = f"已添加 {added} 张照片；共 {len(self.files)} 张待处理。"
            if skipped:
                message += f" 已跳过 {skipped} 个不支持的文件。"
        elif skipped:
            message = "没有可添加的照片。支持 JPG、PNG、WEBP、TIFF、BMP。"
        else:
            message = f"这些照片已在列表中。共 {len(self.files)} 张待处理。"
        self.statusChanged.emit(message)

    def add_folder(self, folder: str) -> None:
        if not folder:
            return
        root = Path(folder)
        if not root.is_dir():
            self.notice.emit("warn", "提示", "所选文件夹不存在。")
            return
        paths = [
            str(item)
            for item in root.rglob("*")
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTS
        ]
        self.add_paths(sorted(paths))

    def remove_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        remove = set(paths)
        self.files = [path for path in self.files if path not in remove]
        for path in remove:
            self.photo_status.pop(path, None)
            self.photo_errors.pop(path, None)
            self.edit_session.clear_photo(path)
        self.current_path = self.files[0] if self.files else None
        self.filesChanged.emit(list(self.files))
        self.currentChanged.emit(self.current_path or "")
        self._emit_metadata_hints()
        self._emit_statuses()
        self._emit_summary()
        self._request_id += 1
        self._preview_timer.stop()
        if not self._preview_running:
            self._start_preview(self._request_id)
        if self.files:
            self.statusChanged.emit(f"已移除所选照片；剩余 {len(self.files)} 张。")
        else:
            self.statusChanged.emit("素材列表已清空。")

    def clear(self) -> None:
        self.files.clear()
        self.photo_status.clear()
        self.photo_errors.clear()
        self.current_path = None
        self._request_id += 1
        self._preview_timer.stop()
        self.filesChanged.emit([])
        self.currentChanged.emit("")
        self.metadataHints.emit({})
        self.previewMessage.emit(PLACEHOLDER_TEXT, False)
        self._emit_statuses()
        self._emit_summary()
        self.statusChanged.emit("素材列表已清空。")

    def select(self, path: str | None) -> None:
        cleaned = path or None
        if cleaned == self.current_path:
            return
        self.current_path = cleaned
        self.currentChanged.emit(cleaned or "")
        self._emit_metadata_hints()
        self._emit_summary()
        self._request_id += 1
        self._preview_timer.stop()
        if not self._preview_running:
            self._start_preview(self._request_id)

    def _emit_metadata_hints(self) -> None:
        if not self.current_path or not Path(self.current_path).is_file():
            self.metadataHints.emit({})
            return
        md = read_photo_metadata(self.current_path)
        self.metadataHints.emit(metadata_placeholders(md))

    def set_preview_size(self, width: int, height: int) -> None:
        # 预览已改为高分辨率位图，窗口尺寸变化不再重渲（避免缩放被重置、也避免糊图）。
        size = (max(200, int(width)), max(180, int(height)))
        self._preview_size = size

    def schedule_preview(self) -> None:
        self._request_id += 1
        self._preview_timer.start(220)

    def refresh_preview(self) -> None:
        self._request_id += 1
        self._preview_timer.stop()
        if not self._preview_running:
            self._start_preview(self._request_id)

    def save_current(self) -> None:
        if not self.current_path:
            self.notice.emit("info", "提示", "请先添加并选择一张照片。")
            return
        if not str(self.output_dir).strip():
            self.notice.emit("info", "提示", "请先选择导出目录。")
            return
        path = self.current_path
        self.photo_status[path] = "exporting"
        self._emit_statuses()
        self.statusChanged.emit("正在导出当前照片…")
        try:
            options = self.render_options(path)
            saved = export_image(path, self.output_dir, options, self.quality)
        except Exception as exc:
            self.photo_status[path] = "failed"
            self.photo_errors[path] = str(exc)
            self._emit_statuses()
            self.statusChanged.emit(f"导出失败：{exc}")
            self.notice.emit("error", "导出失败", f"处理图片时发生错误：\n{exc}")
            return
        self.photo_status[path] = "done"
        self.photo_errors.pop(path, None)
        self.edit_session.clear_photo(path)
        self._emit_statuses()
        self._emit_summary()
        self.statusChanged.emit(f"已保存：{saved}")
        self.notice.emit("info", "导出成功", f"水印图片已保存到：\n{saved}")

    def export_all(self) -> None:
        if self._exporting:
            return
        if not self.files:
            self.notice.emit("info", "提示", "请先添加需要处理的照片。")
            return
        if not str(self.output_dir).strip():
            self.notice.emit("info", "提示", "请先选择导出目录。")
            return
        self._exporting = True
        self._export_token = CancelToken()
        self.exportRunningChanged.emit(True)
        for path in self.files:
            self.photo_status[path] = "exporting"
        self._emit_statuses()
        signals = ExportSignals(self)
        signals.progress.connect(self._on_export_progress)
        signals.finished.connect(self._on_export_finished)
        base_options = self.document.render_options()
        for key in TEXT_KEYS:
            base_options[key] = ""
        for key in FIELD_SCALE_KEYS:
            base_options[key] = 1.0
        base_options["conflict_policy"] = self.conflict_policy
        runnable = ExportRunnable(
            self.files,
            self.output_dir,
            base_options,
            self.quality,
            self._export_token,
            signals,
            self.edit_session.snapshot_photos(),
        )
        self._active_export = runnable
        self._export_pool.start(runnable)
        self.statusChanged.emit(f"正在批量处理 0/{len(self.files)}…")

    def cancel_export(self) -> None:
        if not self._exporting:
            return
        self._export_token.stop = True
        self.statusChanged.emit("正在取消后续任务…")

    def shutdown(self) -> None:
        self._closing = True
        self._request_id += 1
        self._preview_timer.stop()
        self._save_timer.stop()
        self.save_settings()
        # 保留未导出的单张覆盖，下次可恢复；完整清空留给用户主动清空。
        self._export_token.stop = True
        self._preview_pool.waitForDone()
        self._export_pool.waitForDone()
        QCoreApplication.processEvents()

    def _on_preview_timeout(self) -> None:
        if self._closing or self._preview_running:
            return
        self._start_preview(self._request_id)

    def _start_preview(self, request_id: int) -> None:
        if self._closing:
            return
        if self._preview_running:
            return
        if not self.current_path or not Path(self.current_path).exists():
            self.previewMessage.emit(PLACEHOLDER_TEXT, False)
            if self.current_path:
                self.statusChanged.emit("找不到所选照片，可能已被移动或删除。")
            return
        self._preview_running = True
        self._emit_source_image(self.current_path)
        signals = PreviewSignals(self)
        signals.finished.connect(self._on_preview_finished)
        width, height = self._preview_size
        runnable = PreviewRunnable(
            request_id,
            self.current_path,
            self.render_options(self.current_path),
            width,
            height,
            signals,
        )
        self._active_preview = runnable
        self._preview_pool.start(runnable)

    def _emit_source_image(self, path: str) -> None:
        try:
            from photo_watermark_studio.workers.preview_worker import PREVIEW_MAX_EDGE, preview_scale_for

            with Image.open(path) as src:
                image = ImageOps.exif_transpose(src).convert("RGB")
                scale = preview_scale_for(image.size, PREVIEW_MAX_EDGE)
                if scale < 1.0:
                    image = image.resize(
                        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                data = image.tobytes("raw", "RGB")
                qimage = QImage(
                    data, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
                ).copy()
            self.sourceImage.emit(qimage)
        except Exception:
            self.sourceImage.emit(QImage())

    def _on_preview_finished(
        self,
        request_id: int,
        image: QImage,
        hits: object,
        error: str,
        status: str,
    ) -> None:
        self._preview_running = False
        self._active_preview = None
        sender = self.sender()
        if sender is not None:
            sender.deleteLater()
        if self._closing:
            return
        if request_id != self._request_id:
            self._start_preview(self._request_id)
            return
        if error:
            self.previewHits.emit([])
            self.previewMessage.emit(f"无法预览此图片\n{error}", True)
            return
        if image.isNull():
            self.previewHits.emit([])
            self.previewMessage.emit(PLACEHOLDER_TEXT, False)
            return
        self.previewImage.emit(image)
        self.previewHits.emit(hits if isinstance(hits, list) else [])
        if status:
            self.statusChanged.emit(status)

    def _on_export_progress(self, index: int, total: int, succeeded: int) -> None:
        if 0 < index <= len(self.files):
            path = self.files[index - 1]
            # 进度回调时该张已处理完（成功或失败在 finished 汇总）。
            if self.photo_status.get(path) == "exporting":
                self.photo_status[path] = "done" if succeeded >= index else self.photo_status.get(path, "pending")
        self.statusChanged.emit(f"批量处理中 {index}/{total} · 成功 {succeeded} 张")
        self._emit_summary()

    def _on_export_finished(self, succeeded: int, total: int, errors: object, cancelled: int) -> None:
        self._exporting = False
        self._active_export = None
        sender = self.sender()
        if sender is not None:
            sender.deleteLater()
        if self._closing:
            return
        error_list = [str(item) for item in errors] if isinstance(errors, list) else []
        failed_names = {item.split(":", 1)[0].strip() for item in error_list}
        for path in self.files:
            name = Path(path).name
            if name in failed_names:
                self.photo_status[path] = "failed"
                for err in error_list:
                    if err.startswith(name):
                        self.photo_errors[path] = err
                        break
            elif self.photo_status.get(path) == "exporting":
                if cancelled:
                    self.photo_status[path] = "pending"
                else:
                    self.photo_status[path] = "done"
        self.clear_edit_session()
        folder = self.output_dir
        self.exportRunningChanged.emit(False)
        self._emit_statuses()
        self._emit_summary()
        if cancelled:
            self.notice.emit(
                "warn",
                "批量导出已取消",
                f"已停止后续任务。成功 {succeeded} 张，失败 {len(error_list)} 张，未处理 {cancelled} 张。\n\n输出目录：{folder}",
            )
            self.statusChanged.emit(f"批量导出已取消：成功 {succeeded}/{total} 张。输出目录：{folder}")
        elif error_list:
            details = "\n".join(error_list[:8])
            if len(error_list) > 8:
                details += f"\n……另有 {len(error_list) - 8} 个错误"
            self.notice.emit(
                "warn",
                "批量导出完成（部分失败）",
                f"成功 {succeeded} 张，失败 {len(error_list)} 张。\n\n{details}\n\n输出目录：{folder}",
            )
            self.statusChanged.emit(f"批量导出完成：成功 {succeeded}/{total} 张。输出目录：{folder}")
        else:
            self.notice.emit("info", "批量导出完成", f"已成功导出 {succeeded} 张照片。\n\n输出目录：{folder}")
            self.statusChanged.emit(f"批量导出完成：成功 {succeeded}/{total} 张。输出目录：{folder}")
