"""#7180 — an orphaned console is reaped when the wait for an answer expires.

2026-11-08 실측(컴1, CTO 측정): 컴1 MeshAgent(PID 5084) 아래 SYSTEM
powershell.exe(PID 38276, 생성 2026-11-07 21:14:27, 자식은 conhost뿐, 19시간
유휴)를 수동 종료하자 PC 명령이 즉시 회복(whoami 수초). 메시센트럴은 콘솔이
점유된 노드의 runcommand를 큐잉하지 않고 버린다 — 고아 콘솔 하나가 모든 PC
명령을 하루 동안 침묵시켰다.

원인 경로(코드): 사용자 모드 파이프 클라이언트가 run_command에 dispatch_id를
넘기지 않아(local_agent_oracle_mesh_executor.py:1663) 콘솔 프로세스가 pid
마커를 남기지 않았다 → 소유자 stop이 조준할 대상이 없고 executor 재시작 뒤에는
그 dispatch를 아는 주체 자체가 사라짐 → 헬퍼의 스트리밍 계약(#7107/#7111,
"끝나지 않는다")과 합쳐져 클라이언트가 무기한 생존.

이 계약은 세 조각을 고정한다:
- 사용자 모드 클라이언트가 자기 dispatch의 마커를 남긴다(정지·보호·정리의
  조준점).
- 대기가 timed_out으로 끝나면, 같은 노드의 고아 콘솔만 골라 끝내는 정리가
  한 번 돈다: 에이전트의 직계 자식 + 나이 상한 + 자식이 conhost뿐 + 어떤
  dispatch의 마커도 그 pid를 가리키지 않음 + 우리 것 중 라이브가 없음.
  이름 패턴 일괄 종료는 없다 — 명시 pid만. 대상 pid와 생성 시각이 저널에
  남는다. 기본 켜짐, env로 끔.
- 선별 기준은 PowerShell이 PC에서 판정한다(스크립트 내용으로 고정).
"""

from __future__ import annotations

import base64
import io
import json
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from kagent import local_agent_meshcentral_command_port as port_module
from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX, EXIT_SENTINEL, IDLE_CONSOLE_MIN_AGE_ENV,
    IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT, IDLE_CONSOLE_REAP_ENV,
    SWEEP_MODE_IDLE_CONSOLE, SWEEP_SENTINEL, MeshCentralCliCommandPort,
    MeshCentralCommandRefused, _idle_console_min_age_seconds,
    _idle_console_reap_enabled, sweep_script,
)

NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"
PASSWORD = "op3rator-meshtr0ll-secret"
OURS = "dsp_" + "a" * 32
HOST_TAG = "com2-executor"

_TIMEOUT_SLICE = 1


def _frame(**fields) -> bytes:
    body = base64.b64encode(json.dumps(fields).encode("utf-8")).decode("ascii")
    return (SWEEP_SENTINEL + body + "\n").encode("ascii")


class _SilentChild:
    """A meshctrl client that never answers (the busy-dropped command)."""

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


class _Stream:
    def __init__(self, child):
        self._child = child

    def fileno(self):
        raise OSError("not an OS pipe: a test double")

    def read(self, _size):
        return b""


class _Harness:
    """One command whose wait ends in timed_out, and the PC it asks afterwards."""

    def __init__(self, sweep_answers=(None,), run_child=None):
        self._sweep_answers = list(sweep_answers)
        self.sweeps = []
        self.runs = []

    def popen(self, argv, **kwargs):
        if "shell" in argv:
            session = self.sweeps[-1] if self.sweeps else None
            if session is not None:
                session["argv"] = list(argv)
            return _SilentChild()
        child = _SilentChild()
        self.runs.append({"argv": list(argv), "kwargs": dict(kwargs), "child": child})
        return child

    def pty(self, payload_bytes):
        session = {
            "payload": payload_bytes, "argv": None,
            "answer": self._sweep_answers[min(len(self.sweeps),
                                              len(self._sweep_answers) - 1)],
        }
        self.sweeps.append(session)

        class _Handoff:
            slave = 77

            def wait_for(self, done, seconds):
                return session["answer"]

            def wait_closed(self, seconds):
                pass

            def release_slave(self):
                pass

        return _Handoff()

    def port(self):
        return MeshCentralCliCommandPort(
            command_runner=lambda *a, **k: None,
            meshctrl_js=MESHCTRL, login_user="padiemadmin",
            password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
            popen_factory=self.popen, pty_factory=self.pty,
            host_tag=HOST_TAG,
        )

    def run(self, **call):
        call.setdefault("command", "whoami")
        call.setdefault("dispatch_id", OURS)
        call.setdefault("timeout_seconds", _TIMEOUT_SLICE)
        phases = []
        outcome = self.port().run_command(node_ref=NODE, phase_observer=phases.append, **call)
        return outcome, phases

    @property
    def sweep_scripts(self):
        return [session["payload"].decode("utf-8") for session in self.sweeps]


