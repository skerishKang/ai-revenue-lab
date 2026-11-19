"""#8037 — 느린 공유 흉내: 20초 뒤 pc_share_unavailable, 다음 명령은 막히지 않는다.

시계는 주입한다(실제 시간 대기 없음). 공유 판정은 서버가 폴드에 실어 보낸
승인 공유 목록과 명령의 선언으로만 선다 — 로컬 드라이브 명령과 선언 없는
명령은 제한이 없고, 기존 동작 그대로다.
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr
from unittest import mock

from kagent import local_agent_meshcentral_command_port as port_module
from kagent import pc_share_deadline as share
from kagent.local_agent_meshcentral_command_port import (
    ENVELOPE_PREFIX,
    MeshCentralCliCommandPort,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutor,
)

MESHCTRL = "meshctrl.js"
PASSWORD = "p" * 40
OURS = "dsp_" + "a" * 32
FIXED_TOKEN = "1" * 32
SHARE = "\\\\fileserver\\sharename"
SHARE_FWD = "//fileserver/sharename"
LOCAL_COMMAND = "Get-ChildItem -LiteralPath 'C:/Users/qa/문서' -Force"


def _declaration(paths):
    import base64
    literals = ",".join(
        "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
        + base64.b64encode(path.encode("utf-8")).decode("ascii") + "'))"
        for path in paths
    )
    return "$padiemShareTargets=@(" + literals + ")\n"


SHARE_COMMAND = _declaration([SHARE]) + "Get-ChildItem -LiteralPath '" + SHARE + "' -Force"
_TAG_PATCH = None


def _tag() -> str:
    return port_module._envelope_tag(OURS, FIXED_TOKEN)


def setUpModule() -> None:
    global _TAG_PATCH
    _TAG_PATCH = mock.patch.object(
        port_module, "_new_envelope_tag",
        side_effect=lambda dispatch_id: port_module._envelope_tag(dispatch_id, FIXED_TOKEN),
    )
    _TAG_PATCH.start()


def tearDownModule() -> None:
    if _TAG_PATCH is not None:
        _TAG_PATCH.stop()


class _FakeClock:
    """주입 시계. 읽을 때마다 정해진 보폭만큼 나아간다."""

    def __init__(self, step: float = 0.0):
        self.now = 1000.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SilentChild:
    """한 바이트도 답하지 않는 콘솔 자식 (끊긴 공유의 대기 모양)."""

    def __init__(self, on_read=None):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.stdout = _Stream(self, on_read)
        self.killed = False
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def kill(self):
        self.killed = True
        self.exit_code = -9


class _AnsweringChild(_SilentChild):
    """즉시 완결 프레임으로 답하는 자식 (정상 로컬 명령)."""

    def __init__(self, output=b"local listing", dispatch_id=OURS):
        super().__init__()
        self._output = output
        self._dispatch_id = dispatch_id
        self._answered = False

    def answer(self):
        import base64
        self._answered = True
        self.exit_code = 0
        tag = port_module._envelope_tag(self._dispatch_id, FIXED_TOKEN)
        return ((ENVELOPE_PREFIX + tag + ":").encode("ascii")
                + base64.b64encode(self._output)
                + b"\r\n__PADIEM_EXIT__0\r\n")


class _Stream:
    def __init__(self, child, on_read=None):
        self._child = child
        self._on_read = on_read

    def fileno(self):
        raise OSError("not an OS pipe: a test double")

    def read(self, _size):
        if self._on_read is not None:
            self._on_read()
        if isinstance(self._child, _AnsweringChild) and not self._child._answered:
            return self._child.answer()
        return b""


def _port(popen):
    return MeshCentralCliCommandPort(
        command_runner=lambda *a, **k: None,
        meshctrl_js=MESHCTRL, login_user="padiemadmin",
        password_provider=lambda: PASSWORD, url="wss://127.0.0.1:4443",
        popen_factory=popen, pty_factory=lambda payload: None,
    )


def _executor(port, *, clock):
    return OracleMeshExecutor(
        chat_origin="https://chat.example.test",
        channel_secret="s" * 32,
        read_port=mock.Mock(read_bytes=lambda **kwargs: b""),
        command_port=port,
        transport=lambda path, payload: (200, {"ok": True, "cancelled": False}),
        share_clock=clock,
    )


def _dispatch(command_text, *, share_roots=(SHARE,), dispatch_id=OURS):
    return OracleMeshDispatch(
        dispatch_id=dispatch_id, nonce="n" * 16, node_ref="node//X",
        file_path="C:/x", command_id="cmd_x", run_id="chat_pcq_" + "a" * 20,
        kind="command", command_text=command_text, share_roots=share_roots,
    )


class ShareDeclarationContract(unittest.TestCase):
    def test_the_bound_is_twenty_seconds(self):
        self.assertEqual(share.PC_SHARE_COMMAND_TIMEOUT_SECONDS, 20)
        self.assertEqual(
            share.share_command_deadline(
                command_text=SHARE_COMMAND, share_roots=[SHARE]), 20)

    def test_a_local_command_has_no_deadline(self):
        self.assertIsNone(share.share_command_deadline(
            command_text=LOCAL_COMMAND, share_roots=[SHARE]))
        self.assertIsNone(share.share_command_deadline(
            command_text=SHARE_COMMAND, share_roots=None))
        self.assertIsNone(share.share_command_deadline(
            command_text=SHARE_COMMAND, share_roots=[]))

    def test_the_declaration_must_match_the_approved_share(self):
        self.assertIsNone(share.share_command_deadline(
            command_text=_declaration(["\\\\other\\share"]) + "Get-ChildItem x",
            share_roots=[SHARE]))
        # 같은 공유의 다른 철자(슬래시 방향·대소문자)는 같은 승인 단위다.
        self.assertEqual(share.share_command_deadline(
            command_text=_declaration([SHARE_FWD]) + "Get-ChildItem x",
            share_roots=[SHARE]), 20)
        self.assertEqual(share.share_command_deadline(
            command_text=_declaration(["\\\\FILESERVER\\ShareName"]) + "Get-ChildItem x",
            share_roots=[SHARE]), 20)

    def test_a_korean_share_spelling_survives_the_declaration(self):
        root = "\\\\파일서버\\공유 문서"
        self.assertEqual(share.declared_share_roots(_declaration([root])), [root])
        self.assertEqual(share.share_command_deadline(
            command_text=_declaration([root]) + "Get-ChildItem x",
            share_roots=[root]), 20)

    def test_the_verdict_body_is_the_closed_code_with_both_languages(self):
        body = json.loads(share.share_unavailable_body())
        self.assertIs(body["ok"], False)
        self.assertEqual(body["error"], "pc_share_unavailable")
        self.assertIn("회사 네트워크", body["message"])
        self.assertIn("company network", body["message_en"])
        self.assertTrue(share.is_share_unavailable_body(share.share_unavailable_body()))
        self.assertFalse(share.is_share_unavailable_body(b'{"ok":true}'))
        self.assertFalse(share.is_share_unavailable_body(b"not json"))


class SlowShareContract(unittest.TestCase):
    """느린 공유 흉내 → 20초 뒤 닫힌 코드, 명령 정리, 다음 명령 비차단."""

    def _run_slow_share(self, *, step):
        clock = _FakeClock(step=step)
        children = []
        stops = []

        def popen(argv, **kwargs):
            child = _SilentChild(on_read=lambda: clock.advance(1.0))
            children.append(child)
            return child

        executor = _executor(_port(popen), clock=clock)
        stops = []
        executor._command_port.kill_command_process = (
            lambda **kw: stops.append(kw.get("dispatch_id"))
        )
        dispatch = _dispatch(SHARE_COMMAND)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            outcome = executor._execute_command(dispatch)
        return outcome, children, stops, clock

    def test_a_slow_share_closes_at_the_bound_with_the_closed_code(self):
        outcome, children, stops, clock = self._run_slow_share(step=0.0)
        self.assertEqual(outcome.termination, "no_exit_code")
        self.assertIsNone(outcome.exit_code)
        self.assertTrue(share.is_share_unavailable_body(outcome.body))
        # 공유 명령은 PC에서 정리되었다 — 다음 명령이 뒤에 갇히지 않는다.
        # (제한 정리 한 번 + 포트의 중지 경로 정리 한 번, 둘 다 이 dispatch만.)
        self.assertTrue(stops and all(item == OURS for item in stops))
        self.assertTrue(children[0].killed)
        # 주입 시계로 20초를 넘긴 것이지 실제 시간을 기다리지 않았다.
        self.assertGreaterEqual(clock.now - 1000.0, 20.0)

    def test_the_next_command_runs_after_the_slow_share(self):
        clock = _FakeClock()
        children = []

        def popen(argv, **kwargs):
            if len(children) == 0:
                child = _SilentChild(on_read=lambda: clock.advance(25.0))
            else:
                child = _AnsweringChild(b"next command output",
                                        dispatch_id="dsp_" + "b" * 32)
            children.append(child)
            return child

        executor = _executor(_port(popen), clock=clock)
        executor._command_port.kill_command_process = lambda **kw: None
        with redirect_stderr(io.StringIO()):
            first = executor._execute_command(_dispatch(SHARE_COMMAND))
            second = executor._execute_command(
                _dispatch(LOCAL_COMMAND, share_roots=None,
                          dispatch_id="dsp_" + "b" * 32))
        self.assertTrue(share.is_share_unavailable_body(first.body))
        self.assertEqual(second.termination, "exited")
        self.assertEqual(second.exit_code, 0)
        self.assertEqual(second.body, b"next command output")

    def test_a_share_answer_inside_the_bound_is_delivered_unchanged(self):
        clock = _FakeClock()
        children = []

        def popen(argv, **kwargs):
            child = _AnsweringChild(b"share listing")
            children.append(child)
            return child

        executor = _executor(_port(popen), clock=clock)
        stops = []
        executor._command_port.kill_command_process = lambda **kw: stops.append(1)
        with redirect_stderr(io.StringIO()):
            outcome = executor._execute_command(_dispatch(SHARE_COMMAND))
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.body, b"share listing")
        self.assertEqual(stops, [])
        self.assertFalse(children[0].killed)

    def test_a_local_drive_command_keeps_no_deadline(self):
        # 시계가 20초를 훨씬 넘겨도 로컬 명령은 잘리지 않는다(무제한 대기 계약).
        clock = _FakeClock(step=1000.0)
        children = []

        def popen(argv, **kwargs):
            child = _AnsweringChild(b"local listing")
            children.append(child)
            return child

        executor = _executor(_port(popen), clock=clock)
        stops = []
        executor._command_port.kill_command_process = lambda **kw: stops.append(1)
        with redirect_stderr(io.StringIO()):
            outcome = executor._execute_command(
                _dispatch(LOCAL_COMMAND, share_roots=None))
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.body, b"local listing")
        self.assertEqual(stops, [])

    def test_an_undeclared_command_on_a_share_pc_keeps_no_deadline(self):
        clock = _FakeClock(step=1000.0)

        def popen(argv, **kwargs):
            return _AnsweringChild(b"plain output")

        executor = _executor(_port(popen), clock=clock)
        stops = []
        executor._command_port.kill_command_process = lambda **kw: stops.append(1)
        with redirect_stderr(io.StringIO()):
            outcome = executor._execute_command(
                _dispatch("Get-ChildItem -LiteralPath '" + SHARE + "' -Force"))
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.body, b"plain output")
        self.assertEqual(stops, [])


class PollProjectionContract(unittest.TestCase):
    def test_the_poll_projection_carries_the_share_declaration(self):
        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        row = {
            "dispatch_id": OURS, "nonce": "n" * 16, "node_ref": "node//X",
            "file_path": "C:/x", "command_id": "cmd_x",
            "run_id": "chat_pcq_" + "a" * 20, "kind": "command",
            "command_text": SHARE_COMMAND, "share_roots": [SHARE],
        }
        with mock.patch.object(executor, "_poll_payload", return_value=None), \
                mock.patch.object(executor, "_post", return_value=(200, {"ok": True, "dispatch": row})), \
                mock.patch.object(executor, "_leg_for", return_value="chat"):
            executor._carried_pairing_tags = []
            executor._reported_pairing_tags = set()
            dispatch = executor.poll_once()
        self.assertEqual(dispatch.share_roots, (SHARE,))

    def test_a_malformed_declaration_names_no_shares(self):
        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        row = {
            "dispatch_id": OURS, "nonce": "n" * 16, "node_ref": "node//X",
            "file_path": "C:/x", "command_id": "cmd_x",
            "run_id": "chat_pcq_" + "a" * 20, "kind": "command",
            "command_text": SHARE_COMMAND, "share_roots": ["", 3],
        }
        with mock.patch.object(executor, "_poll_payload", return_value=None), \
                mock.patch.object(executor, "_post", return_value=(200, {"ok": True, "dispatch": row})), \
                mock.patch.object(executor, "_leg_for", return_value="chat"):
            executor._carried_pairing_tags = []
            executor._reported_pairing_tags = set()
            dispatch = executor.poll_once()
        self.assertIsNone(dispatch.share_roots)


if __name__ == "__main__":
    unittest.main()
