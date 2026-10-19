#!/usr/bin/env python3
"""Supervise the COM2-local PADIEM runtime (issue #5115).

COM2 is the intended canonical runtime for Chat, Claw, B66, the P01 Engine and
the B14 Router. The services themselves already have start scripts and an
existing scheduled launcher:

* ``infrastructure/start-b14-release.ps1``   -> B14 Router on 127.0.0.1:18717
* ``b62-chat-api/start-b62-release.ps1``     -> Chat/Claw API on 127.0.0.1:18764
* ``p01-ai-engine/start-p01-local.ps1``      -> P01 Engine on 127.0.0.1:18731

This module does not replace them. It adds the missing operational layer:

1. ``status``  - listener, HTTP health and contract fields, loopback binding.
2. ``ensure``  - start only the components that are not listening, then wait
   for health. A running listener is never killed, even when unhealthy,
   because it may belong to the existing OnLogon/Watchdog tasks.
3. ``restart`` / ``stop`` - act only on processes this supervisor started and
   recorded in ``.com2-runtime/managed.json``.
4. ``verify``  - per-product readiness and loopback-only proof.
5. ``install-task`` - register a 5-minute task with the same interactive,
   limited principal as the existing ``PADIEM-*`` tasks.

Safety properties:
* Loopback origins only; no public listener is created here.
* No Cloudflare, D1, R2, DNS or secret mutation.
* Process output goes to local log files; status JSON carries no secret value.
* Automatic restart is limited to supervisor-managed processes and is rate
  limited so a crash loop cannot hammer the machine.
* A single-instance lock prevents overlapping scheduled runs.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

KIND = "PADIEM_COM2_RUNTIME_V1"
DEFAULT_ROOT = Path(os.environ.get("PADIEM_COM2_SERVERS_ROOT", r"D:\PADIEM-Servers"))
STATE_DIR_NAME = ".com2-runtime"
LOCK_NAME = "supervisor.lock"
STATE_NAME = "managed.json"
STATUS_NAME = "status.json"
DEFAULT_TASK_NAME = "PADIEM-COM2-Runtime-Supervisor"


@dataclass(frozen=True)
class Component:
    name: str
    kind: str
    port: int | None
    start_script: str | None
    health_path: str | None
    source_paths: tuple[str, ...] = ()


COMPONENTS: tuple[Component, ...] = (
    Component("b14", "http", 18717, r"infrastructure\start-b14-release.ps1", "/health"),
    Component("b62", "http", 18764, r"b62-chat-api\start-b62-release.ps1", "/health"),
    Component("p01", "http", 18731, r"p01-ai-engine\start-p01-local.ps1", "/internal/v1/health"),
    Component(
        "b66",
        "library",
        None,
        None,
        None,
        (r"b66-quote-adapter\source\app\file_intake.py", r"b66-pdf-renderer\source\worker.py"),
    ),
)

PRODUCTS: dict[str, tuple[str, ...]] = {
    "chat": ("b62",),
    "claw": ("b62",),
    "engine": ("p01",),
    "quote": ("b66",),
}

CONTRACTS: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "b14": lambda body: body.get("status") == "ok" and body.get("app") == "korean-ai-platform",
    "b62": lambda body: (
        body.get("status") == "ok"
        and body.get("app") == "padiem-chat"
        and body.get("runtime") == "b14"
    ),
    "p01": lambda body: (
        body.get("status") == "ok"
        and body.get("service") == "padiem-ai-engine"
        and body.get("completed_run") is True
        and body.get("streaming_run") is True
        and body.get("service_identity") == "required_for_all_non_health_routes"
    ),
}

_NETSTAT_LISTEN = re.compile(
    r"^\s*TCP\s+(?P<local>\S+)\s+\S+\s+LISTENING\s+(?P<pid>\d+)\s*$",
    re.IGNORECASE,
)


class RuntimeBusy(Exception):
    def __init__(self) -> None:
        super().__init__("supervisor_already_running")


class RuntimeError_(Exception):
    """Stable failure code; never carries captured output."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _state_dir(root: Path) -> Path:
    return Path(root) / STATE_DIR_NAME


