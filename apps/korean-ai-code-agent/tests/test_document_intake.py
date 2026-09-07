from __future__ import annotations

import io
import tempfile
from pathlib import Path
import unittest
import zipfile

from kagent.document_intake import HWPX_NOTE, intake_document
from kagent.draft_flow import DraftFlowError, _read_draft_input
from kagent.review_flow import _collect_review_files


def _minimal_pdf(text: str = "Hello Padiem Document") -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = ("BT /F1 12 Tf 72 720 Td (" + text + ") Tj ET").encode("ascii")
    objects[3] = (
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii")
        out += obj
        out += b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


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