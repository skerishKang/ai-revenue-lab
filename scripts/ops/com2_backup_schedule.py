#!/usr/bin/env python3
"""Unattended COM2 backup cycles and operator-requested restore verification.

This is the operational layer for issue #5093. It reuses ``com2_backup.py`` for
the inventory, encrypted archive build, upload, remote integrity verification
and restore check. It adds only:

* a single-instance lock so two scheduled runs cannot overlap;
* bounded retries with a new backup id per attempt, because the Worker never
  overwrites a stored generation;
* a status JSON that records the failed stage, a stable error code,
  recoverability, and the last successful backup even while the current run is
  failing;
* a freshness check for the last success. The check requires an explicit
  ``--max-age-hours``; no cadence, retention or cost policy is decided here;
* an operator-invoked restore verification into a throwaway directory;
* a Windows Task Scheduler installer that injects the existing DPAPI entries
  through the existing ``store.py run`` wrapper. The scheduled time is an
  installer argument, not a default.

No remote object is deleted or overwritten, no operational database is
restored, and no secret value is written to a status file or a log.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

KIND = "PADIEM_COM2_BACKUP_SCHEDULE_V1"
RESTORE_KIND = "PADIEM_COM2_RESTORE_VERIFY_V1"
STATUS_NAME = "backup-status.json"
RESTORE_STATUS_NAME = "restore-check-status.json"
LOG_NAME = "backup.log"
LOCK_NAME = "backup.lock"
DEFAULT_TASK_NAME = "PADIEM-COM2-Backup"
DEFAULT_MACHINE = "com2"
DEFAULT_TOKEN_ENV = "PADIEM_COM2_BACKUP_WRITE_TOKEN"
DEFAULT_KEY_ENV = "COM2_BACKUP_ENCRYPTION_KEY"
DEFAULT_STATE_DIR = Path(
    os.environ.get("PADIEM_COM2_BACKUP_STATE", r"D:\PADIEM-Servers\backups\com2-schedule")
)
DEFAULT_SECRET_STORE = Path(
    os.environ.get(
        "PADIEM_COM2_SECRET_STORE",
        r"D:\PADIEM-Servers\infrastructure\secret-store\store.py",
    )
)
GENERATION_KIND = "PADIEM_COM2_B62_GENERATION_V1"
_GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RETRYABLE_HTTP = re.compile(r"^http_(429|5\d\d)$")
_RETRYABLE_CODES = {
    "endpoint_unreachable",
    "response_too_large",
    "verify_response_invalid",
    "integrity_mismatch",
    "remote_verify_mismatch",
    "source_changed_during_backup",
}


def _load_backup_ops():
    path = Path(__file__).resolve().parent / "com2_backup.py"
    spec = importlib.util.spec_from_file_location("com2_backup_ops_for_schedule", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("COM2_BACKUP_OPS_NOT_FOUND")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BACKUP_OPS = _load_backup_ops()


class InstallError(Exception):
    """Stable installer failure code."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class _Logger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, *parts: Any) -> None:
        line = " ".join(str(part) for part in parts if part not in (None, ""))
        stamped = f"{_utc_now()} {line}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(stamped + "\n")
        print(line, flush=True)


@dataclass(frozen=True)
class BackupConfig:
    endpoint: str
    key_id: str
    roots: tuple[Path, ...] = ()
    machine: str = DEFAULT_MACHINE
    token_env: str = DEFAULT_TOKEN_ENV
    key_env: str = DEFAULT_KEY_ENV
    generation_pointer: Path | None = None
    generations_dir: Path | None = None


