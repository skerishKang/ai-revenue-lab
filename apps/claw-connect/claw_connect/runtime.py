"""Claw Connect application assembly (#4139 S1).

Wires the pieces together in one process: single-instance guard, gated
autostart, connection state, the supervised existing Resident, the tray and a
local quit event so ``claw-connect stop`` can end a running tray.

Nothing here selects a model, builds a Broker or approves a task. Connect is
a supervising UI over the one existing local runner.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import (
    AUTOSTART_RUN_VALUE_NAME,
    CONNECT_PRODUCT,
    CONNECT_VERSION,
    SINGLE_INSTANCE_MUTEX,
    WEB_URL,
)
from .autostart import Autostart, AutostartOutcome, AutostartRefused, start_command
from .connection import ConnectionController, ConnectionState
from .enrollment import ConnectorEnrollment
from .menu_model import (
    ACTION_DISCONNECT,
    ACTION_LOGIN,
    ACTION_OPEN_WEB,
    ACTION_QUIT,
    ACTION_RECONNECT,
    ACTION_AUTOSTART_ON,
    ACTION_AUTOSTART_OFF,
    ACTION_TOGGLE_PAUSE,
)
from .resident_supervisor import (
    ResidentLaunchRefused,
    ResidentSupervisor,
    default_resident_command,
)
from .resident_launch import ResidentLaunchPlan, plan_resident_launch
from .resident_path import resident_src_root
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
        enrollment: ConnectorEnrollment | None = None,
    ) -> None:
        self._autostart = autostart or Autostart(AUTOSTART_RUN_VALUE_NAME, autostart_store)
        self._controller = ConnectionController(probe)
        self._enrollment = enrollment or ConnectorEnrollment()
        self._state_dir = self._enrollment.state_dir
        from .pause_preference import is_paused
        self._user_paused = is_paused(self._state_dir)
        # S2: the supervised process is the one existing kagent Resident, never a
        # placeholder. The deployment pins the source root (installer file or
        # CLAW_RESIDENT_SRC); when it does not, the canonical module name is used
        # as-is so the interpreter resolves it rather than this code guessing.
        self._supervisor = supervisor or ResidentSupervisor(
            resident_command
            or default_resident_command(
                src_root=resident_src_root(state_dir=self._state_dir)
            ),
            # #4139 STEP 3: resolved at every start, so a restart picks up the
            # current committed enrollment instead of a construction-time
            # snapshot, and so the Resident is never launched without the
            # canonical Broker boundary it reads from these exact keys.
            env=self._resident_environment,
        )
        self._single = SingleInstance(SINGLE_INSTANCE_MUTEX)
        self._quit_signal = QuitSignal(QUIT_EVENT_NAME)
        self._offer_signal = QuitSignal("PadiemClawConnect.CustomerOffer.v1")
        self._offer_lock = threading.Lock()
        self._offer_attempted = False
        self._offer_running = False
        self._offer_failure: str | None = None
        self._offer_stage = "not_started"
        self._tray: Any = None
        self._quit = threading.Event()

    @property
    def enrollment(self) -> ConnectorEnrollment:
        return self._enrollment

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

    def reconcile_autostart(self) -> AutostartOutcome | None:
        """Only a committed live credential may register Windows startup.

        An owner's durable OFF remains enforceable even without credentials.
        An unregistered machine still opens its normal tray for login.
        """
        try:
            return self._autostart.register_after_install(
                start_command(), self._enrollment.committed_record()
            )
        except AutostartRefused:
            return None

    def resident_launch_plan(self) -> tuple[ResidentLaunchPlan | None, str]:
        """The canonical launch configuration for the supervised Resident.

        Never mints a device identity: a damaged or absent committed record is
        a refusal, not a reason to create one.
        """
        try:
            record = self._enrollment.committed_record()
        except Exception:
            return None, "enrollment_record_unreadable"
        if getattr(sys, "frozen", False):
            from .installed_runtime import installed_resident_environ
            import os
            return plan_resident_launch(
                record=record,
                environ=installed_resident_environ(
                    state_dir=self._state_dir, environ=os.environ,
                ),
            )
        return plan_resident_launch(record=record)

    def resident_launch_reason(self) -> str:
        """Why the supervised Resident is or is not launchable, evaluated now.

        Read-only and side-effect free: it never spawns a process and never
        mints a device identity, so it is safe to ask from ``status()``.
        """
        return self.resident_launch_plan()[1]

    def _resident_environment(self) -> dict[str, str] | None:
        """Resolved at each start. ``None`` means "do not launch"."""
        plan, _reason = self.resident_launch_plan()
        return plan.environment() if plan is not None else None

    def status(self) -> dict[str, Any]:
        """The observable state. Never claims a state that was not observed."""
        return {
            "product": CONNECT_PRODUCT,
            "version": CONNECT_VERSION,
            "state": self.connector_status().value,
            "resident_running": self._supervisor.is_running(),
            "resident_launch_reason": self.resident_launch_reason(),
            "autostart_enabled": self._autostart.is_enabled(),
            "single_instance": self._single.held,
            "enrollment": self._enrollment.status_snapshot(),
        }

    def connector_status(self) -> ConnectionState:
        """Operator-visible Connector state, projected from device facts only.

        ``CONNECTED`` requires both a server-projected ``online`` lifecycle and
        an observed live session; a locally resumed controller alone is only
        reported as connecting or offline.
        """
        return self._enrollment.project_state(
            paused=self._user_paused or self._controller.state is ConnectionState.PAUSED,
            connected=self._controller.state is ConnectionState.CONNECTED,
        )

    def status_json(self) -> str:
        return json.dumps(self.status(), ensure_ascii=False, sort_keys=True)

    # -- tray actions ------------------------------------------------------
    def open_web(self) -> None:
        import webbrowser  # noqa: PLC0415

        webbrowser.open(WEB_URL)

    def login(self) -> None:
        """Start the reviewed PADIEM login / PC-registration consent flow.

        Opens the official PADIEM authentication surface and returns the URL.
        The Connector never renders a credential form, never stores a password
        and never reads a browser cookie: the reviewed session issues the
        pairing code this device redeems with its own Broker device id.
        """
        url = self._enrollment.begin_login()
        try:
            import webbrowser  # noqa: PLC0415

            webbrowser.open(url)
        except Exception:
            pass
        return url  # type: ignore[return-value]

    def toggle_pause(self) -> None:
        """Persist user pause separately from Windows logon-autostart OFF."""
        from .pause_preference import set_paused

        if self._user_paused:
            set_paused(self._state_dir, False)
            self._user_paused = False
            if self._controller.state is ConnectionState.PAUSED:
                self._controller.resume()
            if self._can_start_resident():
                try:
                    self._supervisor.start()
                except ResidentLaunchRefused:
                    pass
        else:
            set_paused(self._state_dir, True)
            self._user_paused = True
            if self._controller.state is ConnectionState.CONNECTED:
                self._controller.pause()
            self._supervisor.stop()
        self._refresh_tray()

    def _can_start_resident(self) -> bool:
        # Reuse the credential validity contract from guarded logon startup.
        # A tray action is not an alternative enrollment/consent authority.
        # A live credential is necessary but not sufficient: the Resident also
        # needs the canonical Broker boundary, and a child launched without it
        # refuses at once, so this gate is what stops a doomed spawn.
        try:
            return self._resident_environment() is not None
        except Exception:
            return False

    def start_registered_resident(self) -> bool:
        """Bring the supervised Resident up on the committed enrollment.

        This is what makes a tray start actually reach a task-receiving
        Resident. It refuses rather than launching an unconfigurable child, and
        it never overrides the owner's pause or opt-out.
        """
        plan, reason = self.resident_launch_plan()
        if plan is None:
            return False
        if self._user_paused or self._controller.state is ConnectionState.PAUSED:
            return False
        try:
            self._supervisor.start()
        except ResidentLaunchRefused:
            # The provider declined between the plan above and the spawn: no
            # child was created, so this must not report a start.
            return False
        return True

    def reconnect(self) -> None:
        # No manually triggered Resident without valid committed enrollment.
        # A user who disabled boot autostart can still reconnect on demand.
        if not self._can_start_resident():
            self._refresh_tray()
            return
        if self._user_paused:
            from .pause_preference import set_paused
            set_paused(self._state_dir, False)
            self._user_paused = False
        if self._controller.state is ConnectionState.PAUSED:
            self._controller.resume()
        elif self._controller.state is ConnectionState.DISCONNECTED:
            self._controller.connect()
        try:
            self._supervisor.restart()
        except ResidentLaunchRefused:
            # Refused between the gate above and the spawn. ``restart`` stopped
            # any previous child first, so the honest end state is "no
            # Resident", which is what the tray reports.
            pass
        self._refresh_tray()

    def turn_autostart_on(self) -> None:
        """Tray opt-in; must have a committed credential first."""
        try:
            self._autostart.enable(
                start_command(), self._enrollment.committed_record(),
            )
        except AutostartRefused:
            pass
        self._refresh_tray()

    def turn_autostart_off(self) -> None:
        """Durable owner opt-out without removing the live session."""
        try:
            self._autostart.disable()
        except AutostartRefused:
            # Never overwrite another application Run value.
            pass
        self._refresh_tray()

    def disconnect(self) -> None:
        from .pause_preference import set_paused
        set_paused(self._state_dir, True)
        self._user_paused = True
        self._controller.disconnect()
        self._supervisor.stop()
        self._refresh_tray()

    def quit(self) -> None:
        """Graceful shutdown: stop the Resident, release the single instance."""
        self._quit.set()
        self._controller.disconnect()
        self._supervisor.stop()
        # LOCAL2 fix #4420: external stop must also end the Win32 tray
        # message loop, otherwise PumpMessages() blocks forever. Posting
        # WM_DESTROY is thread-safe, so calling from the watcher thread is safe.
        try:
            self._tray.quit()
        except Exception:
            pass

    # -- process lifecycle --------------------------------------------------
    def signal_customer_offer(self) -> bool:
        """Existing web launch activates the already-running tray, no URL data."""
        return self._offer_signal.signal()

    def _record_offer_stage(self, stage: str, failure: str | None = None) -> None:
        """Persist only fixed phase codes; never frames, refs, or credentials."""
        from pathlib import Path
        import os
        import tempfile

        stages = frozenset({
            "not_started", "offer_started", "ready_received",
            "owner_page_open_requested", "owner_link_confirmed",
            "credential_once_received", "dpapi_store_confirmed",
            "install_ack_sent", "install_ack_accepted", "enrollment_published",
        })
        if stage not in stages:
            return
        self._offer_stage = stage
        try:
            root = Path(self._state_dir)
            root.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".offer-stage-", dir=root)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as output:
                    # A fixed reason class only, never an exception's raw text.
                    json.dump({
                        "stage": stage, "result": (
                            "failed" if failure else (
                                "complete" if stage == "enrollment_published"
                                else "in_progress"
                            )
                        ),
                        "reason": (
                            "offer_refused" if failure else None
                        ),
                    }, output)
                os.replace(temporary, root / "customer-offer-stage.json")
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError:
            pass

    def _start_customer_offer_once(self, *, explicit: bool = False) -> None:
        """One in-flight PC offer; a new explicit request may retry after failure."""
        if self._quit.is_set():
            return
        try:
            if self._enrollment.committed_record() is not None:
                return
        except Exception:
            self._offer_failure = "enrollment_record_unreadable"
            return
        # Explicit reconnect never clears the customer's persisted pause/OFF.
        if self._user_paused or (self._autostart.preference() == "off" and not explicit):
            return
        with self._offer_lock:
            if self._offer_running:
                return
            if self._offer_attempted and not (explicit and self._offer_failure is not None):
                return
            self._offer_attempted = True
            self._offer_running = True
            self._offer_failure = None
        self._record_offer_stage("offer_started")
        try:
            threading.Thread(
                target=self._enroll_customer_in_thread,
                name="padiem-customer-first-offer",
                daemon=True,
            ).start()
        except RuntimeError:
            with self._offer_lock:
                self._offer_running = False
                self._offer_failure = "customer_offer_thread_unavailable"
            self._record_offer_stage(self._offer_stage, failure="thread_unavailable")

    def _enroll_customer_in_thread(self) -> None:
        import asyncio
        from .customer_enrollment import enroll_customer_pending_offer
        from .device_wss_enrollment import DeviceSessionRefused

        failure: str | None = None
        try:
            asyncio.run(enroll_customer_pending_offer(enrollment=self._enrollment, on_stage=self._record_offer_stage))
            self._record_offer_stage("enrollment_published")
            self.reconcile_autostart()
            if not self._quit.is_set():
                self.start_registered_resident()
        except DeviceSessionRefused as exc:
            failure = str(exc)
        except Exception:
            # No socket data, code, credential, or owner identity in diagnostics.
            failure = "customer_offer_unavailable"
        finally:
            with self._offer_lock:
                self._offer_failure = failure
                self._offer_running = False
            if failure is not None:
                self._record_offer_stage(self._offer_stage, failure=failure)
            self._refresh_tray()

    def _watch_quit_event(self) -> None:
        next_restart_at = time.monotonic() + 15.0
        while not self._quit.is_set():
            if self._quit_signal.wait(0.5):
                self.quit()
                return
            if self._offer_signal.wait(0):
                if self._enrollment.committed_record() is not None:
                    self.reconnect()
                else:
                    self._start_customer_offer_once(explicit=True)
            # A lost Resident process is not a user OFF decision. A bounded
            # supervisor restart reuses the committed DPAPI binding, never a
            # second pairing or fabricated credential.
            if time.monotonic() >= next_restart_at:
                if not self._user_paused and not self._supervisor.is_running():
                    self.start_registered_resident()
                next_restart_at = time.monotonic() + 15.0

    def run(self, *, explicit_connect: bool = False) -> int:
        """Start the tray. Returns the process exit code.

        0 = clean quit, 3 = another instance already owns this PC.
        """
        if not self._single.acquire():
            return 3
        self._quit_signal.open()
        self._offer_signal.open()
        try:
            self.reconcile_autostart()
            # #4139 STEP 3: a tray start must also bring the one supervised
            # Resident up, on the committed enrollment. Offline or unconfigured
            # is reported through ``resident_launch_reason`` instead of a
            # silently absent Resident.
            if explicit_connect or (self._autostart.preference() != "off" and not self._user_paused):
                self.start_registered_resident()
            # Following the already selected web Computer Connect action,
            # setup bootstraps its offer without an operator command or ID.
            if sys.platform == "win32" and getattr(sys, "frozen", False):
                self._start_customer_offer_once(explicit=explicit_connect)
            if sys.platform == "win32":
                from .tray import ConnectTray  # noqa: PLC0415

                self._tray = ConnectTray(
                    state_source=lambda: self.connector_status(),
                    actions=self.actions(),
                    autostart_source=self._autostart.is_enabled,
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
            ACTION_LOGIN: self.login,
            ACTION_TOGGLE_PAUSE: self.toggle_pause,
            ACTION_RECONNECT: self.reconnect,
            ACTION_AUTOSTART_ON: self.turn_autostart_on,
            ACTION_AUTOSTART_OFF: self.turn_autostart_off,
            ACTION_DISCONNECT: self.disconnect,
            ACTION_QUIT: self.quit,
        }

    def _refresh_tray(self) -> None:
        if self._tray is not None:
            self._tray.refresh()
