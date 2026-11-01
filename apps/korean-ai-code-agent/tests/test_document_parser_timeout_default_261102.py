"""#2824: the isolated document parser now has a finite wait ceiling.

#4379 removed the wall-clock ceiling, so a hung parser child could hold a whole
PC work turn open and nothing above it could interrupt the wait. The default is
finite again, an operator narrows or widens it with one env value inside
[floor, ceiling], and an out-of-range or unparsable value falls back to the
default rather than to no ceiling at all.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

import kagent.document_parser_isolation as isolation
from kagent.document_intake import PARSER_TIMEOUT_NOTE

try:  # the document extra is optional in this environment
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except Exception:  # pragma: no cover - exercised only where the extra is absent
    PdfWriter = None


def _text_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for index in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        content = DecodedStreamObject()
        content.set_data(
            f"BT /F1 12 Tf 20 800 Td (timeout page {index}) Tj ET".encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class DefaultCeilingTests(unittest.TestCase):
    def test_the_default_ceiling_is_finite(self) -> None:
        self.assertEqual(
            isolation.DOCUMENT_PARSER_TIMEOUT_SECONDS,
            isolation.DOCUMENT_PARSER_TIMEOUT_DEFAULT_SECONDS,
        )
        self.assertEqual(
            isolation.DEFAULT_PARSER_ISOLATION_POLICY.timeout_seconds,
            isolation.DOCUMENT_PARSER_TIMEOUT_DEFAULT_SECONDS,
        )
        self.assertEqual(isolation.DOCUMENT_PARSER_TIMEOUT_SECONDS, 120.0)
        # The env value is clamped to this ceiling; a policy may still pass any
        # positive timeout it was already allowed to (#4379 unchanged).
        self.assertEqual(isolation.DOCUMENT_PARSER_TIMEOUT_CEILING_SECONDS, 600.0)
        self.assertEqual(isolation.DOCUMENT_PARSER_TIMEOUT_FLOOR_SECONDS, 10.0)
        self.assertIsNone(isolation.DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS)


class EnvironmentTests(unittest.TestCase):
    def test_values_inside_the_range_are_honoured(self) -> None:
        for raw, expected in (("45", 45.0), ("10", 10.0), ("600", 600.0), (" 30 ", 30.0)):
            with self.subTest(raw=raw):
                self.assertEqual(
                    isolation._configured_timeout_seconds(
                        {isolation.DOCUMENT_PARSER_TIMEOUT_ENV: raw}
                    ),
                    expected,
                )

    def test_out_of_range_or_unparsable_values_fall_back_to_the_default(self) -> None:
        for raw in ("5", "0", "-1", "601", "10000", "abc", "", "   ", "nan", "inf", None):
            with self.subTest(raw=raw):
                self.assertEqual(
                    isolation._configured_timeout_seconds(
                        {isolation.DOCUMENT_PARSER_TIMEOUT_ENV: raw}
                    ),
                    isolation.DOCUMENT_PARSER_TIMEOUT_DEFAULT_SECONDS,
                )

    def test_an_unset_value_is_the_default(self) -> None:
        self.assertEqual(
            isolation._configured_timeout_seconds({}),
            isolation.DOCUMENT_PARSER_TIMEOUT_DEFAULT_SECONDS,
        )

    def test_the_default_source_is_the_process_environment(self) -> None:
        with mock.patch.dict(
            os.environ, {isolation.DOCUMENT_PARSER_TIMEOUT_ENV: "45"}, clear=False
        ):
            self.assertEqual(isolation._configured_timeout_seconds(), 45.0)


class TimeoutBehaviourTests(unittest.TestCase):
    def _spawn_hung_child(self, argv, environment):
        """A real process that never writes a report; the ladder must kill it."""

        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_a_hung_child_is_killed_and_reported_as_a_timeout(self) -> None:
        handle: list[subprocess.Popen] = []

        def spawn(argv, environment):
            process = self._spawn_hung_child(argv, environment)
            handle.append(process)
            return process

        with mock.patch.object(isolation, "_spawn_parser_child", spawn):
            started = time.perf_counter()
            result = isolation.extract_binary_document_isolated(
                name="hung.pdf",
                media_type="application/pdf",
                payload=b"%PDF-1.7 fixture",
                policy=isolation.ParserIsolationPolicy(timeout_seconds=1.0),
            )
            elapsed = time.perf_counter() - started

        self.assertIs(result.outcome, isolation.ParserOutcome.TIMED_OUT)
        self.assertEqual(result.reason_code, isolation.PARSER_TIMEOUT_REASON_CODE)
        self.assertLess(elapsed, 15.0, "the ladder must not wait for the child")
        self.assertIsNotNone(handle[0].poll(), "the hung child outlived the ceiling")

    def test_the_owner_note_keeps_the_code_and_says_what_to_do(self) -> None:
        self.assertIn(isolation.PARSER_TIMEOUT_REASON_CODE, PARSER_TIMEOUT_NOTE)
        self.assertIn("나누", PARSER_TIMEOUT_NOTE)
        for leaked in ("C:\\", "Traceback", "sleep(", "timeout_seconds"):
            self.assertNotIn(leaked, PARSER_TIMEOUT_NOTE)

    @unittest.skipUnless(PdfWriter is not None, "the document extra is not installed")
    def test_a_normal_document_still_parses_under_the_default_ceiling(self) -> None:
        result = isolation.extract_binary_document_isolated(
            name="ok.pdf",
            media_type="application/pdf",
            payload=_text_pdf(3),
        )

        self.assertIs(result.outcome, isolation.ParserOutcome.COMPLETED)
        self.assertIn("timeout page 1", result.text or "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
