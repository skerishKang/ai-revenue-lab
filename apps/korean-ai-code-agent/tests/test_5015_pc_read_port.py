"""#5015: the PC read_file lane reuses the bounded kind=read download port.

These tests pin the transport boundary itself: the official client argv, the
stdin credential marker, the staged file cleanup, the detection-then-abort
download monitor, and the executor outcome markers the Engine already maps.
No live MeshCentral server or credential is involved.
"""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from kagent.local_agent_meshcentral_private_reader import (
    MeshCentralCliFileReadPort,
    MeshCentralReadRefused,
    MeshCentralReadTooLarge,
)
from kagent.local_agent_oracle_mesh_executor import (
    MAX_READ_BYTES_ENVELOPE, MAX_READ_BYTES,
    OracleMeshChannelRefused,
    OracleMeshDispatch,
    OracleMeshExecutor,
    PC_FILE_READ_FAILED_MARKER,
    PC_FILE_TOO_LARGE_MARKER,
)

LIVE_TRIAL_TEXT = (
    "PADIEM MESHCENTRAL SINGLE-PC TXT TEST\n"
    "DATE=2026-10-16\n"
    "HOST=COM1\n"
    "TEST_CASE=mesh-agent-read-and-return\n"
    "END_OF_FILE\n"
)
LIVE_TRIAL_BYTES = LIVE_TRIAL_TEXT.encode("utf-8")
LIVE_TRIAL_SHA = "a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c"
PASSWORD = "p" * 16
MESHCTRL_JS = r"C:\meshcentral-test\node_modules\meshcentral\meshctrl.js"
NODE_REF = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
KOREAN_PATH = (
    r"C:\Users\limone\AppData\Local\PADIEM\공유 폴더"
    r"\a b $(whoami) 'q' & echo.txt"
)
SECRET = "u" * 32


class _RecordingStdin:
    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, text):
        self.value += text

    def close(self):
        self.closed = True


