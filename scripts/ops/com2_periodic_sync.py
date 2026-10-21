#!/usr/bin/env python3
"""Periodic read-only D1/R2 synchronization for the COM2 operational folder.

The runner reuses the existing COM2 scripts in ``--root``:

1. ``refresh_d1.py`` exports both D1 databases read-only and publishes a new
   integrity-checked local generation.
2. The existing inventory Worker (``inventory.mjs`` +
   ``wrangler.inventory.toml``) is started locally with remote R2 bindings and
   each bucket inventory is fetched through ``127.0.0.1``.
3. ``r2_sync.py --diff-only`` decides whether any object is new or changed.
   Only then does ``r2_sync.py`` copy the delta into a new verified generation.

Properties:
* A single-instance lock prevents overlapping runs. A stale lock is replaced
  after ``--stale-minutes``.
* An inventory page is accepted only when ``truncated`` is false and the
  declared count matches the object list. A partial fetch aborts before the
  R2 diff or copy step.
* No production D1 is restored and no R2 object is written or deleted. The
  only writes are local generations, inventories, logs and status files.
* The status JSON contains counts, exit codes and generation timestamps only.
  It never contains object keys, secret values or customer data.

Scheduling is delegated to the existing Windows Task Scheduler with the same
interactive user context as the other ``PADIEM-*`` tasks. ``install-task``
generates a launcher and registers it; ``--dry-run`` prints both without
changing the system.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

KIND = "PADIEM_COM2_PERIODIC_SYNC_V1"
LOCK_NAME = "scheduled-sync.lock"
STATUS_NAME = "scheduled-sync-status.json"
LOG_NAME = "scheduled-sync.log"
DEFAULT_TASK_NAME = "PADIEM-COM2-D1-R2-Sync"
DEFAULT_TASK_TIME = "04:20"
# #5484: the COM2 DPAPI secret store is the only Cloudflare credential path on
# that host. The D1 export already goes through it; the inventory Worker must
# too, because ``wrangler dev`` with a remote R2 binding opens a remote proxy
# session and fails with "You must be logged in to use wrangler dev in remote
# mode" when no credential is present.
DEFAULT_SECRET_STORE = r"D:\PADIEM-Servers\infrastructure\secret-store\store.py"
R2_BUCKETS = ("workspace", "b66", "media")
REQUIRED_LAYOUT = ("refresh_d1.py", "r2_sync.py", "inventory.mjs", "wrangler.inventory.toml")

_DIFF_LINE = re.compile(
    r"^DIFF\s+(?P<bucket>\S+)\s+.*NEW=(?P<new>\d+)\s+CHANGED=(?P<changed>\d+)\s+"
    r"DELETED_REMOTE=(?P<deleted>\d+)\s+UNCHANGED=(?P<unchanged>\d+)\s*$"
)
_D1_GENERATION = re.compile(r"^D1_PUBLISHED_GENERATION\s+(\S+)")
_R2_GENERATION = re.compile(r"^R2_PUBLISHED_GENERATION\s+(\S+)")


class SyncError(Exception):
    """Stable failure code, never captured process output."""


class SyncBusy(SyncError):
    def __init__(self) -> None:
        super().__init__("sync_already_running")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class _Logger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, *parts: Any) -> str:
        line = " ".join(str(part) for part in parts if part is not None and str(part) != "")
        stamped = f"{_utc_now()} {line}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(stamped + "\n")
        print(line, flush=True)
        return stamped


def acquire_lock(root: Path, *, stale_minutes: float, now: float | None = None) -> Path:
    lock = Path(root) / LOCK_NAME
    payload = {"pid": os.getpid(), "started_utc": _utc_now(), "kind": KIND}
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = now if now is not None else time.time()
            age_minutes = (current - lock.stat().st_mtime) / 60.0
            if age_minutes <= stale_minutes:
                raise SyncBusy()
            lock.unlink()
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return lock
    raise SyncBusy()


def release_lock(lock: Path) -> None:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("pid") == os.getpid():
        lock.unlink(missing_ok=True)


def _last_marker(stdout: str, pattern: re.Pattern[str]) -> str | None:
    found = None
    for line in stdout.splitlines():
        match = pattern.match(line.strip())
        if match:
            found = match.group(1)
    return found


def _run_step(
    root: Path,
    name: str,
    command: Sequence[str],
    timeout: float,
    log: _Logger,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired:
        code, stdout, stderr = 124, "", "step_timeout"
    except OSError:
        code, stdout, stderr = 127, "", "step_unavailable"

    for line in stdout.splitlines():
        if line.strip():
            log.emit("OUTPUT", name, line.strip())
    if code != 0:
        log.emit("STEP_FAILED", name, f"exit={code}", (stderr.strip().splitlines() or [""])[-1])
    seconds = round(time.monotonic() - started, 1)
    return {"name": name, "exit": code, "seconds": seconds, "stdout": stdout}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class InventoryServer:
    """A locally started inventory Worker that must be stopped by the runner."""

    def __init__(self, process: subprocess.Popen[bytes], base_url: str, output):
        self.process = process
        self.base_url = base_url
        self.output = output

    def stop(self) -> None:
        try:
            if self.process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            self.output.close()


def inventory_command(
    *,
    wrangler: str,
    port: int,
    secret_store: Path | None = None,
    python: str = sys.executable,
) -> list[str]:
    """Build the inventory Worker command.

    ``wrangler dev`` with a remote R2 binding opens a remote proxy session, so
    it needs a Cloudflare credential. On COM2 that credential lives only in the
    DPAPI secret store, exactly like the D1 export credential. #5484: without
    the store wrapper the remote proxy session fails and the inventory Worker
    exits before the first inventory request, which fails the whole sync.
    """
    command = [wrangler, "dev", "--config", "wrangler.inventory.toml", "--port", str(port)]
    if secret_store is not None and Path(secret_store).is_file():
        command = [python, str(secret_store), "run", *command]
    return command


def start_inventory(
    root: Path,
    *,
    wrangler: str,
    port: int,
    log: _Logger,
    startup_timeout: float = 90.0,
    secret_store: Path | None = None,
    python: str = sys.executable,
) -> InventoryServer:
    selected = port or _free_port()
    output_path = Path(root) / "logs" / "inventory-worker.log"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = output_path.open("a", encoding="utf-8", errors="replace")
    try:
        process = subprocess.Popen(
            inventory_command(
                wrangler=wrangler,
                port=selected,
                secret_store=secret_store,
                python=python,
            ),
            cwd=root,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        output.close()
        raise SyncError("inventory_worker_unavailable") from error
    server = InventoryServer(process, f"http://127.0.0.1:{selected}", output)
    deadline = time.monotonic() + startup_timeout
    ready_url = server.base_url + "/inventory?bucket=workspace"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            server.stop()
            raise SyncError("inventory_worker_exited")
        try:
            with urllib.request.urlopen(ready_url, timeout=5) as response:
                if response.status == 200:
                    log.emit("INVENTORY_READY", f"port={selected}")
                    return server
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1.0)
    server.stop()
    raise SyncError("inventory_worker_not_ready")


def fetch_inventories(
    server: Any,
    root: Path,
    *,
    log: _Logger,
    retries: int = 3,
    retry_delay: float = 2.0,
    timeout: float = 30.0,
) -> dict[str, int]:
    incoming = Path(root) / "r2-staging" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for bucket in R2_BUCKETS:
        url = f"{server.base_url}/inventory?bucket={bucket}"
        payload = None
        last_error = "inventory_request_failed"
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
                last_error = "inventory_request_failed"
                log.emit("INVENTORY_RETRY", bucket, f"attempt={attempt}", type(error).__name__)
                if attempt < retries:
                    time.sleep(retry_delay)
        if payload is None:
            raise SyncError(f"{last_error}:{bucket}")
        objects = payload.get("objects")
        if (
            not isinstance(objects, list)
            or payload.get("truncated") is not False
            or payload.get("count") != len(objects)
        ):
            raise SyncError(f"inventory_incomplete:{bucket}")
        destination = incoming / f"{bucket}.json"
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, destination)
        counts[bucket] = len(objects)
        log.emit("INVENTORY", bucket, f"count={len(objects)}")
    return counts


def parse_diff(stdout: str) -> dict[str, Any]:
    buckets: dict[str, dict[str, int]] = {}
    for line in stdout.splitlines():
        match = _DIFF_LINE.match(line.strip())
        if match:
            buckets[match.group("bucket")] = {
                "new": int(match.group("new")),
                "changed": int(match.group("changed")),
                "deleted_remote": int(match.group("deleted")),
                "unchanged": int(match.group("unchanged")),
            }
    if set(buckets) != set(R2_BUCKETS):
        raise SyncError("r2_diff_unparsed")
    return {
        "buckets": buckets,
        "new": sum(row["new"] for row in buckets.values()),
        "changed": sum(row["changed"] for row in buckets.values()),
        "deleted_remote": sum(row["deleted_remote"] for row in buckets.values()),
    }


def _preflight(root: Path) -> None:
    for name in REQUIRED_LAYOUT:
        if not (root / name).is_file():
            raise SyncError(f"ops_layout_incomplete:{name}")


InventoryFactory = Callable[..., Any]


def run_once(
    root: Path,
    *,
    python: str = sys.executable,
    wrangler: str = "wrangler",
    port: int = 0,
    d1_timeout: float = 900.0,
    r2_diff_timeout: float = 600.0,
    r2_sync_timeout: float = 3600.0,
    startup_timeout: float = 90.0,
    retry_delay: float = 2.0,
    secret_store: Path | None = None,
    log: _Logger | None = None,
    inventory_factory: InventoryFactory = start_inventory,
) -> int:
    root = Path(root)
    log = log or _Logger(root / "logs" / LOG_NAME)
    status_path = root / STATUS_NAME
    started = _utc_now()
    status: dict[str, Any] = {
        "kind": KIND,
        "started_utc": started,
        "finished_utc": None,
        "ok": False,
        "failed_step": None,
        "error": None,
        "d1": {},
        "r2": {},
    }

    current_step = "d1"
    try:
        _preflight(root)
        log.emit("RUN_START", f"root={root}")

        d1 = _run_step(root, "d1", [python, "refresh_d1.py"], d1_timeout, log)
        status["d1"] = {
            "exit": d1["exit"],
            "seconds": d1["seconds"],
            "generation": _last_marker(d1["stdout"], _D1_GENERATION),
        }
        if d1["exit"] != 0:
            raise SyncError("d1_refresh_failed")

        current_step = "inventory"
        server = inventory_factory(
            root,
            wrangler=wrangler,
            port=port,
            log=log,
            startup_timeout=startup_timeout,
            secret_store=secret_store,
        )
        try:
            counts = fetch_inventories(
                server, root, log=log, retry_delay=retry_delay
            )
        finally:
            server.stop()
        status["r2"]["inventory"] = counts

        current_step = "r2_diff"
        diff = _run_step(root, "r2_diff", [python, "r2_sync.py", "--diff-only"], r2_diff_timeout, log)
        if diff["exit"] != 0:
            raise SyncError("r2_diff_failed")
        delta = parse_diff(diff["stdout"])
        status["r2"].update(
            {"new": delta["new"], "changed": delta["changed"],
             "deleted_remote": delta["deleted_remote"], "buckets": delta["buckets"]}
        )

        if delta["new"] or delta["changed"]:
            current_step = "r2_sync"
            full = _run_step(root, "r2_sync", [python, "r2_sync.py"], r2_sync_timeout, log)
            status["r2"]["exit"] = full["exit"]
            status["r2"]["generation"] = _last_marker(full["stdout"], _R2_GENERATION)
            status["r2"]["mode"] = "synced"
            if full["exit"] != 0:
                raise SyncError("r2_sync_failed")
        else:
            status["r2"]["mode"] = "unchanged"
            log.emit("R2_UNCHANGED")

        status["ok"] = True
        status["finished_utc"] = _utc_now()
        _write_json_atomic(status_path, status)
        log.emit("RUN_OK", f"d1={status['d1'].get('generation')}", f"r2={status['r2'].get('mode')}")
        return 0
    except SyncError as error:
        status["failed_step"] = current_step
        status["error"] = str(error)
    except Exception as error:  # noqa: BLE001 - status must record unexpected failures
        status["failed_step"] = current_step
        status["error"] = type(error).__name__
    status["finished_utc"] = _utc_now()
    _write_json_atomic(status_path, status)
    log.emit("RUN_FAILED", f"step={status['failed_step']}", f"error={status['error']}")
    return 1


def run(
    root: Path,
    *,
    stale_minutes: float = 180.0,
    **options: Any,
) -> int:
    root = Path(root)
    log = options.pop("log", None) or _Logger(root / "logs" / LOG_NAME)
    try:
        lock = acquire_lock(root, stale_minutes=stale_minutes)
    except SyncBusy:
        log.emit("RUN_BUSY", f"stale_minutes={stale_minutes}")
        return 1
    try:
        return run_once(root, log=log, **options)
    finally:
        release_lock(lock)


def _launcher_path(root: Path) -> Path:
    return Path(root) / "run-scheduled-sync.ps1"


def _launcher_content(
    root: Path,
    repo: Path,
    *,
    python: str,
    wrangler: str,
    stale_minutes: float,
) -> str:
    script = Path(repo).resolve() / "scripts" / "ops" / "com2_periodic_sync.py"
    return (
        "# Generated by scripts/ops/com2_periodic_sync.py\r\n"
        "$ErrorActionPreference = \"Stop\"\r\n"
        f"Set-Location -LiteralPath \"{Path(root).resolve()}\"\r\n"
        f"& \"{python}\" \"{script}\" run --root \"{Path(root).resolve()}\" "
        f"--wrangler \"{wrangler}\" --stale-minutes {stale_minutes}\r\n"
        "exit $LASTEXITCODE\r\n"
    )


def _schtasks_create(task_name: str, at: str, launcher: Path) -> list[str]:
    action = (
        "powershell.exe -NoProfile -ExecutionPolicy Bypass "
        f"-File \"{launcher.resolve()}\""
    )
    return [
        "schtasks", "/Create", "/TN", task_name, "/SC", "DAILY", "/ST", at,
        "/IT", "/RL", "LIMITED", "/F", "/TR", action,
    ]


def install_task(
    root: Path,
    repo: Path,
    *,
    task_name: str = DEFAULT_TASK_NAME,
    at: str = DEFAULT_TASK_TIME,
    python: str = sys.executable,
    wrangler: str = "wrangler",
    stale_minutes: float = 180.0,
    dry_run: bool = False,
) -> int:
    root = Path(root)
    try:
        _preflight(root)
    except SyncError as error:
        print(f"TASK_INSTALL_FAILED reason={error}", file=sys.stderr)
        return 1
    launcher = _launcher_path(root)
    content = _launcher_content(
        root, repo, python=python, wrangler=wrangler, stale_minutes=stale_minutes
    )
    command = _schtasks_create(task_name, at, launcher)
    if dry_run:
        print(json.dumps(
            {"launcher": str(launcher), "content": content, "command": command},
            indent=2,
        ))
        return 0
    launcher.write_text(content, encoding="utf-8")
    completed = subprocess.run(command, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        print(f"TASK_INSTALL_FAILED exit={completed.returncode} "
              f"{(completed.stderr or completed.stdout).strip()}", file=sys.stderr)
        return 1
    print(f"SCHEDULE_INSTALLED task={task_name} time={at} launcher={launcher}")
    return 0


def remove_task(*, task_name: str = DEFAULT_TASK_NAME, dry_run: bool = False) -> int:
    command = ["schtasks", "/Delete", "/TN", task_name, "/F"]
    if dry_run:
        print(json.dumps({"command": command}, indent=2))
        return 0
    completed = subprocess.run(command, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        print(f"TASK_REMOVE_FAILED exit={completed.returncode}", file=sys.stderr)
        return 1
    print(f"SCHEDULE_REMOVED task={task_name}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run D1 refresh and R2 delta sync once")
    run_parser.add_argument("--root", required=True)
    run_parser.add_argument("--python", default=sys.executable)
    run_parser.add_argument("--wrangler", default=os.environ.get("WRANGLER", "wrangler"))
    run_parser.add_argument("--port", type=int, default=0)
    run_parser.add_argument("--stale-minutes", type=float, default=180.0)
    run_parser.add_argument("--d1-timeout", type=float, default=900.0)
    run_parser.add_argument("--r2-diff-timeout", type=float, default=600.0)
    run_parser.add_argument("--r2-sync-timeout", type=float, default=3600.0)
    run_parser.add_argument("--startup-timeout", type=float, default=90.0)
    run_parser.add_argument(
        "--secret-store",
        default=DEFAULT_SECRET_STORE,
        help=(
            "COM2 DPAPI secret store that injects the Cloudflare credential into "
            "the inventory Worker. The D1 export already uses the same store; "
            "a remote R2 binding needs the same credential."
        ),
    )
    run_parser.set_defaults(handler=_command_run)

    status_parser = subparsers.add_parser("status", help="print the last run status")
    status_parser.add_argument("--root", required=True)
    status_parser.set_defaults(handler=_command_status)

    install_parser = subparsers.add_parser("install-task", help="register the Windows task")
    install_parser.add_argument("--root", required=True)
    install_parser.add_argument("--repo", required=True)
    install_parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    install_parser.add_argument("--time", default=DEFAULT_TASK_TIME)
    install_parser.add_argument("--python", default=sys.executable)
    install_parser.add_argument("--wrangler", default=os.environ.get("WRANGLER", "wrangler"))
    install_parser.add_argument("--stale-minutes", type=float, default=180.0)
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(handler=_command_install)

    remove_parser = subparsers.add_parser("remove-task", help="remove the Windows task")
    remove_parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    remove_parser.add_argument("--dry-run", action="store_true")
    remove_parser.set_defaults(handler=_command_remove)
    return parser


def _command_run(args: argparse.Namespace) -> int:
    return run(
        Path(args.root),
        python=args.python,
        wrangler=args.wrangler,
        port=args.port,
        stale_minutes=args.stale_minutes,
        d1_timeout=args.d1_timeout,
        r2_diff_timeout=args.r2_diff_timeout,
        r2_sync_timeout=args.r2_sync_timeout,
        startup_timeout=args.startup_timeout,
        secret_store=Path(args.secret_store) if args.secret_store else None,
    )


def _command_status(args: argparse.Namespace) -> int:
    path = Path(args.root) / STATUS_NAME
    if not path.is_file():
        print("STATUS_MISSING", file=sys.stderr)
        return 2
    print(path.read_text(encoding="utf-8").strip())
    return 0


def _command_install(args: argparse.Namespace) -> int:
    return install_task(
        Path(args.root),
        Path(args.repo),
        task_name=args.task_name,
        at=args.time,
        python=args.python,
        wrangler=args.wrangler,
        stale_minutes=args.stale_minutes,
        dry_run=args.dry_run,
    )


def _command_remove(args: argparse.Namespace) -> int:
    return remove_task(task_name=args.task_name, dry_run=args.dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
