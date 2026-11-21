"""#8193 — local Mesh Agent self-check and bounded self-recovery.

All side effects are injected: the real runner supplies Windows process/service
probes and actions, tests supply fakes. A check never waits on a real clock in
tests; ``now`` is always injected. The module never imports or changes the
executor, MeshCentral settings or the helper updater.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

#: One notice per episode, and a bounded number of service restarts per day.
DEFAULT_COOLDOWN_SECONDS = 600.0
DEFAULT_MAX_RESTARTS_PER_DAY = 2
DEFAULT_STALE_SHELL_AGE_SECONDS = 900.0


@dataclass(frozen=True, slots=True)
class Shell:
    pid: int
    age_seconds: float
    cpu_seconds: float
    wait_state: str = "Wait"


@dataclass(frozen=True, slots=True)
class Health:
    service_running: bool
    connected: bool
    last_command_at: float | None
    shells: tuple[Shell, ...] = ()

    def stale(self, now: float, max_age: float) -> tuple[Shell, ...]:
        return tuple(shell for shell in self.shells if shell.age_seconds >= max_age)

    def responsive(self, now: float, max_age: float) -> bool:
        if not self.service_running or not self.connected:
            return False
        if self.last_command_at is None or now - self.last_command_at > max_age:
            return False
        return not self.stale(now, max_age)


@dataclass(frozen=True, slots=True)
class Recovery:
    action: str
    detail: str
    at: float
    node: str
    shells_stopped: tuple[int, ...] = ()


@dataclass
class SelfHealer:
    """Decide and execute one bounded recovery attempt.

    ``probe`` is called before and after each action so a successful shell
    cleanup avoids a needless service restart. ``restart_allowed`` is checked
    at decision time; a machine without the right never gets a restart call.
    """

    now: Callable[[], float]
    probe: Callable[[], Health]
    stop_shell: Callable[[int], bool]
    restart_service: Callable[[], bool]
    notify: Callable[[Recovery], None] = lambda recovery: None
    node: str = "pc"
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    max_restarts_per_day: int = DEFAULT_MAX_RESTARTS_PER_DAY
    stale_age_seconds: float = DEFAULT_STALE_SHELL_AGE_SECONDS
    restart_allowed: Callable[[], bool] = lambda: False
    _last_action_at: float = field(default=-10**18, init=False, repr=False)
    _restarts: list[float] = field(default_factory=list, init=False, repr=False)

    def _recovery(self, action: str, detail: str, shells: tuple[int, ...] = ()) -> Recovery:
        moment = self.now()
        result = Recovery(action, detail, moment, self.node, shells)
        if action not in ("none", "cooldown"):
            self._last_action_at = moment
        if action != "none":
            self.notify(result)
        return result

    def run_once(self) -> Recovery:
        moment = self.now()
        health = self.probe()
        if health.responsive(moment, self.stale_age_seconds):
            return self._recovery("none", "responsive")
        if moment - self._last_action_at < self.cooldown_seconds:
            return self._recovery("cooldown", "recent action; no repeat")

        stale = health.stale(moment, self.stale_age_seconds)
        if stale:
            stopped = tuple(pid for pid in (shell.pid for shell in stale)
                            if self.stop_shell(pid))
            if stopped and self.probe().responsive(self.now(), self.stale_age_seconds):
                return self._recovery("shell_stopped", "stale shell cleared", stopped)

        same_day = [stamp for stamp in self._restarts if moment - stamp < 86_400]
        if len(same_day) >= self.max_restarts_per_day:
            return self._recovery("limit", "daily restart cap reached")
        if not self.restart_allowed():
            return self._recovery("notify_only", "restart permission unavailable")
        if not self.restart_service():
            return self._recovery("notify_only", "restart call refused")
        self._restarts.append(moment)
        return self._recovery("restarted", "Mesh Agent restarted")




def report_recovery(recovery, *, opener=None) -> bool:
    """Report one self-recovery through the existing #8142 agent_stall path.

    The title carries the action and result; no private id, key or command
    output is sent. ``opener`` is injected for tests.
    """

    from .local_agent_mesh_stall_watch import StallNotice, loopback_notify, source_id

    notice = StallNotice(
        node=recovery.node,
        last_success=None,
        failures=1,
        suspicion_start=recovery.at,
        title=f"PC 자가 복구: {recovery.node} {recovery.action} {recovery.detail}",
        source_id=source_id("selfheal-" + recovery.node, recovery.at),
        guide="",
    )
    return loopback_notify(notice, origin=_loopback_origin(), opener=opener)


def _loopback_origin():
    import os
    return os.environ.get("PADIEM_MESH_CHAT_ORIGIN", "http://127.0.0.1:8788")




def windows_probe():
    """Read-only Windows probe for the real runner (never called in tests)."""

    import json
    import subprocess
    import time

    def ps(script):
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""

    running = ps("(Get-Service 'Mesh Agent' -ErrorAction SilentlyContinue).Status") == "Running"
    mesh = ps("(Get-Process MeshAgent -ErrorAction SilentlyContinue | "
              "Select-Object -First 1 -ExpandProperty Id)")
    connected = bool(mesh and mesh.isdigit() and ps(
        "(Get-NetTCPConnection -OwningProcess %s -State Established -ErrorAction SilentlyContinue | "
        "Measure-Object).Count" % mesh).isdigit() and ps(
        "(Get-NetTCPConnection -OwningProcess %s -State Established -ErrorAction SilentlyContinue | "
        "Measure-Object).Count" % mesh) != "0")
    moment = time.time()
    raw = ps(
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'powershell.exe' -and "
        "$_.CommandLine -like '*-command -*' } | Select-Object ProcessId,CreationDate | "
        "ConvertTo-Json -Compress"
    )
    shells: list[Shell] = []
    try:
        rows = json.loads(raw) if raw else []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            created = str(row.get("CreationDate", ""))
            stamp = created.split(".")[0]
            try:
                from datetime import datetime
                born = datetime.fromisoformat(stamp).timestamp()
            except ValueError:
                continue
            shells.append(Shell(pid=int(row["ProcessId"]), age_seconds=max(0.0, moment - born),
                                cpu_seconds=0.0, wait_state="Wait"))
    except (ValueError, TypeError, KeyError):
        pass
    return Health(service_running=running, connected=connected,
                  last_command_at=None, shells=tuple(shells))


def windows_stop_shell(pid: int) -> bool:
    import subprocess

    result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True, timeout=20, check=False)
    return result.returncode == 0


def windows_restart_service() -> bool:
    import subprocess

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         'Restart-Service "Mesh Agent"'],
        capture_output=True, timeout=60, check=False,
    )
    return result.returncode == 0


def report_result(recovery) -> None:
    """Send the bounded result to both existing ops paths; never raises."""

    try:
        report_recovery(recovery)
    except Exception:
        pass
    try:
        import json
        import os
        import urllib.request

        key = os.environ.get("PADIEM_OPS_NOTIFY_KEY_PC", "")
        if not key:
            return
        body = json.dumps({
            "node": recovery.node, "at": recovery.at, "action": recovery.action,
            "detail": recovery.detail, "result": "ok" if recovery.action in
            ("shell_stopped", "restarted", "none") else "limited",
        }).encode("utf-8")
        request = urllib.request.Request(
            _loopback_origin().rstrip("/") + "/api/ops/pc/self-heal",
            data=body, method="POST",
            headers={"content-type": "application/json", "X-Padiem-Ops-Notify-Key": key},
        )
        with urllib.request.urlopen(request, timeout=3):
            return
    except Exception:
        return


def run_loop(interval_seconds: float = 300.0) -> None:
    """Scheduled-task entry: check on a fixed cadence, never restart without opt-in."""

    import os
    import time

    if os.environ.get("PADIEM_PC_SELF_HEAL", "").strip().lower() not in ("1", "true", "on"):
        return
    healer = SelfHealer(now=time.time, probe=windows_probe,
                        stop_shell=windows_stop_shell,
                        restart_service=windows_restart_service,
                        notify=report_result,
                        restart_allowed=lambda: os.environ.get(
                            "PADIEM_PC_SELF_HEAL_RESTART", "").strip().lower()
                        in ("1", "true", "on"))
    while True:
        try:
            healer.run_once()
        except Exception:
            pass
        time.sleep(interval_seconds)

if __name__ == "__main__":
    run_loop()


__all__ = ["Health", "Recovery", "SelfHealer", "Shell",
           "DEFAULT_COOLDOWN_SECONDS", "DEFAULT_MAX_RESTARTS_PER_DAY",
           "DEFAULT_STALE_SHELL_AGE_SECONDS", "report_recovery", "run_loop"]
