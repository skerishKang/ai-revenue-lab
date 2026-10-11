"""#3554: one synthetic B14-native 504 response fingerprint for Owner's Kira incident.

The historical response body is unavailable. Equality of the observed 547-byte
body length and this synthetic 547-byte B14 response supports attribution to
B14 error serialization but DOES NOT prove the original exception stage.
No network, paid model calls, real credentials or Production mutations.
"""
from __future__ import annotations

from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import UpstreamTimeout


def test_exact_kira_single_attempt_504_has_observed_547_byte_b14_fingerprint(monkeypatch):
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Synthetic string; not an account credential. Egress is stubbed before any IO.
    monkeypatch.setenv("PADIEM_KIRAAI_API_KEY", "synthetic-fingerprint-20261010-not-a-secret")
    outbound = []

    async def timeout_once(**kwargs):
        outbound.append((
            kwargs.get("model_id"),
            kwargs.get("upstream_model"),
            kwargs.get("platform_provider_id"),
        ))
        raise UpstreamTimeout()

    monkeypatch.setattr(platform, "call_platform_chat_completions", timeout_once)
    with TestClient(create_app()) as client:
        result = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": "kira/qwen3.8-flash-free",
                "messages": [{"role": "user", "content": "synthetic error fingerprint"}],
                "max_tokens": 3900, "stream": False,
                "business14": {
                    "allow_paid": True, "max_attempts": 1,
                    "max_retries": 0, "allow_external_fallback": False,
                },
            },
        )

    assert result.status_code == 504
    error = result.json()["error"]
    assert error["code"] == "upstream_timeout"
    assert error["attempt_count"] == 1
    assert error["fallback_used"] is False
    assert len(error["attempt_evidence"]) == 1
    assert error["attempt_evidence"][0]["error_code"] == "upstream_timeout"
    assert outbound == [
        ("kira/qwen3.8-flash-free", "qwen3.8-flash-free", "kira")
    ]
    # Historical Owner-authorized production QKR-008 request at 18:31 KST
    # returned HTTP504 with a 547-byte response. The exact length match is
    # a forensic clue, not content or root-cause attestation. If the B14
    # error serializer changes, reconcile and document before updating.
    assert len(result.content) == 547
    assert "synthetic error fingerprint" not in result.text
    assert "PADIEM_KIRAAI_API_KEY" not in result.text
