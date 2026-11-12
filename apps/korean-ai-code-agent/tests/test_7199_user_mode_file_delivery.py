"""#7199 — 사용자 모드는 콘솔 본문이 아니라 '파일 + -File' 로 PC 에 닿는다.

원인(측정 2026-11-07..08, 약 19시간): 사용자 모드 클라이언트(약 7KB, 여러 줄)를
MeshAgent 의 ``powershell -command -`` 콘솔 표준입력에 통째로 넣으면, 콘솔의 줄 파서가
열린 블록(``& { ... }``·``try``·here-string)을 다음 줄까지 기다리거나 8191자 넘는 한 줄을
토큰 중간에서 잘라, PowerShell 이 끝나지 않고 콘솔을 계속 점유한다. 에이전트는 명령
자식을 한 번에 하나만 돌리고 그동안 들어온 runcommand 는 "already busy" 로 버리므로,
멈춘 콘솔 하나가 모든 PC 명령을 막는다. SYSTEM 경로는 한 줄짜리라 이 문제를 겪지 않았다.

이 수정은 콘솔에 '완결된 짧은 한 줄' 만 보낸다: 마커를 먼저 쓰고, base64 조각으로 실제
클라이언트를 세션 변수에 쌓아 UTF-8 BOM 임시 ``.ps1`` 로 쓴 뒤 ``-File`` 로 실행한다 —
파일로 돌리면 0.4~2.3초에 끝나던 바로 그 호출이다. 봉투·센티널은 그대로라 회신 파싱은
바뀌지 않는다.
"""
from __future__ import annotations

import base64
import re
import unittest

from kagent.local_agent_meshcentral_command_port import (
    CONSOLE_CHUNK_CHARS,
    ENVELOPE_PREFIX,
    EXIT_SENTINEL,
    MeshCentralCliCommandPort,
    MeshCentralCommandRefused,
    PC_CANCEL_PID_FILE_PREFIX,
    _MAX_ARGV_ELEMENT_BYTES,
    _file_dispatch_console_script,
    _pid_file_literal,
    parse_transcript,
)

DID = "dsp_" + "ab12" * 6          # a well-formed dispatch id
HOST = "padiem-com2-exec.1"
NODE = "wYx8HR9Ou4C96Ys63@Dd2cdXxSOwp"
MESHCTRL = "/opt/meshcentral/meshctrl.js"
FAKE_PASSWORD = "fake-not-a-real-secret"  # test placeholder; not a credential

#: Every console line must sit under the Windows console input ceiling. The chunk
#: lines are held well below it so the staging never depends on line length.
CONSOLE_INPUT_LIMIT = 8191


def _lines(inner: str, dispatch_id: str = DID, host: str = HOST) -> list[str]:
    return _file_dispatch_console_script(inner, dispatch_id, host).split("\n")


def _balanced(line: str) -> tuple[int, int, int]:
    """Open braces, open parens, and odd single-quote count on one line.

    A line that opens a block or a string the NEXT line must close is exactly what
    put the agent's console parser into continuation and never returned.
    """
    return (
        line.count("{") - line.count("}"),
        line.count("(") - line.count(")"),
        line.count("'") % 2,
    )


class EveryConsoleLineIsCompleteAndShort(unittest.TestCase):
    def test_a_big_multi_line_client_becomes_short_complete_lines(self):
        inner = "\n".join("$v{0}='{0} '+('x'*60)".format(i) for i in range(500))
        lines = _lines(inner)
        self.assertTrue(len(lines) > 5)
        for i, line in enumerate(lines):
            self.assertLessEqual(len(line), CONSOLE_INPUT_LIMIT, f"line {i} too long")
            self.assertEqual(_balanced(line), (0, 0, 0), f"line {i} is not self-contained: {line[:60]!r}")

    def test_chunk_lines_stay_under_the_configured_bound(self):
        inner = "y" * 40_000
        chunk_lines = [l for l in _lines(inner) if l.startswith("$__s+=")]
        self.assertTrue(chunk_lines)
        for line in chunk_lines:
            # ``$__s+='<=1000 chars>'`` — body never exceeds the chunk bound.
            body = re.fullmatch(r"\$__s\+='([^']*)'", line).group(1)
            self.assertLessEqual(len(body), CONSOLE_CHUNK_CHARS)

    def test_the_staged_bytes_round_trip_to_the_exact_client(self):
        inner = "whoami\n$x = 'préféré 안녕 ' + 1\n# a comment with 'quotes' and `backtick`"
        chunks = re.findall(r"^\$__s\+='([^']*)'$", _file_dispatch_console_script(inner, DID, HOST), re.M)
        self.assertEqual(base64.b64decode("".join(chunks)).decode("utf-8"), inner)


