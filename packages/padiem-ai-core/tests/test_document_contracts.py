import ast
import dataclasses
import re
from pathlib import Path

import pytest

from padiem_ai_core.document_contracts import (
    DOCUMENT_CONTENT_TRUST_CLASS,
    MAX_DISPLAY_NAME_CHARS,
    MAX_DOCUMENT_SEGMENTS,
    MAX_DOCUMENT_WARNINGS,
    MAX_NORMALIZED_TEXT_CHARS,
    MAX_SEGMENT_TEXT_CHARS,
    DocumentContractError,
    DocumentKind,
    DocumentLocator,
    DocumentSegment,
    ExtractionStatus,
    LocatorKind,
    LocatorPrecision,
    NormalizedDocument,
)

MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "padiem_ai_core" / "document_contracts.py"
)

FORBIDDEN_FIELD_FRAGMENTS = (
    "bytes",
    "base64",
    "path",
    "bucket",
    "secret",
    "token",
    "url",
    "file",
    "mime",
)

FORBIDDEN_IMPORT_ROOTS = (
    "pypdf",
    "openpyxl",
    "zipfile",
    "xml",
    "base64",
    "io",
    "os",
    "pathlib",
    "subprocess",
    "socket",
    "http",
    "requests",
    "httpx",
)


def locator(
    kind: LocatorKind = LocatorKind.PARAGRAPH,
    value: str = "p12",
    precision: LocatorPrecision = LocatorPrecision.EXACT,
) -> DocumentLocator:
    return DocumentLocator(kind=kind, value=value, precision=precision)


def segment(text: str = "Normalized body text.", order: int = 0) -> DocumentSegment:
    return DocumentSegment(text=text, order=order, locator=locator())


def document(
    *,
    kind: DocumentKind = DocumentKind.TEXT,
    status: ExtractionStatus = ExtractionStatus.COMPLETE,
    segments: tuple[DocumentSegment, ...] | None = None,
    warnings: tuple[str, ...] = (),
    display_name: str = "Quarterly report",
    document_id: str = "doc_1",
) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=document_id,
        kind=kind,
        display_name=display_name,
        segments=segments if segments is not None else (segment(),),
        status=status,
        warnings=warnings,
    )


# Group A: valid construction for every supported kind
@pytest.mark.parametrize("kind", list(DocumentKind))
def test_valid_construction_for_every_kind(kind: DocumentKind) -> None:
    doc = document(kind=kind)
    assert doc.kind is kind
    assert doc.status is ExtractionStatus.COMPLETE
    assert doc.text_chars == sum(s.char_count for s in doc.segments)
    assert doc.segment_count == 1
    assert doc.truncated is False
    public = doc.to_public_dict()
    assert public["kind"] == kind.value
    assert public["content_trust_class"] == DOCUMENT_CONTENT_TRUST_CLASS


def test_hwp_and_hwpx_kinds_do_not_exist() -> None:
    values = {kind.value for kind in DocumentKind}
    assert "hwp" not in values
    assert "hwpx" not in values
    assert values == {"text", "markdown", "csv", "json", "pdf", "docx", "pptx", "xlsx"}


# Group B: immutability
def test_all_contracts_are_frozen() -> None:
    doc = document()
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.display_name = "mutated"  # type: ignore[misc]
    seg = segment()
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.order = 5  # type: ignore[misc]
    loc = locator()
    with pytest.raises(dataclasses.FrozenInstanceError):
        loc.value = "x"  # type: ignore[misc]


# Group C: identifier validation
@pytest.mark.parametrize(
    "bad_id",
    ["", " ", "doc 1", "-doc", "doc/../etc", "C:\\temp\\doc", "x" * 129, "att!bad"],
)
def test_document_id_must_be_safe_identifier(bad_id: str) -> None:
    with pytest.raises(DocumentContractError) as exc:
        document(document_id=bad_id)
    assert exc.value.code == "invalid_document_contract"


