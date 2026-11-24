"""One release-pinned refresh using the existing owner-authorized SYSTEM lane.

#8359 F7: the refresh also keeps the SYSTEM self-heal watcher (#8193) registered.
The watcher payload is the same fixed, offline bytes both installers embed; the
only thing the PC contributes is where its Python interpreter lives, read the
way the installer reads it (``PADIEM_PYTHON`` or ``python.exe`` on PATH). A PC
without an interpreter still gets its updater refreshed and says so.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from kagent.pc_self_heal_task import TASK_NAME as SELF_HEAL_TASK_NAME, render_watcher_command

from .pc_helper_update import helper_update_script, render_helper_updater_command

MAX_AGE = timedelta(seconds=180)
SOURCE_SHA256 = hashlib.sha256(helper_update_script().encode("utf-8")).hexdigest()
_DETAIL_PREFIX = "PADIEM_HELPER_REFRESH_DETAIL:"
# 원인 토큰 + 스크립트 줄번호 + 명령이름. 전체가 [a-z0-9_]{1,80} 안에 들어와야
# 한다(메시지 원문·경로는 절대 포함하지 않는다).
_DETAIL = re.compile(r"^PADIEM_HELPER_REFRESH_DETAIL:(?=.{1,80}$)([a-z0-9_]*_[0-9]+_[a-z0-9_]*)$")
_MARKER = re.compile(r"^PADIEM_HELPER_REFRESH:(updated|skipped|reinstall_required|failed):([a-z_]+)$")
_REASONS = {"updated": {"registered", "watcher_python_missing"}, "skipped": {"already_current"},
            "reinstall_required": {"status_missing", "system_denied"},
            "failed": {"registration_failed", "updater_running", "digest_unverified", "watcher_unregistered"}}


def plan_registration(row, *, system_allowed, now):
    """One bounded verdict per fresh observation.

    ``refresh`` is the #8240 updater refresh of an installed helper. ``install``
    (#8359 F6) is a helper that is not there to refresh: the status file is
    missing, or it is present but records no installed release (the executor
    reports both since #8385, as ``file_missing`` and ``release_unknown``).
    The install itself is the separate fixed command in ``pc_helper_install``;
    this plan never runs it, and the operator button never executes it.
    """
    if system_allowed is not True:
        return {"action": "reinstall_required", "reason": "system_denied"}
    state = (row or {}).get("state") or {}
    try:
        observed = datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
        if not timedelta(0) <= now - observed <= MAX_AGE:
            raise ValueError("stale")
    except (KeyError, TypeError, AttributeError, ValueError):
        return {"action": "failed", "reason": "observation_stale"}
    if state.get("helper_status_present") is False:
        return {"action": "install", "reason": "status_missing"}
    if state.get("helper_status_present") is not True:
        return {"action": "failed", "reason": "status_unknown"}
    if not state.get("helper_sha256"):
        return {"action": "install", "reason": "release_unknown"}
    if (state.get("updater_source_present") is not False
            and not state.get("updater_source_sha256")) or state.get("updater_task_present") is None:
        return {"action": "failed", "reason": "digest_unverified"}
    if state.get("updater_source_sha256") == SOURCE_SHA256 and state["updater_task_present"]:
        # #8359 F7: an observed absence of the self-heal watcher is a refresh
        # too; an executor that does not report the key (older build) is not.
        if state.get("self_heal_task_present") is False:
            return {"action": "refresh", "reason": "watcher_missing"}
        return {"action": "skipped", "reason": "already_current"}
    return {"action": "refresh", "reason": "source_changed"}


def registration_command():
    """Fixed repository bytes, never a downloaded script or request parameter.

    Recheck SYSTEM, the install record and the source at execution time, so
    stale observations and concurrent/repeated requests cannot renew the task.
    The established registration function performs its own ACL/install checks.
    """
    return (
        "& {$ErrorActionPreference='Stop';"
        "if([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18'){"
        "Write-Output 'PADIEM_HELPER_REFRESH:reinstall_required:system_denied';return};"
        "$root=[Environment]::GetFolderPath('CommonApplicationData');"
        r"$status=Join-Path $root 'Padiem\helper-status.json';"
        r"$scriptFile=Join-Path $root 'PadiemHelperUpdater\update.ps1';"
        "if(-not(Test-Path -LiteralPath $status -PathType Leaf)){"
        "Write-Output 'PADIEM_HELPER_REFRESH:reinstall_required:status_missing';return};"
        r"try{$task=Get-ScheduledTask -TaskPath '\Padiem\' -TaskName PadiemUserHelperUpdater -ErrorAction SilentlyContinue;"
        "$same=(Test-Path -LiteralPath $scriptFile -PathType Leaf) -and "
        "((Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash -eq '" + SOURCE_SHA256 + "');"
        # #8359 F7: the watcher task and the interpreter it needs, read the
        # installer's way. No interpreter means nothing to register, not a failure.
        r"$watcher=Get-ScheduledTask -TaskPath '\Padiem\' -TaskName " + SELF_HEAL_TASK_NAME + " -ErrorAction SilentlyContinue;"
        "$py=$env:PADIEM_PYTHON;if(-not $py){$pyCommand=Get-Command python.exe -ErrorAction SilentlyContinue;"
        "if($pyCommand){$py=$pyCommand.Source}};"
        "if($same -and $task -and ($watcher -or -not $py)){Write-Output 'PADIEM_HELPER_REFRESH:skipped:already_current';return};"
        "if($task -and $task.State -eq 'Running'){Write-Output 'PADIEM_HELPER_REFRESH:failed:updater_running';return};"
        "if(-not($same -and $task)){"
        + render_helper_updater_command() + ";"
        "if((Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash -ne '" + SOURCE_SHA256 + "' -or "
        r"-not(Get-ScheduledTask -TaskPath '\Padiem\' -TaskName PadiemUserHelperUpdater)){"
        "Write-Output 'PADIEM_HELPER_REFRESH:failed:digest_unverified';return}};"
        "if($py -and -not $watcher){$PythonExecutable=$py;"
        + render_watcher_command() + ";"
        r"if(-not(Get-ScheduledTask -TaskPath '\Padiem\' -TaskName " + SELF_HEAL_TASK_NAME + " -ErrorAction SilentlyContinue)){"
        "Write-Output 'PADIEM_HELPER_REFRESH:failed:watcher_unregistered';return}};"
        "if($py){Write-Output 'PADIEM_HELPER_REFRESH:updated:registered'}"
        "else{Write-Output 'PADIEM_HELPER_REFRESH:updated:watcher_python_missing'}"
        "}catch{Write-Output 'PADIEM_HELPER_REFRESH:failed:registration_failed';"
        # #8359 후속2: 원인 토큰 뒤에 던진 위치를 붙인다. 원인은 업데이트 스크립트의
        # [a-z_] 코드 또는 예외 형식 이름, 줄번호는 ScriptLineNumber, 명령이름은
        # MyCommand.Name에서 영문 소문자·숫자·밑줄만 남긴다. 메시지·경로는 넣지 않는다.
        "$d=[string]$_.Exception.Message;"
        "if($d -cnotmatch '^[a-z_]{1,60}$'){$d='unexpected_'+(([string]$_.Exception.GetType().Name) -replace '[^A-Za-z]','').ToLower()};"
        "if($d.Length -gt 60){$d=$d.Substring(0,60)};"
        "$ln=[string]$_.InvocationInfo.ScriptLineNumber;"
        "if($ln -cnotmatch '^[0-9]+$'){$ln='0'};"
        "$cm=(([string]$_.InvocationInfo.MyCommand.Name) -replace '[^A-Za-z0-9_]','').ToLower();"
        "$d=($d+'_'+$ln+'_'+$cm);"
        "if($d.Length -gt 80){$d=$d.Substring(0,80)};"
        "Write-Output ('" + _DETAIL_PREFIX + "'+$d)}}"
    )


def is_fixed_system_refresh_command(command, *, user_mode):
    """Exactly the repository's own SYSTEM refresh bytes, and nothing else.

    The minimum-version block exists so an old helper cannot run arbitrary
    commands; the one command that *repairs* an old helper is this fixed,
    release-pinned refresh. It is admitted by byte identity only, in SYSTEM
    mode only: a prefix, a suffix, an edited digest or the same text sent
    through the user lane is not the fixed command.
    """
    return user_mode is False and isinstance(command, str) and command == _FIXED_REFRESH_COMMAND


# Rendered once: the bytes are a pure function of the repository source.
_FIXED_REFRESH_COMMAND = registration_command()


def parse_receipt(text):
    matches = [m.groups() for line in (text or "").splitlines() if (m := _MARKER.fullmatch(line.strip()))]
    if len(matches) != 1 or matches[0][1] not in _REASONS[matches[0][0]]:
        return {"action": "failed", "reason": "receipt_unverified"}
    return {"action": matches[0][0], "reason": matches[0][1]}


def parse_refresh_detail(text):
    """The one bounded cause+location token a failed refresh prints, else None.

    The token is ``cause_line_command``: a lowercase cause, the script line
    number and the filtered cmdlet name. Only a single line that matches the
    whole compact format is accepted.
    """
    found = [m.group(1) for line in (text or "").splitlines() if (m := _DETAIL.fullmatch(line.strip()))]
    return found[0] if len(found) == 1 else None


def command_finished(dispatch):
    """A SYSTEM command that ran to completion.

    The SYSTEM lane often ends without an exit code (``termination`` is
    ``no_exit_code``) even when the script finished; the fixed marker it
    prints, and the later observation, decide the outcome, not that code.
    """
    if not isinstance(dispatch, dict) or dispatch.get("state") != "done":
        return False
    code = dispatch.get("exit_code")
    return code == 0 or (code is None and dispatch.get("termination") == "no_exit_code")
