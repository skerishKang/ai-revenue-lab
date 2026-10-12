"""Test-only proof: no trusted B54→B14 session bridge exists (#4416).

Source-only boundary evidence for the CENTRAL slice: the OpenCode Go wire
requires an owner-revalidated stable B54 ``chat_<32hex>`` session id, but no
gateway path (completed JSON nor SSE preview) can supply one from a trusted
server-side provenance. Therefore production code is NOT changed here: any
``session_id`` taken from user JSON or an ``x-opencode-session`` header would
be untrusted input, and grammar alone is not ownership proof.

All tests are network-free. No registry, provider, tier, or routing change.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot.errors import PilotNotConfigured
from app.pilot.gateway import _validate_body, _InvalidBody

GO_MODELS = (
    "opencode-go/longcat-2.5-preview-free",
    "opencode-go/step-5-preview-free",
    "opencode-go/muse-spark-1.3-contributor",
    "opencode-go/gpt-6-luna",
    "opencode-go/claude-haiku-5-5",
)

FORGED_SESSION = "chat_" + "f" * 32
OTHER_SESSION = "chat_" + "0" * 32


def _go_body(model_id: str) -> dict:
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "합성 세션 경계 점검"}],
        "temperature": 0,
        "max_tokens": 8,
    }


# --------------------------------------------------------------------------
# 1. User JSON cannot carry session trust: the field is not even accepted.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_completed_body_rejects_session_id_field(model_id: str) -> None:
    body = _go_body(model_id)
    body["session_id"] = FORGED_SESSION
    with pytest.raises(_InvalidBody, match="Unexpected top-level fields"):
        _validate_body(body)


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_completed_body_rejects_business14_session_field(model_id: str) -> None:
    body = _go_body(model_id)
    body["business14"] = {"session_id": FORGED_SESSION}
    with pytest.raises(_InvalidBody, match="Unexpected business14 fields"):
        _validate_body(body)


def test_stream_preview_body_rejects_session_id_field() -> None:
    from app.pilot.stream_gateway import _validate_preview_body

    raw = _go_body(GO_MODELS[0])
    raw["stream"] = True
    raw["session_id"] = FORGED_SESSION
    with pytest.raises((_InvalidBody, Exception)):
        _validate_preview_body(raw)


# --------------------------------------------------------------------------
# 2. The x-opencode-session header is ignored: forged header changes nothing.
# --------------------------------------------------------------------------


def _post_completed(client: TestClient, model_id: str, headers: dict | None = None):
    return client.post(
        "/api/pilot/v1/chat/completions",
        json=_go_body(model_id),
        headers=headers or {},
    )


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_forged_header_does_not_change_gateway_outcome(model_id: str) -> None:
    with TestClient(create_app()) as client:
        plain = _post_completed(client, model_id)
        forged = _post_completed(
            client, model_id, {"x-opencode-session": FORGED_SESSION}
        )
    assert plain.status_code == forged.status_code
    # request_id is unique per request; compare everything else so a forged
    # header is proven to change nothing about routing or denial.
    plain_body = plain.json()
    forged_body = forged.json()
    for body in (plain_body, forged_body):
        body.pop("request_id", None)
        if isinstance(body.get("error"), dict):
            body["error"].pop("request_id", None)
    assert plain_body == forged_body
    assert plain_body["error"]["reason_code"] == "model_disabled"


# --------------------------------------------------------------------------
# 3. Adapter level: without a trusted session nothing reaches the network.
#    With a forged grammar-valid session but OFF registry, the OFF gate
#    fires before any transport POST.
# --------------------------------------------------------------------------


def _tripwire_transport(seen: list) -> httpx.MockTransport:
    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("no network POST permitted while OFF")

    return httpx.MockTransport(responder)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id,upstream", [
    ("opencode-go/longcat-2.5-preview-free", "longcat-2.5-preview-free"),
    ("opencode-go/step-5-preview-free", "step-5-preview-free"),
])
async def test_go_adapter_without_session_never_posts(model_id, upstream, monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list = []
    with pytest.raises(Exception):
        await plat.call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider="OpenCode Go",
            platform_provider_id="opencode-go",
            messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
            max_tokens=8,
            session_id=None,
            transport=_tripwire_transport(seen),
        )
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id,upstream", [
    ("opencode-go/longcat-2.5-preview-free", "longcat-2.5-preview-free"),
    ("opencode-go/step-5-preview-free", "step-5-preview-free"),
])
async def test_go_adapter_forged_session_blocked_by_off_gate(
    model_id, upstream, monkeypatch
) -> None:
    """Even a grammar-valid forged session cannot pass while OFF.

    The registry OFF gate (PilotNotConfigured) must fire before any
    transport POST — never a session-grammar bypass.
    """

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list = []
    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider="OpenCode Go",
            platform_provider_id="opencode-go",
            messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
            max_tokens=8,
            session_id=FORGED_SESSION,
            transport=_tripwire_transport(seen),
        )
    assert seen == []


# --------------------------------------------------------------------------
# 4. Two conversations cannot share a session through any gateway path:
#    the gateway never forwards one, so sharing is impossible by construction.
# --------------------------------------------------------------------------


def test_gateway_validated_body_never_contains_session() -> None:
    for model_id in GO_MODELS:
        validated = _validate_body(_go_body(model_id))
        assert "session_id" not in validated
        assert "session_id" not in validated.get("business14", {})


def test_distinct_forged_sessions_both_rejected_at_body() -> None:
    for session in (FORGED_SESSION, OTHER_SESSION):
        body = _go_body(GO_MODELS[0])
        body["session_id"] = session
        with pytest.raises(_InvalidBody):
            _validate_body(body)


# --------------------------------------------------------------------------
# 5. OFF pins: provider and all five models stay disabled (read-only).
# --------------------------------------------------------------------------


def test_go_provider_and_five_models_stay_off() -> None:
    from app.pilot.model_registry_file import read_registry

    reg = read_registry()
    assert reg["providers"]["opencode-go"]["enabled"] is False
    ids = {m["id"] for m in reg["models"] if m["provider_id"] == "opencode-go"}
    assert set(GO_MODELS) <= ids
    for model_id in GO_MODELS:
        row = next(m for m in reg["models"] if m["id"] == model_id)
        assert row["enabled"] is False


# --------------------------------------------------------------------------
# 6. SSE preview path carries no session either (same canonical validator).
# --------------------------------------------------------------------------


def test_sse_preview_invocation_carries_no_session_id() -> None:
    import inspect

    from app.pilot import stream_gateway

    source = inspect.getsource(stream_gateway)
    assert "session_id" not in source