class _FakeDownloadProcess:
    """A download child that stages the target on its first poll."""

    def __init__(self, argv, *, staged=b"", exit_immediately=True, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        self.stdin = _RecordingStdin()
        self.returncode = None
        self.terminated = False
        self.target = argv[argv.index("--target") + 1]
        self._staged = staged
        self._exit_immediately = exit_immediately
        self._written = False

    def poll(self):
        if not self._written:
            self._written = True
            if self._staged:
                with open(self.target, "wb") as handle:
                    handle.write(self._staged)
        if self.terminated:
            return self.returncode
        if self._exit_immediately:
            self.returncode = 0
            return self.returncode
        return None

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def _port(tmp_path, *, popen_factory=None, runner=None):
    return MeshCentralCliFileReadPort(
        command_runner=runner or (lambda *a, **k: None),
        meshctrl_js=MESHCTRL_JS,
        login_user="padiemadmin",
        password_provider=lambda: PASSWORD,
        url="wss://127.0.0.1:4443",
        work_dir=str(tmp_path),
        popen_factory=popen_factory,
    )


def _runner(*, staged, returncode=0, capture):
    def run(argv, *, timeout, input):
        del timeout
        capture["argv"] = list(argv)
        capture["input"] = input
        if returncode == 0 and staged is not None:
            with open(argv[argv.index("--target") + 1], "wb") as handle:
                handle.write(staged)
        return type("Result", (), {"returncode": returncode})()

    return run


class _ReadPort:
    """Recording stand-in for the real MeshCentralFileReadPort protocol.

    The contract audit (test_fake_port_contract_261031) rejects ``**kwargs``
    fakes: the fake must refuse arguments the real port does not accept, or a
    renamed port argument passes tests and fails in production (#6327's shape).
    The sentinel defaults keep the omission observable — the assertions below
    rely on ``"max_bytes" not in calls[0]`` seeing only what the executor sent.
    """

    _NOT_SENT = object()

    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def read_bytes(self, *, node_ref, file_path, timeout_seconds=_NOT_SENT, max_bytes=_NOT_SENT):
        recorded = {"node_ref": node_ref, "file_path": file_path}
        if timeout_seconds is not self._NOT_SENT:
            recorded["timeout_seconds"] = timeout_seconds
        if max_bytes is not self._NOT_SENT:
            recorded["max_bytes"] = max_bytes
        self.calls.append(recorded)
        if self.error is not None:
            raise self.error
        return self.result


def _executor(read_port) -> OracleMeshExecutor:
    return OracleMeshExecutor(
        chat_origin="https://chat.padiem.net",
        channel_secret=SECRET,
        read_port=read_port,
    )


def _dispatch(**overrides) -> OracleMeshDispatch:
    fields = {
        "dispatch_id": "dsp-5015", "nonce": "n" * 32, "node_ref": NODE_REF,
        "file_path": KOREAN_PATH, "command_id": "cmd-5015", "run_id": "run-5015",
        "kind": "read",
    }
    fields.update(overrides)
    return OracleMeshDispatch(**fields)


# ---------------------------------------------------------------- port argv
def test_download_argv_keeps_a_korean_space_metacharacter_path_as_one_element(
    tmp_path,
):
    capture: dict = {}
    port = _port(
        tmp_path,
        runner=_runner(staged=LIVE_TRIAL_BYTES, capture=capture),
    )
    raw = port.read_bytes(
        node_ref=NODE_REF, file_path=KOREAN_PATH, timeout_seconds=30,
    )

    assert raw == LIVE_TRIAL_BYTES
    assert hashlib.sha256(raw).hexdigest() == LIVE_TRIAL_SHA
    argv = capture["argv"]
    assert "download" in argv
    assert argv[argv.index("--file") + 1] == KOREAN_PATH
    assert argv[argv.index("--id") + 1] == NODE_REF
    assert argv[argv.index("--target") + 1].startswith(str(tmp_path))
    # The credential travels on stdin; argv carries only the public marker.
    assert capture["input"] == PASSWORD + "\n"
    assert PASSWORD not in argv
    assert "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__" in argv


def test_command_runner_path_refuses_oversize_whole_and_cleans_the_temp(
    tmp_path,
):
    capture: dict = {}
    port = _port(
        tmp_path,
        runner=_runner(staged=b"x" * 1001, capture=capture),
    )
    with pytest.raises(MeshCentralReadTooLarge):
        port.read_bytes(
            node_ref=NODE_REF, file_path=KOREAN_PATH,
            timeout_seconds=30, max_bytes=1000,
        )
    assert not any(tmp_path.iterdir())


def test_command_runner_path_maps_a_download_failure_to_refused(tmp_path):
    capture: dict = {}
    port = _port(
        tmp_path,
        runner=_runner(staged=None, returncode=1, capture=capture),
    )
    with pytest.raises(MeshCentralReadRefused):
        port.read_bytes(
            node_ref=NODE_REF, file_path=KOREAN_PATH, timeout_seconds=30,
        )
    assert not any(tmp_path.iterdir())


# ------------------------------------------------------- monitored download
def test_popen_monitor_aborts_the_child_when_the_target_exceeds_the_bound(
    tmp_path,
):
    created: list = []

    def factory(argv, **kwargs):
        process = _FakeDownloadProcess(
            argv, staged=b"y" * 2048, exit_immediately=False, **kwargs,
        )
        created.append(process)
        return process

    port = _port(tmp_path, popen_factory=factory)
    with pytest.raises(MeshCentralReadTooLarge):
        port.read_bytes(
            node_ref=NODE_REF, file_path=KOREAN_PATH,
            timeout_seconds=30, max_bytes=1000,
        )
    assert len(created) == 1
    assert created[0].terminated is True
    assert created[0].stdin.value == PASSWORD + "\n"
    assert created[0].stdin.closed is True
    assert not any(tmp_path.iterdir())


def test_popen_monitor_timeout_stops_the_child_and_cleans_the_temp(tmp_path):
    created: list = []

    def factory(argv, **kwargs):
        process = _FakeDownloadProcess(
            argv, staged=b"small", exit_immediately=False, **kwargs,
        )
        created.append(process)
        return process

    port = _port(tmp_path, popen_factory=factory)
    with pytest.raises(MeshCentralReadRefused):
        port.read_bytes(
            node_ref=NODE_REF, file_path=KOREAN_PATH,
            timeout_seconds=0, max_bytes=1000,
        )
    assert created[0].terminated is True
    assert not any(tmp_path.iterdir())


def test_popen_monitor_returns_the_exact_bytes_under_the_bound(tmp_path):
    created: list = []

    def factory(argv, **kwargs):
        process = _FakeDownloadProcess(
            argv, staged=LIVE_TRIAL_BYTES, **kwargs,
        )
        created.append(process)
        return process

    port = _port(tmp_path, popen_factory=factory)
    raw = port.read_bytes(
        node_ref=NODE_REF, file_path=KOREAN_PATH,
        timeout_seconds=30, max_bytes=1_000_000,
    )
    assert raw == LIVE_TRIAL_BYTES
    assert hashlib.sha256(raw).hexdigest() == LIVE_TRIAL_SHA
    assert created[0].kwargs.get("stdin") is subprocess.PIPE
    assert created[0].kwargs.get("stdout") is subprocess.DEVNULL
    assert not any(tmp_path.iterdir())


# --------------------------------------------------------- executor mapping
def test_executor_read_returns_the_exact_113_byte_file_and_sha():
    port = _ReadPort(result=LIVE_TRIAL_BYTES)
    outcome = _executor(port).execute(_dispatch(max_bytes=1_000_000))

    assert outcome.termination == "exited"
    assert outcome.exit_code == 0
    assert outcome.body == LIVE_TRIAL_BYTES
    assert hashlib.sha256(outcome.body).hexdigest() == LIVE_TRIAL_SHA
    assert port.calls[0]["max_bytes"] == 1_000_000


def test_executor_read_maps_oversize_to_the_existing_too_large_marker():
    raising = _ReadPort(error=MeshCentralReadTooLarge("too large"))
    outcome = _executor(raising).execute(_dispatch(max_bytes=1000))
    assert outcome.termination == "exited"
    assert outcome.exit_code == 1
    assert outcome.body == PC_FILE_TOO_LARGE_MARKER.encode("utf-8")

    returned = _ReadPort(result=b"z" * 1001)
    outcome = _executor(returned).execute(_dispatch(max_bytes=1000))
    assert outcome.exit_code == 1
    assert outcome.body == PC_FILE_TOO_LARGE_MARKER.encode("utf-8")


def test_executor_read_maps_download_failure_to_read_failed():
    port = _ReadPort(error=MeshCentralReadRefused("download refused"))
    outcome = _executor(port).execute(_dispatch(max_bytes=1_000_000))
    assert outcome.termination == "exited"
    assert outcome.exit_code == 1
    assert outcome.body == PC_FILE_READ_FAILED_MARKER.encode("utf-8")


def test_executor_read_maps_invalid_utf8_to_read_failed_not_empty():
    port = _ReadPort(result=b"\xff\xfe\x00not-utf8")
    outcome = _executor(port).execute(_dispatch(max_bytes=1_000_000))
    assert outcome.termination == "exited"
    assert outcome.exit_code == 1
    assert outcome.body == PC_FILE_READ_FAILED_MARKER.encode("utf-8")


def test_other_read_consumers_keep_the_shared_six_mb_default():
    port = _ReadPort(result=LIVE_TRIAL_BYTES)
    outcome = _executor(port).execute(_dispatch(max_bytes=None))
    assert outcome.exit_code == 0
    # No per-call bound is sent, so the port's 6 MB envelope applies.
    assert "max_bytes" not in port.calls[0]
    assert MAX_READ_BYTES == 6_000_000
    assert MAX_READ_BYTES_ENVELOPE == 20_000_000


def test_poll_parses_and_rejects_an_unbounded_server_value():
    payload = {
        "ok": True,
        "dispatch": {
            "dispatch_id": "dsp-1", "nonce": "n" * 32, "node_ref": NODE_REF,
            "file_path": KOREAN_PATH, "command_id": "cmd-1", "run_id": "run-1",
            "kind": "read", "max_bytes": 1_000_000,
        },
    }
    executor = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net",
        channel_secret=SECRET,
        read_port=_ReadPort(result=b"x"),
        transport=lambda *_: (200, payload),
    )
    dispatch = executor.poll_once()
    assert dispatch is not None
    assert dispatch.max_bytes == 1_000_000

    payload["dispatch"]["max_bytes"] = MAX_READ_BYTES_ENVELOPE + 1
    with pytest.raises(OracleMeshChannelRefused):
        executor.poll_once()


