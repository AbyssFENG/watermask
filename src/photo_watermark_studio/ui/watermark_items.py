# -*- coding: utf-8 -*-
"""画布上的可交互水印图元。"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyle, QStyleOptionGraphicsItem, QWidget

from photo_watermark_studio.core.settings_store import FIELD_GRID_STEP, snap_field_position


class WatermarkBarItem(QGraphicsObject):
    """整块水印区域（非自定义模式仅作命中辅助，默认锁定）。"""

    moved = Signal(float, float)
    selectedChanged = Signal(bool)
    activated = Signal(str, object)
    dragStarted = Signal()
    dragFinished = Signal()

    def __init__(self, key: str = "watermark_bar") -> None:
        super().__init__()
        self.key = key
        self._rect = QRectF(0, 0, 100, 40)
        self._locked = True
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(20)
        self._dragging = False
        self._base_offset = (0.0, 0.0)
        self._image_size = (1.0, 1.0)
        self._view_scale = (1.0, 1.0)

    def is_dragging(self) -> bool:
        return self._dragging

    def set_geometry(self, rect: QRectF, locked: bool = True) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self._locked = locked
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
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
        return QRectF(self._rect)

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        del painter, option, widget
        return

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.selectedChanged.emit(bool(value))
        return super().itemChange(change, value)


class DraggableFieldItem(QGraphicsObject):
    """自定义模式下可拖动的单个字段；拖动期携带像素跟手，松手吸附提交。"""

    positionCommitted = Signal(str, float, float)
    activated = Signal(str, object)
    dragStarted = Signal()
    dragFinished = Signal()

    def __init__(
        self,
        key: str,
        payload: dict[str, Any],
        rect: QRectF,
        *,
        canvas_rect: QRectF,
        on_activate: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        super().__init__()
        self.key = key
        self.payload = payload
        self._rect = QRectF(0, 0, max(8.0, rect.width()), max(8.0, rect.height()))
        self._canvas_rect = QRectF(canvas_rect)
        self._on_activate = on_activate
        self.setPos(rect.topLeft())
        # 手动拖动：不用 ItemIsMovable，避免每帧 itemChange 钳制卡顿。
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(45)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self._dragging = False
        self._moved = False
        self._live_started = False
        self._press_scene = QPointF()
        self._origin_pos = QPointF()
        self._content: QPixmap | None = None

    def is_dragging(self) -> bool:
        return self._dragging

    def set_content_pixmap(self, pixmap: QPixmap | None) -> None:
        self._content = QPixmap(pixmap) if pixmap is not None and not pixmap.isNull() else None
        self.update()

    def clear_content_pixmap(self) -> None:
        self._content = None
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-5, -5, 5, 5)

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        active = self._dragging or bool(option.state & QStyle.StateFlag.State_Selected)
        if self._content is not None and not self._content.isNull():
            painter.drawPixmap(self._rect.toRect(), self._content)
            pen = QPen(QColor("#285BE8") if active else QColor(40, 91, 232, 160), 1.6 if active else 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self._rect, 3, 3)
            return
        pen = QPen(QColor("#285BE8") if active else QColor(40, 91, 232, 150), 2.0 if active else 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(40, 91, 232, 36 if active else 18)))
        painter.drawRoundedRect(self._rect, 4, 4)

    def _center_norm(self) -> tuple[float, float]:
        center = self.pos() + QPointF(self._rect.width() / 2, self._rect.height() / 2)
        cw = max(1.0, self._canvas_rect.width())
        ch = max(1.0, self._canvas_rect.height())
        nx = (center.x() - self._canvas_rect.x()) / cw
        ny = (center.y() - self._canvas_rect.y()) / ch
        return snap_field_position(nx, ny, FIELD_GRID_STEP)

    def _clamp_pos(self, pos: QPointF) -> QPointF:
        # 中心点不越出整张输出画布。
        cx = pos.x() + self._rect.width() / 2
        cy = pos.y() + self._rect.height() / 2
        left = self._canvas_rect.left()
        right = self._canvas_rect.right()
        top = self._canvas_rect.top()
        bottom = self._canvas_rect.bottom()
        cx = max(left, min(right, cx))
        cy = max(top, min(bottom, cy))
        return QPointF(cx - self._rect.width() / 2, cy - self._rect.height() / 2)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._dragging = True
        self._moved = False
        self._live_started = False
        self._press_scene = QPointF(event.scenePos())
        self._origin_pos = QPointF(self.pos())
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        delta = event.scenePos() - self._press_scene
        if abs(delta.x()) + abs(delta.y()) > 3:
            self._moved = True
            if not self._live_started:
                self._live_started = True
                # 超过阈值才裁切像素 / 显示网格，避免单击误擦除。
                self.dragStarted.emit()
        if self._live_started:
            self.setPos(self._clamp_pos(self._origin_pos + delta))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        was_dragging = self._dragging
        moved = self._moved
        live = self._live_started
        self._dragging = False
        self._live_started = False
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        if was_dragging and event.button() == Qt.MouseButton.LeftButton:
            if moved and live:
                nx, ny = self._center_norm()
                cw = max(1.0, self._canvas_rect.width())
                ch = max(1.0, self._canvas_rect.height())
                cx = self._canvas_rect.x() + nx * cw
                cy = self._canvas_rect.y() + ny * ch
                self.setPos(
                    QPointF(cx - self._rect.width() / 2, cy - self._rect.height() / 2)
                )
                self.positionCommitted.emit(self.key, nx, ny)
                self.dragFinished.emit()
            elif not moved:
                if self._on_activate is not None:
                    self._on_activate(self.key, self.payload)
                self.activated.emit(self.key, self.payload)
            event.accept()
        self.update()
        if not event.isAccepted():
            super().mouseReleaseEvent(event)


class HitTextItem(QGraphicsObject):
    """文字命中热区，点击打开编辑（非自定义模式）。"""

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
