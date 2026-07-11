from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from PySide6.QtCore import QLockFile, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from . import data
from .dialogs import AdDialog, BatchAddDialog, ResourceEditDialog
from .processes import FunctionWorker, LogHub, RuntimeLogTailer, SERVICE_NAMES, ServiceManager
from .runtime import (
    APP_NAME,
    LOG_DIR,
    ROOT_DIR,
    backup_database,
    load_control_config,
    parse_env_file,
    save_control_config,
    write_env_file,
)

STATUS_TEXT = {
    "stopped": "已停止",
    "starting": "启动中",
    "running": "运行中",
    "stopping": "停止中",
    "failed": "启动失败",
    "restarting": "重启中",
}


def make_button(text: str, callback: Callable[[], None]) -> QPushButton:
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


def configure_table(table: QTableWidget) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)


def selected_ids(table: QTableWidget, id_column: int = 0) -> list[int]:
    result: list[int] = []
    for index in table.selectionModel().selectedRows():
        item = table.item(index.row(), id_column)
        if not item:
            continue
        try:
            result.append(int(item.data(Qt.ItemDataRole.UserRole) or item.text()))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


class DashboardPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.status_labels: dict[str, QLabel] = {}
        self.stats_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(make_button("启动全部", window.services.start_all))
        toolbar.addWidget(make_button("停止全部", window.services.stop_all))
        toolbar.addWidget(make_button("刷新统计", self.refresh_stats))
        toolbar.addWidget(make_button("刷新前端数据", lambda: window.services.run_utility("export")))
        toolbar.addWidget(make_button("构建前端", window.services.build_frontend))
        toolbar.addWidget(make_button("备份数据库", self.backup_database))
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        services = QGridLayout()
        for column, name in enumerate(("frontend", "admin", "bot")):
            box = QGroupBox(SERVICE_NAMES[name])
            inner = QVBoxLayout(box)
            status = QLabel("已停止")
            status.setStyleSheet("font-size:20px;font-weight:700;color:#64748b")
            self.status_labels[name] = status
            inner.addWidget(status)
            descriptions = {
                "frontend": "本地前端网站服务",
                "admin": "资源、消息、广告管理后台",
                "bot": "Telegram Bot 搜索与监听",
            }
            inner.addWidget(QLabel(descriptions[name]))
            row = QHBoxLayout()
            row.addWidget(make_button("启动", lambda checked=False, n=name: window.services.start(n)))
            row.addWidget(make_button("停止", lambda checked=False, n=name: window.services.stop(n)))
            row.addWidget(make_button("重启", lambda checked=False, n=name: window.services.restart(n)))
            if name in {"frontend", "admin"}:
                row.addWidget(make_button("打开", lambda checked=False, n=name: window.open_service(n)))
            inner.addLayout(row)
            services.addWidget(box, 0, column)
        layout.addLayout(services)

        stats_box = QGroupBox("数据库概况")
        stats_grid = QGridLayout(stats_box)
        names = {
            "links": "候选链接",
            "entries": "资源总数",
            "visible_entries": "前台可见",
            "message_index": "消息索引",
            "active_listening": "监听中",
            "ads": "广告",
        }
        for index, (key, title) in enumerate(names.items()):
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card_layout = QVBoxLayout(card)
            card_layout.addWidget(QLabel(title))
            value = QLabel("-")
            value.setStyleSheet("font-size:24px;font-weight:700")
            self.stats_labels[key] = value
            card_layout.addWidget(value)
            stats_grid.addWidget(card, index // 3, index % 3)
        layout.addWidget(stats_box)
        layout.addStretch(1)
        QTimer.singleShot(100, self.refresh_stats)

    def update_status(self, name: str, status: str) -> None:
        label = self.status_labels[name]
        label.setText(STATUS_TEXT.get(status, status))
        color = {"running": "#16a34a", "failed": "#dc2626", "starting": "#d97706", "stopping": "#d97706"}.get(status, "#64748b")
        label.setStyleSheet(f"font-size:20px;font-weight:700;color:{color}")

    def refresh_stats(self) -> None:
        self.window.run_task("刷新数据库统计", data.dashboard_stats, self._show_stats)

    def _show_stats(self, stats: dict[str, int]) -> None:
        for key, label in self.stats_labels.items():
            label.setText(f"{int(stats.get(key, 0)):,}")

    def backup_database(self) -> None:
        self.window.run_task(
            "备份数据库",
            lambda: backup_database("manual"),
            lambda path: self.window.info(f"备份完成：\n{path}"),
        )


class ResourcesPage(QWidget):
    HEADERS = ["ID", "标题", "用户名", "类型", "分类", "人数", "显示", "有效", "私密", "监听", "消息数", "更新时间"]

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.rows: dict[int, dict[str, Any]] = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题、简介、用户名、分类或链接")
        self.search.returnPressed.connect(self.refresh)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(make_button("刷新", self.refresh))
        toolbar.addWidget(make_button("批量添加", self.add_resources))
        toolbar.addWidget(make_button("编辑", self.edit_selected))
        toolbar.addWidget(make_button("开启监听", lambda: self.set_listener(True)))
        toolbar.addWidget(make_button("关闭监听", lambda: self.set_listener(False)))
        toolbar.addWidget(make_button("显示", lambda: self.batch_flag("keep", 1)))
        toolbar.addWidget(make_button("隐藏", lambda: self.batch_flag("keep", 0)))
        toolbar.addWidget(make_button("删除选中", self.delete_selected))
        toolbar.addWidget(make_button("全选", self.table_select_all))
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        configure_table(self.table)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        layout.addWidget(self.table)
        QTimer.singleShot(150, self.refresh)

    def refresh(self) -> None:
        keyword = self.search.text().strip()
        self.window.run_task("加载资源", lambda: data.list_resources(keyword), self._fill)

    def _fill(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {int(row["id"]): row for row in rows}
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row["id"], row.get("title") or row.get("clean_title") or "",
                row.get("username") or "", row.get("type") or "", row.get("category") or "",
                row.get("count") or 0, "是" if row.get("keep") else "否",
                "是" if row.get("valid") else "否", "是" if row.get("private") else "否",
                f"{'ON' if row.get('listen_enabled') else 'OFF'} / {row.get('listen_status') or 'off'}",
                row.get("message_count") or 0, row.get("updated_at") or "",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def table_select_all(self) -> None:
        self.table.selectAll()

    def _selected(self) -> list[int]:
        ids = selected_ids(self.table)
        if not ids:
            self.window.warn("请先选择资源。")
        return ids

    def add_resources(self) -> None:
        dialog = BatchAddDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        raw = dialog.values()
        if not raw:
            return
        self.window.run_task("扫描并添加资源", lambda: data.scan_and_add_resources(raw), self._added)

    def _added(self, result: dict[str, Any]) -> None:
        failed = result.get("failed") or []
        message = f"已扫描 {result.get('scanned', 0)} 条，保存 {len(result.get('saved') or [])} 条。"
        if failed:
            message += "\n\n失败：\n" + "\n".join(failed[:20])
        self.window.info(message)
        self.window.after_database_change()
        self.refresh()

    def edit_selected(self) -> None:
        ids = self._selected()
        if len(ids) != 1:
            if ids:
                self.window.warn("编辑时只能选择一条资源。")
            return
        row = self.rows.get(ids[0])
        if not row:
            return
        dialog = ResourceEditDialog(row, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.window.run_task(
            "保存资源",
            lambda: data.update_resource(ids[0], values),
            lambda _result: self._changed("资源已保存。"),
        )

    def batch_flag(self, field: str, value: Any) -> None:
        ids = self._selected()
        if not ids:
            return
        self.window.run_task(
            "批量修改资源",
            lambda: data.batch_update_resources(ids, field, value),
            lambda count: self._changed(f"已修改 {count} 条资源。"),
        )

    def set_listener(self, enabled: bool) -> None:
        ids = self._selected()
        if not ids:
            return
        self.window.run_task(
            "更新监听状态",
            lambda: data.set_listeners(ids, enabled),
            self._listener_done,
        )

    def _listener_done(self, result: dict[str, Any]) -> None:
        message = f"成功 {len(result.get('succeeded') or [])} 条。"
        failed = result.get("failed") or []
        if failed:
            message += "\n失败：\n" + "\n".join(failed[:20])
        self.window.info(message)
        self.refresh()

    def delete_selected(self) -> None:
        ids = self._selected()
        if not ids:
            return
        if not self.window.confirm(f"确认删除选中的 {len(ids)} 条资源？\n会同时删除这些资源的消息索引和 links 记录。"):
            return
        self.window.run_task(
            "删除资源",
            lambda: self._delete_with_backup(ids),
            lambda count: self._changed(f"已删除 {count} 条资源。"),
        )

    def _delete_with_backup(self, ids: list[int]) -> int:
        if self.window.config.get("backup_before_delete", True):
            backup_database("delete-resources")
        return data.delete_resources(ids, delete_links=True)

    def _changed(self, message: str) -> None:
        self.window.info(message)
        self.window.after_database_change()
        self.refresh()


class MessagesPage(QWidget):
    HEADERS = ["ID", "来源", "消息ID", "时间", "内容预览", "媒体", "关键词", "跳转链接"]

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关键词、频道、消息预览")
        self.search.returnPressed.connect(self.refresh)
        self.entry_id = QSpinBox()
        self.entry_id.setRange(0, 2_000_000_000)
        self.entry_id.setSpecialValueText("全部资源")
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(QLabel("资源ID"))
        toolbar.addWidget(self.entry_id)
        toolbar.addWidget(make_button("刷新", self.refresh))
        toolbar.addWidget(make_button("删除选中", self.delete_selected))
        toolbar.addWidget(make_button("清空当前资源", self.clear_entry))
        toolbar.addWidget(make_button("全选", self.table_select_all))
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        configure_table(self.table)
        layout.addWidget(self.table)
        QTimer.singleShot(200, self.refresh)

    def refresh(self) -> None:
        keyword = self.search.text().strip()
        entry_id = self.entry_id.value() or None
        self.window.run_task("加载消息索引", lambda: data.list_messages(keyword, entry_id), self._fill)

    def _fill(self, rows: list[dict[str, Any]]) -> None:
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            source = row.get("chat_title") or row.get("entry_title") or row.get("chat_username") or ""
            media = " ".join(str(row.get(key) or "") for key in ("media_emoji", "media_type", "media_meta")).strip()
            values = [
                row["id"], source, row.get("message_id") or "", row.get("message_date") or "",
                row.get("text_preview") or "", media, row.get("keywords") or "", row.get("link") or "",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                if c in {4, 6}:
                    item.setToolTip(str(value))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def table_select_all(self) -> None:
        self.table.selectAll()

    def delete_selected(self) -> None:
        ids = selected_ids(self.table)
        if not ids:
            self.window.warn("请先选择消息。")
            return
        if not self.window.confirm(f"确认删除选中的 {len(ids)} 条消息索引？"):
            return
        self.window.run_task(
            "删除消息",
            lambda: self._delete_with_backup(ids),
            lambda count: self._done(f"已删除 {count} 条消息索引。"),
        )

    def _delete_with_backup(self, ids: list[int]) -> int:
        if self.window.config.get("backup_before_delete", True):
            backup_database("delete-messages")
        return data.delete_messages(ids)

    def clear_entry(self) -> None:
        entry_id = self.entry_id.value()
        if not entry_id:
            self.window.warn("请先填写资源 ID，防止误清空全部消息。")
            return
        if not self.window.confirm(f"确认清空资源 #{entry_id} 的全部消息索引？"):
            return
        self.window.run_task(
            "清空资源消息",
            lambda: data.clear_messages_for_entries([entry_id]),
            lambda count: self._done(f"已删除 {count} 条消息索引。"),
        )

    def _done(self, message: str) -> None:
        self.window.info(message)
        self.refresh()


class AdsPage(QWidget):
    HEADERS = ["ID", "广告位", "标题", "说明", "链接", "排序", "启用"]

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.rows: dict[int, dict[str, Any]] = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(make_button("刷新", self.refresh))
        toolbar.addWidget(make_button("新增", self.add_ad))
        toolbar.addWidget(make_button("编辑", self.edit_ad))
        toolbar.addWidget(make_button("删除选中", self.delete_selected))
        toolbar.addWidget(make_button("全选", self.table_select_all))
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        configure_table(self.table)
        self.table.doubleClicked.connect(lambda _index: self.edit_ad())
        layout.addWidget(self.table)
        QTimer.singleShot(250, self.refresh)

    def refresh(self) -> None:
        self.window.run_task("加载广告", data.list_ads, self._fill)

    def _fill(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {int(row["id"]): row for row in rows}
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row["id"], row.get("position") or "", row.get("title") or "",
                row.get("description") or "", row.get("url") or "", row.get("sort_order") or 0,
                "是" if row.get("enabled") else "否",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def table_select_all(self) -> None:
        self.table.selectAll()

    def add_ad(self) -> None:
        dialog = AdDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.window.run_task(
            "新增广告",
            lambda: data.save_ad(dialog.values()),
            lambda _id: self._done("广告已新增。"),
        )

    def edit_ad(self) -> None:
        ids = selected_ids(self.table)
        if len(ids) != 1:
            self.window.warn("编辑时请选择一条广告。")
            return
        dialog = AdDialog(self.rows.get(ids[0]), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.window.run_task(
            "保存广告",
            lambda: data.save_ad(dialog.values(), ids[0]),
            lambda _id: self._done("广告已保存。"),
        )

    def delete_selected(self) -> None:
        ids = selected_ids(self.table)
        if not ids:
            self.window.warn("请先选择广告。")
            return
        if not self.window.confirm(f"确认删除选中的 {len(ids)} 条广告？"):
            return
        self.window.run_task(
            "删除广告",
            lambda: data.delete_ads(ids),
            lambda count: self._done(f"已删除 {count} 条广告。"),
        )

    def _done(self, message: str) -> None:
        self.window.info(message)
        self.window.after_database_change()
        self.refresh()


class SettingsPage(QWidget):
    ENV_FIELDS = [
        ("SITE_URL", "站点域名", False),
        ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token", True),
        ("BOT_REQUEST_TIMEOUT", "Bot 请求超时", False),
        ("BOT_POLLING_TIMEOUT", "Bot polling 超时", False),
        ("BOT_WEBHOOK_HOST", "Webhook Host", False),
        ("BOT_WEBHOOK_PORT", "Webhook Port", False),
        ("BOT_WEBHOOK_SECRET", "Webhook Secret", True),
        ("ADMIN_HOST", "后台 Host", False),
        ("ADMIN_PORT", "后台 Port", False),
        ("ADMIN_TOKEN", "后台 Token", True),
        ("FRONTEND_HOST", "前端 Host", False),
        ("FRONTEND_PORT", "前端 Port", False),
    ]

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        self.inputs: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        form_box = QGroupBox("环境变量")
        form = QFormLayout(form_box)
        for key, label, secret in self.ENV_FIELDS:
            field = QLineEdit()
            if secret:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            self.inputs[key] = field
            form.addRow(label, field)
        layout.addWidget(form_box)

        behavior_box = QGroupBox("控制中心行为")
        behavior = QFormLayout(behavior_box)
        self.auto_start_frontend = QCheckBox("控制中心启动后自动启动前端")
        self.auto_start_admin = QCheckBox("控制中心启动后自动启动后台")
        self.auto_start_bot = QCheckBox("控制中心启动后自动启动 Bot")
        self.auto_restart = QCheckBox("服务异常退出后自动重启")
        self.minimize_to_tray = QCheckBox("关闭窗口时最小化到托盘")
        self.backup_before_delete = QCheckBox("删除资源或消息前自动备份数据库")
        self.refresh_frontend_after_change = QCheckBox("资源或广告变更后自动刷新前端数据")
        for widget in (
            self.auto_start_frontend, self.auto_start_admin, self.auto_start_bot,
            self.auto_restart, self.minimize_to_tray, self.backup_before_delete,
            self.refresh_frontend_after_change,
        ):
            behavior.addRow(widget)
        layout.addWidget(behavior_box)
        row = QHBoxLayout()
        row.addWidget(make_button("重新载入", self.load))
        row.addWidget(make_button("保存设置", self.save))
        row.addWidget(make_button("打开项目目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT_DIR)))))
        row.addWidget(make_button("打开日志目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.load()

    def load(self) -> None:
        env = parse_env_file()
        for key, field in self.inputs.items():
            field.setText(env.get(key, ""))
        config = self.window.config
        self.auto_start_frontend.setChecked(bool(config.get("auto_start_frontend")))
        self.auto_start_admin.setChecked(bool(config.get("auto_start_admin")))
        self.auto_start_bot.setChecked(bool(config.get("auto_start_bot")))
        self.auto_restart.setChecked(bool(config.get("auto_restart", True)))
        self.minimize_to_tray.setChecked(bool(config.get("minimize_to_tray", True)))
        self.backup_before_delete.setChecked(bool(config.get("backup_before_delete", True)))
        self.refresh_frontend_after_change.setChecked(bool(config.get("refresh_frontend_after_change", True)))

    def save(self) -> None:
        env_values = {key: field.text().strip() for key, field in self.inputs.items()}
        for key in ("BOT_REQUEST_TIMEOUT", "BOT_POLLING_TIMEOUT", "BOT_WEBHOOK_PORT", "ADMIN_PORT", "FRONTEND_PORT"):
            value = env_values[key]
            if value and not value.isdigit():
                self.window.warn(f"{key} 必须是数字。")
                return
        write_env_file(env_values)
        config = {
            "auto_start_frontend": self.auto_start_frontend.isChecked(),
            "auto_start_admin": self.auto_start_admin.isChecked(),
            "auto_start_bot": self.auto_start_bot.isChecked(),
            "auto_restart": self.auto_restart.isChecked(),
            "minimize_to_tray": self.minimize_to_tray.isChecked(),
            "backup_before_delete": self.backup_before_delete.isChecked(),
            "refresh_frontend_after_change": self.refresh_frontend_after_change.isChecked(),
        }
        save_control_config(config)
        self.window.config = load_control_config()
        self.window.info("设置已保存。运行中的服务需要重启后读取新配置。")


class LogsPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["全部", "control", "frontend", "admin", "bot"])
        self.filter.currentTextChanged.connect(self.render)
        toolbar.addWidget(QLabel("服务"))
        toolbar.addWidget(self.filter)
        toolbar.addWidget(make_button("清空显示", self.clear))
        toolbar.addWidget(make_button("打开日志目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))))
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(10000)
        layout.addWidget(self.output)
        self.lines: list[tuple[str, str]] = []

    def append(self, service: str, text: str, _level: str) -> None:
        self.lines.append((service, text))
        if len(self.lines) > 10000:
            self.lines = self.lines[-10000:]
        current = self.filter.currentText()
        if current == "全部" or current == service:
            self.output.appendPlainText(text)
            scrollbar = self.output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def render(self) -> None:
        current = self.filter.currentText()
        self.output.setPlainText("\n".join(text for service, text in self.lines if current == "全部" or current == service))

    def clear(self) -> None:
        self.lines.clear()
        self.output.clear()


class MainWindow(QMainWindow):
    def __init__(self, lock: QLockFile):
        super().__init__()
        self.lock = lock
        self.config = load_control_config()
        self.thread_pool = QThreadPool.globalInstance()
        self.active_workers: list[FunctionWorker] = []
        self.logs = LogHub()
        self.log_tailer = RuntimeLogTailer(self.logs)
        self.services = ServiceManager(self.logs, lambda: self.config)

        self.setWindowTitle(APP_NAME)
        self.resize(1500, 900)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.dashboard = DashboardPage(self)
        self.resources = ResourcesPage(self)
        self.messages = MessagesPage(self)
        self.ads = AdsPage(self)
        self.settings = SettingsPage(self)
        self.logs_page = LogsPage(self)
        self.tabs.addTab(self.dashboard, "总览")
        self.tabs.addTab(self.resources, "资源管理")
        self.tabs.addTab(self.messages, "消息管理")
        self.tabs.addTab(self.ads, "广告管理")
        self.tabs.addTab(self.settings, "设置")
        self.tabs.addTab(self.logs_page, "日志")

        self.logs.message.connect(self.logs_page.append)
        self.services.status_changed.connect(self.dashboard.update_status)
        self._build_tray()
        self.statusBar().showMessage(f"项目目录：{ROOT_DIR}")
        QTimer.singleShot(500, self._auto_start)

    def _build_tray(self) -> None:
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = QAction("打开控制中心", self)
        show_action.triggered.connect(self.show_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        start_action = QAction("启动全部", self)
        start_action.triggered.connect(self.services.start_all)
        menu.addAction(start_action)
        stop_action = QAction("停止全部", self)
        stop_action.triggered.connect(self.services.stop_all)
        menu.addAction(stop_action)
        menu.addSeparator()
        exit_action = QAction("退出并停止全部", self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_from_tray() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def _auto_start(self) -> None:
        for name in ("frontend", "admin", "bot"):
            if self.config.get(f"auto_start_{name}"):
                self.services.start(name)

    def open_service(self, name: str) -> None:
        env = parse_env_file()
        if name == "frontend":
            host = env.get("FRONTEND_HOST", "127.0.0.1") or "127.0.0.1"
            port = env.get("FRONTEND_PORT", "4321") or "4321"
            url = f"http://{host}:{port}/"
        elif name == "admin":
            host = env.get("ADMIN_HOST", "127.0.0.1") or "127.0.0.1"
            port = env.get("ADMIN_PORT", "8787") or "8787"
            token = env.get("ADMIN_TOKEN", "")
            url = f"http://{host}:{port}/"
            if token:
                url += "?token=" + urllib.parse.quote(token)
        else:
            return
        QDesktopServices.openUrl(QUrl(url))

    def run_task(self, title: str, function: Callable[[], Any], on_success: Callable[[Any], None] | None = None) -> None:
        worker = FunctionWorker(function)
        self.active_workers.append(worker)
        self.statusBar().showMessage(f"{title}……")

        def finished(result: Any) -> None:
            self.statusBar().showMessage(f"{title}完成", 4000)
            if on_success:
                on_success(result)
            if worker in self.active_workers:
                self.active_workers.remove(worker)

        def failed(trace: str) -> None:
            self.logs.append("control", trace, "ERROR")
            self.statusBar().showMessage(f"{title}失败", 5000)
            self.warn(f"{title}失败。详细信息已写入日志。\n\n{trace.splitlines()[-1] if trace.splitlines() else trace}")
            if worker in self.active_workers:
                self.active_workers.remove(worker)

        worker.signals.finished.connect(finished)
        worker.signals.failed.connect(failed)
        self.thread_pool.start(worker)

    def after_database_change(self) -> None:
        self.dashboard.refresh_stats()
        if self.config.get("refresh_frontend_after_change", True):
            self.services.run_utility("export")

    def show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def info(self, text: str) -> None:
        QMessageBox.information(self, APP_NAME, text)

    def warn(self, text: str) -> None:
        QMessageBox.warning(self, APP_NAME, text)

    def confirm(self, text: str) -> bool:
        return QMessageBox.question(self, APP_NAME, text) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.config.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "控制中心已最小化到系统托盘，服务继续运行。", QSystemTrayIcon.MessageIcon.Information, 2500)
            return
        if self.confirm("关闭控制中心会停止全部服务。确认退出？"):
            self.exit_application()
            event.accept()
        else:
            event.ignore()

    def exit_application(self) -> None:
        self.services.force_stop_all()
        self.tray.hide()
        if self.lock.isLocked():
            self.lock.unlock()
        QApplication.instance().quit()
