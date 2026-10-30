# -*- coding: utf-8 -*-
"""主窗口：顶栏、三栏工作区和底栏。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.controllers.photo_controller import PhotoController
from photo_watermark_studio.widgets.photo_list import PhotoListPanel
from photo_watermark_studio.widgets.preview_widget import PreviewPanel
from photo_watermark_studio.widgets.settings_panel import SettingsPanel

APP_NAME = "光影水印 · Photo Watermark Studio"


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)
        self.setMinimumSize(1120, 720)
        self.suppress_dialogs = False
        self.last_notice = ("", "", "")
        self._output_dir_full = ""

        self.controller = PhotoController(settings_path)
        self.photo_list = PhotoListPanel()
        self.preview = PreviewPanel()
        self.settings = SettingsPanel()
        self.settings.set_state(self.controller.snapshot())
        self._output_dir_full = self.settings.state()["output_dir"]

        root = QWidget()
        root.setObjectName("AppRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(18, 16, 18, 12)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        self.splitter.addWidget(self.photo_list)
        self.splitter.addWidget(self.preview)
        self.splitter.addWidget(self.settings)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([260, 780, 340])
        mid_layout.addWidget(self.splitter)
        outer.addWidget(mid, 1)
        outer.addWidget(self._build_status_bar())
        self.setCentralWidget(root)

        self._connect()
        self.status_label.setText("添加照片开始制作水印。原图不会被修改。")
        self._refresh_output_label()
        self.controller.set_preview_size(*self.preview.viewport_size())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(72)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 0, 24, 0)
        layout.setSpacing(10)

        mark = QLabel("光")
        mark.setObjectName("LogoMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(38, 38)

        title = QLabel("光影水印")
        title.setObjectName("AppTitle")
        subtitle = QLabel("PHOTO WATERMARK STUDIO  ·  本地照片元数据水印工具")
        subtitle.setObjectName("AppSubtitle")
        for label in (title, subtitle):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        titles.addWidget(title)
        titles.addWidget(subtitle)

        layout.addWidget(mark)
        layout.addLayout(titles)
        layout.setAlignment(titles, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        return header

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(66)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 16, 10)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(False)

        self.output_status = QLabel()
        self.output_status.setObjectName("StatusPath")
        self.output_status.setMinimumWidth(160)
        self.output_status.setMaximumWidth(320)

        self.cancel_button = QPushButton("取消后续")
        self.cancel_button.setObjectName("cancelExportButton")
        self.cancel_button.setProperty("role", "soft")
        self.cancel_button.setVisible(False)

        self.save_button = QPushButton("保存当前图片")
        self.save_button.setObjectName("saveCurrentButton")
        self.save_button.setProperty("role", "soft")

        self.export_button = QPushButton("批量导出水印")
        self.export_button.setObjectName("exportAllButton")
        self.export_button.setProperty("role", "primary")

        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.output_status)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.save_button)
        layout.addWidget(self.export_button)
        return bar

    def _connect(self) -> None:
        self.photo_list.addFilesRequested.connect(self._add_files)
        self.photo_list.addFolderRequested.connect(self._add_folder)
        self.photo_list.clearRequested.connect(self.controller.clear)
        self.photo_list.removeRequested.connect(self._remove_selected)
        self.photo_list.selectionChanged.connect(self.controller.select)
        self.preview.refreshRequested.connect(self.controller.refresh_preview)
        self.preview.resized.connect(self.controller.set_preview_size)
        self.preview.fieldEditRequested.connect(self._on_field_edit_requested)
        self.preview.fieldChanged.connect(self._on_field_changed)
        self.settings.optionsChanged.connect(self._on_settings)
        self.settings.choose_logo_button.clicked.connect(self._choose_logo)
        self.settings.clear_logo_button.clicked.connect(lambda: self.settings.set_logo_path(""))
        self.settings.choose_output_button.clicked.connect(self._choose_output)
        self.save_button.clicked.connect(self._save_current)
        self.export_button.clicked.connect(self.controller.export_all)
        self.cancel_button.clicked.connect(self.controller.cancel_export)

        self.controller.statusChanged.connect(self.status_label.setText)
        self.controller.filesChanged.connect(self._on_files)
        self.controller.currentChanged.connect(self._on_current)
        self.controller.metadataHints.connect(self.settings.set_metadata_placeholders)
        self.controller.previewImage.connect(self.preview.show_image)
        self.controller.previewHits.connect(self.preview.set_hits)
        self.controller.previewMessage.connect(self.preview.show_message)
        self.controller.notice.connect(self._on_notice)
        self.controller.exportRunningChanged.connect(self._on_export_running)
        self.controller.editSessionCleared.connect(self._on_edit_session_cleared)

    def _on_settings(self) -> None:
        state = self.settings.state()
        self.controller.apply_settings(state)
        self._show_output_dir(str(state["output_dir"]))

    def _on_files(self, paths: object) -> None:
        items = [str(path) for path in paths] if isinstance(paths, list) else []
        self.photo_list.set_paths(items, self.controller.current_path)

    def _on_current(self, path: str) -> None:
        self.preview.set_filename(Path(path).name if path else "尚未选择照片")
        self.photo_list.set_current_path(path)
        # 换图时关掉上一张的编辑条，避免文案串到下一张。
        self.preview.hide_editor()

    def _on_field_edit_requested(self, key: str) -> None:
        from photo_watermark_studio.core.renderer import FIELD_LABELS

        label = FIELD_LABELS.get(key, key)
        if key in ("brand", "caption"):
            state = self.settings.field_editor_state(key)
            state["label"] = label
            self.preview.open_field_editor(state)
            return
        if key not in ("camera", "lens", "exif", "date", "gps"):
            return
        current = self.controller.current_path
        session = self.controller.edit_session.get_field(current, key)
        exif_text = self.settings.placeholders().get(key, "")
        # 已有临时修改用临时内容；否则把 EXIF 原文填进输入框。
        filled = str(session.get("text", "") or "").strip() or exif_text
        self.preview.open_field_editor(
            {
                "key": key,
                "label": label,
                "text": filled,
                "placeholder": exif_text or "照片 EXIF 原文",
                "scale": float(session.get("scale", 1.0)),
                "has_scale": True,
            }
        )

    def _on_field_changed(self, key: str, text: str, scale: object) -> None:
        scale_value = float(scale) if isinstance(scale, (int, float)) else None
        if key in ("brand", "caption"):
            self.settings.apply_field_edit(key, text, scale_value)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_field(key, text, scale_value)

    def _on_edit_session_cleared(self) -> None:
        self.preview.hide_editor()

    def _on_export_running(self, running: bool) -> None:
        self.save_button.setEnabled(not running)
        self.export_button.setEnabled(not running)
        self.cancel_button.setVisible(running)

    def _on_notice(self, level: str, title: str, message: str) -> None:
        self.last_notice = (level, title, message)
        if self.suppress_dialogs:
            return
        if level == "error":
            QMessageBox.critical(self, title, message)
        elif level == "warn":
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.information(self, title, message)

    def _show_output_dir(self, path: str) -> None:
        self._output_dir_full = path
        self._refresh_output_label()

    def _refresh_output_label(self) -> None:
        text = self._output_dir_full
        self.output_status.setToolTip(text)
        width = self.output_status.width()
        if width < 40:
            width = 280
        self.output_status.setText(
            self.output_status.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        )

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._refresh_output_label()

    def _browse_dir(self) -> str:
        candidate = str(self.controller.browse_dir or "")
        if candidate and Path(candidate).exists():
            return candidate
        return str(Path.home())

    def _remember_browse(self, path: str) -> None:
        self.controller.set_browse_dir(path)

    def _add_files(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "选择照片",
            self._browse_dir(),
            "照片文件 (*.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp);;所有文件 (*.*)",
        )
        if paths:
            self._remember_browse(paths[0])
            self.controller.add_paths(paths)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择照片文件夹", self._browse_dir())
        if folder:
            self._remember_browse(folder)
            self.controller.add_folder(folder)

    def _remove_selected(self) -> None:
        self.controller.remove_paths(self.photo_list.selected_paths())

    def _choose_logo(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择 Logo 图片",
            self._browse_dir(),
            "透明或普通图片 (*.png *.webp *.jpg *.jpeg *.bmp);;所有文件 (*.*)",
        )
        if path:
            self._remember_browse(path)
            self.settings.set_logo_path(path)

    def _choose_output(self) -> None:
        current = str(self.settings.state()["output_dir"])
        start = current if Path(current).exists() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择水印图片导出目录", start)
        if path:
            self.settings.set_output_dir(path)

    def _save_current(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.controller.save_current()
        finally:
            QApplication.restoreOverrideCursor()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.controller.shutdown()
        event.accept()
