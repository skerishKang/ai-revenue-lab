"""#2824-S3A: the local document parser runs in a dedicated, killable process.

These tests are non-vacuous. They start the real child process, hang a real
child and prove it dies, and drive the kill ladder against a process double that
refuses to stop. Nothing here asserts that a string appears in a module — except
where the claim *is* about structure (the child holds no process authority) and
is simultaneously proven at runtime by importing the child in a real process.

Coverage map (CENTRAL S3-A work order):

* A  valid PDF/DOCX/HWPX -> isolated child -> normal result
* B  gate rejection -> child process created 0
* C  parser hang -> finite timeout -> TIMED_OUT -> child dead
* D  terminate that will not stop the child -> kill escalation -> child dead
* E  timeout != cancellation
* F  timeout error: payload 0, absolute path 0, traceback 0, secret 0
* G  malformed child result -> fail closed
* H  oversized child result -> fail closed
* I  child crash -> bounded deterministic failure
* J  Windows spawn/import behaviour
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pragma: no cover - documents extra provides pypdf
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

import kagent.document_parser_contract as contract
import kagent.document_parser_isolation as isolation
from kagent.document_intake import (
    PARSER_ISOLATION_FAILURE_NOTE,
    PARSER_TIMEOUT_NOTE,
    intake_document,
)
from kagent.draft_flow import DraftFlowError, _read_draft_input

DOCX_MEDIA = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
HWPX_MEDIA = "application/hwp+zip"
PDF_MEDIA = "application/pdf"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_LEAK_MARKER = "RAWPAYLOADMARKERDO_NOT_LEAK"
_SECRET = "SUPERSECRETTOKENDO_NOT_LEAK"


def _docx_xml(text: str = "Hello Docx Document") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )


def _build_zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _minimal_docx(text: str = "Hello Docx Document") -> bytes:
    return _build_zip([("word/document.xml", _docx_xml(text).encode("utf-8"))])


def _minimal_hwpx(*paragraphs: str) -> bytes:
    body = "".join(
        f"<hp:p><hp:r><hp:t>{paragraph}</hp:t></hp:r></hp:p>"
        for paragraph in (paragraphs or ("Hello HwpX Document",))
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        + body
        + "</hs:sec>"
    )
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
        ]
    )


def _minimal_pdf(text: str = "Hello Padiem Document") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=320, height=180)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class _SpawnSpy:
    """Count and record spawns, then delegate to the real child."""

    def __init__(self, delegate=None) -> None:
        self.argv: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self._delegate = delegate or isolation._spawn_parser_child

    def __call__(self, argv: list[str], environment: dict[str, str]):
        self.argv.append(list(argv))
        self.environments.append(dict(environment))
        return self._delegate(argv, environment)

    @property
    def calls(self) -> int:
        return len(self.argv)


class _ProcessDouble:
    """``Popen``-shaped double whose terminate and kill can be ignored.

    ``wait`` raises ``TimeoutExpired`` while the process is alive, so the ladder
    is driven without waiting on a real clock.
    """

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        alive: bool = False,
        ignores_terminate: bool = False,
        ignores_kill: bool = False,
    ) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode: int | None = None if alive else exit_code
        self.terminated = False
        self.killed = False
        self._exit_code = exit_code
        self._alive = alive
        self._ignores_terminate = ignores_terminate
        self._ignores_kill = ignores_kill

    def wait(self, timeout: float | None = None) -> int | None:
        if self._alive:
            raise subprocess.TimeoutExpired("parser-child", timeout or 0.0)
        return self.returncode

    def poll(self) -> int | None:
        return None if self._alive else self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignores_terminate:
            self._alive = False
            self.returncode = self._exit_code

    def kill(self) -> None:
        self.killed = True
        if not self._ignores_kill:
            self._alive = False
            self.returncode = self._exit_code


def _spawn_returning(process: _ProcessDouble):
    return lambda argv, environment: process


def _spawn_running(program: list[str]) -> tuple[object, list]:
    """A real ``Popen`` of an arbitrary attacker-shaped child program.

    The boundary's own argv is deliberately ignored so the ladder is driven
    against a real process that hangs, crashes or ignores termination.
    """

    handles: list = []

    def spawn(_argv: list[str], environment: dict[str, str]):
        process = subprocess.Popen(
            program,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        handles.append(process)
        return process

    return spawn, handles


def _imported_module_names(path: Path) -> set[str]:
    """Every module name imported by a source file, straight from its AST.

    Reading the AST rather than the text is what makes the structural
    assertions documentation-proof: prose that *names* a forbidden module cannot
    trip a test, and a real import cannot hide behind a comment.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(node.module.split(".")[0])
            for alias in node.names:
                names.add(alias.name)
    return names