def acquire_lock(root: Path, *, stale_minutes: float = 10.0, now: float | None = None) -> Path:
    directory = _state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / LOCK_NAME
    payload = {"pid": os.getpid(), "started_utc": _utc_now(), "kind": KIND}
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = now if now is not None else time.time()
            try:
                age_minutes = (current - lock.stat().st_mtime) / 60.0
            except OSError:
                raise RuntimeBusy()
            if age_minutes <= stale_minutes:
                raise RuntimeBusy()
            try:
                lock.unlink()
            except OSError:
                raise RuntimeBusy()
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return lock
    raise RuntimeBusy()


def release_lock(lock: Path) -> None:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("pid") == os.getpid():
        lock.unlink(missing_ok=True)


def load_state(root: Path) -> dict[str, Any]:
    path = _state_dir(root) / STATE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"kind": KIND, "components": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("components"), dict):
        return {"kind": KIND, "components": {}}
    return payload


def save_state(root: Path, state: Mapping[str, Any]) -> None:
    _write_json_atomic(_state_dir(root) / STATE_NAME, state)


def port_open(port: int, *, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_json(
    port: int,
    path: str,
    *,
    host: str = "127.0.0.1",
    timeout: float = 15.0,
) -> dict[str, Any]:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(262144)
    except urllib.error.HTTPError as error:
        return {"ok": False, "http_status": int(error.code), "body": None}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return {"ok": False, "http_status": None, "body": None}
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"ok": False, "http_status": status, "body": None}
    return {"ok": status == 200 and isinstance(body, dict), "http_status": status, "body": body}


def parse_listen_addresses(text: str, port: int) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in text.splitlines():
        match = _NETSTAT_LISTEN.match(line)
        if not match:
            continue
        local = match.group("local")
        if local.startswith("["):
            address, _, raw_port = local.rpartition(":")
            address = address.strip("[]")
        else:
            address, _, raw_port = local.rpartition(":")
        if not raw_port.isdigit() or int(raw_port) != port:
            continue
        found[address] = int(match.group("pid"))
    return found


def listener_addresses(port: int) -> dict[str, int] | None:
    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return parse_listen_addresses(completed.stdout or "", port)


