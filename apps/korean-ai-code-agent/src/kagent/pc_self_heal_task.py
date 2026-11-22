"""#8193 — the SYSTEM scheduled-task definition for the PC self-heal watcher.

The watcher itself lives in ``local_agent_mesh_self_heal.run_loop``. Nothing
registers it today, so a machine never runs the check and the ops report stays
empty. This module gives the installer (#8223) one call to get the exact task
shape: name, executable command, SYSTEM privilege and cadence.

Deliberate boundary, mirroring ``claw_connect.user_helper_registration``:
this module only BUILDS the definition and the registration PowerShell. It
never writes to a real task store. Registration stays an explicit installer
step so the shape is testable without a Windows machine. Change the installer
files (PadiemPcConnect.cs / install-padiem-pc.ps1) belongs to #8223; that change
should only call ``task_definition`` + ``register_script`` from here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Owned, fixed name: re-registering replaces this product's task only.
TASK_NAME = "PadiemPcSelfHeal"
TASK_FOLDER = "\\Padiem\\"
#: Restarting the Mesh Agent service needs elevation. This is the SYSTEM task,
#: not the Limited user-session helper.
TRIGGER_TIMER = "TIMER"
LOGON_TYPE_SERVICE = "ServiceAccount"
RUN_LEVEL_HIGHEST = "Highest"
#: Five minutes matches the watcher's own default cadence and the issue's
#: "10 minutes to recover" acceptance target with two checks to spare.
INTERVAL_MINUTES = 5
MODULE = "kagent.local_agent_mesh_self_heal"
#: Flags the task must set so ``run_loop`` actually runs and may restart.
ENABLE_FLAG = "PADIEM_PC_SELF_HEAL"
RESTART_FLAG = "PADIEM_PC_SELF_HEAL_RESTART"


@dataclass(frozen=True, slots=True)
class SelfHealLaunch:
    """The exact command the SYSTEM task runs."""

    executable: str
    arguments: list[str]
    working_directory: str

    def command_line(self) -> str:
        return " ".join([_quote(self.executable)] + [_quote(arg) for arg in self.arguments])


def _quote(value: str) -> str:
    if not value:
        raise ValueError("an empty argument cannot be quoted")
    if any(char in value for char in ('"', "\r", "\n", "\x00")):
        raise ValueError("an argument may not contain a quote or a line break")
    return f'"{value}"' if " " in value else value


def build_launch(*, python_executable: str,
                 module: str = MODULE, working_directory: str = "") -> SelfHealLaunch:
    """Build the watcher launch. Module names are internal constants, never PC text."""

    if not python_executable:
        raise ValueError("a python executable is required")
    if not module or any(char in module for char in ('"', "\r", "\n", "\x00")):
        raise ValueError("the module is not usable")
    return SelfHealLaunch(
        executable=python_executable,
        arguments=["-m", module],
        working_directory=working_directory,
    )


def task_definition(*, launch: SelfHealLaunch) -> dict[str, Any]:
    """The SYSTEM task definition, as data; returned, never registered here."""

    return {
        "TaskName": TASK_NAME,
        "TaskPath": TASK_FOLDER,
        "Description": "PADIEM PC self-heal watcher (#8193). Checks Mesh Agent every 5 minutes.",
        "Trigger": {"Type": TRIGGER_TIMER, "Interval": "PT%dM" % INTERVAL_MINUTES},
        "Principal": {
            "UserId": "SYSTEM",
            "LogonType": LOGON_TYPE_SERVICE,
            "RunLevel": RUN_LEVEL_HIGHEST,
        },
        "Settings": {
            "MultipleInstances": "IgnoreNew",
            "DisallowStartIfOnBatteries": False,
            "StopIfGoingOnBatteries": False,
            "ExecutionTimeLimit": "PT0S",
        },
        "Action": {
            "Execute": launch.executable,
            "Argument": " ".join(_quote(arg) for arg in launch.arguments),
            "WorkingDirectory": launch.working_directory,
        },
        # Documented for the installer: run_loop returns unless ENABLE is on,
        # and never calls Restart-Service unless RESTART is on as well.
        "Environment": {
            ENABLE_FLAG: "on",
            RESTART_FLAG: "on",
        },
    }


def register_script(definition: dict[str, Any]) -> str:
    """PowerShell that registers the task, built from the definition."""

    def literal(value: str) -> str:
        return "'" + "".join(
            ch + ch if ch in "'\u2018\u2019\u201a\u201b" else ch for ch in str(value)
        ) + "'"

    trigger = definition["Trigger"]
    principal = definition["Principal"]
    action = definition["Action"]
    settings = definition["Settings"]
    env = definition.get("Environment", {})
    lines = [
        # SYSTEM task processes inherit machine-scope variables at start; the
        # installer runs elevated, so this is the one place they are set.
    ]
    for key, value in env.items():
        lines.append("[Environment]::SetEnvironmentVariable(" + literal(key)
                     + ", " + literal(value) + ", 'Machine')")
    return "\n".join(lines + [
        "$ErrorActionPreference = 'Stop'",
        "$action = New-ScheduledTaskAction -Execute " + literal(action["Execute"])
        + " -Argument " + literal(action["Argument"])
        + " -WorkingDirectory " + literal(action["WorkingDirectory"]),
        "$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval "
        + literal(trigger["Interval"]) + " -RepetitionDuration (New-TimeSpan -Days 3650)",
        "$principal = New-ScheduledTaskPrincipal -UserId " + literal(principal["UserId"])
        + " -LogonType " + literal(principal["LogonType"])
        + " -RunLevel " + literal(principal["RunLevel"]),
        "$settings = New-ScheduledTaskSettingsSet -MultipleInstances "
        + literal(settings["MultipleInstances"])
        + " -DisallowStartIfOnBatteries:$" + ("true" if settings["DisallowStartIfOnBatteries"] else "false")
        + " -StopIfGoingOnBatteries:$" + ("true" if settings["StopIfGoingOnBatteries"] else "false")
        + " -ExecutionTimeLimit " + literal(settings["ExecutionTimeLimit"]),
        "Register-ScheduledTask -TaskName " + literal(definition["TaskName"])
        + " -TaskPath " + literal(definition["TaskPath"])
        + " -Action $action -Trigger $trigger -Principal $principal -Settings $settings"
        + " -Description " + literal(definition["Description"]) + " -Force | Out-Null",
    ])


__all__ = [
    "TASK_NAME", "TASK_FOLDER", "TRIGGER_TIMER", "LOGON_TYPE_SERVICE",
    "RUN_LEVEL_HIGHEST", "INTERVAL_MINUTES", "MODULE", "ENABLE_FLAG",
    "RESTART_FLAG", "SelfHealLaunch", "build_launch", "task_definition",
    "register_script",
]