def _called_names(path: Path) -> set[str]:
    """Every bare-name or attribute call target in a source file."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called.add(func.id)
        elif isinstance(func, ast.Attribute):
            called.add(func.attr)
    return called


def _popen_keywords(path: Path) -> list[str]:
    """Keyword argument names of the ``subprocess.Popen`` call in a module."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Popen"
        ):
            return [keyword.arg for keyword in node.keywords if keyword.arg]
    return []


def _hang_command() -> list[str]:
    """A real child that never reads stdin and never finishes in time.

    The sleep is deliberately short: the enforced timeout is 1s, so this proves
    the timeout is finite, while a *mutated* ladder that fails to kill the child
    can only leave a short-lived orphan instead of a two-minute one.
    """

    return [sys.executable, "-c", "import time; time.sleep(30)"]


class ValidDocumentIsolationTests(unittest.TestCase):
    """A: an admitted document really runs in the isolated child."""

    def _parse(self, name: str, media_type: str, payload: bytes):
        spy = _SpawnSpy()
        with mock.patch.object(isolation, "_spawn_parser_child", spy):
            result = isolation.extract_binary_document_isolated(
                name=name, media_type=media_type, payload=payload
            )
        return result, spy

    def test_valid_docx_runs_in_an_isolated_child(self) -> None:
        result, spy = self._parse("plan.docx", DOCX_MEDIA, _minimal_docx())
        self.assertEqual(result.outcome, isolation.ParserOutcome.COMPLETED)
        self.assertEqual(result.reason_code, "ok")
        self.assertEqual(result.text, "Hello Docx Document")
        self.assertEqual(result.child_exit_code, 0)
        self.assertEqual(spy.calls, 1)

    def test_valid_hwpx_runs_in_an_isolated_child(self) -> None:
        result, spy = self._parse(
            "note.hwpx", HWPX_MEDIA, _minimal_hwpx("견적서", "합계 1,000원")
        )
        self.assertEqual(result.outcome, isolation.ParserOutcome.COMPLETED)
        self.assertEqual(result.text, "견적서\n합계 1,000원")
        self.assertEqual(spy.calls, 1)

    def test_valid_pdf_runs_in_an_isolated_child(self) -> None:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the workspace documents extra")
        result, spy = self._parse("plan.pdf", PDF_MEDIA, _minimal_pdf())
        self.assertEqual(result.outcome, isolation.ParserOutcome.COMPLETED)
        self.assertEqual(result.text, "Hello Padiem Document")
        self.assertEqual(spy.calls, 1)

    def test_core_rejection_is_reported_as_a_bounded_code(self) -> None:
        corrupt = _build_zip([("word/document.xml", b"<broken")])
        result, spy = self._parse("bad.docx", DOCX_MEDIA, corrupt)
        self.assertEqual(result.outcome, isolation.ParserOutcome.REJECTED)
        self.assertEqual(result.reason_code, "ooxml_invalid_xml")
        self.assertIsNone(result.text)
        self.assertEqual(spy.calls, 1)

    def test_started_command_is_fixed_and_never_contains_caller_data(self) -> None:
        name = "plan.docx"
        _, spy = self._parse(name, DOCX_MEDIA, _minimal_docx())
        self.assertEqual(len(spy.argv), 1)
        argv = spy.argv[0]
        self.assertEqual(argv, [sys.executable, "-P", "-m", contract.CHILD_MODULE_NAME])
        self.assertNotIn(name, argv)
        self.assertNotIn("-c", argv)
        for token in argv:
            self.assertNotIn(_LEAK_MARKER, token)


