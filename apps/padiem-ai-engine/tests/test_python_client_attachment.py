"""Canonical image attachment admission surface for the Python Engine client (#3210).

Proves the client leg of the A6 server-only live image canary seam:

  ENGINE_ATTACHMENT_CLIENT_FIXED_ROUTE    = PASS
  ENGINE_ATTACHMENT_CALLER_HEADERS_REUSED = PASS
  APP_ID_CLIENT_OWNED                     = PASS
  SERVER_SESSION_ID_REQUIRED              = PASS
  TENANT_OVERRIDE_REJECTED                = PASS
  SUBJECT_OVERRIDE_REJECTED               = PASS
  ATTACHMENT_REF_OVERRIDE_REJECTED        = PASS
  LOCATOR_URL_PATH_OVERRIDE_REJECTED      = PASS
  MALFORMED_RESPONSE_FAIL_CLOSED          = PASS
  NON_2XX_BOUNDED_ERROR                   = PASS
  ENGINE_CALLER_SECRET_OUTPUT             = 0
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(CLIENT_ROOT))

from padiem_ai_engine_client import (  # noqa: E402
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    MAX_ATTACHMENT_IMAGE_BASE64_CHARS,
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)
from app.attachment_byte_store import MAX_STORED_IMAGE_BASE64_CHARS  # noqa: E402

CALLER_ID = "b54-engine-caller-a6"
CREDENTIAL = "attachment-client-credential-0123456789abcdef"
APP_ID = "b54-padiem-claw"
SESSION_ID = "sess_subject:b54-padiem-claw:usr_canary"
ATTACHMENT_REF = "att_" + "Ab3_-9" * 4
IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
EXPIRES_AT = "2026-09-30T03:00:00+00:00"
PROJECTION = {
    "attachment_ref": ATTACHMENT_REF,
    "media_type": "image/png",
    "byte_size": 68,
    "expires_at": EXPIRES_AT,
}


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
        app_id=APP_ID,
        caller_id=CALLER_ID,
        credential=CREDENTIAL,
    )


def _transport(attachment: dict | None = None) -> FakeTransport:
    body = {"ok": True, "attachment": dict(PROJECTION) if attachment is None else attachment}
    return FakeTransport(EngineTransportResponse(status=200, body=json.dumps(body).encode()))


def _request(**overrides) -> dict:
    request = {
        "session_id": SESSION_ID,
        "media_type": "image/png",
        "image_base64": IMAGE_B64,
    }
    request.update(overrides)
    return request


@pytest.mark.asyncio
async def test_attachment_admission_uses_fixed_route_and_reuses_caller_headers():
    transport = _transport()
    client = _client(transport)
    result = await client.admit_image_attachment(_request(trace_id="trace_a6_0001"))

    assert result == PROJECTION
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}"
    assert call["url"] == f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/multimodal/attachments"
    assert call["method"] == "POST"
    assert call["headers"] == {
        "Content-Type": "application/json",
        "X-Padiem-Engine-Caller": CALLER_ID,
        "X-Padiem-Engine-Credential": CREDENTIAL,
    }
    payload = json.loads(call["body"])
    assert payload["app_id"] == APP_ID
    assert payload["session_id"] == SESSION_ID
    assert payload["media_type"] == "image/png"
    assert payload["image_base64"] == IMAGE_B64
    assert payload["trace_id"] == "trace_a6_0001"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert CREDENTIAL not in serialized
    assert "credential" not in serialized.lower()


@pytest.mark.asyncio
async def test_app_id_is_client_owned_and_never_caller_supplied():
    transport = _transport()
    await _client(transport).admit_image_attachment(_request())
    assert json.loads(transport.calls[0]["body"])["app_id"] == APP_ID

    bad = _transport()
    with pytest.raises(PadiemAiEngineClientError):
        await _client(bad).admit_image_attachment(_request(app_id="browser-supplied"))
    assert bad.calls == []


@pytest.mark.asyncio
async def test_server_session_id_is_required_and_bounded():
    for overrides in (
        {"session_id": None},
        {"session_id": ""},
        {"session_id": "   "},
        {"session_id": "sess bad"},
        {"session_id": "x" * 129},
        {"session_id": 7},
    ):
        bad = _transport()
        with pytest.raises(PadiemAiEngineClientError):
            await _client(bad).admit_image_attachment(_request(**overrides))
        assert bad.calls == []

    bad = _transport()
    request = _request()
    request.pop("session_id")
    with pytest.raises(PadiemAiEngineClientError):
        await _client(bad).admit_image_attachment(request)
    assert bad.calls == []


@pytest.mark.asyncio
async def test_tenant_and_subject_overrides_are_rejected():
    for key in ("tenant_id", "subject_id"):
        bad = _transport()
        with pytest.raises(PadiemAiEngineClientError):
            await _client(bad).admit_image_attachment(_request(**{key: "forged"}))
        assert bad.calls == []


@pytest.mark.asyncio
async def test_attachment_ref_and_locator_overrides_are_rejected():
    for key in (
        "attachment_ref",
        "locator",
        "url",
        "path",
        "expiry",
        "storage_key",
        "provider",
        "model",
    ):
        bad = _transport()
        with pytest.raises(PadiemAiEngineClientError):
            await _client(bad).admit_image_attachment(_request(**{key: "forged"}))
        assert bad.calls == []


@pytest.mark.asyncio
async def test_bounded_media_type_and_payload():
    for bad_type in ("image/gif", "text/plain", "", 7, None):
        bad = _transport()
        with pytest.raises(PadiemAiEngineClientError):
            await _client(bad).admit_image_attachment(_request(media_type=bad_type))
        assert bad.calls == []

    normalized = _transport()
    await _client(normalized).admit_image_attachment(_request(media_type=" IMAGE/PNG "))
    assert json.loads(normalized.calls[0]["body"])["media_type"] == "image/png"

    boundary = _transport()
    await _client(boundary).admit_image_attachment(
        _request(image_base64="A" * MAX_ATTACHMENT_IMAGE_BASE64_CHARS)
    )
    assert len(boundary.calls) == 1

    over = _transport()
    with pytest.raises(PadiemAiEngineClientError):
        await _client(over).admit_image_attachment(
            _request(image_base64="A" * (MAX_ATTACHMENT_IMAGE_BASE64_CHARS + 1))
        )
    assert over.calls == []


@pytest.mark.asyncio
async def test_malformed_admission_responses_fail_closed():
    malformed = (
        {"ok": True},
        {"ok": True, "attachment": []},
        {"ok": True, "attachment": "att_x"},
        {"ok": True, "attachment": {**PROJECTION, "locator": "s3://private"}},
        {"ok": True, "attachment": {**PROJECTION, "attachment_ref": "att_short"}},
        {"ok": True, "attachment": {**PROJECTION, "attachment_ref": "../../etc/passwd"}},
        {"ok": True, "attachment": {**PROJECTION, "media_type": "image/gif"}},
        {"ok": True, "attachment": {**PROJECTION, "byte_size": True}},
        {"ok": True, "attachment": {**PROJECTION, "byte_size": 0}},
        {"ok": True, "attachment": {**PROJECTION, "byte_size": "68"}},
        {"ok": True, "attachment": {**PROJECTION, "expires_at": "2026-09-30T03:00:00"}},
        {"ok": True, "attachment": {**PROJECTION, "expires_at": "not-a-time"}},
        {"ok": True, "attachment": {**PROJECTION, "expires_at": 12345}},
    )
    for body in malformed:
        transport = FakeTransport(
            EngineTransportResponse(status=200, body=json.dumps(body).encode())
        )
        with pytest.raises(PadiemAiEngineClientError) as raised:
            await _client(transport).admit_image_attachment(_request())
        assert raised.value.code == "invalid_engine_response"

    # A server-minted ref with no expiry is valid and stays None in the projection.
    ok_null = _transport({**PROJECTION, "expires_at": None})
    result = await _client(ok_null).admit_image_attachment(_request())
    assert result["expires_at"] is None


@pytest.mark.asyncio
async def test_non_2xx_admission_errors_are_bounded():
    plain = FakeTransport(EngineTransportResponse(status=500, body=b'{"ok":true}'))
    with pytest.raises(PadiemAiEngineClientError) as raised:
        await _client(plain).admit_image_attachment(_request())
    assert raised.value.code == "engine_http_error"
    assert raised.value.status == 500

    envelope = FakeTransport(
        EngineTransportResponse(
            status=503,
            body=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "attachment_admission_unavailable",
                        "message": "Trusted attachment admission authority is unavailable.",
                        "retryable": False,
                        "metadata": None,
                    },
                }
            ).encode(),
        )
    )
    with pytest.raises(PadiemAiEngineClientError) as raised2:
        await _client(envelope).admit_image_attachment(_request())
    assert raised2.value.code == "attachment_admission_unavailable"
    assert raised2.value.status == 503
    assert raised2.value.retryable is False
    for text in (str(raised.value), str(raised2.value)):
        assert CREDENTIAL not in text


def test_client_bound_matches_the_engine_store_ceiling():
    assert MAX_ATTACHMENT_IMAGE_BASE64_CHARS == MAX_STORED_IMAGE_BASE64_CHARS