def test_e5a_style_attachment_ref_is_a_valid_identifier() -> None:
    ref = "att_" + "A" * 40
    doc = document(document_id=ref)
    assert doc.document_id == ref


@pytest.mark.parametrize("bad_value", ["", "page 1", "a/b", "x" * 129])
def test_locator_value_must_be_safe_identifier(bad_value: str) -> None:
    with pytest.raises(DocumentContractError):
        locator(value=bad_value)


# Group D: display name is sanitized metadata only
def test_display_name_sanitizes_control_characters_and_whitespace() -> None:
    doc = document(display_name="  Quarterly\x00\x07 report\n\n final   ")
    assert doc.display_name == "Quarterly report final"


def test_display_name_rejects_blank_and_oversized() -> None:
    with pytest.raises(DocumentContractError):
        document(display_name="   ")
    with pytest.raises(DocumentContractError) as exc:
        document(display_name="x" * (MAX_DISPLAY_NAME_CHARS + 1))
    assert exc.value.code == "document_budget_exceeded"


def test_display_name_never_authority() -> None:
    with pytest.raises(DocumentContractError) as exc:
        NormalizedDocument(
            document_id="doc_1",
            kind=DocumentKind.TEXT,
            display_name="safe",
            segments=(segment(),),
            status=ExtractionStatus.COMPLETE,
            display_name_is_authority=True,
        )
    assert exc.value.code == "invalid_document_contract"
    assert document().display_name_is_authority is False


# Group E: structural bounds
def test_segment_text_is_bounded() -> None:
    with pytest.raises(DocumentContractError) as exc:
        segment(text="x" * (MAX_SEGMENT_TEXT_CHARS + 1))
    assert exc.value.code == "document_budget_exceeded"
    with pytest.raises(DocumentContractError):
        segment(text="   ")


def test_total_text_and_segment_count_are_bounded() -> None:
    big = segment(text="x" * MAX_SEGMENT_TEXT_CHARS)
    docs_segments = []
    total = 0
    order = 0
    while total + big.char_count <= MAX_NORMALIZED_TEXT_CHARS:
        docs_segments.append(DocumentSegment(text="x" * MAX_SEGMENT_TEXT_CHARS, order=order))
        total += MAX_SEGMENT_TEXT_CHARS
        order += 1
    docs_segments.append(DocumentSegment(text="y" * (MAX_NORMALIZED_TEXT_CHARS - total + 1), order=order))
    with pytest.raises(DocumentContractError) as exc:
        document(segments=tuple(docs_segments))
    assert exc.value.code == "document_budget_exceeded"

    many = tuple(
        DocumentSegment(text="ok", order=index) for index in range(MAX_DOCUMENT_SEGMENTS + 1)
    )
    with pytest.raises(DocumentContractError) as exc:
        document(segments=many)
    assert exc.value.code == "document_budget_exceeded"


# Group F: segment rules
def test_segment_order_must_be_unique_non_negative_int() -> None:
    with pytest.raises(DocumentContractError):
        segment(order=-1)
    with pytest.raises(DocumentContractError):
        segment(order="0")
    with pytest.raises(DocumentContractError):
        segment(order=True)
    with pytest.raises(DocumentContractError) as exc:
        document(segments=(segment(order=0), segment(order=0)))
    assert exc.value.code == "invalid_document_contract"


def test_segments_must_be_document_segments_and_non_empty() -> None:
    with pytest.raises(DocumentContractError):
        document(segments=("plain text",))
    with pytest.raises(DocumentContractError):
        document(segments=())


def test_segment_locator_type_checked() -> None:
    with pytest.raises(DocumentContractError):
        DocumentSegment(text="ok", order=0, locator="page:1")


