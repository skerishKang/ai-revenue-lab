"""One release-pinned refresh using the existing owner-authorized SYSTEM lane."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from .pc_helper_update import helper_update_script, render_helper_updater_command

MAX_AGE = timedelta(seconds=180)
SOURCE_SHA256 = hashlib.sha256(helper_update_script().encode("utf-8")).hexdigest()
_MARKER = re.compile(r"^PADIEM_HELPER_REFRESH:(updated|skipped|reinstall_required|failed):([a-z_]+)$")
_REASONS = {"updated": {"registered"}, "skipped": {"already_current"},
            "reinstall_required": {"status_missing", "system_denied"},
            "failed": {"registration_failed", "updater_running", "digest_unverified"}}


def plan_registration(row, *, system_allowed, now):
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
        return {"action": "reinstall_required", "reason": "status_missing"}
    if state.get("helper_status_present") is not True or not state.get("helper_sha256"):
        return {"action": "failed", "reason": "status_unknown"}
    if (state.get("updater_source_present") is not False
            and not state.get("updater_source_sha256")) or state.get("updater_task_present") is None:
        return {"action": "failed", "reason": "digest_unverified"}
    if state.get("updater_source_sha256") == SOURCE_SHA256 and state["updater_task_present"]:
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
        "if($same -and $task){Write-Output 'PADIEM_HELPER_REFRESH:skipped:already_current';return};"
        "if($task -and $task.State -eq 'Running'){Write-Output 'PADIEM_HELPER_REFRESH:failed:updater_running';return};"
        + render_helper_updater_command() + ";"
        "if((Get-FileHash -LiteralPath $scriptFile -Algorithm SHA256).Hash -ne '" + SOURCE_SHA256 + "' -or "
        r"-not(Get-ScheduledTask -TaskPath '\Padiem\' -TaskName PadiemUserHelperUpdater)){"
        "Write-Output 'PADIEM_HELPER_REFRESH:failed:digest_unverified';return};"
        "Write-Output 'PADIEM_HELPER_REFRESH:updated:registered'"
        "}catch{Write-Output 'PADIEM_HELPER_REFRESH:failed:registration_failed'}}"
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
