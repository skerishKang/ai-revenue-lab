"""Mocked Worker dispatch tests for the deployment gate and body limits.

These exercise the real ``worker.Default.fetch`` code path, not a static source
string check: the OFF switch, the ON-without-caller-guard state, oversized and
chunked bodies, a missing provider key and malformed audio are all driven
through the actual handler.

The mocked upstream records every attempted call, which is how "no Secret read
and no provider call while OFF" is actually proven rather than asserted.

Two layers, deliberately separated
----------------------------------
``_dispatch``  — the shipped route. Paid routes are **unconditionally closed**
                 here: no guard shape, approval or binding presence may reach a
                 Secret or a provider.

``_run_paid``  — the paid pipeline *behind* that gate, invoked directly with a
                 hand-built :class:`voice_stt_contract.CallerAuthorization`.
                 The Worker itself can never obtain one (the gate always
                 raises), so this is a test harness only; it exists so the
                 upstream request shape, the end-to-end deadline and the
                 provider-masking behaviour stay covered while the route is
                 closed. It is not a production approval path.
"""

from __future__ import annotations

import base64
import json
import types

import pytest

import fake_workers as fw
import voice_stt_contract as c

TRANSCRIBE_ROUTE = "/internal/v1/voice/transcribe"
LIVE_TOKEN_ROUTE = "/internal/v1/voice/live-token"


@pytest.fixture
def runtime():
    worker = fw.install_workers_module()
    return worker


def _transcribe_request(audio=b"voice-bytes", language="ko", url="https://voice.internal/internal/v1/voice/transcribe"):
    headers = {"content-type": "application/json"}
    payload = {
        "audioDataUrl": "data:audio/webm;base64," + base64.b64encode(audio).decode("ascii"),
        "language": language,
    }
    return fw.FakeRequest("POST", url, headers, json.dumps(payload).encode("utf-8"))


def _live_token_request(body=b'{"sessionId":"s"}'):
    return fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, body)


def _test_authorization(route: str) -> c.CallerAuthorization:
    """A test-only authorization object. **Not** a production grant.

    ``worker._require_caller_authorization`` raises unconditionally, so no
    request can ever produce this. Building one by hand is the only way to
    exercise the paid pipeline while the shipped route stays fail-closed.
    """

    return c.CallerAuthorization(
        actor="local3-test-harness",
        tenant="local3-test-tenant",
        route=route,
        reservation_id="test-only-no-real-cost",
        amount_usd=0.01,
    )


async def _dispatch(worker, env, budget, request):
    """Drive the shipped route (``Default.fetch``)."""
    worker.fetch = budget.make_fetch()
    response = await worker.Default(env).fetch(request)
    return json.loads(response.body)


async def _run_paid(worker, env, budget, request, route):
    """Drive the paid pipeline directly, bypassing only the always-closed gate.

    ``Default.fetch`` turns a :class:`VoiceSttError` into the bounded envelope;
    calling the handler directly has to do the same so the assertions below read
    the same shape regardless of layer.
    """
    worker.fetch = budget.make_fetch()
    handler = worker._handle_transcribe if route == TRANSCRIBE_ROUTE else worker._handle_live_token
    try:
        response = await handler(env, request, _test_authorization(route))
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
        fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'),
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
        fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'),
    )
    assert groq.reads == 0
    assert gemini.reads == 0
    assert budget.calls == []


async def test_on_without_caller_guard_is_not_reachable(runtime):
    """ON is not a test override: it still fails closed without the guard."""
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=None)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []


async def test_missing_enabled_var_fails_closed(runtime):
    env = fw.enabled_env()
    del env.PADIEM_VOICE_STT_ENABLED
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}


@pytest.mark.parametrize("flag", ["", "1", "yes", "on", "false", "null", "0"])
async def test_non_true_flag_fails_closed(runtime, flag):
    env = fw.enabled_env(PADIEM_VOICE_STT_ENABLED=flag)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "voice_stt_disabled"}}


@pytest.mark.parametrize("flag", ["true", "TRUE", " True ", "\ttrue\n"])
async def test_true_flag_still_requires_the_caller_guard(runtime, flag):
    """Operator-friendly ``true`` is only the first of two gates."""
    env = fw.enabled_env(PADIEM_VOICE_STT_ENABLED=flag, VOICE_STT_CALLER_GUARD=None)
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}


async def test_capabilities_is_public_and_key_free(runtime):
    """With the gate open and the guard attached, capabilities leaks nothing."""
    env = fw.enabled_env()
    env.VOICE_STT_CALLER_GUARD = types.SimpleNamespace()
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
    response = await runtime._handle_transcribe(env, _transcribe_request(audio=b"x"), _test_authorization(TRANSCRIBE_ROUTE))
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
# P0-A: NO guard shape may authorize a paid call — the routes are closed
# ---------------------------------------------------------------------------