class TheCauseIsNamed(unittest.TestCase):
    """원인 재현: 사용자 클라이언트 콘솔이 자기 dispatch를 이름질게 한다."""

    def test_the_user_mode_client_names_its_own_dispatch(self):
        import kagent.local_agent_oracle_mesh_executor as executor_module

        captured = {}

        class _FakePort:
            def run_command(self, *, node_ref, command, timeout_seconds,
                            cancel_probe=None, dispatch_id=None, **kwargs):
                captured["dispatch_id"] = dispatch_id

                class _Observed:
                    termination = "exited"
                    exit_code = 0
                    output = json.dumps({
                        "status": "ok", "exit_code": 0,
                        "stdout_b64": "", "stderr_b64": "",
                    }).encode("utf-8")
                return _Observed()

        executor = executor_module.OracleMeshExecutor.__new__(
            executor_module.OracleMeshExecutor)
        executor._command_port = _FakePort()
        dispatch = executor_module.OracleMeshDispatch(
            dispatch_id=OURS, nonce="n" * 16, node_ref=NODE, file_path="C:/x",
            command_id="cmd_x", run_id="chat_pcq_" + "a" * 20,
            kind="command", user_mode=True, device_id="dev_x",
            command_text=json.dumps({
                "shell": "whoami", "command": "whoami", "cwd": None,
                "timeout_seconds": 30, "distro": None}),
        )
        executor._execute_command(dispatch)
        # The marker preamble rides the wrapped script only with the id: the
        # 2026-11-07 21:14 console had none, so no stop or sweep could aim at it.
        self.assertEqual(captured["dispatch_id"], OURS)


class TheReaperRidesAnExpiredWait(unittest.TestCase):
    def test_a_timed_out_wait_runs_the_idle_console_scope_once(self):
        harness = _Harness(sweep_answers=[
            _frame(running=False,
                   found=[{"pid": 38276, "name": "powershell.exe",
                           "created": "20261107211427.0+540"}],
                   killed=[38276]),
        ])
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            outcome, phases = harness.run()
        self.assertEqual(outcome.termination, "timed_out")
        self.assertEqual(len(harness.sweeps), 1, "one reaping look, not a loop")
        self.assertIn(SWEEP_MODE_IDLE_CONSOLE, harness.sweep_scripts[0])
        self.assertIn("idle_reap", phases)
        self.assertIn("idle_reap_cleared", phases)
        # The journal names the target and its creation time — OS facts, the
        # evidence an operator needs, never an output value.
        printed = buffer.getvalue()
        self.assertIn("pc_idle_console_reap killed=1", printed)
        self.assertIn("pid=38276", printed)
        self.assertIn("created=20261107211427", printed)

    def test_a_command_that_got_its_answer_never_runs_the_reaper(self):
        class _AnsweringChild(_SilentChild):
            def __init__(self):
                super().__init__()
                self._born = time.monotonic()
                self._answered = False

            def poll(self):
                if self.exit_code is None and not self._answered \
                        and (time.monotonic() - self._born) >= 0.5:
                    self.exit_code = 0
                return self.exit_code

        class _AnsweringStream(_Stream):
            def __init__(self, child):
                super().__init__(child)

            def read(self, _size):
                child = self._child
                if child.exit_code is None:
                    if (time.monotonic() - child._born) < 0.3:
                        time.sleep(0.05)
                        return b"whoami\n"
                    child.exit_code = 0
                    return (ENVELOPE_PREFIX
                            + base64.b64encode(b"ok").decode("ascii")
                            + "\n" + EXIT_SENTINEL + "0\n").encode("ascii")
                return b""

        def popen(argv, **kwargs):
            if "shell" in argv:
                return _SilentChild()
            child = _AnsweringChild()
            child.stdout = _AnsweringStream(child)
            return child

        harness = _Harness()
        harness.popen = popen
        outcome, phases = harness.run()
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(harness.sweeps, [], "a healthy command asks nothing")
        self.assertNotIn("idle_reap", phases)

    def test_the_operator_can_turn_the_reaper_off(self):
        harness = _Harness()
        with patch.dict("os.environ", {IDLE_CONSOLE_REAP_ENV: "0"}):
            outcome, phases = harness.run()
        self.assertEqual(outcome.termination, "timed_out")
        self.assertEqual(harness.sweeps, [], "the reaper stayed home")
        self.assertNotIn("idle_reap", phases)

    def test_a_zero_age_bound_disables_the_reaper(self):
        harness = _Harness()
        with patch.dict("os.environ", {IDLE_CONSOLE_MIN_AGE_ENV: "0"}):
            outcome, phases = harness.run()
        self.assertEqual(outcome.termination, "timed_out")
        self.assertEqual(harness.sweeps, [], "no age bound, no reaping")
        self.assertNotIn("idle_reap", phases)


