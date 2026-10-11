"""#2827 bounded structured PDF authoring tests."""

from __future__ import annotations

import hashlib
import json
from importlib import import_module, util
from io import BytesIO
from pathlib import Path

import pytest

if any(
    util.find_spec(name) is None for name in ("PIL", "pdfplumber", "pypdf", "reportlab")
):
    pytest.skip(
        "optional PDF authoring test dependencies are unavailable",
        allow_module_level=True,
    )

document_normalization = import_module("padiem_ai_core.document_normalization")
pdf_authoring = import_module("padiem_ai_core.pdf_authoring")
pdf_table = import_module("padiem_ai_core.pdf_table")
pil_image = import_module("PIL.Image")
pypdf = import_module("pypdf")
DocumentNormalizationError = document_normalization.DocumentNormalizationError
PDF_AUTHORING_FONT_BYTES = pdf_authoring.PDF_AUTHORING_FONT_BYTES
PDF_AUTHORING_FONT_SHA256 = pdf_authoring.PDF_AUTHORING_FONT_SHA256
PdfAuthoringDocument = pdf_authoring.PdfAuthoringDocument
PdfAuthoringFont = pdf_authoring.PdfAuthoringFont
PdfAuthoringMetadata = pdf_authoring.PdfAuthoringMetadata
PdfHeadingBlock = pdf_authoring.PdfHeadingBlock
PdfImageBlock = pdf_authoring.PdfImageBlock
PdfPageBreakBlock = pdf_authoring.PdfPageBreakBlock
PdfTableBlock = pdf_authoring.PdfTableBlock
PdfTextBlock = pdf_authoring.PdfTextBlock
author_structured_pdf = pdf_authoring.author_structured_pdf
extract_pdf_tables = pdf_table.extract_pdf_tables
PdfReader = pypdf.PdfReader

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pdf_authoring"
FONT_PATH = FIXTURE_DIR / "PadiemNotoSansKRAuthoringTest-Regular.ttf"
FONT_LICENSE_PATH = FIXTURE_DIR / "OFL.txt"
FONT_SOURCE_PATH = FIXTURE_DIR / "FONT_SOURCE.json"


def _font() -> PdfAuthoringFont:
    return PdfAuthoringFont(data=FONT_PATH.read_bytes())


def _image(image_format: str) -> bytes:
    output = BytesIO()
    pil_image.new("RGB", (120, 80), "white").save(output, format=image_format)
    return output.getvalue()


def _document(image_format: str = "PNG") -> PdfAuthoringDocument:
    return PdfAuthoringDocument(
        metadata=PdfAuthoringMetadata(
            title="한글 구조화 문서",
            author="Padiem QA",
            subject="bounded authoring probe",
            keywords=("pdf", "korean", "bounded"),
        ),
        font=_font(),
        blocks=(
            PdfHeadingBlock("한글 제목"),
            PdfTextBlock("본문 내용입니다.\n두 번째 줄입니다."),
            PdfTableBlock(
                (
                    ("이름", "수량", "금액"),
                    ("본문", "2", "12,000"),
                )
            ),
            PdfImageBlock("page.png", _image(image_format)),
            PdfPageBreakBlock(),
            PdfHeadingBlock("두 번째 페이지"),
            PdfTextBlock("페이지 내용은 인스펙션됩니다."),
        ),
    )


def _resources(value: object) -> dict[str, object]:
    if hasattr(value, "get_object"):
        value = value.get_object()
    return value if isinstance(value, dict) else {}


