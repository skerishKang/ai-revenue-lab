"""#3932: genuine owner-scoped PDF inline preview, truthful other-format fallback.

Uses the production endpoint with a test-only canonical tenant authority seam.
No mocked preview is represented as real user-facing UI or Production proof.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app.claw_artifact_preview_routes import claw_artifact_inline_preview
from app.workspace_storage import WorkspaceStorageAccessError

ID = "doc_" + "b" * 32
PATH = "/api/claw/manual-intake/artifact/" + ID + "/preview"
PDF = b"%PDF-1.4\n1 0 obj\n<</Type/Catalog>>\nendobj\n%%EOF\n"
PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _client(*, mime=PDF_MIME, payload=PDF, owner="tenant_a", identity="tenant_a",
            missing=False, failure=None, filename="safe.pdf"):
    meta = SimpleNamespace(document_id=ID, tenant_id=owner, filename=filename, media_type=mime)
    store = SimpleNamespace(get_for_tenant=AsyncMock(
        side_effect=failure if failure else None,
        return_value=None if missing else (meta, payload),
    ))
    app = Starlette(routes=[Route(
        "/api/claw/manual-intake/artifact/{document_id}/preview",
        claw_artifact_inline_preview,
        methods=["GET"],
    )])
    app.state.workspace_document_store = store
    return app, store, AsyncMock(return_value=identity)


def _get(**kwargs):
    app, store, resolver = _client(**kwargs)
    with patch("app.claw_artifact_preview_routes._resolve_canonical_tenant", new=resolver):
        with TestClient(app, base_url="https://chat.example.test") as client:
            result = client.get(PATH)
    return result, store, resolver


def test_real_pdf_bytes_are_inline_only_after_tenant_verified_read():
    resp, store, resolver = _get()
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-type"] == PDF_MIME
    assert resp.headers["content-disposition"].startswith("inline; filename*=UTF-8''")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cross-origin-resource-policy"] == "same-origin"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"
    assert "no-store" in resp.headers["cache-control"]
    store.get_for_tenant.assert_awaited_once_with(tenant_id="tenant_a", document_id=ID)
    resolver.assert_awaited_once()


def test_signed_out_never_reads_storage():
    resp, store, _ = _get(identity=None)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "workspace_scope_unavailable"
    store.get_for_tenant.assert_not_awaited()


def test_missing_foreign_and_deleted_are_nondisclosing_identical_404():
    res = [_get(missing=True)[0], _get(failure=WorkspaceStorageAccessError("foreign id"))[0],
           _get(owner="other_tenant")[0]]
    assert all(r.status_code == 404 for r in res)
    assert all(r.json()["error"]["code"] == "artifact_not_found" for r in res)
    assert len({r.text for r in res}) == 1


def test_read_failure_does_not_leak_object_key():
    resp, _, _ = _get(failure=RuntimeError("R2 secret object key: workspace/tenant_a/token"))
    assert resp.status_code == 503
    assert "workspace/tenant" not in resp.text
    assert "token" not in resp.text


def test_mime_and_bytes_must_both_match_before_inline():
    for mime, payload in ((PDF_MIME, b"<html><script>alert(1)</script>"),
                          (PDF_MIME, b"%PDF-1.4\nmissing eof"),
                          (XLSX_MIME, PDF), (DOCX_MIME, PDF)):
        resp, _, _ = _get(mime=mime, payload=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        preview = resp.json()["preview"]
        assert preview["available"] is False
        assert preview["kind"] == "download_only"
        assert preview["download_available"] is True
        assert resp.headers["x-content-type-options"] == "nosniff"


def test_oversized_pdf_cannot_be_inlined():
    resp, _, _ = _get(payload=b"%PDF-1.4\n" + b"A" * (10 * 1024 * 1024) + b"%%EOF")
    assert resp.status_code == 200
    assert resp.json()["preview"]["available"] is False


def test_untrusted_filename_is_encoded_not_raw_header():
    resp, _, _ = _get(filename="evil\r\nX-Admin:true.pdf")
    assert resp.status_code == 200
    assert "\r\n" not in resp.headers["content-disposition"]
    assert "X-Admin" in resp.headers["content-disposition"]
    assert "%0D%0A" in resp.headers["content-disposition"]


def test_invalid_artifact_id_fails_before_storage():
    app, store, resolver = _client()
    with patch("app.claw_artifact_preview_routes._resolve_canonical_tenant", new=resolver):
        with TestClient(app) as client:
            resp = client.get("/api/claw/manual-intake/artifact/../../etc/passwd/preview")
            # Starlette may normalize ..; any such path must be refused.
            assert resp.status_code in (400, 404)
    store.get_for_tenant.assert_not_awaited()


def test_no_new_storage_authority_and_download_route_unchanged():
    root = Path(__file__).resolve().parents[1] / "app"
    preview = (root / "claw_artifact_preview_routes.py").read_text(encoding="utf-8")
    app = (root / "app_factory.py").read_text(encoding="utf-8")
    assert 'from .claw_routes import _resolve_canonical_tenant' in preview
    assert 'store.get_for_tenant(tenant_id=tenant, document_id=document_id)' in preview
    assert 'Route("/api/claw/manual-intake/artifact/{document_id}", claw_manual_intake_artifact' in app
    assert 'claw_artifact_inline_preview' in app
    assert "put_generated_docx" not in preview
    assert "URL.createObjectURL" not in preview
    assert "artifacts://" not in preview
