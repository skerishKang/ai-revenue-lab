"""#5877 B66 상수 실측: 견적 1건 생성 → 인증 번들 → 미리보기, 10MiB 경계 포함.

B14·R2·실제 PDF 렌더러는 호출하지 않는다(모의 실행 대역). 견적 금액은
QuoteCore(reference/business-66-padiem-quote-v1/quote-core.js)가 계산한 값만 쓰고,
Python 쪽에서 반올림 규칙을 재구현하지 않는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import types
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock
from zipfile import ZIP_STORED, ZipFile

import pytest
from starlette.testclient import TestClient

import app
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_certified_preview import (
    B66CertifiedPreviewError,
    B66CertifiedPreviewStore,
    CGI_PROFILE_FINGERPRINT,
    CGI_SKILL_FINGERPRINT,
)
from app.b66_certified_quote_bundle import (
    BUNDLE_SCHEMA,
    MAX_BUNDLE_JSON_BYTES,
    B66CertifiedQuoteBundleError,
    B66CertifiedQuoteBundleStore,
    parse_bundle,
)
from app.b66_certified_preview import MAX_PREVIEW_BYTES
from app.config import Settings

USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
WORKSPACE = "owner:" + USER_A
SAVED_ID = "b66skill_" + "c" * 32
# 미리보기 저장소는 CGI 지문 쌍에만 응답하므로 승인 스킬을 그 지문에 묶는다.
SKILL_HASH = CGI_SKILL_FINGERPRINT
PROFILE_HASH = CGI_PROFILE_FINGERPRINT
RENDERER_HASH = "3" * 64
PDF = b"%PDF-1.7\nsynthetic-private-document\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\nsynthetic-certified-preview-base"
SCOPE = {
    "max_item_rows": 3,
    "date_serial_range": [1, 2958465],
    "amounts": "non-negative integers (negative/non-integer fail-closed)",
    "text_overflow": "fail-closed rejection when text exceeds its slot room",
}
QUOTE_CORE = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
    / "quote-core.js"
)


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


def _draft():
    return {
        "schemaVersion": 1,
        "meta": {"quoteNo": "Q-2026-001"},
        "items": [{"id": "item-1", "name": "합성 배관", "qty": 2, "unitPrice": 10000}],
        "tax": {"mode": "EXCLUSIVE"},
    }


def _quote_core(draft):
    """실제 QuoteCore로 금액을 계산한다(B14 없이)."""
    script = (
        "const Core=require(process.argv[1]);"
        "const draft=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const totals=Core.computeDraftTotals(draft);"
        "if(!totals)process.exit(9);"
        "console.log(JSON.stringify({coreTotals:totals,"
        "writtenWords:Core.formatKoreanMoneyWords(totals.grand)}));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(QUOTE_CORE)],
        input=json.dumps(draft),
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _model(draft=None):
    computed = _quote_core(draft if draft is not None else _draft())
    return {
        "schemaVersion": 1,
        "derivedBy": "quote-core",
        "template": {"fingerprint": PROFILE_HASH},
        "facts": {"meta": {"quoteNo": "Q-2026-001"}},
        "items": [{"values": {"name": "합성 배관"}}],
        "taxReview": {"required": False},
        "coreTotals": computed["coreTotals"],
        "writtenWords": computed["writtenWords"],
    }


def _template_body(template):
    return json.dumps(template).encode()


def _padded_template(target_bytes):
    """template.json을 정확히 target_bytes로 만든다(패딩 키 1바이트 = 1문자)."""
    template = {
        "schema": "b66.quote_template.v2",
        "supported_scope": copy.deepcopy(SCOPE),
        "resources": {
            "base_document": {
                "file": "base_document.pdf",
                "sha256": hashlib.sha256(PDF).hexdigest(),
            },
            "fonts": {},
        },
        "pad": "",
    }
    deficit = target_bytes - len(_template_body(template))
    if deficit > 0:
        template["pad"] = "a" * deficit
    body = _template_body(template)
    assert len(body) == target_bytes
    return body


def _archive(model=None, *, template_bytes=None, base_pdf=PDF):
    payloads = {"base.pdf": base_pdf}
    if template_bytes is None:
        payloads["template.json"] = _template_body(
            {
                "schema": "b66.quote_template.v2",
                "supported_scope": copy.deepcopy(SCOPE),
                "resources": {
                    "base_document": {
                        "file": "base_document.pdf",
                        "sha256": hashlib.sha256(base_pdf).hexdigest(),
                    },
                    "fonts": {},
                },
            }
        )
    else:
        payloads["template.json"] = template_bytes
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "saved_skill_id": SAVED_ID,
        "skill_fingerprint": SKILL_HASH,
        "profile_fingerprint": PROFILE_HASH,
        "renderer_contract": "b66.certified-pdf.render-only.v1",
        "engine_version": "1.26.3",
        "renderer_sha256": RENDERER_HASH,
        "certification": {"status": "PASS"},
        "supported_scope": copy.deepcopy(SCOPE),
        "baseline_render_model": _model() if model is None else model,
        "files": {
            name: {
                "byte_length": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            for name, body in payloads.items()
        },
    }
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest).encode())
        for name, body in payloads.items():
            archive.writestr(name, body)
    return output.getvalue()


def _parse(body):
    return parse_bundle(
        body,
        saved_skill_id=SAVED_ID,
        skill_fingerprint=SKILL_HASH,
        profile_fingerprint=PROFILE_HASH,
    )


class _R2Object:
    def __init__(self, body, *, size=None):
        self._body = body
        self.size = len(body) if size is None else size
        self.reads = 0

    async def arrayBuffer(self):
        self.reads += 1
        return self._body


class _R2:
    def __init__(self, obj):
        self.obj = obj
        self.calls = []

    async def get(self, key):
        self.calls.append(key)
        return self.obj


def _saved_row():
    return {
        "saved_skill_id": SAVED_ID,
        "workspace_id": WORKSPACE,
        "status": "approved",
        "skill_fingerprint": SKILL_HASH,
        "skill": {
            "fingerprint": SKILL_HASH,
            "calculationAuthority": "quote-core",
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
        row = self.rows.get(
            (kwargs["user_id"], kwargs["workspace_id"], kwargs["saved_skill_id"])
        )
        return row if row and row["status"] == "approved" else None


class _BundlePdfClient:
    """렌더 서비스 대역: 인증 번들만 읽고, 제출 모델이 번들과 같을 때만 PDF를 준다."""

    def __init__(self, store):
        self.store = store
        self.calls = []

    async def render_pdf(self, *, saved_skill_id, skill_fingerprint, profile_fingerprint, render_model):
        self.calls.append(
            {
                "saved_skill_id": saved_skill_id,
                "skill_fingerprint": skill_fingerprint,
                "profile_fingerprint": profile_fingerprint,
                "render_model": render_model,
            }
        )
        bundle = await self.store.get_bundle(
            saved_skill_id=saved_skill_id,
            skill_fingerprint=skill_fingerprint,
            profile_fingerprint=profile_fingerprint,
        )
        if bundle is None:
            return 503, b"{}", "application/json"
        baseline = json.dumps(bundle.baseline_render_model["coreTotals"], sort_keys=True)
        submitted = json.dumps(render_model["coreTotals"], sort_keys=True)
        if baseline != submitted:
            return 422, b"{}", "application/json"
        return 200, bundle.base_pdf, "application/pdf"


def _client(*, skills=None, bundle_store=None, preview_store=None, pdf_client=None, user=USER_A):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        live_enabled="false",
        public_base_url="https://chat.example.test",
        google_client_id="synthetic.apps.example",
        google_client_secret="synthetic-test-secret",
        session_secret="synthetic-test-session-secret-000000",
    )
    instance = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=skills,
        b66_certified_quote_bundle_store=bundle_store,
        b66_certified_preview_store=preview_store,
        b66_pdf_renderer_client=pdf_client,
    )
    client = TestClient(instance, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, user), domain="chat.example.test", path="/"
    )
    return client


def test_5877_quote_core_bundle_pdf_and_preview_end_to_end(renderer, monkeypatch):
    skill = _saved_row()["skill"]
    assert skill["fingerprint"] == CGI_SKILL_FINGERPRINT

    # 1) 견적 생성: 실제 QuoteCore 계산(2 × 10,000원, 부가세 별도).
    model = _model()
    assert model["derivedBy"] == "quote-core"
    assert model["coreTotals"]["subtotal"] == 20000
    assert model["coreTotals"]["vat"] == 2000
    assert model["coreTotals"]["grand"] == 22000
    assert model["writtenWords"] == "이만이천"

    # 2) 번들: 계산 결과가 그대로 봉인되고, 파서가 다시 검증한다.
    bundle = _parse(_archive(model))
    assert bundle.baseline_render_model["coreTotals"]["grand"] == 22000
    assert bundle.fonts == {}

    obj = _R2Object(_archive(model))
    store = B66CertifiedQuoteBundleStore(_R2(obj))
    preview = B66CertifiedPreviewStore(_R2(_R2Object(PNG)))
    monkeypatch.setattr(
        "app.b66_certified_preview.CGI_PREVIEW_SHA256", hashlib.sha256(PNG).hexdigest()
    )

    client = _client(
        skills=_Skills(),
        bundle_store=store,
        preview_store=preview,
        pdf_client=_BundlePdfClient(store),
    )

    pdf = client.post(
        "/api/b66/quote/pdf", json={"saved_skill_id": SAVED_ID, "render_model": model}
    )
    assert pdf.status_code == 200, pdf.text
    assert pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"].startswith("private, no-store")

    image = client.get("/api/b66/quote/preview-base", params={"saved_skill_id": SAVED_ID})
    assert image.status_code == 200, image.text
    assert image.content == PNG
    assert image.headers["content-type"] == "image/png"


def test_5877_bundle_json_member_exactly_ten_mib_is_accepted(renderer):
    assert MAX_BUNDLE_JSON_BYTES == 10 * 1024 * 1024
    template = _padded_template(MAX_BUNDLE_JSON_BYTES)
    assert len(template) == MAX_BUNDLE_JSON_BYTES
    bundle = _parse(_archive(template_bytes=template, base_pdf=PDF))
    assert bundle.template["supported_scope"] == SCOPE
    assert len(bundle.template["pad"]) > 0
    assert bundle.base_pdf == PDF


def test_5877_bundle_json_member_one_byte_over_ten_mib_is_rejected(renderer):
    template = _padded_template(MAX_BUNDLE_JSON_BYTES + 1)
    with pytest.raises(B66CertifiedQuoteBundleError) as error:
        _parse(_archive(template_bytes=template, base_pdf=PDF))
    assert error.value.code == "certified_bundle_invalid"


@pytest.mark.asyncio
async def test_5877_preview_exactly_ten_mib_accepted_one_byte_over_rejected(monkeypatch):
    assert MAX_PREVIEW_BYTES == 10 * 1024 * 1024
    import app.b66_certified_preview as preview_module

    body = PNG + b"a" * (MAX_PREVIEW_BYTES - len(PNG))
    assert len(body) == MAX_PREVIEW_BYTES
    monkeypatch.setattr(
        preview_module, "CGI_PREVIEW_SHA256", hashlib.sha256(body).hexdigest()
    )
    store = B66CertifiedPreviewStore(_R2(_R2Object(body)))
    verified = await store.get_preview(
        skill_fingerprint=CGI_SKILL_FINGERPRINT,
        profile_fingerprint=CGI_PROFILE_FINGERPRINT,
    )
    assert verified is not None and len(verified) == MAX_PREVIEW_BYTES

    oversized = body + b"a"
    assert len(oversized) == MAX_PREVIEW_BYTES + 1
    monkeypatch.setattr(
        preview_module, "CGI_PREVIEW_SHA256", hashlib.sha256(oversized).hexdigest()
    )
    # 선언 크기가 상한 이내여도 실제 바이트가 상한을 넘으면 무결성 단계에서 거부된다.
    with pytest.raises(B66CertifiedPreviewError) as error:
        await B66CertifiedPreviewStore(
            _R2(_R2Object(oversized, size=MAX_PREVIEW_BYTES))
        ).get_preview(
            skill_fingerprint=CGI_SKILL_FINGERPRINT,
            profile_fingerprint=CGI_PROFILE_FINGERPRINT,
        )
    assert str(error.value) == "certified_preview_integrity_failed"


@pytest.mark.asyncio
async def test_5877_preview_declared_size_over_ten_mib_rejected_before_read(monkeypatch):
    import app.b66_certified_preview as preview_module

    body = PNG
    monkeypatch.setattr(
        preview_module, "CGI_PREVIEW_SHA256", hashlib.sha256(body).hexdigest()
    )
    obj = _R2Object(body, size=MAX_PREVIEW_BYTES + 1)
    with pytest.raises(B66CertifiedPreviewError) as error:
        await B66CertifiedPreviewStore(_R2(obj)).get_preview(
            skill_fingerprint=CGI_SKILL_FINGERPRINT,
            profile_fingerprint=CGI_PROFILE_FINGERPRINT,
        )
    assert str(error.value) == "certified_preview_invalid"
    assert obj.reads == 0


def test_5877_other_owner_never_reaches_private_bundle(renderer):
    store = B66CertifiedQuoteBundleStore(_R2(_R2Object(_archive())))
    client = _client(
        skills=_Skills(),
        bundle_store=store,
        pdf_client=_BundlePdfClient(store),
        user=USER_B,
    )
    response = client.post(
        "/api/b66/quote/pdf", json={"saved_skill_id": SAVED_ID, "render_model": _model()}
    )
    assert response.status_code == 404
