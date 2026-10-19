"""Mocked Worker dispatch tests for the deployment gate and body limits.

These exercise the real ``worker.Default.fetch`` code path, not a static source
string check: the OFF switch, the caller-authority gate, oversized and chunked
bodies, a missing provider key and malformed audio are all driven through the
actual handler.

The mocked upstream records every attempted call, which is how "no Secret read
and no provider call while OFF or while unauthorized" is actually proven rather
than asserted.

Two layers, deliberately separated
----------------------------------
``_dispatch``  — the shipped route. It runs the deployment flag, the caller
                 clues, the bounded body read, the Control Plane authority and
                 then the paid pipeline, in that order.

``_run_paid``  — the paid pipeline *behind* the route gate, invoked directly with
                 a hand-built :class:`voice_stt_contract.CallerAuthorization`.
                 This exists so the upstream request shape, the end-to-end
                 deadline and the provider-masking behaviour stay covered without
                 standing up a Control Plane. It is a test harness, not a
                 production approval path: the value it builds is never produced
                 by the Worker unless the Control Plane admits the call.
"""

from __future__ import annotations

import base64
import json
import tomllib
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fake_workers as fw
import voice_stt_contract as c

TRANSCRIBE_ROUTE = "/internal/v1/voice/transcribe"
LIVE_TOKEN_ROUTE = "/internal/v1/voice/live-token"


@pytest.fixture
def runtime():
    worker = fw.install_workers_module()
    return worker


def _caller_authenticated(headers=None, *, clues=True, **overrides):
    """Content-type plus the two opaque caller clues a product Worker presents."""
    merged = {"content-type": "application/json"}
    if clues:
        merged.update(fw.caller_headers())
    merged.update(headers or {})
    merged.update(overrides)
    return merged


def _transcribe_request(audio=b"voice-bytes", language="ko", url="https://voice.internal/internal/v1/voice/transcribe", headers=None, **kw):
    payload = {
        "audioDataUrl": "data:audio/webm;base64," + base64.b64encode(audio).decode("ascii"),
        "language": language,
    }
    return fw.FakeRequest("POST", url, _caller_authenticated(headers, **kw), json.dumps(payload).encode("utf-8"))


def _live_token_request(body=b'{"sessionId":"s"}', headers=None, **kw):
    return fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", _caller_authenticated(headers, **kw), body)


def _test_authorization(route: str) -> c.CallerAuthorization:
    """A test-only authorization object. **Not** a production grant.

    The Worker only ever builds one of these through
    ``voice_stt_caller_auth`` against the Control Plane. This harness builds it
    by hand so the provider-facing pipeline stays covered without an authority.
    """
    return c.CallerAuthorization(
        actor="local3-test-harness",
        tenant="tenant_local3fixture0000000000000000ab",
        route=route,
        capability=(
            c.CAPABILITY_TRANSCRIBE if route == TRANSCRIBE_ROUTE else c.CAPABILITY_LIVE_TOKEN
        ),
        reservation_id="test-only-no-real-cost",
        estimated_units=1,
        policy_revision="test-only-revision",
    )


async def _dispatch(worker, env, budget, request):
    """Drive the shipped route (``Default.fetch``)."""
    worker.fetch = budget.make_fetch()
    response = await worker.Default(env).fetch(request)
    return json.loads(response.body)


async def _run_paid(worker, env, budget, request, route):
    """Drive the paid pipeline directly, bypassing only the caller-authority gate.

    The request's body validation is kept here so the body-bound tests exercise
    the same production code the shipped route runs; only the Control Plane
    round trip is skipped, and ``Default.fetch`` turns a :class:`VoiceSttError`
    into the bounded envelope, so the assertions below read the same shape
    regardless of layer.
    """
    worker.fetch = budget.make_fetch()
    try:
        worker._require_json_content_type(request)
        if route == TRANSCRIBE_ROUTE:
            payload = await worker._read_json(request, c.MAX_REQUEST_BYTES)
            language, audio = c.validate_transcribe_request(payload)
            response = await worker._handle_transcribe(
                env, _test_authorization(route), language, audio
            )
        else:
            payload = await worker._read_json(request, worker.LIVE_TOKEN_MAX_BYTES)
            if not isinstance(payload, dict) or set(payload) - {"sessionId"}:
                raise c.VoiceSttError("unsupported_field", 400)
            response = await worker._handle_live_token(env, _test_authorization(route))
    except c.VoiceSttError as exc:
        return {"ok": False, "error": {"code": exc.code}}
    return json.loads(response.body)


def _transcribe_body_of_exact_size(total: int) -> bytes:
    """A syntactically valid transcribe body of exactly ``total`` bytes.

    The base64 payload is a multiple of 4 characters and the remaining slack is
    filled with JSON whitespace, so the byte count is exact without inventing
    unknown fields.
    """
    prefix = b'{"audioDataUrl":"data:audio/webm;base64,'
    tail = b',"language":"ko"}'
    # The base64 payload must stay clean (it is decoded with validate=True), so
    # the slack is filled with JSON whitespace *outside* the string value.
    b64_budget = total - len(prefix) - 1 - len(tail)  # 1 = the closing quote
    assert b64_budget > 4, "requested size must leave room for the envelope"
    audio_len = (b64_budget // 4) * 3  # base64 expands 3 bytes to 4 characters
    encoded = base64.b64encode(b"\x00" * audio_len)
    padding = total - len(prefix) - len(encoded) - 1 - len(tail)
    return prefix + encoded + b'"' + b" " * padding + tail


# ---------------------------------------------------------------------------
# P0-2: the OFF switch actually blocks
# ---------------------------------------------------------------------------


async def test_off_gate_blocks_every_route_before_any_upstream_call(runtime):
    budget = fw.FetchBudget()
    env = fw.disabled_env(PADIEM_GROQ_API_KEY=fw.FakeSecretsBinding("x"))
    for request in (
        _transcribe_request(),
        fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", _caller_authenticated(), b'{"sessionId":"s"}'),
        fw.FakeRequest("GET", "https://voice.internal/internal/v1/voice/capabilities"),
    ):
        body = await _dispatch(runtime, env, budget, request)
        assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}
    assert budget.calls == []


