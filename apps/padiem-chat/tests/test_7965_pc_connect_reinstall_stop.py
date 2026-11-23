"""#7965: a reinstall stops the running agent wherever it was registered.

The AI customer round of 2026-11-18 hit this on a real PC: an agent installed at
07:57 was running from ``C:\\Program Files\\PADIEM\\MeshAgent.exe``, the very
path a reinstall is about to write, and the old stop rule - "stop only when the
registered path differs" - therefore skipped the stop on every reinstall. The
copy onto the locked file failed, and the message the person saw ("폴더를 만들
수 없습니다") named nothing they could do.

Two layers here:

* Source assertions that run everywhere: the walk calls ``StopInstalledAgent``,
  the skip is gone, the stop is verified through the service's own state
  (``QueryServiceStatus``) with ``sc.exe`` as the fallback, and a replacement
  that still fails says the customer's own next step.
* A compiled harness (the same Framework compiler the build uses) that exercises
  ``NormalizeAgentImagePath`` against real files - a quoted path with arguments
  the way the surface's own registry record looks, an unquoted path with spaces
  and arguments, and the fallbacks - plus ``ServiceIsRunning`` on a name that is
  guaranteed absent. ``StopInstalledAgent`` itself is only run where the real
  "Mesh Agent" service is not installed, so the harness can never stop somebody's
  own agent.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.reinstall_selfheal_sidebar_source import (
    app_js, build_script, index_html, install_wrapper, one_click_test_source, read,
)

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PROGRAM_SOURCE = REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs"

_SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
COMPILER = _SYSTEM_ROOT / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
#: A name no machine ships with, so the state read is deterministic.
ABSENT_SERVICE = "Mesh Agent #7965 Absent"


def _source() -> str:
    return read(PROGRAM_SOURCE)


def test_a_reinstall_stops_the_running_agent_wherever_it_was_registered() -> None:
    """The walk stops first and checks, instead of hoping the path differs."""
    source = _source()
    assert "StopInstalledAgent();" in source
    # The old rule skipped the stop when the registered path matched, which is
    # what every reinstall looks like; the comparison must be gone.
    assert "!running.Equals(durable" not in source
    assert "internal static bool StopInstalledAgent()" in source
    # The stop is verified against the service's own state, not assumed.
    assert "QueryServiceStatus" in source
    assert "internal static bool ServiceIsRunning" in source
    assert "static bool WaitServiceStopped" in source
    # sc.exe is the fallback when the agent's own -stop does not land.
    assert '"stop \\"' + '" + AgentServiceName' in source


def test_the_registered_path_is_normalized_before_it_is_used() -> None:
    """Quotes and arguments come off, and a real file decides the answer."""
    source = _source()
    assert "internal static string NormalizeAgentImagePath" in source
    assert "return NormalizeAgentImagePath(text);" in source
    # The longest existing prefix wins, so an unquoted "C:\Program Files\..."
    # record is not cut at its first space.
    assert "File.Exists(text)" in source
    assert "LastIndexOf(' '," in source


def test_a_failed_replacement_says_the_customers_own_next_step() -> None:
    """A reinstall that still cannot replace names the restart walk, not a hint."""
    source = _source()
    assert "PC를 다시 시작한 뒤, 새 파일을 받아 10분 안에 다시 실행해 주세요." in source
    # The old folder message stays only where it is true - a first install.
    assert source.count("에이전트를 놓을 폴더를 만들 수 없습니다") == 1


_HARNESS = """
// #7965 test harness: compiled together with PadiemPcConnect.cs by the test,
// exercising the ImagePath normalization and the verified stop on this machine.
using System;
using System.IO;
using System.Text;

namespace Padiem.Connect
{
    internal static class ReinstallHarness
    {
        static int Main(string[] arguments)
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            string command = arguments.Length > 0 ? arguments[0] : "";
            if (command == "NORMALIZE" && arguments.Length > 1)
            {
                string raw = File.ReadAllText(arguments[1], Encoding.UTF8)
                    .TrimEnd('\\r', '\\n');
                string result = PadiemPcConnect.NormalizeAgentImagePath(raw);
                Console.WriteLine("NORM=" + (result ?? "(null)"));
                return 0;
            }
            if (command == "REGISTERED")
            {
                string registered = PadiemPcConnect.RegisteredAgentPath();
                Console.WriteLine("REGISTERED=" + (registered ?? "(null)"));
                return 0;
            }
            if (command == "SERVICE" && arguments.Length > 1)
            {
                Console.WriteLine("RUNNING="
                    + (PadiemPcConnect.ServiceIsRunning(arguments[1]) ? "1" : "0"));
                return 0;
            }
            if (command == "STOPINSTALLED")
            {
                Console.WriteLine("STOPPED="
                    + (PadiemPcConnect.StopInstalledAgent() ? "1" : "0"));
                return 0;
            }
            Console.WriteLine("USAGE");
            return 2;
        }
    }
}
"""


def _environment() -> dict[str, str]:
    """This process's environment without the module path a newer PowerShell left."""
    return {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}


