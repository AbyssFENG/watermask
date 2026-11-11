# -*- coding: utf-8 -*-
"""左侧照片素材管理区（缩略图 / 列表）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from photo_watermark_studio.workers.thumbnail_worker import ThumbnailRunnable, ThumbnailSignals

STATUS_LABELS = {
    "pending": "待处理",
    "edited": "已编辑",
    "exporting": "导出中",
    "done": "已完成",
    "failed": "失败",
}


class PhotoListPanel(QFrame):
    addFilesRequested = Signal()
    addFolderRequested = Signal()
    clearRequested = Signal()
    removeRequested = Signal()
    selectionChanged = Signal(str)
    pathsDropped = Signal(object)
    resetPhotoRequested = Signal(str)
    openFolderRequested = Signal(str)
    metaChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(240)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("照片素材")
        self.title_label.setObjectName("PanelTitle")
        self.hint_label = QLabel("拖入照片，或添加 / 导入文件夹")
        self.hint_label.setObjectName("PanelHint")
        self.hint_label.setWordWrap(True)

        self.add_button = QPushButton("＋ 添加照片")
        self.add_button.setObjectName("addPhotosButton")
        self.add_button.setProperty("role", "primary")
        self.add_button.clicked.connect(self.addFilesRequested)

        self.folder_button = QPushButton("导入文件夹")
        self.folder_button.setObjectName("addFolderButton")
        self.folder_button.setProperty("role", "soft")
        self.folder_button.clicked.connect(self.addFolderRequested)

        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("clearPhotosButton")
        self.clear_button.setProperty("role", "soft")
        self.clear_button.clicked.connect(self.clearRequested)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.folder_button)
        row.addWidget(self.clear_button)

        filter_col = QVBoxLayout()
        filter_col.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("assetSearchEdit")
        self.search_edit.setPlaceholderText("搜索文件名")
        self.search_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_edit.textChanged.connect(self._apply_filter)
        filter_col.addWidget(self.search_edit)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("assetSortCombo")
        self.sort_combo.addItems(["导入顺序", "文件名"])
        self.sort_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sort_combo.currentTextChanged.connect(self._apply_sort)
        self.view_combo = QComboBox()
        self.view_combo.setObjectName("assetViewCombo")
        self.view_combo.addItems(["列表", "网格"])
        self.view_combo.setFixedWidth(72)
        self.view_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.view_combo.currentTextChanged.connect(self._apply_view_mode)
        filter_row.addWidget(self.sort_combo, 1)
        filter_row.addWidget(self.view_combo, 0)
        filter_col.addLayout(filter_row)

        self.count_label = QLabel("已选 0 / 共 0")
        self.count_label.setObjectName("CountLabel")

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("fileList")
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setIconSize(QSize(96, 96))
        self.list_widget.setSpacing(6)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._context_menu)
        self.list_widget.currentItemChanged.connect(self._on_current)
        self.list_widget.itemSelectionChanged.connect(self._update_count)

        self.remove_button = QPushButton("移除选中照片")
        self.remove_button.setObjectName("removePhotosButton")
        self.remove_button.setProperty("role", "soft")
        self.remove_button.clicked.connect(self.removeRequested)

        layout.addWidget(self.title_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.add_button)
        layout.addLayout(row)
        layout.addLayout(filter_col)
        layout.addWidget(self.count_label)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.remove_button)

        self._paths: list[str] = []
        self._meta: dict[str, dict[str, Any]] = {}
        self._thumbs: dict[str, QPixmap] = {}
        self._items: dict[str, QListWidgetItem] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._rail_mode = False
        self._apply_view_mode("列表")

    def set_rail_mode(self, enabled: bool = True) -> None:
        """切换为工作台底部的横向图片队列，同时保留完整素材 API。"""
        self._rail_mode = bool(enabled)
        self.setObjectName("ImageRail" if enabled else "Panel")
        self.setMinimumWidth(0 if enabled else 240)
        if not enabled:
            return
        self.setMinimumHeight(68)
        self.setMaximumHeight(72)
        self.title_label.setText("图片队列")
        self.title_label.setObjectName("RailTitle")
        self.title_label.setVisible(False)
        self.count_label.setObjectName("RailCount")
        self.count_label.setVisible(False)
        self.hint_label.setVisible(False)
        self.folder_button.setVisible(False)
        self.clear_button.setVisible(False)
        self.search_edit.setVisible(False)
        self.sort_combo.setVisible(False)
        self.view_combo.setVisible(False)
        self.remove_button.setText("×")
        self.remove_button.setToolTip("从队列移除选中的照片（不会删除原图）")
        self.add_button.setText("＋")
        self.add_button.setObjectName("RailAddTile")
        self.add_button.setProperty("role", "")
        self.add_button.setToolTip("添加照片")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_widget.setObjectName("railList")
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setFlow(QListWidget.Flow.LeftToRight)
        self.list_widget.setWrapping(False)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setMovement(QListWidget.Movement.Static)
        self.list_widget.setGridSize(QSize(72, 52))
        self.list_widget.setIconSize(QSize(64, 36))
        self.list_widget.setSpacing(2)
        self.list_widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root = self.layout()
        if isinstance(root, QVBoxLayout):
            while root.count():
                root.takeAt(0)
            root.setContentsMargins(8, 6, 8, 6)
            root.setSpacing(0)
            rail = QFrame()
            rail.setObjectName("RailContent")
            row = QHBoxLayout(rail)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            row.addWidget(self.list_widget, 1)
            self.add_button.setVisible(True)
            self.add_button.setFixedSize(32, 32)
            self.remove_button.setVisible(True)
            self.remove_button.setFixedSize(32, 32)
            row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.rail_note = QLabel("拖动切换 · 可批量应用")
            self.rail_note.setObjectName("RailNote")
            self.rail_note.setVisible(False)
            root.addWidget(rail)
            self.title_label.style().unpolish(self.title_label)
            self.title_label.style().polish(self.title_label)
        self._apply_filter()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
        if paths:
            self.pathsDropped.emit(paths)
        event.acceptProposedAction()

    def _on_current(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        path = ""
        if current is not None:
            path = str(current.data(Qt.ItemDataRole.UserRole) or "")
        self.selectionChanged.emit(path)

    def selected_paths(self) -> list[str]:
        paths: list[str] = []
        for item in self.list_widget.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                paths.append(str(value))
        return paths

    def set_photo_meta(self, path: str, **kwargs: Any) -> None:
        info = dict(self._meta.get(path) or {})
        info.update(kwargs)
        self._meta[path] = info
        self._refresh_item_text(path)
        self.metaChanged.emit(path)

    def photo_meta(self, path: str) -> dict[str, Any]:
        return dict(self._meta.get(path) or {})

    def set_statuses(self, mapping: dict[str, str]) -> None:
        for path, status in mapping.items():
            self.set_photo_meta(path, status=status)

    def set_paths(self, paths: list[str], current: str | None) -> None:
        self._paths = list(paths)
        for path in paths:
            self._meta.setdefault(path, {"status": "pending", "width": 0, "height": 0})
            if path not in self._thumbs:
                self._request_thumb(path)
        stale = [key for key in self._meta if key not in set(paths)]
        for key in stale:
            self._meta.pop(key, None)
            self._thumbs.pop(key, None)
        self._rebuild_list(current)

    def set_current_path(self, path: str) -> None:
        self.list_widget.blockSignals(True)
        if not path:
            self.list_widget.clearSelection()
            self.list_widget.setCurrentRow(-1)
        else:
            for row in range(self.list_widget.count()):
                item = self.list_widget.item(row)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == path:
                    self.list_widget.setCurrentRow(row)
                    break
        self.list_widget.blockSignals(False)
        self._update_count()

    def _request_thumb(self, path: str) -> None:
        signals = ThumbnailSignals()
        signals.finished.connect(self._on_thumb)
        self._pool.start(ThumbnailRunnable(path, 160, signals))

    def _on_thumb(self, path: str, image, width: int, height: int, error: str) -> None:
        if error or image.isNull():
            return
        self._thumbs[path] = QPixmap.fromImage(image)
        self.set_photo_meta(path, width=width, height=height)
        self._refresh_item_text(path)

    def _item_caption(self, path: str) -> str:
        meta = self._meta.get(path) or {}
        status = STATUS_LABELS.get(str(meta.get("status", "pending")), "待处理")
        name = Path(path).name
        w = int(meta.get("width") or 0)
        h = int(meta.get("height") or 0)
        size = f"{w} × {h}" if w and h else "…"
        if self._rail_mode:
            return name if status == "待处理" else f"{name}\n{status}"
        if self.view_combo.currentText() == "列表":
            return f"{name}\n{size}\n{status}"
        return f"{name}\n{status}"

    def _refresh_item_text(self, path: str) -> None:
        item = self._items.get(path)
        if item is None:
            return
        item.setText(self._item_caption(path))
        pix = self._thumbs.get(path)
        if pix is not None and not pix.isNull():
            item.setIcon(QIcon(pix))
        tip = path
        meta = self._meta.get(path) or {}
        if meta.get("error"):
            tip += f"\n失败：{meta['error']}"
        item.setToolTip(tip)
        self._update_count()

    def _visible_paths(self) -> list[str]:
        query = self.search_edit.text().strip().lower()
        paths = list(self._paths)
        if self.sort_combo.currentText() == "文件名":
            paths = sorted(paths, key=lambda p: Path(p).name.lower())
        if query:
            paths = [p for p in paths if query in Path(p).name.lower()]
        return paths

    def _rebuild_list(self, current: str | None) -> None:
        selected = set(self.selected_paths())
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._items.clear()
        current_row = -1
        for index, path in enumerate(self._visible_paths()):
            item = QListWidgetItem(self._item_caption(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            pix = self._thumbs.get(path)
            if pix is not None and not pix.isNull():
                item.setIcon(QIcon(pix))
            self.list_widget.addItem(item)
            self._items[path] = item
            if current and path == current:
                current_row = index
            if path in selected:
                item.setSelected(True)
        if current_row >= 0:
            self.list_widget.setCurrentRow(current_row)
        self.list_widget.blockSignals(False)
        self._update_count()

    def _apply_filter(self, *_args: object) -> None:
        current = ""
        item = self.list_widget.currentItem()
        if item is not None:
            current = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._rebuild_list(current or None)

    def _apply_sort(self, *_args: object) -> None:
        self._apply_filter()

    def _apply_view_mode(self, mode: str) -> None:
        if self._rail_mode:
            return
        if mode == "网格":
            self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
            self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.list_widget.setMovement(QListWidget.Movement.Static)
            self.list_widget.setGridSize(QSize(126, 148))
            self.list_widget.setIconSize(QSize(96, 96))
        else:
            self.list_widget.setViewMode(QListWidget.ViewMode.ListMode)
            self.list_widget.setIconSize(QSize(56, 56))
        self._apply_filter()

    def _update_count(self) -> None:
        total = len(self._paths)
        if self._rail_mode:
            self.count_label.setText(f"{total} 张照片")
            return
        selected = len(self.list_widget.selectedItems())
        self.count_label.setText(f"已选 {selected} / 共 {total}")

    def _context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not path:
            return
        menu = QMenu(self)
        act_current = QAction("设为当前照片", self)
        act_reset = QAction("重置单张调整", self)
        act_remove = QAction("移除照片", self)
        act_folder = QAction("打开原图所在目录", self)
        menu.addAction(act_current)
        menu.addAction(act_reset)
        menu.addAction(act_remove)
        menu.addSeparator()
        menu.addAction(act_folder)
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen is act_current:
            self.list_widget.setCurrentItem(item)
            self.selectionChanged.emit(path)
        elif chosen is act_reset:
            self.resetPhotoRequested.emit(path)
        elif chosen is act_remove:
            self.list_widget.setCurrentItem(item)
            item.setSelected(True)
            self.removeRequested.emit()
        elif chosen is act_folder:
            folder = str(Path(path).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.openFolderRequested.emit(folder)
