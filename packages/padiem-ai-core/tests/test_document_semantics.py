from __future__ import annotations

import ast
import dataclasses
import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import padiem_ai_core
from padiem_ai_core.document_normalization import (
    MAX_DOCUMENT_CHARS,
    DocumentNormalizationError,
    NormalizedDocument,
    extract_binary_document,
    normalize_text_document,
)
from padiem_ai_core.document_semantics import (
    DOCUMENT_CONTENT_TRUST_CLASS,
    MAX_DOCUMENT_SEGMENTS,
    MAX_DOCUMENT_WARNINGS,
    MAX_SEGMENT_TEXT_CHARS,
    DocumentKind,
    DocumentLocator,
    DocumentSegment,
    ExtractionStatus,
    LocatorKind,
    LocatorPrecision,
    document_kind_for_media,
)

CORE_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "padiem_ai_core"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

MARKER = "PRIVATEDOCUMENTBODYMARKER"

FORBIDDEN_FIELD_FRAGMENTS = (
    "attachment",
    "resolver",
    "token",
    "secret",
    "credential",
    "bucket",
    "storage",
    "path",
    "url",
    "location",
    "base64",
    "document_id",
    "source_ref",
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return output.getvalue()


def _docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    ).encode()
    return _zip_bytes({"word/document.xml": document_xml})


def text_document(text: str = "first line\nsecond line") -> NormalizedDocument:
    return normalize_text_document(name="notes.txt", media_type="text/plain", text=text)


# A. exactly one canonical NormalizedDocument type in Core
def test_single_canonical_normalized_document_type() -> None:
    defining_files = []
    for module_path in sorted(CORE_PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "NormalizedDocument":
                defining_files.append(module_path.name)
    assert defining_files == ["document_normalization.py"]


def test_superseded_contracts_module_is_gone() -> None:
    assert not (CORE_PACKAGE_DIR / "document_contracts.py").exists()
    with pytest.raises(ModuleNotFoundError):
        __import__("padiem_ai_core.document_contracts")


# B/C. #1894 canonical behavior and attributes preserved
def test_canonical_attributes_and_public_shape_preserved() -> None:
    document = text_document("\ufefffirst\r\nsecond\rthird")
    assert document.name == "notes.txt"
    assert document.media_type == "text/plain"
    assert document.text == "first\nsecond\nthird"
    assert document.byte_size == len(document.text.encode("utf-8"))
    assert document.source_kind == "text"
    assert document.to_public_dict() == {
        "type": "document",
        "name": "notes.txt",
        "media_type": "text/plain",
        "byte_size": document.byte_size,
        "text_chars": len(document.text),
    }


def test_binary_docx_path_preserved_through_canonical_object() -> None:
    document = extract_binary_document(
        name="report.docx",
        media_type=DOCX_MIME,
        payload=_docx_bytes("alpha paragraph", "beta paragraph"),
    )
    assert document.text == "alpha paragraph\nbeta paragraph"
    assert document.source_kind == "binary"
    assert document.byte_size > 0


# D. document kind
@pytest.mark.parametrize(
    ("media_type", "expected"),
    [
        ("text/plain", DocumentKind.TEXT),
        ("text/markdown", DocumentKind.MARKDOWN),
        ("text/csv", DocumentKind.CSV),
        ("application/json", DocumentKind.JSON),
        ("application/pdf", DocumentKind.PDF),
        (DOCX_MIME, DocumentKind.DOCX),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            DocumentKind.PPTX,
        ),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            DocumentKind.XLSX,
        ),
    ],
)
def test_kind_mapping_covers_all_supported_media(media_type: str, expected: DocumentKind) -> None:
    assert document_kind_for_media(media_type) is expected


def test_kind_property_on_canonical_documents() -> None:
    assert text_document().kind is DocumentKind.TEXT
    docx = extract_binary_document(
        name="deck.docx", media_type=DOCX_MIME, payload=_docx_bytes("body text")
    )
    assert docx.kind is DocumentKind.DOCX


def test_no_hwp_or_hwpx_kind() -> None:
    assert {kind.value for kind in DocumentKind} == {
        "text",
        "markdown",
        "csv",
        "json",
        "pdf",
        "docx",
        "pptx",
        "xlsx",
    }


# E. content trust fixed by Core
def test_content_trust_class_is_fixed_core_metadata() -> None:
    document = text_document()
    assert document.content_trust_class == DOCUMENT_CONTENT_TRUST_CLASS
    assert DOCUMENT_CONTENT_TRUST_CLASS == "untrusted_reference_data"
    assert "content_trust_class" not in {f.name for f in dataclasses.fields(NormalizedDocument)}
    with pytest.raises(TypeError):
        NormalizedDocument(
            name="a.txt",
            media_type="text/plain",
            text="body",
            content_trust_class="system_instruction_data",
        )
    frozen_error = None
    try:
        document.content_trust_class = "trusted"  # type: ignore[misc]
    except (TypeError, dataclasses.FrozenInstanceError) as exc:
        frozen_error = exc
    assert frozen_error is not None


