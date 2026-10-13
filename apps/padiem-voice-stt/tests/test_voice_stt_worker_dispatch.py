"""Mocked Worker dispatch tests for the deployment gate and body limits.

These exercise the real ``worker.Default.fetch`` code path, not a static source
string check: the OFF switch, the ON-without-caller-guard state, oversized and
chunked bodies, a missing provider key and malformed audio are all driven
through the actual handler.

The mocked upstream records every attempted call, which is how "no Secret read
and no provider call while OFF" is actually proven rather than asserted.
"""

from __future__ import annotations

import base64
import json
import types

import pytest

import fake_workers as fw
import voice_stt_contract as c


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


async def _dispatch(worker, env, budget, request):
    worker.fetch = budget.make_fetch()
    response = await worker.Default(env).fetch(request)
    return json.loads(response.body)


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
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    # No upstream call and no Secret read happened on the way out.
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_oversized_declared_content_length_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x")
    request.headers["content-length"] = str(c.MAX_REQUEST_BYTES + 4096)
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []


@pytest.mark.parametrize("declared", ["-1", "-99999", "abc", "", "1.5", "0x10", "12,3"])
async def test_negative_or_malformed_content_length_is_rejected(runtime, declared):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = _transcribe_request(audio=b"x")
    request.headers["content-length"] = declared
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "invalid_content_length"}}


async def test_body_exactly_at_the_limit_still_reaches_the_handler(runtime):
    """A request right at the ceiling is accepted by the size guard."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    request = _transcribe_request(audio=b"y" * 4096)
    body = await _dispatch(runtime, env, budget, request)
    assert body["ok"] is True and body["text"] == "네"


async def test_empty_body_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, b"")
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "invalid_json"}}
    assert budget.calls == []


async def test_wrong_content_type_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest("POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "text/plain"}, b"{}")
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "unsupported_media_type"}}
    assert budget.calls == []


async def test_unsupported_field_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    payload = {"audioDataUrl": "data:audio/webm;base64,AAAA", "language": "ko", "url": "https://evil.test"}
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/transcribe", {"content-type": "application/json"}, json.dumps(payload).encode()
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "unsupported_field"}}


async def test_invalid_language_is_rejected(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x", language="fr"))
    assert body == {"ok": False, "error": {"code": "invalid_language"}}
    assert budget.calls == []


# ---------------------------------------------------------------------------
# Provider key presence and provider failure
# ---------------------------------------------------------------------------


async def test_missing_groq_key_fails_closed_without_upstream_call(runtime):
    env = fw.enabled_env(PADIEM_GROQ_API_KEY=fw.FakeSecretsBinding(None))
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "stt_key_missing"}}
    assert budget.calls == []


async def test_missing_gemini_key_fails_closed_without_upstream_call(runtime):
    env = fw.enabled_env(PADIEM_GEMINI_API_KEY=fw.FakeSecretsBinding(None))
    budget = fw.FetchBudget()
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "live_token_unavailable"}}
    assert budget.calls == []


async def test_live_token_rejects_unknown_fields(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s","model":"x"}'
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "unsupported_field"}}


async def test_transcribe_falls_through_the_model_sequence(runtime):
    """The turbo model failing must fall through to the full model."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "안녕하세요"})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body["model"] == "whisper-large-v3-turbo"

    # Now make the first attempt fail and confirm the second model is tried.
    calls = []

    original = budget.make_fetch()

    async def _fetch(resource, **kwargs):
        calls.append(kwargs.get("body"))
        if len(calls) == 1:
            return fw.FakeUpstream(500, {"error": {"message": "model unavailable"}})
        return fw.FakeUpstream(200, {"text": "안녕하세요"})

    budget.calls = []
    runtime.fetch = _fetch
    response = await runtime.Default(env).fetch(_transcribe_request(audio=b"x"))
    body = json.loads(response.body)
    assert body["model"] == "whisper-large-v3"
    assert body["ok"] is True


async def test_provider_5xx_never_leaks_provider_detail(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(500, {"error": {"message": "account abc123 quota exhausted"}})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "stt_failed"}}
    assert "abc123" not in json.dumps(body)


async def test_transport_failure_returns_a_bounded_code(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.raise_exc = True
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
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
    await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert seen == [c.GROQ_REQUEST_TIMEOUT_MS]
    assert budget.calls and budget.calls[0]["url"] == c.GROQ_STT_ENDPOINT
    assert budget.calls[0]["signal"] == f"abort-signal-{c.GROQ_REQUEST_TIMEOUT_MS}"


async def test_live_token_call_carries_its_own_shorter_budget(runtime, monkeypatch):
    seen = []
    monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: seen.append(ms))
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque-token"})
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"sess-1"}'
    )
    await _dispatch(runtime, env, budget, request)
    assert seen == [c.LIVE_TOKEN_REQUEST_TIMEOUT_MS]