class GateBeforeSpawnTests(unittest.TestCase):
    """B: a gate denial must not create a child process at all."""

    def _assert_no_spawn(self, name: str, payload: bytes) -> None:
        spy = _SpawnSpy()
        with mock.patch.object(isolation, "_spawn_parser_child", spy):
            intake_document(name, payload)
        self.assertEqual(spy.calls, 0, name)
        self.assertEqual(spy.argv, [], name)

    def test_spoofed_content_never_spawns_a_parser_child(self) -> None:
        for name, payload in (
            ("fake.pdf", b"plain text, not a PDF" + _LEAK_MARKER.encode()),
            ("fake.docx", b"not a zip archive"),
            ("fake.hwpx", b"PK not a real hwpx archive"),
            ("report.pdf", PNG_BYTES),
            ("report.docx", _minimal_hwpx("견적서")),
            ("report.docx", _build_zip([("a.txt", b"x")])),
        ):
            with self.subTest(name=name, kind=payload[:4]):
                self._assert_no_spawn(name, payload)

    def test_archive_policy_denial_never_spawns_a_parser_child(self) -> None:
        bomb = _build_zip(
            [
                ("word/document.xml", _docx_xml().encode("utf-8")),
                ("bomb.bin", b"\x00" * 500_000),
            ]
        )
        traversal = _build_zip(
            [
                ("word/document.xml", _docx_xml().encode("utf-8")),
                ("../escape.xml", b"<x/>"),
            ]
        )
        for name, payload in (("bomb.docx", bomb), ("trav.docx", traversal)):
            with self.subTest(name=name):
                self._assert_no_spawn(name, payload)

    def test_legacy_hwp_and_plain_text_never_spawn_a_parser_child(self) -> None:
        self._assert_no_spawn("note.hwp", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)
        self._assert_no_spawn("README.md", b"# hi\n")
        self._assert_no_spawn("photo.png", PNG_BYTES)


