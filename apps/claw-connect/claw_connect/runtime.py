"""Claw Connect application assembly (#4139 S1).

Wires the pieces together in one process: single-instance guard, opt-in
autostart, connection state, the supervised existing Resident, the tray and a
local quit event so ``claw-connect stop`` can end a running tray.

Nothing here selects a model, builds a Broker or approves a task. Connect is
a supervising UI over the one existing local runner.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import (
    AUTOSTART_RUN_VALUE_NAME,
    CONNECT_PRODUCT,
    CONNECT_VERSION,
    SINGLE_INSTANCE_MUTEX,
    WEB_URL,
)
from .autostart import Autostart
from .connection import ConnectionController, ConnectionState
from .menu_model import (
    ACTION_DISCONNECT,
    ACTION_OPEN_WEB,
    ACTION_QUIT,
    ACTION_RECONNECT,
    ACTION_TOGGLE_PAUSE,
)
from .resident_supervisor import ResidentSupervisor
from .single_instance import AlreadyRunning, SingleInstance

#: Local named event a second process uses to ask a running tray to quit.
QUIT_EVENT_NAME = "PadiemClawConnect.QuitEvent.v1"
#: Exit code when another Connect process already owns this PC.
CONNECT_APP_EXIT_ALREADY_RUNNING = 3


class QuitSignal:
    """Cross-process quit request using a named event (Windows) or a file."""

    def __init__(self, name: str, *, directory: str | None = None) -> None:
        self._name = name
        self._directory = directory
        self._event: Any = None
        self._ready = threading.Event()

    def open(self) -> None:
        if sys.platform == "win32":
            import win32event  # noqa: PLC0415

            self._event = win32event.CreateEvent(None, False, False, self._name)
        self._ready.set()

    def signal(self) -> bool:
        """Fire the quit request. True when a running instance was told."""
        if sys.platform != "win32":
            return False
        import win32api  # noqa: PLC0415
        import win32event  # noqa: PLC0415

        try:
            handle = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE, False, self._name
            )
        except Exception:
            return False
        try:
            win32event.SetEvent(handle)
            return True
        finally:
            win32api.CloseHandle(handle)

    def wait(self, timeout: float) -> bool:
        """Block until a quit is requested or the timeout elapses."""
        if self._event is None:
            return False
        import win32event  # noqa: PLC0415

        result = win32event.WaitForSingleObject(self._event, int(timeout * 1000))
        return result == win32event.WAIT_OBJECT_0

    def close(self) -> None:
        self._event = None


class ConnectApp:
    """One Claw Connect process: single instance, tray, supervised Resident."""

    def __init__(
        self,
        *,
        resident_command: Sequence[str] | None = None,
        autostart_store: Any | None = None,
        probe: Callable[[], bool] | None = None,
        supervisor: ResidentSupervisor | None = None,
        autostart: Autostart | None = None,
    ) -> None:
        self._autostart = autostart or Autostart(AUTOSTART_RUN_VALUE_NAME, autostart_store)
        self._controller = ConnectionController(probe)
        self._supervisor = supervisor or ResidentSupervisor(
            resident_command or ["python", "-c", "pass"]
        )
        self._single = SingleInstance(SINGLE_INSTANCE_MUTEX)
        self._quit_signal = QuitSignal(QUIT_EVENT_NAME)
        self._tray: Any = None
        self._quit = threading.Event()

    @property
    def controller(self) -> ConnectionController:
        return self._controller

    @property
    def supervisor(self) -> ResidentSupervisor:
        return self._supervisor

    @property
    def autostart(self) -> Autostart:
        return self._autostart

    @property
    def single_instance(self) -> SingleInstance:
        return self._single

    def status(self) -> dict[str, Any]:
        """The observable state. Never claims a state that was not observed."""
        return {
            "product": CONNECT_PRODUCT,
            "version": CONNECT_VERSION,
            "state": self._controller.state.value,
            "resident_running": self._supervisor.is_running(),
            "autostart_enabled": self._autostart.is_enabled(),
            "single_instance": self._single.held,
        }

    def status_json(self) -> str:
        return json.dumps(self.status(), ensure_ascii=False, sort_keys=True)

    # -- tray actions ------------------------------------------------------
    def open_web(self) -> None:
        import webbrowser  # noqa: PLC0415

        webbrowser.open(WEB_URL)

    def toggle_pause(self) -> None:
        if self._controller.state is ConnectionState.CONNECTED:
            self._controller.pause()
            self._supervisor.stop()
        elif self._controller.state is ConnectionState.PAUSED:
            self._controller.resume()
            self._supervisor.start()
        self._refresh_tray()

    def reconnect(self) -> None:
        if self._controller.state is ConnectionState.PAUSED:
            self._controller.resume()
        elif self._controller.state is ConnectionState.DISCONNECTED:
            self._controller.connect()
        self._supervisor.restart()
        self._refresh_tray()

    def disconnect(self) -> None:
        self._controller.disconnect()
        self._supervisor.stop()
        self._refresh_tray()

    def quit(self) -> None:
        """Graceful shutdown: stop the Resident, release the single instance."""
        self._quit.set()
        self._controller.disconnect()
        self._supervisor.stop()

    # -- process lifecycle --------------------------------------------------
    def _watch_quit_event(self) -> None:
        while not self._quit.is_set():
            if self._quit_signal.wait(0.5):
                self.quit()
                return

    def run(self) -> int:
        """Start the tray. Returns the process exit code.

        0 = clean quit, 3 = another instance already owns this PC.
        """
        if not self._single.acquire():
            return 3
        self._quit_signal.open()
        try:
            if sys.platform == "win32":
                from .tray import ConnectTray  # noqa: PLC0415

                self._tray = ConnectTray(
                    state_source=lambda: self._controller.state,
                    actions=self.actions(),
                    web_url=WEB_URL,
                )
                self._tray.create()
                watcher = threading.Thread(
                    target=self._watch_quit_event, name="claw-connect-quit", daemon=True
                )
                watcher.start()
                self._tray.run()
            else:
                # Non-Windows developer/CI host: keep the process alive until
                # a quit is requested so the offline lifecycle can be driven.
                self._watch_quit_event()
        finally:
            if not self._quit.is_set():
                self.quit()
            self._supervisor.stop()
            self._single.release()
        return 0

    def actions(self) -> dict[str, Callable[[], None]]:
        return {
            ACTION_OPEN_WEB: self.open_web,
            ACTION_TOGGLE_PAUSE: self.toggle_pause,
            ACTION_RECONNECT: self.reconnect,
            ACTION_DISCONNECT: self.disconnect,
            ACTION_QUIT: self.quit,
        }

    def _refresh_tray(self) -> None:
        if self._tray is not None:
            self._tray.refresh()