# F/G. repr safety
def test_repr_never_exposes_document_or_segment_body() -> None:
    document = text_document(f"{MARKER} hidden body")
    assert MARKER not in repr(document)
    assert MARKER not in str(document.segments)
    segment = DocumentSegment(text=f"{MARKER} segment body", order=3)
    assert MARKER not in repr(segment)
    assert "order=3" in repr(segment)
    assert "char_count" in repr(segment)
    assert MARKER not in repr(
        NormalizedDocument(
            name="x.txt",
            media_type="text/plain",
            text="body",
            segments=(segment,),
        )
    )


# I/J. no resolver token / storage / credential surface
def test_no_forbidden_field_names_on_document_types() -> None:
    for cls in (NormalizedDocument, DocumentSegment, DocumentLocator):
        for data_field in dataclasses.fields(cls):
            lowered = data_field.name.lower()
            for fragment in FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, f"{cls.__name__}.{data_field.name}"


def test_canonical_document_has_no_equatable_identity_field() -> None:
    document = text_document()
    assert not hasattr(document, "document_id")
    assert not hasattr(document, "attachment_ref")
    att_style = f"att_{'A' * 40}"
    assert att_style not in repr(document)
    assert att_style not in json.dumps(document.to_public_dict())


# K/H. bounded segments + public projection safety
def test_public_projection_excludes_body_and_segments() -> None:
    document = text_document(f"{MARKER} secret content")
    public = document.to_public_dict()
    assert "text" not in public
    assert MARKER not in json.dumps(public)
    assert document.segment_count == 1
    assert document.text_chars == len(document.text)


def test_segment_bounds_are_enforced() -> None:
    with pytest.raises(DocumentNormalizationError) as too_long:
        DocumentSegment(text="x" * (MAX_SEGMENT_TEXT_CHARS + 1))
    assert too_long.value.code == "segment_text_limit"

    with pytest.raises(DocumentNormalizationError) as over_budget:
        NormalizedDocument(
            name="big.txt",
            media_type="text/plain",
            text="small",
            segments=(
                DocumentSegment(text="a" * 20_000, order=0),
                DocumentSegment(text="b" * 20_001, order=1),
            ),
        )
    assert over_budget.value.code == "document_segment_budget"

    many = tuple(DocumentSegment(text="ok", order=index) for index in range(MAX_DOCUMENT_SEGMENTS + 1))
    with pytest.raises(DocumentNormalizationError) as over_count:
        NormalizedDocument(name="many.txt", media_type="text/plain", text="body", segments=many)
    assert over_count.value.code == "document_segment_limit"

    with pytest.raises(DocumentNormalizationError):
        DocumentSegment(text="")
    with pytest.raises(DocumentNormalizationError) as dup:
        NormalizedDocument(
            name="d.txt",
            media_type="text/plain",
            text="body",
            segments=(DocumentSegment(text="one", order=0), DocumentSegment(text="two", order=0)),
        )
    assert dup.value.code == "duplicate_segment_order"


def test_document_derives_single_honest_segment() -> None:
    document = text_document(f"line one\n{MARKER}")
    assert document.segment_count == 1
    only = document.segments[0]
    assert only.text == document.text
    assert only.order == 0


# L. optional locators
def test_locator_is_validated_but_never_required() -> None:
    located = DocumentSegment(
        text="cell output",
        order=0,
        locator=DocumentLocator(kind=LocatorKind.CELL, value="Summary.B2", precision=LocatorPrecision.EXACT),
    )
    assert located.locator is not None
    assert located.to_public_dict()["char_count"] == len("cell output")
    assert MARKER not in json.dumps(located.to_public_dict())


@pytest.mark.parametrize("bad_value", ["", "page 1", "a/b", "..\\x", "x" * 129])
def test_locator_values_reject_unsafe_identifiers(bad_value: str) -> None:
    with pytest.raises(DocumentNormalizationError) as exc:
        DocumentLocator(kind=LocatorKind.PAGE, value=bad_value, precision=LocatorPrecision.EXACT)
    assert exc.value.code == "invalid_locator_value"


def test_locator_enums_are_required() -> None:
    with pytest.raises(DocumentNormalizationError):
        DocumentLocator(kind="page", value="12", precision=LocatorPrecision.EXACT)
    with pytest.raises(DocumentNormalizationError):
        DocumentLocator(kind=LocatorKind.PAGE, value="12", precision="exact")


def test_segment_enforces_types_and_order() -> None:
    with pytest.raises(DocumentNormalizationError):
        DocumentSegment(text="t", order=False)
    with pytest.raises(DocumentNormalizationError):
        DocumentSegment(text="t", order=-1)
    with pytest.raises(DocumentNormalizationError):
        DocumentSegment(text="t", order=0, locator="page:1")


