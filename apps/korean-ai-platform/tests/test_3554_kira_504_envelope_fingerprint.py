"""#3554: one synthetic B14-native 504 response fingerprint for the Owner incident.

The historical response body is unavailable. Equality of the observed body
length and this synthetic response's length supports attribution to B14 error
serialization but DOES NOT prove the original exception stage.
No network, paid model calls, real credentials or Production mutations.

#7241 3a: the subject model, its upstream name and the credential binding are
read from the effective registry. Every expectation is expressed against the
row the route actually selected, so this suite writes no deployment value.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.errors import UpstreamTimeout

from _pilot_lane_paths import chat_surface
from _registry_values import a_dispatchable_row, provider_of, provider_row, requires_owner_document

#: The gateway's own chat surface, selected from the mounted router.
CHAT_PATH = chat_surface()

#: The subject row: a real identity the adapter would dispatch on one attempt.
#: Which rows are live is an owner decision, so the case is skipped on a host
#: reading the placeholder fixture.
ROW = a_dispatchable_row()

if ROW is not None:
    #: The public id, its upstream name and its Provider's binding NAME.
    MODEL_ID = ROW["id"]
    UPSTREAM_MODEL = ROW["upstream_model"]
    PROVIDER_ID = provider_of(MODEL_ID)
    BINDING = provider_row(PROVIDER_ID)["credential_binding_name"]
else:  # pragma: no cover - placeholder document; the case is skipped below
    MODEL_ID = UPSTREAM_MODEL = PROVIDER_ID = BINDING = ""

#: The envelope length the incident reconciliation settled on (2026-10-30, PR-F).
#: A forensic clue about the serializer, not a content or root-cause attestation;
#: reconcile and document before changing it when the serializer moves.
OBSERVED_ENVELOPE_BYTES = 518

pytestmark = requires_owner_document


def test_exact_single_attempt_504_has_observed_b14_fingerprint(monkeypatch):
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Synthetic string under the row's own binding name; not an account
    # credential. Egress is stubbed before any IO.
    monkeypatch.setenv(BINDING, "synthetic-fingerprint-not-a-secret")
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
            CHAT_PATH,
            json={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": "synthetic error fingerprint"}],
                "max_tokens": 3900, "stream": False,
                "business14": {
                    "max_retries": 0,
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
    assert outbound == [(MODEL_ID, UPSTREAM_MODEL, PROVIDER_ID)]
    # The historical Owner-authorized production request returned HTTP 504 and
    # this is the reconciled envelope length for that serializer (see above).
    assert len(result.content) == OBSERVED_ENVELOPE_BYTES
    assert "synthetic error fingerprint" not in result.text
    assert BINDING not in result.text
