"""Document reference grammar + error vocabulary authority tests (#2741).

Covers: the canonical ``doc_*`` pattern (grammar class identical to the image
attachment namespace, prefix deliberately different), cross-namespace
collision refusal in both directions, the frozen safe error-code vocabulary,
the server-owned binding alias and the source-only (never composed, never
provisioning) boundary.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.attachment_authority import (  # noqa: E402
    EngineAttachmentAuthorityError,
    require_opaque_attachment_ref,
)
from app.attachment_authority import _ATTACHMENT_REF_RE  # noqa: E402
from app.document_reference import (  # noqa: E402
    DOC_REFERENCE_PATTERN,
    DOCUMENT_STORE_BINDING_NAME,
    RESOLUTION_ERROR_CODES,
    DocumentResolutionError,
    require_document_reference,
)

BODY_MIN = "a" * 16
BODY_MAX = "Z9_-_" + "k" * 115  # 120 chars, mixed legal class


def _ref(body: str) -> str:
    return f"doc_{body}"


# --- grammar ----------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        _ref(BODY_MIN),
        _ref(BODY_MAX),
        _ref("0123456789abcdef"),
        _ref("F1xture-Ref_000123"),
        _ref("opaque-blob-locator-77"),
        "doc_" + "-" * 16,
        "doc_" + "_" * 16,
    ],
)
def test_valid_document_references_are_accepted(reference: str) -> None:
    assert require_document_reference(reference) == reference


@pytest.mark.parametrize(
    "bad",
    [
        None,
        17,
        b"doc_" + BODY_MIN.encode("ascii"),
        "",
        "   ",
        "docx_" + BODY_MIN,
        "doc" + BODY_MIN,
        "DOC_" + BODY_MIN,
        "Doc_" + BODY_MIN,
        _ref("a" * 15),  # too short
        _ref("a" * 121),  # too long
        _ref("has spaces"),
        _ref("has/slash"),
        _ref("has.dot"),
        _ref("has:colon"),
        _ref("has+plus"),
        _ref("has=equals"),
        "../doc_traversal",
        "s3://bucket/doc_" + BODY_MIN,
        "https://storage.internal/doc_" + BODY_MIN,
        "\n" + _ref(BODY_MIN),
        _ref(BODY_MIN) + "\x00",
    ],
)
def test_malformed_or_non_string_references_are_rejected(bad: object) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        require_document_reference(bad)
    assert info.value.code == "invalid_reference"
    assert info.value.status_code == 400


def test_pattern_is_the_single_grammar_owner() -> None:
    assert DOC_REFERENCE_PATTERN.pattern == r"^doc_[A-Za-z0-9_-]{16,120}$"


# --- cross-namespace collision refusal ---------------------------------------


@pytest.mark.parametrize(
    "att_ref",
    ["att_doc000000000000a", "att_s4bdoc000000000c", "att_e5bRoutefixture01"],
)
def test_wellformed_image_references_never_pass_document_grammar(att_ref: object) -> None:
    # historical image fixtures are valid in their own namespace...
    require_opaque_attachment_ref(att_ref)
    # ...and must fail closed against the document store boundary.
    with pytest.raises(DocumentResolutionError) as info:
        require_document_reference(att_ref)
    assert info.value.code == "invalid_reference"


def test_wellformed_document_references_never_pass_image_grammar() -> None:
    for reference in (_ref(BODY_MIN), _ref("F1xture-Ref_000123")):
        with pytest.raises(EngineAttachmentAuthorityError) as info:
            require_opaque_attachment_ref(reference)
        assert info.value.code == "invalid_attachment_reference"


def test_image_grammar_still_accepts_its_own_namespace_unchanged() -> None:
    # The #2741 doc lane must not have touched the att_* lane: a historically
    # valid fixture still resolves through the attachment authority.
    assert require_opaque_attachment_ref("att_F1xture-Ref_000123") == "att_F1xture-Ref_000123"


def test_namespaces_share_shape_class_but_never_prefix() -> None:
    doc_pattern = DOC_REFERENCE_PATTERN.pattern
    att_pattern = _ATTACHMENT_REF_RE.pattern
    assert doc_pattern.startswith("^doc_")
    assert att_pattern.startswith("^att_")
    assert doc_pattern[5:] == att_pattern[5:]


# --- error vocabulary ---------------------------------------------------------


def test_resolution_error_codes_are_the_exact_frozen_vocabulary() -> None:
    assert set(RESOLUTION_ERROR_CODES) == {
        "invalid_reference",
        "invalid_scope",
        "unauthorized",
        "not_found",
        "integrity_mismatch",
        "decode_failed",
        "unsupported_media_type",
        "expired",
        "terminal",
        "store_unavailable",
    }


@pytest.mark.parametrize("code", sorted(RESOLUTION_ERROR_CODES))
def test_known_codes_round_trip_status_and_message(code: str) -> None:
    error = DocumentResolutionError(code, f"safe {code} message", status_code=410)
    assert error.code == code
    assert str(error) == f"safe {code} message"
    assert error.safe_message == f"safe {code} message"
    assert error.status_code == 410
    assert isinstance(error, ValueError)


@pytest.mark.parametrize(
    "code", ["", "random", "internal_leak", "caller_scope_invalid", None, 5]
)
def test_unknown_or_non_string_codes_cannot_be_constructed(code: object) -> None:
    with pytest.raises(ValueError):
        DocumentResolutionError(code, "message")  # type: ignore[arg-type]


def test_default_status_is_400() -> None:
    assert DocumentResolutionError("not_found", "gone").status_code == 400


# --- server-owned binding + source-only boundary ------------------------------


def test_binding_alias_is_exact() -> None:
    assert DOCUMENT_STORE_BINDING_NAME == "ENGINE_DOCUMENT_STORE"


def test_binding_alias_exact_and_store_import_polarity_composed_in_identity_only() -> None:
    wrangler = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert 'binding = "ENGINE_DOCUMENT_STORE"' in wrangler
    assert (
        wrangler.count('database_id = "6b77ad02-bc27-488f-bb97-6325f6750cba"') == 6
    ), "all six Engine D1 aliases share the one provisioned database"
    # #2764: the canonical composition moved INTO the identity worker; the
    # legacy worker stays unwidened. Only worker_identity may reference the
    # durable document store, and app-layer modules still never hard-code the
    # binding: it is deployment env supplied.
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "ENGINE_DOCUMENT_STORE" in identity_source
    assert "document_byte_store" in identity_source
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "ENGINE_DOCUMENT_STORE" not in legacy_source
    assert "document_byte_store" not in legacy_source
    for name in ("engine_composition.py", "capability_manifest.py", "contract_manifest.py"):
        source = (APP_ROOT / "app" / name).read_text(encoding="utf-8")
        assert "ENGINE_DOCUMENT_STORE" not in source
        assert "document_byte_store" not in source


def test_document_reference_module_stays_dependency_free() -> None:
    source = (APP_ROOT / "app" / "document_reference.py").read_text(encoding="utf-8")
    for forbidden in ("import d1", "from d1", "workers", "base64", "secrets", "sqlite", "http"):
        assert forbidden not in source
    assert "import re" in source