def resolve_roots(config: BackupConfig) -> list[Path]:
    """Return the configured roots, resolving the current D1 generation.

    The generation snapshot directory changes with every published generation,
    so a fixed path would silently back up an old database. A pointer that
    cannot be resolved fails the run instead of producing a stale backup.
    """
    selected: list[Path] = list(config.roots)
    pointer_present = config.generation_pointer is not None
    directory_present = config.generations_dir is not None
    if pointer_present != directory_present:
        raise BACKUP_OPS.OpsError("generation_config_incomplete")
    if pointer_present and directory_present:
        assert config.generation_pointer is not None and config.generations_dir is not None
        try:
            pointer = json.loads(config.generation_pointer.read_text(encoding="utf-8"))
        except OSError:
            raise BACKUP_OPS.OpsError("generation_pointer_missing")
        except ValueError:
            raise BACKUP_OPS.OpsError("generation_pointer_invalid")
        if not isinstance(pointer, dict) or pointer.get("kind") != GENERATION_KIND:
            raise BACKUP_OPS.OpsError("generation_pointer_invalid")
        generation = pointer.get("d1_generation")
        if not isinstance(generation, str) or not _GENERATION_RE.fullmatch(generation):
            raise BACKUP_OPS.OpsError("generation_pointer_invalid")
        snapshot = Path(config.generations_dir) / generation
        if not snapshot.is_dir():
            raise BACKUP_OPS.OpsError("generation_snapshot_missing")
        selected.append(snapshot)

    resolved: list[Path] = []
    seen: set[Path] = set()
    for root in selected:
        try:
            candidate = Path(root).resolve()
        except OSError:
            continue
        if not candidate.is_dir() or candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    if not resolved:
        raise BACKUP_OPS.OpsError("no_source_roots")
    return resolved


def acquire_lock(state_dir: Path, *, stale_minutes: float, now: float | None = None) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / LOCK_NAME
    payload = {"pid": os.getpid(), "started_utc": _utc_now(), "kind": KIND}
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            current = now if now is not None else time.time()
            try:
                age_minutes = (current - lock.stat().st_mtime) / 60.0
            except OSError:
                raise BACKUP_OPS.OpsError("backup_already_running")
            if age_minutes <= stale_minutes:
                raise BACKUP_OPS.OpsError("backup_already_running")
            try:
                lock.unlink()
            except OSError:
                raise BACKUP_OPS.OpsError("backup_already_running")
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return lock
    raise BACKUP_OPS.OpsError("backup_already_running")


def release_lock(lock: Path) -> None:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if payload.get("pid") == os.getpid():
        lock.unlink(missing_ok=True)


def _is_retryable(code: str) -> bool:
    return code in _RETRYABLE_CODES or bool(_RETRYABLE_HTTP.fullmatch(code))


def _attempt_backup_id(base: str, attempt: int) -> str:
    return base if attempt == 1 else f"{base}-r{attempt}"


def _base_status(config: BackupConfig, previous: Mapping[str, Any], started: str) -> dict[str, Any]:
    return {
        "kind": KIND,
        "started_utc": started,
        "finished_utc": None,
        "ok": False,
        "endpoint": config.endpoint,
        "machine": config.machine,
        "key_id": config.key_id,
        "backup_id": None,
        "attempts": 0,
        "attempts_detail": [],
        "failed_stage": None,
        "error": None,
        "recoverable": None,
        "operator_action_required": None,
        "source": None,
        "payload": None,
        "remote_verified": False,
        "last_success_utc": previous.get("last_success_utc"),
        "last_success_backup_id": previous.get("last_success_backup_id"),
        "last_failure_utc": previous.get("last_failure_utc"),
        "last_failure_stage": previous.get("last_failure_stage"),
        "last_failure_error": previous.get("last_failure_error"),
        "consecutive_failures": int(previous.get("consecutive_failures") or 0),
    }


def _finish_failure(
    state_dir: Path,
    status: dict[str, Any],
    stage: str,
    code: str,
    log: _Logger,
) -> tuple[int, dict[str, Any]]:
    finished = _utc_now()
    recoverable = _is_retryable(code)
    status.update(
        {
            "finished_utc": finished,
            "failed_stage": stage,
            "error": code,
            "recoverable": recoverable,
            "operator_action_required": not recoverable,
            "last_failure_utc": finished,
            "last_failure_stage": stage,
            "last_failure_error": code,
            "consecutive_failures": int(status.get("consecutive_failures") or 0) + 1,
        }
    )
    _write_json_atomic(state_dir / STATUS_NAME, status)
    log.emit(
        "RUN_FAILED",
        f"stage={stage}",
        f"error={code}",
        f"recoverable={str(recoverable).lower()}",
        f"consecutive_failures={status['consecutive_failures']}",
    )
    return 1, status


