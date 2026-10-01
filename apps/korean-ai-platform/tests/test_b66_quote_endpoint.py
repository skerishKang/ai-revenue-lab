"""B66 live image extraction endpoint contracts (#3249)."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import DocumentParserAuthorityUnavailable
from padiem_ai_core.document_semantics import DocumentNormalizationError
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.factory import create_app
from app import b66_quote_endpoint as endpoint
from app.pilot import gateway as pilot_gateway

ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_PATH = ROOT / "apps" / "b66-quote-adapter" / "app" / "extraction_routing.py"
INTAKE_PATH = ROOT / "apps" / "b66-quote-adapter" / "app" / "file_intake.py"

spec = importlib.util.spec_from_file_location("b66_extraction_routing_test", AUTHORITY_PATH)
assert spec is not None and spec.loader is not None
AUTHORITY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUTHORITY)

intake_spec = importlib.util.spec_from_file_location("b66_file_intake_test", INTAKE_PATH)
assert intake_spec is not None and intake_spec.loader is not None
FILE_INTAKE = importlib.util.module_from_spec(intake_spec)
intake_spec.loader.exec_module(FILE_INTAKE)

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-b66"
TINY_B64 = base64.b64encode(TINY_PNG).decode("ascii")
TINY_PDF = b"%PDF-1.7\nsynthetic-b66-native"
TINY_PDF_B64 = base64.b64encode(TINY_PDF).decode("ascii")


def _payload(**overrides):
    value = {
        "name": "quotation.png",
        "media_type": "image/png",
        "base64": TINY_B64,
    }
    value.update(overrides)
    return value


def _model_answer():
    return {
        "sender": {
            "company": "주식회사 테스트상사",
            "rep": None,
            "bizNo": None,
            "address": None,
            "phone": None,
            "email": None,
        },
        "recipient": {
            "company": "주식회사 샘플산업",
            "person": None,
            "address": None,
            "email": None,
        },
        "quote": {"quoteNo": "Q-2026-3002", "issueDate": None, "validDays": 30},
        "items": [{"name": "스테인리스 배관 40x40", "qty": 12, "unitPrice": 9800}],
        "tax": {"mode": "EXCLUSIVE"},
        "memo": None,
        "evidence": [{"field": "quote.quoteNo", "snippet": "Q-2026-3002"}],
        "warnings": [],
    }


def _ok_upstream(content):
    return JSONResponse(
        {
            "id": "synthetic",
            "object": "chat.completion",
            "model": "stealth/space-bunny-alpha",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "business14": {
                "mode": "live",
                "provider_mode": "live",
                "route_mode": "manual",
                "attempt_count": 1,
                "fallback_used": False,
            },
        }
    )


def test_image_route_reuses_canonical_builder_and_server_validator(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    captured = {}

    async def fake_handle(request_id, body):
        captured["request_id"] = request_id
        captured["body"] = body
        return _ok_upstream(json.dumps(_model_answer(), ensure_ascii=False))

    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)

    with TestClient(create_app()) as client:
        response = client.post("/api/b66/v1/quote/extract-image", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    result = body["result"]
    assert result["source"] == {
        "kind": "image",
        "filename": "quotation.png",
        "media_type": "image/png",
        "byte_size": len(TINY_PNG),
    }
    assert result["extraction"]["source"] == {
        "kind": "image",
        "filename": "quotation.png",
    }
    assert result["extraction"]["quote"]["quoteNo"] == "Q-2026-3002"
    assert result["extraction"]["items"][0]["unitPrice"] == 9800
    assert result["quotecore_authority"] is True

    request_body = captured["body"]
    assert request_body["model"] == AUTHORITY.B66_GOVERNED_ROUTE
    assert request_body["business14"]["required_capabilities"] == ["image"]
    assert request_body["business14"]["allow_external_fallback"] is False
    assert request_body["business14"]["max_attempts"] == 1
    content = request_body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_model_source_spoof_is_rejected_without_raw_content(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    raw = _model_answer()
    raw["source"] = {"kind": "image", "filename": "evil.png"}
    sentinel = "PRIVATE_MODEL_SENTINEL"

    async def fake_handle(request_id, body):
        raw["warnings"] = [sentinel]
        return _ok_upstream(json.dumps(raw, ensure_ascii=False))

    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)
    with TestClient(create_app()) as client:
        response = client.post("/api/b66/v1/quote/extract-image", json=_payload())

    assert response.status_code == 502
    text = response.text
    assert "model_output_source_provenance_mismatch" in text
    assert sentinel not in text
    assert "evil.png" not in text


def test_non_image_and_malformed_payloads_fail_before_upstream(monkeypatch):
    calls = []

    async def fake_handle(request_id, body):
        calls.append(body)
        raise AssertionError("upstream must not run")

    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)

    with TestClient(create_app()) as client:
        document = client.post(
            "/api/b66/v1/quote/extract-image",
            json=_payload(name="quote.pdf", media_type="application/pdf"),
        )
        bad64 = client.post(
            "/api/b66/v1/quote/extract-image",
            json=_payload(base64="!!!"),
        )
        extra = client.post(
            "/api/b66/v1/quote/extract-image",
            json={**_payload(), "model": "forbidden"},
        )

    assert document.status_code == 422
    assert document.json()["error"]["code"] == "image_only_mvp"
    assert bad64.status_code == 422
    assert bad64.json()["error"]["code"] == "invalid_base64"
    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "unsupported_fields"
    assert calls == []


def test_upstream_error_is_collapsed_to_product_safe_code(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    sentinel = "PRIVATE_UPSTREAM_DETAIL"

    async def fake_handle(request_id, body):
        return JSONResponse(
            {"error": {"code": "upstream_timeout", "message": sentinel}},
            status_code=504,
        )

    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)
    with TestClient(create_app()) as client:
        response = client.post("/api/b66/v1/quote/extract-image", json=_payload())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "b14_upstream_unavailable"
    assert response.headers["cache-control"] == "no-store"
    assert sentinel not in response.text


def test_native_document_route_reuses_intake_parser_and_text_extraction(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    monkeypatch.setattr(endpoint, "_intake_authority", lambda: FILE_INTAKE)
    parser_calls = []
    captured = {}

    def fake_parser(*, name, media_type, payload):
        parser_calls.append((name, media_type, payload))
        return NormalizedDocument(
            name=name,
            media_type=media_type,
            text="견적번호 Q-2026-3002\n스테인리스 배관 40x40 12 9800",
            byte_size=len(payload),
            source_kind="binary",
        )

    async def fake_handle(request_id, body):
        captured["request_id"] = request_id
        captured["body"] = body
        return _ok_upstream(json.dumps(_model_answer(), ensure_ascii=False))

    monkeypatch.setattr(FILE_INTAKE, "parse_binary_document_via_authority", fake_parser)
    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/b66/v1/quote/extract-document",
            json={
                "name": "quotation.pdf",
                "media_type": "application/pdf",
                "base64": TINY_PDF_B64,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert parser_calls == [("quotation.pdf", "application/pdf", TINY_PDF)]
    assert body["result"]["source"] == {
        "kind": "native_document",
        "filename": "quotation.pdf",
        "media_type": "application/pdf",
        "byte_size": len(TINY_PDF),
    }
    assert body["result"]["extraction"]["source"] == {
        "kind": "native_document",
        "filename": "quotation.pdf",
    }
    assert body["result"]["extraction"]["quote"]["quoteNo"] == "Q-2026-3002"
    request_body = captured["body"]
    assert request_body["model"] == AUTHORITY.B66_GOVERNED_ROUTE
    assert request_body["business14"]["allow_external_fallback"] is False
    assert request_body["business14"]["max_attempts"] == 1
    assert isinstance(request_body["messages"][0]["content"], str)
    assert "견적번호 Q-2026-3002" in request_body["messages"][0]["content"]


def test_native_document_route_fails_closed_before_model_without_parser_authority(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    monkeypatch.setattr(endpoint, "_intake_authority", lambda: FILE_INTAKE)
    upstream_calls = []

    def unavailable_parser(**kwargs):
        raise DocumentParserAuthorityUnavailable()

    async def fake_handle(request_id, body):
        upstream_calls.append(body)
        raise AssertionError("model must not run without parser authority")

    monkeypatch.setattr(FILE_INTAKE, "parse_binary_document_via_authority", unavailable_parser)
    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/b66/v1/quote/extract-document",
            json={
                "name": "quotation.pdf",
                "media_type": "application/pdf",
                "base64": TINY_PDF_B64,
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "parser_authority_unavailable"
    assert response.headers["cache-control"] == "no-store"
    assert upstream_calls == []


def test_scanned_pdf_stays_manual_when_native_text_is_absent(monkeypatch):
    monkeypatch.setattr(endpoint, "_authority", lambda: AUTHORITY)
    monkeypatch.setattr(endpoint, "_intake_authority", lambda: FILE_INTAKE)
    upstream_calls = []

    def scanned_parser(**kwargs):
        raise DocumentNormalizationError(
            "pdf_empty_text",
            "PDF contains no extractable text; OCR is not enabled.",
        )

    async def fake_handle(request_id, body):
        upstream_calls.append(body)
        raise AssertionError("scanned PDF must not enter text model route")

    monkeypatch.setattr(FILE_INTAKE, "parse_binary_document_via_authority", scanned_parser)
    monkeypatch.setattr(pilot_gateway, "_handle_alpha_chat", fake_handle)

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/b66/v1/quote/extract-document",
            json={
                "name": "quotation.pdf",
                "media_type": "application/pdf",
                "base64": TINY_PDF_B64,
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "scanned_pdf_manual_review_required"
    assert upstream_calls == []


def test_route_source_owns_no_browser_provider_or_secret_surface():
    source = Path(endpoint.__file__).read_text(encoding="utf-8")
    assert "PADIEM_KILO_API_KEY" not in source
    assert "Authorization" not in source
    assert "api_key" not in source.lower()
    assert "build_image_extraction_request" in source
    assert "build_text_extraction_request" in source
    assert "normalize_model_output" in source
    assert "pilot_gateway._validate_body" in source
    assert "pilot_gateway._handle_alpha_chat" in source

def test_deploy_pipeline_stages_canonical_b66_authorities_inside_app_package():
    deploy = (
        ROOT / "apps" / "korean-ai-platform" / "deploy.sh"
    ).read_text(encoding="utf-8")
    assert 'B66_EXTRACTION_SOURCE="../b66-quote-adapter/app/extraction_routing.py"' in deploy
    assert 'B66_EXTRACTION_STAGED="app/b66_extraction_routing.py"' in deploy
    assert 'B66_INTAKE_SOURCE="../b66-quote-adapter/app/file_intake.py"' in deploy
    assert 'B66_INTAKE_STAGED="app/b66_file_intake.py"' in deploy
    assert 'cp "${B66_EXTRACTION_SOURCE}" "${B66_EXTRACTION_STAGED}"' in deploy
    assert 'cp "${B66_INTAKE_SOURCE}" "${B66_INTAKE_STAGED}"' in deploy
    assert "B66_EXTRACTION_AUTHORITY_STAGED=YES" in deploy
    assert "B66_FILE_INTAKE_AUTHORITY_STAGED=YES" in deploy

    endpoint_source = Path(endpoint.__file__).read_text(encoding="utf-8")
    assert 'import_module("app.b66_extraction_routing")' in endpoint_source
    assert 'import_module("app.b66_file_intake")' in endpoint_source

