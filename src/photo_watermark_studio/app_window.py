# -*- coding: utf-8 -*-
"""主窗口：顶栏菜单、三栏工作区和底栏摘要。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.controllers.photo_controller import PhotoController
from photo_watermark_studio.core import settings_store, template_store
from photo_watermark_studio.paths import app_logo_path
from photo_watermark_studio.widgets.photo_list import PhotoListPanel
from photo_watermark_studio.widgets.preview_widget import PreviewPanel
from photo_watermark_studio.widgets.settings_panel import SettingsPanel
from photo_watermark_studio.widgets.studio_sidebar import StudioSidebar

APP_NAME = "停下时光 · Studio"


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
        self.photo_list.set_rail_mode(True)
        self.preview = PreviewPanel()
        self.settings = SettingsPanel()
        self.settings.setMaximumWidth(350)
        self.sidebar = StudioSidebar()
        if settings_path is not None:
            self.settings.set_templates_path(Path(settings_path).with_name("templates.json"))
        self.settings.set_state(self.controller.snapshot())
        self._output_dir_full = self.settings.state()["output_dir"]

        root = QWidget()
        root.setObjectName("AppRoot")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 4)
        outer.setSpacing(0)
        self.topbar = self._build_header()
        outer.addWidget(self.topbar)
        outer.addSpacing(12)
        outer.addWidget(self._build_studio(), 1)
        outer.addSpacing(6)
        outer.addWidget(self._build_status_bar())
        self.setCentralWidget(root)
        self._build_menus()
        self.menuBar().setVisible(False)
        for widget in (
            self.topbar,
            self.sidebar,
            self.workspace_head,
            self.preview,
            self.photo_list,
            self.settings,
        ):
            self._add_shadow(widget)

        self._connect()
        self.status_label.setText("添加照片开始制作水印。原图不会被修改。")
        self._refresh_output_label()
        self.controller.set_preview_size(*self.preview.viewport_size())
        self.controller._emit_summary()
        self.preview.set_layout_drag_enabled(str(self.controller.document.get("style", "")) == "自定义")
        self.sidebar.set_style(str(self.controller.document.get("style", "")))
        self._refresh_recent_templates()
        if self.controller._had_session:
            self.status_label.setText("已恢复上次未完成的单张调整。")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("TopBar")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 0, 24, 0)
        layout.setSpacing(10)

        mark = QLabel("✦")
        mark.setObjectName("LogoMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(34, 34)

        title = QLabel("停下时光")
        title.setObjectName("AppTitle")
        subtitle = QLabel("PHOTO STUDIO")
        subtitle.setObjectName("AppSubtitle")
        for label in (title, subtitle):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        titles = QHBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(8)
        titles.addWidget(title)
        titles.addWidget(subtitle)

        layout.addWidget(mark)
        layout.addLayout(titles)
        layout.setAlignment(titles, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(28)
        self.nav_edit = QPushButton("编辑工作台")
        self.nav_templates = QPushButton("我的模板")
        self.nav_batch = QPushButton("批量处理")
        for button in (self.nav_edit, self.nav_templates, self.nav_batch):
            button.setObjectName("TopNav")
            button.setCheckable(True)
            layout.addWidget(button)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for button in (self.nav_edit, self.nav_templates, self.nav_batch):
            self.nav_group.addButton(button)
        self.nav_edit.setChecked(True)
        layout.addStretch(1)
        self.saved_label = QLabel("●  所有修改已保存")
        self.saved_label.setObjectName("SavedState")
        self.save_template_button = QPushButton("保存为模板")
        self.save_template_button.setObjectName("saveTemplateButton")
        self.save_template_button.setProperty("role", "soft")
        self.save_button = QPushButton("导出当前")
        self.save_button.setObjectName("saveCurrentButton")
        self.save_button.setProperty("role", "soft")
        self.export_button = QPushButton("导出照片 ↗")
        self.export_button.setObjectName("exportAllButton")
        self.export_button.setProperty("role", "primary")
        self.avatar_label = QLabel("TJ")
        self.avatar_label.setObjectName("Avatar")
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setFixedSize(30, 30)
        layout.addWidget(self.saved_label)
        layout.addWidget(self.save_template_button)
        layout.addWidget(self.save_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.avatar_label)
        return header

    @staticmethod
    def _add_shadow(widget: QWidget) -> None:
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(34)
        effect.setOffset(0, 10)
        effect.setColor(QColor(41, 48, 75, 30))
        widget.setGraphicsEffect(effect)

    def _build_studio(self) -> QWidget:
        studio = QWidget()
        studio.setObjectName("StudioBody")
        layout = QHBoxLayout(studio)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        center = QWidget()
        center.setObjectName("CenterWorkspace")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        self.workspace_head = QWidget()
        self.workspace_head.setObjectName("WorkspaceHead")
        head = QHBoxLayout(self.workspace_head)
        head.setContentsMargins(16, 7, 12, 7)
        file_box = QVBoxLayout()
        file_box.setContentsMargins(0, 0, 0, 0)
        file_box.setSpacing(0)
        self.file_title = QLabel("尚未选择照片")
        self.file_title.setObjectName("FileTitle")
        self.file_subtitle = QLabel("导入照片开始编辑")
        self.file_subtitle.setObjectName("FileSubtitle")
        file_box.addWidget(self.file_title)
        file_box.addWidget(self.file_subtitle)
        head.addLayout(file_box)
        head.addStretch(1)
        self.undo_button = QPushButton("↶")
        self.undo_button.setObjectName("IconButton")
        self.undo_button.setToolTip("撤销")
        self.redo_button = QPushButton("↷")
        self.redo_button.setObjectName("IconButton")
        self.redo_button.setToolTip("重做")
        self.fit_button = QPushButton("适应画布")
        self.fit_button.setProperty("role", "soft")
        self.add_photos_button = QPushButton("＋ 导入照片")
        self.add_photos_button.setProperty("role", "soft")
        head.addWidget(self.undo_button)
        head.addWidget(self.redo_button)
        head.addWidget(self.fit_button)
        head.addWidget(self.add_photos_button)

        center_layout.addWidget(self.workspace_head)
        center_layout.addWidget(self.preview, 1)
        center_layout.addWidget(self.photo_list)

        layout.addWidget(self.sidebar)
        layout.addWidget(center, 1)
        layout.addWidget(self.settings)
        return studio

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
        act_reset_watermark = QAction("重置水印设置", self)
        act_reset_watermark.triggered.connect(self._reset_watermark_settings)
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(act_reset)
        edit_menu.addAction(act_reset_watermark)

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
        bar.setFixedHeight(22)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)
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

        self.summary_label.setMinimumWidth(0)
        self.output_status.setMaximumWidth(220)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.summary_label, 0)
        layout.addWidget(self.output_status, 0)
        layout.addWidget(self.cancel_button, 0)
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
        self.preview.fontItalicChanged.connect(self._on_font_italic_changed)
        self.preview.fontOpacityChanged.connect(self._on_font_opacity_changed)
        self.preview.fieldPositionChanged.connect(self._on_field_position)
        self.settings.optionsChanged.connect(self._on_settings)
        self.settings.chooseLogoRequested.connect(self._choose_logo)
        self.settings.clearLogoRequested.connect(lambda: self.settings.set_logo_path(""))
        self.settings.chooseOutputRequested.connect(self._choose_output)
        self.settings.resetWatermarkRequested.connect(self._reset_watermark_settings)
        self.settings.exportRequested.connect(self._export_all)
        self.settings.templatesChanged.connect(self._refresh_recent_templates)
        self.settings.photoFieldTextEdited.connect(self._on_panel_photo_field_edited)
        self.settings.resetPhotoExifRequested.connect(lambda: self.controller.reset_photo_overrides())
        self.sidebar.styleRequested.connect(self._select_style)
        self.sidebar.photosRequested.connect(lambda: self._go_section("photos"))
        self.sidebar.batchRequested.connect(lambda: self._go_section("batch"))
        self.sidebar.assetsRequested.connect(lambda: self._go_section("assets"))
        self.sidebar.allTemplatesRequested.connect(lambda: self._go_section("templates"))
        self.sidebar.recentTemplateRequested.connect(self._apply_recent_template)
        self.sidebar.helpRequested.connect(self._about)
        self.nav_edit.clicked.connect(lambda: self._go_section("photos"))
        self.nav_templates.clicked.connect(lambda: self._go_section("templates"))
        self.nav_batch.clicked.connect(lambda: self._go_section("batch"))
        self.preview.importRequested.connect(self._add_files)
        self.photo_list.metaChanged.connect(self._on_photo_meta)
        self.controller.saveStateChanged.connect(self._on_save_state)
        self.add_photos_button.clicked.connect(self._add_files)
        self.fit_button.clicked.connect(self.preview.fit_in_view)
        self.undo_button.clicked.connect(self.controller.undo)
        self.redo_button.clicked.connect(self.controller.redo)
        self.save_template_button.clicked.connect(self.settings.save_as_template)
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
        self.sidebar.set_style(str(state.get("style", "")))

    def _on_files(self, paths: object) -> None:
        items = [str(path) for path in paths] if isinstance(paths, list) else []
        self.photo_list.set_paths(items, self.controller.current_path)

    def _on_current(self, path: str) -> None:
        self.photo_list.set_current_path(path)
        self.preview.set_photo_token(path)
        self.preview.hide_field_editor()
        if path:
            self.file_title.setText(Path(path).name)
        else:
            self.file_title.setText("尚未选择照片")
        self._update_file_subtitle()
        self._sync_photo_exif_panel()

    def _sync_photo_exif_panel(self) -> None:
        path = self.controller.current_path
        if not path:
            self.settings.set_photo_exif_overrides(None, has_photo=False)
            return
        overrides = {
            key: str(self.controller.edit_session.get_field(path, key).get("text", "") or "")
            for key in ("camera", "lens", "exif")
        }
        self.settings.set_photo_exif_overrides(overrides, has_photo=True)

    def _on_panel_photo_field_edited(self, field: str, text: str) -> None:
        if field not in ("camera", "lens", "exif") or not self.controller.current_path:
            return
        self.controller.apply_edit_session_field(field, text)

    def _on_photo_meta(self, path: str) -> None:
        if path and path == self.controller.current_path:
            self._update_file_subtitle()

    def _update_file_subtitle(self) -> None:
        path = self.controller.current_path
        if not path:
            self.file_subtitle.setText("导入照片开始编辑")
            return
        meta = self.photo_list.photo_meta(path)
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        suffix = Path(path).suffix.lstrip(".").upper()
        fmt = {"JPG": "JPEG", "TIF": "TIFF"}.get(suffix, suffix) or "图片"
        if width and height:
            self.file_subtitle.setText(f"原图 {width} × {height} · {fmt}")
        else:
            self.file_subtitle.setText(f"原图读取中 · {fmt}")

    def _on_save_state(self, state: str) -> None:
        text = {
            "saving": "●  正在保存…",
            "saved": "●  所有修改已保存",
            "error": "●  设置保存失败",
        }.get(state, "●  所有修改已保存")
        self.saved_label.setText(text)
        self.saved_label.setProperty("state", state)
        self.saved_label.style().unpolish(self.saved_label)
        self.saved_label.style().polish(self.saved_label)

    def _go_section(self, name: str) -> None:
        """顶栏导航与左栏工作空间联动，切到对应检查页签。"""
        tab = {"photos": "Logo", "assets": "Logo", "batch": "导出", "templates": "自定义"}.get(name, "Logo")
        nav = {"photos": self.nav_edit, "assets": self.nav_edit, "batch": self.nav_batch}.get(
            name, self.nav_templates
        )
        nav.setChecked(True)
        if name in ("photos", "assets", "batch"):
            self.sidebar.set_active(name)
        self.settings.show_tab(tab)
        if name == "photos":
            self.preview.fit_in_view()

    def _refresh_recent_templates(self) -> None:
        self.sidebar.set_recent_templates(
            template_store.recent_templates(2, self.settings.templates_path())
        )

    def _apply_recent_template(self, template_id: str) -> None:
        if self.settings.apply_template(template_id):
            self.status_label.setText("已应用最近使用的模板。")
        else:
            self._refresh_recent_templates()

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
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

    def _select_style(self, style: str) -> None:
        self.settings.style_combo.setCurrentText(style)

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
                "font_italic": bool(session.get("italic", False)),
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
            if key in ("camera", "lens", "exif"):
                self._sync_photo_exif_panel()

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

    def _on_font_italic_changed(self, key: str, italic: bool) -> None:
        if key in ("brand", "caption"):
            self.settings.set_field_italic(key, italic)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_italic(key, italic)

    def _on_font_opacity_changed(self, key: str, opacity: float) -> None:
        if key in ("brand", "caption"):
            self.settings.set_field_opacity(key, opacity)
            return
        if key in ("camera", "lens", "exif", "date", "gps"):
            self.controller.apply_edit_session_opacity(key, opacity)

    def _on_edit_session_cleared(self) -> None:
        self.preview.hide_field_editor()
        self._sync_photo_exif_panel()

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

    def _reset_watermark_settings(self) -> None:
        if not self.suppress_dialogs:
            answer = QMessageBox.question(
                self,
                "重置水印设置",
                "将恢复默认水印，导出目录和照片列表不变。",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        state = settings_store.reset_watermark_settings(self.settings.state())
        self.settings.set_state(state)
        self.controller.apply_settings(self.settings.state())
        self._show_output_dir(str(self.settings.state()["output_dir"]))

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
            "关于停下时光",
            "停下时光 · Studio\n本地照片元数据水印工具。\n原图只读，结果另存。",
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
