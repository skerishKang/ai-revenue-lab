"""#8359 F6: the fixed, release-pinned fresh install of the user-session helper.

#8240's refresh command repairs the *updater* of a helper that is already
installed; on a PC with no ``helper-status.json`` it stops at
``reinstall_required:status_missing``. The Owner's rule for managed PCs is
"no hands", so a missing helper needs a second fixed command that provisions
it the way the one-click installer does. Everything below is bytes the
repository already ships for that installer (the locked-folder helper block
and the updater registration block) plus the deployment's reviewed release
values; nothing comes from a request, a database row or an observation.

Rendering only. This module never dispatches: a caller still has to pass the
managed-PC, owner-session and switch checks, and the switches
(``PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED`` and ``PADIEM_PC_HELPER_AUTO_INSTALL_ENABLED``)
are off by default.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import re

from .pc_helper_update import render_helper_updater_installer_block
from .pc_pairing_agent_install import render_user_helper_install_block

#: The repository half of the install source: the helper provisioning block
#: and the updater registration it ends with. Deployment-independent.
INSTALL_BLOCK = render_user_helper_install_block() + "\n" + render_helper_updater_installer_block()
INSTALL_BLOCK_SHA256 = hashlib.sha256(INSTALL_BLOCK.encode("utf-8")).hexdigest()

_MARKER = re.compile(r"^PADIEM_HELPER_INSTALL:(installed|skipped|reinstall_required|failed):([a-z_]+)$")
_REASONS = {"installed": {"provisioned"}, "skipped": {"already_installed"},
            "reinstall_required": {"system_denied"},
            "failed": {"provision_failed", "digest_unverified", "install_failed"}}
_VERSION = re.compile(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:-rc[0-9]{1,5})?")
_RELEASE_URL = re.compile(
    r"https://downloads\.padiem\.net/pc-helper/" + _VERSION.pattern + r"/padiem-user-helper\.exe")


def release_pinned(manifest) -> bool:
    """Only the immutable release path with a 64-hex digest may be installed.

    The same shape the installer's status write recognises as versioned: a
    different host, a query, or a mutable path is not a release and renders
    nothing. ``helper_manifest`` already refuses most of this; the check is
    repeated here because this function is the last one before the bytes exist.
    """
    if not isinstance(manifest, dict):
        return False
    url, sha, version = manifest.get("download_url"), manifest.get("sha256"), manifest.get("version")
    return (isinstance(url, str) and _RELEASE_URL.fullmatch(url) is not None
            and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) is not None
            and isinstance(version, str) and _VERSION.fullmatch(version) is not None
            and url == "https://downloads.padiem.net/pc-helper/" + version + "/padiem-user-helper.exe")


def install_script(manifest) -> str:
    """The PowerShell source the fixed command carries, for one release.

    Order: refuse outside SYSTEM; skip when this exact release is already
    installed and recorded; otherwise run the installer's own helper
    provisioning (locked folder, download, SHA-256 check, new secret, logon
    task, status, updater registration) and read the install back from disk
    before claiming it. Every outcome is one bounded marker line.
    """
    if not release_pinned(manifest):
        raise ValueError("helper release is not pinned")
    from .pc_helper_registration import registration_command

    sha = manifest["sha256"]
    return (
        "$ErrorActionPreference='Stop'\n"
        "if([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18'){"
        "Write-Output 'PADIEM_HELPER_INSTALL:reinstall_required:system_denied';return}\n"
        "$padiemRoot=[Environment]::GetFolderPath('CommonApplicationData')\n"
        r"$padiemStatus=Join-Path $padiemRoot 'Padiem\helper-status.json'" "\n"
        r"$padiemExe=Join-Path $padiemRoot 'Padiem\padiem-user-helper.exe'" "\n"
        "function Test-PadiemInstalledRelease {\n"
        "  if(-not (Test-Path -LiteralPath $padiemStatus -PathType Leaf)){return $false}\n"
        "  if(-not (Test-Path -LiteralPath $padiemExe -PathType Leaf)){return $false}\n"
        "  $record=$null\n"
        "  try{$record=ConvertFrom-Json ([IO.File]::ReadAllText($padiemStatus))}catch{return $false}\n"
        "  if(-not $record -or $record.status -ne 'installed'){return $false}\n"
        "  return ((Get-FileHash -LiteralPath $padiemExe -Algorithm SHA256).Hash.ToLowerInvariant() -eq '" + sha + "')\n"
        "}\n"
        "try{\n"
        "  if(Test-PadiemInstalledRelease){Write-Output 'PADIEM_HELPER_INSTALL:skipped:already_installed';return}\n"
        + INSTALL_BLOCK + "\n"
        "  $PadiemUserHelperUrl='" + manifest["download_url"] + "'\n"
        "  $PadiemUserHelperSha256='" + sha + "'\n"
        "  $padiemOk=Install-PadiemUserHelper -Url $PadiemUserHelperUrl -Sha256 $PadiemUserHelperSha256 "
        "-DeviceId (Get-PadiemHelperDeviceId -Tag '')\n"
        "  if(-not $padiemOk){Write-Output 'PADIEM_HELPER_INSTALL:failed:provision_failed';return}\n"
        "  if(-not (Test-PadiemInstalledRelease)){Write-Output 'PADIEM_HELPER_INSTALL:failed:digest_unverified';return}\n"
        "  $maint=@(" + registration_command() + ")\n"
        "  if(-not($maint -contains 'PADIEM_HELPER_REFRESH:updated:registered' -or "
        "$maint -contains 'PADIEM_HELPER_REFRESH:skipped:already_current')){throw 'maintenance registration failed'}\n"
        "  Write-Output 'PADIEM_HELPER_INSTALL:installed:provisioned'\n"
        "}catch{Write-Output 'PADIEM_HELPER_INSTALL:failed:install_failed'}\n"
    )


def install_command(manifest) -> str:
    """Fixed bytes for one deployment release; the same shape as the refresh command.

    The whole source travels inside the command (gzip + base64), so the PC
    downloads nothing but the release the manifest names, and nothing on the
    wire can add a flag or a path.
    """
    payload = base64.b64encode(gzip.compress(install_script(manifest).encode("utf-8"), mtime=0)).decode("ascii")
    return (
        "$b=[Convert]::FromBase64String('" + payload + "');"
        "$ms=[IO.MemoryStream]::new($b);"
        "$gz=[IO.Compression.GZipStream]::new($ms,[IO.Compression.CompressionMode]::Decompress);"
        "$reader=[IO.StreamReader]::new($gz);$source=$reader.ReadToEnd();$reader.Dispose();"
        "& ([scriptblock]::Create($source))"
    )


def install_source_sha256(manifest) -> str:
    """The attempt key for a fresh install: the digest of the exact command bytes.

    It changes when the repository blocks change or when the deployment pins
    another release, and never otherwise - the "once per PC and source" rule
    of #8359 step 1 keys on it.
    """
    return hashlib.sha256(install_command(manifest).encode("utf-8")).hexdigest()


def is_fixed_system_install_command(command, *, manifest, user_mode) -> bool:
    """Byte identity with this deployment's rendered install command, SYSTEM only."""
    if user_mode is not False or not isinstance(command, str) or not release_pinned(manifest):
        return False
    return command == install_command(manifest)


def parse_install_receipt(text):
    matches = [m.groups() for line in (text or "").splitlines() if (m := _MARKER.fullmatch(line.strip()))]
    if len(matches) != 1 or matches[0][1] not in _REASONS[matches[0][0]]:
        return {"action": "failed", "reason": "receipt_unverified"}
    return {"action": matches[0][0], "reason": matches[0][1]}


__all__ = [
    "INSTALL_BLOCK", "INSTALL_BLOCK_SHA256", "install_command", "install_script",
    "install_source_sha256", "is_fixed_system_install_command", "parse_install_receipt",
    "release_pinned",
]
