from __future__ import annotations

import io
import tempfile
from pathlib import Path
import unittest
import zipfile

try:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
except ModuleNotFoundError:  # pypdf is provided by the workspace documents extra.
    PdfWriter = None
    DecodedStreamObject = DictionaryObject = NameObject = None

from kagent.document_intake import HWPX_NOTE, intake_document
from kagent.draft_flow import DraftFlowError, _read_draft_input
from kagent.review_flow import _collect_review_files


def _minimal_pdf(text: str = "Hello Padiem Document") -> bytes | None:
    if PdfWriter is None:
        return None
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


def _minimal_docx(text: str = "Hello Docx Document") -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _corrupt_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<broken")
    return buffer.getvalue()


def _write(repo: Path, name: str, content: bytes | str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8", "newline": ""}
    with open(path, mode, **kwargs) as handle:
        handle.write(content)
    return path


class DocumentIntakeTests(unittest.TestCase):
    def test_pdf_fixture_extracts_text_via_core(self) -> None:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the workspace documents extra")
        result = intake_document("plan.pdf", _minimal_pdf())
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Hello Padiem Document")
        self.assertIsNone(result.note)

    def test_docx_fixture_extracts_text_via_core(self) -> None:
        result = intake_document("plan.docx", _minimal_docx())
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Hello Docx Document")
        self.assertIsNone(result.note)

    def test_corrupt_docx_returns_note_with_reason_code(self) -> None:
        result = intake_document("bad.docx", _corrupt_docx())
        self.assertIsNotNone(result)
        self.assertIsNone(result.text)
        self.assertIn("ooxml_invalid_xml", result.note)

    def test_hwpx_returns_deferred_note(self) -> None:
        result = intake_document("note.hwpx", b"\x00\x01")
        self.assertIsNotNone(result)
        self.assertIsNone(result.text)
        self.assertEqual(result.note, HWPX_NOTE)

    def test_non_document_is_not_routed(self) -> None:
        self.assertIsNone(intake_document("README.md", b"# hi\n"))
        self.assertIsNone(intake_document("fake.pdf", b"plain text, not a PDF"))
        self.assertIsNone(intake_document("fake.docx", b"not a zip archive"))


class ReviewIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_collect_routes_pdf_and_hwpx_and_keeps_utf8(self) -> None:
        if PdfWriter is None:
            self.skipTest("pypdf is provided by the workspace documents extra")
        _write(self.repo, "docs/plan.pdf", _minimal_pdf())
        _write(self.repo, "docs/note.hwpx", b"\x00\x01")
        _write(self.repo, "docs/context.md", "# 컨텍스트\n")
        _write(self.repo, "docs/broken.docx", _corrupt_docx())

        root = self.repo.resolve()
        files = [
            root / "docs/plan.pdf",
            root / "docs/note.hwpx",
            root / "docs/context.md",
            root / "docs/broken.docx",
        ]
        reviewed, skipped = _collect_review_files(files, root)

        reviewed_by_name = dict(reviewed)
        self.assertEqual(reviewed_by_name["docs/plan.pdf"], "Hello Padiem Document")
        self.assertEqual(reviewed_by_name["docs/context.md"], "# 컨텍스트\n")

        skipped_by_name = dict(skipped)
        self.assertEqual(skipped_by_name["docs/note.hwpx"], HWPX_NOTE)
        self.assertIn("ooxml_invalid_xml", skipped_by_name["docs/broken.docx"])


class DraftIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_extracts_docx_text(self) -> None:
        path = _write(self.repo, "plan.docx", _minimal_docx("Hello Draft Docx"))
        self.assertEqual(_read_draft_input(path), "Hello Draft Docx")

    def test_read_hwpx_fails_closed_with_deferred_note(self) -> None:
        path = _write(self.repo, "plan.hwpx", b"\x00\x01")
        with self.assertRaises(DraftFlowError) as ctx:
            _read_draft_input(path)
        self.assertEqual(ctx.exception.code, "draft_input_invalid")
        self.assertIn("HWPX", ctx.exception.safe_message)

    def test_read_corrupt_docx_fails_closed_with_reason_code(self) -> None:
        path = _write(self.repo, "bad.docx", _corrupt_docx())
        with self.assertRaises(DraftFlowError) as ctx:
            _read_draft_input(path)
        self.assertEqual(ctx.exception.code, "draft_input_invalid")
        self.assertIn("ooxml_invalid_xml", ctx.exception.safe_message)


if __name__ == "__main__":
    unittest.main()