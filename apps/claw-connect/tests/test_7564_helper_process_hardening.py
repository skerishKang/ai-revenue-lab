"""#7564 — the helper's children are named, placed and ended by proven facts.

Four facts this suite pins, each one a decision the helper now makes from
something the OS itself reports rather than from a name it was handed:

* Every Windows system executable the helper starts is named by the full path
  the OS reports (``GetSystemDirectoryW``). A bare name would be resolved
  against the helper's own install folder first — a folder other local
  accounts can create files in. An unprovable location is a refusal, never a
  bare-name fallback.
* A request that names no working folder runs in the user's profile folder,
  never in the install folder the scheduled task happened to start the helper
  in. A request that names a folder keeps it.
* A cancelled command and its whole tree end through the kill-on-close job it
  was put in at spawn time, or — without a job — through the spawn handle.
  There is no ``taskkill /T`` anywhere: it selects children by parent PID
  value, which a reused PID turns into somebody else's process tree.
* The helper's pipe is created with ``FILE_FLAG_FIRST_PIPE_INSTANCE``, so a
  pipe name somebody else created first fails the start instead of being
  served with their DACL.

The decision logic runs on every OS over fakes; the real Windows mechanisms
(job objects, the named pipe, the real system directory) have their own
Windows-only tests, and the shipped helper runs them on the ``windows-latest``
job of ``.github/workflows/claw-connect-contract-tests.yml``.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import uuid

import pytest

from claw_connect import user_helper_service as service
from claw_connect import user_session_helper as helper
from claw_connect import user_session_manager as sessions

SECRET = b"deployment-secret-for-tests"

FAKE_SYSTEM_DIR = "/fake-padiem-system32"
FAKE_POWERSHELL = FAKE_SYSTEM_DIR + "/WindowsPowerShell/v1.0/powershell.exe"


def _fake_resolvers(monkeypatch):
    monkeypatch.setattr(helper, "system_executable",
                        lambda name: FAKE_SYSTEM_DIR + "/" + name)
    monkeypatch.setattr(helper, "windows_powershell_executable",
                        lambda: FAKE_POWERSHELL)
    monkeypatch.setattr(sessions, "system_executable",
                        lambda name: FAKE_SYSTEM_DIR + "/" + name)
    monkeypatch.setattr(sessions, "windows_powershell_executable",
                        lambda: FAKE_POWERSHELL)


def _signed(**overrides):
    payload = {
        "request_id": "req_" + "a" * 32, "nonce": "", "shell": "whoami",
        "command": "whoami", "timeout_seconds": 0, "cwd": None, "distro": None,
    }
    payload.update(overrides)
    parsed = helper.parse_request(payload)
    return helper.HelperRequest(
        request_id=parsed.request_id,
        nonce=helper.request_nonce(SECRET, parsed),
        shell=parsed.shell, command=parsed.command,
        timeout_seconds=parsed.timeout_seconds, cwd=parsed.cwd, distro=parsed.distro,
    )


class RecordingConnection:
    """Just enough pipe for ``_serve_streaming``: frames in, frames out."""

    def __init__(self):
        self.frames = []
        self.closed = False

    def write_all(self, data: bytes) -> None:
        self.frames.append(data)

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# 1. System executables: full paths from the OS, refusal without them.
# ---------------------------------------------------------------------------
def test_system_executables_are_named_by_the_os_reported_full_path(monkeypatch):
    _fake_resolvers(monkeypatch)
    assert helper.build_argv(_signed()) == [FAKE_SYSTEM_DIR + "/whoami.exe"]
    powershell = helper.build_argv(_signed(shell="powershell", command="Get-Location"))
    assert powershell[0] == FAKE_POWERSHELL
    assert powershell[1:6] == ["-NoProfile", "-NonInteractive",
                               "-ExecutionPolicy", "Bypass", "-EncodedCommand"]
    assert helper.build_argv(_signed(shell="cmd", command="echo ok"))[0] == \
        FAKE_SYSTEM_DIR + "/cmd.exe"


def test_session_shells_are_named_by_the_os_reported_full_path(monkeypatch):
    _fake_resolvers(monkeypatch)
    assert sessions.build_session_argv("powershell", "", terminal=False)[0] == FAKE_POWERSHELL
    assert sessions.build_session_argv("cmd", "dir", terminal=True)[:2] == \
        [FAKE_SYSTEM_DIR + "/cmd.exe", "/d"]


@pytest.mark.parametrize("shell,command", [
    ("whoami", "whoami"),
    ("powershell", "Get-Location"),
    ("cmd", "echo ok"),
])
def test_an_unprovable_system_directory_is_a_refusal_not_a_bare_name(monkeypatch, shell, command):
    monkeypatch.setattr(helper, "system_executable", lambda name: None)
    monkeypatch.setattr(helper, "windows_powershell_executable", lambda: None)
    with pytest.raises(helper.UserHelperError) as refused:
        helper.build_argv(_signed(shell=shell, command=command))
    assert refused.value.code == helper.USER_HELPER_REFUSED


def test_no_bare_system_executable_call_remains_in_the_helper_source():
    """The argv literals are gone from the helper's runtime modules.

    ``user_helper_provisioning.py`` is the installer's own PowerShell call and
    is deliberately out of this change's scope.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runtime = ["user_session_helper.py", "user_session_manager.py", "user_helper_service.py"]
    for name in runtime:
        with open(os.path.join(root, "claw_connect", name), encoding="utf-8") as handle:
            source = handle.read()
        for pattern in ('["whoami.exe"', '["powershell.exe"', '["cmd.exe"',
                        '["taskkill"', '"taskkill"'):
            assert pattern not in source, (name, pattern)


