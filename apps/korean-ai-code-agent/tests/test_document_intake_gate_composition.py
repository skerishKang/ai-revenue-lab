"""#2824-S2: the common pre-parser gate is composed ahead of the Core parser.

These tests are non-vacuous: they do not assert that the string ``inspect_file``
appears in the module. They spy on the two composition points and prove the
order and the admission counts:

* ``kagent.document_intake.inspect_file``             (the #2824 gate)
* ``kagent.document_intake.extract_binary_document``  (the Core parser)

A file the gate denies must leave the Core parser call count at 0.
"""

from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Self
from unittest import mock

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pragma: no cover - documents extra provides pypdf
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

from kagent.document_intake import (
    DOCX_SIGNATURE_MISSING_NOTE,
    GATE_REJECTION_NOTE_PREFIX,
    LEGACY_HWP_NOTE,
    ROUTE_MISMATCH_NOTE_PREFIX,
    intake_document,
)
from kagent.draft_flow import DraftFlowError, _read_draft_input
from kagent.review_flow import _collect_review_files

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
UNKNOWN_BYTES = b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c"
OLE_HWP_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32

_S_IFLNK_MODE = 0o120777
_LEAK_MARKER = b"RAWPAYLOADMARKERDO_NOT_LEAK"


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


def _docx_xml(text: str = "Hello Docx Document") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )


def _build_zip(
    members: list[tuple[str, bytes]], *, external_attr: int | None = None
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if external_attr is not None:
                info.external_attr = external_attr
            archive.writestr(info, payload)
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


def _mark_encrypted(payload: bytes) -> bytes:
    """Set the encrypted flag on every central-directory record."""

    data = bytearray(payload)
    position = 0
    while True:
        index = data.find(b"PK\x01\x02", position)
        if index == -1:
            break
        data[index + 8] |= 0x01
        position = index + 4
    return bytes(data)


def _docx_with_bomb() -> bytes:
    """A DOCX whose archive carries a tight expansion bomb."""

    return _build_zip(
        [
            ("word/document.xml", _docx_xml().encode("utf-8")),
            ("bomb.bin", b"\x00" * 500_000),
        ]
    )


def _docx_with_traversal() -> bytes:
    return _build_zip(
        [
            ("word/document.xml", _docx_xml().encode("utf-8")),
            ("../escape.xml", b"<x/>"),
        ]
    )


def _docx_with_symlink() -> bytes:
    return _build_zip(
        [("word/document.xml", _docx_xml().encode("utf-8"))],
        external_attr=(_S_IFLNK_MODE << 16),
    )


def _docx_encrypted() -> bytes:
    return _mark_encrypted(_minimal_docx())


def _docx_corrupt() -> bytes:
    """A DOCX whose end-of-central-directory is destroyed."""

    payload = bytearray(_minimal_docx())
    del payload[-22:]
    return bytes(payload) + b"\x00" * 22


def _hwpx_with_bomb() -> bytes:
    body = "<hp:p><hp:r><hp:t>bomb</hp:t></hp:r></hp:p>"
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
        ' xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        + body
        + "</hs:sec>"
    )
    return _build_zip(
        [
            ("mimetype", b"application/hwp+zip"),
            ("Contents/section0.xml", section.encode("utf-8")),
            ("bomb.bin", b"\x00" * 500_000),
        ]
    )