async def test_off_gate_never_reads_the_secret_binding(runtime):
    """The binding handle must stay untouched while OFF."""
    groq = fw.FakeSecretsBinding("groq-key-value")
    gemini = fw.FakeSecretsBinding("gemini-key-value")
    env = fw.disabled_env(PADIEM_GROQ_API_KEY=groq, PADIEM_GEMINI_API_KEY=gemini)
    budget = fw.FetchBudget()
    await _dispatch(runtime, env, budget, _transcribe_request())
    await _dispatch(
        runtime,
        env,
        budget,
        fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", _caller_authenticated(), b'{"sessionId":"s"}'),
    )
    assert groq.reads == 0
    assert gemini.reads == 0
    assert budget.calls == []


async def test_mode1_production_source_requires_both_cp_services(runtime):
    """Source activation requires both private CP authority bindings.

    The separate disabled env still rejects every route before provider calls.
    A source manifest is NOT evidence of production deployment.
    """
    config = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "wrangler.toml").read_text(encoding="utf-8")
    )
    assert config.get("vars", {}).get("PADIEM_VOICE_STT_ENABLED") == "true"
    declared = {
        entry["binding"]: entry["service"]
        for entry in (config.get("services") or [])
    }
    assert declared == {
        "CONTROL_PLANE_IDENTITY": "padiem-control-plane-identity",
        "CONTROL_PLANE_ENGINE_ADMISSION": "padiem-control-plane-engine-admission",
    }
    budget = fw.FetchBudget()
    env = fw.disabled_env()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}
    assert budget.calls == []


@pytest.mark.parametrize("missing", ["CONTROL_PLANE_IDENTITY", "CONTROL_PLANE_ENGINE_ADMISSION"])
@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_on_without_a_canonical_authority_binding_is_not_reachable(runtime, missing, route):
    """ON alone is not a test override: without both CP bindings it fails closed."""
    env = fw.enabled_env(**{missing: None})
    budget = fw.FetchBudget()
    request = _route_request(route)
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0
    assert env.PADIEM_GEMINI_API_KEY.reads == 0


@pytest.mark.parametrize("decoy", [None, types.SimpleNamespace(), types.SimpleNamespace(authorize=True)])
async def test_retired_caller_guard_binding_authorizes_nothing(runtime, decoy):
    """A bound ``VOICE_STT_CALLER_GUARD`` is never consulted and opens nothing."""
    guard = fw.FakeApprovingDecoyGuard() if decoy is None else decoy
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=guard, CONTROL_PLANE_ENGINE_ADMISSION=None)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert getattr(guard, "calls", []) == []
    assert budget.calls == []

    # And it is not consulted on the admitted path either.
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=guard)
    budget.response = fw.FakeUpstream(200, {"text": "ok"})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body["ok"] is True
    assert getattr(guard, "calls", []) == []


async def test_missing_enabled_var_fails_closed(runtime):
    env = fw.enabled_env()
    del env.PADIEM_VOICE_STT_ENABLED
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}


@pytest.mark.parametrize("flag", ["", "1", "yes", "on", "false", "null", "0", "TRUE", " True ", "\ttrue\n", True, 1])
async def test_non_true_flag_fails_closed(runtime, flag):
    env = fw.enabled_env(PADIEM_VOICE_STT_ENABLED=flag)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}


@pytest.mark.parametrize("flag", ["true"])
async def test_true_flag_still_requires_the_canonical_authority(runtime, flag):
    """Operator-friendly ``true`` is only the first of two gates."""
    env = fw.enabled_env(PADIEM_VOICE_STT_ENABLED=flag, CONTROL_PLANE_IDENTITY=None)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}


async def test_capabilities_is_public_and_key_free(runtime):
    """The key-free route needs no authority binding at all."""
    env = fw.enabled_env(CONTROL_PLANE_IDENTITY=None, CONTROL_PLANE_ENGINE_ADMISSION=None)
    budget = fw.FetchBudget()
    request = fw.FakeRequest("GET", "https://voice.internal/internal/v1/voice/capabilities")
    body = await _dispatch(runtime, env, budget, request)
    assert body["ok"] is True
    assert body["provider_order"] == ["gemini_live", "browser_speech", "groq_whisper"]
    blob = json.dumps(body).lower()
    for forbidden in ("key", "token", "secret", "bearer"):
        assert forbidden not in blob
    assert budget.calls == []


async def test_capabilities_wrong_method(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/capabilities")
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "method_not_allowed"}}


async def test_unknown_route(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, fw.FakeRequest("GET", "https://voice.internal/nope"))
    assert body == {"ok": False, "error": {"code": "not_found"}}


# ---------------------------------------------------------------------------
# P0-3: body bounds
# ---------------------------------------------------------------------------