# ---------------------------------------------------------------------------
# 2. The working folder: the request's, else the user profile.
# ---------------------------------------------------------------------------
def _cwd_probe_argv():
    return [sys.executable, "-X", "utf8", "-c",
            "import sys, os; sys.stdout.write(os.getcwd())"]


def test_a_request_without_cwd_runs_in_the_default_folder_not_the_install_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "default_working_directory", lambda: str(tmp_path))
    code, out, _err = helper.run_process(_cwd_probe_argv(), None, None)
    assert code == 0 and out.decode("utf-8") == str(tmp_path)


def test_a_request_with_cwd_keeps_it(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "default_working_directory", lambda: "/elsewhere")
    code, out, _err = helper.run_process(_cwd_probe_argv(), str(tmp_path), None)
    assert code == 0 and out.decode("utf-8") == str(tmp_path)


def test_an_undeterminable_default_working_directory_is_refused(monkeypatch):
    monkeypatch.setattr(helper, "default_working_directory", lambda: None)
    with pytest.raises(helper.UserHelperError) as refused:
        helper.working_directory(None)
    assert refused.value.code == helper.USER_HELPER_REFUSED
    # A request that names a folder is returned unchanged, refusal or not.
    assert helper.working_directory("/tmp/padiem-7564-probe") == "/tmp/padiem-7564-probe"


def test_the_streaming_path_defaults_the_working_folder_and_keeps_a_given_one(monkeypatch, tmp_path):
    captured = {}

    class FakePopen:
        def __init__(self, argv, cwd=None, **kwargs):
            captured["cwd"] = cwd
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 424242

        def poll(self):
            return 0

        def wait(self):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(service, "build_argv", lambda request: ["unused"])
    monkeypatch.setattr(helper, "default_working_directory", lambda: str(tmp_path))
    monkeypatch.setattr(service.subprocess, "Popen", FakePopen)

    connection = RecordingConnection()
    outcome = service._serve_streaming(connection, _signed(shell="powershell", command="Get-Location"))
    assert outcome == "served"
    assert captured["cwd"] == str(tmp_path)

    connection = RecordingConnection()
    outcome = service._serve_streaming(
        connection, _signed(shell="powershell", command="Get-Location", cwd=str(tmp_path)))
    assert outcome == "served"
    assert captured["cwd"] == str(tmp_path)


