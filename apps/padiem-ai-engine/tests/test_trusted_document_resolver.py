"""E5B-S2 trusted document resolver tests (#1750).

Covers the frozen S2 acceptance matrix A–M: opaque-reference resolve,
scope enforcement, Core normalization bridge, projection safety and the
zero-mutation canaries for the canonical Core sources.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import re
import zipfile

import pytest

from app.trusted_document_resolver import (
    ATT_REFERENCE_PATTERN,
    DocumentResolutionError,
    InMemoryStoragePort,
    ResolvedDocumentMeta,
    SafeDocumentProjection,
    TrustedDocumentResolver,
    require_document_reference,
    resolve_and_normalize,
)
from padiem_ai_core.document_normalization import NormalizedDocument

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_PACKAGE = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core"
CORE_TESTS = REPO_ROOT / "packages" / "padiem-ai-core" / "tests"

# Canary hashes taken from the exact E5B-S1 merge base (main @ 2afd3264).
PINNED_SHA256 = {
    CORE_PACKAGE / "document_normalization.py": "2f0620895ecec53a895f9496a46965ca1cbe3536b896ce2e8dc0d076d1fe4934",
    CORE_PACKAGE / "document_semantics.py": "b74628623ebaeddd3caab4be317562d204b798e945088e990830c1ee270fa8f5",
    CORE_TESTS / "test_document_semantics.py": "cf21bd3999348d1d34b18fbb9863a6fe8ec93840f6990bdbf52eeb79fce7c8f5",
    CORE_TESTS / "test_document_normalization.py": "5c7e9166fb2ffd015a307da4a7e653acf24c10e44684f3e8df2d70122660b9ff",
}

REF = "att_doc00000000000a"
LOCATOR = "opaque-blob-locator-77"
SECRET_BODY = "quarterly revenue projections for beta-corp"


def _meta(**overrides: object) -> ResolvedDocumentMeta:
    values: dict[str, object] = {
        "media_type": "text/plain",
        "name": "notes.txt",
        "byte_size": len(SECRET_BODY.encode("utf-8")),
        "app_id": "app.revenue",
        "subject_id": "user.42",
        "tenant_id": "tenant.a",
    }
    values.update(overrides)
    return ResolvedDocumentMeta(**values)  # type: ignore[arg-type]


def _resolver(payload: bytes | None = None, meta: ResolvedDocumentMeta | None = None, *, bind: bool = True) -> TrustedDocumentResolver:
    storage = InMemoryStoragePort()
    resolved_meta = meta or _meta()
    raw = payload if payload is not None else SECRET_BODY.encode("utf-8")
    storage.store(LOCATOR, raw, replace(resolved_meta, byte_size=len(raw)))
    resolver = TrustedDocumentResolver(storage=storage)
    if bind:
        resolver.register(REF, LOCATOR)
    return resolver


def _call(**overrides: object) -> dict[str, str]:
    scope: dict[str, str] = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}
    scope.update(overrides)  # type: ignore[arg-type]
    return scope


# --- A: valid resolve -----------------------------------------------------


def test_a_valid_reference_resolves_to_bytes_and_meta() -> None:
    raw, meta = _resolver().resolve(REF, **_call())
    assert raw == SECRET_BODY.encode("utf-8")
    assert meta.media_type == "text/plain"
    assert meta.byte_size == len(raw)


# --- B: invalid reference grammar -----------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    [
        None,
        "",
        "att_short",
        "https://evil.example/x",
        "s3://bucket/private.bin",
        LOCATOR,
        "att_inject me",
        f"att_{'x' * 200}",
        "../att_traversal",
    ],
)
def test_b_invalid_references_are_rejected(bad_ref: object) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        require_document_reference(bad_ref)
    assert info.value.code == "invalid_reference"
    with pytest.raises(DocumentResolutionError):
        _resolver().resolve(bad_ref, **_call())
    assert not any(
        forbidden in str(info.value).lower()
        for forbidden in ("bucket", "evil.example", "payload", "locator")
    )


# --- C: unknown reference --------------------------------------------------


def test_c_unknown_reference_is_not_found_without_leakage() -> None:
    resolver = _resolver(bind=False)
    with pytest.raises(DocumentResolutionError) as info:
        resolver.resolve(REF, **_call())
    assert info.value.code == "not_found"
    assert info.value.status_code == 404
    assert LOCATOR not in str(info.value)
    assert SECRET_BODY not in str(info.value)


def test_c2_missing_payload_is_not_found() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        TrustedDocumentResolver(storage=InMemoryStoragePort()).resolve(REF, **_call())
    assert info.value.code == "not_found"


# --- D: scope enforcement ---------------------------------------------------


@pytest.mark.parametrize(
    "wrong",
    [
        {"app_id": "app.other"},
        {"subject_id": "user.99"},
        {"tenant_id": "tenant.b"},
        {"app_id": "other"},
    ],
)
def test_d_wrong_scope_is_unauthorized(wrong: dict[str, str]) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        _resolver().resolve(REF, **_call(**wrong))
    assert info.value.code == "unauthorized"
    assert info.value.status_code == 403


@pytest.mark.parametrize("wrong", [{"app_id": ""}, {"subject_id": "bad id"}, {"tenant_id": "../x"}])
def test_d2_invalid_caller_scope_is_rejected(wrong: dict[str, str]) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        _resolver().resolve(REF, **_call(**wrong))
    assert info.value.code == "invalid_scope"


def test_d3_integrity_mismatch_is_rejected() -> None:
    storage = InMemoryStoragePort()
    storage.store(LOCATOR, b"short", _meta())
    resolver = TrustedDocumentResolver(storage=storage)
    resolver.register(REF, LOCATOR)
    with pytest.raises(DocumentResolutionError) as info:
        resolver.resolve(REF, **_call())
    assert info.value.code == "integrity_mismatch"


# --- E: resolve + normalize bridge ------------------------------------------


def test_e_text_document_normalizes_through_bridge() -> None:
    document = resolve_and_normalize(_resolver(), REF, **_call())
    assert isinstance(document, NormalizedDocument)
    assert document.text == SECRET_BODY
    assert document.name == "notes.txt"
    assert document.media_type == "text/plain"
    assert document.source_kind == "text"


def test_e2_json_document_normalizes_through_bridge() -> None:
    body = '{"revenue": 260904}'
    document = resolve_and_normalize(
        _resolver(payload=body.encode("utf-8"), meta=_meta(media_type="application/json", name="report.json")),
        REF,
        **_call(),
    )
    assert document.text == body
    assert document.kind is not None


def _docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_e3_docx_document_normalizes_through_bridge() -> None:
    payload = _docx_bytes(SECRET_BODY)
    document = resolve_and_normalize(
        _resolver(payload=payload, meta=_meta(media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", name="deck.docx")),
        REF,
        **_call(),
    )
    assert document.text == SECRET_BODY
    assert document.source_kind == "binary"
    assert document.byte_size == len(payload)


# --- F: NormalizedDocument carries no reference or scope authority -----------


def test_f_normalized_document_leaks_neither_reference_nor_scope() -> None:
    document = resolve_and_normalize(_resolver(), REF, **_call())
    surfaces = [repr(document), str(document), str(document.to_public_dict())]
    combined = " ".join(surfaces).lower()
    assert "att_" not in combined
    assert LOCATOR.lower() not in combined
    assert "app.revenue" not in combined
    assert "user.42" not in combined
    assert "tenant.a" not in combined
    assert SECRET_BODY not in repr(document)


# --- G/H: safe projection never carries body, reference or locator -----------


def test_g_projection_exposes_only_bounded_metadata() -> None:
    document = resolve_and_normalize(_resolver(), REF, **_call())
    projection = SafeDocumentProjection.from_document(document)
    as_dict = projection.to_dict()
    assert as_dict == {
        "kind": "text",
        "name": "notes.txt",
        "media_type": "text/plain",
        "byte_size": len(SECRET_BODY.encode("utf-8")),
        "text_chars": len(SECRET_BODY),
        "segment_count": 1,
        "status": "complete",
        "content_trust_class": "untrusted_reference_data",
    }


def test_h_projection_repr_and_dict_have_no_body_reference_or_locator() -> None:
    document = resolve_and_normalize(_resolver(), REF, **_call())
    projection = SafeDocumentProjection.from_document(document)
    combined = (repr(projection) + str(projection.to_dict())).lower()
    assert SECRET_BODY.lower() not in combined
    assert "att_" not in combined
    assert LOCATOR.lower() not in combined
    assert isinstance(projection.text_chars, int)


# --- I: failures never yield a degraded document ------------------------------


def test_i_unsupported_media_type_raises_without_document() -> None:
    resolver = _resolver(payload=b"\x00\x01binary", meta=_meta(media_type="application/octet-stream", name="blob.bin"))
    with pytest.raises(DocumentResolutionError) as info:
        resolve_and_normalize(resolver, REF, **_call())
    assert info.value.code == "unsupported_media_type"


def test_i2_non_utf8_text_bytes_raise_decode_failed() -> None:
    resolver = _resolver(payload=b"\xff\xfe\x00garbled", meta=_meta())
    with pytest.raises(DocumentResolutionError) as info:
        resolve_and_normalize(resolver, REF, **_call())
    assert info.value.code == "decode_failed"


def test_i3_unauthorized_resolve_produces_no_document() -> None:
    with pytest.raises(DocumentResolutionError):
        resolve_and_normalize(_resolver(), "att_missingmissing", **_call())


# --- J: base import needs no optional extraction dependencies ------------------


def test_j_optional_dependencies_stay_lazy() -> None:
    import app.trusted_document_resolver as module

    module_source = Path(module.__file__).read_text(encoding="utf-8")
    normalization_source = (CORE_PACKAGE / "document_normalization.py").read_text(encoding="utf-8")
    top_level_imports = normalization_source.split("class NormalizedDocument", 1)[0] + module_source
    assert not re.search(r"^import pypdf", top_level_imports, re.MULTILINE)
    assert not re.search(r"^from pypdf", top_level_imports, re.MULTILINE)
    assert not re.search(r"^import openpyxl", top_level_imports, re.MULTILINE)
    assert not re.search(r"^from openpyxl", top_level_imports, re.MULTILINE)
    assert ATT_REFERENCE_PATTERN.pattern.startswith("^att_")


# --- L/M: zero-mutation canaries against the S1 merge base ---------------------


@pytest.mark.parametrize("relative_path, expected", list(PINNED_SHA256.items()))
def test_lm_frozen_sources_are_unmodified(relative_path: Path, expected: str) -> None:
    assert relative_path.exists(), f"expected frozen file to exist: {relative_path}"
    actual = hashlib.sha256(relative_path.read_bytes()).hexdigest()
    assert actual == expected, f"{relative_path.name} drifted from the pinned S1 base revision"
