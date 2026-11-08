# -*- coding: utf-8 -*-
"""右侧分组属性面板（模板 / 内容 / 元数据 / 外观 / 布局 / 导出）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.document import WatermarkDocument
from photo_watermark_studio.core.font_presets import DEFAULT_FONT_FAMILY, coerce_font_family
from photo_watermark_studio.core.settings_store import (
    BUILTIN_STYLES,
    DEFAULT_FIELD_BOLD,
    FIELD_BOLD_KEYS,
    FIELD_FONT_KEYS,
    FIELD_OPACITY_KEYS,
    FIELD_POSITION_KEYS,
    STYLES,
    THEMES,
    coerce_field_opacity,
    coerce_field_positions,
    coerce_settings,
    default_layout,
    effective_style,
    snap_field_position,
)
from photo_watermark_studio.core import template_store


class _NoWheelComboBox(QComboBox):
    """禁止滚轮改选项，避免在属性栏滚动时误触。"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class _NoWheelSlider(QSlider):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


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
        self._field_positions: dict[str, dict[str, float]] = {}
        self._templates_path = template_store.default_templates_path()
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
        self._field_fonts: dict[str, str] = {
            key.removesuffix("_font"): DEFAULT_FONT_FAMILY for key in FIELD_FONT_KEYS
        }
        self._field_bolds: dict[str, bool] = {
            key: bool(DEFAULT_FIELD_BOLD.get(key, False)) for key in DEFAULT_FIELD_BOLD
        }
        self._field_opacities: dict[str, float] = {
            key.removesuffix("_opacity"): 1.0 for key in FIELD_OPACITY_KEYS
        }
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
        g_template = _Group("模板", False)
        self.style_combo = _NoWheelComboBox()
        self.style_combo.setObjectName("styleCombo")
        self.style_combo.addItems(list(STYLES))
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        g_template.add(self._label("水印模板"))
        g_template.add(self.style_combo)
        self.base_style_row = QWidget()
        base_col = QVBoxLayout(self.base_style_row)
        base_col.setContentsMargins(0, 0, 0, 0)
        base_col.setSpacing(4)
        self.base_style_combo = _NoWheelComboBox()
        self.base_style_combo.setObjectName("baseStyleCombo")
        self.base_style_combo.addItems(list(BUILTIN_STYLES))
        self.base_style_combo.currentTextChanged.connect(self._update_style_dependent_ui)
        self.base_style_combo.currentTextChanged.connect(self._emit)
        base_col.addWidget(self._label("自定义底版"))
        base_col.addWidget(self.base_style_combo)
        g_template.add(self.base_style_row)
        g_template.add(self._label("用户模板"))
        self.user_template_combo = _NoWheelComboBox()
        self.user_template_combo.setObjectName("userTemplateCombo")
        g_template.add(self.user_template_combo)
        tpl_row = QHBoxLayout()
        self.tpl_apply_btn = QPushButton("应用")
        self.tpl_apply_btn.setProperty("role", "soft")
        self.tpl_apply_btn.clicked.connect(self._apply_user_template)
        self.tpl_save_btn = QPushButton("保存当前")
        self.tpl_save_btn.setProperty("role", "soft")
        self.tpl_save_btn.clicked.connect(self._save_user_template)
        self.tpl_save_as_btn = QPushButton("另存为")
        self.tpl_save_as_btn.setProperty("role", "soft")
        self.tpl_save_as_btn.clicked.connect(self._save_as_user_template)
        tpl_row.addWidget(self.tpl_apply_btn)
        tpl_row.addWidget(self.tpl_save_btn)
        tpl_row.addWidget(self.tpl_save_as_btn)
        g_template.body_layout.addLayout(tpl_row)
        tpl_row2 = QHBoxLayout()
        self.tpl_rename_btn = QPushButton("重命名")
        self.tpl_rename_btn.setProperty("role", "soft")
        self.tpl_rename_btn.clicked.connect(self._rename_user_template)
        self.tpl_delete_btn = QPushButton("删除")
        self.tpl_delete_btn.setProperty("role", "soft")
        self.tpl_delete_btn.clicked.connect(self._delete_user_template)
        tpl_row2.addWidget(self.tpl_rename_btn)
        tpl_row2.addWidget(self.tpl_delete_btn)
        g_template.body_layout.addLayout(tpl_row2)
        form.addWidget(g_template)

        # 外观（紧跟模板）
        g_look = _Group("外观", False)
        self.theme_combo = _NoWheelComboBox()
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.currentTextChanged.connect(self._emit)
        g_look.add(self._label("底栏 / 相框配色"))
        g_look.add(self.theme_combo)
        g_look.add(self._label("水印大小"))
        scale_row = QHBoxLayout()
        self.scale_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
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
        self.opacity_row = QWidget()
        self.opacity_row.setObjectName("barOpacityRow")
        opacity_layout = QHBoxLayout(self.opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(8)
        self.opacity_spin = _NoWheelDoubleSpinBox()
        self.opacity_spin.setObjectName("barOpacitySpin")
        self.opacity_spin.setRange(0.15, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.72)
        self.opacity_spin.valueChanged.connect(self._emit)
        opacity_layout.addWidget(self._label("底栏透明度"))
        opacity_layout.addWidget(self.opacity_spin)
        g_look.add(self.opacity_row)
        form.addWidget(g_look)
        self._refresh_user_templates()
        self._update_style_dependent_ui()

        # 内容
        g_content = _Group("内容", False)
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
        self.show_logo = self._check("显示 Logo", "showLogoBox")
        self.show_logo.setChecked(True)
        self.show_logo.toggled.connect(self._update_logo_label)
        self.show_brand_text = self._check("Logo 旁显示署名", "showBrandTextBox")
        g_content.add(self._label("品牌 / 摄影署名"))
        g_content.add(self.brand_edit)
        g_content.add(self._label("自定义说明"))
        g_content.add(self.caption_edit)
        g_content.add(self._label("Logo"))
        g_content.add(self.logo_label)
        g_content.body_layout.addLayout(logo_row)
        g_content.add(self.show_logo)
        g_content.add(self.show_brand_text)
        form.addWidget(g_content)

        # 元数据
        g_meta = _Group("元数据", False)
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

        # 位置与布局：暂关闭（操作有 bug），固定默认底部位置。

        # 导出
        g_export = _Group("导出", False)
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
        self.format_combo = _NoWheelComboBox()
        self.format_combo.setObjectName("exportFormatCombo")
        self.format_combo.addItem("JPG", "jpg")
        self.format_combo.addItem("PNG", "png")
        self.format_combo.addItem("WEBP", "webp")
        self.format_combo.addItem("TIFF", "tiff")
        self.format_combo.currentIndexChanged.connect(self._on_export_format_changed)
        g_export.add(self._label("导出格式"))
        g_export.add(self.format_combo)

        self.quality_row = QWidget()
        self.quality_row.setObjectName("jpgQualityRow")
        quality_row = QHBoxLayout(self.quality_row)
        quality_row.setContentsMargins(0, 0, 0, 0)
        self.quality_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setObjectName("qualitySlider")
        self.quality_slider.setRange(80, 100)
        self.quality_slider.setValue(95)
        self.quality_slider.valueChanged.connect(self._on_quality)
        self.quality_value = QLabel("95")
        self.quality_value.setObjectName("ValueLabel")
        quality_row.addWidget(self._label("JPG 质量"))
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_value)
        g_export.add(self.quality_row)

        self.png_compress_row = QWidget()
        self.png_compress_row.setObjectName("pngCompressRow")
        png_row = QHBoxLayout(self.png_compress_row)
        png_row.setContentsMargins(0, 0, 0, 0)
        self.png_compress_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self.png_compress_slider.setObjectName("pngCompressSlider")
        self.png_compress_slider.setRange(0, 9)
        self.png_compress_slider.setValue(6)
        self.png_compress_slider.valueChanged.connect(self._on_png_compress)
        self.png_compress_value = QLabel("6")
        self.png_compress_value.setObjectName("ValueLabel")
        png_row.addWidget(self._label("PNG 压缩"))
        png_row.addWidget(self.png_compress_slider, 1)
        png_row.addWidget(self.png_compress_value)
        g_export.add(self.png_compress_row)

        self.webp_quality_row = QWidget()
        self.webp_quality_row.setObjectName("webpQualityRow")
        webp_row = QHBoxLayout(self.webp_quality_row)
        webp_row.setContentsMargins(0, 0, 0, 0)
        self.webp_quality_slider = _NoWheelSlider(Qt.Orientation.Horizontal)
        self.webp_quality_slider.setObjectName("webpQualitySlider")
        self.webp_quality_slider.setRange(1, 100)
        self.webp_quality_slider.setValue(90)
        self.webp_quality_slider.valueChanged.connect(self._on_webp_quality)
        self.webp_quality_value = QLabel("90")
        self.webp_quality_value.setObjectName("ValueLabel")
        webp_row.addWidget(self._label("WEBP 质量"))
        webp_row.addWidget(self.webp_quality_slider, 1)
        webp_row.addWidget(self.webp_quality_value)
        g_export.add(self.webp_quality_row)

        self.keep_exif = self._check("保留 EXIF", "keepExifCheck")
        self.keep_icc = self._check("保留 ICC 色彩配置", "keepIccCheck")
        self.keep_exif.setChecked(True)
        self.keep_icc.setChecked(True)
        g_export.add(self.keep_exif)
        g_export.add(self.keep_icc)

        self.conflict_combo = _NoWheelComboBox()
        self.conflict_combo.setObjectName("conflictCombo")
        self.conflict_combo.addItem("重名时自动编号", "number")
        self.conflict_combo.addItem("重名时覆盖（需确认）", "overwrite")
        self.conflict_combo.currentIndexChanged.connect(self._emit)
        g_export.add(self._label("文件冲突"))
        g_export.add(self.conflict_combo)
        form.addWidget(g_export)
        self._update_export_format_ui()
        form.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._inputs = [
            self.style_combo,
            self.base_style_combo,
            self.theme_combo,
            self.brand_edit,
            self.caption_edit,
            self.show_camera,
            self.show_lens,
            self.show_exif,
            self.show_date,
            self.show_gps,
            self.show_logo,
            self.show_brand_text,
            self.scale_slider,
            self.format_combo,
            self.quality_slider,
            self.png_compress_slider,
            self.webp_quality_slider,
            self.keep_exif,
            self.keep_icc,
            self.opacity_spin,
            self.conflict_combo,
        ]
        self._update_logo_label()
        self._update_style_dependent_ui()
        self._update_export_format_ui()

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _check(self, text: str, object_name: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setObjectName(object_name)
        box.toggled.connect(self._emit)
        return box

    def _on_style_changed(self, *_args: object) -> None:
        self._update_style_dependent_ui()
        self._emit()

    def _update_style_dependent_ui(self, *_args: object) -> None:
        custom = self.style_combo.currentText() == "自定义"
        self.base_style_row.setVisible(custom)
        # 底栏透明度：极简叠加，或自定义且底版为极简。
        eff = effective_style(
            {
                "style": self.style_combo.currentText(),
                "base_style": self.base_style_combo.currentText(),
            }
        )
        self.opacity_row.setVisible(eff == "极简叠加")

    def _emit(self, *_args: object) -> None:
        if not self._loading:
            self.optionsChanged.emit()

    def _selected_template_id(self) -> str:
        return str(self.user_template_combo.currentData() or "")

    def _refresh_user_templates(self, select_id: str | None = None) -> None:
        current = select_id or self._selected_template_id()
        self.user_template_combo.blockSignals(True)
        self.user_template_combo.clear()
        self.user_template_combo.addItem("（未选择）", "")
        for entry in template_store.list_templates(self._templates_path):
            self.user_template_combo.addItem(str(entry["name"]), str(entry["id"]))
        idx = self.user_template_combo.findData(current)
        self.user_template_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.user_template_combo.blockSignals(False)

    def _prompt_template_name(self, title: str, default: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, "模板名称：", text=default)
        if not ok:
            return None
        name = str(text or "").strip()
        if not name:
            QMessageBox.information(self, "提示", "模板名称不能为空。")
            return None
        return name

    def _save_user_template(self) -> None:
        tid = self._selected_template_id()
        if tid:
            entry = template_store.get_template(tid, self._templates_path)
            name = str(entry["name"]) if entry else ""
        else:
            name = self._prompt_template_name("保存当前模板") or ""
            if not name:
                return
        try:
            saved = template_store.save_template(
                name,
                self.state(),
                template_id=tid or None,
                path=self._templates_path,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self._refresh_user_templates(str(saved["id"]))

    def _save_as_user_template(self) -> None:
        name = self._prompt_template_name("另存为模板")
        if not name:
            return
        try:
            saved = template_store.save_template(name, self.state(), path=self._templates_path)
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self._refresh_user_templates(str(saved["id"]))

    def _apply_user_template(self) -> None:
        tid = self._selected_template_id()
        if not tid:
            QMessageBox.information(self, "提示", "请先选择一个用户模板。")
            return
        entry = template_store.get_template(tid, self._templates_path)
        if entry is None:
            QMessageBox.warning(self, "提示", "模板不存在或已被删除。")
            self._refresh_user_templates()
            return
        merged = dict(self.state())
        merged.update(entry["settings"])
        # 保留当前导出目录 / 浏览目录
        merged["output_dir"] = self._output_dir
        self.set_state(merged)
        self._emit()

    def _rename_user_template(self) -> None:
        tid = self._selected_template_id()
        if not tid:
            QMessageBox.information(self, "提示", "请先选择一个用户模板。")
            return
        entry = template_store.get_template(tid, self._templates_path)
        if entry is None:
            self._refresh_user_templates()
            return
        name = self._prompt_template_name("重命名模板", str(entry["name"]))
        if not name:
            return
        try:
            template_store.rename_template(tid, name, self._templates_path)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        self._refresh_user_templates(tid)

    def _delete_user_template(self) -> None:
        tid = self._selected_template_id()
        if not tid:
            QMessageBox.information(self, "提示", "请先选择一个用户模板。")
            return
        entry = template_store.get_template(tid, self._templates_path)
        label = str(entry["name"]) if entry else "该模板"
        answer = QMessageBox.question(self, "删除模板", f"确定删除「{label}」？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        template_store.delete_template(tid, self._templates_path)
        self._refresh_user_templates()

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

    def _on_png_compress(self, value: int) -> None:
        self.png_compress_value.setText(str(int(value)))
        self._emit()

    def _on_webp_quality(self, value: int) -> None:
        self.webp_quality_value.setText(str(int(value)))
        self._emit()

    def _on_export_format_changed(self, *_args: object) -> None:
        self._update_export_format_ui()
        self._emit()

    def _update_export_format_ui(self, *_args: object) -> None:
        fmt = str(self.format_combo.currentData() or "jpg")
        self.quality_row.setVisible(fmt == "jpg")
        self.png_compress_row.setVisible(fmt == "png")
        self.webp_quality_row.setVisible(fmt == "webp")

    def _update_logo_label(self) -> None:
        path = self._logo_path
        missing = False
        has_logo = bool(path)
        self.show_logo.setEnabled(has_logo)
        if not path:
            self.logo_label.setText("未选择 Logo（支持透明 PNG）")
        else:
            name = Path(path).name
            if Path(path).is_file():
                text = name
            else:
                text = f"路径失效：{name}"
                missing = True
            if not self.show_logo.isChecked():
                text = f"{text}（已隐藏）"
            self.logo_label.setText(text)
        self.logo_label.setProperty("missing", missing)
        self.logo_label.style().unpolish(self.logo_label)
        self.logo_label.style().polish(self.logo_label)

    def set_logo_path(self, path: str) -> None:
        self._logo_path = path or ""
        if self._logo_path:
            self.show_logo.blockSignals(True)
            self.show_logo.setChecked(True)
            self.show_logo.blockSignals(False)
        self._update_logo_label()
        self._emit()

    def set_output_dir(self, path: str) -> None:
        self._output_dir = path
        self.output_label.setText(path)
        self.output_label.setToolTip(path)
        self._emit()

    def set_layout_offset(self, ox: float, oy: float) -> None:
        """兼容旧接口；整框偏移已废弃。"""
        return

    def set_field_position(self, key: str, x: float, y: float, *, emit: bool = True) -> None:
        name = str(key or "").strip()
        if name not in FIELD_POSITION_KEYS:
            return
        try:
            nx, ny = snap_field_position(float(x), float(y))
        except (TypeError, ValueError):
            return
        current = self._field_positions.get(name) or {}
        if (
            abs(float(current.get("x", -1)) - nx) < 1e-6
            and abs(float(current.get("y", -1)) - ny) < 1e-6
        ):
            return
        self._field_positions[name] = {"x": nx, "y": ny}
        if emit and self.style_combo.currentText() == "自定义" and not self._loading:
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
            "font_family": self.field_font(key),
            "font_bold": self.field_bold(key),
            "font_opacity": self.field_opacity(key),
        }

    def field_font(self, key: str) -> str:
        return coerce_font_family(self._field_fonts.get(key, DEFAULT_FONT_FAMILY))

    def set_field_font(self, key: str, name: str) -> None:
        if key not in self._field_fonts:
            return
        next_name = coerce_font_family(name)
        if next_name == self._field_fonts.get(key):
            return
        self._field_fonts[key] = next_name
        self._emit()

    def field_bold(self, key: str) -> bool:
        return bool(self._field_bolds.get(key, DEFAULT_FIELD_BOLD.get(key, False)))

    def set_field_bold(self, key: str, bold: bool) -> None:
        if key not in self._field_bolds:
            return
        next_bold = bool(bold)
        if next_bold == self._field_bolds.get(key):
            return
        self._field_bolds[key] = next_bold
        self._emit()

    def field_opacity(self, key: str) -> float:
        return coerce_field_opacity(self._field_opacities.get(key, 1.0), 1.0)

    def set_field_opacity(self, key: str, opacity: float) -> None:
        if key not in self._field_opacities:
            return
        next_opacity = coerce_field_opacity(opacity, 1.0)
        if abs(next_opacity - float(self._field_opacities.get(key, 1.0))) < 1e-6:
            return
        self._field_opacities[key] = next_opacity
        self._emit()

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
        layout = default_layout()
        layout["bar_opacity"] = self.opacity_spin.value()
        # 切走自定义不清空，再切回可恢复。
        layout["field_positions"] = {
            key: {"x": float(pos["x"]), "y": float(pos["y"])}
            for key, pos in self._field_positions.items()
            if isinstance(pos, dict)
        }
        data: dict[str, Any] = {
            "style": self.style_combo.currentText(),
            "base_style": self.base_style_combo.currentText(),
            "theme": self.theme_combo.currentText(),
            "brand": self.brand_edit.text(),
            "caption": self.caption_edit.text(),
            "scale": self.scale_slider.value() / 100,
            "logo_path": self._logo_path,
            "show_logo": self.show_logo.isChecked(),
            "show_camera": self.show_camera.isChecked(),
            "show_lens": self.show_lens.isChecked(),
            "show_exif": self.show_exif.isChecked(),
            "show_date": self.show_date.isChecked(),
            "show_gps": self.show_gps.isChecked(),
            "show_brand_text": self.show_brand_text.isChecked(),
            "quality": self.quality_slider.value(),
            "export_format": self.format_combo.currentData(),
            "png_compress": self.png_compress_slider.value(),
            "webp_quality": self.webp_quality_slider.value(),
            "keep_exif": self.keep_exif.isChecked(),
            "keep_icc": self.keep_icc.isChecked(),
            "output_dir": self._output_dir,
            "layout": layout,
            "conflict_policy": self.conflict_combo.currentData(),
        }
        for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
            data[text_key] = ""
            data[scale_key] = 1.0
            data[f"{key}_font"] = DEFAULT_FONT_FAMILY
            data[f"{key}_bold"] = bool(DEFAULT_FIELD_BOLD.get(key, False))
            data[f"{key}_opacity"] = 1.0
        data["brand_font"] = self.field_font("brand")
        data["caption_font"] = self.field_font("caption")
        data["brand_bold"] = self.field_bold("brand")
        data["caption_bold"] = self.field_bold("caption")
        data["brand_opacity"] = self.field_opacity("brand")
        data["caption_opacity"] = self.field_opacity("caption")
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
            base_index = self.base_style_combo.findText(str(data.get("base_style", "经典底栏")))
            self.base_style_combo.setCurrentIndex(base_index if base_index >= 0 else 0)
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
            self.show_logo.setChecked(bool(data["show_logo"]))
            self.show_brand_text.setChecked(bool(data["show_brand_text"]))
            for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
                self._field_texts[key] = str(data[text_key])
                self._field_scales[key] = float(data[scale_key])
            self.scale_slider.setValue(int(round(float(data["scale"]) * 100)))
            self.scale_value.setText(f"{self.scale_slider.value()}%")
            for font_key in FIELD_FONT_KEYS:
                field = font_key.removesuffix("_font")
                self._field_fonts[field] = coerce_font_family(data.get(font_key, DEFAULT_FONT_FAMILY))
            for bold_key in FIELD_BOLD_KEYS:
                field = bold_key.removesuffix("_bold")
                default_bold = bool(DEFAULT_FIELD_BOLD.get(field, False))
                self._field_bolds[field] = bool(data.get(bold_key, default_bold))
            for opacity_key in FIELD_OPACITY_KEYS:
                field = opacity_key.removesuffix("_opacity")
                self._field_opacities[field] = coerce_field_opacity(
                    data.get(opacity_key, 1.0), 1.0
                )
            self.quality_slider.setValue(int(data["quality"]))
            self.quality_value.setText(str(self.quality_slider.value()))
            fmt = str(data.get("export_format", "jpg"))
            fidx = self.format_combo.findData(fmt)
            self.format_combo.setCurrentIndex(fidx if fidx >= 0 else 0)
            self.png_compress_slider.setValue(int(data.get("png_compress", 6)))
            self.png_compress_value.setText(str(self.png_compress_slider.value()))
            self.webp_quality_slider.setValue(int(data.get("webp_quality", 90)))
            self.webp_quality_value.setText(str(self.webp_quality_slider.value()))
            self.keep_exif.setChecked(bool(data.get("keep_exif", True)))
            self.keep_icc.setChecked(bool(data.get("keep_icc", True)))
            self._logo_path = str(data["logo_path"])
            self._update_logo_label()
            self._output_dir = str(data["output_dir"])
            self.output_label.setText(self._output_dir)
            self.output_label.setToolTip(self._output_dir)
            self.opacity_spin.setValue(float(layout.get("bar_opacity", 0.72)))
            self._field_positions = coerce_field_positions(layout.get("field_positions"))
            policy = str(data.get("conflict_policy", "number"))
            pidx = self.conflict_combo.findData(policy)
            self.conflict_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
            self._update_style_dependent_ui()
            self._update_export_format_ui()
        finally:
            for widget in self._inputs:
                widget.blockSignals(False)
            self._loading = False