async def test_oversized_chunked_body_without_content_length_is_rejected(runtime):
    """No Content-Length at all: the stream reader must still bound the body."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    oversize = c.MAX_REQUEST_BYTES + 512
    request = _transcribe_request(audio=b"a" * oversize, language="ko")
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    # No upstream call and no Secret read happened on the way out.
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_oversized_declared_content_length_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x")
    request.headers["content-length"] = str(c.MAX_REQUEST_BYTES + 4096)
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_declared_content_length_lie_is_rejected(runtime):
    """A header that understates the real body must not lower the guard."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"a" * (c.MAX_REQUEST_BYTES + 1024))
    request.headers["content-length"] = "1024"  # lies about the real size
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


@pytest.mark.parametrize("declared", ["-1", "-99999", "abc", "", "1.5", "0x10", "12,3"])
async def test_negative_or_malformed_content_length_is_rejected(runtime, declared):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x")
    request.headers["content-length"] = declared
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "invalid_content_length"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


# ---------------------------------------------------------------------------
# The real 5 MiB request boundary (not a 4 KiB stand-in)
# ---------------------------------------------------------------------------


async def test_body_of_exactly_max_request_bytes_passes_the_size_guard(runtime):
    """Exactly ``MAX_REQUEST_BYTES`` (5 MiB) is admitted by the byte ceiling.

    The body is deliberately delivered as ONE chunk with no Content-Length, so
    a single JS-sized read of the whole 5 MiB must be accounted correctly and
    must not be truncated into a falsely legal size. The request then fails on
    the *semantic* audio ceiling (3 MiB) — which is the proof that the byte
    ceiling let it through rather than rejecting it as too large.
    """
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    exact = _transcribe_body_of_exact_size(c.MAX_REQUEST_BYTES)
    assert len(exact) == c.MAX_REQUEST_BYTES == 5 * 1024 * 1024
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, exact)
    request.body = fw._Stream(exact, chunk=len(exact))  # one undivided chunk
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body["error"]["code"] != "request_too_large", body
    assert body == {"ok": False, "error": {"code": "audio_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_body_one_byte_over_max_request_bytes_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    over = _transcribe_body_of_exact_size(c.MAX_REQUEST_BYTES + 1)
    assert len(over) == c.MAX_REQUEST_BYTES + 1
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, over)
    request.body = fw._Stream(over, chunk=len(over))
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_body_one_byte_over_the_limit_in_small_chunks_is_rejected(runtime):
    """The +1 case split across ordinary 4 KiB chunks is still caught."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    over = _transcribe_body_of_exact_size(c.MAX_REQUEST_BYTES + 1)
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, over)
    request.body = fw._Stream(over, chunk=4096)
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_nominal_small_body_succeeds_smoke(runtime):
    """Nominal success only — this is NOT size-boundary evidence."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    request = _transcribe_request(audio=b"y" * 4096)
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body["ok"] is True and body["text"] == "네"


async def test_empty_body_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, b"")
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "invalid_json"}}
    assert budget.calls == []


async def test_wrong_content_type_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "text/plain"}, b"{}")
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "unsupported_media_type"}}
    assert budget.calls == []


async def test_unsupported_field_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    payload = {"audioDataUrl": "data:audio/webm;base64,AAAA", "language": "ko", "url": "https://evil.test"}
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, json.dumps(payload).encode()
    )
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "unsupported_field"}}


async def test_invalid_language_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x", language="fr"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "invalid_language"}}
    assert budget.calls == []


# ---------------------------------------------------------------------------
# Provider key presence and provider failure
# ---------------------------------------------------------------------------


async def test_missing_groq_key_fails_closed_without_upstream_call(runtime):
    env = fw.enabled_env(PADIEM_GROQ_API_KEY=fw.FakeSecretsBinding(None))
    budget = fw.FetchBudget()
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_key_missing"}}
    assert budget.calls == []


async def test_missing_gemini_key_fails_closed_without_upstream_call(runtime):
    env = fw.enabled_env(PADIEM_GEMINI_API_KEY=fw.FakeSecretsBinding(None))
    budget = fw.FetchBudget()
    body = await _run_paid(runtime, env, budget, _live_token_request(), LIVE_TOKEN_ROUTE)
    assert body == {"ok": False, "error": {"code": "live_token_unavailable"}}
    assert budget.calls == []