def _embedded_font_file_count(page: object) -> int:
    fonts = _resources(_resources(page.get("/Resources")).get("/Font"))
    descriptors: list[dict[str, object]] = []
    for reference in fonts.values():
        font = _resources(reference)
        descriptor = _resources(font.get("/FontDescriptor"))
        if descriptor:
            descriptors.append(descriptor)
        descendants = font.get("/DescendantFonts", [])
        descendants = (
            descendants if isinstance(descendants, (list, tuple)) else [descendants]
        )
        for descendant_reference in descendants:
            descendant = _resources(descendant_reference)
            descriptor = _resources(descendant.get("/FontDescriptor"))
            if descriptor:
                descriptors.append(descriptor)
    return sum(
        int(any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")))
        for descriptor in descriptors
    )


def _image_xobject_count(page: object) -> int:
    xobjects = _resources(_resources(page.get("/Resources")).get("/XObject"))
    return sum(
        1
        for reference in xobjects.values()
        if _resources(reference).get("/Subtype") == "/Image"
    )


def test_font_fixture_is_explicit_and_reproducible() -> None:
    payload = FONT_PATH.read_bytes()
    source = json.loads(FONT_SOURCE_PATH.read_text(encoding="utf-8"))
    license_text = FONT_LICENSE_PATH.read_text(encoding="utf-8")

    assert len(payload) == PDF_AUTHORING_FONT_BYTES == 62_604
    assert hashlib.sha256(payload).hexdigest() == PDF_AUTHORING_FONT_SHA256
    assert source["license"] == "OFL-1.1"
    assert (
        source["source_sha256"]
        == "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252"
    )
    assert source["subset_sha256"] == PDF_AUTHORING_FONT_SHA256
    assert source["runtime_bundle"] is False
    assert "SIL OPEN FONT LICENSE Version 1.1" in license_text
    assert "Reserved Font Name 'Source'" in license_text


def test_authored_pdf_is_deterministic_and_fully_readable() -> None:
    document = _document()
    first = author_structured_pdf(document)
    second = author_structured_pdf(document)

    assert first.data == second.data
    assert first.sha256 == second.sha256
    assert first.page_count == 2
    assert first.size_bytes <= pdf_authoring.MAX_PDF_AUTHORING_OUTPUT_BYTES
    assert first.counts.safe_dict() == {
        "heading": 2,
        "text": 2,
        "table": 1,
        "image": 1,
        "page_break": 1,
    }

    reader = PdfReader(BytesIO(first.data), strict=True)
    assert len(reader.pages) == 2
    assert str(reader.metadata.title) == "한글 구조화 문서"
    assert str(reader.metadata.author) == "Padiem QA"
    assert str(reader.metadata.subject) == "bounded authoring probe"
    assert str(reader.metadata.keywords) == "pdf korean bounded"
    assert str(reader.metadata.creator) == "Padiem bounded PDF authoring"
    assert str(reader.metadata.producer) == "ReportLab"
    assert [(page.extract_text() or "").strip() for page in reader.pages] == [
        "한글 제목\n본문 내용입니다.\n두 번째 줄입니다.\n이름\n수량\n금액\n본문\n2\n12,000",
        "두 번째 페이지\n페이지 내용은 인스펙션됩니다.",
    ]
    assert _image_xobject_count(reader.pages[0]) == 1
    assert _embedded_font_file_count(reader.pages[0]) > 0
    assert _embedded_font_file_count(reader.pages[1]) > 0

    root = reader.trailer["/Root"]
    assert not any(
        key in root
        for key in (
            "/AA",
            "/AcroForm",
            "/EmbeddedFiles",
            "/Names",
            "/OpenAction",
            "/Outlines",
        )
    )
    assert all(not page.get("/Annots") for page in reader.pages)

    table_result = extract_pdf_tables(name="authored.pdf", payload=first.data)
    assert table_result.status == "partial_supported"
    assert table_result.table_count == 1
    assert table_result.unsupported_page_numbers == (2,)
    assert table_result.tables[0].rows[0] == ("이름", "수량", "금액")
    assert table_result.tables[0].rows[1] == ("본문", "2", "12,000")


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
def test_png_and_jpeg_sources_are_normalized_and_embedded(image_format: str) -> None:
    artifact = author_structured_pdf(_document(image_format))
    reader = PdfReader(BytesIO(artifact.data), strict=True)

    assert artifact.page_count == 2
    assert _image_xobject_count(reader.pages[0]) == 1


def test_plain_text_cannot_create_links_scripts_or_annotations() -> None:
    source = _document()
    artifact = author_structured_pdf(
        PdfAuthoringDocument(
            metadata=source.metadata,
            font=source.font,
            blocks=(PdfTextBlock("javascript:https://example.com"),),
        )
    )
    reader = PdfReader(BytesIO(artifact.data), strict=True)
    root = reader.trailer["/Root"]

    assert (reader.pages[0].extract_text() or "").strip() == (
        "javascript:https://example.com"
    )
    assert not any(
        key in root
        for key in (
            "/AA",
            "/AcroForm",
            "/EmbeddedFiles",
            "/JavaScript",
            "/JS",
            "/Names",
            "/OpenAction",
            "/Outlines",
        )
    )
    assert not reader.pages[0].get("/Annots")


def test_public_projection_and_repr_exclude_font_and_pdf_bytes() -> None:
    artifact = author_structured_pdf(_document())
    public = artifact.safe_dict()

    assert public["page_count"] == 2
    assert public["size_bytes"] == artifact.size_bytes
    assert public["font"]["embedded"] is True
    assert public["production_ready"] is False
    assert public["active_content_policy"] == "forbidden"
    assert public["external_uri_fetch_count"] == 0
    assert "data" not in public
    assert str(artifact.data) not in repr(artifact)
    assert str(artifact.data) not in str(public)
    assert str(artifact.font.data) not in repr(artifact)
    assert str(artifact.font.data) not in str(public)


def test_unapproved_or_incomplete_fonts_fail_closed() -> None:
    with pytest.raises(DocumentNormalizationError) as digest_error:
        PdfAuthoringFont(data=b"not-the-approved-font")
    assert digest_error.value.code == "pdf_authoring_font_limit"

    altered = bytearray(FONT_PATH.read_bytes())
    altered[0] ^= 1
    with pytest.raises(DocumentNormalizationError) as altered_error:
        PdfAuthoringFont(data=bytes(altered))
    assert altered_error.value.code == "pdf_authoring_font_unapproved"

    document = _document()
    with pytest.raises(DocumentNormalizationError) as glyph_error:
        author_structured_pdf(
            PdfAuthoringDocument(
                metadata=document.metadata,
                font=document.font,
                blocks=(PdfTextBlock("中文"),),
            )
        )
    assert glyph_error.value.code == "pdf_authoring_font_glyph_missing"


@pytest.mark.parametrize(
    ("document_factory", "code"),
    [
        (lambda: _document().blocks[0], None),
        (
            lambda: (PdfPageBreakBlock(), PdfTextBlock("한글 제목")),
            "pdf_authoring_page_break_invalid",
        ),
        (
            lambda: (PdfTextBlock("한글 제목"), PdfPageBreakBlock()),
            "pdf_authoring_page_break_invalid",
        ),
        (
            lambda: (PdfPageBreakBlock(), PdfPageBreakBlock()),
            "pdf_authoring_page_break_invalid",
        ),
        (
            lambda: (PdfTableBlock((("이름", "수량"), ("본문",))),),
            "pdf_authoring_table_invalid",
        ),
        (
            lambda: (PdfImageBlock("page.png", b"not-an-image"),),
            "pdf_authoring_image_rejected",
        ),
        (
            lambda: (PdfImageBlock("page.webp", _image("WEBP")),),
            "pdf_authoring_image_unsupported",
        ),
    ],
)
def test_invalid_or_unsupported_constructs_fail_closed(
    document_factory: object,
    code: str | None,
) -> None:
    document = _document()
    if code is None:
        with pytest.raises(DocumentNormalizationError):
            author_structured_pdf(document_factory())
        return
    with pytest.raises(DocumentNormalizationError) as error:
        author_structured_pdf(
            PdfAuthoringDocument(
                metadata=document.metadata,
                font=document.font,
                blocks=document_factory(),
            )
        )
    assert error.value.code == code


def test_output_and_page_limits_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf_authoring, "MAX_PDF_AUTHORING_OUTPUT_BYTES", 1024)
    with pytest.raises(DocumentNormalizationError) as output_error:
        author_structured_pdf(_document())
    assert output_error.value.code == "pdf_authoring_output_limit"

    monkeypatch.setattr(
        pdf_authoring, "MAX_PDF_AUTHORING_OUTPUT_BYTES", 2 * 1024 * 1024
    )
    monkeypatch.setattr(pdf_authoring, "MAX_PDF_AUTHORING_PAGES", 1)
    with pytest.raises(DocumentNormalizationError) as page_error:
        author_structured_pdf(_document())
    assert page_error.value.code == "pdf_authoring_page_limit"


def test_authoring_source_has_no_ocr_parser_render_or_network_authority() -> None:
    source = Path(pdf_authoring.__file__).read_text(encoding="utf-8").lower()
    for token in (
        "httpx",
        "pypdf",
        "pdfplumber",
        "pypdfium2",
        "requests",
        "run_ocr",
        "subprocess",
        "urllib",
    ):
        assert token not in source