def is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def contract_ok(component: Component, body: Mapping[str, Any] | None) -> bool:
    if body is None:
        return False
    check = CONTRACTS.get(component.name)
    return bool(check and check(body))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return str(pid) in (completed.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def default_launch(component: Component, root: Path, log_path: Path) -> int:
    if not component.start_script:
        raise RuntimeError_("component_has_no_start_script")
    script = Path(root) / component.start_script
    if not script.is_file():
        raise RuntimeError_("start_script_missing")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS makes powershell.exe -File exit before running here;
        # CREATE_NO_WINDOW keeps the console hidden without that side effect.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            cwd=str(script.parent),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    except OSError as error:
        raise RuntimeError_("start_script_unavailable") from error
    finally:
        handle.close()
    return int(process.pid)


def default_stop(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def _component_by_name(name: str, components: Sequence[Component]) -> Component:
    for component in components:
        if component.name == name:
            return component
    raise RuntimeError_("unknown_component")


def _health(component: Component, *, timeout: float) -> dict[str, Any]:
    assert component.port is not None and component.health_path is not None
    return http_json(component.port, component.health_path, timeout=timeout)


def _component_ready(
    component: Component,
    *,
    timeout: float,
    health_timeout: float,
) -> bool:
    assert component.port is not None
    if not port_open(component.port):
        return False
    result = _health(component, timeout=health_timeout)
    return bool(result["ok"] and contract_ok(component, result["body"]))


def _wait_ready(
    component: Component,
    *,
    timeout: float,
    health_timeout: float,
    poll: float = 1.0,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = now() + timeout
    while True:
        if _component_ready(component, timeout=timeout, health_timeout=health_timeout):
            return True
        if now() >= deadline:
            return False
        sleep(poll)


def _wait_port_closed(
    port: int,
    *,
    timeout: float,
    poll: float = 0.5,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = now() + timeout
    while port_open(port):
        if now() >= deadline:
            return False
        sleep(poll)
    return True


def _managed_entry(state: Mapping[str, Any], component: Component) -> dict[str, Any] | None:
    entry = state.get("components", {}).get(component.name)
    return entry if isinstance(entry, dict) else None


def _record_managed(
    state: dict[str, Any],
    component: Component,
    pid: int,
    *,
    restarted: bool,
) -> None:
    entry = {
        "pid": pid,
        "started_utc": _utc_now(),
        "start_script": component.start_script,
    }
    if restarted:
        entry["last_restart_utc"] = _utc_now()
        entry["last_restart_epoch"] = time.time()
    previous = state["components"].get(component.name)
    if isinstance(previous, dict) and previous.get("last_restart_epoch") and not restarted:
        entry["last_restart_epoch"] = previous["last_restart_epoch"]
        entry["last_restart_utc"] = previous.get("last_restart_utc")
    state["components"][component.name] = entry


def collect_status(
    root: Path,
    *,
    components: Sequence[Component] = COMPONENTS,
    state: Mapping[str, Any] | None = None,
    health_timeout: float = 15.0,
    address_reader: Callable[[int], dict[str, int] | None] | None = None,
    listener_check: Callable[[int], bool] = port_open,
) -> dict[str, Any]:
    loaded = state if state is not None else load_state(root)
    reader = address_reader if address_reader is not None else listener_addresses
    status_components: dict[str, Any] = {}
    issues: list[str] = []

    for component in components:
        if component.kind == "library":
            missing = [
                path for path in component.source_paths if not (Path(root) / path).is_file()
            ]
            status_components[component.name] = {
                "kind": "library",
                "ready": not missing,
                "missing": missing,
                "http_listener": False,
            }
            if missing:
                issues.append(f"{component.name}:source_missing")
            continue

        assert component.port is not None
        listening = listener_check(component.port)
        health = _health(component, timeout=health_timeout) if listening else None
        body = health["body"] if health else None
        contract = contract_ok(component, body if isinstance(body, dict) else None)
        entry = _managed_entry(loaded, component)
        managed = bool(entry and _pid_alive(int(entry.get("pid", 0))))
        addresses = reader(component.port) if listening else {}
        loopback = None
        if addresses:
            loopback = all(is_loopback(address) for address in addresses)
        healthy = listening and bool(health and health["ok"]) and contract
        if listening and loopback is False:
            healthy = False
            issues.append(f"{component.name}:non_loopback_listener")
        if listening and not contract:
            issues.append(f"{component.name}:health_contract_failed")
        if not listening:
            issues.append(f"{component.name}:not_listening")

        status_components[component.name] = {
            "kind": "http",
            "port": component.port,
            "listening": listening,
            "health": bool(health and health["ok"]),
            "contract": contract,
            "http_status": health["http_status"] if health else None,
            "loopback_only": loopback,
            "managed": managed,
            "pid": entry.get("pid") if managed and entry else None,
            "healthy": healthy,
        }

    products: dict[str, str] = {}
    for product, required in PRODUCTS.items():
        states = [status_components.get(name, {}).get("healthy") for name in required]
        if product == "quote":
            ready = status_components.get("b66", {}).get("ready") is True
            products[product] = "library_only" if ready else "source_missing"
            continue
        if required and all(value is True for value in states):
            products[product] = "ready"
        else:
            products[product] = "degraded"

    http_components = [c for c in components if c.kind == "http"]
    healthy_all = all(
        status_components.get(component.name, {}).get("healthy") is True
        for component in http_components
    )

    return {
        "kind": KIND,
        "checked_utc": _utc_now(),
        "root": str(root),
        "healthy": healthy_all,
        "components": status_components,
        "products": products,
        "issues": sorted(set(issues)),
    }


def ensure(
    root: Path,
    *,
    components: Sequence[Component] = COMPONENTS,
    timeout: float = 90.0,
    health_timeout: float = 15.0,
    restart_unhealthy: bool = True,
    restart_cooldown_seconds: float = 300.0,
    launcher: Callable[[Component, Path, Path], int] | None = None,
    stopper: Callable[[int], None] | None = None,
    address_reader: Callable[[int], dict[str, int] | None] | None = None,
    listener_check: Callable[[int], bool] = port_open,
) -> dict[str, Any]:
    launch = launcher if launcher is not None else default_launch
    stop = stopper if stopper is not None else default_stop
    lock = acquire_lock(root)
    actions: list[dict[str, Any]] = []
    try:
        state = load_state(root)
        state.setdefault("kind", KIND)
        state.setdefault("components", {})
        for component in components:
            if component.kind != "http":
                continue
            assert component.port is not None
            listening = listener_check(component.port)
            ready = listening and _component_ready(
                component,
                timeout=timeout,
                health_timeout=health_timeout,
            )
            if ready:
                actions.append({"component": component.name, "action": "already_healthy"})
                continue

            entry = _managed_entry(state, component)
            managed = bool(entry and _pid_alive(int(entry.get("pid", 0))))
            if managed:
                last_restart = float(entry.get("last_restart_epoch", 0.0)) if entry else 0.0
                if not restart_unhealthy:
                    actions.append({"component": component.name, "action": "restart_disabled"})
                    continue
                if time.time() - last_restart < restart_cooldown_seconds:
                    actions.append({"component": component.name, "action": "restart_cooldown"})
                    continue
                stop(int(entry["pid"]))  # type: ignore[index]
                closed = _wait_port_closed(component.port, timeout=15.0)
                actions.append(
                    {
                        "component": component.name,
                        "action": "restarted",
                        "port_released": closed,
                    }
                )
                if not closed:
                    continue
                state["components"].pop(component.name, None)
            elif listening:
                actions.append(
                    {"component": component.name, "action": "unmanaged_unhealthy_untouched"}
                )
                continue
            else:
                actions.append({"component": component.name, "action": "started"})

            try:
                pid = launch(component, root, _state_dir(root) / "logs" / f"{component.name}.log")
            except RuntimeError_ as error:
                actions[-1]["result"] = str(error)
                continue
            _record_managed(
                state,
                component,
                pid,
                restarted=actions[-1]["action"] == "restarted",
            )
            save_state(root, state)
            ready_after = _wait_ready(
                component,
                timeout=timeout,
                health_timeout=health_timeout,
            )
            actions[-1]["ready"] = ready_after

        save_state(root, state)
        status = collect_status(
            root,
            components=components,
            state=state,
            health_timeout=health_timeout,
            address_reader=address_reader,
            listener_check=listener_check,
        )
        status["actions"] = actions
        _write_json_atomic(_state_dir(root) / STATUS_NAME, status)
        return status
    finally:
        release_lock(lock)


def restart(
    root: Path,
    name: str,
    *,
    components: Sequence[Component] = COMPONENTS,
    timeout: float = 90.0,
    health_timeout: float = 15.0,
    launcher: Callable[[Component, Path, Path], int] | None = None,
    stopper: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    component = _component_by_name(name, components)
    if component.kind != "http" or component.port is None:
        raise RuntimeError_("component_has_no_listener")
    launch = launcher if launcher is not None else default_launch
    stop = stopper if stopper is not None else default_stop
    lock = acquire_lock(root)
    try:
        state = load_state(root)
        entry = _managed_entry(state, component)
        if not entry:
            raise RuntimeError_("not_supervised")
        pid = int(entry.get("pid", 0))
        if not _pid_alive(pid):
            state["components"].pop(component.name, None)
            save_state(root, state)
            raise RuntimeError_("managed_process_not_alive")
        stop(pid)
        if not _wait_port_closed(component.port, timeout=20.0):
            raise RuntimeError_("port_not_released")
        new_pid = launch(component, root, _state_dir(root) / "logs" / f"{component.name}.log")
        _record_managed(state, component, new_pid, restarted=True)
        save_state(root, state)
        ready = _wait_ready(component, timeout=timeout, health_timeout=health_timeout)
        return {
            "kind": KIND,
            "component": component.name,
            "restarted": True,
            "pid": new_pid,
            "ready": ready,
        }
    finally:
        release_lock(lock)


def stop_component(
    root: Path,
    name: str,
    *,
    components: Sequence[Component] = COMPONENTS,
    stopper: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    component = _component_by_name(name, components)
    stop = stopper if stopper is not None else default_stop
    lock = acquire_lock(root)
    try:
        state = load_state(root)
        entry = _managed_entry(state, component)
        if not entry:
            raise RuntimeError_("not_supervised")
        pid = int(entry.get("pid", 0))
        stop(pid)
        state["components"].pop(component.name, None)
        save_state(root, state)
        return {"kind": KIND, "component": component.name, "stopped": True, "pid": pid}
    finally:
        release_lock(lock)


def verify(
    root: Path,
    *,
    components: Sequence[Component] = COMPONENTS,
    health_timeout: float = 15.0,
    address_reader: Callable[[int], dict[str, int] | None] | None = None,
    listener_check: Callable[[int], bool] = port_open,
) -> dict[str, Any]:
    status = collect_status(
        root,
        components=components,
        health_timeout=health_timeout,
        address_reader=address_reader,
        listener_check=listener_check,
    )
    checks: dict[str, Any] = {}
    passed = True
    for component in components:
        if component.kind != "http":
            continue
        observed = status["components"][component.name]
        loopback = observed["loopback_only"]
        check = {
            "listening": observed["listening"],
            "health": observed["health"],
            "contract": observed["contract"],
            "loopback_only": loopback,
        }
        if loopback is None:
            check["loopback_evidence"] = "unavailable"
        if not (
            observed["listening"]
            and observed["health"]
            and observed["contract"]
            and loopback is not False
        ):
            passed = False
        checks[component.name] = check

    quote = status["components"].get("b66", {})
    return {
        "kind": KIND,
        "verified_utc": _utc_now(),
        "root": str(root),
        "passed": passed,
        "checks": checks,
        "products": status["products"],
        "b66": {
            "source_ready": quote.get("ready") is True,
            "http_listener": False,
            "note": "B66 runs as source/library on COM2; no local HTTP route is started",
        },
        "issues": status["issues"],
    }


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def install_task(
    root: Path,
    *,
    script_path: Path,
    task_name: str = DEFAULT_TASK_NAME,
    interval_minutes: int = 5,
    dry_run: bool = False,
    force: bool = False,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    directory = _state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    launcher_path = directory / "run-supervisor.ps1"
    log_path = directory / "supervisor.log"
    launcher = "\n".join(
        [
            "$ErrorActionPreference='Stop'",
            f"Set-Location {_powershell_quote(str(root))}",
            "try {",
            (
                f"  $output = & py -3 {_powershell_quote(str(script_path))} ensure "
                f"--root {_powershell_quote(str(root))} 2>&1"
            ),
            "  $code = $LASTEXITCODE",
            "} catch {",
            "  $output = @($_ | Out-String)",
            "  $code = 1",
            "}",
            "if ($code -ne 0) {",
            (
                "  ('[{0}] ensure exit={1}' -f "
                "(Get-Date).ToUniversalTime().ToString('o'), $code)"
                f" | Add-Content {_powershell_quote(str(log_path))}"
            ),
            f"  $output | Add-Content {_powershell_quote(str(log_path))}",
            "}",
            "",
        ]
    )
    command = [
        "schtasks",
        "/Create",
        "/SC",
        "MINUTE",
        "/MO",
        str(interval_minutes),
        # Offset from the existing PADIEM watchdog start boundary so the two
        # five-minute schedules do not race on a missing service.
        "/ST",
        "00:01",
        "/TN",
        task_name,
        "/TR",
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{launcher_path}"',
        "/IT",
        "/RL",
        "LIMITED",
    ]
    if force:
        command.append("/F")
    result: dict[str, Any] = {
        "kind": KIND,
        "task_name": task_name,
        "interval_minutes": interval_minutes,
        "launcher": str(launcher_path),
        "command": command,
        "dry_run": dry_run,
        "registered": False,
    }
    if dry_run:
        result["launcher_content"] = launcher
        return result
    launcher_path.write_text(launcher, encoding="utf-8")
    execute = runner or (
        lambda argv: subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    )
    completed = execute(command)
    result["exit"] = int(completed.returncode)
    if completed.returncode != 0:
        result["error"] = "schtasks_failed"
        result["stderr_tail"] = (completed.stderr or "").strip().splitlines()[-1:] or []
        return result
    result["registered"] = True
    return result


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(DEFAULT_ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status", parents=[common], help="read-only runtime status"
    )
    status_parser.add_argument("--health-timeout", type=float, default=15.0)

    ensure_parser = subparsers.add_parser(
        "ensure", parents=[common], help="start missing components"
    )
    ensure_parser.add_argument("--timeout", type=float, default=90.0)
    ensure_parser.add_argument("--health-timeout", type=float, default=15.0)
    ensure_parser.add_argument("--restart-cooldown", type=float, default=300.0)
    ensure_parser.add_argument("--no-restart", action="store_true")

    restart_parser = subparsers.add_parser(
        "restart", parents=[common], help="restart a supervised component"
    )
    restart_parser.add_argument("component")
    restart_parser.add_argument("--timeout", type=float, default=90.0)

    stop_parser = subparsers.add_parser(
        "stop", parents=[common], help="stop a supervised component"
    )
    stop_parser.add_argument("component")

    verify_parser = subparsers.add_parser(
        "verify", parents=[common], help="product readiness and loopback proof"
    )
    verify_parser.add_argument("--health-timeout", type=float, default=15.0)

    task_parser = subparsers.add_parser(
        "install-task", parents=[common], help="register the 5-minute supervisor task"
    )
    task_parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    task_parser.add_argument("--interval-minutes", type=int, default=5)
    task_parser.add_argument("--dry-run", action="store_true")
    task_parser.add_argument(
        "--force", action="store_true", help="replace an existing task with the same name"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "status":
            report = collect_status(root, health_timeout=args.health_timeout)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["healthy"] else 1
        if args.command == "ensure":
            report = ensure(
                root,
                timeout=args.timeout,
                health_timeout=args.health_timeout,
                restart_unhealthy=not args.no_restart,
                restart_cooldown_seconds=args.restart_cooldown,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["healthy"] else 1
        if args.command == "restart":
            report = restart(root, args.component, timeout=args.timeout)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("ready") else 1
        if args.command == "stop":
            report = stop_component(root, args.component)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "verify":
            report = verify(root, health_timeout=args.health_timeout)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["passed"] else 1
        if args.command == "install-task":
            report = install_task(
                root,
                script_path=Path(__file__).resolve(),
                task_name=args.task_name,
                interval_minutes=args.interval_minutes,
                dry_run=args.dry_run,
                force=args.force,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("registered") or args.dry_run else 1
    except RuntimeBusy:
        print(json.dumps({"kind": KIND, "status": "busy", "error": "supervisor_already_running"}))
        return 3
    except RuntimeError_ as error:
        print(json.dumps({"kind": KIND, "status": "error", "error": str(error)}))
        return 2
    except KeyboardInterrupt:
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
