# -*- coding: utf-8 -*-
"""左侧照片列表。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class PhotoListPanel(QFrame):
    addFilesRequested = Signal()
    addFolderRequested = Signal()
    clearRequested = Signal()
    removeRequested = Signal()
    selectionChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(8)

        title = QLabel("照片素材")
        title.setObjectName("PanelTitle")
        hint = QLabel("导入照片后可逐张预览，也可批量套用")
        hint.setObjectName("PanelHint")
        hint.setWordWrap(True)

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

        self.count_label = QLabel("待处理  0 张")
        self.count_label.setObjectName("CountLabel")

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("fileList")
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self._on_current)

        self.remove_button = QPushButton("移除选中照片")
        self.remove_button.setObjectName("removePhotosButton")
        self.remove_button.setProperty("role", "soft")
        self.remove_button.clicked.connect(self.removeRequested)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.add_button)
        layout.addLayout(row)
        layout.addWidget(self.count_label)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.remove_button)

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

    def set_paths(self, paths: list[str], current: str | None) -> None:
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        current_row = -1
        for index, path in enumerate(paths):
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list_widget.addItem(item)
            if current and path == current:
                current_row = index
        if current_row >= 0:
            self.list_widget.setCurrentRow(current_row)
        self.list_widget.blockSignals(False)
        self.count_label.setText(f"待处理  {len(paths)} 张")

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
