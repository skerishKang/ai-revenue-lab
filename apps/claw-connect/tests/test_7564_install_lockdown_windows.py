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
  a small harness, by the compiler the build itself uses;
* the Connector's own unelevated lane (``claw_connect.user_helper_provisioning``)
  is called with its real Windows calls and a sandbox folder.

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
from types import SimpleNamespace

import pytest

from claw_connect import user_helper_provisioning as provisioning

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
                if (command == "taskrunning")
                {
                    Console.WriteLine("RUNNING=" + (PadiemPcConnect.HelperTaskRunning(args[1]) ? "1" : "0"));
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


def _task_states() -> dict[str, str]:
    """Every scheduled task this machine has, by full path, with its state."""
    listed = _run([
        POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false);"
        "Get-ScheduledTask | Where-Object { $_.TaskPath -and $_.TaskName } |"
        " ForEach-Object { [Console]::Out.WriteLine(([string] $_.State) + '|' + $_.TaskPath + $_.TaskName) }",
    ])
    assert listed.returncode == 0, listed.stdout + listed.stderr
    states: dict[str, str] = {}
    for line in listed.stdout.splitlines():
        state, _separator, path = line.partition("|")
        if path:
            states[path] = state
    return states


def test_program_reads_whether_a_task_is_running_from_the_task_store_itself(harness):
    """Read-only: the state of tasks this machine already has, never changed."""
    before = _task_states()
    assert before, "this machine lists no scheduled task to read"
    # A few of each kind: the tasks that are running now, and ones that are not.
    running = [path for path, state in before.items() if state == "Running"][:5]
    resting = [path for path, state in before.items() if state != "Running"][:5]
    answers = {
        path: _values(_run([harness, "taskrunning", path]).stdout).get("RUNNING")
        for path in running + resting
    }
    after = _task_states()
    compared = 0
    for path, answer in answers.items():
        # A task may start or stop between the reads; only a task whose state
        # did not move is evidence either way.
        if before[path] != after.get(path):
            continue
        assert answer == ("1" if before[path] == "Running" else "0"), (path, before[path])
        compared += 1
    assert compared > 0
    missing = _run([harness, "taskrunning", "\\Padiem\\PadiemTest7564NoSuchTask"])
    assert _values(missing.stdout).get("RUNNING") == "0", missing.stdout


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


# ---------------------------------------------------------------------------
# 3. The Connector's own lane: unelevated, with its real Windows calls.
# ---------------------------------------------------------------------------

DEVICE = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"


def _connector(tmp_path: Path, folder: Path, **overrides):
    root = tmp_path / "ClawConnect"
    (root / "claw_connect").mkdir(parents=True, exist_ok=True)
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = provisioning.provision_user_helper(
        device_id=DEVICE, state_dir=root, secret_dir=folder, user=r"PC\padiem",
        run=run, python_executable=sys.executable, **overrides,
    )
    return result, calls


def _connector_expected(stand: Stand, kind: str) -> Descriptor:
    # This lane has no elevation: the user owns what it makes and is the third
    # account beside SYSTEM and the Administrators group.
    inherit = frozenset({"OI", "CI"}) if kind == "folder" else frozenset()
    return Descriptor(stand.me, True, frozenset({
        (SYSTEM, FULL, inherit),
        (ADMINISTRATORS, FULL, inherit),
        (stand.me, FULL if kind == "folder" else READ, inherit),
    }))


