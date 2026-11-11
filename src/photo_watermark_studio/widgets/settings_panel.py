# -*- coding: utf-8 -*-
"""右侧样式编辑面板：Logo / 参数 / 主题 / 自定义 / 导出 五个页签。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from photo_watermark_studio.core.document import WatermarkDocument
from photo_watermark_studio.core.font_presets import DEFAULT_FONT_FAMILY, coerce_font_family
from photo_watermark_studio.core.renderer import compose_exposure_line, parse_exposure_line
from photo_watermark_studio.core.settings_store import (
    BG_SWATCHES,
    BUILTIN_STYLES,
    DEFAULT_FIELD_BOLD,
    FIELD_BOLD_KEYS,
    FIELD_FONT_KEYS,
    FIELD_ITALIC_KEYS,
    FIELD_OPACITY_KEYS,
    FIELD_POSITION_KEYS,
    STYLES,
    THEMES,
    coerce_field_opacity,
    coerce_field_positions,
    coerce_hex_color,
    coerce_settings,
    default_layout,
    effective_style,
    snap_field_position,
)
from photo_watermark_studio.core import template_store
from photo_watermark_studio.widgets.inspector_controls import (
    ColorSwatchRow,
    ControlSection,
    PresetRow,
    SegmentControl,
    ToggleSwitch,
    ValueSlider,
)
from photo_watermark_studio.widgets.save_template_dialog import SaveTemplateDialog


class _NoWheelComboBox(QComboBox):
    """禁止滚轮改选项，避免在属性栏滚动时误触。"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class _SegmentBar(QWidget):
    """圆角分段页签，保留 QTabBar 的少量公开接口。"""

    currentChanged = Signal(int)

    def __init__(self, labels: tuple[str, ...]) -> None:
        super().__init__()
        self.setObjectName("InspectorTabs")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._index = 0
        self._buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("InspectorTab")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, value=index: self.setCurrentIndex(value))
            group.addButton(button)
            self._buttons.append(button)
            layout.addWidget(button, 1)

    def count(self) -> int:
        return len(self._buttons)

    def tabText(self, index: int) -> str:
        return self._buttons[index].text()

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index == self._index:
            return
        self._index = index
        self.currentChanged.emit(index)


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

TAB_NAMES = ("Logo", "参数", "主题", "自定义", "导出")
LOGO_PRESETS = (("", "无"), ("nikon", "Nikon"), ("image", "图片"))
LOGO_LAYOUTS = ("图标 + 文字", "仅图标", "仅文字")
THEME_LABELS = {"白色": "纯白", "黑色": "纯黑", "高斯模糊": "模糊"}
_FRAMED_STYLES = ("卡片相框", "胶片边框")


def _percent(number: int) -> str:
    return f"{number}%"


def _radius_text(number: int) -> str:
    return "默认" if number <= 0 else f"{number} px"


def _shadow_text(number: int) -> str:
    if number <= 0:
        return "无"
    if number <= 35:
        return "轻柔"
    if number <= 70:
        return "适中"
    return "浓郁"