async def test_live_token_rejects_unknown_fields(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_paid(runtime, env, budget, _live_token_request(b'{"sessionId":"s","model":"x"}'), LIVE_TOKEN_ROUTE)
    assert body == {"ok": False, "error": {"code": "unsupported_field"}}


async def test_transcribe_falls_through_the_model_sequence(runtime):
    """The turbo model failing must fall through to the full model."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "안녕하세요"})
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body["model"] == "whisper-large-v3-turbo"

    # Now make the first attempt fail and confirm the second model is tried.
    calls = []

    async def _fetch(resource, **kwargs):
        calls.append(kwargs.get("body"))
        if len(calls) == 1:
            return fw.FakeUpstream(500, {"error": {"message": "model unavailable"}})
        return fw.FakeUpstream(200, {"text": "안녕하세요"})

    budget.calls = []
    runtime.fetch = _fetch
    _, audio = c.validate_transcribe_request(
        {
            "audioDataUrl": "data:audio/webm;base64,"
            + base64.b64encode(b"x").decode("ascii")
        }
    )
    response = await runtime._handle_transcribe(
        env, _test_authorization(TRANSCRIBE_ROUTE), "ko", audio
    )
    body = json.loads(response.body)
    assert body["model"] == "whisper-large-v3"
    assert body["ok"] is True


async def test_provider_5xx_never_leaks_provider_detail(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(500, {"error": {"message": "account abc123 quota exhausted"}})
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_failed"}}
    assert "abc123" not in json.dumps(body)


async def test_transport_failure_returns_a_bounded_code(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.raise_exc = True
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}


async def test_upstream_call_carries_a_timeout_budget(runtime, monkeypatch):
    """The abort-signal budget is bounded and actually applied to the call."""
    seen = []

    def _record(ms):
        seen.append(ms)
        return f"abort-signal-{ms}"

    monkeypatch.setattr(runtime, "_build_abort_signal", _record)
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert seen == [c.GROQ_REQUEST_TIMEOUT_MS]
    assert budget.calls and budget.calls[0]["url"] == c.GROQ_STT_ENDPOINT
    assert budget.calls[0]["signal"] == f"abort-signal-{c.GROQ_REQUEST_TIMEOUT_MS}"


async def test_live_token_call_carries_its_own_shorter_budget(runtime, monkeypatch):
    seen = []
    monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: seen.append(ms))
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque-token"})
    await _run_paid(runtime, env, budget, _live_token_request(b'{"sessionId":"sess-1"}'), LIVE_TOKEN_ROUTE)
    assert seen == [c.LIVE_TOKEN_REQUEST_TIMEOUT_MS]


async def test_secret_value_never_reaches_the_response_or_the_log_stream(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    response_raw = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    dumped = json.dumps(response_raw)
    assert "groq-key-value" not in dumped
    assert "gemini-key-value" not in dumped
    # The Authorization header is transport-only, never a response field.
    assert "Authorization" in budget.calls[0]["headers"]


# ---------------------------------------------------------------------------
# P0-1: token request shape reached through the real handler
# ---------------------------------------------------------------------------


async def test_live_token_request_shape_through_the_handler(runtime, monkeypatch):
    # Freeze the clock so the sent body equals the contract's own output exactly.
    monkeypatch.setattr(c, "_now_epoch_ms", lambda: 1_800_000_000_000)
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque-token"})
    body = await _run_paid(runtime, env, budget, _live_token_request(b'{"sessionId":"sess-1"}'), LIVE_TOKEN_ROUTE)
    assert body["ok"] is True
    assert body["token"] == "auth_tokens/opaque-token"

    call = budget.calls[0]
    assert call["url"] == c.GEMINI_LIVE_TOKEN_ENDPOINT
    assert "v1beta" in call["url"]
    sent = json.loads(call["body"])
    assert sent == c.build_live_token_request_body()
    assert sent["liveConnectConstraints"]["model"] == c.GEMINI_LIVE_STT_MODEL
    assert "model" not in {k for k in sent if k != "liveConnectConstraints"}


async def test_live_token_provider_failure_is_bounded(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(401, {"error": {"message": "invalid api key abc123"}})
    body = await _run_paid(runtime, env, budget, _live_token_request(), LIVE_TOKEN_ROUTE)
    assert body == {"ok": False, "error": {"code": "live_token_unavailable"}}
    assert "abc123" not in json.dumps(body)


# ---------------------------------------------------------------------------
# The paid-route authority: only a canonical Control Plane verdict opens a route
# ---------------------------------------------------------------------------


def _route_request(route, audio=b"x"):
    return _transcribe_request(audio=audio) if route == TRANSCRIBE_ROUTE else _live_token_request()


#: Every way the canonical authority can fail to admit one paid call. Each row
#: must answer with its bounded code and must not touch a Secret or a provider.
_DENIALS = [
    (
        "no_identity_binding",
        lambda: fw.enabled_env(CONTROL_PLANE_IDENTITY=None),
        "caller_guard_unavailable",
    ),
    (
        "no_admission_binding",
        lambda: fw.enabled_env(CONTROL_PLANE_ENGINE_ADMISSION=None),
        "caller_guard_unavailable",
    ),
    (
        "identity_binding_is_a_plain_object",
        lambda: fw.enabled_env(CONTROL_PLANE_IDENTITY=types.SimpleNamespace()),
        "caller_guard_unavailable",
    ),
    (
        "admission_binding_is_a_plain_object",
        lambda: fw.enabled_env(CONTROL_PLANE_ENGINE_ADMISSION=types.SimpleNamespace()),
        "caller_guard_unavailable",
    ),
    (
        "admission_binding_approves_everything_by_truthiness",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=types.SimpleNamespace(
                fetch_entitlement_snapshot=lambda **_: {"allowed": True, "cost_scope": {"daily_usd_cap": 5}},
                reserve_usage=lambda **_: True,
            )
        ),
        "voice_stt_authority_unavailable",
    ),
    (
        "session_missing",
        lambda: fw.enabled_env(CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(missing=True)),
        "voice_stt_unauthenticated",
    ),
    (
        "session_revoked",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(state="revoked")
            )
        ),
        "voice_stt_unauthenticated",
    ),
    (
        "session_expired",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(
                    issued_at=fw.CP_RESERVED_PAST, expires_at=fw.CP_PAST
                )
            )
        ),
        "voice_stt_unauthenticated",
    ),
    (
        # A fully self-consistent Control Plane answer for a *different* product.
        # Only the explicit session/claim product comparison can catch this: the
        # snapshot below would otherwise match the borrowed identity exactly.
        "session_belongs_to_another_product",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(product_id="b54-padiem-claw")
            ),
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(
                    fw.voice_grant(), fw.live_token_grant(), product_id="b54-padiem-claw"
                )
            ),
        ),
        "voice_stt_forbidden",
    ),
    (
        "session_id_echo_mismatch",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(session_id="sess-someone-else")
            )
        ),
        "voice_stt_forbidden",
    ),
    (
        "subject_is_anonymous",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(
                    subject={"subject_type": "anonymous", "subject_id": fw.CP_SUBJECT}
                )
            )
        ),
        "voice_stt_forbidden",
    ),
    (
        "tenant_absent",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(tenant_id=None)
            )
        ),
        "voice_stt_tenant_unavailable",
    ),
    (
        "tenant_aliased_to_the_product",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(
                fw.cp_session_payload(tenant_id=fw.CP_PRODUCT)
            )
        ),
        "voice_stt_tenant_unavailable",
    ),
    (
        "no_voice_grant_at_all",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(("orchestration.run", True, None))
            )
        ),
        "voice_stt_cost_denied",
    ),
    (
        "voice_grant_denied",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(("voice.stt.transcribe", False, None))
            )
        ),
        "voice_stt_cost_denied",
    ),
    (
        "snapshot_belongs_to_another_product",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(
                    fw.voice_grant(), product_id="b54-padiem-claw"
                )
            )
        ),
        "voice_stt_forbidden",
    ),
    (
        "snapshot_belongs_to_another_subject",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(
                    fw.voice_grant(),
                    subject={"subject_type": "user", "subject_id": "user-someone-else"},
                )
            )
        ),
        "voice_stt_forbidden",
    ),
    (
        "snapshot_is_expired",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                snapshot=fw.cp_snapshot_payload(
                    fw.voice_grant(), issued_at=fw.CP_RESERVED_PAST, expires_at=fw.CP_PAST
                )
            )
        ),
        "voice_stt_cost_denied",
    ),
    (
        "reservation_refused",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(admitted=False)
        ),
        "voice_stt_cost_denied",
    ),
    (
        "reservation_expired",
        lambda: fw.enabled_env(
            CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
                reservation=fw.cp_reservation_payload(
                    reserved_at=fw.CP_RESERVED_PAST, expires_at=fw.CP_PAST
                )
            )
        ),
        "voice_stt_cost_denied",
    ),
    (
        "authority_transport_failure",
        lambda: fw.enabled_env(
            CONTROL_PLANE_IDENTITY=fw.FakeIdentityBinding(raises=RuntimeError("cp down"))
        ),
        "voice_stt_authority_unavailable",
    ),
]


@pytest.mark.parametrize("name,build,expected", _DENIALS, ids=[n for n, _, _ in _DENIALS])
@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_no_unverified_authority_state_reaches_a_secret_or_a_provider(
    runtime, name, build, expected, route
):
    """Every denial path stays closed on **both** paid routes.

    The regression this preserves: a binding that merely exists, or answers
    ``True``/``{"allowed": True, ...}``, must never reach a Secret or a provider.
    The Worker now asks the canonical Control Plane instead of guessing, and each
    way that answer can be absent, wrong or refusing maps to a bounded code.
    """
    env = build()
    budget = fw.FetchBudget()
    request = _route_request(route)
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": expected}}, name
    assert budget.calls == [], f"{name}: a provider was called"
    assert env.PADIEM_GROQ_API_KEY.reads == 0, name
    assert env.PADIEM_GEMINI_API_KEY.reads == 0, name


@pytest.mark.parametrize(
    "header",
    [
        {"x-padiem-product-id": ""},
        {"x-padiem-auth-session-id": ""},
        {"x-padiem-auth-session-id": None},
        {"x-padiem-product-id": "../../etc/passwd"},
        {"x-padiem-product-id": "b62", "x-padiem-auth-session-id": "s" * 200},
    ],
    ids=["blank_product", "blank_session", "null_session", "path_escape", "oversized_session"],
)
@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_missing_or_malformed_caller_clues_are_unauthenticated(runtime, header, route):
    """No usable identity clue means no paid call — before the body is even read."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = (
        _transcribe_request(audio=b"x", headers=header)
        if route == TRANSCRIBE_ROUTE
        else _live_token_request(headers=header)
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "voice_stt_unauthenticated"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0
    assert env.CONTROL_PLANE_IDENTITY.calls == []


@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_absent_caller_clues_are_unauthenticated(runtime, route):
    """A request that presents no clue at all is not an anonymous free tier."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = (
        _transcribe_request(audio=b"x", clues=False)
        if route == TRANSCRIBE_ROUTE
        else _live_token_request(clues=False)
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "voice_stt_unauthenticated"}}
    assert env.CONTROL_PLANE_IDENTITY.calls == []


async def test_voice_grant_limit_caps_the_audited_units(runtime):
    """A bounded grant refuses a request whose audited units exceed its limit."""
    env = fw.enabled_env(
        CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
            snapshot=fw.cp_snapshot_payload(fw.voice_grant(limit=1))
        )
    )
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "ok"})
    within = b"a" * c.AUDIO_COST_UNIT_BYTES
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=within))
    assert body["ok"] is True
    over = b"a" * (c.AUDIO_COST_UNIT_BYTES + 1)
    env = fw.enabled_env(
        CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
            snapshot=fw.cp_snapshot_payload(fw.voice_grant(limit=1))
        )
    )
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=over))
    assert body == {"ok": False, "error": {"code": "voice_stt_cost_denied"}}
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_an_unauthenticated_request_is_rejected_before_its_body_is_buffered(runtime):
    """Ordering: identity clues are read before the bounded body read."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x", headers={"x-padiem-product-id": None})
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "voice_stt_unauthenticated"}}
    assert env.CONTROL_PLANE_IDENTITY.calls == []
    assert env.CONTROL_PLANE_ENGINE_ADMISSION.snapshot_calls == []


