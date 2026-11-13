"""#7065 (c) stage 2 — logon registration for the user-session helper.

The helper has to start when the user logs on, inside that user's session, with
no elevation. A scheduled task with an ``ONLOGON`` trigger and ``Limited`` run
level is the mechanism: it is the Windows-native way to get a process into the
interactive session without a service and without administrator rights.

Two boundaries are deliberate:

* **This module never registers anything by itself.** It builds the exact task
  definition and the exact command line, and returns them. Registration is an
  explicit call the installer makes, so a test can prove the shape without
  touching a real machine's task store.

* **Nothing here needs elevation.** ``Register-ScheduledTask`` for the current
  user's own logon trigger runs unelevated. The one step that does need an
  administrator is granting the pipe's DACL to SYSTEM, and that lives in the
  installer script as a separately-labelled step — see
  ``install_user_helper.ps1`` and the PR body's "대표 1회 실행 필요" note.

The task name is fixed and owned: re-registering replaces this product's own
task and never touches any other task on the machine.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Sequence

TASK_NAME = "PadiemUserSessionHelper"
TASK_FOLDER = "\\Padiem\\"
#: The helper is a plain user process. ``Limited`` is the run level that keeps it
#: there; ``Highest`` would be a silent elevation and is never used.
RUN_LEVEL_LIMITED = "Limited"
TRIGGER_ONLOGON = "ONLOGON"


@dataclass(frozen=True, slots=True)
class HelperLaunch:
    """The exact command the task runs, and the working directory it runs in."""

    executable: str
    arguments: list[str]
    working_directory: str

    def command_line(self) -> str:
        """A quoted command line, for the task action's ``Execute``/``Argument``."""
        return " ".join([_quote(self.executable)] + [_quote(arg) for arg in self.arguments])


def _quote(value: str) -> str:
    if not value:
        raise ValueError("an empty argument cannot be quoted")
    if any(char in value for char in ('"', "\r", "\n", "\x00")):
        raise ValueError("an argument may not contain a quote or a line break")
    return f'"{value}"' if " " in value else value


def build_launch(*, python_executable: str, device_id: str, secret_file: str,
                 module: str = "claw_connect.user_helper_service",
                 working_directory: str = "") -> HelperLaunch:
    """The helper's launch command.

    The device id and the secret path are validated by the stage-1 rules before
    they reach a command line, so no customer text is interpolated here.
    """
    from .user_session_helper import pipe_name  # noqa: PLC0415 - validation lives in stage 1

    pipe_name(device_id)  # raises unless this is a real device id
    if not secret_file or any(char in secret_file for char in ('"', "\r", "\n", "\x00")):
        raise ValueError("the secret file path is not usable")
    return HelperLaunch(
        executable=python_executable,
        arguments=["-m", module, "--device-id", device_id, "--secret-file", secret_file],
        working_directory=working_directory,
    )


def task_definition(*, launch: HelperLaunch, user: str) -> dict[str, Any]:
    """The scheduled task definition, as data.

    Returned rather than registered so the shape is testable and so the installer
    is the only thing that writes to the task store.
    """
    if not user or any(char in user for char in ('"', "\r", "\n", "\x00")):
        raise ValueError("the task user is not usable")
    return {
        "TaskName": TASK_NAME,
        "TaskPath": TASK_FOLDER,
        "Description": "PADIEM user-session helper (#7065). Runs one request per process.",
        "Trigger": {"Type": TRIGGER_ONLOGON, "User": user},
        "Principal": {
            "UserId": user,
            "LogonType": "Interactive",
            "RunLevel": RUN_LEVEL_LIMITED,
        },
        "Settings": {
            # One helper per session: a second instance would be a second pipe
            # owner and a second process per request.
            "MultipleInstances": "IgnoreNew",
            # The helper ends with the session it belongs to.
            "StopIfGoingOnBatteries": False,
            "DisallowStartIfOnBatteries": False,
            "ExecutionTimeLimit": "PT0S",
        },
        "Action": {
            "Execute": launch.executable,
            "Argument": " ".join(_quote(arg) for arg in launch.arguments),
            "WorkingDirectory": launch.working_directory,
        },
    }