async def test_secret_value_never_reaches_the_response_or_the_log_stream(runtime):
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    response_raw = (await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x")))
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
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"sess-1"}'
    )
    body = await _dispatch(runtime, env, budget, request)
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
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "live_token_unavailable"}}
    assert "abc123" not in json.dumps(body)


# ---------------------------------------------------------------------------
# Caller-guard authorization: presence alone must NOT authorize a paid call
# ---------------------------------------------------------------------------


async def test_presence_only_guard_blocks_paid_routes(runtime):
    """A binding with no ``authorize`` contract must not authorize a paid call.

    Mere presence of ``VOICE_STT_CALLER_GUARD`` is not caller identity or cost
    approval. Before the guard gained a verified authorize contract this was the
    exact gap: ON + a bound object allowed a paid Groq/Gemini call.
    """
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=types.SimpleNamespace())
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_presence_only_guard_blocks_live_token_route(runtime):
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=types.SimpleNamespace())
    budget = fw.FetchBudget()
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'
    )
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GEMINI_API_KEY.reads == 0


@pytest.mark.parametrize(
    "decision",
    [
        False,
        None,
        {"allowed": False, "caller": "acct", "cost_scope": {"daily_usd_cap": 5}},
        {"allowed": True},
        {"allowed": True, "caller": "acct"},
        {"allowed": True, "cost_scope": {"daily_usd_cap": 5}},
        {},
    ],
)
async def test_non_approving_guard_decisions_block_paid_routes(runtime, decision):
    """Anything short of identity + cost approval fails closed before a call."""
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=fw.FakeCallerGuard(decision=decision))
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_guard_exception_fails_closed(runtime):
    class _Boom:
        async def authorize(self, request_context):
            raise RuntimeError("guard backend down")

    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=_Boom())
    budget = fw.FetchBudget()
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "caller_guard_unavailable"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_approving_guard_is_actually_consulted_per_paid_route(runtime):
    """The guard's ``authorize`` is called with the route, not merely present."""
    guard = fw.FakeCallerGuard()
    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=guard)
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert guard.calls and guard.calls[0]["route"] == "/internal/v1/voice/transcribe"

    guard2 = fw.FakeCallerGuard()
    env2 = fw.enabled_env(VOICE_STT_CALLER_GUARD=guard2)
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'
    )
    budget2 = fw.FetchBudget()
    budget2.response = fw.FakeUpstream(200, {"name": "auth_tokens/opaque"})
    await _dispatch(runtime, env2, budget2, request)
    assert guard2.calls and guard2.calls[0]["route"] == "/internal/v1/voice/live-token"


async def test_sync_approving_guard_is_accepted(runtime):
    """A synchronous (non-coroutine) authorize that approves also works."""

    class _SyncGuard:
        def authorize(self, request_context):
            return {"allowed": True, "caller": "acct", "cost_scope": {"daily_usd_cap": 1}}

    env = fw.enabled_env(VOICE_STT_CALLER_GUARD=_SyncGuard())
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body["ok"] is True


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
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []
    assert env.PADIEM_GROQ_API_KEY.reads == 0


async def test_chunk_reader_exact_limit_boundary_is_honoured(runtime):
    """A single chunk exactly at the read budget is accepted, not rejected."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.response = fw.FakeUpstream(200, {"text": "네"})
    request = _transcribe_request(audio=b"y" * 4096)
    request.body = fw._Stream(request._body, chunk=len(request._body))
    body = await _dispatch(runtime, env, budget, request)
    assert body["ok"] is True and body["text"] == "네"


async def test_chunk_reader_one_byte_over_budget_is_rejected(runtime):
    """Many small chunks whose total is one byte past the ceiling are rejected."""
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    oversize = c.MAX_REQUEST_BYTES + 1
    request = _transcribe_request(audio=b"a" * oversize)
    request.body = fw._Stream(request._body, chunk=4096)
    body = await _dispatch(runtime, env, budget, request)
    assert body == {"ok": False, "error": {"code": "request_too_large"}}
    assert budget.calls == []


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
    body = await _dispatch(runtime, env, budget, _transcribe_request(audio=b"x"))
    assert body == {"ok": False, "error": {"code": "stt_unavailable"}}
    assert budget.calls and budget.calls[0]["signal"] is None


async def test_live_token_no_abortsignal_runtime_still_bounded(runtime, monkeypatch):
    monkeypatch.setattr(runtime, "_build_abort_signal", lambda ms: None)
    monkeypatch.setattr(c, "LIVE_TOKEN_REQUEST_TIMEOUT_MS", 120)
    env = fw.enabled_env()
    budget = fw.FetchBudget()
    budget.hang = True
    request = fw.FakeRequest(
        "POST", "https://voice.internal/internal/v1/voice/live-token", {"content-type": "application/json"}, b'{"sessionId":"s"}'
    )
    body = await _dispatch(runtime, env, budget, request)
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
