"""E5B-S2 trusted document resolver tests (#1750), async durable seam (#2741).

Covers the S2 acceptance matrix over its evolved E8C-B form: opaque ``doc_*``
resolve through the durable storage port, scope and expiry enforcement, the
Core normalization bridge, projection safety and the zero-mutation canaries
for the canonical Core sources.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re

import pytest

from app.document_byte_store import (
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
    StoredDocumentRecord,
)
from app.trusted_document_resolver import (
    DOC_REFERENCE_PATTERN,
    DurableDocumentStoragePort,
    DocumentResolutionError,
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
# Canary hashes re-pinned at #2012 HWPX Core change (PR #2033).
# Re-pinned again at #2824-S3A, which changed the OOXML unsafe-path fixture only
# (PR #2861). Core *source* pins below are deliberately unchanged: that slice
# added no Core process authority.
# Re-pinned a third time at #2966 (PR #2969), which factors the Core HWPX
# archive-and-XML walk so a structured decoder and the flat reader share one
# parse. That is a Core *source* change to document_normalization.py, so its pin
# and its fixture pin move; document_semantics.py is untouched and stays pinned
# at the E5B-S1 digest. No Core process, network or filesystem authority was
# added by that slice.
# Re-pinned a fourth time at #2979, which adds the Core package-preserving
# mutation authority. That slice exposes a raw-member accessor and the gate's
# own member-name predicate from document_normalization.py, so its pin moves;
# the other three pins are unchanged. It adds no Core process, network or
# filesystem authority: every archive walk still runs through the one gate, and
# the mutator owns no archive or XML primitive of its own.
PINNED_SHA256 = {
    CORE_PACKAGE / "document_normalization.py": "41052fcf63fa47cdcc471a1ea938f5d34e5453d2917920877bb531beaa705d72",
    CORE_PACKAGE / "document_semantics.py": "a9cb2284d538c38aa5e08eb0e0ea4ff792922ae8ce58514e09228288ac57be85",
    CORE_TESTS / "test_document_semantics.py": "650ca215c9842b6bb4d45faed6707749c3cf2a7c008bb18fc4a567b0487fa7e5",
    CORE_TESTS / "test_document_normalization.py": "ba88eb112d5855751ba4316013daef60095e574ed8bb13441c479ad0cc70da5e",
}

REF = "doc_r2741resolvertest1"
OLD_S2_REF = "att_doc00000000000a"  # legacy S2 fixture; must never resolve now
SECRET_BODY = "quarterly revenue projections for beta-corp"
T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}


def _resolver(
    payload: bytes | None = None,
    *,
    meta: ResolvedDocumentMeta | None = None,
    ref: str = REF,
    bind: bool = True,
    clock_at: datetime | None = None,
) -> TrustedDocumentResolver:
    """Build the honest production stack: in-memory durable store behind the facade."""

    resolved_meta = meta or ResolvedDocumentMeta(
        media_type="text/plain",
        name="notes.txt",
        byte_size=len(payload if payload is not None else SECRET_BODY.encode("utf-8")),
        **SCOPE,
    )
    async def scenario() -> TrustedDocumentResolver:
        port = InMemoryDocumentByteStore()
        if bind:
            assert isinstance(resolved_meta, ResolvedDocumentMeta)
            await port.put(
                StoredDocumentRecord(
                    document_ref=ref,
                    app_id=resolved_meta.app_id,
                    tenant_id=resolved_meta.tenant_id,
                    subject_id=resolved_meta.subject_id,
                    media_type=resolved_meta.media_type,
                    name=resolved_meta.name,
                    byte_size=resolved_meta.byte_size,
                    created_at=T0,
                    expires_at=T0 + timedelta(hours=24),
                ),
                payload if payload is not None else SECRET_BODY.encode("utf-8"),
            )
        scoped = ScopedDocumentByteStore(
            port=port, clock=lambda: clock_at or T0
        )
        return TrustedDocumentResolver(storage=DurableDocumentStoragePort(scoped))

    return asyncio.run(scenario())


def _call(**overrides: object) -> dict[str, str]:
    scope: dict[str, str] = dict(SCOPE)
    scope.update(overrides)  # type: ignore[arg-type]
    return scope


# --- A: valid resolve -----------------------------------------------------


def test_a_valid_reference_resolves_to_bytes_and_meta() -> None:
    raw, meta = asyncio.run(_resolver().resolve(REF, **_call()))
    assert raw == SECRET_BODY.encode("utf-8")
    assert meta.media_type == "text/plain"
    assert meta.byte_size == len(raw)
    assert async_resolve_and_normalize_works()


def async_resolve_and_normalize_works() -> bool:
    doc = asyncio.run(resolve_and_normalize(_resolver(), REF, **_call()))
    return isinstance(doc, NormalizedDocument)


# --- B: invalid reference grammar -----------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    [
        None,
        "",
        "att_short",
        OLD_S2_REF,  # cross-namespace: image refs are foreign here
        "https://evil.example/x",
        "s3://bucket/private.bin",
        "opaque-blob-locator-77",
        "doc_inject me",
        f"doc_{'x' * 200}",
        "../doc_traversal",
        "DOC_" + "x" * 16,
    ],
)
def test_b_invalid_references_are_rejected(bad_ref: object) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        require_document_reference(bad_ref)
    assert info.value.code == "invalid_reference"
    with pytest.raises(DocumentResolutionError):
        asyncio.run(_resolver().resolve(bad_ref, **_call()))
    assert not any(
        forbidden in str(info.value).lower()
        for forbidden in ("bucket", "evil.example", "payload", "locator")
    )


# --- C: unknown reference --------------------------------------------------


def test_c_unknown_reference_is_not_found_without_leakage() -> None:
    resolver = _resolver(bind=False)
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolver.resolve(REF, **_call()))
    assert info.value.code == "not_found"
    assert info.value.status_code == 404
    assert OLD_S2_REF not in str(info.value)
    assert SECRET_BODY not in str(info.value)


def test_c2_empty_store_resolves_nothing() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(_resolver(bind=False).resolve(REF, **_call()))
    assert info.value.code == "not_found"


# --- D: scope enforcement ---------------------------------------------------


@pytest.mark.parametrize(
    "wrong",
    [
        {"app_id": "app.other"},
        {"subject_id": "user.99"},
        {"tenant_id": "tenant.b"},
    ],
)
def test_d_wrong_caller_scope_is_unauthorized(wrong: dict[str, str]) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(_resolver().resolve(REF, **_call(**wrong)))
    assert info.value.code == "unauthorized"
    assert info.value.status_code == 403


@pytest.mark.parametrize(
    "wrong",
    [
        {"app_id": ""},
        {"subject_id": "bad id"},
        {"tenant_id": "../x"},
        {"app_id": None},
        {"subject_id": "x" * 129},
    ],
)
def test_d2_invalid_caller_scope_shape_is_rejected(wrong: dict[str, str]) -> None:
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(_resolver().resolve(REF, **_call(**wrong)))
    assert info.value.code == "invalid_scope"


def test_d3_tampered_record_size_fails_closed() -> None:
    resolver = _resolver()
    # tamper the durable record directly: metadata no longer matches the bytes
    scoped = resolver._storage._store
    record = scoped._port._records[REF]
    scoped._port._records[REF] = replace(record, byte_size=len(SECRET_BODY) + 900)
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolver.resolve(REF, **_call()))
    assert info.value.code == "integrity_mismatch"


# --- E: retention state ------------------------------------------------------


def test_e_expired_document_resolves_as_expired() -> None:
    resolver = _resolver(clock_at=T0 + timedelta(hours=25))
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolver.resolve(REF, **_call()))
    assert info.value.code == "expired"
    assert info.value.status_code == 410


def test_e2_terminal_document_resolves_as_terminal() -> None:
    resolver = _resolver()

    async def scenario() -> None:
        scoped = resolver._storage._store
        await scoped.invalidate(document_ref=REF, **SCOPE)
        with pytest.raises(DocumentResolutionError) as info:
            await resolver.resolve(REF, **_call())
        assert info.value.code == "terminal"
        assert info.value.status_code == 410

    asyncio.run(scenario())


def test_e3_store_backend_failure_maps_to_store_unavailable() -> None:
    from app.document_byte_store import DocumentByteStoreError

    class Exploding:
        async def fetch_document(self, **_kwargs):
            raise DocumentByteStoreError(
                "store_unavailable", "Document byte store is unavailable.", status_code=503
            )

    resolver = TrustedDocumentResolver(storage=DurableDocumentStoragePort(Exploding()))
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolver.resolve(REF, **_call()))
    assert info.value.code == "store_unavailable"
    assert info.value.status_code == 503


# --- F: normalize through the durable seam ------------------------------------


def test_f_resolve_and_normalize_produces_canonical_document() -> None:
    document = asyncio.run(resolve_and_normalize(_resolver(), REF, **_call()))
    assert isinstance(document, NormalizedDocument)
    assert document.text == SECRET_BODY
    assert document.media_type == "text/plain"


def test_f2_undecodable_text_fails_closed() -> None:
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolve_and_normalize(_resolver(payload=b"\xff\xfe\x00\x01"), REF, **_call()))
    assert info.value.code == "decode_failed"


# --- G/H: projection ------------------------------------------------------------


def test_g_projection_exposes_only_safe_metadata_keys() -> None:
    document = asyncio.run(resolve_and_normalize(_resolver(), REF, **_call()))
    projection = SafeDocumentProjection.from_document(document)
    assert "kind" in projection.to_dict()
    assert "name" in projection.to_dict()
    assert "text" not in projection.to_dict()
    assert "segments" not in projection.to_dict()


def test_h_projection_never_leaks_secret_body() -> None:
    document = asyncio.run(resolve_and_normalize(_resolver(), REF, **_call()))
    projection = SafeDocumentProjection.from_document(document)
    combined = repr(projection) + str(projection.to_dict())
    assert SECRET_BODY not in combined


# --- I: legacy namespace can never resolve -------------------------------------


def test_i_legacy_att_reference_is_rejected_end_to_end() -> None:
    # the exact S2 fixture from #1750 fails closed now: cross-namespace refusal
    with pytest.raises(DocumentResolutionError) as info:
        asyncio.run(resolve_and_normalize(_resolver(), OLD_S2_REF, **_call()))
    assert info.value.code == "invalid_reference"


# --- J: no eager optional-extraction imports at module head ---------------------


def test_j_heavy_parsers_stay_lazy() -> None:
    module = pytest.importorskip("app.trusted_document_resolver")
    source = Path(module.__file__).read_text(encoding="utf-8")
    head = source.split("def normalize_resolved_document")[0]
    assert not re.search(r"^\s*import pypdf", head, re.MULTILINE)
    assert not re.search(r"^\s*import openpyxl", head, re.MULTILINE)
    assert not re.search(r"^\s*from pypdf", head, re.MULTILINE)
    assert not re.search(r"^\s*from openpyxl", head, re.MULTILINE)


# --- J2: namespace isolation from the image lane --------------------------------


def test_j2_document_and_image_grammar_do_not_overlap() -> None:
    assert DOC_REFERENCE_PATTERN.pattern.startswith("^doc_")
    # a legal doc reference is rejected by the image grammar owner
    from app.attachment_authority import EngineAttachmentAuthorityError, require_opaque_attachment_ref

    with pytest.raises(EngineAttachmentAuthorityError):
        require_opaque_attachment_ref(REF)


# --- K: durable port is the only storage adapter --------------------------------


def test_k_legacy_sync_port_surface_is_gone() -> None:
    import app.trusted_document_resolver as module

    assert not hasattr(module, "InMemoryStoragePort")
    assert not hasattr(TrustedDocumentResolver, "register")
    assert not hasattr(TrustedDocumentResolver, "bind")
    assert callable(getattr(TrustedDocumentResolver, "resolve"))
    import inspect

    assert inspect.iscoroutinefunction(TrustedDocumentResolver.resolve)
    assert inspect.iscoroutinefunction(resolve_and_normalize)


# --- L/M: zero-mutation canaries -----------------------------------------------


@pytest.mark.parametrize("path, digest", list(PINNED_SHA256.items()))
def test_lm_canaries_hold(path: Path, digest: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == digest, f"{path.name} drifted from pinned SHA256"
