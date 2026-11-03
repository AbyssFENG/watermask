# -*- coding: utf-8 -*-
"""中间画布：缩放、原图对比、水印图元交互。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.coordinate_mapper import CoordinateMapper, ImageSize, ViewRect
from photo_watermark_studio.ui.watermark_items import HitTextItem, WatermarkBarItem

PLACEHOLDER_TEXT = "添加一张照片\n开始设计你的专属水印"


class _ZoomView(QGraphicsView):
    viewportResized = Signal()
    scaleChanged = Signal(float)
    userZoomed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewportResized.emit()


class CanvasPanel(QFrame):
    """替代旧 PreviewPanel 的画布容器，保留兼容信号。"""

    viewportResized = Signal()
    fieldEditRequested = Signal(str)
    fieldChanged = Signal(str, str, object)
    layoutOffsetChanged = Signal(float, float)
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
        self.editor_scale = QSpinBox()
        self.editor_scale.setObjectName("watermarkScaleSpin")
        self.editor_scale.setRange(70, 160)
        self.editor_scale.setSingleStep(5)
        self.editor_scale.setSuffix("%")
        self.editor_scale.setFixedWidth(78)
        self.editor_close = QPushButton("完成")
        self.editor_close.setProperty("role", "soft")
        er.addWidget(self.editor_label)
        er.addWidget(self.editor_text, 1)
        er.addWidget(self.editor_scale)
        er.addWidget(self.editor_close)
        self.tip = QLabel("修改写入当前照片覆盖；可撤销。预览为高分辨率，可放大查看细节。")
        self.tip.setObjectName("MutedLabel")
        self.tip.setWordWrap(True)
        root.addWidget(self.editor)
        root.addWidget(self.tip)

        self._photo_item = QGraphicsPixmapItem()
        self._photo_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._photo_item.setZValue(0)
        self.scene.addItem(self._photo_item)
        self._bar_item = WatermarkBarItem()
        self._bar_item.setVisible(False)
        self.scene.addItem(self._bar_item)
        self._hit_items: list[HitTextItem] = []
        self._editor_key = ""
        self._compare = False
        self._raw_image: QImage | None = None
        self._watermark_image: QImage | None = None
        self._hits: list[dict[str, Any]] = []
        self._image_size = ImageSize(1, 1)
        self._layout_offset = (0.0, 0.0)
        self._suppress_move = False
        self._has_image = False
        self._fit_mode = True
        self._photo_token = ""

        self.fit_button.clicked.connect(self.fit_in_view)
        self.one_button.clicked.connect(self.zoom_100)
        self.zoom_in_button.clicked.connect(lambda: self._manual_zoom(1.15))
        self.zoom_out_button.clicked.connect(lambda: self._manual_zoom(1 / 1.15))
        self.compare_button.toggled.connect(self._on_compare)
        self.view.scaleChanged.connect(self._on_scale_label)
        self.view.userZoomed.connect(self._on_user_zoomed)
        self.view.viewportResized.connect(self._on_viewport_resized)
        self._bar_item.moved.connect(self._on_bar_moved)
        self.editor_text.textEdited.connect(self._emit_editor)
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
        self._layout_offset = (float(ox), float(oy))

    def set_photo_token(self, token: str) -> None:
        """换图时传入路径，用于决定是否重置适应窗口。"""
        token = str(token or "")
        if token != self._photo_token:
            self._photo_token = token
            self._fit_mode = True

    def set_preview_image(self, image: QImage, hits: list[dict[str, Any]] | None = None) -> None:
        if image.isNull():
            self.show_message(PLACEHOLDER_TEXT, False)
            return
        keep_view = self._has_image and not self._fit_mode
        center = self.view.mapToScene(self.view.viewport().rect().center()) if keep_view else None
        scale = self.view.current_scale() if keep_view else 1.0

        self._watermark_image = QImage(image)
        self._hits = list(hits or [])
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
        if not show_watermark:
            return
        bar_hit = None
        for hit in self._hits:
            if hit.get("key") == "watermark_bar":
                bar_hit = hit
                break
        view = ViewRect(0, 0, float(self._image_size.width), float(self._image_size.height))
        mapper = CoordinateMapper(self._image_size, view)
        if bar_hit is not None:
            x, y, w, h = mapper.hit_to_scene(bar_hit)
            self._suppress_move = True
            # 位置拖动暂关闭，底栏仅作选中/命中辅助，不可拖移。
            self._bar_item.set_geometry(QRectF(x, y, w, h), locked=True)
            self._bar_item.set_mapper_context(
                (float(self._image_size.width), float(self._image_size.height)),
                (mapper.scale_x, mapper.scale_y),
                self._layout_offset,
            )
            self._bar_item.setVisible(True)
            self._suppress_move = False
        for hit in self._hits:
            key = str(hit.get("key", ""))
            if not key or key == "watermark_bar":
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

    def _on_bar_moved(self, nx: float, ny: float) -> None:
        if self._suppress_move:
            return
        self._layout_offset = (nx, ny)
        self.layoutOffsetChanged.emit(nx, ny)

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
        self.editor_scale.blockSignals(True)
        self.editor_text.setText(str(payload.get("text", "")))
        self.editor_text.setPlaceholderText(str(payload.get("placeholder", "照片 EXIF 原文")))
        has_scale = bool(payload.get("has_scale", False))
        self.editor_scale.setVisible(has_scale)
        if has_scale:
            scale = float(payload.get("scale", 1.0) or 1.0)
            self.editor_scale.setValue(int(round(scale * 100)))
        self.editor_text.blockSignals(False)
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

    def set_image(self, image: QImage, hits: list | None = None) -> None:
        self.set_preview_image(image, hits)

    def set_hits(self, hits: list | None) -> None:
        self._hits = list(hits or [])
        self._rebuild_overlays(not self._compare)
