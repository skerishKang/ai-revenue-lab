"""Network-free PDF ownership/bundle tests; renderer execution is separate proof.

Synthetic fixture bytes and a fake renderer isolate the authenticated transport
and private archive boundary. They are not document-fidelity certification.
"""

from __future__ import annotations

import copy
import hashlib
import json
import stat
import sys
import types
from io import BytesIO
from unittest.mock import MagicMock
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from starlette.testclient import TestClient

import app
from app.app_factory import create_app
from app.b66_certified_preview import B66CertifiedPreviewStore, CGI_PREVIEW_OBJECT_KEY
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_certified_quote_bundle import (
    BUNDLE_SCHEMA, MAX_BUNDLE_ZIP_BYTES,
    B66CertifiedQuoteBundleError, B66CertifiedQuoteBundleStore,
    bundle_object_key, parse_bundle,
)
from app.config import Settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
WORKSPACE = "owner:" + USER_A
SAVED_ID = "b66skill_" + "c" * 32
SKILL_HASH = "1" * 64
PROFILE_HASH = "2" * 64
RENDERER_HASH = "3" * 64
PDF = b"%PDF-1.7\nsynthetic-private-document\n%%EOF"
FONT = b"synthetic-font-for-boundary-test"
SCOPE = {
    "max_item_rows": 3, "date_serial_range": [1, 2958465],
    "amounts": "non-negative integers (negative/non-integer fail-closed)",
    "text_overflow": "fail-closed rejection when text exceeds its slot room",
}


def _model():
    return {
        "schemaVersion": 1, "derivedBy": "quote-core",
        "template": {"fingerprint": PROFILE_HASH},
        "facts": {"meta": {"quoteNo": "Q-2026-001"}},
        "items": [{"values": {"name": "Synthetic item"}}] + [
            {"filler": True, "values": {}} for _ in range(6)
        ],
        "taxReview": {"required": False},
        "coreTotals": {
            "amounts": [100], "subtotal": 100, "supply": 100,
            "vat": 10, "grand": 110, "mode": "EXCLUSIVE",
            "effectiveItems": [{"name": "Synthetic item", "qty": 1, "unitPrice": 100}],
        },
        "writtenWords": "일백일십",
    }


@pytest.fixture
def renderer(monkeypatch):
    fake = types.ModuleType("app.b66_certified_pdf_renderer")
    fake.RENDERER_CONTRACT = "b66.certified-pdf.render-only.v1"
    fake.ENGINE_VERSION = "1.26.3"
    fake.renderer_source_sha256 = lambda: RENDERER_HASH
    fake.calls = []

    class PdfError(ValueError):
        def __init__(self, code):
            self.code = code
            super().__init__("private renderer detail must not escape")

    fake.B66CertifiedPdfError = PdfError

    def render_pdf(**kwargs):
        fake.calls.append(kwargs)
        return PDF

    fake.render_pdf = render_pdf
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(app, "b66_certified_pdf_renderer", fake, raising=False)
    return fake


def _archive(*, manifest_change=None, payload_change=None, extra=None, compression=ZIP_STORED):
    template = {
        "schema": "b66.quote_template.v2", "supported_scope": copy.deepcopy(SCOPE),
        "resources": {
            "base_document": {"file": "base_document.pdf", "sha256": hashlib.sha256(PDF).hexdigest()},
            "fonts": {"SyntheticFont": {"file": "fonts/synthetic.ttf", "sha256": hashlib.sha256(FONT).hexdigest()}},
        },
    }
    payloads = {
        "base.pdf": PDF, "fonts/synthetic.ttf": FONT,
        "template.json": json.dumps(template).encode(),
    }
    manifest = {
        "schema": BUNDLE_SCHEMA, "saved_skill_id": SAVED_ID,
        "skill_fingerprint": SKILL_HASH, "profile_fingerprint": PROFILE_HASH,
        "renderer_contract": "b66.certified-pdf.render-only.v1",
        "engine_version": "1.26.3", "renderer_sha256": RENDERER_HASH,
        "certification": {"status": "PASS"},
        "supported_scope": copy.deepcopy(SCOPE), "baseline_render_model": _model(),
        "files": {name: {"byte_length": len(body), "sha256": hashlib.sha256(body).hexdigest()} for name, body in payloads.items()},
    }
    if manifest_change:
        manifest_change(manifest)
    if payload_change:
        payload_change(payloads)
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for name, body in payloads.items():
            archive.writestr(name, body)
        if extra:
            for name, body in extra:
                archive.writestr(name, body)
    return output.getvalue()


