"""#7177 — a silent PC may not hold the command lane forever.

2026-11-08 운영 실측(컴2 executor 저널): 11-07 20:05:56 이후 result 0 —
start·spawn은 계속 journal 되지만 결과가 하루 동안 하나도 없었다. 메시센트럴은
콘솔이 점유된 노드의 runcommand를 큐잉하지 않고 버린다(`_run_shell_session`
문서), 그러므로 점유된 콘솔 뒤의 모든 명령은 클라이언트가 한 바이트도 출력하지
않는 채 영원히 대기했다(#5995의 deadline 제거 + 콘솔 프로브 기본 off의 결합).

이 계약은 대기의 두 면을 고정한다:
- 대화하는 명령은 여전히 무제한이다 — 바이트가 오면 상한은 매번 초기화되고,
  프로세스가 끝나면 즉시 결과를 돌려준다(#7111 요구).
- 한 바이트도 없는 대기는 상한(PADIEM_MESH_SILENT_WAIT_SECONDS, 기본 600,
  0=비활성)에서 끝난다 — 이 호스트에서 클라이언트만 끝내고 PC는 만지지 않으며,
  dispatch는 timed_out으로 완결되어 다음 작업이 진행된다.
- 사용자 모드 경로도 SYSTEM과 같은 phase 척추(start/spawn/result)를 저널한다.
"""

from __future__ import annotations

import io
import json
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

from kagent.local_agent_meshcentral_command_port import (
    MeshCentralCliCommandPort,
    _silent_wait_seconds,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutor,
)

MESHCTRL = "meshctrl.js"
PASSWORD = "p" * 40


class _SilentChild:
    """A console child that never answers and never exits (the wedged lane)."""

    def __init__(self):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdout = _Stream(self)
        self.killed = False
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


class _TalkingChild(_SilentChild):
    """Streams one slice of transcript per interval, then finishes."""

    def __init__(self, slices=3, slice_seconds=0.05):
        super().__init__()
        self._slices, self._slice_seconds = slices, slice_seconds
        self._born = time.monotonic()

    def poll(self):
        if self.exit_code is None:
            if (time.monotonic() - self._born) >= self._slices * self._slice_seconds:
                self.exit_code = 0
        return self.exit_code


class _Stream:
    def __init__(self, child):
        self._child = child

    def fileno(self):
        raise OSError("not an OS pipe: a test double")

    def read(self, _size):
        child = self._child
        if isinstance(child, _TalkingChild):
            # Streams transcript slices for the scripted while, then the
            # envelope + sentinel, then goes quiet — poll() (checked on empty
            # chunks only) reports the exit.
            if (time.monotonic() - child._born) < child._slices * child._slice_seconds:
                time.sleep(child._slice_seconds)
                return b"slice of transcript\n"
            if child.exit_code is None:
                child.exit_code = 0
                import base64
                return (b"PADIEM_B64=" + base64.b64encode(b"whoami output")
                        + b"\r\n__PADIEM_EXIT__0\r\n")
            return b""
        return b""


def _port(popen):
    return MeshCentralCliCommandPort(
        command_runner=lambda *a, **k: None,
        meshctrl_js=MESHCTRL, login_user="padiemadmin",
        password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
        popen_factory=popen, pty_factory=lambda payload: None,
    )


def _run_one(port, **extra):
    phases = []
    outcome = port.run_command(
        node_ref="node//X", command="whoami", timeout_seconds=None,
        dispatch_id="dsp_" + "a" * 16, phase_observer=phases.append, **extra)
    return outcome, phases


class SilentWaitBoundContract(unittest.TestCase):
    def test_the_bound_reads_the_env_with_a_600s_default(self):
        self.assertEqual(_silent_wait_seconds(), 600.0)
        self.assertEqual(
            _silent_wait_seconds(environ={"PADIEM_MESH_SILENT_WAIT_SECONDS": "30"}), 30.0)
        self.assertEqual(
            _silent_wait_seconds(environ={"PADIEM_MESH_SILENT_WAIT_SECONDS": "0"}), 0.0)
        self.assertEqual(
            _silent_wait_seconds(environ={"PADIEM_MESH_SILENT_WAIT_SECONDS": "junk"}), 600.0)
        self.assertEqual(_silent_wait_seconds(explicit=2.5), 2.5)

    def test_a_never_answering_pc_ends_at_the_bound_and_the_lane_is_free(self):
        children = []

        def popen(argv, **kwargs):
            child = _SilentChild()
            children.append(child)
            return child

        port = _port(popen)
        with mock.patch.dict("os.environ", {"PADIEM_MESH_SILENT_WAIT_SECONDS": "0.2"}):
            outcome, phases = _run_one(port)
        self.assertEqual(outcome.termination, "timed_out")
        self.assertIsNone(outcome.exit_code)
        # The client was ended on THIS host only; the dispatch completes visibly.
        self.assertTrue(children[0].killed)
        self.assertIn("spawn", phases)
        self.assertIn("silent_timeout", phases)

    def test_a_talking_command_is_never_cut_and_answers_when_it_ends(self):
        def popen(argv, **kwargs):
            return _TalkingChild(slices=3, slice_seconds=0.05)

        port = _port(popen)
        with mock.patch.dict("os.environ", {"PADIEM_MESH_SILENT_WAIT_SECONDS": "0.2"}):
            outcome, phases = _run_one(port)
        # Every slice resets the bound; the ending transcript parses whole.
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.exit_code, 0)
        self.assertIn(b"slice of transcript", outcome.output)
        self.assertIn("reply", phases)
        self.assertNotIn("silent_timeout", phases)


class UserModePhaseSpine(unittest.TestCase):
    """The 15:45 user job read as 'claimed then nothing' — that ends here."""

    def test_user_mode_journals_the_same_phase_spine_as_system(self):
        class _FakePort:
            def run_command(self, *, node_ref, command, timeout_seconds,
                            cancel_probe=None, phase_observer=None, **kwargs):
                if callable(phase_observer):
                    phase_observer("spawn")
                    phase_observer("session_lane")

                class _Observed:
                    termination = "exited"
                    exit_code = 0
                    output = json.dumps({
                        "status": "ok", "exit_code": 0,
                        "stdout_b64": "", "stderr_b64": "",
                    }).encode("utf-8")
                return _Observed()

        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        executor._command_port = _FakePort()
        dispatch = OracleMeshDispatch(
            dispatch_id="dsp_userphase01", nonce="n" * 16, node_ref="node//X",
            file_path="C:/x", command_id="cmd_x", run_id="chat_pcq_" + "a" * 20,
            kind="command", user_mode=True, device_id="dev_x",
            command_text=json.dumps({
                "shell": "whoami", "command": "whoami", "cwd": None,
                "timeout_seconds": 30, "distro": None}),
        )
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            outcome = executor._execute_command(dispatch)
        printed = buffer.getvalue()
        self.assertEqual(outcome.termination, "exited")
        for phase in ("start", "spawn", "session_lane", "result"):
            self.assertIn(f"phase={phase}", printed)
        self.assertIn("dispatch_id=dsp_userphase01", printed)
        # The spine is bounded correlation only — no command or output text.
        self.assertNotIn('"command": "whoami"', printed)


if __name__ == "__main__":
    unittest.main()
