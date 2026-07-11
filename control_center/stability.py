from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QTimer

from .processes import ManagedService, SERVICE_NAMES, ServiceManager

_INSTALLED = False
_STABLE_WINDOW_MS = 60_000


def install_service_restart_guard() -> None:
    """Keep the five-attempt crash limit effective across rapid restarts.

    ManagedService originally cleared ``restart_attempts`` as soon as a child
    emitted ``started``. A process that starts and immediately crashes would
    therefore retry forever. Deliberate user starts still begin a fresh retry
    budget, while automatic starts keep the current budget. A service earns a
    reset only after it remains alive for a full stability window.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    def mark_stable(service: ManagedService, generation: int, pid: int) -> None:
        if (
            getattr(service, "_stability_generation", 0) == generation
            and service.is_running()
            and int(service.process.processId()) == pid
        ):
            service.restart_attempts = 0
            service.logs.append(
                "control",
                f"{SERVICE_NAMES[service.name]} 已稳定运行 60 秒，自动重启计数已重置。",
            )

    def guarded_started(service: ManagedService) -> None:
        service._set_status("running")
        service.logs.append(
            "control",
            f"{SERVICE_NAMES[service.name]} 已启动，PID={service.process.processId()}。",
        )
        generation = int(getattr(service, "_stability_generation", 0)) + 1
        service._stability_generation = generation
        pid = int(service.process.processId())
        QTimer.singleShot(
            _STABLE_WINDOW_MS,
            lambda s=service, g=generation, p=pid: mark_stable(s, g, p),
        )

    original_start: Callable[[ServiceManager, str], Any] = ServiceManager.start
    original_restart: Callable[[ServiceManager, str], Any] = ServiceManager.restart

    def deliberate_start(manager: ServiceManager, name: str) -> Any:
        manager.services[name].restart_attempts = 0
        return original_start(manager, name)

    def deliberate_restart(manager: ServiceManager, name: str) -> Any:
        manager.services[name].restart_attempts = 0
        return original_restart(manager, name)

    ManagedService._started = guarded_started
    ServiceManager.start = deliberate_start
    ServiceManager.restart = deliberate_restart