class HardTimeoutTests(unittest.TestCase):
    """C/F: a hung parser is terminated by a finite, enforced timeout."""

    def test_real_hanging_child_is_killed_and_reported_as_timed_out(self) -> None:
        spawn, handles = _spawn_running(_hang_command())
        policy = isolation.ParserIsolationPolicy(
            timeout_seconds=1.0, terminate_grace_seconds=3.0
        )
        started = time.monotonic()
        with mock.patch.object(isolation, "_spawn_parser_child", spawn):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx",
                media_type=DOCX_MEDIA,
                payload=_minimal_docx(),
                policy=policy,
            )
        elapsed = time.monotonic() - started

        self.assertEqual(result.outcome, isolation.ParserOutcome.TIMED_OUT)
        self.assertEqual(result.reason_code, contract.PARSER_TIMEOUT_REASON_CODE)
        self.assertIsNone(result.text)
        # A terminated child reports no exit code, matching the semantic
        # reference in kagent.windows_local_executor.
        self.assertIsNone(result.child_exit_code)

        # The timeout is finite and the child is really gone.
        self.assertLess(elapsed, 30.0)
        self.assertEqual(len(handles), 1)
        handle = handles[0]
        self.assertIsNotNone(handle.poll(), "the parser child outlived the timeout")
        self.assertIsNotNone(handle.returncode)

    def test_hanging_child_through_intake_document_uses_the_timeout_note(self) -> None:
        spawn, handles = _spawn_running(_hang_command())
        policy = isolation.ParserIsolationPolicy(timeout_seconds=1.0)
        with mock.patch.object(isolation, "_spawn_parser_child", spawn), mock.patch.object(
            isolation, "DEFAULT_PARSER_ISOLATION_POLICY", policy
        ):
            result = intake_document("plan.docx", _minimal_docx())
        self.assertIsNotNone(result)
        self.assertIsNone(result.text)
        self.assertEqual(result.note, PARSER_TIMEOUT_NOTE)
        self.assertIsNotNone(handles[0].poll(), "the parser child outlived the timeout")

    def test_timeout_note_leaks_no_payload_path_traceback_or_secret(self) -> None:
        payload = _build_zip(
            [
                ("word/document.xml", _docx_xml().encode("utf-8")),
                ("notes/secret.txt", f"{_LEAK_MARKER} {_SECRET}".encode()),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret-vault" / "plan.docx"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

            spawn, handles = _spawn_running(_hang_command())
            policy = isolation.ParserIsolationPolicy(timeout_seconds=1.0)
            with mock.patch.object(isolation, "_spawn_parser_child", spawn), mock.patch.object(
                isolation, "DEFAULT_PARSER_ISOLATION_POLICY", policy
            ), self.assertRaises(DraftFlowError) as ctx:
                _read_draft_input(path)

            message = ctx.exception.safe_message
            self.assertEqual(ctx.exception.code, "draft_input_invalid")
            self.assertNotIn(_LEAK_MARKER, message)
            self.assertNotIn(_SECRET, message)
            self.assertNotIn("Traceback", message)
            self.assertNotIn("Exception", message)
            self.assertNotIn(str(path), message)
            self.assertNotIn(path.name, message)
            self.assertNotIn(str(path.parent), message)
            self.assertNotIn("secret.txt", message)
            self.assertLess(len(message), 120, message)
            self.assertIsNotNone(handles[0].poll())

    def test_surviving_child_fails_closed_instead_of_being_called_a_timeout(self) -> None:
        process = _ProcessDouble(alive=True, ignores_terminate=True, ignores_kill=True)
        with mock.patch.object(
            isolation, "_spawn_parser_child", _spawn_returning(process)
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx",
                media_type=DOCX_MEDIA,
                payload=_minimal_docx(),
                policy=isolation.ParserIsolationPolicy(
                    timeout_seconds=1.0, terminate_grace_seconds=0.05, kill_grace_seconds=0.05
                ),
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertIsNone(result.text)


class KillEscalationTests(unittest.TestCase):
    """D: terminate that does not stop the child must escalate to kill."""

    def test_ignored_terminate_escalates_to_kill(self) -> None:
        process = _ProcessDouble(alive=True, ignores_terminate=True)
        with mock.patch.object(
            isolation, "_spawn_parser_child", _spawn_returning(process)
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx",
                media_type=DOCX_MEDIA,
                payload=_minimal_docx(),
                policy=isolation.ParserIsolationPolicy(
                    timeout_seconds=1.0, terminate_grace_seconds=0.05
                ),
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.poll(), "the child survived the kill escalation")
        self.assertEqual(result.outcome, isolation.ParserOutcome.TIMED_OUT)
        self.assertTrue(result.terminated_by_kill)
        self.assertEqual(result.reason_code, contract.PARSER_TIMEOUT_REASON_CODE)

    def test_successful_terminate_does_not_escalate_to_kill(self) -> None:
        process = _ProcessDouble(alive=True)
        with mock.patch.object(
            isolation, "_spawn_parser_child", _spawn_returning(process)
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx",
                media_type=DOCX_MEDIA,
                payload=_minimal_docx(),
                policy=isolation.ParserIsolationPolicy(
                    timeout_seconds=1.0, terminate_grace_seconds=0.05
                ),
            )
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertEqual(result.outcome, isolation.ParserOutcome.TIMED_OUT)
        self.assertFalse(result.terminated_by_kill)

    def test_timeout_action_cannot_be_weakened(self) -> None:
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.ParserIsolationPolicy(timeout_action="warn")
        self.assertEqual(isolation.PARSER_TIMEOUT_ACTION, "kill")


class TimeoutIsNotCancellationTests(unittest.TestCase):
    """E: the boundary has no cancellation authority and never claims one."""

    def test_outcome_vocabulary_has_no_cancellation_term(self) -> None:
        self.assertEqual(
            {outcome.value for outcome in isolation.ParserOutcome},
            {"completed", "rejected", "timed_out", "failed"},
        )
        for name in ("cancel", "cancelled", "cancel_parse", "abort"):
            self.assertFalse(
                hasattr(isolation, name), f"unexpected cancellation authority: {name}"
            )

    def test_timeout_and_failure_have_distinct_outcomes_notes_and_codes(self) -> None:
        self.assertNotEqual(
            isolation.ParserOutcome.TIMED_OUT, isolation.ParserOutcome.FAILED
        )
        self.assertNotEqual(PARSER_TIMEOUT_NOTE, PARSER_ISOLATION_FAILURE_NOTE)
        self.assertIn(
            contract.PARSER_TIMEOUT_REASON_CODE, PARSER_TIMEOUT_NOTE
        )
        self.assertNotIn(
            contract.PARSER_ISOLATION_FAILURE_REASON_CODE, PARSER_TIMEOUT_NOTE
        )

    def test_timed_out_result_may_not_carry_text_or_an_exit_code(self) -> None:
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.IsolatedParseResult(
                outcome=isolation.ParserOutcome.TIMED_OUT,
                reason_code=contract.PARSER_TIMEOUT_REASON_CODE,
                text="partial",
            )
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.IsolatedParseResult(
                outcome=isolation.ParserOutcome.TIMED_OUT,
                reason_code=contract.PARSER_TIMEOUT_REASON_CODE,
                child_exit_code=0,
            )


class BoundedChildResultTests(unittest.TestCase):
    """G/H/I: an untrustworthy child result fails closed with a bounded code."""

    def _boundary(self, process: _ProcessDouble, policy=None):
        with mock.patch.object(
            isolation, "_spawn_parser_child", _spawn_returning(process)
        ):
            return isolation.extract_binary_document_isolated(
                name="plan.docx",
                media_type=DOCX_MEDIA,
                payload=_minimal_docx(),
                policy=policy or isolation.DEFAULT_PARSER_ISOLATION_POLICY,
            )

    def test_malformed_child_output_fails_closed(self) -> None:
        for label, stdout in (
            ("not-json", b"not a report at all"),
            ("partial", b'{"ok": true, "text": "trunca'),
            ("empty", b""),
            ("not-an-object", b'["ok", true]'),
            ("missing-ok", b'{"text": "hello"}'),
            ("wrong-type", b'{"ok": "yes", "text": "hello"}'),
            ("success-with-code", b'{"ok": true, "text": "hi", "code": "ooxml_invalid_xml"}'),
            ("success-with-extra-key", b'{"ok": true, "text": "hi", "extra": 1}'),
            ("refusal-with-text", b'{"ok": false, "code": "ooxml_invalid_xml", "text": "hi"}'),
        ):
            with self.subTest(label=label):
                result = self._boundary(_ProcessDouble(stdout=stdout))
                self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
                self.assertIsNone(result.text)
                self.assertEqual(
                    result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
                )

    def test_unbounded_reason_code_in_a_child_report_fails_closed(self) -> None:
        # A traceback, a payload or a host path can never match the bounded
        # reason grammar, so it cannot be projected as a parse outcome.
        for code in (
            "Traceback (most recent call last): File \"C:/x.py\"",
            _LEAK_MARKER,
            "ooxml_invalid_xml; rm -rf /",
            "Ooxml_Invalid_Xml",
            "x" * 200,
        ):
            with self.subTest(code=code[:24]):
                payload = json.dumps({"ok": False, "code": code}).encode("utf-8")
                result = self._boundary(_ProcessDouble(stdout=payload))
                self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
                self.assertEqual(
                    result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
                )

    def test_oversized_child_output_fails_closed(self) -> None:
        body = json.dumps({"ok": True, "text": "x" * 500}).encode("utf-8")
        policy = isolation.ParserIsolationPolicy(max_output_bytes=64)
        result = self._boundary(_ProcessDouble(stdout=body), policy=policy)
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertIsNone(result.text)

    def test_child_text_over_the_core_character_bound_fails_closed(self) -> None:
        over = json.dumps({"ok": True, "text": "x" * 50_000}).encode("utf-8")
        result = self._boundary(_ProcessDouble(stdout=over))
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertIsNone(result.text)

    def test_nonzero_child_exit_code_fails_closed(self) -> None:
        body = json.dumps({"ok": True, "text": "hello"}).encode("utf-8")
        result = self._boundary(_ProcessDouble(stdout=body, exit_code=1))
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertIsNone(result.text)

    def test_child_result_with_missing_pipes_fails_closed(self) -> None:
        process = _ProcessDouble()
        process.stdout = None
        with mock.patch.object(
            isolation, "_spawn_parser_child", _spawn_returning(process)
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=_minimal_docx()
            )
        self.assertTrue(process.killed)
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)

    def test_oversized_input_is_refused_without_spawning(self) -> None:
        oversized = b"%PDF-" + b"\x00" * (2 * 1024 * 1024)
        spy = _SpawnSpy()
        with mock.patch.object(isolation, "_spawn_parser_child", spy):
            result = isolation.extract_binary_document_isolated(
                name="plan.pdf", media_type=PDF_MEDIA, payload=oversized
            )
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertEqual(result.reason_code, contract.PARSER_INPUT_REASON_CODE)

    def test_empty_payload_is_refused_without_spawning(self) -> None:
        spy = _SpawnSpy()
        with mock.patch.object(isolation, "_spawn_parser_child", spy):
            result = isolation.extract_binary_document_isolated(
                name="plan.pdf", media_type=PDF_MEDIA, payload=b""
            )
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.reason_code, contract.PARSER_INPUT_REASON_CODE)

    def test_child_stderr_is_drained_and_never_surfaced(self) -> None:
        body = json.dumps({"ok": True, "text": "hello"}).encode("utf-8")
        noisy = _ProcessDouble(
            stdout=body, stderr=(_LEAK_MARKER + "\n" + _SECRET + "\n").encode() * 5000
        )
        result = self._boundary(noisy)
        self.assertEqual(result.outcome, isolation.ParserOutcome.COMPLETED)
        self.assertEqual(result.text, "hello")
        self.assertNotIn(_LEAK_MARKER, repr(result))
        self.assertNotIn(_SECRET, repr(result))


class ChildCrashTests(unittest.TestCase):
    """I/J: a child that cannot run becomes one bounded, deterministic failure."""

    def test_real_child_that_exits_without_a_report_fails_closed(self) -> None:
        command = [sys.executable, "-c", "import sys; sys.exit(3)"]
        spawn, handles = _spawn_running(command)
        with mock.patch.object(isolation, "_spawn_parser_child", spawn):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=_minimal_docx()
            )
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertIsNone(result.text)
        self.assertEqual(result.child_exit_code, 3)
        self.assertEqual(handles[0].returncode, 3)

    def test_real_child_without_the_module_fails_closed(self) -> None:
        # The production command line and environment are used unchanged; only
        # the import root is emptied, so this exercises a real import failure.
        with tempfile.TemporaryDirectory() as empty_root, mock.patch.object(
            isolation, "_child_environment", lambda: {"PYTHONPATH": empty_root}
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=_minimal_docx()
            )
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertIsNone(result.text)
        self.assertIsNotNone(result.child_exit_code)
        self.assertNotEqual(result.child_exit_code, 0)

    def test_missing_interpreter_is_a_bounded_failure_without_a_spawn(self) -> None:
        spy = _SpawnSpy()
        with mock.patch.object(isolation, "_spawn_parser_child", spy), mock.patch.object(
            isolation.sys, "executable", ""
        ):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=_minimal_docx()
            )
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)

    def test_spawn_oserror_is_a_bounded_failure(self) -> None:
        def explode(argv, environment):
            raise OSError("cannot start the parser child")

        with mock.patch.object(isolation, "_spawn_parser_child", explode):
            result = isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=_minimal_docx()
            )
        self.assertEqual(result.outcome, isolation.ParserOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.PARSER_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertNotIn("cannot start", result.reason_code)


class ChildAuthorityTests(unittest.TestCase):
    """The child starts nothing, and the boundary grants it nothing."""

    def test_child_holds_no_process_creation_authority_at_runtime(self) -> None:
        # Proven in a real process, in the production child environment.
        probe = (
            "import kagent.document_parser_child as module;"
            "names = ('subprocess', 'multiprocessing', 'Popen', 'system', 'fork',"
            " 'spawn', 'Thread', 'alarm');"
            "print(sorted(name for name in names if hasattr(module, name)))"
        )
        completed = subprocess.run(
            [sys.executable, "-P", "-c", probe],
            capture_output=True,
            text=True,
            env=isolation._child_environment(),
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-400:])
        self.assertEqual(completed.stdout.strip(), "[]")

    def test_child_imports_no_process_thread_signal_or_file_authority(self) -> None:
        child = Path(isolation.__file__).with_name("document_parser_child.py")
        imported = _imported_module_names(child)
        for forbidden in (
            "subprocess",
            "multiprocessing",
            "concurrent",
            "threading",
            "signal",
            "pathlib",
            "tempfile",
            "os",
            "shutil",
            "socket",
            "urllib",
            "httpx",
            "requests",
        ):
            self.assertNotIn(forbidden, imported, forbidden)
        called = _called_names(child)
        for forbidden in ("open", "system", "popen", "fork", "spawn", "exec"):
            self.assertNotIn(forbidden, called, forbidden)

    def test_child_module_delegates_the_parse_to_core_only(self) -> None:
        child = Path(isolation.__file__).with_name("document_parser_child.py")
        imported = _imported_module_names(child)
        self.assertIn("padiem_ai_core", imported)
        self.assertIn("extract_binary_document", imported)
        called = _called_names(child)
        self.assertIn("extract_binary_document", called)
        # No format or bound re-implementation in the child.
        for forbidden in ("ZipFile", "ElementTree", "PdfReader", "load_workbook"):
            self.assertNotIn(forbidden, called, forbidden)

    def test_boundary_does_not_request_a_process_group_shell_or_executor(self) -> None:
        imported = _imported_module_names(Path(isolation.__file__))
        # ``subprocess`` is the process authority this module deliberately owns;
        # every cooperative mechanism is absent by construction.
        self.assertIn("subprocess", imported)
        for forbidden in (
            "asyncio",
            "concurrent",
            "multiprocessing",
            "signal",
            "windows_local_executor",
        ):
            self.assertNotIn(forbidden, imported, forbidden)

        keywords = _popen_keywords(Path(isolation.__file__))
        self.assertIn("shell", keywords)
        self.assertIn("creationflags", keywords)
        for forbidden in ("start_new_session", "preexec_fn", "process_group"):
            self.assertNotIn(forbidden, keywords, forbidden)

    def test_timeout_action_is_kill_not_a_cooperative_cancel(self) -> None:
        source = Path(isolation.__file__).read_text(encoding="utf-8")
        self.assertIn("process.terminate()", source)
        self.assertIn("process.kill()", source)
        self.assertEqual(isolation.PARSER_TIMEOUT_ACTION, "kill")
        called = _called_names(Path(isolation.__file__))
        for forbidden in ("wait_for", "ProcessPoolExecutor", "ThreadPoolExecutor"):
            self.assertNotIn(forbidden, called, forbidden)

    def test_import_roots_expose_only_the_reviewed_kagent_tree(self) -> None:
        roots = isolation.child_import_roots()
        self.assertEqual(len(roots), 1)
        self.assertTrue(roots[0].endswith(os.path.join("korean-ai-code-agent", "src")))
        self.assertIn(os.pathsep.join(roots), isolation._child_environment()["PYTHONPATH"])

    def test_child_environment_is_bounded_and_drops_caller_values(self) -> None:
        environment = isolation._child_environment()
        self.assertEqual(
            set(environment),
            {
                "PYTHONPATH",
                "PYTHONIOENCODING",
                "PYTHONUTF8",
                "SystemRoot",
                "WINDIR",
                "SystemDrive",
                "APPDATA",
                "USERPROFILE",
                "HOME",
            }
            & set(environment),
        )
        for forbidden in ("PATH", "TEMP", "TMP", "PADIEM_CHAT_LIVE_ENABLED"):
            self.assertNotIn(forbidden, environment)
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(environment["PYTHONUTF8"], "1")


