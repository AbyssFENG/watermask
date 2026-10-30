# -*- coding: utf-8 -*-
"""中间预览区。显示的是缩小图，导出不会使用这张图。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QImage, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

PLACEHOLDER_TEXT = "添加一张照片\n开始设计你的专属水印"


class PreviewImageLabel(QLabel):
    clickedAt = Signal(QPoint)

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setMouseTracking(True)
        self._hits: list[dict[str, Any]] = []
        self._hovering = False

    def set_hits(self, hits: list[dict[str, Any]] | None) -> None:
        self._hits = list(hits or [])
        if self.underMouse():
            self._update_cursor(self.mapFromGlobal(QCursor.pos()))

    def pixmap_rect(self) -> QRect | None:
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return None
        cr = self.contentsRect()
        x = cr.x() + max(0, (cr.width() - pix.width()) // 2)
        y = cr.y() + max(0, (cr.height() - pix.height()) // 2)
        return QRect(x, y, pix.width(), pix.height())

    def hit_at(self, pos: QPoint) -> dict[str, Any] | None:
        rect = self.pixmap_rect()
        if rect is None or not rect.contains(pos):
            return None
        local_x = pos.x() - rect.x()
        local_y = pos.y() - rect.y()
        pad = 6
        matches: list[tuple[float, dict[str, Any]]] = []
        for hit in self._hits:
            x = float(hit.get("x", 0)) - pad
            y = float(hit.get("y", 0)) - pad
            w = float(hit.get("w", 0)) + pad * 2
            h = float(hit.get("h", 0)) + pad * 2
            if x <= local_x <= x + w and y <= local_y <= y + h:
                matches.append((w * h, hit))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0])
        return matches[0][1]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clickedAt.emit(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._update_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovering = False
        self.unsetCursor()
        super().leaveEvent(event)

    def _update_cursor(self, pos: QPoint | None) -> None:
        if pos is None:
            return
        hovering = self.hit_at(pos) is not None
        if hovering != self._hovering:
            self._hovering = hovering
            if hovering:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()


class PreviewPanel(QFrame):
    resized = Signal(int, int)
    refreshRequested = Signal()
    fieldEditRequested = Signal(str)
    fieldChanged = Signal(str, str, object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(360)
        self._editor_key = ""
        self._suppress_editor = False
        self._last_viewport = (0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("实时预览")
        title.setObjectName("PanelTitle")
        self.name_label = QLabel("尚未选择照片")
        self.name_label.setObjectName("PanelHint")

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(title)
        titles.addWidget(self.name_label)

        self.refresh_button = QPushButton("刷新预览")
        self.refresh_button.setObjectName("refreshPreviewButton")
        self.refresh_button.setProperty("role", "soft")
        self.refresh_button.clicked.connect(self.refreshRequested)

        header = QHBoxLayout()
        header.addLayout(titles, 1)
        header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)

        self.canvas = QFrame()
        self.canvas.setObjectName("PreviewCanvas")
        canvas_layout = QVBoxLayout(self.canvas)
        canvas_layout.setContentsMargins(12, 12, 12, 12)
        self.image_label = PreviewImageLabel(PLACEHOLDER_TEXT)
        self.image_label.setObjectName("PreviewLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.clickedAt.connect(self._on_image_clicked)
        canvas_layout.addWidget(self.image_label)

        # 叠在预览画布上，不挤占布局，避免点击时预览被顶没/闪掉。
        self.editor = QFrame(self.canvas)
        self.editor.setObjectName("WatermarkEditor")
        self.editor.setVisible(False)
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(10, 8, 10, 8)
        editor_layout.setSpacing(6)
        top = QHBoxLayout()
        self.editor_title = QLabel("编辑水印文字")
        self.editor_title.setObjectName("FieldLabel")
        self.editor_close = QPushButton("完成")
        self.editor_close.setObjectName("closeEditorButton")
        self.editor_close.setProperty("role", "soft")
        self.editor_close.clicked.connect(self.hide_editor)
        top.addWidget(self.editor_title, 1)
        top.addWidget(self.editor_close)
        editor_layout.addLayout(top)
        row = QHBoxLayout()
        self.editor_text = QLineEdit()
        self.editor_text.setObjectName("watermarkTextEdit")
        self.editor_text.setPlaceholderText("照片 EXIF 原文")
        self.editor_text.textChanged.connect(self._on_editor_changed)
        self.editor_scale = QSpinBox()
        self.editor_scale.setObjectName("watermarkScaleSpin")
        self.editor_scale.setRange(70, 160)
        self.editor_scale.setSingleStep(5)
        self.editor_scale.setSuffix("%")
        self.editor_scale.setFixedWidth(78)
        self.editor_scale.valueChanged.connect(self._on_editor_changed)
        row.addWidget(self.editor_text, 1)
        row.addWidget(self.editor_scale)
        editor_layout.addLayout(row)
        tip = QLabel("修改写入临时文件；导出或关闭程序后清除。预览会同步更新。")
        tip.setObjectName("MutedLabel")
        tip.setWordWrap(True)
        editor_layout.addWidget(tip)
        self.editor.raise_()

        layout.addLayout(header)
        layout.addWidget(self.canvas, 1)

    def viewport_size(self) -> tuple[int, int]:
        size = self.canvas.contentsRect().size()
        return max(200, size.width() - 24), max(180, size.height() - 24)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_editor()
        width, height = self.viewport_size()
        if (width, height) != self._last_viewport:
            self._last_viewport = (width, height)
            self.resized.emit(width, height)

    def set_filename(self, name: str) -> None:
        self.name_label.setText(name or "尚未选择照片")

    def show_image(self, image: QImage) -> None:
        self.image_label.setPixmap(QPixmap.fromImage(image))
        self.image_label.setText("")
        self._set_error(False)
        self._position_editor()

    def set_hits(self, hits: object) -> None:
        items = [dict(item) for item in hits] if isinstance(hits, list) else []
        self.image_label.set_hits(items)

    def show_message(self, text: str, error: bool = False) -> None:
        self.image_label.setPixmap(QPixmap())
        self.image_label.set_hits([])
        self.image_label.setText(text)
        self.hide_editor()
        self._set_error(error)

    def open_field_editor(self, payload: dict[str, Any]) -> None:
        key = str(payload.get("key", "") or "")
        if not key:
            return
        self._editor_key = key
        self._suppress_editor = True
        self.editor_title.setText(str(payload.get("label", "编辑水印文字")))
        # 直接填入当前展示文案（临时修改或 EXIF 原文），方便继续改。
        filled = str(payload.get("text", "") or "")
        self.editor_text.setText(filled)
        self.editor_text.setPlaceholderText(str(payload.get("placeholder", "照片 EXIF 原文")))
        has_scale = bool(payload.get("has_scale", False))
        self.editor_scale.setVisible(has_scale)
        if has_scale:
            scale = float(payload.get("scale", 1.0) or 1.0)
            self.editor_scale.setValue(int(round(scale * 100)))
        self.editor.setVisible(True)
        self._position_editor()
        self.editor.raise_()
        self._suppress_editor = False
        self.editor_text.setFocus()
        self.editor_text.selectAll()

    def hide_editor(self) -> None:
        self.editor.setVisible(False)
        self._editor_key = ""

    def _position_editor(self) -> None:
        if not self.editor.isVisible():
            return
        margin = 10
        width = max(240, self.canvas.width() - margin * 2)
        self.editor.adjustSize()
        height = max(96, self.editor.sizeHint().height())
        self.editor.setGeometry(margin, max(margin, self.canvas.height() - height - margin), width, height)

    def _on_image_clicked(self, pos: QPoint) -> None:
        hit = self.image_label.hit_at(pos)
        if hit is None:
            self.hide_editor()
            return
        key = str(hit.get("key", "") or "")
        if key:
            self.fieldEditRequested.emit(key)

    def _on_editor_changed(self, *_args: object) -> None:
        if self._suppress_editor or not self._editor_key:
            return
        scale = self.editor_scale.value() / 100 if self.editor_scale.isVisible() else None
        self.fieldChanged.emit(self._editor_key, self.editor_text.text(), scale)

    def _set_error(self, error: bool) -> None:
        self.image_label.setProperty("error", error)
        self.image_label.style().unpolish(self.image_label)
        self.image_label.style().polish(self.image_label)