def _run(argv, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(part) for part in argv], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, check=False,
        env=_environment(), **kwargs,
    )


@pytest.fixture(scope="module")
def harness(tmp_path_factory) -> Path:
    if sys.platform != "win32" or not COMPILER.is_file():
        pytest.skip("the .NET Framework compiler the build uses is not on this machine")
    work = tmp_path_factory.mktemp("harness")
    shutil.copyfile(PROGRAM_SOURCE, work / "PadiemPcConnect.cs")
    (work / "ReinstallHarness.cs").write_text(_HARNESS, encoding="utf-8")
    done = _run([
        COMPILER, "/nologo", "/noconfig", "/target:exe", "/platform:anycpu",
        "/codepage:65001", "/reference:System.dll", "/reference:System.Management.dll",
        "/main:Padiem.Connect.ReinstallHarness",
        "/out:harness.exe",
        "PadiemPcConnect.cs", "ReinstallHarness.cs",
    ], cwd=work)
    assert done.returncode == 0, done.stdout + done.stderr
    return work / "harness.exe"


def _normalize_case(harness: Path, work: Path, raw: str) -> str:
    record = work / ("case-" + str(abs(hash(raw)))[:8] + ".txt")
    record.write_text(raw, encoding="utf-8")
    done = _run([harness, "NORMALIZE", str(record)])
    assert done.returncode == 0, done.stdout + done.stderr
    for line in done.stdout.splitlines():
        if line.startswith("NORM="):
            return line[5:]
    raise AssertionError(done.stdout)


def test_a_quoted_record_with_arguments_returns_the_quoted_path(
        harness, tmp_path: Path) -> None:
    """The shape the surface's own registry record has: quoted path, then switches."""
    agent = tmp_path / "Mesh Agent.exe"
    agent.write_bytes(b"MZ")
    raw = f'"{agent}" --agentName="pd-cfeca717 [C]" --installedByUser="S-1-1-1"'
    assert _normalize_case(harness, tmp_path, raw) == str(agent)


def test_an_unquoted_record_with_spaces_and_arguments_finds_the_binary(
        harness, tmp_path: Path) -> None:
    """Longest existing prefix wins, so the first space does not cut the path."""
    agent = tmp_path / "Mesh Agent.exe"
    agent.write_bytes(b"MZ")
    raw = f"{agent} -stop"
    assert _normalize_case(harness, tmp_path, raw) == str(agent)


def test_an_unquoted_record_without_arguments_is_itself(harness, tmp_path: Path) -> None:
    agent = tmp_path / "MeshAgent.exe"
    agent.write_bytes(b"MZ")
    assert _normalize_case(harness, tmp_path, str(agent)) == str(agent)


def test_a_record_nothing_can_confirm_falls_back_to_the_first_space_cut(
        harness, tmp_path: Path) -> None:
    raw = "C:\\definitely\\missing.exe -stop"
    assert _normalize_case(harness, tmp_path, raw) == "C:\\definitely\\missing.exe"


def test_an_empty_record_is_no_path(harness, tmp_path: Path) -> None:
    assert _normalize_case(harness, tmp_path, "") == "(null)"


def test_a_service_that_does_not_exist_is_not_running(harness) -> None:
    done = _run([harness, "SERVICE", ABSENT_SERVICE])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RUNNING=0" in done.stdout, done.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="reads this machine's services")
def test_the_verified_stop_says_stopped_when_there_is_nothing_running(harness) -> None:
    """On a PC without the agent the stop is trivially done - and never harmful.

    Skipped on a machine that really has the "Mesh Agent" service installed: the
    call is the real one, and this test must never stop somebody's own agent.
    """
    listed = _run([harness, "REGISTERED"])
    assert listed.returncode == 0, listed.stdout + listed.stderr
    if "REGISTERED=(null)" not in listed.stdout:
        pytest.skip('this machine really has a "Mesh Agent" service registered')
    done = _run([harness, "STOPINSTALLED"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "STOPPED=1" in done.stdout, done.stdout