class PolicyTests(unittest.TestCase):
    """The timeout and the byte ceilings are bounded on both sides."""

    def test_default_timeout_is_the_central_decision(self) -> None:
        self.assertEqual(isolation.DOCUMENT_PARSER_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(
            isolation.DEFAULT_PARSER_ISOLATION_POLICY.timeout_seconds, 30.0
        )
        self.assertLessEqual(
            isolation.DOCUMENT_PARSER_TIMEOUT_SECONDS,
            isolation.DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS,
        )

    def test_unbounded_or_non_positive_timeouts_are_rejected(self) -> None:
        for value in (0, 0.0, -1.0, 30.5, 31.0, 300.0, float("inf"), float("nan")):
            with self.subTest(timeout=value), self.assertRaises(
                isolation.ParserIsolationError
            ):
                isolation.ParserIsolationPolicy(timeout_seconds=value)

    def test_grace_and_ceiling_values_are_validated(self) -> None:
        for kwargs in (
            {"terminate_grace_seconds": 0},
            {"kill_grace_seconds": -1},
            {"drain_join_seconds": 0},
            {"max_envelope_bytes": 0},
            {"max_output_bytes": -5},
            {"max_error_bytes": True},
        ):
            with self.subTest(**kwargs), self.assertRaises(
                isolation.ParserIsolationError
            ):
                isolation.ParserIsolationPolicy(**kwargs)

    def test_policy_rejects_a_non_policy_and_bad_input_types(self) -> None:
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload=b"x", policy=object()
            )
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.extract_binary_document_isolated(
                name=None, media_type=DOCX_MEDIA, payload=b"x"
            )
        with self.assertRaises(isolation.ParserIsolationError):
            isolation.extract_binary_document_isolated(
                name="plan.docx", media_type=DOCX_MEDIA, payload="not bytes"
            )

    def test_contract_ceilings_are_derived_from_the_core_bounds(self) -> None:
        self.assertGreater(contract.MAX_CHILD_ENVELOPE_BYTES, 2 * 1024 * 1024)
        self.assertGreater(contract.MAX_CHILD_OUTPUT_BYTES, 40_000)
        self.assertEqual(contract.MAX_CHILD_ERROR_BYTES, 8192)


if __name__ == "__main__":
    unittest.main()
