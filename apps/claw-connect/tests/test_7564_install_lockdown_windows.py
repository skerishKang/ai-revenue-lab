"""#7564 (설치 단계) — the installers lock the helper's folder and secret, on real Windows.

The one-click install provisions the user-session helper in three lanes: the two
PowerShell files (one shared block) and the double-click program. Each of them
has to leave ``%ProgramData%\\Padiem`` so that only SYSTEM and administrators can
write there, the console user can read and run, and nobody else is named - and
has to do it without adopting a folder another account made first, without
keeping a secret that was already lying there, and without a moment in which the
new secret exists under looser permissions.

These tests run the shipped code itself against a sandbox folder:

* the PowerShell block is cut out of ``scripts/pc_pairing/install-padiem-pc.ps1``
  (padiem-chat's tests pin that the server-rendered file carries the same block)
  and dot-sourced by Windows PowerShell with ``%ProgramData%`` pointed at the
  sandbox;
* the program's functions are compiled from ``PadiemPcConnect.cs`` together with
  a small harness, by the compiler the build itself uses.

What each test reads back is the descriptor Windows reports for the object
(``Get-Acl``), never the installer's own word.

Two ways to stand in the sandbox. A process that holds the administrator role
(the CI runner) runs everything exactly as shipped: the owner is the
Administrators group. A developer's unelevated process cannot make an object the
Administrators group owns, so there the test names the current account in the
two places the installer names Administrators - and nothing else changes. No
test touches the machine's real ``%ProgramData%`` or its real helper task.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows descriptors and Windows PowerShell",
)

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts" / "pc_pairing" / "install-padiem-pc.ps1"
PROGRAM_SOURCE = REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs"
BLOCK_START = "# ---- the user-session helper the one-click install also provisions ----\n"
BLOCK_END = "\nfunction Format-PadiemCode {"

SYSTEM = "S-1-5-18"
ADMINISTRATORS = "S-1-5-32-544"
USERS = "S-1-5-32-545"
#: The console user of the sandbox. No account holds this SID; an entry may name
#: one all the same, which is exactly what makes it a clean stand-in.
CONSOLE_USER = "S-1-5-21-1111111111-2222222222-3333333333-1001"
FULL = 0x1F01FF
READ_EXECUTE = 0x1200A9
READ = 0x120089

_SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
POWERSHELL = _SYSTEM_ROOT / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
COMPILER = _SYSTEM_ROOT / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
OLD_PROGRAM = _SYSTEM_ROOT / "System32" / "PING.EXE"
NEW_PROGRAM = _SYSTEM_ROOT / "System32" / "whoami.exe"

_ALIASES = {
    "SY": SYSTEM, "BA": ADMINISTRATORS, "BU": USERS, "WD": "S-1-1-0",
    "AU": "S-1-5-11", "CO": "S-1-3-0", "IU": "S-1-5-4",
}
_RIGHTS = {"FA": FULL, "FR": READ, "FX": 0x1200A0, "FW": 0x120116, "GA": 0x10000000}


@dataclass(frozen=True)
class Stand:
    """Which accounts the installer names in this process (see the module note)."""

    shipped: bool
    me: str
    owner: str
    administrators: str

    @property
    def stand_in(self) -> str:
        return "" if self.shipped else self.me


@dataclass(frozen=True)
class Descriptor:
    owner: str
    protected: bool
    entries: frozenset


def _run(argv, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(part) for part in argv], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, check=False, **kwargs,
    )


def _powershell(script: Path, *arguments: str) -> subprocess.CompletedProcess:
    return _run([
        POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", script, *arguments,
    ])


def _values(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and re.fullmatch(r"[A-Z_0-9]+", key):
            found[key] = value
    return found


def _sid(token: str) -> str:
    return _ALIASES.get(token, token)


def _rights(token: str) -> int:
    if token.lower().startswith("0x"):
        return int(token, 16)
    value = 0
    for index in range(0, len(token), 2):
        value |= _RIGHTS[token[index:index + 2]]
    return value


def _parse(sddl: str) -> Descriptor:
    match = re.fullmatch(
        r"O:(?P<owner>.+?)(?:G:(?P<group>.+?))?D:(?P<flags>[A-Z]*)"
        r"(?P<entries>(?:\([^)]*\))*)(?:S:.*)?",
        sddl.strip(),
    )
    assert match, sddl
    entries = set()
    for kind, flags, rights, _object, _inherited, sid in re.findall(
        r"\(([^;]*);([^;]*);([^;]*);([^;]*);([^;]*);([^)]*)\)", match["entries"],
    ):
        assert kind == "A", sddl
        entries.add((
            _sid(sid), _rights(rights),
            frozenset(flags[index:index + 2] for index in range(0, len(flags), 2)),
        ))
    return Descriptor(_sid(match["owner"]), "P" in match["flags"], frozenset(entries))


def _descriptors(tmp_path: Path, *paths: Path) -> list[Descriptor]:
    """What Windows itself reports for each object, in one PowerShell run."""
    listing = tmp_path / "read-back-paths.txt"
    listing.write_text("\n".join(str(path) for path in paths), encoding="utf-8")
    reader = tmp_path / "read-back.ps1"
    reader.write_text(
        "param([string] $Listing)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "foreach ($path in [System.IO.File]::ReadAllLines($Listing)) {\n"
        "  [Console]::Out.WriteLine((Get-Acl -LiteralPath $path).Sddl)\n"
        "}\n",
        encoding="utf-8-sig",
    )
    done = _powershell(reader, str(listing))
    assert done.returncode == 0, done.stdout + done.stderr
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    assert len(lines) == len(paths), done.stdout
    return [_parse(line) for line in lines]


def _expected(stand: Stand, kind: str, user: str | None = CONSOLE_USER) -> Descriptor:
    inherit = frozenset({"OI", "CI"}) if kind == "folder" else frozenset()
    entries = {(SYSTEM, FULL, inherit), (stand.administrators, FULL, inherit)}
    if user:
        entries.add((user, READ if kind == "data" else READ_EXECUTE, inherit))
    return Descriptor(stand.owner, True, frozenset(entries))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junction(link: Path, target: Path) -> None:
    done = _run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)])
    assert done.returncode == 0, done.stdout + done.stderr


def _give_to_another_owner(stand: Stand, folder: Path) -> str:
    """Make ``folder`` one this install must not adopt; returns extra script text.

    As an administrator the folder is really handed to the ordinary Users
    group. Without the role an owner cannot be given away, so the installer's
    list of trusted owners is narrowed to SYSTEM instead - the folder's actual
    owner, read from the disk, is then not on it.
    """
    if stand.shipped:
        done = _run(["icacls.exe", str(folder), "/setowner", "*" + USERS])
        assert done.returncode == 0, done.stdout + done.stderr
        return ""
    return "function Get-PadiemHelperTrustedOwnerSids { return @($PadiemHelperSystemSid) }\n"


@pytest.fixture(scope="module")
def stand() -> Stand:
    done = _run([
        POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
        "$i=[Security.Principal.WindowsIdentity]::GetCurrent();"
        "[Console]::Out.WriteLine($i.User.Value);"
        "[Console]::Out.WriteLine((New-Object Security.Principal.WindowsPrincipal($i))"
        ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))",
    ])
    assert done.returncode == 0, done.stdout + done.stderr
    sid, role = [line.strip() for line in done.stdout.splitlines() if line.strip()][:2]
    if role == "True":
        return Stand(True, sid, ADMINISTRATORS, ADMINISTRATORS)
    return Stand(False, sid, sid, sid)


# ---------------------------------------------------------------------------
# 1. The PowerShell block, run by Windows PowerShell against a sandbox.
# ---------------------------------------------------------------------------

_PRELUDE = r"""param([string] $Block, [string] $ProgramData, [string] $StandIn, [string] $Url, [string] $Sha)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:ProgramData = $ProgramData
. $Block
# Never the machine's real helper task.
$PadiemUserHelperTaskName = "PadiemTest7564NoSuchTask"
if ($StandIn) {
  $PadiemHelperAdministratorsSid = $StandIn
  $PadiemHelperOwnerSid = $StandIn
}
$ConsoleUserSid = "S-1-5-21-1111111111-2222222222-3333333333-1001"
function Say([string] $Key, $Value) { [Console]::Out.WriteLine($Key + "=" + $Value) }
"""

#: The whole install, with the three things a sandbox cannot have replaced: the
#: console account, its SID, and the registration in the machine's task store.
_INSTALL = r"""
function Get-PadiemConsoleUser { return "PADIEMTEST\console" }
function Get-PadiemAccountSid { param([string] $Account) return $ConsoleUserSid }
$Registered = Join-Path $ProgramData "registered.log"
function Register-PadiemUserHelperTask {
  param([string] $HelperExe, [string] $SecretPath, [string] $DeviceId, [string] $ConsoleUser)
  $line = $HelperExe + "|" + $SecretPath + "|" + $DeviceId + "|" + $ConsoleUser + "|" + [int] (Test-Path -LiteralPath $SecretPath)
  [System.IO.File]::AppendAllText($Registered, $line + "`n")
  return $true
}
$result = Install-PadiemUserHelper -Url $Url -Sha256 $Sha -DeviceId "pd-test7564"
Say "RESULT" $result
Say "RESULT_TYPE" $result.GetType().Name
"""


@pytest.fixture(scope="module")
def block(tmp_path_factory) -> Path:
    """The helper block exactly as the wrapper ships it, as a file to dot-source."""
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    text = wrapper[wrapper.index(BLOCK_START):wrapper.index(BLOCK_END)]
    path = tmp_path_factory.mktemp("block") / "helper-block.ps1"
    # With a byte-order mark, the way both lanes ship: Windows PowerShell reads
    # a file without one in the machine's code page.
    path.write_text(text, encoding="utf-8-sig")
    return path


def _block_run(tmp_path: Path, block: Path, stand: Stand, body: str, *,
               url: str = "", sha: str = "") -> tuple[dict[str, str], str, Path]:
    program_data = tmp_path / "ProgramData"
    program_data.mkdir(exist_ok=True)
    script = tmp_path / "scenario.ps1"
    script.write_text(_PRELUDE + body, encoding="utf-8-sig")
    done = _powershell(script, str(block), str(program_data), stand.stand_in, url, sha)
    output = done.stdout + done.stderr
    assert done.returncode == 0, output
    return _values(done.stdout), output, program_data / "Padiem"


def test_block_makes_a_new_folder_with_inheritance_cut_and_only_the_named_accounts(
        tmp_path, block, stand):
    values, output, folder = _block_run(tmp_path, block, stand, r"""
