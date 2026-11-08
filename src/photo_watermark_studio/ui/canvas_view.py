# -*- coding: utf-8 -*-
"""中间画布：缩放、原图对比、水印图元交互。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyleOptionGraphicsItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.coordinate_mapper import CoordinateMapper, ImageSize, ViewRect
from photo_watermark_studio.core.font_presets import (
    DEFAULT_FONT_FAMILY,
    available_font_names,
    coerce_font_family,
    qt_family_for,
)
from photo_watermark_studio.core.settings_store import (
    DEFAULT_FIELD_BOLD,
    FIELD_GRID_STEP,
    FIELD_POSITION_KEYS,
    coerce_field_opacity,
)
from photo_watermark_studio.ui.watermark_items import DraggableFieldItem, HitTextItem, WatermarkBarItem

PLACEHOLDER_TEXT = "添加一张照片\n开始设计你的专属水印"


class _NineGridGuideItem(QGraphicsObject):
    """拖动字段时：整画布 5% 细网格，1/3·2/3 四根加粗（cosmetic）。"""

    def __init__(self) -> None:
        super().__init__()
        self._canvas = QRectF()
        self.setZValue(40)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setVisible(False)

    def set_canvas_rect(self, rect: QRectF) -> None:
        next_canvas = QRectF(rect)
        if next_canvas == self._canvas:
            return
        self.prepareGeometryChange()
        self._canvas = next_canvas
        self.update()

    def boundingRect(self) -> QRectF:
        return self._canvas

    @staticmethod
    def _draw_lines(
        painter: QPainter,
        lines: list[tuple[float, float, float, float]],
        *,
        shadow_color: QColor,
        accent_color: QColor,
        shadow_width: float,
        accent_width: float,
        dashed: bool,
    ) -> None:
        shadow = QPen(shadow_color, shadow_width)
        shadow.setCosmetic(True)
        painter.setPen(shadow)
        for x1, y1, x2, y2 in lines:
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
        accent = QPen(accent_color, accent_width)
        accent.setCosmetic(True)
        if dashed:
            accent.setStyle(Qt.PenStyle.DashLine)
            accent.setDashPattern([8, 5])
        painter.setPen(accent)
        for x1, y1, x2, y2 in lines:
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if self._canvas.isEmpty():
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        r = self._canvas
        step = max(0.01, float(FIELD_GRID_STEP))

        # 细网格：整画布；靠近 1/3、2/3 的留给加粗线。
        fine: list[tuple[float, float, float, float]] = []
        n = int(round(1.0 / step))
        for i in range(1, n):
            t = i * step
            if t >= 0.999:
                break
            if abs(t - 1 / 3) < 0.02 or abs(t - 2 / 3) < 0.02:
                continue
            x = r.left() + r.width() * t
            y = r.top() + r.height() * t
            fine.append((x, r.top(), x, r.bottom()))
            fine.append((r.left(), y, r.right(), y))
        self._draw_lines(
            painter,
            fine,
            shadow_color=QColor(0, 0, 0, 90),
            accent_color=QColor(255, 255, 255, 130),
            shadow_width=1.5,
            accent_width=1.25,
            dashed=False,
        )

        # 同一坐标系上加粗 1/3、2/3 四根线。
        thirds: list[tuple[float, float, float, float]] = []
        for frac in (1 / 3, 2 / 3):
            x = r.left() + r.width() * frac
            y = r.top() + r.height() * frac
            thirds.append((x, r.top(), x, r.bottom()))
            thirds.append((r.left(), y, r.right(), y))
        self._draw_lines(
            painter,
            thirds,
            shadow_color=QColor(0, 0, 0, 180),
            accent_color=QColor(255, 255, 255, 230),
            shadow_width=2.25,
            accent_width=1.75,
            dashed=True,
        )


class _ZoomView(QGraphicsView):
    viewportResized = Signal()
    scaleChanged = Signal(float)
    userZoomed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        # 左键留给水印字段；画布平移用右键。
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self._panning = False
        self._pan_last = QPoint()

    def current_scale(self) -> float:
        return abs(float(self.transform().m11()) or 1.0)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_by(1.1)
        else:
            self.zoom_by(1 / 1.1)
        event.accept()

    def zoom_by(self, factor: float) -> None:
        next_scale = max(0.05, min(16.0, self.current_scale() * factor))
        self.set_user_scale(next_scale, user=True)

    def set_user_scale(self, scale: float, *, user: bool = True) -> None:
        target = max(0.05, min(16.0, float(scale)))
        self.setTransform(QTransform.fromScale(target, target))
        self.scaleChanged.emit(target)
        if user:
            self.userZoomed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self._panning = True
            self._pan_last = event.pos()
            self.viewport().setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.buttons() & Qt.MouseButton.RightButton:
            delta = event.pos() - self._pan_last
            self._pan_last = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._panning:
            self._panning = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewportResized.emit()


class CanvasPanel(QFrame):
    """替代旧 PreviewPanel 的画布容器，保留兼容信号。"""

    viewportResized = Signal()
    fieldEditRequested = Signal(str)
    fieldChanged = Signal(str, str, object)
    fontFamilyChanged = Signal(str, str)  # field_key, font_family
    fontBoldChanged = Signal(str, bool)  # field_key, bold
    fontOpacityChanged = Signal(str, float)  # field_key, opacity 0.3–1.0
    layoutOffsetChanged = Signal(float, float)  # 兼容旧接线；自定义不再使用
    fieldPositionChanged = Signal(str, float, float)
    compareToggled = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("画布 / 实时预览")
        title.setObjectName("PanelTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        root.addLayout(title_row)

        self.tools_bar = QWidget()
        self.tools_bar.setObjectName("CanvasToolsBar")
        tools = QHBoxLayout(self.tools_bar)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)
        self.fit_button = QPushButton("适应窗口")
        self.fit_button.setObjectName("fitViewButton")
        self.fit_button.setProperty("role", "soft")
        self.one_button = QPushButton("100%")
        self.one_button.setObjectName("oneToOneButton")
        self.one_button.setProperty("role", "soft")
        self.zoom_out_button = QPushButton("缩小")
        self.zoom_out_button.setProperty("role", "soft")
        self.zoom_in_button = QPushButton("放大")
        self.zoom_in_button.setProperty("role", "soft")
        self.scale_label = QLabel("适应")
        self.scale_label.setObjectName("ValueLabel")
        self.compare_button = QPushButton("原图对比")
        self.compare_button.setObjectName("compareButton")
        self.compare_button.setCheckable(True)
        self.compare_button.setProperty("role", "soft")
        for btn in (
            self.fit_button,
            self.one_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.compare_button,
        ):
            tools.addWidget(btn)
        tools.addWidget(self.scale_label)
        tools.addStretch(1)
        root.addWidget(self.tools_bar)

        self.scene = QGraphicsScene(self)
        # 与浅色相框区分的中性灰底（导出不受影响）。
        self.scene.setBackgroundBrush(QBrush(QColor("#8B94A3")))
        self.view = _ZoomView()
        self.view.setScene(self.scene)
        self.view.setObjectName("CanvasView")
        root.addWidget(self.view, 1)

        self.empty_label = QLabel(PLACEHOLDER_TEXT)
        self.empty_label.setObjectName("EmptyCanvasLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.empty_label, 1)

        self.editor = QFrame()
        self.editor.setObjectName("FieldEditorBar")
        self.editor.setVisible(False)
        er = QHBoxLayout(self.editor)
        er.setContentsMargins(10, 8, 10, 8)
        er.setSpacing(8)
        self.editor_label = QLabel("字段")
        self.editor_label.setObjectName("MutedLabel")
        self.editor_text = QLineEdit()
        self.editor_text.setObjectName("watermarkTextEdit")
        self.editor_font = QComboBox()
        self.editor_font.setObjectName("watermarkFontCombo")
        self.editor_font.setFixedWidth(148)
        self.editor_font.setToolTip("水印字体")
        for name in available_font_names():
            self.editor_font.addItem(name)
            family = qt_family_for(name)
            if family:
                self.editor_font.setItemData(
                    self.editor_font.count() - 1,
                    QFont(family, 11),
                    Qt.ItemDataRole.FontRole,
                )
        self.editor_bold = QToolButton()
        self.editor_bold.setObjectName("watermarkBoldButton")
        self.editor_bold.setText("B")
        self.editor_bold.setCheckable(True)
        self.editor_bold.setToolTip("加粗")
        self.editor_bold.setFixedSize(32, 32)
        bold_font = QFont(self.editor_bold.font())
        bold_font.setBold(True)
        self.editor_bold.setFont(bold_font)
        self.editor_opacity_label = QLabel("透明")
        self.editor_opacity_label.setObjectName("MutedLabel")
        self.editor_opacity = QSpinBox()
        self.editor_opacity.setObjectName("watermarkOpacitySpin")
        self.editor_opacity.setRange(30, 100)
        self.editor_opacity.setSingleStep(5)
        self.editor_opacity.setSuffix("%")
        self.editor_opacity.setFixedWidth(72)
        self.editor_opacity.setToolTip("文字透明度")
        self.editor_opacity.setValue(100)
        self.editor_scale_label = QLabel("大小")
        self.editor_scale_label.setObjectName("MutedLabel")
        self.editor_scale = QSpinBox()
        self.editor_scale.setObjectName("watermarkScaleSpin")
        self.editor_scale.setRange(70, 160)
        self.editor_scale.setSingleStep(5)
        self.editor_scale.setSuffix("%")
        self.editor_scale.setFixedWidth(72)
        self.editor_scale.setToolTip("字段大小")
        self.editor_close = QPushButton("完成")
        self.editor_close.setProperty("role", "soft")
        er.addWidget(self.editor_label)
        er.addWidget(self.editor_text, 1)
        er.addWidget(self.editor_font)
        er.addWidget(self.editor_bold)
        er.addWidget(self.editor_opacity_label)
        er.addWidget(self.editor_opacity)
        er.addWidget(self.editor_scale_label)
        er.addWidget(self.editor_scale)
        er.addWidget(self.editor_close)
        self.tip = QLabel("修改写入当前照片覆盖；可撤销。右键拖动画布；预览为高分辨率，可放大查看细节。")
        self.tip.setObjectName("MutedLabel")
        self.tip.setWordWrap(True)
        self._tip_default = self.tip.text()
        root.addWidget(self.editor)
        root.addWidget(self.tip)

        self._photo_item = QGraphicsPixmapItem()
        self._photo_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._photo_item.setZValue(0)
        self.scene.addItem(self._photo_item)
        self._bar_item = WatermarkBarItem()
        self._bar_item.setVisible(False)
        self.scene.addItem(self._bar_item)
        self._guide_item = _NineGridGuideItem()
        self.scene.addItem(self._guide_item)
        self._hit_items: list[QGraphicsItem] = []
        self._editor_key = ""
        self._compare = False
        self._raw_image: QImage | None = None
        self._watermark_image: QImage | None = None
        self._hits: list[dict[str, Any]] = []
        self._image_size = ImageSize(1, 1)
        self._has_image = False
        self._fit_mode = True
        self._photo_token = ""
        self._allow_field_drag = False
        self._pending_drag_image: QImage | None = None
        self._pending_drag_hits: list[dict[str, Any]] = []
        self._field_dragging = False
        self._sprites: list[dict[str, Any]] = []
        self._pending_drag_sprites: list[dict[str, Any]] = []

        self.fit_button.clicked.connect(self.fit_in_view)
        self.one_button.clicked.connect(self.zoom_100)
        self.zoom_in_button.clicked.connect(lambda: self._manual_zoom(1.15))
        self.zoom_out_button.clicked.connect(lambda: self._manual_zoom(1 / 1.15))
        self.compare_button.toggled.connect(self._on_compare)
        self.view.scaleChanged.connect(self._on_scale_label)
        self.view.userZoomed.connect(self._on_user_zoomed)
        self.view.viewportResized.connect(self._on_viewport_resized)
        self.editor_text.textEdited.connect(self._emit_editor)
        self.editor_font.currentTextChanged.connect(self._emit_font_family)
        self.editor_bold.toggled.connect(self._emit_font_bold)
        self.editor_opacity.valueChanged.connect(self._emit_font_opacity)
        self.editor_scale.valueChanged.connect(self._emit_editor)
        self.editor_close.clicked.connect(self.hide_field_editor)

        self.show_message(PLACEHOLDER_TEXT, False)

    def viewport_size(self) -> tuple[int, int]:
        vp = self.view.viewport()
        return max(200, vp.width()), max(180, vp.height())

    def show_message(self, text: str, is_error: bool = False) -> None:
        self.empty_label.setText(text)
        self.empty_label.setVisible(True)
        self.view.setVisible(False)
        self.tools_bar.setVisible(False)
        self.tip.setVisible(False)
        self.editor.setVisible(False)
        self._photo_item.setPixmap(QPixmap())
        self._bar_item.setVisible(False)
        self._guide_item.setVisible(False)
        self._clear_hits()
        self._has_image = False
        self._photo_token = ""
        if is_error:
            self.empty_label.setProperty("error", True)
        else:
            self.empty_label.setProperty("error", False)
        self.empty_label.style().unpolish(self.empty_label)
        self.empty_label.style().polish(self.empty_label)

    def set_layout_offset(self, ox: float, oy: float) -> None:
        """兼容旧接口；字段级拖动不再使用整框偏移。"""
        return

    def set_layout_drag_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._allow_field_drag:
            self._update_tip()
            return
        self._allow_field_drag = enabled
        self._update_tip()
        if self._has_image and not self._compare and not self._field_dragging:
            self._rebuild_overlays(True)

    def _update_tip(self) -> None:
        if self._allow_field_drag:
            self.tip.setText("自定义模式：左键拖动字段，松手吸附网格；右键拖动画布。")
        else:
            self.tip.setText(self._tip_default)

    def set_photo_token(self, token: str) -> None:
        """换图时传入路径，用于决定是否重置适应窗口。"""
        token = str(token or "")
        if token != self._photo_token:
            self._photo_token = token
            self._fit_mode = True

    def set_preview_image(
        self,
        image: QImage,
        hits: list[dict[str, Any]] | None = None,
        *,
        sprites: list[dict[str, Any]] | None = None,
    ) -> None:
        if image.isNull():
            self.show_message(PLACEHOLDER_TEXT, False)
            return
        if self._field_dragging:
            # 拖动中只缓存结果，松手后再套用，避免框跳回。
            self._pending_drag_image = QImage(image)
            self._pending_drag_hits = list(hits or [])
            self._pending_drag_sprites = list(sprites or [])
            return
        keep_view = self._has_image and not self._fit_mode
        center = self.view.mapToScene(self.view.viewport().rect().center()) if keep_view else None
        scale = self.view.current_scale() if keep_view else 1.0

        self._watermark_image = QImage(image)
        self._hits = list(hits or [])
        self._sprites = list(sprites or [])
        self.empty_label.setVisible(False)
        self.tools_bar.setVisible(True)
        self.tip.setVisible(True)
        self.view.setVisible(True)
        self._apply_display_image()
        self._has_image = True

        if keep_view and center is not None:
            self.view.set_user_scale(scale, user=False)
            self.view.centerOn(center)
            self._fit_mode = False
            self._on_scale_label(self.view.current_scale())
        else:
            self.fit_in_view()

    def set_source_image(self, image: QImage | None) -> None:
        self._raw_image = QImage(image) if image is not None and not image.isNull() else None
        if self._compare:
            self._apply_display_image()

    def _apply_display_image(self) -> None:
        show_raw = self._compare and self._raw_image is not None and not self._raw_image.isNull()
        image = self._raw_image if show_raw else self._watermark_image
        if image is None or image.isNull():
            return
        pix = QPixmap.fromImage(image)
        self._photo_item.setPixmap(pix)
        self._image_size = ImageSize(pix.width(), pix.height())
        self.scene.setSceneRect(QRectF(pix.rect()).adjusted(-2, -2, 2, 2))
        self._rebuild_overlays(not show_raw)

    def _rebuild_overlays(self, show_watermark: bool) -> None:
        self._clear_hits()
        self._bar_item.setVisible(False)
        self._guide_item.setVisible(False)
        if not show_watermark:
            return
        view = ViewRect(0, 0, float(self._image_size.width), float(self._image_size.height))
        mapper = CoordinateMapper(self._image_size, view)
        canvas_rect = QRectF(0, 0, float(self._image_size.width), float(self._image_size.height))
        # 整画布细网格；1/3·2/3 四根加粗。
        self._guide_item.set_canvas_rect(canvas_rect)

        if self._allow_field_drag:
            # 自定义双层：底图无字段；字段用透明精灵图层跟手拖动。
            sprite_by_key = {
                str(s.get("key", "")): s for s in self._sprites if str(s.get("key", ""))
            }
            for hit in self._hits:
                key = str(hit.get("key", ""))
                if key not in FIELD_POSITION_KEYS:
                    continue
                spr = sprite_by_key.get(key)
                if spr is not None:
                    x, y = float(spr.get("x", 0)), float(spr.get("y", 0))
                    w, h = float(spr.get("w", 8)), float(spr.get("h", 8))
                else:
                    x, y, w, h = mapper.hit_to_scene(hit)
                item = DraggableFieldItem(
                    key,
                    hit,
                    QRectF(x, y, max(8, w), max(8, h)),
                    canvas_rect=canvas_rect,
                    on_activate=self._on_hit,
                )
                if spr is not None:
                    qimg = spr.get("image")
                    if isinstance(qimg, QImage) and not qimg.isNull():
                        item.set_content_pixmap(QPixmap.fromImage(qimg))
                item.positionCommitted.connect(self._on_field_position)
                item.dragStarted.connect(self._on_field_drag_started)
                item.dragFinished.connect(self._on_field_drag_finished)
                self.scene.addItem(item)
                self._hit_items.append(item)
            return

        bar_hit = None
        for hit in self._hits:
            if hit.get("key") == "watermark_bar":
                bar_hit = hit
                break
        if bar_hit is not None:
            x, y, w, h = mapper.hit_to_scene(bar_hit)
            self._bar_item.set_geometry(QRectF(x, y, w, h), locked=True)
            self._bar_item.setVisible(True)

        for hit in self._hits:
            key = str(hit.get("key", ""))
            if not key or key in ("watermark_bar", "photo_content"):
                continue
            x, y, w, h = mapper.hit_to_scene(hit)
            item = HitTextItem(key, hit, QRectF(x, y, max(8, w), max(8, h)), on_activate=self._on_hit)
            self.scene.addItem(item)
            self._hit_items.append(item)

    def _clear_hits(self) -> None:
        for item in self._hit_items:
            self.scene.removeItem(item)
        self._hit_items.clear()

    def _on_hit(self, key: str, payload: dict[str, Any]) -> None:
        self.fieldEditRequested.emit(key)

    def _on_field_position(self, key: str, nx: float, ny: float) -> None:
        self.fieldPositionChanged.emit(key, nx, ny)

    def _on_field_drag_started(self) -> None:
        self._field_dragging = True
        self._guide_item.setVisible(True)
        sender = self.sender()
        if isinstance(sender, DraggableFieldItem):
            sender.setZValue(60)

    def _on_field_drag_finished(self) -> None:
        self._field_dragging = False
        self._guide_item.setVisible(False)
        sender = self.sender()
        if isinstance(sender, DraggableFieldItem):
            sender.setZValue(45)
        pending = self._pending_drag_image
        hits = self._pending_drag_hits
        sprites = self._pending_drag_sprites
        self._pending_drag_image = None
        self._pending_drag_hits = []
        self._pending_drag_sprites = []
        if pending is not None and not pending.isNull():
            self.set_preview_image(pending, hits, sprites=sprites)

    def _on_compare(self, checked: bool) -> None:
        self._compare = checked
        self._apply_display_image()
        self.compareToggled.emit(checked)

    def _manual_zoom(self, factor: float) -> None:
        self._fit_mode = False
        self.view.zoom_by(factor)

    def _on_user_zoomed(self) -> None:
        self._fit_mode = False

    def zoom_100(self) -> None:
        """预览图 1:1 像素（接近原图像素，受预览上限约束）。"""
        self._fit_mode = False
        self.view.set_user_scale(1.0, user=True)
        if not self._photo_item.pixmap().isNull():
            self.view.centerOn(self._photo_item)

    def _on_scale_label(self, scale: float) -> None:
        if self._fit_mode:
            self.scale_label.setText("适应")
        else:
            self.scale_label.setText(f"{int(round(scale * 100))}%")

    def _on_viewport_resized(self) -> None:
        if self._fit_mode and self._has_image:
            self.fit_in_view()
        # 不再向外触发重渲；仅在适应模式下随窗口重算显示比例。

    def fit_in_view(self) -> None:
        if self._photo_item.pixmap().isNull():
            return
        self._fit_mode = True
        self.view.fitInView(self._photo_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._on_scale_label(self.view.current_scale())

    def open_field_editor(self, payload: dict[str, Any]) -> None:
        self._editor_key = str(payload.get("key", ""))
        self.editor_label.setText(str(payload.get("label", self._editor_key)))
        self.editor_text.blockSignals(True)
        self.editor_font.blockSignals(True)
        self.editor_bold.blockSignals(True)
        self.editor_opacity.blockSignals(True)
        self.editor_scale.blockSignals(True)
        self.editor_text.setText(str(payload.get("text", "")))
        self.editor_text.setPlaceholderText(str(payload.get("placeholder", "照片 EXIF 原文")))
        font_family = coerce_font_family(payload.get("font_family", DEFAULT_FONT_FAMILY))
        idx = self.editor_font.findText(font_family)
        self.editor_font.setCurrentIndex(idx if idx >= 0 else 0)
        default_bold = bool(DEFAULT_FIELD_BOLD.get(self._editor_key, False))
        self.editor_bold.setChecked(bool(payload.get("font_bold", default_bold)))
        opacity = coerce_field_opacity(payload.get("font_opacity", 1.0), 1.0)
        self.editor_opacity.setValue(int(round(opacity * 100)))
        has_scale = bool(payload.get("has_scale", False))
        self.editor_scale_label.setVisible(has_scale)
        self.editor_scale.setVisible(has_scale)
        if has_scale:
            scale = float(payload.get("scale", 1.0) or 1.0)
            self.editor_scale.setValue(int(round(scale * 100)))
        self.editor_text.blockSignals(False)
        self.editor_font.blockSignals(False)
        self.editor_bold.blockSignals(False)
        self.editor_opacity.blockSignals(False)
        self.editor_scale.blockSignals(False)
        self.editor.setVisible(True)
        self.editor_text.setFocus()

    def hide_field_editor(self) -> None:
        self.editor.setVisible(False)
        self._editor_key = ""

    def _emit_editor(self, *_args: object) -> None:
        if not self._editor_key:
            return
        scale = self.editor_scale.value() / 100 if self.editor_scale.isVisible() else None
        self.fieldChanged.emit(self._editor_key, self.editor_text.text(), scale)

    def _emit_font_family(self, *_args: object) -> None:
        if not self._editor_key:
            return
        self.fontFamilyChanged.emit(
            self._editor_key,
            coerce_font_family(self.editor_font.currentText()),
        )

    def _emit_font_bold(self, checked: bool) -> None:
        if not self._editor_key:
            return
        self.fontBoldChanged.emit(self._editor_key, bool(checked))

    def _emit_font_opacity(self, *_args: object) -> None:
        if not self._editor_key:
            return
        self.fontOpacityChanged.emit(
            self._editor_key,
            coerce_field_opacity(self.editor_opacity.value() / 100.0, 1.0),
        )

    def set_image(self, image: QImage, hits: list | None = None) -> None:
        self.set_preview_image(image, hits)

    def set_hits(self, hits: list | None) -> None:
        self._hits = list(hits or [])
        self._rebuild_overlays(not self._compare)
