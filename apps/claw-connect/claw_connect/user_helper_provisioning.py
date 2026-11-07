"""#7107 PR-B — provision the user-session helper after Connector enrollment.

The Connector is already installed per user and has enrolled. At that point it
owns the exact ``device_id`` the PC dispatch names, so it can do the three
things the one-click installer cannot do before the PC identity exists:

1. create ``C:/ProgramData/Padiem/helper.secret`` (32 random bytes, SYSTEM
   read, installing user modify), never printing the value;
2. point the helper at the installed ``claw_connect`` package, with the install
   root as the task working directory;
3. register the per-user ONLOGON/Limited task and start it immediately.

A failure never fails enrollment or PC connection. The status is written to
``<install root>/helper-status.json`` and reported to the user request as
``user_session_unavailable`` by the existing delegation lane.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from . import user_helper_registration as registration

SECRET_DIR = Path(r"C:\ProgramData\Padiem")
SECRET_NAME = "helper.secret"
STATUS_NAME = "helper-status.json"
STATUS_INSTALLED = "installed"
STATUS_NOT_INSTALLED = "not_installed"
STATUS_SKIPPED = "skipped"
STATUS_PENDING_ENROLLMENT = "pending_enrollment"

Runner = Callable[..., Any]


def _default_run(argv: Sequence[str], **kwargs: Any) -> Any:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=30, **kwargs,
    )


def _write_status(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / STATUS_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError:
        # The helper is optional; a status write failure must not fail the PC.
        pass
    return payload


def read_status(state_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the last provisioning outcome without creating or changing anything."""
    try:
        data = json.loads((Path(state_dir) / STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": STATUS_PENDING_ENROLLMENT}
    return data if isinstance(data, dict) else {"status": STATUS_PENDING_ENROLLMENT}


def _create_secret(path: Path) -> str:
    """Write 32 random bytes as hex. The value is returned only for tests, never logged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value + "\n", encoding="ascii", newline="\n")
    return value


def _set_secret_acl(path: Path, user: str, run: Runner) -> bool:
    """SYSTEM may read; the installing user may modify. No other principals."""
    if not user:
        return False
    try:
        completed = run([
            "icacls", str(path), "/inheritance:r", "/grant:r",
            "SYSTEM:(R)", f"{user}:(M)",
        ])
    except Exception:
        return False
    return getattr(completed, "returncode", 1) == 0


def _register_task(*, launch: registration.HelperLaunch, user: str, run: Runner) -> bool:
    definition = registration.task_definition(launch=launch, user=user)
    script = registration.register_script(definition)
    try:
        completed = run([
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", script,
        ])
    except Exception:
        return False
    return getattr(completed, "returncode", 1) == 0


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    name = getpass.getuser()
    return f"{domain}{os.sep}{name}" if domain else name


def provision_user_helper(
    *,
    device_id: str,
    state_dir: str | os.PathLike[str],
    python_executable: str | None = None,
    secret_dir: str | os.PathLike[str] | None = None,
    user: str | None = None,
    run: Runner | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Best-effort helper provisioning; always returns a status, never raises."""
    root = Path(state_dir)
    runner = run or _default_run
    secret_path = (Path(secret_dir) if secret_dir is not None else SECRET_DIR) / SECRET_NAME
    executable = python_executable or registration.default_python_executable()
    base: dict[str, Any] = {"device_id": device_id, "task": registration.TASK_NAME}

    def done(status: str, reason: str | None = None, **extra: Any) -> dict[str, Any]:
        payload = {**base, "status": status}
        if reason is not None:
            payload["reason"] = reason
        payload.update(extra)
        return _write_status(root, payload)

    try:
        # One shared validator: an unusable id must never reach a command line.
        registration.build_launch(
            python_executable=executable,
            device_id=device_id,
            secret_file=str(secret_path),
        )
    except Exception as exc:
        return done(STATUS_NOT_INSTALLED, "device_id_invalid", error=type(exc).__name__)

    if (platform or sys.platform) != "win32":
        return done(STATUS_SKIPPED, "unsupported_platform")
    if getattr(sys, "frozen", False):
        # The standalone EXE carries no host Python; it cannot run the helper.
        return done(STATUS_SKIPPED, "frozen_connector")
    if not (root / "claw_connect").is_dir():
        return done(STATUS_SKIPPED, "claw_connect_missing")
    if not executable:
        return done(STATUS_SKIPPED, "python_missing")

    secret_created = False
    try:
        if not secret_path.is_file() or not secret_path.read_bytes().strip():
            _create_secret(secret_path)
            secret_created = True
        owner = user or _current_user()
        if not _set_secret_acl(secret_path, owner, runner):
            return done(
                STATUS_NOT_INSTALLED, "secret_acl_failed",
                secret_created=secret_created,
            )
        launch = registration.build_launch(
            python_executable=executable,
            device_id=device_id,
            secret_file=str(secret_path),
            working_directory=str(root),
        )
        if not _register_task(launch=launch, user=owner, run=runner):
            return done(
                STATUS_NOT_INSTALLED, "task_registration_failed",
                secret_created=secret_created,
            )
        return done(STATUS_INSTALLED, secret_created=secret_created)
    except Exception as exc:
        return done(
            STATUS_NOT_INSTALLED, "provision_failed",
            error=type(exc).__name__, secret_created=secret_created,
        )