class TheSelectionDecidesOnThePc(unittest.TestCase):
    """정리 대상 선별: 유휴·활성·다른 주체 소유를 스크립트가 구분한다."""

    def test_the_scope_is_the_narrowest_that_ends_exactly_the_orphan(self):
        script = sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_IDLE_CONSOLE,
                              host_tag=HOST_TAG, min_age_seconds=900)
        # Only the agent's direct children — never a name, never a wider net.
        self.assertIn("ParentProcessId=$__padiem_agent", script)
        for forbidden in ("/IM", "Stop-Process", "Get-Process", "Stop-Service"):
            self.assertNotIn(forbidden, script)
        # The age bound is embedded as the literal the operator configured.
        self.assertIn("[TimeSpan]::FromSeconds(900)", script)
        self.assertIn("CreationDate", script)
        # A candidate with a child that is not conhost is WORK: skipped.
        self.assertIn("-ne 'conhost.exe'", script)
        # A process ANY dispatch's marker names is someone's work: skipped.
        self.assertIn("$__padiem_claimed -contains $__padiem_k.ProcessId", script)
        # This session's own family is untouchable, and our own live dispatch
        # (its marker points at a live process) ends nothing at all.
        self.assertIn("$__padiem_safe -contains", script)
        self.assertIn("if (-not $__padiem_live)", script)
        # One console line, not a script file.
        self.assertNotIn("\n", script)

    def test_the_marker_pass_is_ours_only_and_inert_without_a_tag(self):
        ours = sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_IDLE_CONSOLE,
                            host_tag=HOST_TAG, min_age_seconds=900)
        self.assertIn("$__padiem_o.host -ne '" + HOST_TAG + "'", ours)
        self.assertIn("Remove-Item -LiteralPath $__padiem_o.file", ours)
        partner_free = sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_IDLE_CONSOLE,
                                    min_age_seconds=900)
        # No tag: the failover partner's marker is not ours to read — the
        # marker pass ends nothing and only the structural pass runs.
        self.assertIn("continue;", partner_free)

    def test_a_non_positive_age_bound_is_a_refusal_not_a_blanket_kill(self):
        with self.assertRaises(MeshCentralCommandRefused):
            sweep_script(dispatch_id=OURS, mode=SWEEP_MODE_IDLE_CONSOLE,
                         min_age_seconds=0)

    def test_the_env_defaults_are_on_with_a_nine_hundred_second_bound(self):
        self.assertTrue(_idle_console_reap_enabled())
        self.assertTrue(_idle_console_reap_enabled(environ={}))
        self.assertFalse(_idle_console_reap_enabled(environ={IDLE_CONSOLE_REAP_ENV: "0"}))
        self.assertEqual(_idle_console_min_age_seconds(), IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT)
        self.assertEqual(_idle_console_min_age_seconds(environ={IDLE_CONSOLE_MIN_AGE_ENV: "30"}), 30)
        self.assertEqual(_idle_console_min_age_seconds(environ={IDLE_CONSOLE_MIN_AGE_ENV: "junk"}),
                         IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT)
        self.assertEqual(_idle_console_min_age_seconds(environ={IDLE_CONSOLE_MIN_AGE_ENV: "-5"}), 0)


if __name__ == "__main__":
    unittest.main()
