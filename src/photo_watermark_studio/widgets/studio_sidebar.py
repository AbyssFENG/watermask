# -*- coding: utf-8 -*-
"""“停下时光”工作台左侧导航与模板库。"""
from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class StudioSidebar(QFrame):
    styleRequested = Signal(str)
    photosRequested = Signal()
    batchRequested = Signal()
    assetsRequested = Signal()
    helpRequested = Signal()
    allTemplatesRequested = Signal()
    recentTemplateRequested = Signal(str)

    _TEMPLATES = (
        ("卡片相框", "留白 · 信息卡片", "card"),
        ("极简叠加", "轻量 · 不遮挡", "overlay"),
        ("经典底栏", "深色 · 参数展示", "footer"),
        ("胶片边框", "复古 · 摄影感", "film"),
        ("纯文字中下", "简洁 · 作品署名", "text"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StudioSidebar")
        self.setMinimumWidth(200)
        self.setMaximumWidth(232)

        root = QVBoxLayout(self)
        root.setContentsMargins(13, 17, 13, 14)
        root.setSpacing(6)

        root.addWidget(self._section("工作空间"))
        self.photo_button = self._nav("▧  照片编辑", True)
        self.batch_button = self._nav("▤  批量任务")
        self.assets_button = self._nav("◈  素材与 Logo")
        self.nav_buttons = {
            "photos": self.photo_button,
            "batch": self.batch_button,
            "assets": self.assets_button,
        }
        self.photo_button.clicked.connect(lambda: self._activate("photos", self.photosRequested))
        self.batch_button.clicked.connect(lambda: self._activate("batch", self.batchRequested))
        self.assets_button.clicked.connect(lambda: self._activate("assets", self.assetsRequested))
        for button in self.nav_buttons.values():
            root.addWidget(button)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 12, 0, 2)
        head_layout.setSpacing(4)
        head_layout.addWidget(self._section("模板库"))
        head_layout.addStretch(1)
        self.all_templates_button = QPushButton("全部 ↗")
        self.all_templates_button.setObjectName("SidebarLink")
        self.all_templates_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.all_templates_button.clicked.connect(self.allTemplatesRequested)
        head_layout.addWidget(self.all_templates_button)
        root.addWidget(head)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(7)
        self.template_group = QButtonGroup(self)
        self.template_group.setExclusive(True)
        self.template_buttons: dict[str, QAbstractButton] = {}
        for index, (name, desc, kind) in enumerate(self._TEMPLATES):
            button = QToolButton()
            button.setText(f"{name}\n{desc}")
            button.setObjectName("TemplateCard")
            button.setCheckable(True)
            button.setProperty("template", name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(self._template_icon(kind))
            button.setIconSize(QSize(80, 48))
            button.setMinimumHeight(88)
            button.clicked.connect(lambda checked=False, value=name: self.styleRequested.emit(value))
            self.template_group.addButton(button)
            self.template_buttons[name] = button
            grid.addWidget(button, index // 2, index % 2)
        root.addLayout(grid)
        custom_button = self._nav("＋  新建自定义模板")
        custom_button.setCheckable(True)
        custom_button.clicked.connect(lambda: self.styleRequested.emit("自定义"))
        self.template_group.addButton(custom_button)
        self.template_buttons["自定义"] = custom_button
        root.addWidget(custom_button)

        recent_head = self._section("最近使用")
        recent_head.setContentsMargins(0, 10, 0, 2)
        root.addWidget(recent_head)
        self.recent_box = QVBoxLayout()
        self.recent_box.setContentsMargins(0, 0, 0, 0)
        self.recent_box.setSpacing(4)
        root.addLayout(self.recent_box)
        self.recent_label = QLabel("保存模板后会出现在这里")
        self.recent_label.setObjectName("SidebarHint")
        self.recent_label.setWordWrap(True)
        self.recent_box.addWidget(self.recent_label)
        self.recent_buttons: list[QPushButton] = []
        root.addStretch(1)

        help_button = self._nav("?  帮助与反馈")
        help_button.clicked.connect(self.helpRequested)
        root.addWidget(help_button)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SidebarSection")
        return label

    @staticmethod
    def _nav(text: str, active: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("SidebarNav")
        button.setCheckable(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("active", active)
        return button

    def _activate(self, name: str, signal: Any) -> None:
        self.set_active(name)
        signal.emit()

    def set_active(self, name: str) -> None:
        for key, button in self.nav_buttons.items():
            active = key == name
            if bool(button.property("active")) == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def active_nav(self) -> str:
        for key, button in self.nav_buttons.items():
            if button.property("active"):
                return key
        return ""

    def set_style(self, style: str) -> None:
        button = self.template_buttons.get(str(style))
        if button is not None:
            button.setChecked(True)

    def set_recent_templates(self, entries: Iterable[dict[str, Any]]) -> None:
        for button in self.recent_buttons:
            self.recent_box.removeWidget(button)
            button.deleteLater()
        self.recent_buttons = []
        items = list(entries)
        for entry in items:
            tid = str(entry.get("id", ""))
            name = str(entry.get("name", "") or "未命名模板")
            style = str((entry.get("settings") or {}).get("style", "") or "")
            text = f"◫  {name}" + (f" · {style}" if style else "")
            button = self._nav(text)
            button.setObjectName("SidebarRecent")
            button.setToolTip(f"应用模板「{name}」")
            button.clicked.connect(lambda _checked=False, value=tid: self.recentTemplateRequested.emit(value))
            self.recent_box.addWidget(button)
            self.recent_buttons.append(button)
        self.recent_label.setVisible(not items)

    @staticmethod
    def _template_icon(kind: str) -> QIcon:
        pixmap = QPixmap(92, 58)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#DCE2ED"))
        painter.drawRoundedRect(0, 0, 92, 58, 7, 7)
        if kind == "film":
            painter.setBrush(QColor("#1D2028"))
            painter.drawRoundedRect(8, 4, 76, 50, 3, 3)
            painter.setBrush(QColor("#728493"))
            painter.drawRect(13, 9, 66, 33)
            painter.setPen(QPen(QColor(235, 238, 244, 200), 2))
            painter.drawLine(32, 48, 44, 48)
            painter.drawLine(48, 48, 60, 48)
            painter.end()
            return QIcon(pixmap)
        painter.setBrush(QColor("#728493"))
        painter.drawRoundedRect(13, 7, 66, 40, 3, 3)
        if kind == "card":
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRect(7, 42, 78, 16)
        elif kind == "overlay":
            painter.setBrush(QColor(255, 255, 255, 190))
            painter.drawRoundedRect(18, 37, 56, 9, 3, 3)
        elif kind == "footer":
            painter.setBrush(QColor("#222936"))
            painter.drawRect(0, 40, 92, 18)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 215), 2))
            painter.drawLine(27, 38, 65, 38)
            painter.drawLine(36, 43, 56, 43)
        painter.end()
        return QIcon(pixmap)
