# -*- coding: utf-8 -*-
"""右侧水印设置。控件只反映同一份配置。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.settings_store import STYLES, THEMES, coerce_settings

_META_FIELDS = (
    ("camera", "相机型号", "show_camera", "camera_text", "camera_scale", "showCameraBox"),
    ("lens", "镜头型号", "show_lens", "lens_text", "lens_scale", "showLensBox"),
    ("exif", "曝光参数", "show_exif", "exif_text", "exif_scale", "showExifBox"),
    ("date", "拍摄时间", "show_date", "date_text", "date_scale", "showDateBox"),
    ("gps", "GPS 坐标", "show_gps", "gps_text", "gps_scale", "showGpsBox"),
)

_FIELD_TEXT_KEYS = {
    "camera": "camera_text",
    "lens": "lens_text",
    "exif": "exif_text",
    "date": "date_text",
    "gps": "gps_text",
    "brand": "brand",
    "caption": "caption",
}
_FIELD_SCALE_KEYS = {
    "camera": "camera_scale",
    "lens": "lens_scale",
    "exif": "exif_scale",
    "date": "date_scale",
    "gps": "gps_scale",
}


class SettingsPanel(QFrame):
    optionsChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(286)
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
        self._field_texts: dict[str, str] = {key: "" for key in _FIELD_TEXT_KEYS}
        self._field_scales: dict[str, float] = {key: 1.0 for key in _FIELD_SCALE_KEYS}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 8)
        layout.setSpacing(8)

        title = QLabel("水印设置")
        title.setObjectName("PanelTitle")
        title.setContentsMargins(16, 0, 16, 0)
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SettingsBody")
        form = QVBoxLayout(body)
        form.setContentsMargins(16, 4, 16, 16)
        form.setSpacing(6)

        form.addWidget(self._field_label("水印模板"))
        self.style_combo = QComboBox()
        self.style_combo.setObjectName("styleCombo")
        self.style_combo.addItems(list(STYLES))
        self.style_combo.currentTextChanged.connect(self._emit)
        form.addWidget(self.style_combo)

        form.addWidget(self._field_label("底栏 / 相框配色"))
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.currentTextChanged.connect(self._emit)
        form.addWidget(self.theme_combo)

        form.addWidget(self._field_label("品牌 / 摄影署名（留空则不显示）"))
        self.brand_edit = QLineEdit()
        self.brand_edit.setObjectName("brandEdit")
        self.brand_edit.setPlaceholderText("留空则不显示")
        self.brand_edit.textChanged.connect(self._on_brand_changed)
        form.addWidget(self.brand_edit)

        form.addWidget(self._field_label("自定义说明（可选）"))
        self.caption_edit = QLineEdit()
        self.caption_edit.setObjectName("captionEdit")
        self.caption_edit.setPlaceholderText("例如 城市 · 天气")
        self.caption_edit.textChanged.connect(self._on_caption_changed)
        form.addWidget(self.caption_edit)

        form.addWidget(self._divider())
        form.addWidget(self._field_label("自动读取并显示的照片信息"))
        hint = QLabel("勾选要显示的项。点击预览中的水印文字可改文案和字号（写入临时文件，导出或退出后清除）。")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        form.addWidget(hint)

        checks = QGridLayout()
        checks.setHorizontalSpacing(10)
        checks.setVerticalSpacing(6)
        self.show_camera = self._check("相机型号", "showCameraBox")
        self.show_lens = self._check("镜头型号", "showLensBox")
        self.show_exif = self._check("曝光参数", "showExifBox")
        self.show_date = self._check("拍摄时间", "showDateBox")
        self.show_gps = self._check("GPS 坐标", "showGpsBox")
        self.show_brand_text = self._check("Logo 旁显示署名", "showBrandTextBox")
        checks.addWidget(self.show_camera, 0, 0)
        checks.addWidget(self.show_lens, 0, 1)
        checks.addWidget(self.show_exif, 1, 0)
        checks.addWidget(self.show_date, 1, 1)
        checks.addWidget(self.show_gps, 2, 0)
        checks.addWidget(self.show_brand_text, 2, 1)
        form.addLayout(checks)

        form.addWidget(self._field_label("水印大小"))
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
        form.addLayout(scale_row)

        form.addWidget(self._divider())
        form.addWidget(self._field_label("自定义 Logo"))
        logo_row = QHBoxLayout()
        self.choose_logo_button = QPushButton("选择图片…")
        self.choose_logo_button.setObjectName("chooseLogoButton")
        self.choose_logo_button.setProperty("role", "soft")
        self.clear_logo_button = QPushButton("移除")
        self.clear_logo_button.setObjectName("clearLogoButton")
        self.clear_logo_button.setProperty("role", "soft")
        logo_row.addWidget(self.choose_logo_button)
        logo_row.addWidget(self.clear_logo_button)
        logo_row.addStretch(1)
        form.addLayout(logo_row)
        self.logo_label = QLabel("未选择 Logo（支持透明 PNG）")
        self.logo_label.setObjectName("MutedLabel")
        self.logo_label.setWordWrap(True)
        form.addWidget(self.logo_label)

        form.addWidget(self._field_label("导出目录"))
        output_row = QHBoxLayout()
        self.output_label = QLabel()
        self.output_label.setObjectName("PathLabel")
        self.output_label.setWordWrap(True)
        self.choose_output_button = QPushButton("选择")
        self.choose_output_button.setObjectName("chooseOutputButton")
        self.choose_output_button.setProperty("role", "soft")
        output_row.addWidget(self.output_label, 1)
        output_row.addWidget(self.choose_output_button)
        form.addLayout(output_row)

        quality_caption = QLabel("导出为 JPG · 质量")
        quality_caption.setObjectName("MutedLabel")
        form.addWidget(quality_caption)
        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setObjectName("qualitySlider")
        self.quality_slider.setRange(80, 100)
        self.quality_slider.setValue(95)
        self.quality_slider.valueChanged.connect(self._on_quality)
        self.quality_value = QLabel("95")
        self.quality_value.setObjectName("ValueLabel")
        self.quality_value.setMinimumWidth(32)
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_value)
        form.addLayout(quality_row)
        form.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

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
        ]

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        label.setWordWrap(True)
        return label

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

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

    def set_metadata_placeholders(self, values: dict[str, str] | None) -> None:
        data = values or {}
        self._placeholders = {
            "camera": str(data.get("camera", "") or ""),
            "lens": str(data.get("lens", "") or ""),
            "exif": str(data.get("exif", "") or ""),
            "date": str(data.get("date", "") or ""),
            "gps": str(data.get("gps", "") or ""),
        }

    def placeholders(self) -> dict[str, str]:
        return dict(self._placeholders)

    def field_editor_state(self, key: str) -> dict[str, Any]:
        """仅用于品牌/说明等常驻字段；元数据项由主窗口结合临时会话组装。"""
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
        }
        # 元数据文案/字号只存在临时会话，不写入正式设置。
        for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
            data[text_key] = ""
            data[scale_key] = 1.0
        return data

    def set_state(self, state: dict[str, Any]) -> None:
        data = coerce_settings(state)
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
        finally:
            for widget in self._inputs:
                widget.blockSignals(False)
            self._loading = False
