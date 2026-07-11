from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import shutil
import sqlite3
import sys
import traceback
import urllib.parse
import urllib.request
import webbrowser
from ctypes import wintypes
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "TG 索引控制中心"
APP_VERSION = "1.0.0"
SENSITIVE_KEYS = {"TELEGRAM_BOT_TOKEN", "BOT_WEBHOOK_SECRET", "ADMIN_TOKEN"}
ENV_KEYS = [
    "SITE_URL",
    "TELEGRAM_BOT_TOKEN",
    "BOT_REQUEST_TIMEOUT",
    "BOT_POLLING_TIMEOUT",
    "BOT_WEBHOOK_HOST",
    "BOT_WEBHOOK_PORT",
    "BOT_WEBHOOK_SECRET",
    "ADMIN_HOST",
    "ADMIN_PORT",
    "ADMIN_TOKEN",
    "FRONTEND_HOST",
    "FRONTEND_PORT",
]


def app_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


ROOT_DIR = app_root()
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "rectg.db"
WEB_DIST = ROOT_DIR / "web" / "dist"
LOG_DIR = ROOT_DIR / "logs"
CONFIG_PATH = DATA_DIR / "control_center.json"
SECRETS_PATH = DATA_DIR / "control_center.secrets.json"
ENV_PATH = ROOT_DIR / ".env"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for path in (ROOT_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def parse_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def update_env_file(values: dict[str, str], path: Path = ENV_PATH) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    remaining = dict(values)
    output: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        elif key in SENSITIVE_KEYS:
            output.append(f"# {key} 由 TG 索引控制中心安全存储")
        else:
            output.append(raw)
    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# TG 索引控制中心")
        for key, value in remaining.items():
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, Any]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def dpapi_encrypt(value: str) -> str:
    raw = value.encode("utf-8")
    if os.name != "nt":
        return "plain:" + base64.b64encode(raw).decode("ascii")
    in_blob, in_buf = _blob(raw)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), ctypes.c_wchar_p(APP_NAME), None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del in_buf


def dpapi_decrypt(value: str) -> str:
    if not value:
        return ""
    if value.startswith("plain:"):
        return base64.b64decode(value[6:]).decode("utf-8")
    if not value.startswith("dpapi:") or os.name != "nt":
        return ""
    encrypted = base64.b64decode(value[6:])
    in_blob, in_buf = _blob(encrypted)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del in_buf


