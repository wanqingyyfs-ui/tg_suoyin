from __future__ import annotations

import codecs
import logging
import logging.handlers
import traceback
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QRunnable, QTimer, Signal

from .runtime import LOG_DIR, ROOT_DIR, WEB_DIST_DIR, ensure_runtime_dirs, parse_env_file, redact, service_program_and_args, utility_program_and_args

SERVICE_NAMES = {"frontend": "前端网站", "admin": "管理后台", "bot": "Telegram Bot"}


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
        else:
            self.signals.finished.emit(result)


class LogHub(QObject):
    message = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_dirs()
        self.loggers: dict[str, logging.Logger] = {}

    def _logger(self, service: str) -> logging.Logger:
        if service in self.loggers:
            return self.loggers[service]
        logger = logging.getLogger(f"tg_control_center.{service}.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / f"{service}.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        self.loggers[service] = logger
        return logger

    def append(self, service: str, text: str, level: str = "INFO") -> None:
        clean = redact(text.rstrip("\r\n"), parse_env_file())
        if not clean:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        rendered = f"[{timestamp}] [{SERVICE_NAMES.get(service, service)}] [{level}] {clean}"
        logger = self._logger(service)
        if level == "ERROR":
            logger.error(clean)
        elif level == "WARNING":
            logger.warning(clean)
        else:
            logger.info(clean)
        self.message.emit(service, rendered, level)


class RuntimeLogTailer(QObject):
    """Tail raw child logs so a windowed PyInstaller child never needs a console."""

    def __init__(self, logs: LogHub):
        super().__init__()
        self.logs = logs
        self.paths = {name: LOG_DIR / f"raw-{name}.log" for name in ("frontend", "admin", "bot", "control")}
        self.offsets: dict[str, int] = {}
        self.decoders = {name: codecs.getincrementaldecoder("utf-8")("replace") for name in self.paths}
        self.buffers = {name: "" for name in self.paths}
        for name, path in self.paths.items():
            try:
                self.offsets[name] = path.stat().st_size
            except OSError:
                self.offsets[name] = 0
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def poll(self) -> None:
        for name, path in self.paths.items():
            try:
                size = path.stat().st_size
            except OSError:
                continue
            offset = self.offsets.get(name, 0)
            if size < offset:
                offset = 0
                self.decoders[name] = codecs.getincrementaldecoder("utf-8")("replace")
                self.buffers[name] = ""
            if size == offset:
                continue
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read()
                    self.offsets[name] = handle.tell()
            except OSError:
                continue
            text = self.buffers[name] + self.decoders[name].decode(data)
            lines = text.splitlines(keepends=True)
            remainder = ""
            for index, line in enumerate(lines):
                if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                    remainder = line
                else:
                    level = "ERROR" if any(token in line for token in ("Traceback", "ERROR", "❌", "失败", "异常")) else "INFO"
                    self.logs.append(name, line, level)
            self.buffers[name] = remainder


class ManagedService(QObject):
    status_changed = Signal(str, str)

    def __init__(self, name: str, logs: LogHub, config_getter: Callable[[], dict[str, Any]]):
        super().__init__()
        self.name = name
        self.logs = logs
        self.config_getter = config_getter
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT_DIR))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.started.connect(self._started)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.status = "stopped"
        self.manual_stop = False
        self.restart_attempts = 0
        self.stdout_buffer = ""
        self.stderr_buffer = ""

    def _environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        for key, value in parse_env_file().items():
            env.insert(key, value)
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("TG_SUOYIN_ROOT", str(ROOT_DIR))
        return env

    def _set_status(self, status: str) -> None:
        self.status = status
        self.status_changed.emit(self.name, status)

    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def start(self) -> None:
        if self.is_running():
            self.logs.append("control", f"{SERVICE_NAMES[self.name]} 已经在运行。", "WARNING")
            return
        self.manual_stop = False
        self.process.setProcessEnvironment(self._environment())
        program, arguments = service_program_and_args(self.name)
        self._set_status("starting")
        self.logs.append("control", f"正在启动 {SERVICE_NAMES[self.name]}：{program} {' '.join(arguments)}")
        self.process.start(program, arguments)

    def stop(self) -> None:
        if not self.is_running():
            self._set_status("stopped")
            return
        self.manual_stop = True
        self._set_status("stopping")
        self.logs.append("control", f"正在停止 {SERVICE_NAMES[self.name]}。")
        self.process.terminate()
        QTimer.singleShot(3500, self._kill_if_needed)

    def restart(self) -> None:
        if self.is_running():
            self.manual_stop = True
            self._set_status("restarting")
            self.process.terminate()
            QTimer.singleShot(3500, self._kill_and_restart)
        else:
            self.start()

    def force_stop(self, timeout_ms: int = 3000) -> None:
        self.manual_stop = True
        if not self.is_running():
            return
        self.process.terminate()
        if not self.process.waitForFinished(timeout_ms):
            self.process.kill()
            self.process.waitForFinished(1500)

    def _kill_if_needed(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.logs.append("control", f"{SERVICE_NAMES[self.name]} 未及时退出，执行强制停止。", "WARNING")
            self.process.kill()

    def _kill_and_restart(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        self.manual_stop = False
        self.start()

    def _started(self) -> None:
        self.restart_attempts = 0
        self._set_status("running")
        self.logs.append("control", f"{SERVICE_NAMES[self.name]} 已启动，PID={self.process.processId()}。")

    def _error(self, error: QProcess.ProcessError) -> None:
        self._set_status("failed")
        self.logs.append("control", f"{SERVICE_NAMES[self.name]} 进程错误：{error.name} / {self.process.errorString()}", "ERROR")

    def _finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._flush_buffers()
        unexpected = not self.manual_stop and exit_code != 0
        self._set_status("failed" if unexpected else "stopped")
        level = "ERROR" if unexpected else "INFO"
        self.logs.append("control", f"{SERVICE_NAMES[self.name]} 已退出：exit_code={exit_code}, exit_status={exit_status.name}。", level)
        if unexpected and self.config_getter().get("auto_restart", True) and self.restart_attempts < 5:
            self.restart_attempts += 1
            delay_ms = min(30000, 3000 * self.restart_attempts)
            self.logs.append("control", f"{SERVICE_NAMES[self.name]} 将在 {delay_ms // 1000} 秒后自动重启（第 {self.restart_attempts}/5 次）。", "WARNING")
            QTimer.singleShot(delay_ms, self.start)

    @staticmethod
    def _decode(data: bytes) -> str:
        return bytes(data).decode("utf-8", errors="replace")

    def _emit_lines(self, text: str, stderr: bool = False) -> str:
        lines = text.splitlines(keepends=True)
        remainder = ""
        for index, line in enumerate(lines):
            if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                remainder = line
                continue
            self.logs.append(self.name, line, "ERROR" if stderr else "INFO")
        return remainder

    def _read_stdout(self) -> None:
        self.stdout_buffer += self._decode(self.process.readAllStandardOutput())
        self.stdout_buffer = self._emit_lines(self.stdout_buffer, False)

    def _read_stderr(self) -> None:
        self.stderr_buffer += self._decode(self.process.readAllStandardError())
        self.stderr_buffer = self._emit_lines(self.stderr_buffer, True)

    def _flush_buffers(self) -> None:
        if self.stdout_buffer:
            self.logs.append(self.name, self.stdout_buffer)
            self.stdout_buffer = ""
        if self.stderr_buffer:
            self.logs.append(self.name, self.stderr_buffer, "ERROR")
            self.stderr_buffer = ""


class ServiceManager(QObject):
    status_changed = Signal(str, str)
    utility_finished = Signal(str, bool)

    def __init__(self, logs: LogHub, config_getter: Callable[[], dict[str, Any]]):
        super().__init__()
        self.logs = logs
        self.config_getter = config_getter
        self.services = {name: ManagedService(name, logs, config_getter) for name in ("frontend", "admin", "bot")}
        for service in self.services.values():
            service.status_changed.connect(self.status_changed)
        self.utility_processes: dict[str, QProcess] = {}
        self.utility_callbacks: dict[str, Callable[[bool], None] | None] = {}

    def start(self, name: str) -> None:
        if name == "frontend" and not (WEB_DIST_DIR / "index.html").exists():
            self.logs.append("control", "未发现前端构建，先自动构建前端。", "WARNING")
            self.build_frontend(lambda ok: self.services[name].start() if ok else None)
            return
        self.services[name].start()

    def stop(self, name: str) -> None:
        self.services[name].stop()

    def restart(self, name: str) -> None:
        self.services[name].restart()

    def start_all(self) -> None:
        self.start("frontend")
        self.start("admin")
        self.start("bot")

    def stop_all(self) -> None:
        for name in ("bot", "admin", "frontend"):
            self.stop(name)

    def force_stop_all(self) -> None:
        for name in ("bot", "admin", "frontend"):
            self.services[name].force_stop()
        for process in list(self.utility_processes.values()):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)

    def run_utility(self, name: str, callback: Callable[[bool], None] | None = None) -> None:
        existing = self.utility_processes.get(name)
        if existing and existing.state() != QProcess.ProcessState.NotRunning:
            self.logs.append("control", f"工具 {name} 正在运行。", "WARNING")
            return
        process = QProcess(self)
        process.setWorkingDirectory(str(ROOT_DIR))
        env = QProcessEnvironment.systemEnvironment()
        for key, value in parse_env_file().items():
            env.insert(key, value)
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("TG_SUOYIN_ROOT", str(ROOT_DIR))
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda p=process: self.logs.append("control", bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))
        process.finished.connect(lambda code, _status, n=name: self._utility_done(n, code == 0))
        process.errorOccurred.connect(lambda _err, p=process, n=name: self.logs.append("control", f"工具 {n} 启动失败：{p.errorString()}", "ERROR"))
        self.utility_processes[name] = process
        self.utility_callbacks[name] = callback
        program, args = utility_program_and_args(name)
        self.logs.append("control", f"运行工具 {name}。")
        process.start(program, args)

    def build_frontend(self, callback: Callable[[bool], None] | None = None) -> None:
        self.run_utility("frontend-build", callback)

    def _utility_done(self, name: str, ok: bool) -> None:
        self.logs.append("control", f"工具 {name} {'执行成功' if ok else '执行失败'}。", "INFO" if ok else "ERROR")
        callback = self.utility_callbacks.pop(name, None)
        process = self.utility_processes.pop(name, None)
        if process:
            process.deleteLater()
        self.utility_finished.emit(name, ok)
        if callback:
            callback(ok)