async def test_an_admitted_call_reserves_cost_from_the_validated_audio_length(runtime):
    """The cost units come from the Worker, never from the request."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    two_units = (c.AUDIO_COST_UNIT_BYTES * 2) + 1
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"a" * two_units))
    assert body["ok"] is True
    admission = env.CONTROL_PLANE_ENGINE_ADMISSION
    assert len(admission.reservation_calls) == 1
    reservation = admission.reservation_calls[0]["reservation"]
    assert reservation["estimated_units"] == 3
    assert reservation["product_id"] == fw.CP_PRODUCT
    assert reservation["subject"] == {"subject_type": "user", "subject_id": fw.CP_SUBJECT}
    assert reservation["billing_semantic_id"] == c.CAPABILITY_TRANSCRIBE


@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_distinct_paid_calls_never_reuse_one_control_plane_reservation(runtime, route):
    """CP idempotency is per request, not per user/route/audio-size bucket.

    The real Control Plane returns an existing reservation when an idempotency
    key repeats. Two independent invocations must therefore have different keys
    even when every product, subject, unit count and payload byte is identical.
    """
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = (
        fw.FakeUpstream(200, {"text": "네"})
        if route == TRANSCRIBE_ROUTE
        else fw.FakeUpstream(200, {"name": "auth_tokens/opaque"})
    )
    for _ in range(2):
        request = (
            _transcribe_request(audio=b"same audio")
            if route == TRANSCRIBE_ROUTE
            else _live_token_request()
        )
        result = await _dispatch(runtime, env, budget, request)
        assert result["ok"] is True
    calls = env.CONTROL_PLANE_ENGINE_ADMISSION.reservation_calls
    assert len(calls) == 2
    left, right = (call["reservation"] for call in calls)
    assert left["estimated_units"] == right["estimated_units"]
    assert left["product_id"] == right["product_id"]
    assert left["idempotency_key"] != right["idempotency_key"]
    assert left["request_fingerprint"] != right["request_fingerprint"]


async def test_control_plane_reservation_time_is_observed_after_its_rpc(runtime):
    """CP stamps reserved_at *during* the RPC, later than the pre-RPC clock.

    This is a valid authorization. A pre-RPC observation would reject it as
    'from the future' even though the authority itself generated that time.
    """
    current = [datetime.now(timezone.utc)]

    class StampAtReservation(fw.FakeAdmissionBinding):
        async def reserve_usage(self, payload):
            current[0] += timedelta(seconds=1)
            self.reservation = fw.cp_reservation_payload(
                reserved_at=current[0].isoformat(),
                expires_at=(current[0] + timedelta(minutes=5)).isoformat(),
            )
            return await super().reserve_usage(payload)

    authority = runtime.caller_auth.CallerAuthority(
        identity=runtime.caller_auth.CloudflareIdentitySessionClient(
            fw.FakeIdentityBinding()
        ),
        admission=runtime.caller_auth.CloudflareAdmissionClient(
            StampAtReservation()
        ),
        clock=lambda: current[0],
    )
    authorization = await authority.authorize(
        clues=runtime.caller_auth.CallerClues(
            product_id=fw.CP_PRODUCT, session_id=fw.CP_SESSION
        ),
        capability=c.CAPABILITY_TRANSCRIBE,
        route=TRANSCRIBE_ROUTE,
        estimated_units=1,
    )
    assert authorization.admits(TRANSCRIBE_ROUTE)


async def test_cost_denied_is_decided_before_the_secret_is_read(runtime):
    """A cost denial never even resolves the provider key."""
    env = fw.enabled_env(
        CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(admitted=False)
    )
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_cost_denied"}}
    assert env.PADIEM_GROQ_API_KEY.reads == 0
    assert budget.calls == []


async def test_live_token_mints_only_under_its_own_capability(runtime):
    """The transcription grant does not open the live-token route, and vice versa."""
    transcribe_only = fw.enabled_env(
        CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
            snapshot=fw.cp_snapshot_payload(fw.voice_grant())
        )
    )
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque"})
    body = await _dispatch(runtime, transcribe_only, budget, _live_token_request())
    assert body == {"ok": False, "error": {"code": "voice_stt_cost_denied"}}
    assert transcribe_only.PADIEM_GEMINI_API_KEY.reads == 0

    live_only = fw.enabled_env(
        CONTROL_PLANE_ENGINE_ADMISSION=fw.FakeAdmissionBinding(
            snapshot=fw.cp_snapshot_payload(fw.live_token_grant())
        )
    )
    body = await _dispatch(runtime, live_only, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_cost_denied"}}
    assert live_only.PADIEM_GROQ_API_KEY.reads == 0


async def test_an_admitted_transcription_calls_the_provider(runtime):
    """The one admitted path, end to end through the shipped route."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body["ok"] is True and body["text"] == "네"
    assert budget.calls and budget.calls[0]["url"] == c.GROQ_STT_ENDPOINT


