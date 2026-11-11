# -*- coding: utf-8 -*-
"""检查面板通用控件：分节、开关、分段选择、预设按钮行、带数值滑条。"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ControlSection(QFrame):
    """原型里的 control-section：粗体标题 + 右侧小字说明 + 内容。"""

    def __init__(self, title: str, hint: str = "", *, first: bool = False) -> None:
        super().__init__()
        self.setObjectName("ControlSection")
        self.setProperty("first", first)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4 if first else 13, 0, 9)
        outer.setSpacing(9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("ControlTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("ControlHint")
        self.hint_label.setVisible(bool(hint))
        head.addWidget(self.hint_label)
        outer.addLayout(head)
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        outer.addLayout(self.body_layout)

    def add(self, item: QWidget | QLayout) -> None:
        if isinstance(item, QLayout):
            self.body_layout.addLayout(item)
        else:
            self.body_layout.addWidget(item)


class ToggleSwitch(QAbstractButton):
    """整行可点的开关：左侧文字，右侧胶囊开关。保留 QCheckBox 的 isChecked/toggled 接口。"""

    _TRACK_W = 34
    _TRACK_H = 19

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        width = self.fontMetrics().horizontalAdvance(self.text()) + self._TRACK_W + 16
        return QSize(width, 28)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._TRACK_W + 8, 28)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        text_color = QColor("#687080" if enabled else "#B3B8C3")
        painter.setPen(text_color)
        text_rect = self.rect().adjusted(0, 0, -(self._TRACK_W + 8), 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        x = self.width() - self._TRACK_W
        y = (self.height() - self._TRACK_H) / 2
        track = QRectF(x, y, self._TRACK_W, self._TRACK_H)
        on = self.isChecked()
        if not enabled:
            color = QColor("#E6E8EE")
        else:
            color = QColor("#7E8BE5" if on else "#D8DCE5")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, self._TRACK_H / 2, self._TRACK_H / 2)
        knob = self._TRACK_H - 4
        knob_x = x + (self._TRACK_W - knob - 2 if on else 2)
        painter.setBrush(QColor(0, 0, 0, 28))
        painter.drawEllipse(QRectF(knob_x, y + 3, knob, knob))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(knob_x, y + 2, knob, knob))
        painter.end()


class SegmentControl(QWidget):
    """胶囊分段选择，单选。"""

    currentChanged = Signal(int)

    def __init__(self, labels: Iterable[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Segment")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._index = 0
        self._buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(5)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=index: self.setCurrentIndex(value))
            self._group.addButton(button)
            self._buttons.append(button)
            layout.addWidget(button, 1)

    def count(self) -> int:
        return len(self._buttons)

    def button(self, index: int) -> QPushButton:
        return self._buttons[index]

    def currentIndex(self) -> int:
        return self._index

    def currentText(self) -> str:
        return self._buttons[self._index].text() if self._buttons else ""

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index == self._index:
            return
        self._index = index
        if not self.signalsBlocked():
            self.currentChanged.emit(index)


class PresetRow(QWidget):
    """一行可单选的预设按钮，每个按钮带一个数据值。"""

    triggered = Signal(object)

    def __init__(self, items: Iterable[tuple[Any, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PresetRow")
        self._buttons: dict[Any, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for value, text in items:
            button = QPushButton(text)
            button.setObjectName("PresetButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, data=value: self.triggered.emit(data))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button, 1)

    def button(self, value: Any) -> QPushButton | None:
        return self._buttons.get(value)

    def currentData(self) -> Any:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return None

    def setCurrentData(self, value: Any) -> None:
        button = self._buttons.get(value)
        if button is not None:
            button.setChecked(True)


class _NoWheelSlider(QSlider):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class ValueSlider(QWidget):
    """标题行（名称 + 当前值）下面一条滑条。"""

    valueChanged = Signal(int)

    def __init__(
        self,
        title: str,
        low: int,
        high: int,
        value: int,
        *,
        object_name: str = "",
        formatter: Callable[[int], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ValueSliderRow")
        self._formatter = formatter or (lambda number: f"{number}%")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(5)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("FieldHead")
        self.value_label = QLabel("")
        self.value_label.setObjectName("FieldValue")
        head.addWidget(self.title_label)
        head.addStretch(1)
        head.addWidget(self.value_label)
        layout.addLayout(head)
        self.slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        if object_name:
            self.slider.setObjectName(object_name)
        self.slider.setRange(low, high)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_value)
        layout.addWidget(self.slider)
        self._refresh_label()

    def _on_value(self, number: int) -> None:
        self._refresh_label()
        self.valueChanged.emit(int(number))

    def _refresh_label(self) -> None:
        self.value_label.setText(self._formatter(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(value))
        self._refresh_label()

    def blockSignals(self, block: bool) -> bool:  # noqa: N802 — Qt 命名
        self.slider.blockSignals(block)
        return super().blockSignals(block)


class _SwatchButton(QAbstractButton):
    def __init__(self, hex_color: str = "", *, picker: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hex_color = hex_color.upper()
        self.is_picker = picker
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        outer = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor("#7C89E2" if active else "#D9DDE7"), 2 if active else 1))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(outer)
        inner = QRectF(3.5, 3.5, self.width() - 7, self.height() - 7)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.is_picker and not self.hex_color:
            grad = QLinearGradient(inner.topLeft(), inner.bottomRight())
            grad.setColorAt(0.0, QColor("#B4A4E8"))
            grad.setColorAt(1.0, QColor("#E6B8C5"))
            painter.setBrush(grad)
        else:
            painter.setBrush(QColor(self.hex_color or "#FFFFFF"))
        painter.drawEllipse(inner)
        if self.is_picker:
            luma = 200
            if self.hex_color:
                c = QColor(self.hex_color)
                luma = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
            painter.setPen(QColor("#232730" if luma >= 145 else "#FFFFFF"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "＋")
        painter.end()


class ColorSwatchRow(QWidget):
    """原型背景颜色行：标题 + 五颗预设色卡 + 一颗「＋」自选取色器。"""

    colorSelected = Signal(str)

    def __init__(
        self,
        presets: Iterable[str] = ("#FFFFFF", "#22252B", "#E9E5DC", "#CBD6DF", "#D5C0E6"),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ColorSwatchRow")
        self._color = ""
        self._swatches: dict[str, _SwatchButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("背景颜色")
        self.title_label.setObjectName("FieldHead")
        self.value_label = QLabel("跟随主题")
        self.value_label.setObjectName("FieldValue")
        head.addWidget(self.title_label)
        head.addStretch(1)
        head.addWidget(self.value_label)
        layout.addLayout(head)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for idx, raw in enumerate(presets):
            code = raw.upper()
            btn = _SwatchButton(code, parent=self)
            btn.setObjectName(f"swatch_{idx}")
            btn.setToolTip(code)
            btn.clicked.connect(lambda _checked=False, value=code: self.select_color(value))
            self._swatches[code] = btn
            row.addWidget(btn)
        self.picker_button = _SwatchButton("", picker=True, parent=self)
        self.picker_button.setObjectName("customColorSwatch")
        self.picker_button.setToolTip("自选任意颜色")
        self.picker_button.clicked.connect(self._open_color_dialog)
        row.addWidget(self.picker_button)
        row.addStretch(1)
        layout.addLayout(row)
        self._sync_buttons()

    def color(self) -> str:
        return self._color

    def button(self, hex_color: str) -> _SwatchButton | None:
        return self._swatches.get(str(hex_color or "").upper())

    def select_color(self, hex_color: str, *, emit: bool = True) -> None:
        clean = str(hex_color or "").strip().upper()
        self._color = clean
        self._sync_buttons()
        if emit and not self.signalsBlocked():
            self.colorSelected.emit(self._color)

    def set_color(self, hex_color: str) -> None:
        self.select_color(hex_color, emit=False)

    def _open_color_dialog(self) -> None:
        initial = QColor(self._color) if self._color else QColor("#D5C0E6")
        chosen = QColorDialog.getColor(initial, self, "选择背景颜色")
        if not chosen.isValid():
            self._sync_buttons()
            return
        self.select_color(chosen.name().upper(), emit=True)

    def _sync_buttons(self) -> None:
        matched = False
        for code, btn in self._swatches.items():
            on = bool(self._color) and code == self._color
            btn.setChecked(on)
            btn.update()
            if on:
                matched = True
        custom = bool(self._color) and not matched
        self.picker_button.hex_color = self._color if custom else ""
        self.picker_button.setChecked(custom)
        self.picker_button.update()
        self.value_label.setText(self._color if self._color else "跟随主题")

