from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QProcess, QTimer

from .processes import ManagedService, SERVICE_NAMES

_INSTALLED = False
_STABLE_WINDOW_MS = 60_000
_STOP_TIMEOUT_MS = 3_500
_MAX_RESTARTS = 5


def install_service_restart_guard() -> None:
    """Install cancellable service stop/restart timers before services exist.

    This keeps the automatic retry budget bounded, prevents stale single-shot
    callbacks from starting duplicate child processes, and treats an expected
    Windows force-stop as a controlled shutdown instead of a service failure.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_init: Callable[..., None] = ManagedService.__init__
    original_start: Callable[[ManagedService], Any] = ManagedService.start
    original_force_stop: Callable[..., None] = ManagedService.force_stop
    original_error: Callable[[ManagedService, QProcess.ProcessError], None] = ManagedService._error

    def initialized(service: ManagedService, *args: Any, **kwargs: Any) -> None:
        original_init(service, *args, **kwargs)
        service._auto_restart_timer = QTimer(service)
        service._auto_restart_timer.setSingleShot(True)
        service._auto_restart_timer.timeout.connect(lambda s=service: automatic_start(s))

        service._kill_timer = QTimer(service)
        service._kill_timer.setSingleShot(True)
        service._kill_timer.timeout.connect(lambda s=service: finish_termination(s))

        service._stable_timer = QTimer(service)
        service._stable_timer.setSingleShot(True)
        service._stable_timer.timeout.connect(lambda s=service: mark_stable(s))

        service._restart_after_stop = False
        service._stability_pid = 0

    def stop_timer(service: ManagedService, name: str) -> None:
        timer = getattr(service, name, None)
        if timer is not None:
            timer.stop()

    def cancel_all_timers(service: ManagedService) -> None:
        stop_timer(service, "_auto_restart_timer")
        stop_timer(service, "_kill_timer")
        stop_timer(service, "_stable_timer")

    def mark_stable(service: ManagedService) -> None:
        pid = int(service.process.processId())
        if not service.is_running() or pid != int(getattr(service, "_stability_pid", 0)):
            return
        previous = int(service.restart_attempts)
        service.restart_attempts = 0
        if previous:
            service.logs.append(
                "control",
                f"{SERVICE_NAMES[service.name]} 已稳定运行 60 秒，自动重启计数已重置。",
            )

    def started(service: ManagedService) -> None:
        service._set_status("running")
        service.logs.append(
            "control",
            f"{SERVICE_NAMES[service.name]} 已启动，PID={service.process.processId()}。",
        )
        service._stability_pid = int(service.process.processId())
        service._stable_timer.start(_STABLE_WINDOW_MS)

    def manual_start(service: ManagedService) -> Any:
        cancel_all_timers(service)
        service._restart_after_stop = False
        service.restart_attempts = 0
        return original_start(service)

    def automatic_start(service: ManagedService) -> Any:
        service._auto_restart_timer.stop()
        if service.is_running():
            return None
        return original_start(service)

    def manual_stop(service: ManagedService) -> None:
        stop_timer(service, "_auto_restart_timer")
        stop_timer(service, "_stable_timer")
        service._restart_after_stop = False
        service.restart_attempts = 0
        if not service.is_running():
            service.manual_stop = True
            service._set_status("stopped")
            return
        service.manual_stop = True
        service._set_status("stopping")
        service.logs.append("control", f"正在停止 {SERVICE_NAMES[service.name]}。")
        service.process.terminate()
        service._kill_timer.start(_STOP_TIMEOUT_MS)

    def manual_restart(service: ManagedService) -> None:
        stop_timer(service, "_auto_restart_timer")
        stop_timer(service, "_stable_timer")
        service.restart_attempts = 0
        if not service.is_running():
            manual_start(service)
            return
        service.manual_stop = True
        service._restart_after_stop = True
        service._set_status("restarting")
        service.logs.append("control", f"正在重启 {SERVICE_NAMES[service.name]}。")
        service.process.terminate()
        service._kill_timer.start(_STOP_TIMEOUT_MS)

    def finish_termination(service: ManagedService) -> None:
        if service.process.state() == QProcess.ProcessState.NotRunning:
            return
        service.logs.append(
            "control",
            f"{SERVICE_NAMES[service.name]} 未及时退出，执行强制停止。",
            "WARNING",
        )
        service.process.kill()

    def force_stop(service: ManagedService, timeout_ms: int = 3000) -> None:
        cancel_all_timers(service)
        service._restart_after_stop = False
        service.restart_attempts = 0
        original_force_stop(service, timeout_ms)

    def process_error(service: ManagedService, error: QProcess.ProcessError) -> None:
        if service.manual_stop and error == QProcess.ProcessError.Crashed:
            service.logs.append(
                "control",
                f"{SERVICE_NAMES[service.name]} 已按请求强制停止。",
                "WARNING",
            )
            return
        original_error(service, error)

    def finished(service: ManagedService, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        stop_timer(service, "_kill_timer")
        stop_timer(service, "_stable_timer")
        service._flush_buffers()

        restart_requested = bool(getattr(service, "_restart_after_stop", False))
        service._restart_after_stop = False
        unexpected = not service.manual_stop and exit_code != 0

        if restart_requested:
            service._set_status("restarting")
        else:
            service._set_status("failed" if unexpected else "stopped")

        level = "ERROR" if unexpected else "INFO"
        service.logs.append(
            "control",
            f"{SERVICE_NAMES[service.name]} 已退出：exit_code={exit_code}, exit_status={exit_status.name}。",
            level,
        )

        if restart_requested:
            QTimer.singleShot(0, lambda s=service: manual_start(s))
            return

        if unexpected and service.config_getter().get("auto_restart", True):
            if service.restart_attempts < _MAX_RESTARTS:
                service.restart_attempts += 1
                delay_ms = min(30_000, 3_000 * service.restart_attempts)
                service.logs.append(
                    "control",
                    f"{SERVICE_NAMES[service.name]} 将在 {delay_ms // 1000} 秒后自动重启（第 {service.restart_attempts}/{_MAX_RESTARTS} 次）。",
                    "WARNING",
                )
                service._auto_restart_timer.start(delay_ms)
            else:
                service.logs.append(
                    "control",
                    f"{SERVICE_NAMES[service.name]} 已达到自动重启上限，请查看日志并手动处理。",
                    "ERROR",
                )
        else:
            stop_timer(service, "_auto_restart_timer")

    ManagedService.__init__ = initialized
    ManagedService.start = manual_start
    ManagedService.stop = manual_stop
    ManagedService.restart = manual_restart
    ManagedService.force_stop = force_stop
    ManagedService._started = started
    ManagedService._error = process_error
    ManagedService._finished = finished