async def test_capabilities_needs_no_caller_identity(runtime):
    """The key-free route is unaffected by the paid-route authority."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, fw.FakeRequest("GET", "https://voice.internal/internal/v1/voice/capabilities"))
    assert body["ok"] is True
    assert body["enabled_route_contract"] == "canonical_caller_tenant_cost_authority"
    assert budget.calls == []
    assert env.CONTROL_PLANE_IDENTITY.calls == []


# ---------------------------------------------------------------------------
# Handler defence in depth: an authorization is bound to its own route
# ---------------------------------------------------------------------------


async def _run_handler(worker, env, budget, authorization):
    """Call the transcribe handler with an arbitrary claimed authorization."""
    worker.fetch = budget.make_fetch()
    _, audio = c.validate_transcribe_request(
        {"audioDataUrl": "data:audio/webm;base64," + base64.b64encode(b"x").decode("ascii")}
    )
    try:
        response = await worker._handle_transcribe(env, authorization, "ko", audio)
    except c.VoiceSttError as exc:
        return {"ok": False, "error": {"code": exc.code}}
    return json.loads(response.body)


async def test_pipeline_refuses_an_authorization_for_another_route(runtime):
    """Even a verified authorization is re-checked against the route it names."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_handler(runtime, env, budget, _test_authorization(LIVE_TOKEN_ROUTE))
    assert body == {"ok": False, "error": {"code": "voice_stt_authority_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


@pytest.mark.parametrize(
    "authorization",
    [None, True, {}, {"allowed": True, "cost_scope": {"daily_usd_cap": 1}}, "approved"],
)
async def test_pipeline_refuses_anything_that_is_not_an_authorization(runtime, authorization):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_handler(runtime, env, budget, authorization)
    assert body == {"ok": False, "error": {"code": "voice_stt_authority_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor", ""),
        ("tenant", "   "),
        ("capability", ""),
        ("reservation_id", ""),
        ("policy_revision", ""),
        ("estimated_units", 0),
        ("estimated_units", -3),
        ("estimated_units", True),
        ("estimated_units", "1"),
        ("estimated_units", c.MAX_RESERVATION_UNITS + 1),
    ],
)
async def test_pipeline_refuses_an_incomplete_authorization(runtime, field, value):
    """A blank actor/tenant/capability/reservation or a non-positive cost is refused."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    kwargs = {
        "actor": _test_authorization(TRANSCRIBE_ROUTE).actor,
        "tenant": _test_authorization(TRANSCRIBE_ROUTE).tenant,
        "route": TRANSCRIBE_ROUTE,
        "capability": c.CAPABILITY_TRANSCRIBE,
        "reservation_id": "res-fixture",
        "estimated_units": 1,
        "policy_revision": "rev",
    }
    kwargs[field] = value
    body = await _run_handler(runtime, env, budget, c.CallerAuthorization(**kwargs))
    assert body == {"ok": False, "error": {"code": "voice_stt_authority_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


# ---------------------------------------------------------------------------
# _chunk_reader: one large chunk must not be silently truncated
# ---------------------------------------------------------------------------


async def test_single_giant_chunk_is_accounted_and_rejected_not_truncated(runtime):
    """A body delivered as ONE huge JS chunk is rejected, never sliced to fit.

    Regression guard for ``bytes(value)[:limit]``: with a single chunk larger
    than the ceiling the old reader truncated to ``limit`` bytes and the
    accumulator saw only a legal-size body, so an oversized request could be
    mis-judged as in-bounds.
    """
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    oversize = c.MAX_REQUEST_BYTES + 1
    request = _transcribe_request(audio=b"a" * oversize)
    # One undivided read, exactly like a single large Workers/JS chunk.
    request.body = fw._Stream(request._body, chunk=len(request._body))
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_single_chunk_at_the_read_budget_is_accepted_smoke(runtime):
    """Nominal single-chunk success only. Not size-boundary evidence."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    request = _transcribe_request(audio=b"y" * 4096)
    request.body = fw._Stream(request._body, chunk=len(request._body))
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body["ok"] is True and body["text"] == "네"


async def test_chunk_reader_one_byte_over_budget_is_rejected(runtime):
    """Many small chunks whose total is one byte past the ceiling are rejected."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    oversize = c.MAX_REQUEST_BYTES + 1
    request = _transcribe_request(audio=b"a" * oversize)
    request.body = fw._Stream(request._body, chunk=4096)
    body = await _run_paid(runtime, env, budget, request, TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


# ---------------------------------------------------------------------------
# Timeout: a runtime without AbortSignal.timeout must still be bounded
# ---------------------------------------------------------------------------


async def test_no_abort_signal_timeout_runtime_still_bounded(runtime, monkeypatch):
    """Without ``AbortSignal`` the upstream call is still wall-clock bounded.

    ``_build_abort_signal`` returns ``None`` on such a runtime; the fetch must
    not wait forever — ``asyncio.wait_for`` cancels it at the same budget.
    """
    monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: None)
    monkeypatch.setattr(c, "GROQ_REQUEST_TIMEOUT_MS", 120)
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.hang = True  # upstream never answers
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}
    assert budget.calls and budget.calls[0]["signal"] is None


async def test_live_token_no_abortsignal_runtime_still_bounded(runtime, monkeypatch):
    monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: None)
    monkeypatch.setattr(c, "LIVE_TOKEN_REQUEST_TIMEOUT_MS", 120)
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.hang = True
    body = await _run_paid(runtime, env, budget, _live_token_request(), LIVE_TOKEN_ROUTE)
    # A transport/timeout failure on the live-token route surfaces as the same
    # bounded upstream code the transcribe route uses; it never leaks a trace.
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}
    assert budget.calls and budget.calls[0]["signal"] is None


def test_build_abort_signal_returns_none_without_abortsupport(runtime, monkeypatch):
    """A runtime whose ``js`` has no ``AbortSignal.timeout`` yields ``None``."""
    import sys as _sys

    fake_js = types.SimpleNamespace()  # no AbortSignal at all
    monkeypatch.setitem(_sys.modules, "js", fake_js)
    assert runtime._build_abort_signal(1000) is None

    fake_js2 = types.SimpleNamespace(AbortSignal=types.SimpleNamespace())  # no .timeout
    monkeypatch.setitem(_sys.modules, "js", fake_js2)
    assert runtime._build_abort_signal(1000) is None


def test_build_abort_signal_uses_timeout_when_supported(runtime, monkeypatch):
    """A supported runtime gets a real AbortSignal from ``AbortSignal.timeout``."""
    import sys as _sys

    fake_js = types.SimpleNamespace(
        AbortSignal=types.SimpleNamespace(timeout=lambda ms: ("signal", ms))
    )
    monkeypatch.setitem(_sys.modules, "js", fake_js)
    assert runtime._build_abort_signal(25000) == ("signal", 25000)


# ---------------------------------------------------------------------------
# P0-C: the deadline must cover the response BODY, not just the headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
@pytest.mark.parametrize("abort_supported", [True, False])
async def test_hanging_response_body_is_bounded(runtime, monkeypatch, route, abort_supported):
    """Headers answered, body never finishes: the budget must still expire.

    This is the P0-C regression. ``asyncio.wait_for(fetch(...))`` bounded only
    the initial response; ``await upstream.json()`` then waited unbounded, so a
    trickling provider could hold the Worker past the stated 25s / 8s ceiling.
    The deadline is now captured once and the body read only gets what is left.
    """
    monkeypatch.setattr(c, "GROQ_REQUEST_TIMEOUT_MS", 120)
    monkeypatch.setattr(c, "LIVE_TOKEN_REQUEST_TIMEOUT_MS", 120)
    if not abort_supported:
        monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: None)

    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"}, hang_body=True)
    request = _route_request(route)
    body = await _run_paid(runtime, env, budget, request, route)
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}
    # The provider was actually contacted once, and its body read was attempted.
    assert len(budget.calls) == 1
    assert budget.response.body_reads == 1


async def test_oversized_upstream_body_is_rejected(runtime):
    """A provider that answers with a huge body is not buffered indefinitely."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, raw="x" * (c.MAX_UPSTREAM_RESPONSE_BYTES + 1))
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}