# M. no false precision
def test_current_parsers_never_fabricate_locators() -> None:
    text_doc = text_document()
    assert all(segment.locator is None for segment in text_doc.segments)
    docx = extract_binary_document(
        name="report.docx", media_type=DOCX_MIME, payload=_docx_bytes("honest body")
    )
    assert all(segment.locator is None for segment in docx.segments)


# N. failure is an exception; rejected state is unconstructible
def test_extraction_failures_raise_and_never_yield_documents() -> None:
    with pytest.raises(DocumentNormalizationError):
        normalize_text_document(name="legacy.hwp", media_type="application/x-hwp", text="anything")
    with pytest.raises(DocumentNormalizationError):
        normalize_text_document(name="x.txt", media_type="text/plain", text="")
    with pytest.raises(DocumentNormalizationError):
        extract_binary_document(name="x.docx", media_type=DOCX_MIME, payload=b"not-a-zip")
    assert {status.value for status in ExtractionStatus} == {"complete", "truncated"}
    assert not hasattr(ExtractionStatus, "REJECTED")


def test_status_and_warning_invariants() -> None:
    with pytest.raises(DocumentNormalizationError) as bad_status:
        NormalizedDocument(name="a.txt", media_type="text/plain", text="body", status="complete")
    assert bad_status.value.code == "invalid_document_status"

    with pytest.raises(DocumentNormalizationError) as silent_truncation:
        NormalizedDocument(
            name="a.txt",
            media_type="text/plain",
            text="body",
            status=ExtractionStatus.TRUNCATED,
        )
    assert silent_truncation.value.code == "truncation_requires_warning"

    truncated = NormalizedDocument(
        name="a.txt",
        media_type="text/plain",
        text="body",
        status=ExtractionStatus.TRUNCATED,
        warnings=("text_truncated",),
    )
    assert truncated.truncated is True
    assert truncated.status is ExtractionStatus.TRUNCATED
    assert text_document().truncated is False


def test_warnings_are_bounded_machine_tokens() -> None:
    with pytest.raises(DocumentNormalizationError):
        NormalizedDocument(
            name="a.txt",
            media_type="text/plain",
            text="body",
            warnings=(f"parsed exception {MARKER}",),
        )
    with pytest.raises(DocumentNormalizationError):
        NormalizedDocument(
            name="a.txt",
            media_type="text/plain",
            text="body",
            warnings=("dup", "dup"),
        )
    with pytest.raises(DocumentNormalizationError) as overload:
        NormalizedDocument(
            name="a.txt",
            media_type="text/plain",
            text="body",
            warnings=tuple(f"warn_{index}" for index in range(MAX_DOCUMENT_WARNINGS + 1)),
        )
    assert overload.value.code == "document_warnings_limit"


def test_canonical_type_is_frozen() -> None:
    document = text_document()
    with pytest.raises(dataclasses.FrozenInstanceError):
        document.name = "mutated.txt"  # type: ignore[misc]


# O/P. dependency boundary preserved
def test_core_base_and_semantic_imports_require_no_document_extras() -> None:
    probe = (
        "import sys\n"
        "import padiem_ai_core\n"
        "import padiem_ai_core.document_semantics\n"
        "import padiem_ai_core.document_normalization as dn\n"
        "assert dn.__file__ == " + repr(str(CORE_PACKAGE_DIR / "document_normalization.py")) + "\n"
        "assert 'pypdf' not in sys.modules\n"
        "assert 'openpyxl' not in sys.modules\n"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(CORE_PACKAGE_DIR.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_stdlib_document_paths_work_without_pdf_or_xlsx_extras() -> None:
    document = extract_binary_document(
        name="slide.docx", media_type=DOCX_MIME, payload=_docx_bytes("stdlib extraction")
    )
    assert document.text == "stdlib extraction"
    core_project = (CORE_PACKAGE_DIR.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "documents = [" in core_project
    assert '"pypdf' in core_project
    assert '"openpyxl' in core_project


def test_package_root_exports_semantics_only() -> None:
    for name in (
        "DocumentKind",
        "DocumentLocator",
        "DocumentSegment",
        "ExtractionStatus",
        "LocatorKind",
        "LocatorPrecision",
        "DocumentNormalizationError",
    ):
        assert name in padiem_ai_core.__all__
    root_vars = vars(padiem_ai_core)
    assert "NormalizedDocument" not in padiem_ai_core.__all__
    assert "NormalizedDocument" not in root_vars


def test_core_document_modules_carry_no_engine_grammar() -> None:
    for module_name in ("document_semantics.py", "document_normalization.py"):
        source = (CORE_PACKAGE_DIR / module_name).read_text(encoding="utf-8")
        assert "attachment_authority" not in source
        assert "require_opaque_attachment_ref" not in source
        assert 'r"^att_' not in source
        assert "att_[" not in source