def test_a_session_start_without_cwd_does_not_inherit_the_install_folder(monkeypatch, tmp_path):
    captured = {}

    def factory(argv, cwd, **options):
        captured["cwd"] = cwd
        return _StubBackend()

    monkeypatch.setattr(sessions, "default_working_directory", lambda: str(tmp_path))
    manager = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: ["unused"],
        backends={"pipe": factory}, reaper_interval=None)
    try:
        reply = manager.handle({"v": 1, "op": "start", "wait_ms": 0},
                               request_id="req_" + "b" * 32, cwd=None)
        assert reply.ok, reply.header
        assert captured["cwd"] == str(tmp_path)
    finally:
        manager.shutdown()


def test_a_session_start_with_cwd_keeps_it_and_an_undeterminable_one_fails(monkeypatch, tmp_path):
    captured = {}

    def factory(argv, cwd, **options):
        captured["cwd"] = cwd
        return _StubBackend()

    monkeypatch.setattr(sessions, "default_working_directory", lambda: None)
    manager = sessions.SessionManager(
        argv_builder=lambda shell, command, terminal: ["unused"],
        backends={"pipe": factory}, reaper_interval=None)
    try:
        reply = manager.handle({"v": 1, "op": "start", "wait_ms": 0},
                               request_id="req_" + "c" * 32, cwd=str(tmp_path))
        assert reply.ok, reply.header
        assert captured["cwd"] == str(tmp_path)
        refused = manager.handle({"v": 1, "op": "start", "wait_ms": 0},
                                 request_id="req_" + "d" * 32, cwd=None)
        assert not refused.ok and refused.header["code"] == "pc_session_start_failed"
        assert refused.header["detail"] == "cwd_invalid"
    finally:
        manager.shutdown()


class _StubBackend:
    name = "pipe"

    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def close(self):
        pass


# ---------------------------------------------------------------------------
# 3. Ending a command: the job first, the spawn handle as the fallback.
# ---------------------------------------------------------------------------
class _FakeJob:
    def __init__(self, result=True, error=None):
        self.result, self.error = result, error
        self.terminated = False

    def terminate(self):
        self.terminated = True
        if self.error is not None:
            raise self.error
        return self.result


class _FakeProcess:
    def __init__(self, job=None):
        self._padiem_job = job
        self.killed = 0

    def kill(self):
        self.killed += 1


def test_the_job_ends_the_tree_without_touching_the_child_again():
    job, process = _FakeJob(result=True), _FakeProcess()
    process._padiem_job = job
    service._kill_process_tree(process)
    assert job.terminated and process.killed == 0


def test_without_a_job_the_spawn_handle_ends_the_child():
    process = _FakeProcess(job=None)
    service._kill_process_tree(process)
    assert process.killed == 1


@pytest.mark.parametrize("result,error", [(False, None), (True, OSError("job gone"))])
def test_a_failed_job_termination_falls_back_to_the_spawn_handle(result, error):
    job, process = _FakeJob(result=result, error=error), _FakeProcess()
    process._padiem_job = job
    service._kill_process_tree(process)
    assert job.terminated and process.killed == 1


def _process_gone(pid: int, timeout_seconds: float = 15.0) -> bool:
    """Poll one PID the test started until its exit code is final."""
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return True  # no such process: it is gone
        code = ctypes.c_uint32(0)
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        if ok and code.value != 258:  # STILL_ACTIVE
            return True
        time.sleep(0.2)
    return False


POWERSHELL_TREE_COMMAND = (
    "$g = Start-Process powershell -ArgumentList '-NoProfile','-Command',"
    "'Start-Sleep -Seconds 180' -WindowStyle Hidden -PassThru;"
    "Write-Output $g.Id;"
    "Start-Sleep -Seconds 180"
)


@pytest.mark.skipif(sys.platform != "win32",
                    reason="job objects and a real process tree exist on Windows only")