def register_script(definition: dict[str, Any]) -> str:
    """The PowerShell that registers the task, built from the definition.

    Kept as a string so the installer can run it and a test can read it. Values
    are placed as single-quoted PowerShell literals with any quote doubled, which
    is the only escaping a literal needs.
    """
    def literal(value: str) -> str:
        # #7559: PowerShell closes a single-quoted string on five characters
        # (' and U+2018..U+201B); each is doubled. The helper's single-file
        # build does not import the Core package, so this mirrors
        # ``padiem_ai_core.powershell_literal.ps_literal``.
        return "'" + "".join(
            ch + ch if ch in "'\u2018\u2019\u201a\u201b" else ch for ch in str(value)
        ) + "'"

    trigger = definition["Trigger"]
    principal = definition["Principal"]
    action = definition["Action"]
    settings = definition["Settings"]
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$action = New-ScheduledTaskAction -Execute "
        + literal(action["Execute"]) + " -Argument " + literal(action["Argument"])
        + (
            " -WorkingDirectory " + literal(action["WorkingDirectory"])
            if action.get("WorkingDirectory") else ""
        ),
        "$trigger = New-ScheduledTaskTrigger -AtLogOn -User " + literal(trigger["User"]),
        "$principal = New-ScheduledTaskPrincipal -UserId " + literal(principal["UserId"])
        + " -LogonType " + literal(principal["LogonType"])
        + " -RunLevel " + literal(principal["RunLevel"]),
        "$settings = New-ScheduledTaskSettingsSet -MultipleInstances "
        + literal(settings["MultipleInstances"]),
        "Register-ScheduledTask -TaskName " + literal(definition["TaskName"])
        + " -TaskPath " + literal(definition["TaskPath"])
        + " -Action $action -Trigger $trigger -Principal $principal -Settings $settings"
        + " -Description " + literal(definition["Description"]) + " -Force",
        "Start-ScheduledTask -TaskName " + literal(definition["TaskName"])
        + " -TaskPath " + literal(definition["TaskPath"]),
    ])


def stop_script() -> str:
    """The PowerShell that ends this product's own running task instance (#7564).

    A helper that is still running keeps the secret it read at start in memory,
    so an install that writes a new secret ends it first and waits until the
    task is no longer running. A task that is not registered is not a failure;
    one that is still running after the wait is (exit code 3).
    """
    select = "-TaskPath '" + TASK_FOLDER + "' -TaskName '" + TASK_NAME + "'"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$task = Get-ScheduledTask " + select + " -ErrorAction SilentlyContinue",
        "if ($task) {",
        "    Stop-ScheduledTask " + select + " -ErrorAction SilentlyContinue",
        "    for ($attempt = 0; $attempt -lt 40; $attempt++) {",
        "        $task = Get-ScheduledTask " + select + " -ErrorAction SilentlyContinue",
        "        if (-not $task -or $task.State -ne 'Running') { break }",
        "        Start-Sleep -Milliseconds 250",
        "    }",
        "    if ($task -and $task.State -eq 'Running') { exit 3 }",
        "}",
    ])


def unregister_script() -> str:
    """The PowerShell that removes only this product's own task."""
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$path = '" + TASK_FOLDER + "' + '" + TASK_NAME + "'",
        "if (Get-ScheduledTask -TaskPath '" + TASK_FOLDER + "' -TaskName '"
        + TASK_NAME + "' -ErrorAction SilentlyContinue) {",
        "    Unregister-ScheduledTask -TaskPath '" + TASK_FOLDER + "' -TaskName '"
        + TASK_NAME + "' -Confirm:$false",
        "}",
    ])


def default_python_executable() -> str:
    """The interpreter the task should run.

    ``sys.executable`` is the interpreter that is already running the installer,
    which is the one the connector is installed against. It is not guessed from
    PATH, because a task's PATH is not the user's PATH.
    """
    return sys.executable


def registration_requires_elevation() -> bool:
    """Whether registering this task needs an administrator.

    It does not: an ONLOGON trigger for the current user with ``Limited`` run
    level is a per-user registration. This function exists so the installer can
    state that as a checked fact rather than an assumption.
    """
    return False


def elevation_steps() -> Sequence[str]:
    """The steps that DO need an administrator, named for the installer.

    Only the pipe ACL grant needs it, and only because SYSTEM has to be able to
    open the pipe. Everything else is per-user.
    """
    return (
        "Grant the helper pipe DACL to SYSTEM (icacls on the pipe security descriptor)",
    )