def run_once(
    state_dir: Path,
    config: BackupConfig,
    *,
    retries: int = 3,
    retry_delay: float = 5.0,
    ops: Any = BACKUP_OPS,
    log: _Logger | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = _utc_now,
) -> tuple[int, dict[str, Any]]:
    state_dir = Path(state_dir)
    log = log or _Logger(state_dir / LOG_NAME)
    started = now()
    previous = _read_json(state_dir / STATUS_NAME)
    status = _base_status(config, previous, started)
    attempt = 0

    try:
        roots = resolve_roots(config)
        token = os.environ.get(config.token_env, "")
        if not token:
            raise BACKUP_OPS.OpsError("backup_token_env_missing")
        key = ops.encryption_key_from_env(config.key_env)
        base_id = ops.default_backup_id()
        status["source"] = {"roots": len(roots)}
    except BACKUP_OPS.OpsError as error:
        return _finish_failure(state_dir, status, "prepare", error.code, log)
    except Exception:
        return _finish_failure(state_dir, status, "prepare", "unexpected_error", log)

    for attempt in range(1, max(1, retries) + 1):
        backup_id = _attempt_backup_id(base_id, attempt)
        out_dir = state_dir / "backups" / backup_id
        detail: dict[str, Any] = {
            "attempt": attempt,
            "backup_id": backup_id,
            "stage": "build",
            "error": None,
        }
        status["attempts"] = attempt
        status["backup_id"] = backup_id
        status["attempts_detail"].append(detail)
        log.emit("ATTEMPT_START", f"attempt={attempt}", f"backup_id={backup_id}")

        try:
            built = ops.build_backup(
                roots,
                out_dir,
                config.machine,
                backup_id,
                now(),
                encryption_key=key,
                key_id=config.key_id,
            )
            status["source"] = {
                "roots": len(roots),
                "files": built["manifest"]["file_count"],
                "bytes": built["manifest"]["total_bytes"],
            }
            status["payload"] = {
                "bytes": built["payload_bytes"],
                "sha256": built["payload_sha256"],
            }
            detail["stage"] = "upload"
            log.emit("BUILD_OK", f"backup_id={backup_id}",
                     f"files={built['manifest']['file_count']}",
                     f"payload_bytes={built['payload_bytes']}")

            ops.upload_backup(
                config.endpoint, out_dir, config.machine, backup_id, token
            )
            detail["stage"] = "remote_verify"
            log.emit("UPLOAD_OK", f"backup_id={backup_id}")

            verified = ops.verify_backup(
                config.endpoint,
                config.machine,
                backup_id,
                token,
                out_dir,
                config.key_id,
            )
            if verified.get("sha256") != built["payload_sha256"]:
                raise BACKUP_OPS.OpsError("remote_verify_mismatch")
            if verified.get("key_id") != config.key_id:
                raise BACKUP_OPS.OpsError("encryption_key_id_mismatch")
        except BACKUP_OPS.CONTRACT.BackupError as error:
            detail["error"] = error.code
            detail["stage"] = status["failed_stage"] = _current_stage(detail)
            if attempt < retries and _is_retryable(error.code):
                log.emit("RETRY", f"attempt={attempt}", f"error={error.code}")
                sleep(retry_delay)
                continue
            return _finish_failure(state_dir, status, detail["stage"], error.code, log)
        except BACKUP_OPS.OpsError as error:
            detail["error"] = error.code
            detail["stage"] = _current_stage(detail)
            if attempt < retries and _is_retryable(error.code):
                log.emit("RETRY", f"attempt={attempt}", f"error={error.code}")
                sleep(retry_delay)
                continue
            return _finish_failure(state_dir, status, detail["stage"], error.code, log)
        except Exception:
            detail["error"] = "unexpected_error"
            detail["stage"] = _current_stage(detail)
            return _finish_failure(
                state_dir, status, detail["stage"], "unexpected_error", log
            )

        detail["stage"] = "completed"
        status.update(
            {
                "finished_utc": now(),
                "ok": True,
                "remote_verified": True,
                "failed_stage": None,
                "error": None,
                "recoverable": None,
                "operator_action_required": None,
                "last_success_utc": now(),
                "last_success_backup_id": backup_id,
                "consecutive_failures": 0,
            }
        )
        _write_json_atomic(state_dir / STATUS_NAME, status)
        log.emit(
            "RUN_OK",
            f"backup_id={backup_id}",
            f"remote_verified=true",
            f"attempts={attempt}",
        )
        return 0, status

    return _finish_failure(
        state_dir, status, "unknown", "retry_exhausted", log
    )