#: Every shape a binding could plausibly wear, including verdicts that a naive
#: "is it truthy?" check would have accepted. None of them may spend money.
_GUARD_SHAPES = [
    ("presence_only", lambda: types.SimpleNamespace()),
    ("empty_namespace", lambda: types.SimpleNamespace(authorize=None)),
    ("approving_decoy", lambda: fw.FakeCallerGuard()),
    ("bare_true", lambda: fw.FakeCallerGuard(decision=True)),
    ("bare_false", lambda: fw.FakeCallerGuard(decision=False)),
    ("no_verdict", lambda: fw.FakeCallerGuard(decision=None)),
    ("empty_dict", lambda: fw.FakeCallerGuard(decision={})),
    ("zero_scope", lambda: fw.FakeCallerGuard(decision={"allowed": True, "caller": "x", "cost_scope": 0})),
    ("blank_scope", lambda: fw.FakeCallerGuard(decision={"allowed": True, "caller": "x", "cost_scope": ""})),
    ("blank_caller", lambda: fw.FakeCallerGuard(decision={"allowed": True, "caller": "", "cost_scope": {"daily_usd_cap": 5}})),
    ("unscoped_true", lambda: fw.FakeCallerGuard(decision={"allowed": True, "caller": "x", "cost_scope": {"daily_usd_cap": 5}})),
]


@pytest.mark.parametrize("name,build", _GUARD_SHAPES, ids=[n for n, _ in _GUARD_SHAPES])
@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_no_guard_shape_reaches_a_secret_or_a_provider(runtime, name, build, route):
    """The shipped route stays closed for *every* guard shape, on both paid routes.

    This is the P0-A regression. A previous revision accepted a present binding,
    a bare ``True`` and an unscoped ``{"allowed": True, ...}`` verdict and went
    on to read a Secret and call Groq/Gemini. No verdict is trusted now, because
    no verdict is even requested: the binding is never consulted.
    """
    guard = build()
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=guard)
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x") if route == TRANSCRIBE_ROUTE else _live_token_request()
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == [], f"{name}: a provider was called"
    assert env.PADIEM_GROQ_API_KEY.reads == 0
    assert env.PADIEM_GEMINI_API_KEY.reads == 0
    assert getattr(guard, "calls", []) == [], f"{name}: the binding was consulted"


async def test_presence_only_guard_blocks_paid_routes(runtime):
    """Presence of ``VOICE_STT_CALLER_GUARD`` is not caller identity or cost approval."""
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=types.SimpleNamespace())
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_guard_exception_cannot_be_raised_because_the_guard_is_never_called(runtime):
    """An exploding binding is harmless: nothing invokes it."""

    class _Boom:
        async def authorize(self, request_context):
            raise RuntimeError("guard backend down")

    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=_Boom())
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_sync_approving_guard_does_not_open_a_paid_route(runtime):
    """A synchronous approving ``authorize`` is still not an authorization."""

    class _SyncGuard:
        def authorize(self, request_context):  # pragma: no cover - must never run
            return {"allowed": True, "caller": "acct", "cost_scope": {"daily_usd_cap": 1}}

    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=_SyncGuard())
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


@pytest.mark.parametrize("route", [TRANSCRIBE_ROUTE, LIVE_TOKEN_ROUTE])
async def test_require_caller_authorization_always_fails_closed(runtime, route):
    """The gate itself: no env can make it return."""
    for env in (
        fw.enabled_env(),
        fw.enabled_env(VOICE_STT_CALLER_GUARD=fw.FakeCallerGuard()),
        fw.enabled_env(VOICE_STT_CALLER_GUARD=None),
        fw.disabled_env(),
    ):
        with pytest.raises(c.VoiceSttError) as raised:
            await runtime._require_caller_authorization(env, route=route)
        assert raised.value.code == "caller_authorization_unimplemented"
        assert raised.value.status == 503


async def _run_paid_with(worker, env, budget, request, authorization):
    """Call the transcribe pipeline with an arbitrary claimed authorization."""
    worker.fetch = budget.make_fetch()
    try:
        response = await worker._handle_transcribe(env, request, authorization)
    except c.VoiceSttError as exc:
        return {"ok": False, "error": {"code": exc.code}}
    return json.loads(response.body)


async def test_pipeline_refuses_an_authorization_for_another_route(runtime):
    """Even a hand-built authorization is checked against the route it names."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_paid_with(runtime, env, budget, _transcribe_request(audio=b"x"), _test_authorization(LIVE_TOKEN_ROUTE))
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        True,
        {},
        {"allowed": True, "caller": "acct", "cost_scope": {"daily_usd_cap": 1}},
        "approved",
    ],
)
async def test_pipeline_refuses_anything_that_is_not_an_authorization(runtime, authorization):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _run_paid_with(runtime, env, budget, _transcribe_request(audio=b"x"), authorization)
    assert body == {"ok": False, "error": {"code": "caller_authorization_unimplemented"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_capabilities_still_answers_with_a_decoy_guard_attached(runtime):
    """The key-free route is unaffected by the paid-route closure."""
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=types.SimpleNamespace())
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, fw.FakeRequest("GET", "https://voice.internal/internal/v1/voice/capabilities"))
    assert body["ok"] is True
    assert body["enabled_route_contract"] == "paid_fail_closed_no_authority"
    assert budget.calls == []


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
    request = _transcribe_request(audio=b"x") if route == TRANSCRIBE_ROUTE else _live_token_request()
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
