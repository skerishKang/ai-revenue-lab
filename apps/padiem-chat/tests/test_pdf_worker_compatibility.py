from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


EXPECTED_TEXT = "Padiem PDF worker compatibility"


def _minimal_text_pdf(text: str) -> bytes:
    """Build a tiny deterministic text PDF entirely in memory.

    The fixture deliberately avoids reportlab/native helpers so the preflight
    exercises only the proposed pypdf dependency and Python in-memory objects.
    """

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
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_ref}
            )
        }
    )

    content = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content.set_data(
        f"BT /F1 14 Tf 36 90 Td ({escaped}) Tj ET".encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(content)

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pypdf_reads_and_extracts_known_text_entirely_in_memory() -> None:
    payload = _minimal_text_pdf(EXPECTED_TEXT)

    reader = PdfReader(BytesIO(payload))

    assert len(reader.pages) == 1
    assert EXPECTED_TEXT in (reader.pages[0].extract_text() or "")


def test_preflight_fixture_does_not_require_filesystem_or_network() -> None:
    payload = _minimal_text_pdf("bounded")
    assert payload.startswith(b"%PDF-")
    assert b"https://" not in payload
    assert b"http://" not in payload
