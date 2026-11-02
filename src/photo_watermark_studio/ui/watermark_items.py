# -*- coding: utf-8 -*-
"""画布上的可交互水印图元。"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyle, QStyleOptionGraphicsItem, QWidget


class WatermarkBarItem(QGraphicsObject):
    """可拖动的水印区域；拖动结果以归一化偏移回传。"""

    moved = Signal(float, float)
    selectedChanged = Signal(bool)
    activated = Signal(str, object)

    def __init__(self, key: str = "watermark_bar") -> None:
        super().__init__()
        self.key = key
        self._rect = QRectF(0, 0, 100, 40)
        self._locked = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(20)
        self._dragging = False
        self._base_offset = (0.0, 0.0)
        self._image_size = (1.0, 1.0)
        self._view_scale = (1.0, 1.0)

    def set_geometry(self, rect: QRectF, locked: bool = False) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self._locked = locked
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not locked)
        self.setPos(0, 0)

    def set_mapper_context(
        self,
        image_size: tuple[float, float],
        view_scale: tuple[float, float],
        base_offset: tuple[float, float],
    ) -> None:
        self._image_size = image_size
        self._view_scale = view_scale
        self._base_offset = base_offset

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-4, -4, 4, 4)

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        pen = QPen(QColor("#285BE8") if selected else QColor(40, 91, 232, 90), 1.5 if selected else 1.0)
        pen.setStyle(Qt.PenStyle.DashLine if selected else Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(40, 91, 232, 28 if selected else 10)))
        painter.drawRoundedRect(self._rect, 6, 6)
        if selected and not self._locked:
            handle = QRectF(self._rect.right() - 8, self._rect.bottom() - 8, 10, 10)
            painter.setBrush(QBrush(QColor("#285BE8")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(handle)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.selectedChanged.emit(bool(value))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self._dragging:
            pos = self.pos()
            sx = self._view_scale[0] or 1.0
            sy = self._view_scale[1] or 1.0
            iw, ih = self._image_size
            nx = self._base_offset[0] + (pos.x() / sx) / max(iw, 1.0)
            ny = self._base_offset[1] + (pos.y() / sy) / max(ih, 1.0)
            self.moved.emit(max(-0.45, min(0.45, nx)), max(-0.45, min(0.45, ny)))
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        self._dragging = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.activated.emit(self.key, {})
        super().mouseDoubleClickEvent(event)


class HitTextItem(QGraphicsObject):
    """文字命中热区，点击打开编辑。"""

    activated = Signal(str, object)

    def __init__(
        self,
        key: str,
        payload: dict[str, Any],
        rect: QRectF,
        on_activate: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__()
        self.key = key
        self.payload = payload
        self._rect = QRectF(rect)
        self._on_activate = on_activate
        self.setAcceptHoverEvents(True)
        self.setZValue(30)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self._hover = False

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if self._hover or (option.state & QStyle.StateFlag.State_Selected):
            painter.setBrush(QBrush(QColor(40, 91, 232, 45)))
            painter.setPen(QPen(QColor("#285BE8"), 1.0))
            painter.drawRoundedRect(self._rect, 3, 3)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._on_activate is not None:
                self._on_activate(self.key, self.payload)
            self.activated.emit(self.key, self.payload)
        super().mousePressEvent(event)