def _parse(body):
    return parse_bundle(body, saved_skill_id=SAVED_ID, skill_fingerprint=SKILL_HASH, profile_fingerprint=PROFILE_HASH)


def test_verified_bundle_returns_only_compiled_bytes(renderer):
    bundle = _parse(_archive())
    assert bundle.base_pdf == PDF
    assert bundle.fonts == {"fonts/synthetic.ttf": FONT}
    assert bundle.baseline_render_model["coreTotals"]["grand"] == 110
    assert renderer.calls == []


@pytest.mark.parametrize("change", [
    lambda m: m.update(saved_skill_id="b66skill_" + "d" * 32),
    lambda m: m.update(skill_fingerprint="4" * 64),
    lambda m: m.update(profile_fingerprint="5" * 64),
    lambda m: m.update(engine_version="1.26.4"),
    lambda m: m.update(renderer_sha256="6" * 64),
    lambda m: m["certification"].update(status="UNPROVEN"),
    lambda m: m["supported_scope"].update(max_item_rows=4),
    lambda m: m["files"]["base.pdf"].update(sha256="7" * 64),
    lambda m: m["baseline_render_model"].pop("coreTotals"),
])
def test_stale_uncertified_or_tampered_bundle_never_reaches_renderer(renderer, change):
    with pytest.raises(B66CertifiedQuoteBundleError):
        _parse(_archive(manifest_change=change))
    assert renderer.calls == []


def test_font_bytes_rehashed_even_when_pdf_is_unchanged(renderer):
    tampered = _archive(payload_change=lambda p: p.update({"fonts/synthetic.ttf": b"tampered-font"}))
    with pytest.raises(B66CertifiedQuoteBundleError):
        _parse(tampered)


@pytest.mark.parametrize("name", ["../escape.ttf", "/absolute.ttf", "fonts/nested/escape.ttf", "unknown.json", "base.pdf"])
def test_extra_unsafe_or_duplicate_members_are_rejected(renderer, name):
    with pytest.raises(B66CertifiedQuoteBundleError):
        _parse(_archive(extra=[(name, b"unexpected-private-member")]))


def test_symlink_member_rejected_without_extraction(renderer):
    link = ZipInfo("fonts/link.ttf")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(B66CertifiedQuoteBundleError):
        _parse(_archive(extra=[(link, b"/private/path")]))


def test_archive_expansion_bound_checked_before_read(renderer, monkeypatch):
    import app.b66_certified_quote_bundle as module

    monkeypatch.setattr(module, "MAX_BUNDLE_EXPANDED_BYTES", 16)
    with pytest.raises(B66CertifiedQuoteBundleError):
        _parse(_archive(compression=ZIP_DEFLATED))


class _R2Object:
    def __init__(self, body, *, size=None):
        self._body = body
        self.size = len(body) if size is None else size
        self.reads = 0

    async def arrayBuffer(self):
        self.reads += 1
        return self._body

    @property
    def body(self):
        raise AssertionError("JS stream body must not be read")


class _R2:
    def __init__(self, obj):
        self.obj = obj
        self.calls = []

    async def get(self, key):
        self.calls.append(key)
        return self.obj


