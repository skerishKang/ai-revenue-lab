"""#5224: the platform-credential execution lanes require a proven caller.

B14 is publicly routable. The catalog lane spends the platform's own Provider
credentials, so an anonymous or wrongly-signed external request must be
refused before any credential is resolved and before any Provider request is
built. These tests are the load-bearing regression for that boundary.

No network, no paid model call, no real credential, no Production mutation.
"""
from __future__ import annotations

import json
import time

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.service_proof import (
    MAX_PROOF_SKEW_SECONDS,
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    SERVICE_PROOF_BINDING,
    compute_service_proof,
)

MODEL_ID = "kira/qwen3.8-flash-free"
SECRET = "b14-test-service-proof-secret-0123456789abcdef"


def test_shared_contract_vector_is_stable():
    """The proof construction is one shared contract, not two implementations.

    The B62 Chat suite asserts the same vector, so a change in either
    implementation is caught instead of silently breaking the other side.
    """
    import hashlib
    import hmac

    contract_secret = "b14-contract-vector-secret-0123456789abcdef"
    contract_timestamp = "1700000000"
    contract_body = b'{"model":"x"}'
    expected = hmac.new(
        contract_secret.encode("utf-8"),
        contract_timestamp.encode("ascii") + b"." + contract_body,
        hashlib.sha256,
    ).hexdigest()
    assert expected == (
        "b6a1234c77da135333d5a3d01b87ff0a1624c9a1359fef7a25542ea4aba2c1a5"
    )
    assert compute_service_proof(
        contract_secret, contract_timestamp, contract_body,
    ) == expected


def _live_runtime(monkeypatch):
    """Put the runtime in the live mode the Production Worker actually serves."""
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Synthetic string; not an account credential. Egress is stubbed below.
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_09", "synthetic-5224-not-a-secret")


def _stub_provider(monkeypatch):
    """Record every Provider dispatch attempt instead of making one."""
    outbound: list[tuple] = []

    async def _record(**kwargs):
        outbound.append((kwargs.get("model_id"), kwargs.get("platform_provider_id")))
        return {
            "id": "chatcmpl-synthetic",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "synthetic"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(platform, "call_platform_chat_completions", _record)
    return outbound


def _chat_payload(model_id: str = MODEL_ID) -> dict:
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "synthetic"}],
        "max_tokens": 32,
        "stream": False,
        "business14": {
            "allow_paid": True,
            "max_attempts": 1,
            "max_retries": 0,
            "allow_external_fallback": False,
        },
    }


def _body(payload: dict) -> bytes:
    """Serialize exactly the bytes the application will verify."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _proof_headers(
    body: bytes, *, secret: str = SECRET, timestamp: str | None = None
) -> dict[str, str]:
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    return {
        PROOF_HEADER: compute_service_proof(secret, stamp, body),
        PROOF_TIME_HEADER: stamp,
    }


def _post(client, path: str, payload: dict, *, proof: dict[str, str] | None = None):
    body = _body(payload)
    headers = {"Content-Type": "application/json"}
    if proof is not None:
        headers.update(proof)
    return client.post(path, content=body, headers=headers)


@pytest.mark.no_b14_service_proof
def test_anonymous_catalog_dispatch_is_refused_with_zero_provider_dispatch(monkeypatch):
    """An anonymous external caller must not reach the platform credential."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)

    with TestClient(create_app()) as client:
        result = _post(client, "/api/pilot/v1/chat/completions", _chat_payload())

    assert result.status_code == 401
    error = result.json()["error"]
    assert error["code"] == "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_wrongly_signed_catalog_dispatch_is_refused_with_zero_provider_dispatch(monkeypatch):
    """A forged or wrong-secret proof must not reach the platform credential."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/pilot/v1/chat/completions",
            _chat_payload(),
            proof=_proof_headers(
                _body(_chat_payload()),
                secret="a-completely-different-proof-secret-000",
            ),
        )

    assert result.status_code == 401
    assert result.json()["error"]["code"] == "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_stale_proof_timestamp_is_refused_with_zero_provider_dispatch(monkeypatch):
    """A captured proof must not stay usable outside the skew window."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)
    stale = str(int(time.time()) - (MAX_PROOF_SKEW_SECONDS + 120))

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/pilot/v1/chat/completions",
            _chat_payload(),
            proof=_proof_headers(_body(_chat_payload()), timestamp=stale),
        )

    assert result.status_code == 401
    assert result.json()["error"]["code"] == "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_proof_for_a_different_body_is_refused_with_zero_provider_dispatch(monkeypatch):
    """The proof is body-bound, so it cannot authorize another request."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/pilot/v1/chat/completions",
            _chat_payload(),
            proof=_proof_headers(b'{"model":"someone-elses-request"}'),
        )

    assert result.status_code == 401
    assert result.json()["error"]["code"] == "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_unconfigured_proof_secret_fails_closed(monkeypatch):
    """Without the deployment secret the lane refuses instead of dispatching."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)
    monkeypatch.delenv(SERVICE_PROOF_BINDING, raising=False)

    with TestClient(create_app()) as client:
        result = _post(client, "/api/pilot/v1/chat/completions", _chat_payload())

    assert result.status_code == 503
    assert result.json()["error"]["code"] == "b14_service_proof_unconfigured"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_byok_lane_is_not_blocked_by_the_platform_caller_proof(monkeypatch):
    """The BYOK contract stays separate: the caller owns that credential."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)
    payload = _chat_payload("synthetic/unregistered-model")
    body = _body(payload)

    with TestClient(create_app()) as client:
        result = client.post(
            "/api/pilot/v1/chat/completions",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Business14-Provider-Key": "caller-owned-synthetic-key",
            },
        )

    # The BYOK lane answers on its own contract. It never reaches the
    # platform credential and never needs the server-to-server proof.
    assert result.status_code != 401
    assert result.json().get("error", {}).get("code") != "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_public_read_only_surfaces_stay_open_without_a_proof(monkeypatch):
    """The public pages and the read-only model authority are not blocked."""
    _live_runtime(monkeypatch)

    with TestClient(create_app()) as client:
        for path in (
            "/health",
            "/api/pilot/health",
            "/api/pilot/models",
            "/api/pilot/provider-readiness",
            "/workspace",
        ):
            result = client.get(path)
            assert result.status_code == 200, path


@pytest.mark.no_b14_service_proof
def test_b66_extraction_lane_is_refused_without_a_proof(monkeypatch):
    """The B66 extraction lane spends the platform credential too."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/b66/v1/quote/extract-image",
            {"name": "quote.png", "media_type": "image/png", "base64": "aGk="},
        )

    assert result.status_code == 401
    assert result.json()["error"]["code"] == "b14_service_proof_required"
    assert outbound == []


@pytest.mark.no_b14_service_proof
def test_stream_preview_lane_is_refused_without_a_proof(monkeypatch):
    """The streaming preview lane is a platform-credential lane as well."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/pilot/v1/chat/completions/stream-preview",
            _chat_payload(),
        )

    assert result.status_code == 401
    assert result.json()["error"]["code"] == "b14_service_proof_required"
    assert outbound == []


def test_proven_caller_still_dispatches(monkeypatch):
    """A proven server-to-server caller keeps the existing execution contract."""
    _live_runtime(monkeypatch)
    outbound = _stub_provider(monkeypatch)
    payload = _chat_payload()
    body = _body(payload)

    with TestClient(create_app()) as client:
        result = _post(
            client,
            "/api/pilot/v1/chat/completions",
            payload,
            proof=_proof_headers(body),
        )

    assert result.status_code == 200
    assert outbound == [(MODEL_ID, "kira")]