class TheMarkerAndInvocationMatchTheStopContract(unittest.TestCase):
    def test_the_marker_is_written_pid_first_then_host_tag(self):
        script = _file_dispatch_console_script("whoami", DID, HOST)
        # The reaper reads the file as (pid, host) with ``Select-Object -First 2`` and
        # the stop reads the pid with ``-First 1``; the order and the filename are the
        # contract those two rely on.
        self.assertIn(PC_CANCEL_PID_FILE_PREFIX + DID + ".pid", script)
        self.assertIn(_pid_file_literal(DID), script)
        pid_at = script.index("Set-Content -LiteralPath $__pp -Value $PID -Encoding ascii")
        host_at = script.index("Add-Content -LiteralPath $__pp -Value '" + HOST + "' -Encoding ascii")
        self.assertLess(pid_at, host_at)

    def test_no_host_tag_writes_the_pid_and_start_time_lines(self):
        script = _file_dispatch_console_script("whoami", DID, None)
        self.assertIn("Set-Content -LiteralPath $__pp -Value $PID -Encoding ascii", script)
        # No tag: no host line. #7564 adds the start-time line unconditionally.
        self.assertNotIn("Add-Content -LiteralPath $__pp -Value '", script)
        self.assertIn("-Value $__padiem_dt.ToFileTime()", script)

    def test_the_client_runs_as_a_file_not_as_console_input(self):
        script = _file_dispatch_console_script("whoami", DID, HOST)
        self.assertIn(PC_CANCEL_PID_FILE_PREFIX + DID + ".ps1", script)
        self.assertIn("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File $__fp", script)
        # The temp files are removed whatever the child did.
        self.assertIn("Remove-Item -LiteralPath $__fp", script)
        self.assertIn("Remove-Item -LiteralPath $__pp", script)

    def test_the_script_text_never_carries_the_joined_marker_tokens(self):
        # The envelope and sentinel are built at runtime from split literals, so a
        # terminal that echoed this script could not be read back as an answer, and a
        # base64 chunk (no '_' in the alphabet) can never contain them either.
        script = _file_dispatch_console_script("whoami", DID, HOST)
        self.assertNotIn(ENVELOPE_PREFIX, script)
        self.assertNotIn(EXIT_SENTINEL, script)
        self.assertIn("'PADIEM_'+'B64='", script)
        self.assertIn("'__PADIEM_'+'EXIT__'", script)

    def test_a_file_delivered_reply_parses_through_the_unchanged_envelope(self):
        # The console wrapper base64-encodes the client's stdout into the same
        # PADIEM_B64 envelope and prints the same sentinel, so parse_transcript reads
        # a file-delivered reply exactly as it reads a wrapped one.
        client_json = '{"request_id":"req_x","status":"ok","exit_code":0,"stdout_b64":"bGltb25l"}'
        transcript = (
            ENVELOPE_PREFIX + base64.b64encode(client_json.encode()).decode() + "\n"
            + EXIT_SENTINEL + "0\n"
        ).encode()
        termination, code, body = parse_transcript(transcript)
        self.assertEqual(termination, "exited")
        self.assertEqual(code, 0)
        self.assertEqual(body.decode(), client_json)


class _Completed:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _capturing_port(calls):
    def runner(argv, **kwargs):
        calls.append(list(argv))
        ok = (
            ENVELOPE_PREFIX + base64.b64encode(b"{}").decode() + "\n"
            + EXIT_SENTINEL + "0\n"
        ).encode()
        return _Completed(0, ok)

    return MeshCentralCliCommandPort(
        command_runner=runner,
        meshctrl_js=MESHCTRL,
        login_user="padiemadmin",
        password_provider=lambda: FAKE_PASSWORD,
        url="wss://127.0.0.1:4443",
    )


def _run_value(argv: list[str]) -> str:
    return argv[argv.index("--run") + 1]


class RunCommandRoutesUserModeToFileDelivery(unittest.TestCase):
    def test_file_delivery_sends_the_staging_script_not_the_wrapped_body(self):
        calls: list = []
        inner = "\n".join("$v{0}=1".format(i) for i in range(300))  # multi-line client
        _capturing_port(calls).run_command(
            node_ref=NODE, command=inner, dispatch_id=DID, deliver_as_file=True)
        sent = _run_value(calls[0])
        # It is the staging script: the dispatch marker and the -File run are present,
        # the chunks rebuild the exact client, and the client body is NEVER wrapped in
        # the SYSTEM ``& { ... }`` block that stalled the console.
        self.assertIn(_pid_file_literal(DID), sent)
        self.assertIn("-File $__fp", sent)
        chunks = re.findall(r"^\$__s\+='([^']*)'$", sent, re.M)
        self.assertEqual(base64.b64decode("".join(chunks)).decode("utf-8"), inner)
        self.assertNotIn("& { ", sent)
        for line in sent.split("\n"):
            self.assertEqual(_balanced(line), (0, 0, 0))

    def test_system_mode_still_uses_the_wrapped_single_block(self):
        calls: list = []
        _capturing_port(calls).run_command(
            node_ref=NODE, command="hostname.exe", dispatch_id=DID, deliver_as_file=False)
        sent = _run_value(calls[0])
        self.assertIn("& { hostname.exe", sent)
        self.assertNotIn("-File $__fp", sent)

    def test_file_delivery_requires_a_dispatch_id_for_its_marker(self):
        calls: list = []
        with self.assertRaises(MeshCentralCommandRefused):
            _capturing_port(calls).run_command(
                node_ref=NODE, command="whoami", dispatch_id=None, deliver_as_file=True)
        self.assertEqual(calls, [])

    def test_a_client_that_fits_stays_one_argv_element(self):
        calls: list = []
        inner = "z" * 50_000
        _capturing_port(calls).run_command(
            node_ref=NODE, command=inner, dispatch_id=DID, deliver_as_file=True)
        sent = _run_value(calls[0])
        self.assertLessEqual(len(sent.encode("utf-8")) + 1, _MAX_ARGV_ELEMENT_BYTES)
        for line in sent.split("\n"):
            self.assertLessEqual(len(line), CONSOLE_INPUT_LIMIT)

    def test_a_client_too_large_to_exec_is_refused_with_its_cause(self):
        calls: list = []
        with self.assertRaises(MeshCentralCommandRefused):
            _capturing_port(calls).run_command(
                node_ref=NODE, command="q" * 110_000, dispatch_id=DID, deliver_as_file=True)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
