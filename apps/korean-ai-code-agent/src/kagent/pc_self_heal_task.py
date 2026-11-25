"""#8193 — the SYSTEM scheduled-task definition for the PC self-heal watcher.

The watcher itself lives in ``local_agent_mesh_self_heal.run_loop``. Nothing
registers it today, so a machine never runs the check and the ops report stays
empty. This module gives the installer (#8223) one call to get the exact task
shape: name, executable command, SYSTEM privilege and cadence.

Deliberate boundary, mirroring ``claw_connect.user_helper_registration``:
this module only BUILDS the definition and the fixed registration/removal
PowerShell payloads. It never writes to a real task store. Registration stays
an explicit installer step so the shape is testable without a Windows machine.
Both installers (PadiemPcConnect.cs / install-padiem-pc.ps1) embed
``render_watcher_command`` and its ``unregister=True`` variant; the removal
path calls the latter. The shape is fixed here and pinned by tests.
"""
from __future__ import annotations

import base64
import gzip
import re
import sys
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
DESCRIPTION = "PADIEM PC self-heal watcher (#8193). Checks Mesh Agent every 5 minutes."
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


def _ps_literal(value: str) -> str:
    # PowerShell closes a single-quoted string on five characters; each is
    # doubled. Same escaping as the helper registration's fixed payload.
    return "'" + "".join(
        ch + ch if ch in "'\u2018\u2019\u201a\u201b" else ch for ch in str(value)
    ) + "'"


def _interval_minutes(value: str) -> int:
    """The data model keeps ISO strings; the cmdlet needs a TimeSpan."""

    match = re.fullmatch(r"PT(\d+)M", str(value))
    return int(match.group(1)) if match else INTERVAL_MINUTES


def _iso_seconds(value: str) -> int:
    """ExecutionTimeLimit도 ISO 문자열 그대로 넘기면 인자 변환에 실패한다."""

    match = re.fullmatch(r"PT(\d+)S", str(value))
    return int(match.group(1)) if match else 0


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
        "Description": DESCRIPTION,
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

    literal = _ps_literal
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
        # #8359 후속3: -RepetitionInterval은 TimeSpan이어야 한다. ISO 문자열을
        # 그대로 넘기면 인자 변환에 실패한다.
        "$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval "
        + "(New-TimeSpan -Minutes %d)" % _interval_minutes(trigger["Interval"])
        + " -RepetitionDuration (New-TimeSpan -Days 3650)",
        "$principal = New-ScheduledTaskPrincipal -UserId " + literal(principal["UserId"])
        + " -LogonType " + literal(principal["LogonType"])
        + " -RunLevel " + literal(principal["RunLevel"]),
        "$settings = New-ScheduledTaskSettingsSet -MultipleInstances "
        + literal(settings["MultipleInstances"])
        + " -DisallowStartIfOnBatteries:$" + ("true" if settings["DisallowStartIfOnBatteries"] else "false")
        + " -StopIfGoingOnBatteries:$" + ("true" if settings["StopIfGoingOnBatteries"] else "false")
        + " -ExecutionTimeLimit (New-TimeSpan -Seconds %d)" % _iso_seconds(settings["ExecutionTimeLimit"]),
        "Register-ScheduledTask -TaskName " + literal(definition["TaskName"])
        + " -TaskPath " + literal(definition["TaskPath"])
        + " -Action $action -Trigger $trigger -Principal $principal -Settings $settings"
        + " -Description " + literal(definition["Description"]) + " -Force | Out-Null",
    ])


def unregister_script() -> str:
    """PowerShell that removes only this product's own task (#8225 removal path)."""

    select = "-TaskPath " + _ps_literal(TASK_FOLDER) + " -TaskName " + _ps_literal(TASK_NAME)
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$task = Get-ScheduledTask " + select + " -ErrorAction SilentlyContinue",
        "if ($task) {",
        "    Unregister-ScheduledTask " + select + " -Confirm:$false",
        "}",
    ])