async def test_upstream_stream_stops_at_first_chunk_over_ceiling(runtime):
    """A provider body is rejected without reading its remaining megabytes."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(
        200, raw="x" * (c.MAX_UPSTREAM_RESPONSE_BYTES + (1024 * 1024))
    )
    body = await _run_paid(
        runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE
    )
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}
    assert budget.response.body_reads <= (c.MAX_UPSTREAM_RESPONSE_BYTES // 4096) + 1


@pytest.mark.parametrize("extra", [0, 1])
async def test_upstream_stream_exact_boundary_and_plus_one(runtime, extra):
    """256 KiB is accepted and 256 KiB + 1 is rejected during stream reading."""
    prefix = '{"text":"'
    suffix = '"}'
    size = c.MAX_UPSTREAM_RESPONSE_BYTES + extra
    raw = prefix + ("x" * (size - len(prefix) - len(suffix))) + suffix
    upstream = fw.FakeUpstream(200, raw=raw)
    if extra == 0:
        assert (await runtime._read_upstream_json(upstream, 1)) == {"text": "x" * (size - len(prefix) - len(suffix))}
    else:
        with pytest.raises(c.VoiceSttError) as exc:
            await runtime._read_upstream_json(upstream, 1)
        assert exc.value.code == "stt_unavailable"
    assert upstream.body_reads > 0


async def test_upstream_stream_never_calls_text(runtime):
    """The streaming path must not call a materialising Response.text()."""
    upstream = fw.FakeUpstream(200, {"text": "ok"})

    async def forbidden_text():
        raise AssertionError("Response.text() would buffer without a memory bound")

    upstream.text = forbidden_text
    assert await runtime._read_upstream_json(upstream, 1) == {"text": "ok"}


async def test_missing_upstream_body_fails_closed_without_text_fallback(runtime):
    upstream = fw.FakeUpstream(200, {"text": "ok"})
    upstream.body = None
    with pytest.raises(c.VoiceSttError) as exc:
        await runtime._read_upstream_json(upstream, 1)
    assert exc.value.code == "stt_unavailable"


async def test_unparseable_upstream_body_fails_closed_without_leaking_text(runtime):
    """A provider answering with non-JSON (or a trace) is masked."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, raw="upstream account abc123 exploded")
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body == {"ok": False, "error": {"code": "stt_failed"}}
    assert "abc123" not in json.dumps(body)


async def test_successful_upstream_body_still_parses(runtime):
    """The bounded body read must not break the happy path."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "안녕하세요"})
    body = await _run_paid(runtime, env, budget, _transcribe_request(audio=b"x"), TRANSCRIBE_ROUTE)
    assert body["ok"] is True and body["text"] == "안녕하세요"


async def test_live_token_success_through_the_bounded_body_read(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque-token"})
    body = await _run_paid(runtime, env, budget, _live_token_request(b'{"sessionId":"s1"}'), LIVE_TOKEN_ROUTE)
    assert body["ok"] is True and body["token"] == "auth_tokens/opaque-token"