@pytest.mark.asyncio
async def test_private_store_derives_key_and_reads_arraybuffer_once(renderer):
    obj = _R2Object(_archive())
    r2 = _R2(obj)
    store = B66CertifiedQuoteBundleStore(r2)
    result = await store.get_bundle(saved_skill_id=SAVED_ID, skill_fingerprint=SKILL_HASH, profile_fingerprint=PROFILE_HASH)
    assert result.base_pdf == PDF
    assert r2.calls == [f"b66/certified-quote-bundles/{SAVED_ID}/{SKILL_HASH}/bundle.zip"]
    assert obj.reads == 1
    r2.obj = _R2Object(_archive(payload_change=lambda p: p.update({"base.pdf": b"%PDF-tampered"})))
    with pytest.raises(B66CertifiedQuoteBundleError):
        await store.get_bundle(saved_skill_id=SAVED_ID, skill_fingerprint=SKILL_HASH, profile_fingerprint=PROFILE_HASH)
    assert len(r2.calls) == 2, "private bytes are re-read and verified for each request"


@pytest.mark.asyncio
async def test_oversized_r2_object_rejected_before_read(renderer):
    obj = _R2Object(b"small", size=MAX_BUNDLE_ZIP_BYTES + 1)
    with pytest.raises(B66CertifiedQuoteBundleError):
        await B66CertifiedQuoteBundleStore(_R2(obj)).get_bundle(saved_skill_id=SAVED_ID, skill_fingerprint=SKILL_HASH, profile_fingerprint=PROFILE_HASH)
    assert obj.reads == 0


def test_invalid_assignment_cannot_redirect_private_key():
    with pytest.raises(B66CertifiedQuoteBundleError):
        bundle_object_key(saved_skill_id="../other", skill_fingerprint=SKILL_HASH)


def _saved_row():
    return {
        "saved_skill_id": SAVED_ID, "workspace_id": WORKSPACE, "status": "approved",
        "skill_fingerprint": SKILL_HASH,
        "skill": {
            "fingerprint": SKILL_HASH, "calculationAuthority": "quote-core",
            "rendererContract": "quote-template-renderer.v1",
            "approval": {"status": "approved", "skillFingerprint": SKILL_HASH},
            "internalTemplate": {
                "fingerprint": PROFILE_HASH,
                "approval": {"status": "approved", "contentFingerprint": PROFILE_HASH},
            },
        },
    }


class _Skills:
    def __init__(self):
        self.rows = {(USER_A, WORKSPACE, SAVED_ID): _saved_row()}
        self.calls = []

    async def get_skill(self, **kwargs):
        self.calls.append(kwargs)
        row = self.rows.get((kwargs["user_id"], kwargs["workspace_id"], kwargs["saved_skill_id"]))
        return row if row and row["status"] == "approved" else None


class _Bundles:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = []

    async def get_bundle(self, **kwargs):
        self.calls.append(kwargs)
        return self.bundle


class _PdfService:
    def __init__(self, *, status=200, body=PDF, content_type="application/pdf"):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.calls = []

    async def render_pdf(self, **kwargs):
        self.calls.append(kwargs)
        return self.status, self.body, self.content_type


def _client(*, skills=None, bundles=None, signed_in=True, user=USER_A, **kwargs):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", live_enabled="false",
        public_base_url="https://chat.example.test", google_client_id="synthetic.apps.example",
        google_client_secret="synthetic-test-secret", session_secret="synthetic-test-session-secret-000000",
    )
    pdf_service = kwargs.pop("b66_pdf_renderer_client", None) or _PdfService()
    instance = create_app(
        settings=settings, history_store=MagicMock(), b66_saved_quote_skill_store=skills,
        b66_certified_quote_bundle_store=bundles, b66_pdf_renderer_client=pdf_service, **kwargs,
    )
    instance.state._test_pdf_service = pdf_service
    client = TestClient(instance, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, user), domain="chat.example.test", path="/")
    return client


def _post(client, model=None, **extra):
    return client.post("/api/b66/quote/pdf", json={"saved_skill_id": SAVED_ID, "render_model": model or _model(), **extra})