class _CompositionSpy:
    """Record the call order of the gate and the Core parser.

    Both composition points are patched with wrappers that record their name
    and then delegate to the real implementation, so the product behaviour
    under test is unchanged.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._patches: list = []

    def __enter__(self) -> Self:
        import kagent.document_intake as module

        real_gate = module.inspect_file
        real_parser = module.extract_binary_document

        def gate(name, data, *args, **kwargs):
            self.calls.append("inspect_file")
            return real_gate(name, data, *args, **kwargs)

        def parser(**kwargs):
            self.calls.append("extract_binary_document")
            return real_parser(**kwargs)

        self._patches = [
            mock.patch.object(module, "inspect_file", gate),
            mock.patch.object(module, "extract_binary_document", parser),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc) -> bool:
        for patch in reversed(self._patches):
            patch.stop()
        return False

    def count(self, name: str) -> int:
        return self.calls.count(name)


class OrderAndAdmissionTests(unittest.TestCase):
    """A/B: the gate precedes Core, and a denied file never reaches it."""

    def test_valid_pdf_gate_runs_before_core_parser_once(self) -> None:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the workspace documents extra")
        with _CompositionSpy() as spy:
            result = intake_document("plan.pdf", _minimal_pdf())
        self.assertEqual(
            spy.calls, ["inspect_file", "extract_binary_document"]
        )
        self.assertEqual(spy.count("extract_binary_document"), 1)
        self.assertEqual(result.text, "Hello Padiem Document")
        self.assertIsNone(result.note)

    def test_pdf_named_non_pdf_never_reaches_the_parser(self) -> None:
        """B: content authority — a rename cannot buy parser admission."""

        cases = {
            "png": PNG_BYTES,
            "jpeg": JPEG_BYTES,
            "plain-zip": _build_zip([("a.txt", b"x")]),
            "docx-zip": _minimal_docx(),
            "unknown": UNKNOWN_BYTES,
        }
        for label, payload in cases.items():
            with self.subTest(payload=label):
                with _CompositionSpy() as spy:
                    result = intake_document("report.pdf", payload)
                self.assertEqual(spy.count("extract_binary_document"), 0)
                self.assertEqual(spy.count("inspect_file"), 1)
                self.assertIsNone(result.text)
                self.assertTrue(
                    result.note.startswith(GATE_REJECTION_NOTE_PREFIX), result.note
                )

    def test_valid_hwpx_gate_then_core_extraction(self) -> None:
        """C: a gate-confirmed HWPX_CANDIDATE reaches Core."""

        with _CompositionSpy() as spy:
            result = intake_document("note.hwpx", _minimal_hwpx("견적서", "합계 1,000원"))
        self.assertEqual(
            spy.calls, ["inspect_file", "extract_binary_document"]
        )
        self.assertEqual(result.text, "견적서\n합계 1,000원")
        self.assertIsNone(result.note)

    def test_fake_hwpx_never_reaches_the_parser(self) -> None:
        """D: a plain ZIP renamed .hwpx is rejected by structural preflight."""

        cases = {
            "plain-zip": _build_zip([("a.txt", b"x")]),
            "docx-zip": _minimal_docx(),
            "wrong-mimetype": _build_zip(
                [
                    ("mimetype", b"application/zip"),
                    ("Contents/section0.xml", b"<x/>"),
                ]
            ),
        }
        for label, payload in cases.items():
            with self.subTest(payload=label):
                with _CompositionSpy() as spy:
                    result = intake_document("fake.hwpx", payload)
                self.assertEqual(spy.count("extract_binary_document"), 0)
                self.assertEqual(spy.count("inspect_file"), 1)
                self.assertIsNone(result.text)
                self.assertTrue(
                    result.note.startswith(GATE_REJECTION_NOTE_PREFIX), result.note
                )

    def test_admitted_zip_without_ooxml_signature_never_reaches_the_parser(self) -> None:
        with _CompositionSpy() as spy:
            result = intake_document("report.docx", _build_zip([("a.txt", b"x")]))
        self.assertEqual(spy.count("extract_binary_document"), 0)
        self.assertEqual(result.note, DOCX_SIGNATURE_MISSING_NOTE)

    def test_docx_named_hwpx_content_is_a_content_mismatch(self) -> None:
        with _CompositionSpy() as spy:
            result = intake_document("report.docx", _minimal_hwpx("견적서"))
        self.assertEqual(spy.count("extract_binary_document"), 0)
        self.assertTrue(
            result.note.startswith(ROUTE_MISMATCH_NOTE_PREFIX), result.note
        )

    def test_valid_docx_passes_gate_then_core(self) -> None:
        with _CompositionSpy() as spy:
            result = intake_document("plan.docx", _minimal_docx())
        self.assertEqual(
            spy.calls, ["inspect_file", "extract_binary_document"]
        )
        self.assertEqual(result.text, "Hello Docx Document")


class ArchivePolicyBeforeParserTests(unittest.TestCase):
    """E/F/G: archive policy denials stop the file before the parser."""

    def _assert_denied(self, name: str, payload: bytes, code: str) -> None:
        with _CompositionSpy() as spy:
            result = intake_document(name, payload)
        self.assertEqual(spy.count("extract_binary_document"), 0, code)
        self.assertEqual(spy.count("inspect_file"), 1)
        self.assertIsNone(result.text)
        self.assertIn(code, result.note)

    def test_zip_bomb_is_denied_before_parser(self) -> None:
        self._assert_denied("bomb.docx", _docx_with_bomb(), "archive_expansion_ratio")
        self._assert_denied("bomb.hwpx", _hwpx_with_bomb(), "archive_expansion_ratio")

    def test_traversal_entry_is_denied_before_parser(self) -> None:
        self._assert_denied(
            "trav.docx", _docx_with_traversal(), "archive_unsafe_path"
        )

    def test_symlink_entry_is_denied_before_parser(self) -> None:
        self._assert_denied("link.docx", _docx_with_symlink(), "archive_link_entry")

    def test_corrupt_archive_is_denied_before_parser(self) -> None:
        self._assert_denied("bad.docx", _docx_corrupt(), "archive_malformed")

    def test_encrypted_archive_is_denied_before_parser(self) -> None:
        self._assert_denied("locked.docx", _docx_encrypted(), "archive_encrypted")


class LegacyAndTextFallbackTests(unittest.TestCase):
    """H/I: legacy HWP posture and the ordinary text path are unchanged."""

    def test_legacy_hwp_gate_executed_then_unsupported_posture(self) -> None:
        with _CompositionSpy() as spy:
            result = intake_document("note.hwp", OLE_HWP_BYTES)
        self.assertEqual(spy.count("inspect_file"), 1)
        self.assertEqual(spy.count("extract_binary_document"), 0)
        self.assertIsNone(result.text)
        self.assertEqual(result.note, LEGACY_HWP_NOTE)

    def test_text_and_image_inputs_keep_the_caller_text_path(self) -> None:
        for name, payload in (
            ("README.md", b"# hi\n"),
            ("notes.txt", b"plain text\n"),
            ("photo.png", PNG_BYTES),
            ("no-extension", b"raw\n"),
        ):
            with self.subTest(name=name):
                with _CompositionSpy() as spy:
                    result = intake_document(name, payload)
                self.assertIsNone(result)
                self.assertEqual(spy.count("extract_binary_document"), 0)


class FlowCompositionTests(unittest.TestCase):
    """J/K: the review and draft flows really go through the common gate."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, payload: bytes) -> Path:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_review_flow_binary_route_goes_through_common_gate(self) -> None:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the workspace documents extra")
        self._write("docs/plan.pdf", _minimal_pdf())
        self._write("docs/spoofed.pdf", PNG_BYTES)
        self._write("docs/context.md", "# 컨텍스트\n".encode())
        root = self.repo.resolve()
        files = [root / "docs/plan.pdf", root / "docs/spoofed.pdf", root / "docs/context.md"]

        with _CompositionSpy() as spy:
            reviewed, skipped = _collect_review_files(files, root)

        reviewed_by_name = dict(reviewed)
        skipped_by_name = dict(skipped)
        self.assertEqual(reviewed_by_name["docs/plan.pdf"], "Hello Padiem Document")
        self.assertEqual(reviewed_by_name["docs/context.md"], "# 컨텍스트\n")
        self.assertNotIn("docs/spoofed.pdf", reviewed_by_name)
        self.assertTrue(
            skipped_by_name["docs/spoofed.pdf"].startswith(
                GATE_REJECTION_NOTE_PREFIX
            ),
            skipped_by_name["docs/spoofed.pdf"],
        )
        # The gate ran for every file at the boundary; Core ran only for the
        # document the gate admitted.
        self.assertEqual(spy.count("inspect_file"), 3)
        self.assertEqual(spy.count("extract_binary_document"), 1)

    def test_draft_flow_binary_route_goes_through_common_gate(self) -> None:
        valid = self._write("plan.docx", _minimal_docx("Hello Draft Docx"))
        with _CompositionSpy() as spy:
            text = _read_draft_input(valid)
        self.assertEqual(text, "Hello Draft Docx")
        self.assertEqual(spy.count("inspect_file"), 1)
        self.assertEqual(spy.count("extract_binary_document"), 1)

        spoofed = self._write("spoofed.docx", PNG_BYTES)
        with _CompositionSpy() as spy, self.assertRaises(DraftFlowError) as ctx:
            _read_draft_input(spoofed)
        self.assertEqual(spy.count("extract_binary_document"), 0)
        self.assertEqual(ctx.exception.code, "draft_input_invalid")
        self.assertIn(GATE_REJECTION_NOTE_PREFIX, ctx.exception.safe_message)