class SettingsPanel(QFrame):
    optionsChanged = Signal()
    chooseLogoRequested = Signal()
    clearLogoRequested = Signal()
    chooseOutputRequested = Signal()
    resetWatermarkRequested = Signal()
    exportRequested = Signal()
    templatesChanged = Signal()
    photoFieldTextEdited = Signal(str, str)
    resetPhotoExifRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Panel")
        self.setMinimumWidth(300)
        self._loading = False
        self._syncing_pads = False
        self._logo_path = ""
        self._logo_mark = ""
        self._output_dir = ""
        self._field_positions: dict[str, dict[str, float]] = {}
        self._templates_path = template_store.default_templates_path()
        self._placeholders: dict[str, str] = {key: "" for key, *_rest in _META_FIELDS}
        self._field_texts: dict[str, str] = {"brand": "", "caption": "", **self._placeholders}
        self._field_scales: dict[str, float] = {key: 1.0 for key in _FIELD_SCALE_KEYS}
        self._field_fonts: dict[str, str] = {
            key.removesuffix("_font"): DEFAULT_FONT_FAMILY for key in FIELD_FONT_KEYS
        }
        self._field_bolds: dict[str, bool] = {
            key: bool(DEFAULT_FIELD_BOLD.get(key, False)) for key in DEFAULT_FIELD_BOLD
        }
        self._field_italics: dict[str, bool] = {key.removesuffix("_italic"): False for key in FIELD_ITALIC_KEYS}
        self._field_opacities: dict[str, float] = {
            key.removesuffix("_opacity"): 1.0 for key in FIELD_OPACITY_KEYS
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        tabs_wrap = QWidget()
        tabs_layout = QVBoxLayout(tabs_wrap)
        tabs_layout.setContentsMargins(16, 0, 16, 10)
        tabs_layout.setSpacing(0)
        self.tabs = _SegmentBar(TAB_NAMES)
        tabs_layout.addWidget(self.tabs)
        root.addWidget(tabs_wrap)

        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("SettingsBody")
        form = QVBoxLayout(body)
        form.setContentsMargins(18, 4, 18, 12)
        form.setSpacing(0)

        self._pages: dict[str, QWidget] = {
            "Logo": self._build_logo_page(),
            "参数": self._build_params_page(),
            "主题": self._build_theme_page(),
            "自定义": self._build_custom_page(),
            "导出": self._build_export_page(),
        }
        for page in self._pages.values():
            form.addWidget(page)
        form.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_footer())

        self.tabs.currentChanged.connect(self._set_inspector_tab)
        self._set_inspector_tab(0)

        self._inputs: list[QWidget] = [
            self.style_combo,
            self.base_style_combo,
            self.theme_combo,
            self.theme_segment,
            self.bg_swatches,
            self.brand_edit,
            self.caption_edit,
            self.show_camera,
            self.show_lens,
            self.show_exif,
            self.show_date,
            self.show_gps,
            self.show_logo,
            self.show_brand_text,
            self.show_divider,
            self.logo_layout_segment,
            self.logo_scale_slider,
            self.logo_opacity_slider,
            self.scale_slider,
            self.bar_height_slider,
            self.pad_top_slider,
            self.pad_right_slider,
            self.pad_bottom_slider,
            self.pad_left_slider,
            self.corner_radius_slider,
            self.shadow_strength_slider,
            self.bar_opacity_slider,
            self.format_combo,
            self.quality_slider,
            self.png_compress_slider,
            self.webp_quality_slider,
            self.keep_exif,
            self.keep_icc,
            self.conflict_combo,
        ]
        self._refresh_user_templates()
        self._update_logo_ui()
        self._update_style_dependent_ui()
        self._update_export_format_ui()
        self.set_photo_exif_overrides(None, has_photo=False)

    # ------------------------------------------------------------------ 构建
    def _build_header(self) -> QWidget:
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 12)
        header_layout.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title = QLabel("样式编辑")
        title.setObjectName("PanelTitle")
        hint = QLabel("调整水印的每一个细节")
        hint.setObjectName("PanelHint")
        hint.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(hint)
        self.header_reset_button = QPushButton("↺")
        self.header_reset_button.setObjectName("InspectorReset")
        self.header_reset_button.setFixedSize(34, 34)
        self.header_reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_reset_button.setToolTip("重置水印设置")
        self.header_reset_button.clicked.connect(self.resetWatermarkRequested)
        header_layout.addLayout(titles, 1)
        header_layout.addWidget(self.header_reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("InspectorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return page, layout

    def _build_logo_page(self) -> QWidget:
        page, layout = self._page()
        style_section = ControlSection("Logo 样式", "选择你的标识", first=True)
        self.logo_presets = PresetRow(LOGO_PRESETS)
        self.logo_presets.setObjectName("logoPresetRow")
        self.logo_presets.triggered.connect(self._on_logo_preset)
        style_section.add(self.logo_presets)
        self.logo_scale_slider = ValueSlider(
            "Logo 大小", 50, 190, 100, object_name="logoScaleSlider", formatter=_percent
        )
        self.logo_scale_slider.valueChanged.connect(self._emit)
        self.logo_opacity_slider = ValueSlider(
            "Logo 透明度", 20, 100, 100, object_name="logoOpacitySlider", formatter=_percent
        )
        self.logo_opacity_slider.valueChanged.connect(self._emit)
        style_section.add(self.logo_scale_slider)
        style_section.add(self.logo_opacity_slider)
        head = QLabel("自定义 Logo 图片")
        head.setObjectName("FieldHead")
        style_section.add(head)
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        self.logo_button = QPushButton("＋ 上传 PNG / SVG")
        self.logo_button.setObjectName("chooseLogoButton")
        self.logo_button.setProperty("role", "soft")
        self.logo_button.clicked.connect(self.chooseLogoRequested)
        self.clear_logo_button = QPushButton("移除")
        self.clear_logo_button.setObjectName("clearLogoButton")
        self.clear_logo_button.setProperty("role", "soft")
        self.clear_logo_button.setFixedWidth(64)
        self.clear_logo_button.clicked.connect(self.clearLogoRequested)
        logo_row.addWidget(self.logo_button, 1)
        logo_row.addWidget(self.clear_logo_button)
        style_section.add(logo_row)
        self.logo_label = QLabel("未选择 Logo（支持透明 PNG）")
        self.logo_label.setObjectName("PathLabel")
        self.logo_label.setWordWrap(True)
        style_section.add(self.logo_label)
        layout.addWidget(style_section)

        layout_section = ControlSection("Logo 布局")
        self.logo_layout_segment = SegmentControl(LOGO_LAYOUTS)
        self.logo_layout_segment.setObjectName("logoLayoutSegment")
        self.logo_layout_segment.currentChanged.connect(self._on_logo_layout)
        layout_section.add(self.logo_layout_segment)
        # 布局分段写入这两个开关；开关本身不放进界面。
        self.show_logo = ToggleSwitch("显示 Logo", page)
        self.show_logo.setObjectName("showLogoBox")
        self.show_logo.setChecked(True)
        self.show_logo.setVisible(False)
        self.show_brand_text = ToggleSwitch("Logo 旁显示署名", page)
        self.show_brand_text.setObjectName("showBrandTextBox")
        self.show_brand_text.setVisible(False)
        self.show_divider = self._switch("显示分隔线", "showDividerSwitch")
        layout_section.add(self.show_divider)
        layout.addWidget(layout_section)
        return page

    def _build_params_page(self) -> QWidget:
        page, layout = self._page()
        device = ControlSection("拍摄设备", "按当前照片保存", first=True)
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.addWidget(self._head("相机品牌 / 型号"))
        head_row.addStretch(1)
        self.reset_photo_exif_button = QPushButton("恢复 EXIF")
        self.reset_photo_exif_button.setObjectName("resetPhotoExifButton")
        self.reset_photo_exif_button.setProperty("role", "soft")
        self.reset_photo_exif_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_photo_exif_button.setFixedHeight(22)
        self.reset_photo_exif_button.setToolTip("清除当前照片的手动文字覆盖，恢复真实 EXIF")
        self.reset_photo_exif_button.clicked.connect(self.resetPhotoExifRequested)
        head_row.addWidget(self.reset_photo_exif_button)
        device.add(head_row)
        self.camera_edit = QLineEdit()
        self.camera_edit.setObjectName("cameraEdit")
        self.camera_edit.setPlaceholderText("自动读取 EXIF 相机型号")
        self.camera_edit.textEdited.connect(
            lambda text: self._on_photo_field_edited("camera", text)
        )
        device.add(self.camera_edit)
        device.add(self._head("镜头"))
        self.lens_edit = QLineEdit()
        self.lens_edit.setObjectName("lensEdit")
        self.lens_edit.setPlaceholderText("自动读取 EXIF 镜头型号")
        self.lens_edit.textEdited.connect(
            lambda text: self._on_photo_field_edited("lens", text)
        )
        device.add(self.lens_edit)
        layout.addWidget(device)

        exposure = ControlSection("曝光参数", "焦距 · 光圈 · 快门 · ISO")
        exp_grid = QGridLayout()
        exp_grid.setContentsMargins(0, 0, 0, 0)
        exp_grid.setHorizontalSpacing(8)
        exp_grid.setVerticalSpacing(6)
        self.focal_edit = QLineEdit()
        self.focal_edit.setObjectName("focalEdit")
        self.focal_edit.setPlaceholderText("例如 24MM")
        self.aperture_edit = QLineEdit()
        self.aperture_edit.setObjectName("apertureEdit")
        self.aperture_edit.setPlaceholderText("例如 F/2.8")
        self.shutter_edit = QLineEdit()
        self.shutter_edit.setObjectName("shutterEdit")
        self.shutter_edit.setPlaceholderText("例如 1/250S")
        self.iso_edit = QLineEdit()
        self.iso_edit.setObjectName("isoEdit")
        self.iso_edit.setPlaceholderText("例如 100")
        for idx, (caption_text, edit) in enumerate(
            (
                ("焦距", self.focal_edit),
                ("光圈", self.aperture_edit),
                ("快门", self.shutter_edit),
                ("ISO", self.iso_edit),
            )
        ):
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(4)
            cell.addWidget(self._head(caption_text))
            cell.addWidget(edit)
            edit.textEdited.connect(self._on_exposure_grid_edited)
            exp_grid.addLayout(cell, idx // 2, idx % 2)
        exposure.add(exp_grid)
        layout.addWidget(exposure)

        author = ControlSection("作者信息")
        self.brand_edit = QLineEdit()
        self.brand_edit.setObjectName("brandEdit")
        self.brand_edit.setPlaceholderText("留空则不显示")
        self.brand_edit.textChanged.connect(self._on_brand_changed)
        self.caption_edit = QLineEdit()
        self.caption_edit.setObjectName("captionEdit")
        self.caption_edit.setPlaceholderText("例如 城市 · 天气")
        self.caption_edit.textChanged.connect(self._on_caption_changed)
        author.add(self._head("作者 / 署名"))
        author.add(self.brand_edit)
        author.add(self._head("自定义说明"))
        author.add(self.caption_edit)
        layout.addWidget(author)

        meta = ControlSection("显示项", "自动读取 EXIF")
        self.show_camera = self._switch("相机型号", "showCameraBox")
        self.show_lens = self._switch("镜头型号", "showLensBox")
        self.show_exif = self._switch("曝光参数", "showExifBox")
        self.show_date = self._switch("拍摄时间", "showDateBox")
        self.show_gps = self._switch("GPS 坐标", "showGpsBox")
        for switch in (self.show_camera, self.show_lens, self.show_exif, self.show_date, self.show_gps):
            meta.add(switch)
        self._missing_hint = QLabel("")
        self._missing_hint.setObjectName("Notice")
        self._missing_hint.setWordWrap(True)
        meta.add(self._missing_hint)
        tip = QLabel("缺失字段不会伪造。点击预览中的水印文字可改文案和字号，按张保存，可撤销。")
        tip.setObjectName("Notice")
        tip.setWordWrap(True)
        meta.add(tip)
        layout.addWidget(meta)
        return page

    def _build_theme_page(self) -> QWidget:
        page, layout = self._page()
        material = ControlSection("背景材质", first=True)
        self.theme_segment = SegmentControl(tuple(THEME_LABELS[name] for name in THEMES))
        self.theme_segment.setObjectName("themeSegment")
        self.theme_segment.currentChanged.connect(self._on_theme_segment)
        material.add(self.theme_segment)
        self.bg_swatches = ColorSwatchRow(BG_SWATCHES)
        self.bg_swatches.colorSelected.connect(self._on_bg_swatch_selected)
        material.add(self.bg_swatches)
        self.theme_combo = _NoWheelComboBox()
        self.theme_combo.setObjectName("themeCombo")
        self.theme_combo.addItems(list(THEMES))
        self.theme_combo.setVisible(False)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo)
        material.add(self.theme_combo)
        layout.addWidget(material)

        self.bar_metrics = ControlSection("边框宽度", "四边独立控制")
        self.bar_metrics.setObjectName("barMetrics")
        self.pad_top_slider = self._pad_slider("上边距", "padTopSlider")
        self.pad_right_slider = self._pad_slider("右边距", "padRightSlider")
        self.pad_bottom_slider = self._pad_slider("下边距", "padBottomSlider")
        self.pad_left_slider = self._pad_slider("左边距", "padLeftSlider")
        for slider in self._pad_sliders():
            self.bar_metrics.add(slider)
        self.lock_pads = ToggleSwitch("锁定四边比例")
        self.lock_pads.setObjectName("lockPadsSwitch")
        self.lock_pads.toggled.connect(self._on_lock_pads)
        self.bar_metrics.add(self.lock_pads)
        layout.addWidget(self.bar_metrics)

        detail = ControlSection("细节")
        self.corner_radius_slider = ValueSlider(
            "照片圆角", 0, 48, 0, object_name="cornerRadiusSlider", formatter=_radius_text
        )
        self.corner_radius_slider.valueChanged.connect(self._emit)
        self.shadow_strength_slider = ValueSlider(
            "阴影强度", 0, 100, 25, object_name="shadowStrengthSlider", formatter=_shadow_text
        )
        self.shadow_strength_slider.valueChanged.connect(self._emit)
        self.scale_slider = ValueSlider("水印大小", 65, 160, 100, object_name="scaleSlider")
        self.scale_slider.valueChanged.connect(self._emit)
        self.bar_height_slider = ValueSlider("底栏高度", 50, 200, 100, object_name="barHeightSlider")
        self.bar_height_slider.valueChanged.connect(self._emit)
        self.bar_opacity_slider = ValueSlider("底栏透明度", 15, 100, 72, object_name="barOpacitySlider")
        self.bar_opacity_slider.valueChanged.connect(self._emit)
        self.opacity_row = self.bar_opacity_slider
        for widget in (
            self.corner_radius_slider,
            self.shadow_strength_slider,
            self.scale_slider,
            self.bar_height_slider,
            self.bar_opacity_slider,
        ):
            detail.add(widget)
        layout.addWidget(detail)
        return page

    def _build_custom_page(self) -> QWidget:
        page, layout = self._page()
        tpl = ControlSection("模板与底版", first=True)
        self.style_combo = _NoWheelComboBox()
        self.style_combo.setObjectName("styleCombo")
        self.style_combo.addItems(list(STYLES))
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        tpl.add(self._head("水印模板"))
        tpl.add(self.style_combo)
        self.base_style_row = QWidget()
        base_col = QVBoxLayout(self.base_style_row)
        base_col.setContentsMargins(0, 0, 0, 0)
        base_col.setSpacing(6)
        self.base_style_combo = _NoWheelComboBox()
        self.base_style_combo.setObjectName("baseStyleCombo")
        self.base_style_combo.addItems(list(BUILTIN_STYLES))
        self.base_style_combo.currentTextChanged.connect(self._update_style_dependent_ui)
        self.base_style_combo.currentTextChanged.connect(self._emit)
        base_col.addWidget(self._head("自定义底版"))
        base_col.addWidget(self.base_style_combo)
        tpl.add(self.base_style_row)
        layout.addWidget(tpl)

        mine = ControlSection("我的模板", "保存在本机")
        self.user_template_combo = _NoWheelComboBox()
        self.user_template_combo.setObjectName("userTemplateCombo")
        mine.add(self.user_template_combo)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.tpl_apply_btn = self._soft_button("应用", self._apply_user_template)
        self.tpl_save_btn = self._soft_button("保存当前", self._save_user_template)
        self.tpl_save_as_btn = self._soft_button("另存为", self._save_as_user_template)
        self.tpl_rename_btn = self._soft_button("重命名", self._rename_user_template)
        self.tpl_delete_btn = self._soft_button("删除", self._delete_user_template)
        grid.addWidget(self.tpl_apply_btn, 0, 0)
        grid.addWidget(self.tpl_save_btn, 0, 1)
        grid.addWidget(self.tpl_save_as_btn, 0, 2)
        grid.addWidget(self.tpl_rename_btn, 1, 0)
        grid.addWidget(self.tpl_delete_btn, 1, 1)
        mine.add(grid)
        layout.addWidget(mine)

        drag = QLabel(
            "选择「自定义」模板后，可以在画布上直接拖动 Logo、署名和每一项参数，"
            "位置会吸附到网格。调整完成后，可保存为个人模板，供后续单张或批量照片使用。"
        )
        drag.setObjectName("Notice")
        drag.setWordWrap(True)
        layout.addWidget(drag)
        return page

    def _build_export_page(self) -> QWidget:
        page, layout = self._page()
        target = ControlSection("导出位置", first=True)
        self.output_label = QLabel("")
        self.output_label.setObjectName("PathLabel")
        self.output_label.setWordWrap(True)
        self.output_button = QPushButton("选择导出目录")
        self.output_button.setObjectName("chooseOutputButton")
        self.output_button.setProperty("role", "soft")
        self.output_button.clicked.connect(self.chooseOutputRequested)
        target.add(self.output_label)
        target.add(self.output_button)
        self.conflict_combo = _NoWheelComboBox()
        self.conflict_combo.setObjectName("conflictCombo")
        self.conflict_combo.addItem("重名时自动编号", "number")
        self.conflict_combo.addItem("重名时覆盖（需确认）", "overwrite")
        self.conflict_combo.currentIndexChanged.connect(self._emit)
        target.add(self._head("文件冲突"))
        target.add(self.conflict_combo)
        layout.addWidget(target)

        fmt = ControlSection("格式与质量")
        self.format_combo = _NoWheelComboBox()
        self.format_combo.setObjectName("exportFormatCombo")
        for label, value in (("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("TIFF", "tiff")):
            self.format_combo.addItem(label, value)
        self.format_combo.currentIndexChanged.connect(self._on_export_format_changed)
        fmt.add(self._head("导出格式"))
        fmt.add(self.format_combo)
        self.quality_slider = ValueSlider("JPG 质量", 80, 100, 95, object_name="qualitySlider", formatter=str)
        self.quality_slider.valueChanged.connect(self._emit)
        self.quality_row = self.quality_slider
        self.png_compress_slider = ValueSlider(
            "PNG 压缩", 0, 9, 6, object_name="pngCompressSlider", formatter=str
        )
        self.png_compress_slider.valueChanged.connect(self._emit)
        self.png_compress_row = self.png_compress_slider
        self.webp_quality_slider = ValueSlider(
            "WEBP 质量", 1, 100, 90, object_name="webpQualitySlider", formatter=str
        )
        self.webp_quality_slider.valueChanged.connect(self._emit)
        self.webp_quality_row = self.webp_quality_slider
        fmt.add(self.quality_slider)
        fmt.add(self.png_compress_slider)
        fmt.add(self.webp_quality_slider)
        layout.addWidget(fmt)

        meta = ControlSection("元数据")
        self.keep_exif = self._switch("保留 EXIF", "keepExifCheck")
        self.keep_icc = self._switch("保留 ICC 色彩配置", "keepIccCheck")
        self.keep_exif.setChecked(True)
        self.keep_icc.setChecked(True)
        meta.add(self.keep_exif)
        meta.add(self.keep_icc)
        layout.addWidget(meta)
        return page

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("InspectorFooter")
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(8)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.reset_watermark_button = QPushButton("重置")
        self.reset_watermark_button.setObjectName("resetWatermarkButton")
        self.reset_watermark_button.setProperty("role", "soft")
        self.reset_watermark_button.clicked.connect(self.resetWatermarkRequested)
        self.footer_export_button = QPushButton("导出照片")
        self.footer_export_button.setObjectName("footerExportButton")
        self.footer_export_button.setProperty("role", "primary")
        self.footer_export_button.clicked.connect(self.exportRequested)
        for button in (self.reset_watermark_button, self.footer_export_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        actions.addWidget(self.reset_watermark_button, 1)
        actions.addWidget(self.footer_export_button, 2)
        layout.addLayout(actions)
        notice = QLabel("提示：编辑效果实时预览。导出时将按原图分辨率渲染，不会覆盖原始照片。")
        notice.setObjectName("Notice")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        return footer

    def _head(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldHead")
        return label

    def _switch(self, text: str, object_name: str) -> ToggleSwitch:
        switch = ToggleSwitch(text)
        switch.setObjectName(object_name)
        switch.toggled.connect(self._emit)
        return switch

    def _soft_button(self, text: str, slot: Any) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", "soft")
        button.clicked.connect(slot)
        return button

    def _pad_slider(self, title: str, object_name: str) -> ValueSlider:
        slider = ValueSlider(title, 40, 220, 100, object_name=object_name)
        slider.valueChanged.connect(lambda value, source=slider: self._on_pad_changed(source, value))
        return slider

    def _pad_sliders(self) -> tuple[ValueSlider, ...]:
        return (self.pad_top_slider, self.pad_right_slider, self.pad_bottom_slider, self.pad_left_slider)

    # ------------------------------------------------------------------ 交互
    def _on_pad_changed(self, source: ValueSlider, value: int) -> None:
        if self.lock_pads.isChecked() and not self._syncing_pads and not self._loading:
            self._syncing_pads = True
            try:
                for slider in self._pad_sliders():
                    if slider is not source:
                        slider.blockSignals(True)
                        slider.setValue(value)
                        slider.blockSignals(False)
            finally:
                self._syncing_pads = False
        self._emit()

    def _on_lock_pads(self, checked: bool) -> None:
        if checked:
            self._on_pad_changed(self.pad_top_slider, self.pad_top_slider.value())

    def _on_theme_segment(self, index: int) -> None:
        self.bg_swatches.blockSignals(True)
        self.bg_swatches.set_color("")
        self.bg_swatches.blockSignals(False)
        if 0 <= index < self.theme_combo.count() and self.theme_combo.currentIndex() != index:
            self.theme_combo.setCurrentIndex(index)
        else:
            self._emit()

    def _on_theme_combo(self, index: int) -> None:
        self.theme_segment.blockSignals(True)
        self.theme_segment.setCurrentIndex(index)
        self.theme_segment.blockSignals(False)
        if self.theme_combo.currentText() == "高斯模糊" and self.bg_swatches.color():
            self.bg_swatches.blockSignals(True)
            self.bg_swatches.set_color("")
            self.bg_swatches.blockSignals(False)
        self._emit()

    def _on_bg_swatch_selected(self, hex_color: str) -> None:
        clean = coerce_hex_color(hex_color)
        if clean and self.theme_combo.currentText() == "高斯模糊":
            self.theme_combo.blockSignals(True)
            self.theme_segment.blockSignals(True)
            self.theme_combo.setCurrentIndex(0)
            self.theme_segment.setCurrentIndex(0)
            self.theme_combo.blockSignals(False)
            self.theme_segment.blockSignals(False)
        self._emit()

    def _on_photo_field_edited(self, field: str, text: str) -> None:
        if self._loading:
            return
        self.photoFieldTextEdited.emit(field, str(text or ""))

    def _on_exposure_grid_edited(self, *_args: object) -> None:
        if self._loading:
            return
        line = compose_exposure_line(
            focal=self.focal_edit.text(),
            aperture=self.aperture_edit.text(),
            shutter=self.shutter_edit.text(),
            iso=self.iso_edit.text(),
        )
        self.photoFieldTextEdited.emit("exif", line)

    def set_photo_exif_overrides(
        self, values: dict[str, str] | None, *, has_photo: bool = True
    ) -> None:
        data = values or {}
        cam = str(data.get("camera", "") or "")
        lens = str(data.get("lens", "") or "")
        exif = str(data.get("exif", "") or "")
        parsed = parse_exposure_line(exif)
        edits = (
            (self.camera_edit, cam),
            (self.lens_edit, lens),
            (self.focal_edit, parsed["focal"]),
            (self.aperture_edit, parsed["aperture"]),
            (self.shutter_edit, parsed["shutter"]),
            (self.iso_edit, parsed["iso"]),
        )
        for edit, val in edits:
            edit.blockSignals(True)
            if edit.text() != val:
                edit.setText(val)
            edit.setEnabled(bool(has_photo))
            edit.blockSignals(False)
        self.reset_photo_exif_button.setEnabled(bool(has_photo))

    def _on_logo_preset(self, value: object) -> None:
        if value == "image":
            if not self._logo_path:
                self.chooseLogoRequested.emit()
            self._update_logo_ui()
            return
        self._logo_mark = str(value or "")
        if self._logo_path:
            # 选固定徽记时放弃已上传图片，否则图片优先会让选择看起来无效。
            self._logo_path = ""
        if self._logo_mark and not self.show_logo.isChecked():
            self.show_logo.setChecked(True)
        self._update_logo_ui()
        self._emit()

    def _on_logo_layout(self, index: int) -> None:
        self.show_logo.blockSignals(True)
        self.show_brand_text.blockSignals(True)
        self.show_logo.setChecked(index in (0, 1))
        self.show_brand_text.setChecked(index == 0)
        self.show_logo.blockSignals(False)
        self.show_brand_text.blockSignals(False)
        self._update_logo_ui()
        self._emit()

    def _sync_logo_layout(self) -> None:
        if not self.show_logo.isChecked():
            index = 2
        elif self.show_brand_text.isChecked():
            index = 0
        else:
            index = 1
        self.logo_layout_segment.blockSignals(True)
        self.logo_layout_segment.setCurrentIndex(index)
        self.logo_layout_segment.blockSignals(False)

    def _on_style_changed(self, *_args: object) -> None:
        self._update_style_dependent_ui()
        self._emit()

    def _update_style_dependent_ui(self, *_args: object) -> None:
        custom = self.style_combo.currentText() == "自定义"
        self.base_style_row.setVisible(custom)
        eff = effective_style(
            {
                "style": self.style_combo.currentText(),
                "base_style": self.base_style_combo.currentText(),
            }
        )
        self.bar_opacity_slider.setVisible(eff == "极简叠加")
        self.corner_radius_slider.setVisible(eff == "卡片相框")
        self.shadow_strength_slider.setVisible(eff == "卡片相框")
        if custom:
            show_metrics = eff in _FRAMED_STYLES
        else:
            show_metrics = eff in ("经典底栏", "极简叠加", *_FRAMED_STYLES)
        self.bar_metrics.setVisible(show_metrics)
        self.bar_height_slider.setVisible(show_metrics)
        framed = eff in _FRAMED_STYLES
        self.bar_metrics.title_label.setText("边框宽度" if framed else "底栏边距")
        self.bar_height_slider.title_label.setText("页脚高度" if framed else "底栏高度")

    def _emit(self, *_args: object) -> None:
        if not self._loading:
            self.optionsChanged.emit()

    # ------------------------------------------------------------------ 模板
    def set_templates_path(self, path: Path | str) -> None:
        self._templates_path = Path(path)
        self._refresh_user_templates()

    def templates_path(self) -> Path:
        return self._templates_path

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

    def _templates_updated(self, select_id: str | None = None) -> None:
        self._refresh_user_templates(select_id)
        self.templatesChanged.emit()

    def _prompt_template_name(
        self,
        title: str,
        default: str = "",
        *,
        description: str = "为当前样式命名，之后可以在模板库中快速调用。",
        confirm_text: str = "保存模板",
    ) -> str | None:
        dialog = SaveTemplateDialog(
            self, title=title, description=description, name=default, confirm_text=confirm_text
        )
        if dialog.exec() != SaveTemplateDialog.DialogCode.Accepted:
            return None
        return dialog.template_name() or None

    def _save_user_template(self) -> None:
        tid = self._selected_template_id()
        if tid:
            entry = template_store.get_template(tid, self._templates_path)
            name = str(entry["name"]) if entry else ""
        else:
            name = self._prompt_template_name("保存为我的模板") or ""
            if not name:
                return
        self._store_template(name, tid or None)

    def _save_as_user_template(self) -> None:
        name = self._prompt_template_name("保存为我的模板", "我的模板")
        if name:
            self._store_template(name, None)

    def _store_template(self, name: str, template_id: str | None) -> None:
        try:
            saved = template_store.save_template(
                name, self.state(), template_id=template_id, path=self._templates_path
            )
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self._templates_updated(str(saved["id"]))

    def save_as_template(self) -> None:
        """供顶栏“保存为模板”按钮调用。"""
        self._save_as_user_template()

    def apply_template(self, template_id: str) -> bool:
        entry = template_store.get_template(template_id, self._templates_path)
        if entry is None:
            self._refresh_user_templates()
            return False
        merged = dict(self.state())
        merged.update(entry["settings"])
        merged["output_dir"] = self._output_dir
        self.set_state(merged)
        self._refresh_user_templates(str(entry["id"]))
        self._emit()
        return True

    def _apply_user_template(self) -> None:
        tid = self._selected_template_id()
        if not tid:
            QMessageBox.information(self, "提示", "请先选择一个用户模板。")
            return
        if not self.apply_template(tid):
            QMessageBox.warning(self, "提示", "模板不存在或已被删除。")

    def _rename_user_template(self) -> None:
        tid = self._selected_template_id()
        if not tid:
            QMessageBox.information(self, "提示", "请先选择一个用户模板。")
            return
        entry = template_store.get_template(tid, self._templates_path)
        if entry is None:
            self._refresh_user_templates()
            return
        name = self._prompt_template_name(
            "重命名模板", str(entry["name"]), description="输入新的模板名称。", confirm_text="重命名"
        )
        if not name:
            return
        try:
            template_store.rename_template(tid, name, self._templates_path)
        except (ValueError, KeyError) as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        self._templates_updated(tid)

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
        self._templates_updated()

    # ------------------------------------------------------------------ 页签
    def show_tab(self, name: str) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                return

    def current_tab(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def page(self, name: str) -> QWidget | None:
        return self._pages.get(name)

    def _set_inspector_tab(self, index: int) -> None:
        name = self.tabs.tabText(index)
        for key, page in self._pages.items():
            page.setVisible(key == name)

    # ------------------------------------------------------------------ 其它
    def _on_brand_changed(self, *_args: object) -> None:
        self._field_texts["brand"] = self.brand_edit.text()
        self._emit()

    def _on_caption_changed(self, *_args: object) -> None:
        self._field_texts["caption"] = self.caption_edit.text()
        self._emit()

    def _on_export_format_changed(self, *_args: object) -> None:
        self._update_export_format_ui()
        self._emit()

    def _update_export_format_ui(self, *_args: object) -> None:
        fmt = str(self.format_combo.currentData() or "jpg")
        self.quality_row.setVisible(fmt == "jpg")
        self.png_compress_row.setVisible(fmt == "png")
        self.webp_quality_row.setVisible(fmt == "webp")

    def _update_logo_ui(self) -> None:
        path = self._logo_path
        missing = False
        if not path:
            self.logo_label.setText("未选择图片。可使用上方 Nikon 徽记，或上传透明 PNG。")
            self.logo_presets.setCurrentData(self._logo_mark)
        else:
            name = Path(path).name
            text = name if Path(path).is_file() else f"路径失效：{name}"
            missing = not Path(path).is_file()
            if not self.show_logo.isChecked():
                text = f"{text}（布局为仅文字，已隐藏）"
            self.logo_label.setText(text)
            self.logo_presets.setCurrentData("image")
        self.clear_logo_button.setEnabled(bool(path))
        self.logo_label.setProperty("missing", missing)
        self.logo_label.style().unpolish(self.logo_label)
        self.logo_label.style().polish(self.logo_label)
        self._sync_logo_layout()

    def _update_logo_label(self) -> None:
        self._update_logo_ui()

    def set_logo_path(self, path: str) -> None:
        self._logo_path = path or ""
        if self._logo_path and not self.show_logo.isChecked():
            self.show_logo.blockSignals(True)
            self.show_logo.setChecked(True)
            self.show_logo.blockSignals(False)
        self._update_logo_ui()
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
        self._placeholders = {key: str(data.get(key, "") or "") for key, *_rest in _META_FIELDS}
        self.camera_edit.setPlaceholderText(self._placeholders["camera"] or "自动读取 EXIF 相机型号")
        self.lens_edit.setPlaceholderText(self._placeholders["lens"] or "自动读取 EXIF 镜头型号")
        parsed = parse_exposure_line(self._placeholders["exif"])
        self.focal_edit.setPlaceholderText(parsed["focal"] or "例如 24MM")
        self.aperture_edit.setPlaceholderText(parsed["aperture"] or "例如 F/2.8")
        self.shutter_edit.setPlaceholderText(parsed["shutter"] or "例如 1/250S")
        self.iso_edit.setPlaceholderText(parsed["iso"] or "例如 100")
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
            "font_italic": self.field_italic(key),
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

    def field_italic(self, key: str) -> bool:
        return bool(self._field_italics.get(key, False))

    def set_field_italic(self, key: str, italic: bool) -> None:
        if key not in self._field_italics:
            return
        next_italic = bool(italic)
        if next_italic == self._field_italics.get(key):
            return
        self._field_italics[key] = next_italic
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

    # ------------------------------------------------------------------ 状态
    def state(self) -> dict[str, Any]:
        layout = default_layout()
        layout["bar_opacity"] = self.bar_opacity_slider.value() / 100
        layout["bar_height"] = self.bar_height_slider.value() / 100
        left = self.pad_left_slider.value() / 100
        right = self.pad_right_slider.value() / 100
        layout["pad_left"] = left
        layout["pad_right"] = right
        layout["side_pad"] = round((left + right) / 2, 4)
        layout["pad_top"] = self.pad_top_slider.value() / 100
        layout["pad_bottom"] = self.pad_bottom_slider.value() / 100
        layout["corner_radius"] = self.corner_radius_slider.value()
        layout["shadow_strength"] = self.shadow_strength_slider.value()
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
            "bg_color": self.bg_swatches.color(),
            "brand": self.brand_edit.text(),
            "caption": self.caption_edit.text(),
            "scale": self.scale_slider.value() / 100,
            "logo_path": self._logo_path,
            "logo_mark": self._logo_mark,
            "logo_scale": self.logo_scale_slider.value() / 100,
            "logo_opacity": self.logo_opacity_slider.value() / 100,
            "show_logo": self.show_logo.isChecked(),
            "show_divider": self.show_divider.isChecked(),
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
            data[f"{key}_italic"] = False
            data[f"{key}_opacity"] = 1.0
        data["brand_font"] = self.field_font("brand")
        data["caption_font"] = self.field_font("caption")
        data["brand_bold"] = self.field_bold("brand")
        data["caption_bold"] = self.field_bold("caption")
        data["brand_italic"] = self.field_italic("brand")
        data["caption_italic"] = self.field_italic("caption")
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
            theme_index = theme_index if theme_index >= 0 else 0
            self.theme_combo.setCurrentIndex(theme_index)
            self.theme_segment.setCurrentIndex(theme_index)
            self.bg_swatches.set_color(str(data.get("bg_color", "") or ""))
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
            self.show_divider.setChecked(bool(data.get("show_divider", False)))
            self._logo_mark = str(data.get("logo_mark", "") or "")
            self.logo_scale_slider.setValue(int(round(float(data.get("logo_scale", 1.0)) * 100)))
            self.logo_opacity_slider.setValue(int(round(float(data.get("logo_opacity", 1.0)) * 100)))
            for key, _label, _show_key, text_key, scale_key, _check_name in _META_FIELDS:
                self._field_texts[key] = str(data[text_key])
                self._field_scales[key] = float(data[scale_key])
            self.scale_slider.setValue(int(round(float(data["scale"]) * 100)))
            for font_key in FIELD_FONT_KEYS:
                field = font_key.removesuffix("_font")
                self._field_fonts[field] = coerce_font_family(data.get(font_key, DEFAULT_FONT_FAMILY))
            for bold_key in FIELD_BOLD_KEYS:
                field = bold_key.removesuffix("_bold")
                default_bold = bool(DEFAULT_FIELD_BOLD.get(field, False))
                self._field_bolds[field] = bool(data.get(bold_key, default_bold))
            for italic_key in FIELD_ITALIC_KEYS:
                field = italic_key.removesuffix("_italic")
                self._field_italics[field] = bool(data.get(italic_key, False))
            for opacity_key in FIELD_OPACITY_KEYS:
                field = opacity_key.removesuffix("_opacity")
                self._field_opacities[field] = coerce_field_opacity(
                    data.get(opacity_key, 1.0), 1.0
                )
            self.quality_slider.setValue(int(data["quality"]))
            fmt = str(data.get("export_format", "jpg"))
            fidx = self.format_combo.findData(fmt)
            self.format_combo.setCurrentIndex(fidx if fidx >= 0 else 0)
            self.png_compress_slider.setValue(int(data.get("png_compress", 6)))
            self.webp_quality_slider.setValue(int(data.get("webp_quality", 90)))
            self.keep_exif.setChecked(bool(data.get("keep_exif", True)))
            self.keep_icc.setChecked(bool(data.get("keep_icc", True)))
            self._logo_path = str(data["logo_path"])
            self._output_dir = str(data["output_dir"])
            self.output_label.setText(self._output_dir)
            self.output_label.setToolTip(self._output_dir)
            self.bar_opacity_slider.setValue(int(round(float(layout.get("bar_opacity", 0.72)) * 100)))
            self.bar_height_slider.setValue(int(round(float(layout.get("bar_height", 1.0)) * 100)))
            side = float(layout.get("side_pad", 1.0))
            self.pad_left_slider.setValue(int(round(float(layout.get("pad_left", side)) * 100)))
            self.pad_right_slider.setValue(int(round(float(layout.get("pad_right", side)) * 100)))
            self.pad_top_slider.setValue(int(round(float(layout.get("pad_top", 1.0)) * 100)))
            self.pad_bottom_slider.setValue(int(round(float(layout.get("pad_bottom", 1.0)) * 100)))
            self.corner_radius_slider.setValue(int(layout.get("corner_radius", 0)))
            self.shadow_strength_slider.setValue(int(layout.get("shadow_strength", 25)))
            self._field_positions = coerce_field_positions(layout.get("field_positions"))
            policy = str(data.get("conflict_policy", "number"))
            pidx = self.conflict_combo.findData(policy)
            self.conflict_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
            self._update_logo_ui()
            self._update_style_dependent_ui()
            self._update_export_format_ui()
        finally:
            for widget in self._inputs:
                widget.blockSignals(False)
            self._loading = False