def test_a_cancelled_command_ends_its_whole_tree_through_the_job():
    """The child the test started, and the grandchild it started, both end."""
    child = subprocess.Popen(
        [helper.windows_powershell_executable(), "-NoProfile", "-NonInteractive",
         "-Command", POWERSHELL_TREE_COMMAND],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    job = None
    try:
        grandchild_pid = int(child.stdout.readline().strip())
        job = service._job_for(getattr(child, "_handle", None))
        child._padiem_job = job
        assert job is not None, "the child did not land in a kill-on-close job"
        service._kill_process_tree(child)
        child.wait(timeout=15)
        assert _process_gone(grandchild_pid), "the grandchild survived the job"
    finally:
        if job is not None:
            job.close()  # kill-on-close: ends anything left of the tree
        if child.poll() is None:
            child.kill()


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the spawn-handle fallback is a Windows handle fact")
def test_without_a_job_the_spawn_handle_still_ends_the_child():
    child = subprocess.Popen(
        [helper.windows_powershell_executable(), "-NoProfile", "-NonInteractive",
         "-Command", "Start-Sleep -Seconds 180"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    try:
        child._padiem_job = None  # the job could not be created: the fallback runs
        service._kill_process_tree(child)
        child.wait(timeout=15)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()


# ---------------------------------------------------------------------------
# 4. The pipe name is claimed with the first-instance flag.
# ---------------------------------------------------------------------------
def test_the_first_instance_flag_is_part_of_the_listener():
    source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "claw_connect", "user_helper_service.py")
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    assert "_FILE_FLAG_FIRST_PIPE_INSTANCE" in source
    assert "self._first_instance" in source


@pytest.mark.skipif(sys.platform != "win32",
                    reason="named pipes exist on Windows only")
def test_an_already_owned_pipe_name_fails_the_start(monkeypatch):
    """A pipe name somebody else created first refuses the start."""
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    name = f"padiem-test-7564-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    handle = kernel.CreateNamedPipeW(
        ctypes.c_wchar_p("\\\\.\\pipe\\" + name),
        0x00000003 | 0x00080000,  # PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE
        0x00000000 | 0x00000000 | 0x00000000,  # byte mode, byte read, wait
        255, 4096, 4096, 0, None,
    )
    assert handle not in (0, -1, (1 << 64) - 1), "the test pipe could not be created"
    try:
        monkeypatch.setattr(service, "pipe_name", lambda device_id: name)
        with pytest.raises(helper.UserHelperError) as refused:
            service.WindowsPipeListener("7564-dupe-pipe-probe")
        assert refused.value.code == helper.USER_HELPER_REFUSED
        assert "already taken" in refused.value.detail
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32",
                    reason="named pipes exist on Windows only")
def test_an_unclaimed_pipe_name_still_starts(monkeypatch):
    """The positive control: a free name starts, and the flag did not break it."""
    name = f"padiem-test-7564-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(service, "pipe_name", lambda device_id: name)
    listener = service.WindowsPipeListener("7564-free-pipe-probe")
    try:
        assert listener._first_instance is False  # the first instance was created
    finally:
        listener.close()


# ---------------------------------------------------------------------------
# The real OS answers, on the only OS the helper ships for.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32",
                    reason="the system directory is a Windows fact")
def test_the_system_directory_comes_from_the_os_and_the_files_are_there():
    directory = helper.system_directory()
    assert directory is not None and os.path.isdir(directory)
    assert helper.system_executable("whoami.exe") == os.path.join(directory, "whoami.exe")
    assert os.path.isfile(helper.system_executable("whoami.exe"))
    assert os.path.isfile(helper.system_executable("cmd.exe"))
    assert os.path.isfile(helper.windows_powershell_executable())
    argv = helper.build_argv(_signed())
    assert argv == [os.path.join(directory, "whoami.exe")]


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the user profile folder is the logged-in user's own")
def test_the_default_working_directory_is_the_user_profile():
    profile = helper.default_working_directory()
    assert profile is not None and os.path.isdir(profile)
    assert os.path.normcase(profile) == os.path.normcase(os.environ["USERPROFILE"])