class SafeProjectionTests(unittest.TestCase):
    """L: a gate rejection leaks no payload, host path or exception detail."""

    def test_gate_rejection_note_is_bounded_and_leak_free(self) -> None:
        payload = PNG_BYTES + _LEAK_MARKER
        cases = (
            ("/tmp/secret/report.pdf", payload),
            ("/tmp/secret/report.pdf", UNKNOWN_BYTES + _LEAK_MARKER),
            ("/tmp/secret/report.hwpx", _build_zip([("a.txt", _LEAK_MARKER)])),
            ("/tmp/secret/report.docx", _docx_with_bomb()),
            ("/tmp/secret/report.hwp", OLE_HWP_BYTES + _LEAK_MARKER),
        )
        for name, data in cases:
            with self.subTest(name=name, kind=data[:4]):
                result = intake_document(name, data)
                note = result.note or ""
                self.assertNotIn(_LEAK_MARKER.decode(), note)
                self.assertNotIn("/tmp/secret", note)
                self.assertNotIn("Traceback", note)
                self.assertNotIn("Exception", note)
                self.assertNotIn("word/document.xml", note)
                self.assertNotIn("bomb.bin", note)
                self.assertLess(len(note), 120, note)
                self.assertIsNone(result.text)


if __name__ == "__main__":
    unittest.main()