class SettingsStore:
    DEFAULTS: dict[str, Any] = {
        "auto_start_frontend": False,
        "auto_start_admin": False,
        "auto_start_bot": False,
        "auto_restart": True,
        "close_to_tray": True,
        "frontend_host": "127.0.0.1",
        "frontend_port": 4321,
        "log_max_mb": 10,
        "backup_keep": 20,
    }

    def __init__(self) -> None:
        ensure_dirs()
        self.data = dict(self.DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass
        self.secrets: dict[str, str] = {}
        if SECRETS_PATH.exists():
            try:
                raw = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
                for key, encrypted in raw.items():
                    self.secrets[key] = dpapi_decrypt(str(encrypted))
            except Exception:
                self.secrets = {}

    def save(self) -> None:
        ensure_dirs()
        CONFIG_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        encrypted = {key: dpapi_encrypt(value) for key, value in self.secrets.items() if value}
        SECRETS_PATH.write_text(json.dumps(encrypted, ensure_ascii=False, indent=2), encoding="utf-8")

    def environment(self) -> dict[str, str]:
        env = parse_env_file()
        env.update({k: v for k, v in self.secrets.items() if v})
        env.setdefault("FRONTEND_HOST", str(self.data.get("frontend_host", "127.0.0.1")))
        env.setdefault("FRONTEND_PORT", str(self.data.get("frontend_port", 4321)))
        return env


def connect_db(write: bool = False) -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在：{DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    if write:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
    return conn


def backup_database() -> Path:
    ensure_dirs()
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"rectg-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    source = connect_db()
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return target


def trim_backups(keep: int) -> None:
    backup_dir = DATA_DIR / "backups"
    if not backup_dir.exists():
        return
    files = sorted(backup_dir.glob("rectg-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[max(1, int(keep)):]:
        try:
            path.unlink()
        except OSError:
            pass


def rotate_log(path: Path, max_mb: int) -> None:
    if not path.exists() or path.stat().st_size < max(1, max_mb) * 1024 * 1024:
        return
    old = path.with_suffix(path.suffix + ".1")
    if old.exists():
        old.unlink()
    path.replace(old)


class ServiceManager(QWidget):
    state_changed = Signal(str, str)
    log_received = Signal(str, str)

    def __init__(self, settings: SettingsStore) -> None:
        super().__init__()
        self.settings = settings
        self.processes: dict[str, QProcess] = {}
        self.states = {name: "STOPPED" for name in ("frontend", "admin", "bot")}
        self.manual_stop: set[str] = set()
        self.pending_restart: set[str] = set()

    def _command(self, service: str) -> tuple[str, list[str]]:
        if getattr(sys, "frozen", False):
            return sys.executable, ["--service", service]
        return sys.executable, [str(ROOT_DIR / "control_center.py"), "--service", service]

    def _process(self, service: str) -> QProcess:
        process = self.processes.get(service)
        if process is not None:
            return process
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardOutput.connect(partial(self._read_output, service, False))
        process.readyReadStandardError.connect(partial(self._read_output, service, True))
        process.started.connect(partial(self._on_started, service))
        process.finished.connect(partial(self._on_finished, service))
        process.errorOccurred.connect(partial(self._on_error, service))
        self.processes[service] = process
        return process

    def start(self, service: str) -> None:
        process = self._process(service)
        if process.state() != QProcess.NotRunning:
            return
        self.manual_stop.discard(service)
        program, args = self._command(service)
        env = QProcessEnvironment.systemEnvironment()
        for key, value in self.settings.environment().items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(ROOT_DIR))
        self.states[service] = "STARTING"
        self.state_changed.emit(service, "STARTING")
        self.log_received.emit(service, f"{now_text()} 启动服务")
        process.start(program, args)

    def stop(self, service: str) -> None:
        process = self._process(service)
        self.manual_stop.add(service)
        if process.state() == QProcess.NotRunning:
            self.states[service] = "STOPPED"
            self.state_changed.emit(service, "STOPPED")
            return
        self.states[service] = "STOPPING"
        self.state_changed.emit(service, "STOPPING")
        process.terminate()
        QTimer.singleShot(5000, lambda: process.kill() if process.state() != QProcess.NotRunning else None)

    def restart(self, service: str) -> None:
        process = self._process(service)
        if process.state() == QProcess.NotRunning:
            self.start(service)
            return
        self.pending_restart.add(service)
        self.stop(service)

    def start_all(self) -> None:
        for name in ("frontend", "admin", "bot"):
            self.start(name)

    def stop_all(self) -> None:
        for name in ("bot", "admin", "frontend"):
            self.stop(name)

    def running(self, service: str) -> bool:
        return self._process(service).state() != QProcess.NotRunning

    def _read_output(self, service: str, error: bool) -> None:
        process = self._process(service)
        data = process.readAllStandardError() if error else process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        prefix = "[ERROR] " if error else ""
        for line in text.splitlines():
            if line.strip():
                self.log_received.emit(service, prefix + line)

    def _on_started(self, service: str) -> None:
        self.states[service] = "RUNNING"
        self.state_changed.emit(service, "RUNNING")

    def _on_finished(self, service: str, exit_code: int, _status: Any) -> None:
        state = "STOPPED" if service in self.manual_stop or exit_code == 0 else "FAILED"
        self.manual_stop.discard(service)
        self.states[service] = state
        self.state_changed.emit(service, state)
        self.log_received.emit(service, f"{now_text()} 服务退出，代码 {exit_code}")
        if service in self.pending_restart:
            self.pending_restart.discard(service)
            self.state_changed.emit(service, "RESTARTING")
            QTimer.singleShot(250, lambda: self.start(service))
        elif state == "FAILED" and self.settings.data.get("auto_restart", True):
            self.state_changed.emit(service, "RESTARTING")
            QTimer.singleShot(3000, lambda: self.start(service))

    def _on_error(self, service: str, error: Any) -> None:
        self.log_received.emit(service, f"[ERROR] QProcess: {error}")


class ScanWorker(QThread):
    done = Signal(int, str)
    failed = Signal(str)

    def __init__(self, raw: str, category: str) -> None:
        super().__init__()
        self.raw = raw
        self.category = category

    def run(self) -> None:
        try:
            from admin_dashboard import scan_telegram_batch, save_scanned_entries
            results = scan_telegram_batch(self.raw)
            data: dict[str, str] = {"batch_total": str(sum(1 for r in results if not r.error))}
            idx = 0
            errors = []
            for result in results:
                if result.error:
                    errors.append(f"{result.url}: {result.error}")
                    continue
                fields = {
                    "username": result.username,
                    "url": result.url,
                    "title": result.title,
                    "description": result.description,
                    "type": result.entry_type,
                    "count": "" if result.count is None else str(result.count),
                    "category": self.category,
                    "keep": "1",
                    "valid": str(result.valid),
                    "private": str(result.private),
                }
                for key, value in fields.items():
                    data[f"{key}_{idx}"] = value
                idx += 1
            ids = save_scanned_entries(data) if idx else []
            self.done.emit(len(ids), "\n".join(errors[:20]))
        except Exception:
            self.failed.emit(traceback.format_exc())


class AddResourcesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量添加 Telegram 资源")
        self.resize(680, 430)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每行输入一个公开链接或 @username："))
        self.text = QTextEdit()
        self.text.setPlaceholderText("https://t.me/example\n@example2")
        layout.addWidget(self.text)
        form = QFormLayout()
        self.category = QLineEdit("🧭 综合导航")
        form.addRow("默认分类", self.category)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def selected_ids(table: QTableWidget, id_column: int = 1) -> list[int]:
    result: list[int] = []
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item and item.checkState() == Qt.Checked:
            try:
                result.append(int(table.item(row, id_column).text()))
            except Exception:
                pass
    return result


def check_item() -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
    item.setCheckState(Qt.Unchecked)
    return item


class ResourcesPage(QWidget):
    log = Signal(str)
    changed = Signal()

    def __init__(self, settings: SettingsStore) -> None:
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题、用户名、分类或链接")
        controls.addWidget(self.search, 1)
        for text, slot in (
            ("刷新", self.load),
            ("批量添加", self.add),
            ("删除所选", self.delete_selected),
            ("开启监听", partial(self.listener_selected, True)),
            ("关闭监听", partial(self.listener_selected, False)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels(["选", "ID", "标题", "用户名", "链接", "类型", "分类", "人数", "显示", "有效", "私密", "监听", "消息"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.search.returnPressed.connect(self.load)
        self.load()

    def load(self) -> None:
        try:
            keyword = self.search.text().strip()
            conn = connect_db(write=True)
            try:
                from message_indexer import init_message_index_schema
                init_message_index_schema(conn)
                params: list[Any] = []
                where = ""
                if keyword:
                    where = "WHERE e.title LIKE ? OR e.username LIKE ? OR e.category LIKE ? OR e.url LIKE ?"
                    params = [f"%{keyword}%"] * 4
                rows = conn.execute(
                    f"""SELECT e.id,e.title,e.username,e.url,e.type,e.category,e.count,e.keep,e.valid,e.private,
                               e.listen_enabled,e.listen_status,COUNT(mi.id) AS message_count
                        FROM entries e LEFT JOIN message_index mi ON mi.entry_id=e.id
                        {where} GROUP BY e.id ORDER BY e.id DESC LIMIT 1000""",
                    params,
                ).fetchall()
            finally:
                conn.close()
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                values = [
                    None, row["id"], row["title"] or "", row["username"] or "", row["url"] or "",
                    row["type"] or "", row["category"] or "", row["count"] or 0,
                    "是" if row["keep"] else "否", "是" if row["valid"] else "否",
                    "是" if row["private"] else "否",
                    f"{'ON' if row['listen_enabled'] else 'OFF'} / {row['listen_status'] or 'off'}",
                    row["message_count"] or 0,
                ]
                self.table.setItem(r, 0, check_item())
                for c in range(1, len(values)):
                    self.table.setItem(r, c, QTableWidgetItem(str(values[c])))
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def add(self) -> None:
        dialog = AddResourcesDialog(self)
        if dialog.exec() != QDialog.Accepted or not dialog.text.toPlainText().strip():
            return
        self.worker = ScanWorker(dialog.text.toPlainText(), dialog.category.text().strip() or "🧭 综合导航")
        self.worker.done.connect(self._add_done)
        self.worker.failed.connect(lambda text: QMessageBox.critical(self, APP_NAME, text))
        self.worker.start()
        self.log.emit("开始扫描并添加 Telegram 资源")

    def _add_done(self, count: int, errors: str) -> None:
        message = f"已保存 {count} 条资源。"
        if errors:
            message += "\n部分扫描失败：\n" + errors
        QMessageBox.information(self, APP_NAME, message)
        self.load()
        self.changed.emit()

    def delete_selected(self) -> None:
        ids = selected_ids(self.table)
        if not ids:
            QMessageBox.information(self, APP_NAME, "请先勾选资源。")
            return
        if QMessageBox.question(self, APP_NAME, f"确认删除所选 {len(ids)} 个资源及其消息索引？") != QMessageBox.Yes:
            return
        try:
            backup = backup_database()
            conn = connect_db(write=True)
            try:
                conn.execute("BEGIN IMMEDIATE")
                marks = ",".join("?" for _ in ids)
                rows = conn.execute(f"SELECT username,url FROM entries WHERE id IN ({marks})", ids).fetchall()
                conn.execute(f"DELETE FROM message_index WHERE entry_id IN ({marks})", ids)
                conn.execute(f"DELETE FROM entries WHERE id IN ({marks})", ids)
                for row in rows:
                    conn.execute("DELETE FROM links WHERE url=? OR username=?", (row["url"], row["username"]))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            trim_backups(int(self.settings.data.get("backup_keep", 20)))
            self.log.emit(f"删除资源 {ids}；备份：{backup.name}")
            self.load()
            self.changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def listener_selected(self, enabled: bool) -> None:
        ids = selected_ids(self.table)
        if not ids:
            QMessageBox.information(self, APP_NAME, "请先勾选资源。")
            return
        try:
            if enabled:
                from admin_dashboard import enable_listener
                errors = []
                for entry_id in ids:
                    try:
                        enable_listener(entry_id)
                    except Exception as exc:
                        errors.append(f"{entry_id}: {exc}")
                if errors:
                    QMessageBox.warning(self, APP_NAME, "\n".join(errors[:20]))
            else:
                conn = connect_db(write=True)
                try:
                    marks = ",".join("?" for _ in ids)
                    conn.execute(
                        f"UPDATE entries SET listen_enabled=0,listen_status='off',listen_error=NULL,updated_at=datetime('now') WHERE id IN ({marks})",
                        ids,
                    )
                    conn.commit()
                finally:
                    conn.close()
            self.load()
            self.changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))


class MessagesPage(QWidget):
    log = Signal(str)

    def __init__(self, settings: SettingsStore) -> None:
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索频道、关键词、消息 ID")
        controls.addWidget(self.search, 1)
        for text, slot in (("刷新", self.load), ("删除所选", self.delete_selected), ("清空全部", self.clear_all)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["选", "ID", "来源", "用户名", "消息ID", "时间", "内容预览", "媒体", "关键词", "链接"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        layout.addWidget(self.table)
        self.search.returnPressed.connect(self.load)
        self.load()

    def load(self) -> None:
        try:
            keyword = self.search.text().strip()
            conn = connect_db(write=True)
            try:
                from message_indexer import init_message_index_schema
                init_message_index_schema(conn)
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(message_index)").fetchall()}
                preview = "COALESCE(mi.text_preview,'')" if "text_preview" in columns else "''"
                media = "COALESCE(mi.media_type,'')" if "media_type" in columns else "''"
                params: list[Any] = []
                where = ""
                if keyword:
                    where = """WHERE mi.keywords LIKE ? OR mi.chat_title LIKE ? OR mi.chat_username LIKE ?
                               OR CAST(mi.message_id AS TEXT) LIKE ?"""
                    params = [f"%{keyword}%"] * 4
                rows = conn.execute(
                    f"""SELECT mi.id,mi.chat_title,mi.chat_username,mi.message_id,mi.message_date,
                               {preview} AS preview,{media} AS media,mi.keywords,mi.link
                        FROM message_index mi {where}
                        ORDER BY mi.id DESC LIMIT 2000""",
                    params,
                ).fetchall()
            finally:
                conn.close()
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                self.table.setItem(r, 0, check_item())
                values = [row["id"], row["chat_title"] or "", row["chat_username"] or "", row["message_id"],
                          row["message_date"] or "", row["preview"] or "", row["media"] or "",
                          " ".join((row["keywords"] or "").split()[:30]), row["link"] or ""]
                for c, value in enumerate(values, start=1):
                    self.table.setItem(r, c, QTableWidgetItem(str(value)))
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                self.table.setRowCount(0)
            else:
                QMessageBox.critical(self, APP_NAME, str(exc))
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def delete_selected(self) -> None:
        ids = selected_ids(self.table)
        if not ids:
            QMessageBox.information(self, APP_NAME, "请先勾选消息。")
            return
        if QMessageBox.question(self, APP_NAME, f"确认删除所选 {len(ids)} 条消息索引？") != QMessageBox.Yes:
            return
        try:
            backup = backup_database()
            conn = connect_db(write=True)
            try:
                conn.execute("BEGIN IMMEDIATE")
                for start in range(0, len(ids), 400):
                    batch = ids[start:start + 400]
                    marks = ",".join("?" for _ in batch)
                    conn.execute(f"DELETE FROM message_index WHERE id IN ({marks})", batch)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            trim_backups(int(self.settings.data.get("backup_keep", 20)))
            self.log.emit(f"删除 {len(ids)} 条消息索引；备份：{backup.name}")
            self.load()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def clear_all(self) -> None:
        if QMessageBox.question(self, APP_NAME, "确认清空全部消息索引？此操作会先自动备份数据库。") != QMessageBox.Yes:
            return
        try:
            backup = backup_database()
            conn = connect_db(write=True)
            try:
                conn.execute("DELETE FROM message_index")
                conn.commit()
            finally:
                conn.close()
            self.log.emit(f"清空全部消息索引；备份：{backup.name}")
            self.load()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))


class AdsPage(QWidget):
    changed = Signal()
    log = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        form_box = QGroupBox("广告内容")
        form = QFormLayout(form_box)
        self.ad_id = QLineEdit()
        self.ad_id.setReadOnly(True)
        self.title = QLineEdit()
        self.url = QLineEdit()
        self.description = QLineEdit()
        self.image_url = QLineEdit()
        self.position = QLineEdit("bot_search_inline")
        self.sort_order = QSpinBox()
        self.sort_order.setRange(-9999, 9999)
        self.enabled = QCheckBox("启用")
        self.enabled.setChecked(True)
        for label, widget in (
            ("ID", self.ad_id), ("位置", self.position), ("标题", self.title), ("链接", self.url),
            ("说明", self.description), ("图片链接", self.image_url), ("排序", self.sort_order), ("状态", self.enabled),
        ):
            form.addRow(label, widget)
        buttons = QHBoxLayout()
        for text, slot in (("新增", self.add), ("保存修改", self.update), ("删除所选", self.delete), ("刷新", self.load)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        form.addRow(buttons)
        layout.addWidget(form_box)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ID", "位置", "标题", "链接", "说明", "图片", "排序", "启用"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.populate)
        layout.addWidget(self.table)
        self.load()

    def ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute("""CREATE TABLE IF NOT EXISTS ads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, position TEXT NOT NULL, title TEXT NOT NULL,
            description TEXT, url TEXT NOT NULL, image_url TEXT, sort_order INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def load(self) -> None:
        try:
            conn = connect_db(write=True)
            try:
                self.ensure_table(conn)
                rows = conn.execute("SELECT * FROM ads ORDER BY sort_order,id").fetchall()
                conn.commit()
            finally:
                conn.close()
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                values = [row["id"], row["position"], row["title"], row["url"], row["description"] or "",
                          row["image_url"] or "", row["sort_order"], "是" if row["enabled"] else "否"]
                for c, value in enumerate(values):
                    self.table.setItem(r, c, QTableWidgetItem(str(value)))
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def populate(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.ad_id.setText(self.table.item(row, 0).text())
        self.position.setText(self.table.item(row, 1).text())
        self.title.setText(self.table.item(row, 2).text())
        self.url.setText(self.table.item(row, 3).text())
        self.description.setText(self.table.item(row, 4).text())
        self.image_url.setText(self.table.item(row, 5).text())
        self.sort_order.setValue(int(self.table.item(row, 6).text() or 0))
        self.enabled.setChecked(self.table.item(row, 7).text() == "是")

    def payload(self) -> tuple[Any, ...]:
        if not self.title.text().strip() or not self.url.text().strip():
            raise ValueError("广告标题和链接不能为空。")
        return (self.position.text().strip() or "bot_search_inline", self.title.text().strip()[:30],
                self.description.text().strip(), self.url.text().strip(), self.image_url.text().strip(),
                self.sort_order.value(), 1 if self.enabled.isChecked() else 0)

    def add(self) -> None:
        try:
            data = self.payload()
            conn = connect_db(write=True)
            try:
                self.ensure_table(conn)
                conn.execute("""INSERT INTO ads(position,title,description,url,image_url,sort_order,enabled,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,datetime('now'),datetime('now'))""", data)
                conn.commit()
            finally:
                conn.close()
            self.log.emit("新增广告")
            self.load()
            self.changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def update(self) -> None:
        if not self.ad_id.text().isdigit():
            QMessageBox.information(self, APP_NAME, "请先选择广告。")
            return
        try:
            data = self.payload()
            conn = connect_db(write=True)
            try:
                conn.execute("""UPDATE ads SET position=?,title=?,description=?,url=?,image_url=?,sort_order=?,enabled=?,
                                updated_at=datetime('now') WHERE id=?""", (*data, int(self.ad_id.text())))
                conn.commit()
            finally:
                conn.close()
            self.log.emit(f"更新广告 {self.ad_id.text()}")
            self.load()
            self.changed.emit()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def delete(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, APP_NAME, "请先选择广告。")
            return
        ad_id = int(self.table.item(row, 0).text())
        if QMessageBox.question(self, APP_NAME, f"确认删除广告 {ad_id}？") != QMessageBox.Yes:
            return
        conn = connect_db(write=True)
        try:
            conn.execute("DELETE FROM ads WHERE id=?", (ad_id,))
            conn.commit()
        finally:
            conn.close()
        self.log.emit(f"删除广告 {ad_id}")
        self.load()
        self.changed.emit()


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, settings: SettingsStore) -> None:
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        env_group = QGroupBox("环境变量")
        env_form = QFormLayout(env_group)
        self.env_edits: dict[str, QLineEdit] = {}
        env = self.settings.environment()
        for key in ENV_KEYS:
            edit = QLineEdit(env.get(key, ""))
            if key in SENSITIVE_KEYS:
                edit.setEchoMode(QLineEdit.Password)
            self.env_edits[key] = edit
            env_form.addRow(key, edit)
        layout.addWidget(env_group)
        app_group = QGroupBox("控制中心")
        app_form = QFormLayout(app_group)
        self.auto_frontend = QCheckBox()
        self.auto_admin = QCheckBox()
        self.auto_bot = QCheckBox()
        self.auto_restart = QCheckBox()
        self.close_to_tray = QCheckBox()
        for widget, key in (
            (self.auto_frontend, "auto_start_frontend"), (self.auto_admin, "auto_start_admin"),
            (self.auto_bot, "auto_start_bot"), (self.auto_restart, "auto_restart"),
            (self.close_to_tray, "close_to_tray"),
        ):
            widget.setChecked(bool(settings.data.get(key)))
        self.frontend_port = QSpinBox()
        self.frontend_port.setRange(1, 65535)
        self.frontend_port.setValue(int(settings.data.get("frontend_port", 4321)))
        self.log_max = QSpinBox()
        self.log_max.setRange(1, 500)
        self.log_max.setValue(int(settings.data.get("log_max_mb", 10)))
        self.backup_keep = QSpinBox()
        self.backup_keep.setRange(1, 500)
        self.backup_keep.setValue(int(settings.data.get("backup_keep", 20)))
        for label, widget in (
            ("启动程序后自动启动前端", self.auto_frontend),
            ("启动程序后自动启动后台", self.auto_admin),
            ("启动程序后自动启动 Bot", self.auto_bot),
            ("服务异常退出后自动重启", self.auto_restart),
            ("关闭窗口时最小化到托盘", self.close_to_tray),
            ("前端端口", self.frontend_port),
            ("单个日志最大 MB", self.log_max),
            ("保留数据库备份数量", self.backup_keep),
        ):
            app_form.addRow(label, widget)
        layout.addWidget(app_group)
        buttons = QHBoxLayout()
        save = QPushButton("保存配置")
        save.clicked.connect(self.save)
        test = QPushButton("测试 Bot Token")
        test.clicked.connect(self.test_bot)
        open_data = QPushButton("打开数据目录")
        open_data.clicked.connect(lambda: os.startfile(str(DATA_DIR)) if os.name == "nt" else None)
        buttons.addWidget(save)
        buttons.addWidget(test)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def save(self) -> None:
        try:
            env_values: dict[str, str] = {}
            for key, edit in self.env_edits.items():
                value = edit.text().strip()
                if key in SENSITIVE_KEYS:
                    self.settings.secrets[key] = value
                else:
                    env_values[key] = value
            update_env_file(env_values)
            self.settings.data.update({
                "auto_start_frontend": self.auto_frontend.isChecked(),
                "auto_start_admin": self.auto_admin.isChecked(),
                "auto_start_bot": self.auto_bot.isChecked(),
                "auto_restart": self.auto_restart.isChecked(),
                "close_to_tray": self.close_to_tray.isChecked(),
                "frontend_port": self.frontend_port.value(),
                "log_max_mb": self.log_max.value(),
                "backup_keep": self.backup_keep.value(),
            })
            self.settings.save()
            QMessageBox.information(self, APP_NAME, "配置已保存。服务重启后使用新配置。")
            self.saved.emit()
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def test_bot(self) -> None:
        token = self.env_edits["TELEGRAM_BOT_TOKEN"].text().strip()
        if not token:
            QMessageBox.warning(self, APP_NAME, "请先填写 TELEGRAM_BOT_TOKEN。")
            return
        try:
            request = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe", method="POST")
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("ok"):
                user = payload.get("result") or {}
                QMessageBox.information(self, APP_NAME, f"Token 有效：@{user.get('username', '')}")
            else:
                raise RuntimeError(str(payload))
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Token 检测失败：{exc}")


class DashboardPage(QWidget):
    def __init__(self, manager: ServiceManager, settings: SettingsStore) -> None:
        super().__init__()
        self.manager = manager
        self.settings = settings
        layout = QVBoxLayout(self)
        cards = QGridLayout()
        self.state_labels: dict[str, QLabel] = {}
        names = {"frontend": "前端网站", "admin": "管理后台", "bot": "Telegram Bot"}
        for col, service in enumerate(("frontend", "admin", "bot")):
            box = QGroupBox(names[service])
            box_layout = QVBoxLayout(box)
            state = QLabel("STOPPED")
            state.setStyleSheet("font-size:20px;font-weight:700")
            self.state_labels[service] = state
            box_layout.addWidget(state)
            buttons = QHBoxLayout()
            for text, slot in (
                ("启动", partial(manager.start, service)),
                ("停止", partial(manager.stop, service)),
                ("重启", partial(manager.restart, service)),
            ):
                button = QPushButton(text)
                button.clicked.connect(slot)
                buttons.addWidget(button)
            box_layout.addLayout(buttons)
            open_button = QPushButton("打开页面")
            if service == "frontend":
                open_button.clicked.connect(lambda: webbrowser.open(
                    f"http://{settings.data.get('frontend_host','127.0.0.1')}:{settings.data.get('frontend_port',4321)}"
                ))
            elif service == "admin":
                open_button.clicked.connect(lambda: webbrowser.open(
                    f"http://{settings.environment().get('ADMIN_HOST','127.0.0.1')}:{settings.environment().get('ADMIN_PORT','8787')}"
                ))
            else:
                open_button.setEnabled(False)
            box_layout.addWidget(open_button)
            cards.addWidget(box, 0, col)
        layout.addLayout(cards)
        all_buttons = QHBoxLayout()
        for text, slot in (("启动全部", manager.start_all), ("停止全部", manager.stop_all), ("重启全部", self.restart_all)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            all_buttons.addWidget(button)
        self.export_button = QPushButton("重新导出前端数据")
        all_buttons.addWidget(self.export_button)
        all_buttons.addStretch(1)
        layout.addLayout(all_buttons)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addStretch(1)
        manager.state_changed.connect(self.update_state)
        timer = QTimer(self)
        timer.timeout.connect(self.refresh_summary)
        timer.start(5000)
        self.refresh_summary()

    def restart_all(self) -> None:
        for name in ("frontend", "admin", "bot"):
            self.manager.restart(name)

    def update_state(self, service: str, state: str) -> None:
        self.state_labels[service].setText(state)
        color = {"RUNNING": "#16a34a", "FAILED": "#dc2626", "STARTING": "#d97706", "RESTARTING": "#d97706"}.get(state, "#64748b")
        self.state_labels[service].setStyleSheet(f"font-size:20px;font-weight:700;color:{color}")

    def refresh_summary(self) -> None:
        try:
            conn = connect_db()
            try:
                counts = {
                    "资源": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
                    "前台可见": conn.execute("SELECT COUNT(*) FROM entries WHERE valid=1 AND private=0 AND keep=1").fetchone()[0],
                    "消息索引": conn.execute("SELECT COUNT(*) FROM message_index").fetchone()[0],
                    "监听中": conn.execute("SELECT COUNT(*) FROM entries WHERE listen_enabled=1 AND listen_status='active'").fetchone()[0],
                }
            finally:
                conn.close()
            self.summary.setText(" | ".join(f"{k}: {v}" for k, v in counts.items()))
        except Exception as exc:
            self.summary.setText(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        self.settings = SettingsStore()
        self.manager = ServiceManager(self.settings)
        self.quitting = False
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1500, 900)
        self.pages = QStackedWidget()
        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        self.nav.addItems(["总览", "资源管理", "消息管理", "广告管理", "配置", "实时日志"])
        self.dashboard = DashboardPage(self.manager, self.settings)
        self.resources = ResourcesPage(self.settings)
        self.messages = MessagesPage(self.settings)
        self.ads = AdsPage()
        self.settings_page = SettingsPage(self.settings)
        self.logs = QTabWidget()
        self.log_edits: dict[str, QTextEdit] = {}
        for name, title in (("all", "全部"), ("frontend", "前端"), ("admin", "后台"), ("bot", "Bot"), ("control", "控制中心")):
            edit = QTextEdit()
            edit.setReadOnly(True)
            edit.document().setMaximumBlockCount(10000)
            self.log_edits[name] = edit
            self.logs.addTab(edit, title)
        for page in (self.dashboard, self.resources, self.messages, self.ads, self.settings_page, self.logs):
            self.pages.addWidget(page)
        splitter = QSplitter()
        splitter.addWidget(self.nav)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.manager.log_received.connect(self.append_log)
        self._service_log_offsets: dict[str, int] = {}
        if getattr(sys, "frozen", False):
            tail_timer = QTimer(self)
            tail_timer.timeout.connect(self.tail_service_logs)
            tail_timer.start(500)
            self._tail_timer = tail_timer
        self.resources.log.connect(lambda text: self.append_log("control", text))
        self.messages.log.connect(lambda text: self.append_log("control", text))
        self.ads.log.connect(lambda text: self.append_log("control", text))
        self.resources.changed.connect(self.run_export)
        self.ads.changed.connect(self.run_export)
        self.dashboard.export_button.clicked.connect(self.run_export)
        self._setup_toolbar()
        self._setup_tray()
        QTimer.singleShot(600, self.auto_start)

    def _setup_toolbar(self) -> None:
        bar = QToolBar("主工具栏")
        self.addToolBar(bar)
        for text, slot in (
            ("启动全部", self.manager.start_all), ("停止全部", self.manager.stop_all),
            ("打开前端", lambda: webbrowser.open(f"http://127.0.0.1:{self.settings.data.get('frontend_port',4321)}")),
            ("备份数据库", self.manual_backup),
        ):
            action = QAction(text, self)
            action.triggered.connect(slot)
            bar.addAction(action)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
        self.tray.setToolTip(APP_NAME)
        menu = self.tray.contextMenu() or None
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        for text, slot in (
            ("打开控制中心", self.show_normal), ("启动全部", self.manager.start_all),
            ("停止全部", self.manager.stop_all), ("打开前端", lambda: webbrowser.open(f"http://127.0.0.1:{self.settings.data.get('frontend_port',4321)}")),
            ("退出并停止全部", self.quit_all),
        ):
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def show_normal(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def append_log(self, service: str, text: str) -> None:
        clean = text
        for secret in self.settings.secrets.values():
            if secret:
                clean = clean.replace(secret, "***")
        line = f"[{now_text()}] [{service.upper()}] {clean}"
        self.log_edits["all"].append(line)
        if service in self.log_edits:
            self.log_edits[service].append(line)
        path = LOG_DIR / f"{service}.log"
        rotate_log(path, int(self.settings.data.get("log_max_mb", 10)))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.status.showMessage(clean[:180], 5000)

    def tail_service_logs(self) -> None:
        for service in ("frontend", "admin", "bot", "export"):
            path = LOG_DIR / f"{service}.service.log"
            if not path.exists():
                continue
            offset = self._service_log_offsets.get(service, 0)
            try:
                size = path.stat().st_size
                if size < offset:
                    offset = 0
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    data = handle.read()
                    self._service_log_offsets[service] = handle.tell()
                for line in data.splitlines():
                    if line.strip():
                        self.append_log("control" if service == "export" else service, line)
            except OSError:
                pass

    def run_export(self) -> None:
        process = QProcess(self)
        if getattr(sys, "frozen", False):
            program, args = sys.executable, ["--service", "export"]
        else:
            program, args = sys.executable, [str(ROOT_DIR / "control_center.py"), "--service", "export"]
        env = QProcessEnvironment.systemEnvironment()
        for key, value in self.settings.environment().items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self.append_log("control", bytes(process.readAllStandardOutput()).decode("utf-8", "replace").strip()))
        process.finished.connect(lambda code, _status: self.append_log("control", f"前端数据导出完成，退出代码 {code}"))
        process.start(program, args)
        self._export_process = process

    def manual_backup(self) -> None:
        try:
            path = backup_database()
            trim_backups(int(self.settings.data.get("backup_keep", 20)))
            QMessageBox.information(self, APP_NAME, f"数据库已备份：\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))

    def auto_start(self) -> None:
        for service, key in (
            ("frontend", "auto_start_frontend"), ("admin", "auto_start_admin"), ("bot", "auto_start_bot")
        ):
            if self.settings.data.get(key):
                self.manager.start(service)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.quitting and self.settings.data.get("close_to_tray", True):
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "程序已最小化到托盘，已启动的服务继续运行。")
            return
        event.accept()

    def quit_all(self) -> None:
        self.quitting = True
        self.manager.stop_all()
        QTimer.singleShot(1800, QApplication.instance().quit)


class TeeStream:
    def __init__(self, primary: Any, file_handle: Any) -> None:
        self.primary = primary
        self.file_handle = file_handle
        self.encoding = "utf-8"

    def write(self, text: str) -> int:
        value = str(text)
        if self.primary is not None:
            try:
                self.primary.write(value)
                self.primary.flush()
            except Exception:
                pass
        self.file_handle.write(value)
        self.file_handle.flush()
        return len(value)

    def flush(self) -> None:
        if self.primary is not None:
            try:
                self.primary.flush()
            except Exception:
                pass
        self.file_handle.flush()

    def isatty(self) -> bool:
        return False


def prepare_service_stdio(name: str) -> None:
    ensure_dirs()
    handle = (LOG_DIR / f"{name}.service.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = TeeStream(sys.stdout, handle)
    sys.stderr = TeeStream(sys.stderr, handle)


def run_frontend_service() -> None:
    host = os.environ.get("FRONTEND_HOST", "127.0.0.1")
    port = int(os.environ.get("FRONTEND_PORT", "4321"))
    if not WEB_DIST.exists():
        raise SystemExit(f"前端构建目录不存在：{WEB_DIST}。请先运行 npm run build。")
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(WEB_DIST), **kwargs)
        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} {fmt % args}", flush=True)
        def do_GET(self) -> None:
            requested = urllib.parse.urlparse(self.path).path
            target = WEB_DIST / requested.lstrip("/")
            if requested != "/" and not target.exists() and not Path(str(target) + ".html").exists():
                self.path = "/index.html"
            super().do_GET()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"前端服务已启动：http://{host}:{port}", flush=True)
    server.serve_forever()


def run_service(name: str) -> None:
    prepare_service_stdio(name)
    os.chdir(ROOT_DIR)
    if name == "frontend":
        run_frontend_service()
    elif name == "admin":
        import admin_dashboard
        sys.argv = ["admin_dashboard.py"]
        admin_dashboard.main()
    elif name == "bot":
        import bot as tg_bot
        tg_bot.run_polling(drop_webhook=True)
    elif name == "export":
        import export_frontend_data
        export_frontend_data.main()
    else:
        raise SystemExit(f"未知服务：{name}")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--service", choices=["frontend", "admin", "bot", "export"])
    args = parser.parse_args()
    if args.service:
        run_service(args.service)
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
