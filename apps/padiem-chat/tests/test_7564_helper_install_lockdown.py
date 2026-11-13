"""#7564 (설치 단계) — the one-click install locks the helper's folder and secret.

``%ProgramData%`` lets every local account create files inside a child folder,
so a helper folder that simply inherits is one another account on the same PC
can put a file into, and a secret that is kept across installs is one whoever
wrote it first already knows. The install therefore:

* makes the folder with inheritance cut and three accounts named - SYSTEM and
  the Administrators group in full, the console user reading and running - or,
  when the folder is already there, adopts it only from an owner it trusts and
  otherwise stops and says why;
* writes a new secret on every install, into a file that carries its
  descriptor from the moment it exists, under a name nothing reads yet;
* ends a helper that is still running, clears out what does not belong, reads
  the finished install back from the disk, and only then registers the task.

The behaviour itself is walked on real Windows by
``apps/claw-connect/tests/test_7564_install_lockdown_windows.py`` (Windows
PowerShell runs the block, and the program's functions are compiled with a
harness). This file pins the shipped text on every OS, so neither PowerShell
lane and not the program can drift back to the inherited folder or the kept
secret without a failure here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.pc_device_pairing_routes import render_install_script  # noqa: E402
from app.pc_pairing_agent_install import (  # noqa: E402
    render_agent_install_block,
    render_user_helper_install_block,
)

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts" / "pc_pairing" / "install-padiem-pc.ps1"
PROGRAM = REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs"
GUIDE = REPO / "docs" / "operations" / "PC_CONNECT_EXE_20261028.md"
AGENT_URL = "https://mesh.example.padiem.net/meshagents?id=4&meshid=c9yfFkUpi38"
HELPER_URL = "https://downloads.example.padiem.net/pc-helper/padiem-user-helper-7108.exe"
HELPER_SHA = "0123456789abcdef" * 4

BLOCK = render_user_helper_install_block()


def _rendered() -> str:
    script = render_install_script(
        install_tag="pd-1234abcd", agent_url=AGENT_URL,
        user_helper_url=HELPER_URL, user_helper_sha256=HELPER_SHA,
    )
    assert script is not None
    return script


def _function(text: str, name: str) -> str:
    start = text.index("function " + name + " {")
    end = text.find("\nfunction ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def _method(source: str, signature: str) -> str:
    start = source.index(signature)
    end = source.index("\n        }\n", start)
    return source[start:end]


# -- 1. who is named ---------------------------------------------------------

def test_accounts_are_sids_and_the_owner_is_the_administrators_group() -> None:
    assert '$PadiemHelperSystemSid = "S-1-5-18"' in BLOCK
    assert '$PadiemHelperAdministratorsSid = "S-1-5-32-544"' in BLOCK
    assert "$PadiemHelperOwnerSid = $PadiemHelperAdministratorsSid" in BLOCK
    # Each is assigned once, in the block, and nowhere else in either lane: a
    # real install has no second place that could name a different owner.
    assignment = re.compile(r"^\s*\$PadiemHelper(?:System|Administrators|Owner)Sid\s*=", re.M)
    for lane in (_rendered(), WRAPPER.read_text(encoding="utf-8-sig")):
        assert len(assignment.findall(lane)) == 3
    # No display name a localized Windows spells differently, and no tool that
    # takes one.
    for gone in ("icacls", '"SYSTEM:(R)"', ":(M)", "Administrators:", "BUILTIN"):
        assert gone not in BLOCK, gone


def test_the_descriptors_name_system_administrators_and_the_console_user_only() -> None:
    builder = _function(BLOCK, "Get-PadiemHelperSddl")
    # Inheritance is cut ("P"), and the entries are these three and no fourth.
    assert '"D:PAI(A;"' in builder
    assert BLOCK.count("(A;") == 3
    assert '";FA;;;" + $PadiemHelperSystemSid' in builder
    assert '";FA;;;" + $PadiemHelperAdministratorsSid' in builder
    assert '";;;" + $UserSid + ")"' in builder
    # The console user reads and runs the folder and the program, and only
    # reads the secret and the status.
    assert '$rights = if ($Kind -eq "data") { "0x120089" } else { "0x1200a9" }' in builder
    assert '$inherit = if ($Kind -eq "folder") { "OICI" } else { "" }' in builder
    # A value that is not a SID never reaches the descriptor string.
    assert builder.count("-notmatch $pattern") == 2
    for broad in (";;;WD", ";;;BU", ";;;AU", ";;;IU", "S-1-1-0", "S-1-5-32-545", "S-1-5-11"):
        assert broad not in BLOCK, broad


def test_only_the_installing_administrator_is_trusted_beside_system_and_the_group() -> None:
    trusted = _function(BLOCK, "Get-PadiemHelperTrustedOwnerSids")
    assert "$trusted = @($PadiemHelperSystemSid, $PadiemHelperAdministratorsSid)" in trusted
    # The running account joins the list only when it holds the administrator
    # role - it is then the account doing this install.
    role = trusted.index("IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)")
    assert role < trusted.index("$trusted += $identity.User.Value")
    assert trusted.count("$trusted +=") == 1


# -- 2. the folder -----------------------------------------------------------

def test_a_folder_that_is_there_is_checked_before_it_is_touched() -> None:
    protect = _function(BLOCK, "Protect-PadiemHelperStateDir")
    adopt = protect.index("$refusal = Test-PadiemHelperFolderAdoptable -Path $Path")
    refuse = protect.index("if ($refusal) { return $refusal }")
    apply = protect.index("[System.IO.Directory]::SetAccessControl($Path, $security)")
    create = protect.index("[System.IO.Directory]::CreateDirectory($Path, $security)")
    read_back = protect.index('Test-PadiemHelperSecurity -Path $Path -Kind "folder"')
    assert adopt < refuse < apply < create < read_back
    assert 'return "state_dir_acl_unverified"' in protect

    adoptable = _function(BLOCK, "Test-PadiemHelperFolderAdoptable")
    assert 'return "state_dir_is_a_link"' in adoptable
    assert 'return "state_dir_owner_untrusted"' in adoptable
    assert "@(Get-PadiemHelperTrustedOwnerSids) -notcontains $owner" in adoptable
    # An owner that cannot be read is not a trusted owner.
    assert "if (-not $owner -or" in adoptable


def test_the_folder_and_every_file_exist_only_with_their_descriptor() -> None:
    # Created already carrying it: no moment with the inherited list.
    assert "[System.IO.Directory]::CreateDirectory($Path, $security)" in BLOCK
    locked = _function(BLOCK, "New-PadiemHelperLockedFile")
    assert "[System.IO.FileMode]::CreateNew" in locked
    assert "[System.IO.FileOptions]::None, $security)" in locked
    # The three files all go through that one function.
    assert 'New-PadiemHelperLockedFile -Path $pending -Kind "program"' in BLOCK
    assert BLOCK.count('New-PadiemHelperLockedFile -Path $pending -Kind "data"') == 2
    # The ways the old install made them are gone from the block.
    for gone in (
        "New-Item -ItemType Directory -Path $PadiemUserHelperStateDir",
        "Copy-Item -LiteralPath $temp -Destination $PadiemUserHelperExe",
        "System.IO.StreamWriter(",
        "Set-PadiemHelperSecretAcl",
    ):
        assert gone not in BLOCK, gone
    # A new file is renamed in after the old one is removed; it is never
    # merged into the old file, which would keep the old owner and entries.
    move = _function(BLOCK, "Move-PadiemHelperFileIntoPlace")
    assert move.index("[System.IO.File]::Delete($Target)") \
        < move.index("[System.IO.File]::Move($Source, $Target)")
    assert "::Replace(" not in BLOCK


# -- 3. the secret -----------------------------------------------------------

def test_a_secret_that_is_already_there_is_never_read_back_or_kept() -> None:
    install = _function(BLOCK, "Install-PadiemUserHelper")
    # Unconditional: the line is a statement of its own, not the body of a test
    # for whether a secret exists.
    (line,) = [
        text for text in install.splitlines()
        if "New-PadiemHelperSecret -Path $PadiemUserHelperSecret" in text
    ]
    assert line.strip() == (
        "New-PadiemHelperSecret -Path $PadiemUserHelperSecret -UserSid $userSid"
    )
    for gone in (
        "Test-Path -LiteralPath $PadiemUserHelperSecret",
        "(Get-Item -LiteralPath $PadiemUserHelperSecret)",
        "OpenRead($PadiemUserHelperSecret",
        "Get-Content",
        "ReadAllText",
        "ReadAllBytes",
    ):
        assert gone not in BLOCK, gone
    secret = _function(BLOCK, "New-PadiemHelperSecret")
    assert "New-Object byte[] 32" in secret and "RandomNumberGenerator" in secret
    assert secret.index("New-PadiemHelperLockedFile -Path $pending") \
        < secret.index("Move-PadiemHelperFileIntoPlace -Source $pending -Target $Path")


def test_the_reason_is_said_and_the_secret_never_is() -> None:
    for line in BLOCK.splitlines():
        if "Write-Host" in line or "Write-Output" in line:
            for value in ("PadiemUserHelperSecret", "$hex", "$bytes", "$payload"):
                assert value not in line, line
    failure = _function(BLOCK, "Write-PadiemHelperFailure")
    assert 'Write-Host ("사용자 세션 도우미 설치를 멈춘 이유: " + $reason)' in failure
    assert "소유자가 관리자나 SYSTEM이 아니어서" in failure
    # The status is local evidence, written only into a folder the install
    # would adopt and never through a file that was already lying there.
    status = _function(BLOCK, "Write-PadiemHelperStatus")
    assert "if (Test-PadiemHelperFolderAdoptable -Path $PadiemUserHelperStateDir) { return }" in status
    assert "New-Item" not in status and "$PadiemUserHelperSecret" not in status


# -- 4. the order of an install ------------------------------------------------

def test_nothing_is_downloaded_stopped_or_written_before_the_folder_is_adopted() -> None:
    install = _function(BLOCK, "Install-PadiemUserHelper")
    lock = install.index(
        "$refusal = Protect-PadiemHelperStateDir -Path $PadiemUserHelperStateDir -UserSid $userSid"
    )
    refused = install.index("if ($refusal) {", lock)
    leaves = install.index("return $false", refused)
    download = install.index("Invoke-WebRequest -Uri $Url -OutFile $temp")
    stop = install.index("Stop-PadiemUserHelper -HelperExe $PadiemUserHelperExe")
    assert lock < refused < leaves < download < stop
    # The console user is resolved to a SID first; without one nothing starts.
    assert install.index("$userSid = Get-PadiemAccountSid -Account $consoleUser") < lock


def test_an_install_that_was_not_read_back_leaves_no_secret_to_start_from() -> None:
    install = _function(BLOCK, "Install-PadiemUserHelper")
    stopped = install.index("$stopped = $true")
    fault = install.index("$fault = Get-PadiemHelperInstallFault -UserSid $userSid")
    verified = install.index("$verified = $true")
    task = install.index("Register-PadiemUserHelperTask -HelperExe $PadiemUserHelperExe")
    assert stopped < fault < verified < task
    guard = install.index("if ($stopped -and -not $verified) {")
    assert install.index("finally {") < guard
    removal = install.index(
        "Remove-Item -LiteralPath $PadiemUserHelperSecret -Force", guard,
    )
    assert removal - guard < 400
    read_back = _function(BLOCK, "Get-PadiemHelperInstallFault")
    for kind in ('"folder"', '"program"', '"data"'):
        assert "-Kind " + kind in read_back


def test_a_running_helper_is_ended_and_the_task_record_is_waited_for() -> None:
    stop = _function(BLOCK, "Stop-PadiemUserHelper")
    assert stop.index("Stop-ScheduledTask -TaskName $PadiemUserHelperTaskName") \
        < stop.index("$process.Kill()")
    # Only a process running this exact file is ended.
    assert "[string]::Equals($image, $HelperExe, [System.StringComparison]::OrdinalIgnoreCase)" in stop
    assert '([string] $task.State -ne "Running")' in stop


def test_what_does_not_belong_is_moved_by_name_and_never_walked() -> None:
    clear = _function(BLOCK, "Move-PadiemHelperForeignContent")
    assert "[System.IO.Directory]::Move($child.FullName, $destination)" in clear
    assert "[System.IO.File]::Move($child.FullName, $destination)" in clear
    assert "-Recurse" not in BLOCK
    # The place it goes to is itself created locked, with no user entry.
    assert 'New-PadiemHelperSecurity -Kind "folder" -UserSid $null' in clear
    assert 'Test-PadiemHelperSecurity -Path $quarantine -Kind "folder" -UserSid $null' in clear


def test_neither_block_carries_a_percent_sign() -> None:
    # The server-rendered lane fills its template with the percent operator; a
    # stray sign in a block breaks the whole install file.
    assert "%" not in BLOCK
    assert "%" not in render_agent_install_block()
    assert BLOCK in _rendered()


# -- 5. the double-click program runs the same lock-down -----------------------

def test_the_program_names_the_same_accounts_and_builds_the_same_descriptors() -> None:
    source = PROGRAM.read_text(encoding="utf-8")
    assert 'internal const string SystemSid = "S-1-5-18";' in source
    assert 'internal const string AdministratorsSid = "S-1-5-32-544";' in source
    shipped = _method(source, "internal static HelperAccounts ShippedHelperAccounts()")
    assert "return new HelperAccounts(AdministratorsSid, AdministratorsSid, trusted.ToArray());" in shipped
    assert shipped.count("trusted.Add(") == 3
    assert "IsInRole(WindowsBuiltInRole.Administrator)" in shipped
    # The install has one place that makes the accounts, and it is that one.
    assert source.count("new HelperAccounts(") == 1
    # ... and the two places that use accounts (the install, the status) both
    # take them from it.
    assert source.count("HelperAccounts accounts = ShippedHelperAccounts();") == 2

    sddl = _method(source, "internal static string HelperSddl(")
    assert '"D:PAI(A;"' in sddl and sddl.count("(A;") == 3
    assert 'string inherit = kind == "folder" ? "OICI" : "";' in sddl
    assert 'string rights = kind == "data" ? "0x120089" : "0x1200a9";' in sddl
    for gone in ("icacls", "File.Exists(UserHelperSecretPath())", "SetUserHelperSecretAcl"):
        assert gone not in source, gone


def test_the_program_walks_the_same_order() -> None:
    source = PROGRAM.read_text(encoding="utf-8")
    provision = _method(source, "static string ProvisionUserHelper(")
    order = [
        provision.index("ProtectHelperDirectory(directory, userSid, accounts)"),
        provision.index("Download(url, temp)"),
        provision.index("Sha256Hex(temp)"),
        provision.index("InstallHelperFiles(directory, temp, sha, userSid, accounts,"),
        provision.index("RegisterUserHelperTask("),
    ]
    assert order == sorted(order)

    files = _method(source, "internal static string InstallHelperFiles(")
    order = [
        files.index("StopUserHelper(program, taskPath)"),
        files.index("QuarantineForeignContent(directory, accounts,"),
        files.index("PlaceHelperProgram(sourceExe, program, sha256, userSid, accounts)"),
        files.index("WriteHelperSecret(secret, userSid, accounts)"),
        files.index("HelperInstallFault(directory, userSid, accounts)"),
        files.index("verified = true;"),
        files.index("if (stopped && !verified)"),
        files.index("File.Delete(secret)"),
    ]
    assert order == sorted(order)

    protect = _method(source, "internal static string ProtectHelperDirectory(")
    assert protect.index("FolderAdoptionRefusal(path, accounts)") \
        < protect.index("Directory.SetAccessControl(path, security)") \
        < protect.index("Directory.CreateDirectory(path, security)") \
        < protect.index('HelperSecurityMatches(path, "folder", userSid, accounts)')
    locked = _method(source, "internal static FileStream CreateLockedFile(")
    assert "FileMode.CreateNew" in locked
    # The status goes through the same locked writer, into an adoptable folder.
    status = _method(source, "static void WriteUserHelperStatus(")
    assert "FolderAdoptionRefusal(directory, accounts).Length > 0" in status
    assert "WriteLockedFile(UserHelperStatusPath()" in status
    assert "File.WriteAllText" not in status


# -- 6. the guide says what the install leaves behind --------------------------

def test_the_install_guide_states_the_lock_down() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    assert "#7564" in guide
    for said in ("S-1-5-32-544", "state_dir_owner_untrusted", "매번 새로"):
        assert said in guide, said
    # The old description of the secret's access list is gone.
    assert "`SYSTEM:(R)`" not in guide
