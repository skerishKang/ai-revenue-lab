from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(CLIENT_ROOT))

from padiem_ai_engine_client import (  # noqa: E402
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_ORCHESTRATE_CANCEL_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_RESUME_PATH,
    EngineTransportResponse,
    ORCHESTRATION_FIELD_PARITY,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)


AGENT = {
    "id": "agent:padiem:chat@1",
    "title": "Padiem Chat",
    "description": "test",
    "system_instruction": "test",
    "task_type": "general",
    "optimize_for": "balanced",
    "max_tokens": 256,
}
MESSAGES = [{"role": "user", "content": "hello"}]
CREDENTIAL = "c" * 48


class FakeTransport:
    def __init__(self, response: EngineTransportResponse):
        self.response = response
        self.calls = []

    async def request(self, *, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return self.response


def _client(transport: FakeTransport) -> PadiemAiEngineClient:
    return PadiemAiEngineClient(
        transport=transport,
        app_id="b62",
        caller_id="padiem-chat-b62",
        credential=CREDENTIAL,
    )


@pytest.mark.asyncio
async def test_orchestrate_injects_identity_and_uses_fixed_internal_origin():
    transport = FakeTransport(
        EngineTransportResponse(
            status=200,
            body=json.dumps({"ok": True, "orchestration": {"events": []}}).encode(),
        )
    )
    client = _client(transport)
    result = await client.orchestrate(
        {
            "agent": AGENT,
            "messages": MESSAGES,
            "subject_id": "subject_1",
            "execution_context": {"trace_id": "trace_1", "timeout_seconds": 20},
        }
    )
    assert result == {"events": []}
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}"
    assert call["method"] == "POST"
    assert call["headers"]["X-Padiem-Engine-Caller"] == "padiem-chat-b62"
    assert call["headers"]["X-Padiem-Engine-Credential"] == CREDENTIAL
    payload = json.loads(call["body"])
    assert payload["app_id"] == "b62"
    assert payload["subject_id"] == "subject_1"
    assert "credential" not in payload


@pytest.mark.asyncio
async def test_authority_bearing_fields_fail_closed_before_transport():
    transport = FakeTransport(
        EngineTransportResponse(status=200, body=b'{"ok":true,"orchestration":{}}')
    )
    client = _client(transport)
    with pytest.raises(PadiemAiEngineClientError) as raised:
        await client.orchestrate(
            {
                "agent": AGENT,
                "messages": MESSAGES,
                "tool_authorization": {"scope": ["write"]},
            }
        )
    assert raised.value.code == "unsupported_orchestration_field"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_resume_requires_exact_trusted_decision_shape():
    transport = FakeTransport(
        EngineTransportResponse(
            status=200,
            body=json.dumps({"ok": True, "orchestration": {"events": [{"kind": "run_resumed"}]}}).encode(),
        )
    )
    client = _client(transport)
    result = await client.resume_orchestration(
        {
            "agent": AGENT,
            "messages": MESSAGES,
            "continuation_ref": "cont_abcdefgh12345678",
            "decision": {
                "decision_id": "decision_1",
                "pause_id": "pause_1",
                "outcome": "approved",
                "authority_ref": "b62_session_subject_1",
                "evidence_ref": "b62_decision_1",
                "decided_at": "2026-09-03T06:00:00+09:00",
            },
        }
    )
    assert result["events"][0]["kind"] == "run_resumed"
    call = transport.calls[0]
    assert call["url"] == f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_RESUME_PATH}"
    payload = json.loads(call["body"])
    assert payload["decision"]["pause_id"] == "pause_1"

    bad_transport = FakeTransport(transport.response)
    bad_client = _client(bad_transport)
    with pytest.raises(PadiemAiEngineClientError):
        await bad_client.resume_orchestration(
            {
                "agent": AGENT,
                "messages": MESSAGES,
                "continuation_ref": "cont_abcdefgh12345678",
                "decision": {"pause_id": "pause_1", "outcome": "approved"},
            }
        )
    assert bad_transport.calls == []


@pytest.mark.asyncio
async def test_cancel_is_continuation_only_and_no_browser_authority_fields():
    transport = FakeTransport(
        EngineTransportResponse(status=200, body=b'{"ok":true,"cancelled":true}')
    )
    client = _client(transport)
    result = await client.cancel_orchestration_pause(
        {"continuation_ref": "cont_abcdefgh12345678", "reason": "user_cancelled"}
    )
    assert result["ok"] is True
    call = transport.calls[0]
    assert call["url"] == f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_CANCEL_PATH}"
    payload = json.loads(call["body"])
    assert payload == {
        "app_id": "b62",
        "continuation_ref": "cont_abcdefgh12345678",
        "reason": "user_cancelled",
    }


@pytest.mark.asyncio
async def test_safe_engine_error_is_projected_without_transport_details():
    transport = FakeTransport(
        EngineTransportResponse(
            status=503,
            body=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "approval_verification_unavailable",
                        "message": "Approval decision verification is unavailable.",
                        "retryable": False,
                        "metadata": None,
                    },
                }
            ).encode(),
        )
    )
    client = _client(transport)
    with pytest.raises(PadiemAiEngineClientError) as raised:
        await client.orchestrate({"agent": AGENT, "messages": MESSAGES})
    assert raised.value.code == "approval_verification_unavailable"
    assert raised.value.status == 503
    assert raised.value.retryable is False


def test_python_client_field_parity_matches_js_contract_states():
    assert ORCHESTRATION_FIELD_PARITY["tool_authorization"] == "EXPLICITLY_DEFERRED_AND_REJECTED"
    assert ORCHESTRATION_FIELD_PARITY["continuation_ref"] == "RESUME_ONLY_SUPPORTED_AND_MAPPED"
    assert ORCHESTRATION_FIELD_PARITY["decision"] == "RESUME_ONLY_SUPPORTED_AND_MAPPED"
    assert ORCHESTRATION_FIELD_PARITY["app_id"] == "CLIENT_OWNED_AND_INJECTED"


def test_constructor_rejects_short_credential_and_untrusted_transport():
    transport = FakeTransport(EngineTransportResponse(status=200, body=b'{"ok":true}'))
    with pytest.raises(PadiemAiEngineClientError):
        PadiemAiEngineClient(
            transport=transport,
            app_id="b62",
            caller_id="padiem-chat-b62",
            credential="short",
        )
    with pytest.raises(PadiemAiEngineClientError):
        PadiemAiEngineClient(
            transport=object(),
            app_id="b62",
            caller_id="padiem-chat-b62",
            credential=CREDENTIAL,
        )
