"""B66 live image extraction endpoint contracts (#3249)."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.factory import create_app
from app import b66_quote_endpoint as endpoint
from app.pilot import gateway as pilot_gateway

ROOT = Path(__file__).resolve().parents[3]
AUTHORITY_PATH = ROOT / "apps" / "b66-quote-adapter" / "app" / "extraction_routing.py"

spec = importlib.util.spec_from_file_location("b66_extraction_routing_test", AUTHORITY_PATH)
assert spec is not None and spec.loader is not None
AUTHORITY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUTHORITY)

TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-b66"
TINY_B64 = base64.b64encode(TINY_PNG).decode("ascii")


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
    assert sentinel not in response.text


def test_route_source_owns_no_browser_provider_or_secret_surface():
    source = Path(endpoint.__file__).read_text(encoding="utf-8")
    assert "PADIEM_KILO_API_KEY" not in source
    assert "Authorization" not in source
    assert "api_key" not in source.lower()
    assert "build_image_extraction_request" in source
    assert "normalize_model_output" in source
    assert "pilot_gateway._validate_body" in source
    assert "pilot_gateway._handle_alpha_chat" in source

def test_deploy_pipeline_stages_the_single_canonical_authority_inside_app_package():
    deploy = (
        ROOT / "apps" / "korean-ai-platform" / "deploy.sh"
    ).read_text(encoding="utf-8")
    assert 'B66_AUTHORITY_SOURCE="../b66-quote-adapter/app/extraction_routing.py"' in deploy
    assert 'B66_STAGED_MODULE="app/b66_extraction_routing.py"' in deploy
    assert 'cp "${B66_AUTHORITY_SOURCE}" "${B66_STAGED_MODULE}"' in deploy
    assert "B66_EXTRACTION_AUTHORITY_STAGED=YES" in deploy

    endpoint_source = Path(endpoint.__file__).read_text(encoding="utf-8")
    assert 'import_module("app.b66_extraction_routing")' in endpoint_source

