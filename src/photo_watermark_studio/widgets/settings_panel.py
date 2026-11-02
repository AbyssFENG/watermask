# -*- coding: utf-8 -*-
"""右侧分组属性面板（模板 / 内容 / 元数据 / 外观 / 布局 / 导出）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.document import ANCHORS, WatermarkDocument
from photo_watermark_studio.core.settings_store import STYLES, THEMES, coerce_settings

_META_FIELDS = (
    ("camera", "相机型号", "show_camera", "camera_text", "camera_scale", "showCameraBox"),
    ("lens", "镜头型号", "show_lens", "lens_text", "lens_scale", "showLensBox"),
    ("exif", "曝光参数", "show_exif", "exif_text", "exif_scale", "showExifBox"),
    ("date", "拍摄时间", "show_date", "date_text", "date_scale", "showDateBox"),
    ("gps", "GPS 坐标", "show_gps", "gps_text", "gps_scale", "showGpsBox"),
)

_FIELD_SCALE_KEYS = {
    "camera": "camera_scale",
    "lens": "lens_scale",
    "exif": "exif_scale",
    "date": "date_scale",
    "gps": "gps_scale",
}

_ANCHOR_LABELS = {
    "top_left": "左上",
    "top_center": "上中",
    "top_right": "右上",
    "middle_left": "左中",
    "center": "居中",
    "middle_right": "右中",
    "bottom_left": "左下",
    "bottom_center": "下中",
    "bottom_right": "右下",
}


class _Group(QFrame):
    def __init__(self, title: str, expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName("InspectorGroup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName("InspectorGroupToggle")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.body = QWidget()
        self.body.setObjectName("InspectorGroupBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(8, 4, 8, 8)
        self.body_layout.setSpacing(6)
        self.body.setVisible(expanded)
        self.toggle.toggled.connect(self._on_toggle)
        outer.addWidget(self.toggle)
        outer.addWidget(self.body)

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def add(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)


class SettingsPanel(QFrame):
    optionsChanged = Signal()
    chooseLogoRequested = Signal()
    clearLogoRequested = Signal()
    chooseOutputRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(300)
        self._loading = False
        self._logo_path = ""
        self._output_dir = ""
        self._placeholders: dict[str, str] = {
            "camera": "",
            "lens": "",
            "exif": "",
            "date": "",
            "gps": "",
        }
        self._field_texts: dict[str, str] = {
            "brand": "",
            "caption": "",
            "camera": "",
            "lens": "",
            "exif": "",
            "date": "",
            "gps": "",
        }
        self._field_scales: dict[str, float] = {key: 1.0 for key in _FIELD_SCALE_KEYS}
        self._missing_hint = QLabel("")
        self._missing_hint.setObjectName("MutedLabel")
        self._missing_hint.setWordWrap(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 8)
        title = QLabel("水印属性")
        title.setObjectName("PanelTitle")
        hint = QLabel("分组调整模板、内容、布局与导出")
        hint.setObjectName("PanelHint")
        hint.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(hint)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("SettingsBody")
        form = QVBoxLayout(body)
        form.setContentsMargins(12, 4, 12, 16)
        form.setSpacing(4)

        # 模板
        g_template = _Group("模板", True)
        self.style_combo = QComboBox()
        self.style_combo.setObjectName("styleCombo")
        self.style_combo.addItems(list(STYLES))
        self.style_combo.currentTextChanged.connect(self._emit)
        g_template.add(self._label("水印模板"))
        g_template.add(self.style_combo)
        form.addWidget(g_template)

        # 内容
        g_content = _Group("内容", True)
        self.brand_edit = QLineEdit()
        self.brand_edit.setObjectName("brandEdit")
        self.brand_edit.setPlaceholderText("留空则不显示")
        self.brand_edit.textChanged.connect(self._on_brand_changed)
        self.caption_edit = QLineEdit()
        self.caption_edit.setObjectName("captionEdit")
        self.caption_edit.setPlaceholderText("例如 城市 · 天气")
        self.caption_edit.textChanged.connect(self._on_caption_changed)
        self.logo_label = QLabel("未选择 Logo（支持透明 PNG）")
        self.logo_label.setObjectName("PathLabel")
        self.logo_label.setWordWrap(True)
        logo_row = QHBoxLayout()
        self.logo_button = QPushButton("选择 Logo")
        self.logo_button.setObjectName("chooseLogoButton")
        self.logo_button.setProperty("role", "soft")
        self.logo_button.clicked.connect(self.chooseLogoRequested)
        self.clear_logo_button = QPushButton("移除")
        self.clear_logo_button.setObjectName("clearLogoButton")
        self.clear_logo_button.setProperty("role", "soft")
        self.clear_logo_button.clicked.connect(self.clearLogoRequested)
        logo_row.addWidget(self.logo_button)
        logo_row.addWidget(self.clear_logo_button)
        self.show_brand_text = self._check("Logo 旁显示署名", "showBrandTextBox")
        g_content.add(self._label("品牌 / 摄影署名"))
        g_content.add(self.brand_edit)
        g_content.add(self._label("自定义说明"))
        g_content.add(self.caption_edit)
        g_content.add(self._label("Logo"))
        g_content.add(self.logo_label)
        g_content.body_layout.addLayout(logo_row)
        g_content.add(self.show_brand_text)
        form.addWidget(g_content)

        # 元数据
        g_meta = _Group("元数据", True)
        g_meta.add(self._label("勾选要显示的项；缺失字段不会伪造"))
        g_meta.add(self._missing_hint)
        checks = QGridLayout()
        checks.setHorizontalSpacing(10)
        checks.setVerticalSpacing(6)
        self.show_camera = self._check("相机型号", "showCameraBox")
        self.show_lens = self._check("镜头型号", "showLensBox")
        self.show_exif = self._check("曝光参数", "showExifBox")
        self.show_date = self._check("拍摄时间", "showDateBox")
        self.show_gps = self._check("GPS 坐标", "showGpsBox")
        checks.addWidget(self.show_camera, 0, 0)
        checks.addWidget(self.show_lens, 0, 1)
        checks.addWidget(self.show_exif, 1, 0)
        checks.addWidget(self.show_date, 1, 1)
        checks.addWidget(self.show_gps, 2, 0)
        g_meta.body_layout.addLayout(checks)
        tip = QLabel("点击预览中的水印文字可改文案和字号（按张保存，可撤销）。")
        tip.setObjectName("MutedLabel")
        tip.setWordWrap(True)
        g_meta.add(tip)
        form.addWidget(g_meta)

        # 外观
        g_look = _Group("外观", True)
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.currentTextChanged.connect(self._emit)
        g_look.add(self._label("底栏 / 相框配色"))
        g_look.add(self.theme_combo)
        g_look.add(self._label("水印大小"))
        scale_row = QHBoxLayout()
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setObjectName("scaleSlider")
        self.scale_slider.setRange(65, 160)
        self.scale_slider.setValue(100)
        self.scale_slider.valueChanged.connect(self._on_scale)
        self.scale_value = QLabel("100%")
        self.scale_value.setObjectName("ValueLabel")
        self.scale_value.setMinimumWidth(48)
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_value)
        g_look.body_layout.addLayout(scale_row)
        opacity_row = QHBoxLayout()
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setObjectName("barOpacitySpin")
        self.opacity_spin.setRange(0.15, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.72)
        self.opacity_spin.valueChanged.connect(self._emit)
        opacity_row.addWidget(self._label("底栏透明度"))
        opacity_row.addWidget(self.opacity_spin)
        g_look.body_layout.addLayout(opacity_row)
        form.addWidget(g_look)

        # 位置与布局
        g_layout = _Group("位置与布局", True)
        self.anchor_combo = QComboBox()
        self.anchor_combo.setObjectName("anchorCombo")
        for key in ANCHORS:
            self.anchor_combo.addItem(_ANCHOR_LABELS.get(key, key), key)
        self.anchor_combo.currentIndexChanged.connect(self._emit)
        g_layout.add(self._label("九宫格定位（主要影响极简叠加）"))
        g_layout.add(self.anchor_combo)
        margin_row = QHBoxLayout()
        self.margin_x = QDoubleSpinBox()
        self.margin_x.setRange(0.0, 0.35)
        self.margin_x.setSingleStep(0.01)
        self.margin_x.setDecimals(2)
        self.margin_x.setObjectName("marginXSpin")
        self.margin_x.valueChanged.connect(self._emit)
        self.margin_y = QDoubleSpinBox()
        self.margin_y.setRange(0.0, 0.35)
        self.margin_y.setSingleStep(0.01)
        self.margin_y.setDecimals(2)
        self.margin_y.setObjectName("marginYSpin")
        self.margin_y.valueChanged.connect(self._emit)
        margin_row.addWidget(self._label("边距 X"))
        margin_row.addWidget(self.margin_x)
        margin_row.addWidget(self._label("Y"))
        margin_row.addWidget(self.margin_y)
        g_layout.body_layout.addLayout(margin_row)
        offset_row = QHBoxLayout()
        self.offset_x = QDoubleSpinBox()
        self.offset_x.setRange(-0.45, 0.45)
        self.offset_x.setSingleStep(0.01)
        self.offset_x.setDecimals(2)
        self.offset_x.setObjectName("offsetXSpin")
        self.offset_x.valueChanged.connect(self._emit)
        self.offset_y = QDoubleSpinBox()
        self.offset_y.setRange(-0.45, 0.45)
        self.offset_y.setSingleStep(0.01)
        self.offset_y.setDecimals(2)
        self.offset_y.setObjectName("offsetYSpin")
        self.offset_y.valueChanged.connect(self._emit)
        offset_row.addWidget(self._label("偏移 X"))
        offset_row.addWidget(self.offset_x)
        offset_row.addWidget(self._label("Y"))
        offset_row.addWidget(self.offset_y)
        g_layout.body_layout.addLayout(offset_row)
        form.addWidget(g_layout)

        # 导出
        g_export = _Group("导出", True)
        self.output_label = QLabel("")
        self.output_label.setObjectName("PathLabel")
        self.output_label.setWordWrap(True)
        self.output_button = QPushButton("选择导出目录")
        self.output_button.setObjectName("chooseOutputButton")
        self.output_button.setProperty("role", "soft")
        self.output_button.clicked.connect(self.chooseOutputRequested)
        g_export.add(self._label("导出目录"))
        g_export.add(self.output_label)
        g_export.add(self.output_button)
        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setObjectName("qualitySlider")
        self.quality_slider.setRange(80, 100)
        self.quality_slider.setValue(95)
        self.quality_slider.valueChanged.connect(self._on_quality)
        self.quality_value = QLabel("95")
        self.quality_value.setObjectName("ValueLabel")
        quality_row.addWidget(self._label("JPG 质量"))
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_value)
        g_export.body_layout.addLayout(quality_row)
        self.conflict_combo = QComboBox()
        self.conflict_combo.setObjectName("conflictCombo")
        self.conflict_combo.addItem("重名时自动编号", "number")
        self.conflict_combo.addItem("重名时覆盖（需确认）", "overwrite")
        self.conflict_combo.currentIndexChanged.connect(self._emit)
        g_export.add(self._label("文件冲突"))
        g_export.add(self.conflict_combo)
        form.addWidget(g_export)
        form.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._inputs = [
            self.style_combo,
            self.theme_combo,
            self.brand_edit,
            self.caption_edit,
            self.show_camera,
            self.show_lens,
            self.show_exif,
            self.show_date,
            self.show_gps,
            self.show_brand_text,
            self.scale_slider,
            self.quality_slider,
            self.opacity_spin,
            self.anchor_combo,
            self.margin_x,
            self.margin_y,
            self.offset_x,
            self.offset_y,
            self.conflict_combo,
        ]

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _check(self, text: str, object_name: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setObjectName(object_name)
        box.toggled.connect(self._emit)
        return box

    def _emit(self, *_args: object) -> None:
        if not self._loading:
            self.optionsChanged.emit()

    def _on_brand_changed(self, *_args: object) -> None:
        self._field_texts["brand"] = self.brand_edit.text()
        self._emit()

    def _on_caption_changed(self, *_args: object) -> None:
        self._field_texts["caption"] = self.caption_edit.text()
        self._emit()

    def _on_scale(self, value: int) -> None:
        self.scale_value.setText(f"{int(value)}%")
        self._emit()

    def _on_quality(self, value: int) -> None:
        self.quality_value.setText(str(int(value)))
        self._emit()

    def _update_logo_label(self) -> None:
        path = self._logo_path
        missing = False
        if not path:
            self.logo_label.setText("未选择 Logo（支持透明 PNG）")
        else:
            name = Path(path).name
            if Path(path).is_file():
                self.logo_label.setText(name)
            else:
                self.logo_label.setText(f"路径失效：{name}")
                missing = True
        self.logo_label.setProperty("missing", missing)
        self.logo_label.style().unpolish(self.logo_label)
        self.logo_label.style().polish(self.logo_label)

    def set_logo_path(self, path: str) -> None:
        self._logo_path = path or ""
        self._update_logo_label()
        self._emit()

    def set_output_dir(self, path: str) -> None:
        self._output_dir = path
        self.output_label.setText(path)
        self.output_label.setToolTip(path)
        self._emit()

    def set_layout_offset(self, ox: float, oy: float) -> None:
        self._loading = True
        self.offset_x.blockSignals(True)
        self.offset_y.blockSignals(True)
        self.offset_x.setValue(float(ox))
        self.offset_y.setValue(float(oy))
        self.offset_x.blockSignals(False)
        self.offset_y.blockSignals(False)
        self._loading = False

    def set_metadata_placeholders(self, values: dict[str, str] | None) -> None:
        data = values or {}
        self._placeholders = {
            "camera": str(data.get("camera", "") or ""),
            "lens": str(data.get("lens", "") or ""),
            "exif": str(data.get("exif", "") or ""),
            "date": str(data.get("date", "") or ""),
            "gps": str(data.get("gps", "") or ""),
        }
        missing = [label for key, label, *_rest in _META_FIELDS if not self._placeholders.get(key)]
        if missing:
            self._missing_hint.setText("当前照片缺少：" + "、".join(missing))
        else:
            self._missing_hint.setText("当前照片 EXIF 字段齐全。")

    def placeholders(self) -> dict[str, str]:
        return dict(self._placeholders)

    def field_editor_state(self, key: str) -> dict[str, Any]:
        scale_key = _FIELD_SCALE_KEYS.get(key)
        if key == "brand":
            custom = self.brand_edit.text()
            hint = "留空则不显示"
        elif key == "caption":
            custom = self.caption_edit.text()
            hint = "例如 城市 · 天气"
        else:
            custom = ""
            hint = self._placeholders.get(key, "") or "留空则用照片信息"
        return {
            "key": key,
            "text": custom,
            "display": custom,
            "placeholder": hint,
            "scale": float(self._field_scales.get(key, 1.0)) if scale_key else None,
            "has_scale": scale_key is not None,
        }

    def apply_field_edit(self, key: str, text: str, scale: float | None = None) -> None:
        if key == "brand":
            self.brand_edit.blockSignals(True)
            self.brand_edit.setText(text)
            self.brand_edit.blockSignals(False)
            self._field_texts["brand"] = text
            self._emit()
            return
        if key == "caption":
            self.caption_edit.blockSignals(True)
            self.caption_edit.setText(text)
            self.caption_edit.blockSignals(False)
            self._field_texts["caption"] = text
            self._emit()

    def state(self) -> dict[str, Any]:
        layout = {
            "anchor": self.anchor_combo.currentData(),
            "margin_x": self.margin_x.value(),
            "margin_y": self.margin_y.value(),
            "offset_x": self.offset_x.value(),
            "offset_y": self.offset_y.value(),
            "bar_opacity": self.opacity_spin.value(),
            "corner_radius": 0,
            "blur_radius": 12.0,
        }
        data: dict[str, Any] = {
            "style": self.style_combo.currentText(),
            "theme": self.theme_combo.currentText(),
            "brand": self.brand_edit.text(),
            "caption": self.caption_edit.text(),
            "scale": self.scale_slider.value() / 100,
            "logo_path": self._logo_path,
            "show_camera": self.show_camera.isChecked(),
            "show_lens": self.show_lens.isChecked(),
            "show_exif": self.show_exif.isChecked(),
            "show_date": self.show_date.isChecked(),
            "show_gps": self.show_gps.isChecked(),
            "show_brand_text": self.show_brand_text.isChecked(),
            "quality": self.quality_slider.value(),
            "output_dir": self._output_dir,
            "layout": layout,
            "conflict_policy": self.conflict_combo.currentData(),
        }
        for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
            data[text_key] = ""
            data[scale_key] = 1.0
        return data

    def document(self) -> WatermarkDocument:
        return WatermarkDocument(self.state())

    def set_state(self, state: dict[str, Any]) -> None:
        data = coerce_settings(state)
        layout = data.get("layout") if isinstance(data.get("layout"), dict) else {}
        self._loading = True
        for widget in self._inputs:
            widget.blockSignals(True)
        try:
            style_index = self.style_combo.findText(str(data["style"]))
            self.style_combo.setCurrentIndex(style_index if style_index >= 0 else 0)
            theme_index = self.theme_combo.findText(str(data["theme"]))
            self.theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
            self.brand_edit.setText(str(data["brand"]))
            self.caption_edit.setText(str(data["caption"]))
            self._field_texts["brand"] = str(data["brand"])
            self._field_texts["caption"] = str(data["caption"])
            self.show_camera.setChecked(bool(data["show_camera"]))
            self.show_lens.setChecked(bool(data["show_lens"]))
            self.show_exif.setChecked(bool(data["show_exif"]))
            self.show_date.setChecked(bool(data["show_date"]))
            self.show_gps.setChecked(bool(data["show_gps"]))
            self.show_brand_text.setChecked(bool(data["show_brand_text"]))
            for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
                self._field_texts[key] = str(data[text_key])
                self._field_scales[key] = float(data[scale_key])
            self.scale_slider.setValue(int(round(float(data["scale"]) * 100)))
            self.scale_value.setText(f"{self.scale_slider.value()}%")
            self.quality_slider.setValue(int(data["quality"]))
            self.quality_value.setText(str(self.quality_slider.value()))
            self._logo_path = str(data["logo_path"])
            self._update_logo_label()
            self._output_dir = str(data["output_dir"])
            self.output_label.setText(self._output_dir)
            self.output_label.setToolTip(self._output_dir)
            self.opacity_spin.setValue(float(layout.get("bar_opacity", 0.72)))
            self.margin_x.setValue(float(layout.get("margin_x", 0.0)))
            self.margin_y.setValue(float(layout.get("margin_y", 0.0)))
            self.offset_x.setValue(float(layout.get("offset_x", 0.0)))
            self.offset_y.setValue(float(layout.get("offset_y", 0.0)))
            anchor = str(layout.get("anchor", "bottom_center"))
            idx = self.anchor_combo.findData(anchor)
            self.anchor_combo.setCurrentIndex(idx if idx >= 0 else self.anchor_combo.findData("bottom_center"))
            policy = str(data.get("conflict_policy", "number"))
            pidx = self.conflict_combo.findData(policy)
            self.conflict_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
        finally:
            for widget in self._inputs:
                widget.blockSignals(False)
            self._loading = False
