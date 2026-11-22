"""#8359 F6: the fixed fresh-install command and its switch-gated linkage.

No dispatch happens anywhere in this module: the command is rendered and
inspected as bytes, the plan maps to it only behind two switches that are off
by default, and the operator route reports an install without executing it.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import re
from types import SimpleNamespace

import pytest

from app.pc_helper_auto_update import (
    AUTO_INSTALL_SWITCH, AUTO_UPDATE_SWITCH, auto_install_enabled, command_for_plan,
)
from app.pc_helper_install import (
    INSTALL_BLOCK, INSTALL_BLOCK_SHA256, install_command, install_script, install_source_sha256,
    is_fixed_system_install_command, parse_install_receipt, release_pinned,
)
from app.pc_helper_registration import registration_command
from app.pc_helper_update import render_helper_updater_installer_block
from app.pc_helper_version_routes import helper_manifest
from app.pc_pairing_agent_install import render_user_helper_install_block

HELPER = "e" * 64
OTHER = "f" * 64


def _manifest(version="0.3.0-rc2", sha=HELPER):
    return helper_manifest(SimpleNamespace(
        pc_pairing_user_helper_url="https://downloads.padiem.net/pc-helper/" + version + "/padiem-user-helper.exe",
        pc_pairing_user_helper_sha256=sha))


def _unpack(command):
    """The source the PC would run: the one base64 payload, gunzipped."""
    found = re.fullmatch(
        r"\$b=\[Convert\]::FromBase64String\('([A-Za-z0-9+/=]+)'\);"
        r"\$ms=\[IO\.MemoryStream\]::new\(\$b\);"
        r"\$gz=\[IO\.Compression\.GZipStream\]::new\(\$ms,\[IO\.Compression\.CompressionMode\]::Decompress\);"
        r"\$reader=\[IO\.StreamReader\]::new\(\$gz\);\$source=\$reader\.ReadToEnd\(\);\$reader\.Dispose\(\);"
        r"& \(\[scriptblock\]::Create\(\$source\)\)", command)
    assert found is not None, "the command carries exactly one payload and no other text"
    return gzip.decompress(base64.b64decode(found.group(1))).decode("utf-8")


def test_install_block_is_the_installers_own_bytes():
    assert INSTALL_BLOCK == render_user_helper_install_block() + "\n" + render_helper_updater_installer_block()
    assert INSTALL_BLOCK_SHA256 == hashlib.sha256(INSTALL_BLOCK.encode("utf-8")).hexdigest()
    # The block defines the provisioning the command calls and the updater
    # registration it ends with; it never touches the self-heal watcher (F7).
    for needle in ("function Install-PadiemUserHelper", "function Get-PadiemHelperDeviceId",
                   "function Register-PadiemHelperUpdater", "Register-PadiemHelperUpdater\n"):
        assert needle in INSTALL_BLOCK
    assert "SelfHeal" not in INSTALL_BLOCK and "%" not in INSTALL_BLOCK


def test_only_the_immutable_release_path_is_pinned():
    assert release_pinned(_manifest())
    for bad in (None, {}, {**_manifest(), "sha256": "E" * 64}, {**_manifest(), "version": "0.3.0-rc3"},
                {**_manifest(), "download_url": "https://example.com/padiem-user-helper.exe"},
                {**_manifest(), "download_url": _manifest()["download_url"] + "?x=1"}):
        assert not release_pinned(bad)
    with pytest.raises(ValueError):
        install_script({**_manifest(), "sha256": "E" * 64})


def test_command_is_fixed_per_release_and_carries_only_the_pinned_release():
    manifest = _manifest()
    command = install_command(manifest)
    assert command == install_command(_manifest())
    assert install_source_sha256(manifest) == hashlib.sha256(command.encode("utf-8")).hexdigest()
    assert install_command(_manifest(sha=OTHER)) != command
    assert install_command(_manifest(version="0.3.0-rc3")) != command
    assert install_source_sha256(_manifest(sha=OTHER)) != install_source_sha256(manifest)
    assert command != registration_command()
    source = _unpack(command)
    assert source == install_script(manifest)
    # SYSTEM first, then the idempotent skip, then the installer's own block.
    assert source.index("S-1-5-18") < source.index("Test-PadiemInstalledRelease") < source.index(INSTALL_BLOCK)
    assert "$PadiemUserHelperUrl='" + manifest["download_url"] + "'" in source
    assert "$PadiemUserHelperSha256='" + HELPER + "'" in source
    assert "-DeviceId (Get-PadiemHelperDeviceId -Tag '')" in source
    # Nothing but the pinned release is fetched by this source (the updater it
    # registers carries its own fixed manifest endpoint inside its payload); the
    # only other "https" text is the installer's release-path pattern.
    addresses = {found for found in re.findall(r"https://[^\s'\"]+", source) if "\\" not in found}
    assert addresses == {manifest["download_url"]}
    assert OTHER not in source
    for marker in ("PADIEM_HELPER_INSTALL:reinstall_required:system_denied",
                   "PADIEM_HELPER_INSTALL:skipped:already_installed",
                   "PADIEM_HELPER_INSTALL:failed:provision_failed",
                   "PADIEM_HELPER_INSTALL:failed:digest_unverified",
                   "PADIEM_HELPER_INSTALL:installed:provisioned",
                   "PADIEM_HELPER_INSTALL:failed:install_failed"):
        assert source.count(marker) == 1


def test_fixed_install_command_is_byte_identity_in_system_mode_only():
    manifest = _manifest()
    command = install_command(manifest)
    assert is_fixed_system_install_command(command, manifest=manifest, user_mode=False)
    assert not is_fixed_system_install_command(command, manifest=manifest, user_mode=True)
    assert not is_fixed_system_install_command(command, manifest=manifest, user_mode=None)
    assert not is_fixed_system_install_command(command, manifest=_manifest(sha=OTHER), user_mode=False)
    assert not is_fixed_system_install_command(command, manifest=None, user_mode=False)
    for near in (command + ";whoami", "whoami;" + command, command[:-1], " " + command,
                 registration_command(), "", None, command.encode()):
        assert not is_fixed_system_install_command(near, manifest=manifest, user_mode=False)


def test_install_receipt_is_one_bounded_marker():
    assert parse_install_receipt("PADIEM_HELPER_INSTALL:installed:provisioned") == {
        "action": "installed", "reason": "provisioned"}
    assert parse_install_receipt("noise\nPADIEM_HELPER_INSTALL:skipped:already_installed\n") == {
        "action": "skipped", "reason": "already_installed"}
    for text in ("", None, "PADIEM_HELPER_INSTALL:installed:other",
                 "PADIEM_HELPER_REFRESH:updated:registered",
                 "PADIEM_HELPER_INSTALL:installed:provisioned\nPADIEM_HELPER_INSTALL:failed:install_failed"):
        assert parse_install_receipt(text) == {"action": "failed", "reason": "receipt_unverified"}


def test_plan_maps_to_fixed_bytes_only_behind_the_switches():
    manifest = _manifest()
    refresh, install = {"action": "refresh", "reason": "source_changed"}, {"action": "install", "reason": "status_missing"}
    off = {}
    update_only = {AUTO_UPDATE_SWITCH: "1"}
    both = {AUTO_UPDATE_SWITCH: "true", AUTO_INSTALL_SWITCH: "on"}
    install_only = {AUTO_INSTALL_SWITCH: "1"}
    # Default: nothing runs.
    assert command_for_plan(refresh, manifest=manifest, env=off) is None
    assert command_for_plan(install, manifest=manifest, env=off) is None
    assert not auto_install_enabled(off) and not auto_install_enabled(install_only)
    # The refresh opens with the first switch; the install needs the second one too.
    assert command_for_plan(refresh, manifest=manifest, env=update_only) == ("refresh", registration_command())
    assert command_for_plan(install, manifest=manifest, env=update_only) is None
    assert command_for_plan(install, manifest=manifest, env=install_only) is None
    assert command_for_plan(install, manifest=manifest, env=both) == ("install", install_command(manifest))
    assert command_for_plan({**install, "reason": "release_unknown"}, manifest=manifest, env=both) == (
        "install", install_command(manifest))
    # An unpinned release renders nothing even with both switches on.
    assert command_for_plan(install, manifest=None, env=both) is None
    assert command_for_plan(install, manifest={**manifest, "sha256": "E" * 64}, env=both) is None
    # Every other verdict has nothing to run.
    for plan in ({"action": "reinstall_required", "reason": "system_denied"},
                 {"action": "failed", "reason": "observation_stale"},
                 {"action": "skipped", "reason": "already_current"}, {}, None, "install"):
        assert command_for_plan(plan, manifest=manifest, env=both) is None