$reason = Protect-PadiemHelperStateDir -Path $PadiemUserHelperStateDir -UserSid $ConsoleUserSid
Say "REASON" ("[" + $reason + "]")
Say "REASON_TYPE" $reason.GetType().Name
""")
    assert values["REASON"] == "[]", output
    assert values["REASON_TYPE"] == "String"
    (found,) = _descriptors(tmp_path, folder)
    # Inheritance is cut, and the three entries are the whole list: SYSTEM and
    # the administrators with full control, the console user reading and
    # running, each handed down to what is created inside.
    assert found == _expected(stand, "folder")
    assert found.protected
    assert not any("ID" in flags for _sid_, _rights_, flags in found.entries)
    assert {sid for sid, _rights_, _flags in found.entries} == {
        SYSTEM, stand.administrators, CONSOLE_USER,
    }


def test_block_refuses_a_folder_another_account_owns_and_changes_nothing(
        tmp_path, block, stand):
    program_data = tmp_path / "ProgramData"
    folder = program_data / "Padiem"
    folder.mkdir(parents=True)
    planted = folder / "planted.dll"
    planted.write_bytes(b"left here by somebody else")
    narrowed = _give_to_another_owner(stand, folder)
    (before,) = _descriptors(tmp_path, folder)
    # The link names a file that is not there: an install that got as far as
    # the download would fail on it, with a different reason.
    missing = (tmp_path / "never-downloaded.exe").as_uri()

    values, output, _ = _block_run(
        tmp_path, block, stand, narrowed + _INSTALL, url=missing, sha="0" * 64,
    )

    assert values["RESULT"] == "False", output
    assert values["RESULT_TYPE"] == "Boolean", output
    assert "사용자 세션 도우미 설치를 멈춘 이유: state_dir_owner_untrusted" in output
    assert "소유자가 관리자나 SYSTEM이 아니어서" in output
    # Nothing was adopted, written or registered - not even the status file.
    (after,) = _descriptors(tmp_path, folder)
    assert after == before
    assert sorted(child.name for child in folder.iterdir()) == ["planted.dll"]
    assert planted.read_bytes() == b"left here by somebody else"
    assert not (program_data / "registered.log").exists()
    assert not [child for child in program_data.iterdir() if "quarantine" in child.name]


def test_block_refuses_a_folder_that_is_a_link_and_leaves_its_target_alone(
        tmp_path, block, stand):
    program_data = tmp_path / "ProgramData"
    program_data.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "theirs.txt").write_text("theirs", encoding="utf-8")
    _junction(program_data / "Padiem", elsewhere)
    (before,) = _descriptors(tmp_path, elsewhere)

    values, output, _ = _block_run(
        tmp_path, block, stand, _INSTALL,
        url=(tmp_path / "never-downloaded.exe").as_uri(), sha="0" * 64,
    )

    assert values["RESULT"] == "False", output
    assert "사용자 세션 도우미 설치를 멈춘 이유: state_dir_is_a_link" in output
    (after,) = _descriptors(tmp_path, elsewhere)
    assert after == before
    assert sorted(child.name for child in elsewhere.iterdir()) == ["theirs.txt"]


def _old_install(tmp_path: Path) -> tuple[Path, Path, subprocess.Popen]:
    """A PC that was installed before this change, with its helper running.

    The folder carries whatever its parent hands down (the way the old installer
    left it), the old secret is still there, the old program is running out of
    the folder, and other things have been put beside them.
    """
    program_data = tmp_path / "ProgramData"
    folder = program_data / "Padiem"
    folder.mkdir(parents=True)
    (folder / "helper.secret").write_text("0ld" * 21 + "0\n", encoding="ascii")
    (folder / "helper-status.json").write_text('{"status":"installed"}\n', encoding="utf-8")
    shutil.copyfile(OLD_PROGRAM, folder / "padiem-user-helper.exe")
    (folder / "sub").mkdir()
    (folder / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "theirs.txt").write_text("theirs", encoding="utf-8")
    _junction(folder / "link", elsewhere)
    running = subprocess.Popen(
        [str(folder / "padiem-user-helper.exe"), "-n", "300", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return folder, elsewhere, running


def test_block_reinstalls_over_a_running_helper_an_old_secret_and_a_loose_folder(
        tmp_path, block, stand):
    folder, elsewhere, running = _old_install(tmp_path)
    old_secret = (folder / "helper.secret").read_text(encoding="ascii")
    (loose,) = _descriptors(tmp_path, folder)
    assert not loose.protected  # the starting point really is the inherited list
    source = tmp_path / "reviewed-helper.exe"
    shutil.copyfile(NEW_PROGRAM, source)
    try:
        values, output, _ = _block_run(
            tmp_path, block, stand, _INSTALL, url=source.as_uri(), sha=_sha256(source).upper(),
        )
        assert values["RESULT"] == "True", output
        assert values["RESULT_TYPE"] == "Boolean", output
        # The helper that was running is gone before its file is replaced.
        assert running.wait(timeout=15) is not None
    finally:
        if running.poll() is None:
            running.kill()

    secret = folder / "helper.secret"
    program = folder / "padiem-user-helper.exe"
    status = folder / "helper-status.json"
    found_folder, found_secret, found_program, found_status = _descriptors(
        tmp_path, folder, secret, program, status,
    )
    assert found_folder == _expected(stand, "folder")
    assert found_secret == _expected(stand, "data")
    assert found_program == _expected(stand, "program")
    assert found_status == _expected(stand, "data")

    # A new secret, in the shape the helper reads, that nothing printed.
    value = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", value)
    assert value != old_secret
    assert value.strip() not in output and old_secret.strip() not in output
    assert value.strip() not in status.read_text(encoding="utf-8")
    assert '"status":"installed"' in status.read_text(encoding="utf-8")
    # The program is the reviewed bytes, not the ones that were there.
    assert _sha256(program) == _sha256(source) != _sha256(OLD_PROGRAM)

    # Only the install's own three files stay. The subfolder and the link were
    # moved, whole and by name, into a folder only SYSTEM and administrators
    # open; what the link pointed at was never walked into.
    assert sorted(child.name for child in folder.iterdir()) == [
        "helper-status.json", "helper.secret", "padiem-user-helper.exe",
    ]
    (quarantine,) = [
        child for child in folder.parent.iterdir()
        if child.name.startswith("Padiem.quarantine-")
    ]
    assert sorted(child.name for child in quarantine.iterdir()) == ["link", "sub"]
    assert (quarantine / "sub" / "inner.txt").read_text(encoding="utf-8") == "inner"
    assert sorted(child.name for child in elsewhere.iterdir()) == ["theirs.txt"]
    (found_quarantine,) = _descriptors(tmp_path, quarantine)
    assert found_quarantine == _expected(stand, "folder", user=None)

    # The task was registered once, after the secret was in place.
    registered = (folder.parent / "registered.log").read_text(encoding="utf-8").splitlines()
    assert registered == [f"{program}|{secret}|pd-test7564|PADIEMTEST\\console|1"]

    # Installing again makes yet another secret: none is ever kept.
    again, output_again, _ = _block_run(
        tmp_path, block, stand, _INSTALL, url=source.as_uri(), sha=_sha256(source),
    )
    assert again["RESULT"] == "True", output_again
    second = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", second) and second not in (value, old_secret)
    (found_second,) = _descriptors(tmp_path, secret)
    assert found_second == _expected(stand, "data")
    assert not [child for child in folder.iterdir() if child.name.endswith(".new")]


def test_block_install_that_cannot_clear_the_folder_leaves_no_secret_to_start_from(
        tmp_path, block, stand):
    folder, _elsewhere, running = _old_install(tmp_path)
    source = tmp_path / "reviewed-helper.exe"
    shutil.copyfile(NEW_PROGRAM, source)
    # Somebody keeps a file inside the subfolder open, so it cannot be moved out.
    held = open(folder / "sub" / "inner.txt", "rb")  # noqa: SIM115 - held on purpose
    try:
        values, output, _ = _block_run(
            tmp_path, block, stand, _INSTALL, url=source.as_uri(), sha=_sha256(source),
        )
        running.wait(timeout=15)
    finally:
        held.close()
        if running.poll() is None:
            running.kill()

    assert values["RESULT"] == "False", output
    assert "사용자 세션 도우미 설치를 멈춘 이유: state_dir_foreign_content" in output
    # The old helper was ended, and nothing is left for a helper to start with:
    # no secret at all, and no registration.
    assert not (folder / "helper.secret").exists()
    assert not (folder.parent / "registered.log").exists()
    assert (folder / "sub" / "inner.txt").exists()


# ---------------------------------------------------------------------------
# 2. The double-click program's own functions, compiled with a harness.
# ---------------------------------------------------------------------------

_HARNESS = r"""
// #7564 test harness: compiled together with PadiemPcConnect.cs by the test,
// never shipped. It calls the install's own lock-down functions against a
// sandbox folder and prints what they answered, one KEY=VALUE per line.
using System;