# Group G: locator rules
def test_locator_requires_enum_kind_and_precision() -> None:
    with pytest.raises(DocumentContractError):
        DocumentLocator(kind="page", value="p1", precision=LocatorPrecision.EXACT)
    with pytest.raises(DocumentContractError):
        DocumentLocator(kind=LocatorKind.PAGE, value="p1", precision="exact")
    loc = DocumentLocator(
        kind=LocatorKind.SHEET,
        value="Sheet2",
        precision=LocatorPrecision.APPROXIMATE,
    )
    assert loc.to_public_dict() == {
        "kind": "sheet",
        "value": "Sheet2",
        "precision": "approximate",
    }


# Group H: warnings are bounded safe identifiers
@pytest.mark.parametrize(
    "bad_warning",
    ["", "Truncated-At-Page", "page truncated", "x" * 65, "att_" + "A" * 80],
)
def test_warning_identifiers_validated(bad_warning: str) -> None:
    with pytest.raises(DocumentContractError):
        document(warnings=(bad_warning,))


def test_warnings_reject_duplicates_and_overload() -> None:
    with pytest.raises(DocumentContractError):
        document(warnings=("lossy_heading", "lossy_heading"))
    with pytest.raises(DocumentContractError) as exc:
        document(warnings=tuple(f"warn_{index}" for index in range(MAX_DOCUMENT_WARNINGS + 1)))
    assert exc.value.code == "document_budget_exceeded"


def test_truncated_status_requires_warning() -> None:
    with pytest.raises(DocumentContractError) as exc:
        document(status=ExtractionStatus.TRUNCATED)
    assert exc.value.code == "truncation_requires_warning"
    doc = document(status=ExtractionStatus.TRUNCATED, warnings=("text_truncated",))
    assert doc.truncated is True


# Group I: rejected extraction cannot masquerade as usable
def test_rejected_status_cannot_construct_document() -> None:
    with pytest.raises(DocumentContractError) as exc:
        document(status=ExtractionStatus.REJECTED)
    assert exc.value.code == "rejected_document_not_normalizable"


def test_trust_class_cannot_be_widened() -> None:
    with pytest.raises(DocumentContractError):
        NormalizedDocument(
            document_id="doc_1",
            kind=DocumentKind.TEXT,
            display_name="safe",
            segments=(segment(),),
            status=ExtractionStatus.COMPLETE,
            content_trust_class="trusted_instruction_data",
        )


def test_error_messages_never_echo_content() -> None:
    secret = "TOP_SECRET_BODY_CONTENT"
    with pytest.raises(DocumentContractError) as exc:
        document(display_name=secret + "x" * MAX_DISPLAY_NAME_CHARS)
    assert secret not in str(exc.value)


# Group J: machine scan — no transport/storage/bytes authority fields
def test_no_forbidden_field_names_anywhere() -> None:
    for cls in (DocumentLocator, DocumentSegment, NormalizedDocument):
        for field in dataclasses.fields(cls):
            lowered = field.name.lower()
            for fragment in FORBIDDEN_FIELD_FRAGMENTS:
                assert fragment not in lowered, f"{cls.__name__}.{field.name}"
    assert DOCUMENT_CONTENT_TRUST_CLASS == "untrusted_reference_data"


# Group K: no parser / transport / storage imports in the contract module
def test_module_only_imports_pure_stdlib_contract_tools() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots <= {"dataclasses", "enum", "re", "__future__"}
    for root in FORBIDDEN_IMPORT_ROOTS:
        assert root not in imported_roots


def test_no_engine_attachment_grammar_imported() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "attachment_authority" not in source
    assert "require_opaque_attachment_ref" not in source
    assert not re.search(r"att_\[", source)


# Package export convention
def test_public_types_are_exported_from_package() -> None:
    import padiem_ai_core

    for name in (
        "DocumentKind",
        "DocumentLocator",
        "DocumentSegment",
        "NormalizedDocument",
        "ExtractionStatus",
        "LocatorKind",
        "LocatorPrecision",
        "DocumentContractError",
    ):
        assert name in padiem_ai_core.__all__
        assert getattr(padiem_ai_core, name) is not None
