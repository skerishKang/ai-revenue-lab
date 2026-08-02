"""Tests for the catalog validator auth contract (Business 14 Alpha 1).

All tests are network-free (use httpx.MockTransport). No external network calls.

Covers:
- anonymous 200 success (checked=true)
- anonymous 401 / 403 -> authentication_required (NOT network_skipped)
- key present -> Authorization Bearer header used
- key redaction (no key leaks in error output)
- network timeout -> network_skipped
- price drift detection
- unavailable model detection
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.catalog import (
    CATALOG_MODELS,
    CATALOG_SOURCE,
    CATALOG_SOURCE_URL,
    fetch_live_models,
    validate_catalog_ids_live,
)
from app.pilot.openrouter_config import openrouter_config


@pytest.fixture(autouse=True)
def _reset_config():
    saved = {
        "api_key": openrouter_config.api_key,
        "provider_mode": openrouter_config.provider_mode,
        "base_url": openrouter_config.base_url,
    }
    openrouter_config.api_key = ""
    openrouter_config.provider_mode = "mock"
    openrouter_config.base_url = "https://openrouter.ai/api/v1"
    yield
    openrouter_config.api_key = saved["api_key"]
    openrouter_config.provider_mode = saved["provider_mode"]
    openrouter_config.base_url = saved["base_url"]


def _models_payload() -> dict:
    """Build a plausible Models API response payload covering catalog entries."""
    return {
        "data": [
            {
                "id": "openrouter/free",
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "google/gemini-2.5-flash",
                "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
            },
            {
                "id": "deepseek/deepseek-chat",
                "pricing": {"prompt": "0.0000002574", "completion": "0.0000010287"},
            },
        ]
    }


class TestCatalogAnonymous200:
    def test_anonymous_200_checked_true(self):
        def handler(request):
            assert "authorization" not in request.headers
            return httpx.Response(200, json=_models_payload())

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is True
        assert result["skipped"] is False
        assert result["reason"] == ""
        assert result["checked_at"]
        assert result["available"] or result["unavailable"]

    def test_fetch_live_models_anonymous_success(self):
        def handler(request):
            assert "authorization" not in request.headers
            assert request.url == "https://openrouter.ai/api/v1/models"
            return httpx.Response(200, json=_models_payload())

        transport = httpx.MockTransport(handler)
        result = fetch_live_models(transport=transport)
        assert result["ok"] is True
        assert "models_by_id" in result
        assert "google/gemini-2.5-flash" in result["models_by_id"]


class TestCatalogAnonymous401403:
    @pytest.mark.parametrize("status", [401, 403])
    def test_anonymous_401_403_authentication_required(self, status):
        def handler(request):
            return httpx.Response(status, json={"error": {"message": "unauthorized"}})

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is False
        assert result["skipped"] is True
        assert result["reason"] == "authentication_required"
        # 401/403 must NOT be expressed as network_skipped
        assert "network_skipped" not in result["reason"]

    @pytest.mark.parametrize("status", [401, 403])
    def test_fetch_live_models_401_403(self, status):
        def handler(request):
            return httpx.Response(status, json={"error": {"message": "denied"}})

        transport = httpx.MockTransport(handler)
        result = fetch_live_models(transport=transport)
        assert result["ok"] is False
        assert result["reason"] == "authentication_required"


class TestCatalogKeyPresent:
    def test_key_present_authorization_header(self):
        openrouter_config.api_key = "sk-or-v1-catalog-test-secret-1234567890"

        def handler(request):
            auth = request.headers.get("authorization", "")
            assert auth.startswith("Bearer sk-or-v1-catalog-test-secret-")
            assert "sk-or-v1-catalog-test-secret-1234567890" in auth
            return httpx.Response(200, json=_models_payload())

        transport = httpx.MockTransport(handler)
        result = fetch_live_models(transport=transport)
        assert result["ok"] is True

    def test_key_not_in_result_or_reason(self):
        secret = "sk-or-v1-super-secret-catalog-key-9988776655"
        openrouter_config.api_key = secret

        def handler(request):
            return httpx.Response(401, json={"error": {"message": "bad key"}})

        transport = httpx.MockTransport(handler)
        result = fetch_live_models(transport=transport)
        assert secret not in json.dumps(result)

    def test_validate_with_key_uses_bearer(self):
        openrouter_config.api_key = "sk-or-v1-catalog-bearer-test-abcdef"
        captured = {}

        def handler(request):
            captured["auth"] = request.headers.get("authorization", "")
            return httpx.Response(200, json=_models_payload())

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is True
        assert captured["auth"] == f"Bearer {openrouter_config.api_key}"
        assert "sk-or-v1-catalog-bearer-test-abcdef" not in json.dumps(result)


class TestCatalogNetworkSkipped:
    def test_network_timeout_network_skipped(self):
        def handler(request):
            raise httpx.ConnectTimeout("timed out")

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is False
        assert result["skipped"] is True
        assert result["reason"].startswith("network_skipped:")
        assert "authentication_required" not in result["reason"]

    def test_request_error_network_skipped(self):
        def handler(request):
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(handler)
        result = fetch_live_models(transport=transport)
        assert result["ok"] is False
        assert result["reason"].startswith("network_skipped:")


class TestCatalogPriceDrift:
    def test_price_drift_detected(self):
        payload = _models_payload()
        # gemini snapshot is 0.30/2.50; live is 0.40/3.00 -> drift
        payload["data"][1]["pricing"] = {"prompt": "0.0000004", "completion": "0.000003"}

        def handler(request):
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is True
        drift_models = {d["model_id"] for d in result["price_drift"]}
        assert "google/gemini-2.5-flash" in drift_models

    def test_no_drift_when_prices_match(self):
        payload = _models_payload()
        payload["data"][1]["pricing"] = {"prompt": "0.0000003", "completion": "0.0000025"}

        def handler(request):
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is True
        assert all(d["model_id"] != "google/gemini-2.5-flash" for d in result["price_drift"])


class TestCatalogUnavailableModel:
    def test_unavailable_model_detected(self):
        payload = {
            "data": [
                {"id": "openrouter/free", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "google/gemini-2.5-flash", "pricing": {"prompt": "0.0000003", "completion": "0.0000025"}},
            ]
        }

        def handler(request):
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        result = validate_catalog_ids_live(transport=transport)
        assert result["checked"] is True
        assert "deepseek/deepseek-chat" in result["unavailable"]


class TestCatalogSourceMetadata:
    def test_source_metadata_present(self):
        assert CATALOG_SOURCE == "openrouter_models_api"
        assert CATALOG_SOURCE_URL == "https://openrouter.ai/api/v1/models"
        assert len(CATALOG_MODELS) >= 5