def test_marker_constants_are_the_engine_prefix():
    assert PC_FILE_TOO_LARGE_MARKER.startswith("PADIEM_PC_FILE_ERROR:")
    assert PC_FILE_READ_FAILED_MARKER.startswith("PADIEM_PC_FILE_ERROR:")


def test_twenty_mb_explicit_read_bound_survives_execution_and_restart(tmp_path):
    raw = b"a" * 20_000_000
    port = _ReadPort(result=raw)
    executor = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret=SECRET,
        read_port=port, pending_dir=str(tmp_path),
        transport=lambda *_: (503, {"ok": False}),
    )
    dispatch = _dispatch(max_bytes=20_000_000)
    outcome = executor.execute(dispatch)
    assert outcome.body == raw
    assert port.calls[0]["max_bytes"] == 20_000_000
    assert executor.submit(dispatch, outcome)["retryable"] is True
    restored = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret=SECRET,
        read_port=port, pending_dir=str(tmp_path),
    )
    assert restored.load_pending() is True
    assert restored._pending[0].max_bytes == 20_000_000
    assert restored._pending[1].body == raw
    too_large = _executor(_ReadPort(result=raw + b"a")).execute(dispatch)
    assert too_large.body == PC_FILE_TOO_LARGE_MARKER.encode()