namespace Padiem.Connect
{
    internal static class LockdownHarness
    {
        static PadiemPcConnect.HelperAccounts Accounts(string standIn)
        {
            if (standIn == "-")
            {
                return PadiemPcConnect.ShippedHelperAccounts();
            }
            string[] parts = standIn.Split(new[] { '|' });
            return new PadiemPcConnect.HelperAccounts(parts[0], parts[0],
                parts[1].Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries));
        }

        static int Main(string[] args)
        {
            try
            {
                string command = args[0];
                if (command == "shipped")
                {
                    PadiemPcConnect.HelperAccounts shipped = PadiemPcConnect.ShippedHelperAccounts();
                    Console.WriteLine("OWNER=" + shipped.Owner);
                    Console.WriteLine("ADMINISTRATORS=" + shipped.Administrators);
                    Console.WriteLine("TRUSTED=" + string.Join(",", shipped.TrustedOwners));
                    return 0;
                }
                string directory = args[1];
                PadiemPcConnect.HelperAccounts accounts = Accounts(args[2]);
                string user = args[3];
                if (command == "protect")
                {
                    Console.WriteLine("REASON=[" + PadiemPcConnect.ProtectHelperDirectory(
                        directory, user, accounts) + "]");
                }
                else if (command == "files")
                {
                    Console.WriteLine("REASON=[" + PadiemPcConnect.InstallHelperFiles(
                        directory, args[4], args[5], user, accounts, null) + "]");
                }
                else
                {
                    Console.WriteLine("UNKNOWN_COMMAND=1");
                    return 2;
                }
                return 0;
            }
            catch (Exception error)
            {
                Console.WriteLine("ERROR=" + error.GetType().Name);
                return 3;
            }
        }
    }
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory) -> Path:
    if not COMPILER.is_file():
        pytest.skip("the .NET Framework compiler the build uses is not on this machine")
    work = tmp_path_factory.mktemp("harness")
    shutil.copyfile(PROGRAM_SOURCE, work / "PadiemPcConnect.cs")
    (work / "LockdownHarness.cs").write_text(_HARNESS, encoding="utf-8")
    done = _run([
        COMPILER, "/nologo", "/noconfig", "/target:exe", "/platform:anycpu",
        "/codepage:65001", "/reference:System.dll", "/reference:System.Management.dll",
        "/main:Padiem.Connect.LockdownHarness", "/out:harness.exe",
        "PadiemPcConnect.cs", "LockdownHarness.cs",
    ], cwd=work)
    assert done.returncode == 0, done.stdout + done.stderr
    return work / "harness.exe"