def watcher_script() -> str:
    """The fixed, offline payload both installers embed for the SYSTEM task.

    The Python executable is a parameter because only the installer on the PC
    knows where its interpreter lives. No remote script, machine-name exclusion
    or caller-supplied task name enters this payload: #8225 removed the old
    single-host exception, so every managed PC registers the same owned task.
    """
    lines = [
        "param([string]$PythonExecutable, [switch]$Unregister)",
        "$ErrorActionPreference = 'Stop'",
        "$taskPath = " + _ps_literal(TASK_FOLDER),
        "$taskName = " + _ps_literal(TASK_NAME),
        "if ($Unregister) {",
        "    if (Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue) {",
        "        Unregister-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Confirm:$false",
        "    }",
        "    exit 0",
        "}",
        "if (-not $PythonExecutable) { throw 'python_executable_missing' }",
    ]
    for key, value in ((ENABLE_FLAG, "on"), (RESTART_FLAG, "on")):
        lines.append("[Environment]::SetEnvironmentVariable(" + _ps_literal(key)
                     + ", " + _ps_literal(value) + ", 'Machine')")
    lines += [
        "$action = New-ScheduledTaskAction -Execute $PythonExecutable -Argument "
        + _ps_literal("-m " + MODULE),
        # #8359 후속3: ISO 문자열('PT5M')은 TimeSpan으로 변환되지 않아 등록이
        # 실패한다. 설치 프로그램과 유지보수가 같은 페이로드를 쓰므로 여기서
        # 함께 고친다.
        "$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval "
        + "(New-TimeSpan -Minutes %d)" % INTERVAL_MINUTES
        + " -RepetitionDuration (New-TimeSpan -Days 3650)",
        "$principal = New-ScheduledTaskPrincipal -UserId " + _ps_literal("SYSTEM")
        + " -LogonType " + _ps_literal(LOGON_TYPE_SERVICE)
        + " -RunLevel " + _ps_literal(RUN_LEVEL_HIGHEST),
        "$settings = New-ScheduledTaskSettingsSet -MultipleInstances "
        + _ps_literal("IgnoreNew") + " -ExecutionTimeLimit (New-TimeSpan -Seconds 0)",
        "Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath"
        + " -Action $action -Trigger $trigger -Principal $principal -Settings $settings"
        + " -Description " + _ps_literal(DESCRIPTION) + " -Force | Out-Null",
    ]
    return "\n".join(lines)


def render_watcher_command(*, unregister: bool = False) -> str:
    """A fixed, gzip-backed offline PowerShell command, like the updater's."""

    payload = base64.b64encode(
        gzip.compress(watcher_script().encode("utf-8"), mtime=0)
    ).decode("ascii")
    action = ("& ([scriptblock]::Create($source)) -Unregister" if unregister
              else "& ([scriptblock]::Create($source)) -PythonExecutable $PythonExecutable")
    return (
        "$b=[Convert]::FromBase64String('" + payload + "');"
        "$ms=[IO.MemoryStream]::new($b);"
        "$gz=[IO.Compression.GZipStream]::new($ms,[IO.Compression.CompressionMode]::Decompress);"
        "$reader=[IO.StreamReader]::new($gz);$source=$reader.ReadToEnd();$reader.Dispose();"
        + action
    )


def render_watcher_installer_block() -> str:
    """The wrapper function embedded in the PowerShell single-file installer."""

    return ("function Register-PadiemSelfHealWatcher {\n"
            "  param([string]$PythonExecutable)\n"
            "  " + render_watcher_command() + "\n}\n")


def default_python_executable() -> str:
    """The interpreter already running the installer, never read from PATH."""

    return sys.executable


__all__ = [
    "TASK_NAME", "TASK_FOLDER", "TRIGGER_TIMER", "LOGON_TYPE_SERVICE",
    "RUN_LEVEL_HIGHEST", "INTERVAL_MINUTES", "MODULE", "DESCRIPTION",
    "ENABLE_FLAG", "RESTART_FLAG", "SelfHealLaunch", "build_launch",
    "task_definition", "register_script", "unregister_script", "watcher_script",
    "render_watcher_command", "render_watcher_installer_block",
    "default_python_executable",
]
