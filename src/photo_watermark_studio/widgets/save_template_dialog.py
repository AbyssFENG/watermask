# -*- coding: utf-8 -*-
"""“保存为我的模板”对话框，样式对齐原型 modal。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SaveTemplateDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "保存为我的模板",
        description: str = "为当前样式命名，之后可以在模板库中快速调用。",
        name: str = "",
        confirm_text: str = "保存模板",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TemplateDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("TemplateDialogCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("DialogTitle")
        hint = QLabel(description)
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(hint)
        label = QLabel("模板名称")
        label.setObjectName("FieldHead")
        layout.addSpacing(6)
        layout.addWidget(label)
        self.name_edit = QLineEdit(name)
        self.name_edit.setObjectName("templateNameEdit")
        self.name_edit.setPlaceholderText("例如 我的旅行相框")
        self.name_edit.selectAll()
        layout.addWidget(self.name_edit)
        self.error_label = QLabel("")
        self.error_label.setObjectName("DialogError")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
        actions.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setProperty("role", "soft")
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton(confirm_text)
        self.confirm_button.setObjectName("dialogConfirmButton")
        self.confirm_button.setProperty("role", "primary")
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self._confirm)
        for button in (self.cancel_button, self.confirm_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(88)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.name_edit.returnPressed.connect(self._confirm)

    def template_name(self) -> str:
        return self.name_edit.text().strip()

    def _confirm(self) -> None:
        if not self.template_name():
            self.error_label.setText("模板名称不能为空。")
            self.error_label.setVisible(True)
            self.name_edit.setFocus()
            return
        self.accept()