def _current_stage(detail: Mapping[str, Any]) -> str:
    stage = detail.get("stage")
    return stage if isinstance(stage, str) and stage else "build"


def run(
    state_dir: Path,
    config: BackupConfig,
    *,
    stale_minutes: float = 180.0,
    retries: int = 3,
    retry_delay: float = 5.0,
    ops: Any = BACKUP_OPS,
) -> int:
    state_dir = Path(state_dir)
    log = _Logger(state_dir / LOG_NAME)
    try:
        lock = acquire_lock(state_dir, stale_minutes=stale_minutes)
    except BACKUP_OPS.OpsError as error:
        log.emit("RUN_BUSY", f"error={error.code}", f"stale_minutes={stale_minutes}")
        return 3
    try:
        code, _status = run_once(
            state_dir,
            config,
            retries=retries,
            retry_delay=retry_delay,
            ops=ops,
            log=log,
        )
        return code
    finally:
        release_lock(lock)


def restore_verify(
    state_dir: Path,
    config: BackupConfig,
    backup_id: str,
    *,
    work_dir: Path | None = None,
    ops: Any = BACKUP_OPS,
) -> tuple[int, dict[str, Any]]:
    """Operator-invoked restore check into a throwaway directory.

    The verified tree is removed after the check. Nothing is published into a
    source root or an operational database, and this function is never called
    by the scheduled runner.
    """
    state_dir = Path(state_dir)
    work_root = Path(work_dir) if work_dir is not None else state_dir / "restore-check"
    work_root.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix=f"{backup_id}-", dir=str(work_root)))
    status: dict[str, Any] = {
        "kind": RESTORE_KIND,
        "started_utc": _utc_now(),
        "finished_utc": None,
        "ok": False,
        "backup_id": backup_id,
        "machine": config.machine,
        "failed_stage": None,
        "error": None,
        "files": None,
        "bytes": None,
        "encrypted": None,
        "key_id": None,
    }
    try:
        token = os.environ.get(config.token_env, "")
        if not token:
            raise BACKUP_OPS.OpsError("backup_token_env_missing")
        key = ops.encryption_key_from_env(config.key_env)
        result = ops.restore_check(
            config.endpoint,
            config.machine,
            backup_id,
            token,
            target,
            encryption_key=key,
            expected_key_id=config.key_id,
        )
        status.update(
            {
                "ok": True,
                "files": result.get("file_count"),
                "bytes": result.get("total_bytes"),
                "encrypted": result.get("encrypted"),
                "key_id": result.get("key_id"),
            }
        )
    except BACKUP_OPS.OpsError as error:
        status.update({"failed_stage": "restore_check", "error": error.code})
    except BACKUP_OPS.CONTRACT.BackupError as error:
        status.update({"failed_stage": "restore_check", "error": error.code})
    except Exception:
        status.update({"failed_stage": "restore_check", "error": "unexpected_error"})
    finally:
        shutil.rmtree(target, ignore_errors=True)

    status["finished_utc"] = _utc_now()
    _write_json_atomic(state_dir / RESTORE_STATUS_NAME, status)
    return (0 if status["ok"] else 1), status


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_arguments(
    state_dir: Path,
    config: BackupConfig,
    *,
    retries: int,
    retry_delay: float,
    stale_minutes: float,
) -> list[str]:
    arguments = [
        "run",
        "--state-dir", str(Path(state_dir).resolve()),
        "--endpoint", config.endpoint,
        "--machine", config.machine,
        "--key-id", config.key_id,
        "--token-env", config.token_env,
        "--key-env", config.key_env,
        "--retries", str(retries),
        "--retry-delay", str(retry_delay),
        "--stale-minutes", str(stale_minutes),
    ]
    for root in config.roots:
        arguments.extend(["--root", str(Path(root).resolve())])
    if config.generation_pointer is not None:
        arguments.extend(
            ["--generation-pointer", str(Path(config.generation_pointer).resolve())]
        )
    if config.generations_dir is not None:
        arguments.extend(
            ["--generations-dir", str(Path(config.generations_dir).resolve())]
        )
    return arguments