def test_connector_lane_locks_a_new_folder_and_writes_a_new_secret_each_time(tmp_path, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.parent.mkdir()
    result, calls = _connector(tmp_path, folder)
    assert result["status"] == "installed", result
    secret = folder / "helper.secret"
    found_folder, found_secret = _descriptors(tmp_path, folder, secret)
    assert found_folder == _connector_expected(stand, "folder")
    assert found_secret == _connector_expected(stand, "data")
    assert not any("ID" in flags for _sid_, _rights_, flags in found_secret.entries)
    first = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", first)
    # Windows PowerShell by the path the OS reports, never by a bare name.
    assert calls and all(Path(call[0]) == POWERSHELL for call in calls)
    assert all(first.strip() not in call[-1] for call in calls)

    again, _calls = _connector(tmp_path, folder)
    assert again["status"] == "installed", again
    second = secret.read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{64}\n", second) and second != first
    (found_again,) = _descriptors(tmp_path, secret)
    assert found_again == _connector_expected(stand, "data")
    assert [child.name for child in folder.iterdir()] == ["helper.secret"]


def test_connector_lane_locks_a_loose_folder_it_owns_and_drops_the_old_secret(tmp_path, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.mkdir(parents=True)
    (folder / "helper.secret").write_text("5" * 64 + "\n", encoding="ascii")
    (loose,) = _descriptors(tmp_path, folder)
    assert not loose.protected and loose.owner == stand.me
    result, _calls = _connector(tmp_path, folder)
    assert result["status"] == "installed", result
    found_folder, found_secret = _descriptors(tmp_path, folder, folder / "helper.secret")
    assert found_folder == _connector_expected(stand, "folder")
    assert found_secret == _connector_expected(stand, "data")
    assert (folder / "helper.secret").read_text(encoding="ascii") != "5" * 64 + "\n"


def test_connector_lane_leaves_a_folder_it_does_not_own_exactly_as_it_is(tmp_path, stand):
    folder = tmp_path / "ProgramData" / "Padiem"
    folder.mkdir(parents=True)
    (folder / "helper.secret").write_text("5" * 64 + "\n", encoding="ascii")
    if stand.shipped:
        # Really handed to another owner.
        _give_to_another_owner(stand, folder)
        overrides = {}
    else:
        # Without the administrator role an owner cannot be given away, so the
        # lane is told it runs as a different account than the folder's owner.
        class Another(provisioning.WindowsSecurity):
            def current_user_sid(self) -> str:
                return CONSOLE_USER

        overrides = {"security": Another()}
    (before,) = _descriptors(tmp_path, folder)

    result, calls = _connector(tmp_path, folder, **overrides)

    assert result["status"] == "not_installed", result
    assert result["reason"] == "state_dir_owner_untrusted", result
    assert calls == []
    (after,) = _descriptors(tmp_path, folder)
    assert after == before
    assert (folder / "helper.secret").read_text(encoding="ascii") == "5" * 64 + "\n"


def test_connector_lane_refuses_a_folder_that_is_a_link(tmp_path, stand):
    program_data = tmp_path / "ProgramData"
    program_data.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _junction(program_data / "Padiem", elsewhere)
    result, calls = _connector(tmp_path, program_data / "Padiem")
    assert result["status"] == "not_installed", result
    assert result["reason"] == "state_dir_is_a_link", result
    assert calls == [] and list(elsewhere.iterdir()) == []


# ---------------------------------------------------------------------------
# 4. The two scripts that only look: the manual installer's refusal and the
#    read-only diagnosis.
# ---------------------------------------------------------------------------

MANUAL_INSTALLER = REPO / "apps" / "claw-connect" / "install_user_helper.ps1"
DIAGNOSIS = REPO / "apps" / "claw-connect" / "tools" / "check-user-helper.ps1"


def _function(source: Path, name: str) -> str:
    """One function's own text, cut out of a script that cannot be dot-sourced."""
    text = source.read_text(encoding="utf-8-sig")
    start = text.index("function " + name)
    end = text.index("\nfunction ", start + 1)
    return text[start:end] + "\n"


def _judge(tmp_path: Path, function: str, call: str, *targets: Path) -> list[str]:
    script = tmp_path / "judge.ps1"
    script.write_text(
        "Set-StrictMode -Version Latest\n"
        "$ErrorActionPreference = 'Stop'\n"
        + function
        + "foreach ($target in $args) { [Console]::Out.WriteLine('[' + (" + call + ") + ']') }\n",
        encoding="utf-8-sig",
    )
    done = _powershell(script, *[str(target) for target in targets])
    assert done.returncode == 0, done.stdout + done.stderr
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _locked_and_open(tmp_path: Path) -> tuple[Path, Path]:
    """A secret the Connector lane really locked, and one in a plain folder."""
    locked = tmp_path / "ProgramData" / "Padiem"
    locked.parent.mkdir()
    result, _calls = _connector(tmp_path, locked)
    assert result["status"] == "installed", result
    open_folder = tmp_path / "ProgramData" / "Open"
    open_folder.mkdir()
    (open_folder / "helper.secret").write_text("5" * 64 + "\n", encoding="ascii")
    return locked, open_folder


def test_manual_installer_refuses_a_secret_other_accounts_can_reach(tmp_path):
    locked, open_folder = _locked_and_open(tmp_path)
    answers = _judge(
        tmp_path, _function(MANUAL_INSTALLER, "Get-SecretRefusal"),
        "Get-SecretRefusal -Path $target",
        locked / "helper.secret", open_folder / "helper.secret",
    )
    assert answers[0] == "[]", answers
    # The reason names the object, never what is in it.
    assert answers[1].startswith("[inherits its access list from the folder above: "), answers
    assert "5555" not in answers[1]
    source = MANUAL_INSTALLER.read_text(encoding="utf-8")
    # The check sits before anything is registered or stopped.
    assert source.index("$secretRefusal = Get-SecretRefusal -Path $SecretFile") \
        < source.index("\nStop-HelperTask\n") \
        < source.index("Register-ScheduledTask -TaskName $TaskName")


def test_diagnosis_tool_tells_a_locked_folder_from_an_open_one(tmp_path):
    locked, open_folder = _locked_and_open(tmp_path)
    answers = _judge(
        tmp_path, _function(DIAGNOSIS, "Test-OnlyTrustedAccounts"),
        "Test-OnlyTrustedAccounts (Get-Acl -LiteralPath $target)",
        locked, locked / "helper.secret", open_folder, open_folder / "helper.secret",
    )
    assert answers == ["[True]", "[True]", "[False]", "[False]"], answers


def test_diagnosis_tool_runs_read_only_and_reports_the_folder(tmp_path):
    done = _powershell(DIAGNOSIS)
    values = _values(done.stdout)
    # 0 OK, 1 WARN, 2 FAIL: whatever this machine's helper is, the tool ends
    # with a verdict, and the new section answers either way.
    assert done.returncode in (0, 1, 2), done.stdout + done.stderr
    assert values.get("VERDICT") in ("OK", "WARN", "FAIL"), done.stdout + done.stderr
    assert values.get("INSTALL_DIR_PRESENT") in ("true", "false"), done.stdout
    if values["INSTALL_DIR_PRESENT"] == "true":
        assert values.get("INSTALL_DIR_LOCKED") in ("True", "False"), done.stdout
        assert re.fullmatch(r"S-1-[0-9-]+", values.get("INSTALL_DIR_OWNER_SID", "")), done.stdout
