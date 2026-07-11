from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from .runtime import APP_NAME, ROOT_DIR, apply_env, ensure_runtime_dirs
from .window import MainWindow


def run_gui() -> int:
    ensure_runtime_dirs()
    apply_env()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("tg-suoyin")
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT_DIR / "data" / "control_center.lock"))
    lock.setStaleLockTime(10000)
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_NAME, "控制中心已经在运行，请从系统托盘打开。")
        return 2
    window = MainWindow(lock)
    window.show()
    app.aboutToQuit.connect(window.services.force_stop_all)
    code = app.exec()
    if lock.isLocked():
        lock.unlock()
    return code
