# -*- coding: utf-8 -*-
"""主窗口：顶栏菜单、三栏工作区和底栏摘要。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
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
from photo_watermark_studio.paths import app_logo_path
from photo_watermark_studio.widgets.photo_list import PhotoListPanel
from photo_watermark_studio.widgets.preview_widget import PreviewPanel
from photo_watermark_studio.widgets.settings_panel import SettingsPanel

APP_NAME = "光影水印 · Photo Watermark Studio"


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        logo = app_logo_path()
        if logo.is_file():
            self.setWindowIcon(QIcon(str(logo)))
        self.suppress_dialogs = False
        self.last_notice = ("", "", "")
        self._output_dir_full = ""
        self._pending_preview = None

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
        mid_layout.setContentsMargins(16, 12, 16, 8)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(10)
        self.splitter.addWidget(self.photo_list)
        self.splitter.addWidget(self.preview)
        self.splitter.addWidget(self.settings)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 4)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([260, 820, 320])
        mid_layout.addWidget(self.splitter)
        outer.addWidget(mid, 1)
        outer.addWidget(self._build_status_bar())
        self.setCentralWidget(root)
        self._build_menus()

        self._connect()
        self.status_label.setText("添加照片开始制作水印。原图不会被修改。")
        self._refresh_output_label()
        self.controller.set_preview_size(*self.preview.viewport_size())
        self.controller._emit_summary()
        self.preview.set_layout_drag_enabled(str(self.controller.document.get("style", "")) == "自定义")
        if self.controller._had_session:
            self.status_label.setText("已恢复上次未完成的单张调整。")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 0, 24, 0)
        layout.setSpacing(10)

        mark = QLabel("光")
        mark.setObjectName("LogoMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(34, 34)
        logo = app_logo_path()
        if logo.is_file():
            pix = QPixmap(str(logo))
            if not pix.isNull():
                mark.setPixmap(
                    pix.scaled(
                        34,
                        34,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                mark.setText("")

        title = QLabel("光影水印")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Photo Watermark Studio  ·  本地照片元数据水印工具")
        subtitle.setObjectName("AppSubtitle")
        for label in (title, subtitle):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        titles.addWidget(title)
        titles.addWidget(subtitle)

        layout.addWidget(mark)
        layout.addLayout(titles)
        layout.setAlignment(titles, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        return header

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        act_add = QAction("添加照片", self)
        act_add.setShortcut(QKeySequence.StandardKey.Open)
        act_add.triggered.connect(self._add_files)
        act_folder = QAction("导入文件夹", self)
        act_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        act_folder.triggered.connect(self._add_folder)
        act_save = QAction("导出当前图片", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self._save_current)
        act_export = QAction("批量导出", self)
        act_export.triggered.connect(self._export_all)
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_add)
        file_menu.addAction(act_folder)
        file_menu.addSeparator()
        file_menu.addAction(act_save)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu("编辑")
        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.triggered.connect(self.controller.undo)
        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.triggered.connect(self.controller.redo)
        act_reset = QAction("重置当前照片调整", self)
        act_reset.triggered.connect(lambda: self.controller.reset_photo_overrides())
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(act_reset)

        view_menu = self.menuBar().addMenu("视图")
        act_fit = QAction("适应窗口", self)
        act_fit.setShortcut(QKeySequence("0"))
        act_fit.triggered.connect(self.preview.fit_in_view)
        act_100 = QAction("100% 查看", self)
        act_100.setShortcut(QKeySequence("1"))
        act_100.triggered.connect(lambda: self.preview.view.set_user_scale(1.0))
        view_menu.addAction(act_fit)
        view_menu.addAction(act_100)

        help_menu = self.menuBar().addMenu("帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 16, 10)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(False)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("StatusSummary")

        self.output_status = QLabel()
        self.output_status.setObjectName("StatusPath")
        self.output_status.setMinimumWidth(140)
        self.output_status.setMaximumWidth(280)

        self.cancel_button = QPushButton("取消后续")
        self.cancel_button.setObjectName("cancelExportButton")
        self.cancel_button.setProperty("role", "soft")
        self.cancel_button.setVisible(False)

        self.save_button = QPushButton("导出当前图片")
        self.save_button.setObjectName("saveCurrentButton")
        self.save_button.setProperty("role", "soft")
        self.save_button.setMinimumWidth(118)

        self.export_button = QPushButton("批量导出水印")
        self.export_button.setObjectName("exportAllButton")
        self.export_button.setProperty("role", "primary")
        self.export_button.setMinimumWidth(118)

        self.summary_label.setMinimumWidth(0)
        self.output_status.setMaximumWidth(220)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.summary_label, 0)
        layout.addWidget(self.output_status, 0)
        layout.addWidget(self.cancel_button, 0)
        layout.addWidget(self.save_button, 0)
        layout.addWidget(self.export_button, 0)
        return bar

    def _connect(self) -> None:
        self.photo_list.addFilesRequested.connect(self._add_files)
        self.photo_list.addFolderRequested.connect(self._add_folder)
        self.photo_list.clearRequested.connect(self._clear_photos)
        self.photo_list.removeRequested.connect(self._remove_selected)
        self.photo_list.selectionChanged.connect(self.controller.select)
        self.photo_list.pathsDropped.connect(self._on_paths_dropped)
        self.photo_list.resetPhotoRequested.connect(self.controller.reset_photo_overrides)
        self.preview.fieldEditRequested.connect(self._on_field_edit_requested)
        self.preview.fieldChanged.connect(self._on_field_changed)
        self.preview.fontFamilyChanged.connect(self._on_font_family_changed)
        self.preview.fontBoldChanged.connect(self._on_font_bold_changed)
        self.preview.fontOpacityChanged.connect(self._on_font_opacity_changed)
        self.preview.fieldPositionChanged.connect(self._on_field_position)
        self.settings.optionsChanged.connect(self._on_settings)
        self.settings.chooseLogoRequested.connect(self._choose_logo)
        self.settings.clearLogoRequested.connect(lambda: self.settings.set_logo_path(""))
        self.settings.chooseOutputRequested.connect(self._choose_output)
        self.save_button.clicked.connect(self._save_current)
        self.export_button.clicked.connect(self._export_all)
        self.cancel_button.clicked.connect(self.controller.cancel_export)

        self.controller.statusChanged.connect(self.status_label.setText)
        self.controller.filesChanged.connect(self._on_files)
        self.controller.currentChanged.connect(self._on_current)
        self.controller.metadataHints.connect(self.settings.set_metadata_placeholders)
        self.controller.previewImage.connect(self._on_preview_image)
        self.controller.previewHits.connect(self._on_preview_hits)
        self.controller.previewSprites.connect(self._on_preview_sprites)
        self.controller.previewMessage.connect(self.preview.show_message)
        self.controller.sourceImage.connect(self.preview.set_source_image)
        self.preview.compareToggled.connect(self.controller.set_compare_mode)
        self.controller.notice.connect(self._on_notice)
        self.controller.exportRunningChanged.connect(self._on_export_running)
        self.controller.editSessionCleared.connect(self._on_edit_session_cleared)
        self.controller.photoStatusesChanged.connect(self._on_statuses)
        self.controller.summaryChanged.connect(self._on_summary)
        self.controller.historyChanged.connect(self._on_history)

    def _on_preview_image(self, image) -> None:
        self._pending_preview = image
        self._pending_sprites: list = []

    def _on_preview_sprites(self, sprites: object) -> None:
        self._pending_sprites = sprites if isinstance(sprites, list) else []

    def _on_preview_hits(self, hits: object) -> None:
        image = self._pending_preview
        if image is None:
            return
        self.preview.set_preview_image(
            image,
            hits if isinstance(hits, list) else [],
            sprites=getattr(self, "_pending_sprites", []),
        )

    def _on_field_position(self, key: str, x: float, y: float) -> None:
        # 直连 controller，面板仅静默同步，避免整表 apply_settings。
        self.controller.apply_field_position(key, x, y)
        self.settings.set_field_position(key, x, y, emit=False)

    def _on_settings(self) -> None:
        state = self.settings.state()
        self.controller.apply_settings(state)
        self._show_output_dir(str(state["output_dir"]))
        custom = str(state.get("style", "")) == "自定义"
        self.preview.set_layout_drag_enabled(custom)

    def _on_files(self, paths: object) -> None:
        items = [str(path) for path in paths] if isinstance(paths, list) else []
        self.photo_list.set_paths(items, self.controller.current_path)

    def _on_current(self, path: str) -> None:
        self.photo_list.set_current_path(path)
        self.preview.set_photo_token(path)
        self.preview.hide_field_editor()

    def _on_statuses(self, mapping: object) -> None:
        if isinstance(mapping, dict):
            self.photo_list.set_statuses({str(k): str(v) for k, v in mapping.items()})
            for path, err in self.controller.photo_errors.items():
                self.photo_list.set_photo_meta(path, error=err)

    def _on_summary(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        total = int(payload.get("total", 0))
        pending = int(payload.get("pending", 0))
        style = str(payload.get("style", ""))
        self.summary_label.setText(f"{total} 张 · {pending} 待处理 · {style}")
        enabled = total > 0
        self.save_button.setEnabled(enabled and not self.controller._exporting)
        self.export_button.setEnabled(enabled and not self.controller._exporting)

    def _on_history(self, can_undo: bool, can_redo: bool) -> None:
        self.act_undo.setEnabled(can_undo)
        self.act_redo.setEnabled(can_redo)

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
        filled = str(session.get("text", "") or "").strip() or exif_text
        self.preview.open_field_editor(
            {
                "key": key,
                "label": label,
                "text": filled,
                "placeholder": exif_text or "照片 EXIF 原文",
                "scale": float(session.get("scale", 1.0)),
                "has_scale": True,
                "font_family": str(session.get("font", "默认")),
                "font_bold": bool(session.get("bold", False)),
                "font_opacity": float(session.get("opacity", 1.0)),
            }
        )

    def _on_field_changed(self, key: str, text: str, scale: object) -> None:
        scale_value = float(scale) if isinstance(scale, (int, float)) else None
        if key in ("brand", "caption"):
            self.settings.apply_field_edit(key, text, scale_value)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_field(key, text, scale_value)

    def _on_font_family_changed(self, key: str, name: str) -> None:
        if key in ("brand", "caption"):
            self.settings.set_field_font(key, name)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_font(key, name)

    def _on_font_bold_changed(self, key: str, bold: bool) -> None:
        if key in ("brand", "caption"):
            self.settings.set_field_bold(key, bold)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_bold(key, bold)

    def _on_font_opacity_changed(self, key: str, opacity: float) -> None:
        if key in ("brand", "caption"):
            self.settings.set_field_opacity(key, opacity)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_opacity(key, opacity)

    def _on_edit_session_cleared(self) -> None:
        self.preview.hide_field_editor()

    def _on_export_running(self, running: bool) -> None:
        self.save_button.setEnabled(not running and bool(self.controller.files))
        self.export_button.setEnabled(not running and bool(self.controller.files))
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
            width = 240
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

    def _on_paths_dropped(self, paths: object) -> None:
        items = [str(p) for p in paths] if isinstance(paths, list) else []
        files: list[str] = []
        for item in items:
            path = Path(item)
            if path.is_dir():
                self.controller.add_folder(str(path))
            elif path.is_file():
                files.append(str(path))
        if files:
            self._remember_browse(files[0])
            self.controller.add_paths(files)

    def _clear_photos(self) -> None:
        if not self.controller.files:
            return
        if not self.suppress_dialogs:
            answer = QMessageBox.question(self, "清空素材", "确定从列表中移除全部照片？不会删除磁盘原图。")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.clear()

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

    def _export_all(self) -> None:
        policy = str(self.settings.state().get("conflict_policy", "number"))
        if policy == "overwrite" and not self.suppress_dialogs:
            answer = QMessageBox.warning(
                self,
                "覆盖确认",
                "当前冲突策略为覆盖已有水印文件。原图不会被覆盖，但同名 *_watermark.* 会被替换。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.controller.export_all()

    def _save_current(self) -> None:
        self.controller.save_current()

    def _about(self) -> None:
        QMessageBox.information(
            self,
            "关于光影水印",
            "光影水印 Photo Watermark Studio 2.0\n本地照片元数据水印工具。\n原图只读，结果另存。",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller._exporting and not self.suppress_dialogs:
            answer = QMessageBox.question(
                self,
                "正在导出",
                "导出仍在进行。关闭将取消后续任务。是否关闭？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.cancel_export()
        self.controller.shutdown()
        event.accept()
