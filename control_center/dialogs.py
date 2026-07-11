from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget,
)


class BatchAddDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("批量添加 Telegram 资源")
        self.resize(680, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每行输入一个公开链接或 @username。程序会扫描后写入数据库。"))
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("https://t.me/channel1\n@group2")
        layout.addWidget(self.input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("扫描并保存")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> str:
        return self.input.toPlainText().strip()


class ResourceEditDialog(QDialog):
    def __init__(self, row: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑资源 #{row['id']}")
        form = QFormLayout(self)
        self.title = QLineEdit(str(row.get("title") or ""))
        self.category = QLineEdit(str(row.get("category") or ""))
        self.entry_type = QComboBox()
        self.entry_type.addItems(["channel", "group", "bot"])
        self.entry_type.setCurrentText(str(row.get("type") or "channel"))
        self.keep = QCheckBox("前台显示")
        self.keep.setChecked(bool(row.get("keep")))
        self.valid = QCheckBox("有效")
        self.valid.setChecked(bool(row.get("valid")))
        self.private = QCheckBox("私密")
        self.private.setChecked(bool(row.get("private")))
        form.addRow("标题", self.title)
        form.addRow("分类", self.category)
        form.addRow("类型", self.entry_type)
        form.addRow("状态", self.keep)
        form.addRow("", self.valid)
        form.addRow("", self.private)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "title": self.title.text().strip(), "category": self.category.text().strip(),
            "type": self.entry_type.currentText(), "keep": int(self.keep.isChecked()),
            "valid": int(self.valid.isChecked()), "private": int(self.private.isChecked()),
        }


class AdDialog(QDialog):
    def __init__(self, row: dict[str, Any] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("广告设置")
        row = row or {}
        form = QFormLayout(self)
        self.position = QLineEdit(str(row.get("position") or "bot_search_inline"))
        self.title = QLineEdit(str(row.get("title") or ""))
        self.description = QLineEdit(str(row.get("description") or ""))
        self.url = QLineEdit(str(row.get("url") or ""))
        self.image_url = QLineEdit(str(row.get("image_url") or ""))
        self.sort_order = QSpinBox()
        self.sort_order.setRange(-99999, 99999)
        self.sort_order.setValue(int(row.get("sort_order") or 0))
        self.enabled = QCheckBox("启用")
        self.enabled.setChecked(bool(row.get("enabled", 1)))
        form.addRow("广告位", self.position)
        form.addRow("标题", self.title)
        form.addRow("说明", self.description)
        form.addRow("链接", self.url)
        form.addRow("图片链接", self.image_url)
        form.addRow("排序", self.sort_order)
        form.addRow("状态", self.enabled)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, Any]:
        return {
            "position": self.position.text().strip() or "bot_search_inline",
            "title": self.title.text().strip(), "description": self.description.text().strip(),
            "url": self.url.text().strip(), "image_url": self.image_url.text().strip(),
            "sort_order": self.sort_order.value(), "enabled": int(self.enabled.isChecked()),
        }