def install_task(
    state_dir: Path,
    repo: Path,
    config: BackupConfig,
    *,
    at: str,
    task_name: str = DEFAULT_TASK_NAME,
    python: str = sys.executable,
    secret_store: Path | None = DEFAULT_SECRET_STORE,
    retries: int = 3,
    retry_delay: float = 5.0,
    stale_minutes: float = 180.0,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if not _TIME_RE.fullmatch(at):
        raise InstallError("invalid_schedule_time")
    if not config.key_id:
        raise InstallError("encryption_key_id_missing")
    try:
        resolve_roots(config)
    except BACKUP_OPS.OpsError as error:
        raise InstallError(error.code)
    script = Path(repo).resolve() / "scripts" / "ops" / "com2_backup_schedule.py"
    if not script.is_file():
        raise InstallError("runner_script_missing")
    store = Path(secret_store) if secret_store is not None else None
    if store is not None and not store.is_file():
        raise InstallError("secret_store_missing")

    state_dir = Path(state_dir)
    launcher = state_dir / "run-backup.ps1"
    command = [python, str(script)] + _run_arguments(
        state_dir,
        config,
        retries=retries,
        retry_delay=retry_delay,
        stale_minutes=stale_minutes,
    )
    if store is not None:
        command = [python, str(store), "run"] + command
    content = (
        "# Generated by scripts/ops/com2_backup_schedule.py\r\n"
        "$ErrorActionPreference = \"Stop\"\r\n"
        f"Set-Location -LiteralPath {_ps_quote(state_dir.resolve())}\r\n"
        f"& {' '.join(_ps_quote(part) for part in command)}\r\n"
        "exit $LASTEXITCODE\r\n"
    )
    schtasks = [
        "schtasks", "/Create", "/SC", "DAILY", "/ST", at,
        "/TN", task_name,
        "/TR", f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{launcher.resolve()}"',
        "/IT", "/RL", "LIMITED",
    ]
    if force:
        schtasks.append("/F")
    result: dict[str, Any] = {
        "kind": KIND,
        "task_name": task_name,
        "time": at,
        "launcher": str(launcher),
        "command": schtasks,
        "launcher_content": content,
        "dry_run": dry_run,
        "registered": False,
    }
    if dry_run:
        return result

    state_dir.mkdir(parents=True, exist_ok=True)
    launcher.write_text(content, encoding="utf-8")
    completed = subprocess.run(
        schtasks,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    result["exit"] = int(completed.returncode)
    if completed.returncode != 0:
        result["error"] = "schtasks_failed"
        result["stderr_tail"] = (completed.stderr or "").strip().splitlines()[-1:] or []
        return result
    result["registered"] = True
    return result


def status_report(
    state_dir: Path,
    *,
    max_age_hours: float | None = None,
) -> tuple[int, dict[str, Any] | None]:
    path = Path(state_dir) / STATUS_NAME
    if not path.is_file():
        print("STATUS_MISSING", file=sys.stderr)
        return 2, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("STATUS_INVALID", file=sys.stderr)
        return 2, None
    if not isinstance(payload, dict):
        print("STATUS_INVALID", file=sys.stderr)
        return 2, None
    print(json.dumps(payload, indent=2, sort_keys=True))
    if max_age_hours is None:
        return (0 if payload.get("ok") else 1), payload
    last = _parse_instant(payload.get("last_success_utc"))
    if last is None:
        print("LAST_SUCCESS_MISSING", file=sys.stderr)
        return 1, payload
    age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
    if age_hours > max_age_hours:
        print(f"LAST_SUCCESS_STALE age_hours={age_hours:.1f}", file=sys.stderr)
        return 1, payload
    print(f"LAST_SUCCESS_OK age_hours={age_hours:.1f}")
    return 0, payload


def _config_from_args(args: argparse.Namespace) -> BackupConfig:
    pointer = Path(args.generation_pointer) if args.generation_pointer else None
    directory = Path(args.generations_dir) if args.generations_dir else None
    return BackupConfig(
        endpoint=args.endpoint,
        key_id=args.key_id,
        roots=tuple(Path(value) for value in args.root),
        machine=args.machine,
        token_env=args.token_env,
        key_env=args.key_env,
        generation_pointer=pointer,
        generations_dir=directory,
    )


def _command_run(args: argparse.Namespace) -> int:
    return run(
        Path(args.state_dir),
        _config_from_args(args),
        stale_minutes=args.stale_minutes,
        retries=args.retries,
        retry_delay=args.retry_delay,
    )


def _command_status(args: argparse.Namespace) -> int:
    code, _payload = status_report(
        Path(args.state_dir), max_age_hours=args.max_age_hours
    )
    return code


def _command_restore(args: argparse.Namespace) -> int:
    code, payload = restore_verify(
        Path(args.state_dir),
        _config_from_args(args),
        args.backup_id,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )
    if payload["ok"]:
        print(
            f"RESTORE_VERIFY_OK backup_id={args.backup_id} "
            f"files={payload['files']} bytes={payload['bytes']}"
        )
    else:
        print(
            f"RESTORE_VERIFY_FAIL stage={payload['failed_stage']} "
            f"error={payload['error']}",
            file=sys.stderr,
        )
    return code


def _command_install(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    try:
        result = install_task(
            Path(args.state_dir),
            Path(args.repo),
            config,
            at=args.time,
            task_name=args.task_name,
            python=args.python,
            secret_store=Path(args.secret_store) if args.secret_store else None,
            retries=args.retries,
            retry_delay=args.retry_delay,
            stale_minutes=args.stale_minutes,
            dry_run=args.dry_run,
            force=args.force,
        )
    except InstallError as error:
        print(f"TASK_INSTALL_FAILED reason={error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["dry_run"]:
        return 0
    if not result["registered"]:
        print(
            f"TASK_INSTALL_FAILED exit={result.get('exit')} "
            f"{(result.get('stderr_tail') or [''])[0]}",
            file=sys.stderr,
        )
        return 1
    print(f"SCHEDULE_INSTALLED task={result['task_name']} time={result['time']}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    def backup_arguments(sub: argparse.ArgumentParser, *, with_state: bool = True) -> None:
        if with_state:
            sub.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
        sub.add_argument("--endpoint", required=True)
        sub.add_argument("--machine", default=DEFAULT_MACHINE)
        sub.add_argument("--key-id", required=True)
        sub.add_argument("--root", action="append", default=[])
        sub.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
        sub.add_argument("--key-env", default=DEFAULT_KEY_ENV)
        sub.add_argument("--generation-pointer", default="")
        sub.add_argument("--generations-dir", default="")

    run_parser = subparsers.add_parser("run", help="run one backup cycle")
    backup_arguments(run_parser)
    run_parser.add_argument("--retries", type=int, default=3)
    run_parser.add_argument("--retry-delay", type=float, default=5.0)
    run_parser.add_argument("--stale-minutes", type=float, default=180.0)
    run_parser.set_defaults(handler=_command_run)

    status_parser = subparsers.add_parser("status", help="print the last run status")
    status_parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    status_parser.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help="fail when the last success is older than this explicit bound",
    )
    status_parser.set_defaults(handler=_command_status)

    restore_parser = subparsers.add_parser(
        "restore-verify", help="operator-requested restore check into a throwaway directory"
    )
    backup_arguments(restore_parser)
    restore_parser.add_argument("--backup-id", required=True)
    restore_parser.add_argument("--work-dir", default="")
    restore_parser.set_defaults(handler=_command_restore)

    install_parser = subparsers.add_parser(
        "install-task", help="register the Windows scheduled task"
    )
    backup_arguments(install_parser)
    install_parser.add_argument("--repo", required=True)
    install_parser.add_argument("--time", required=True)
    install_parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    install_parser.add_argument("--python", default=sys.executable)
    install_parser.add_argument("--secret-store", default=str(DEFAULT_SECRET_STORE))
    install_parser.add_argument("--retries", type=int, default=3)
    install_parser.add_argument("--retry-delay", type=float, default=5.0)
    install_parser.add_argument("--stale-minutes", type=float, default=180.0)
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--force", action="store_true")
    install_parser.set_defaults(handler=_command_install)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