def _accounts(stand: Stand, trusted: str | None = None) -> str:
    if stand.shipped and trusted is None:
        return "-"
    owner = ADMINISTRATORS if stand.shipped else stand.me
    return owner + "|" + (trusted if trusted is not None else SYSTEM + "," + stand.me)


def test_program_ships_with_administrators_as_owner_and_names_no_other_group(harness, stand):
    done = _run([harness, "shipped"])
    values = _values(done.stdout)
    assert done.returncode == 0, done.stdout + done.stderr
    assert values["OWNER"] == ADMINISTRATORS
    assert values["ADMINISTRATORS"] == ADMINISTRATORS
    # SYSTEM and the group always; the running account only when it is itself
    # an administrator (it is then the account doing the install).
    expected = [SYSTEM, ADMINISTRATORS] + ([stand.me] if stand.shipped else [])
    assert values["TRUSTED"].split(",") == expected


def test_program_makes_a_new_folder_with_inheritance_cut_and_only_the_named_accounts(
        tmp_path, harness, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.parent.mkdir()
    done = _run([harness, "protect", folder, _accounts(stand), CONSOLE_USER])
    assert _values(done.stdout).get("REASON") == "[]", done.stdout + done.stderr
    (found,) = _descriptors(tmp_path, folder)
    assert found == _expected(stand, "folder")
    assert not any("ID" in flags for _sid_, _rights_, flags in found.entries)


def test_program_refuses_a_folder_another_account_owns_and_changes_nothing(
        tmp_path, harness, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.mkdir(parents=True)
    (folder / "planted.dll").write_bytes(b"left here by somebody else")
    if stand.shipped:
        _give_to_another_owner(stand, folder)
        accounts = _accounts(stand)
    else:
        accounts = _accounts(stand, trusted=SYSTEM)
    (before,) = _descriptors(tmp_path, folder)
    done = _run([harness, "protect", folder, accounts, CONSOLE_USER])
    assert _values(done.stdout).get("REASON") == "[state_dir_owner_untrusted]", done.stdout
    (after,) = _descriptors(tmp_path, folder)
    assert after == before
    assert sorted(child.name for child in folder.iterdir()) == ["planted.dll"]


def test_program_refuses_a_folder_that_is_a_link(tmp_path, harness, stand):
    program_data = tmp_path / "ProgramData"
    program_data.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _junction(program_data / "Padiem", elsewhere)
    (before,) = _descriptors(tmp_path, elsewhere)
    done = _run([harness, "protect", program_data / "Padiem", _accounts(stand), CONSOLE_USER])
    assert _values(done.stdout).get("REASON") == "[state_dir_is_a_link]", done.stdout
    (after,) = _descriptors(tmp_path, elsewhere)
    assert after == before


def test_program_reinstalls_over_a_running_helper_an_old_secret_and_a_loose_folder(
        tmp_path, harness, stand):
    folder, elsewhere, running = _old_install(tmp_path)
    old_secret = (folder / "helper.secret").read_text(encoding="ascii")
    source = tmp_path / "reviewed-helper.exe"
    shutil.copyfile(NEW_PROGRAM, source)
    try:
        locked = _run([harness, "protect", folder, _accounts(stand), CONSOLE_USER])
        assert _values(locked.stdout).get("REASON") == "[]", locked.stdout + locked.stderr
        done = _run([
            harness, "files", folder, _accounts(stand), CONSOLE_USER, source, _sha256(source),
        ])
        assert _values(done.stdout).get("REASON") == "[]", done.stdout + done.stderr
        assert running.wait(timeout=15) is not None
    finally:
        if running.poll() is None:
            running.kill()

    secret = folder / "helper.secret"
    program = folder / "padiem-user-helper.exe"
    found_folder, found_secret, found_program = _descriptors(tmp_path, folder, secret, program)
    assert found_folder == _expected(stand, "folder")
    assert found_secret == _expected(stand, "data")
    assert found_program == _expected(stand, "program")
    value = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", value) and value != old_secret
    assert value.strip() not in done.stdout + done.stderr
    assert _sha256(program) == _sha256(source) != _sha256(OLD_PROGRAM)
    # The stale status of the old install is a plain file its installer owned,
    # so it stays until the new status replaces it; the subfolder and the link
    # are gone from the folder.
    assert sorted(child.name for child in folder.iterdir()) == [
        "helper-status.json", "helper.secret", "padiem-user-helper.exe",
    ]
    (quarantine,) = [
        child for child in folder.parent.iterdir()
        if child.name.startswith("Padiem.quarantine-")
    ]
    assert sorted(child.name for child in quarantine.iterdir()) == ["link", "sub"]
    assert sorted(child.name for child in elsewhere.iterdir()) == ["theirs.txt"]
    (found_quarantine,) = _descriptors(tmp_path, quarantine)
    assert found_quarantine == _expected(stand, "folder", user=None)

    again = _run([
        harness, "files", folder, _accounts(stand), CONSOLE_USER, source, _sha256(source),
    ])
    assert _values(again.stdout).get("REASON") == "[]", again.stdout + again.stderr
    second = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", second) and second not in (value, old_secret)
    assert not [child for child in folder.iterdir() if child.name.endswith(".new")]


def test_program_install_that_cannot_clear_the_folder_leaves_no_secret_to_start_from(
        tmp_path, harness, stand):
    folder, _elsewhere, running = _old_install(tmp_path)
    source = tmp_path / "reviewed-helper.exe"
    shutil.copyfile(NEW_PROGRAM, source)
    held = open(folder / "sub" / "inner.txt", "rb")  # noqa: SIM115 - held on purpose
    try:
        locked = _run([harness, "protect", folder, _accounts(stand), CONSOLE_USER])
        assert _values(locked.stdout).get("REASON") == "[]", locked.stdout + locked.stderr
        done = _run([
            harness, "files", folder, _accounts(stand), CONSOLE_USER, source, _sha256(source),
        ])
        running.wait(timeout=15)
    finally:
        held.close()
        if running.poll() is None:
            running.kill()
    assert _values(done.stdout).get("REASON") == "[state_dir_foreign_content]", done.stdout
    assert not (folder / "helper.secret").exists()


def test_program_refuses_a_program_whose_placed_bytes_are_not_the_reviewed_ones(
        tmp_path, harness, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.parent.mkdir()
    source = tmp_path / "reviewed-helper.exe"
    shutil.copyfile(NEW_PROGRAM, source)
    locked = _run([harness, "protect", folder, _accounts(stand), CONSOLE_USER])
    assert _values(locked.stdout).get("REASON") == "[]", locked.stdout + locked.stderr
    done = _run([harness, "files", folder, _accounts(stand), CONSOLE_USER, source, "0" * 64])
    assert _values(done.stdout).get("REASON") == "[sha256_mismatch]", done.stdout
    assert list(folder.iterdir()) == []