def test_pdf_route_requires_auth_and_owner_before_private_read(renderer):
    skills = _Skills()
    bundles = _Bundles(_parse(_archive()))
    anonymous = _client(skills=skills, bundles=bundles, signed_in=False)
    assert _post(anonymous).status_code == 401
    assert skills.calls == bundles.calls == []
    other = _client(skills=skills, bundles=bundles, user=USER_B)
    assert _post(other).status_code == 404
    assert bundles.calls == renderer.calls == []
    skills.rows[(USER_A, WORKSPACE, SAVED_ID)]["status"] = "disabled"
    assert _post(_client(skills=skills, bundles=bundles)).status_code == 404
    assert bundles.calls == []


def test_pdf_route_unavailable_workspace_never_uses_owner_fallback(renderer):
    skills = _Skills()
    bundles = _Bundles(_parse(_archive()))
    client = _client(skills=skills, bundles=bundles, identity_shadow_store=object())
    response = _post(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "workspace_authority_unavailable"
    assert skills.calls == bundles.calls == []


def test_same_user_other_workspace_cannot_read_bundle(renderer, monkeypatch):
    import app.b66_certified_pdf_routes as routes

    async def other_workspace(request, uid):
        return "tenant_" + "d" * 32

    monkeypatch.setattr(routes, "_resolve_memory_workspace", other_workspace)
    bundles = _Bundles(_parse(_archive()))
    assert _post(_client(skills=_Skills(), bundles=bundles)).status_code == 404
    assert bundles.calls == []


def test_route_streams_renderer_bytes_and_ignores_ui_filler_rows(renderer):
    skills = _Skills()
    bundles = _Bundles(_parse(_archive()))
    client = _client(skills=skills, bundles=bundles)
    response = _post(client)
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="quote-Q-2026-001.pdf"'
    assert response.headers["cache-control"].startswith("private, no-store")
    assert bundles.calls == []
    assert client.app.state._test_pdf_service.calls[0]["saved_skill_id"] == SAVED_ID
    assert client.app.state._test_pdf_service.calls[0]["skill_fingerprint"] == SKILL_HASH
    assert client.app.state._test_pdf_service.calls[0]["profile_fingerprint"] == PROFILE_HASH
    assert client.app.state._test_pdf_service.calls[0]["render_model"]["coreTotals"]["grand"] == 110


def test_approved_skill_with_canonical_builtin_profile_keeps_existing_authority(renderer):
    skills = _Skills()
    profile = skills.rows[(USER_A, WORKSPACE, SAVED_ID)]["skill"]["internalTemplate"]
    profile.update(builtin=True, approval=None)
    client = _client(skills=skills, bundles=_Bundles(_parse(_archive())))
    response = _post(client)
    assert response.status_code == 200
    assert len(renderer.calls) == 0
    assert len(client.app.state._test_pdf_service.calls) == 1


def test_present_profile_approval_cannot_disagree_with_persisted_fingerprint(renderer):
    skills = _Skills()
    profile = skills.rows[(USER_A, WORKSPACE, SAVED_ID)]["skill"]["internalTemplate"]
    profile["approval"]["contentFingerprint"] = "9" * 64
    bundles = _Bundles(_parse(_archive()))
    response = _post(_client(skills=skills, bundles=bundles))
    assert response.status_code == 503
    assert bundles.calls == renderer.calls == []


@pytest.mark.parametrize("change", [
    lambda m: m.pop("coreTotals"), lambda m: m.pop("writtenWords"),
    lambda m: m["taxReview"].update(required=True),
    lambda m: m["template"].update(fingerprint="8" * 64),
])
def test_missing_values_provisional_tax_and_client_template_override_fail_closed(renderer, change):
    model = _model()
    change(model)
    bundles = _Bundles(_parse(_archive()))
    response = _post(_client(skills=_Skills(), bundles=bundles), model=model)
    assert response.status_code == 422
    assert bundles.calls == renderer.calls == []


def test_extra_owner_field_and_bad_row_id_fail_before_authority_reads(renderer):
    skills = _Skills()
    bundles = _Bundles(_parse(_archive()))
    client = _client(skills=skills, bundles=bundles)
    assert _post(client, user_id=USER_B).status_code == 400
    assert client.post("/api/b66/quote/pdf", json={"saved_skill_id": "../other", "render_model": _model()}).status_code == 400
    assert skills.calls == bundles.calls == []


@pytest.mark.parametrize("upstream_status,status", [(422, 422), (503, 503)])
def test_renderer_service_errors_are_bounded(renderer, upstream_status, status):
    service = _PdfService(status=upstream_status, body=b'{"private":"detail"}', content_type="application/json")
    response = _post(_client(
        skills=_Skills(), bundles=_Bundles(_parse(_archive())),
        b66_pdf_renderer_client=service,
    ))
    assert response.status_code == status
    assert "private" not in response.text


def test_invalid_pdf_service_response_fails_closed(renderer):
    service = _PdfService(status=200, body=b"not-a-pdf", content_type="text/plain")
    response = _post(_client(
        skills=_Skills(), bundles=_Bundles(_parse(_archive())),
        b66_pdf_renderer_client=service,
    ))
    assert response.status_code == 503



def test_absent_pdf_service_never_falls_back_to_html_print(renderer):
    client = _client(skills=_Skills(), bundles=_Bundles(None))
    client.app.state.b66_pdf_renderer_client = None
    response = _post(client)
    assert response.status_code == 503
    assert renderer.calls == []


def test_factory_reuses_r2_for_read_only_bundle_store():
    r2 = _R2(None)
    client = _client(r2_binding=r2)
    store = client.app.state.b66_certified_quote_bundle_store
    assert isinstance(store, B66CertifiedQuoteBundleStore)
    assert store.r2_bucket is r2
    assert not hasattr(store, "put_bundle")

class _PreviewService:
    def __init__(self, body=b"\x89PNG\r\n\x1a\nsynthetic-preview"):
        self.body = body
        self.calls = []

    async def get_preview(self, **kwargs):
        self.calls.append(kwargs)
        return self.body


def test_preview_route_requires_auth_and_exact_owner_skill(renderer):
    skills = _Skills()
    preview = _PreviewService()
    anonymous = _client(
        skills=skills, signed_in=False, b66_certified_preview_store=preview
    )
    response = anonymous.get(
        "/api/b66/quote/preview-base", params={"saved_skill_id": SAVED_ID}
    )
    assert response.status_code == 401
    assert preview.calls == []

    other = _client(
        skills=skills, user=USER_B, b66_certified_preview_store=preview
    )
    response = other.get(
        "/api/b66/quote/preview-base", params={"saved_skill_id": SAVED_ID}
    )
    assert response.status_code == 404
    assert preview.calls == []


def test_preview_route_streams_only_verified_private_png(renderer):
    preview = _PreviewService()
    client = _client(
        skills=_Skills(), b66_certified_preview_store=preview
    )
    response = client.get(
        "/api/b66/quote/preview-base", params={"saved_skill_id": SAVED_ID}
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"].startswith("private, no-store")
    assert preview.calls == [{
        "skill_fingerprint": SKILL_HASH,
        "profile_fingerprint": PROFILE_HASH,
    }]


@pytest.mark.asyncio
async def test_preview_store_is_exact_fingerprint_and_hash_bound(monkeypatch):
    import app.b66_certified_preview as preview_module

    body = b"\x89PNG\r\n\x1a\nverified-preview"
    monkeypatch.setattr(
        preview_module, "CGI_PREVIEW_SHA256", hashlib.sha256(body).hexdigest()
    )
    obj = _R2Object(body)
    r2 = _R2(obj)
    store = B66CertifiedPreviewStore(r2)

    assert await store.get_preview(
        skill_fingerprint=preview_module.CGI_SKILL_FINGERPRINT,
        profile_fingerprint=preview_module.CGI_PROFILE_FINGERPRINT,
    ) == body
    assert r2.calls == [CGI_PREVIEW_OBJECT_KEY]
    assert await store.get_preview(
        skill_fingerprint="9" * 64,
        profile_fingerprint=preview_module.CGI_PROFILE_FINGERPRINT,
    ) is None
    assert r2.calls == [CGI_PREVIEW_OBJECT_KEY]
