"""#3977 exact-model native parameter transport contracts (no live credentials)."""
import json
from pathlib import Path

import httpx
import pytest

from app.pilot.gateway import _validate_body, _InvalidBody
from app.pilot.model_native_parameters import (
    OPTIONAL_FIELDS,
    UnsupportedModelParameter,
    validate_native_parameters,
)
from app.pilot.model_registry_file import read_registry
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.schemas import PilotChatRequest
from app.pilot.provider import _build_upstream_request

from _registry_values import (
    a_model_id,
    model_ids,
    model_rows,
    provider_of,
)


def request(model, **params):
    return _validate_body({
        "model": model,
        "messages": [{"role": "user", "content": "hello"}],
        **params,
    })


def _native_fields(model_id):
    """The model-native fields the exact route declares, per serving evidence.

    ``registered_serving_evidence()`` is the app's public report for the rows it
    has profile evidence for. The native-parameter authority itself
    (``_SUPPORTED``) is a different table — a route can declare a documented
    option there without a serving-evidence profile — so the option set is the
    union of what the two authorities say, and no field is restated here
    (#7241 3단계).
    """
    from app.pilot.model_native_parameters import _SUPPORTED
    from app.pilot.model_serving_evidence import registered_serving_evidence

    fields = set(_SUPPORTED.get(model_id, {}))
    try:
        evidence = registered_serving_evidence()
    except ValueError:
        # A host whose document does not fill every profiled identity has no
        # serving evidence to read; the native-parameter table already answered.
        evidence = ()
    for item in evidence:
        if item.model_id == model_id:
            fields |= set(item.native_override_fields)
    return fields


def _models_accepting(field):
    """Installed exact ids whose authorities declare ``field`` as documented."""
    return [mid for mid in sorted(model_ids()) if field in _native_fields(mid)]


def _models_rejecting(field):
    """Installed exact ids whose authorities do not declare ``field``."""
    return [mid for mid in sorted(model_ids()) if field not in _native_fields(field)]


def _first_model_with(field):
    """One installed exact id that documents ``field``, or ``None``.

    ``None`` means the effective registry registers no route that documents the
    option; the case that needs one skips rather than borrowing a route the
    document does not carry.
    """
    accepting = _models_accepting(field)
    return accepting[0] if accepting else None


def _provider_label(model_id):
    """The Provider display name the registry itself carries for this row."""
    for row in model_rows():
        if row["id"] == model_id:
            return row["provider_name"]
    raise AssertionError("model is not in the effective registry")


@pytest.mark.parametrize("model", sorted(model_ids()))
def test_every_registered_model_omits_hidden_defaults(model):
    b = request(model)
    assert b["temperature"] is None
    assert b["max_tokens"] is None
    assert b["model_parameters"] == {}


def _reasoning_vocabulary(model_id):
    """The accepted reasoning levels the exact route's own rule declares.

    The app keeps one authority for this (``_SUPPORTED``), read here exactly as
    ``model_serving_evidence`` reads it, so no level is restated in this file.
    """
    from app.pilot.model_native_parameters import _SUPPORTED

    rule = _SUPPORTED.get(model_id, {}).get("reasoning_effort")
    assert rule is not None, f"{model_id} reports a field its rule does not carry"
    return sorted(rule)


def test_model_native_google_reasoning_only_when_explicit():
    documented = _models_accepting("reasoning_effort")
    if not documented:
        # The effective document registers no route that documents the reasoning
        # choice, so there is no vocabulary to pin (#7241 3단계).
        pytest.skip("the effective registry registers no route with a reasoning choice")
    for model_id in documented:
        accepted = _reasoning_vocabulary(model_id)
        for level in accepted:
            assert request(model_id, reasoning_effort=level)["model_parameters"] == {
                "reasoning_effort": level,
            }
        with pytest.raises(_InvalidBody, match="reasoning_effort"):
            request(model_id, reasoning_effort="none")


def test_unknown_native_field_is_not_silently_discarded():
    known = set(OPTIONAL_FIELDS)
    invent = lambda base: base + "-unverified"  # noqa: E731 - a non-contract field name
    unknown_field = invent(sorted(known)[0])
    assert unknown_field not in known
    with pytest.raises(UnsupportedModelParameter, match="unsupported model-native fields"):
        validate_native_parameters(a_model_id(), {unknown_field: {"type": "enabled"}})


def test_native_sensenova_exact_documented_sampling():
    model = _first_model_with("top_p")
    if model is None:
        pytest.skip("the effective registry registers no route with documented sampling")
    sampling = (
        ("top_p", 0.95), ("top_k", 20), ("min_p", 0.0),
        ("presence_penalty", 1.5), ("repetition_penalty", 1.0),
    )
    for name, _value in sampling:
        assert name in _native_fields(model), f"{model} does not document {name}"
    native = request(model, **dict(sampling))["model_parameters"]
    assert native == dict(sampling)


@pytest.mark.parametrize("model", sorted(model_ids()))
def test_unverified_reasoning_field_is_rejected_before_egress(model):
    if "reasoning_effort" in _native_fields(model):
        pytest.skip("route documents the reasoning choice")
    with pytest.raises(_InvalidBody, match="not documented"):
        request(model, reasoning_effort="high")


@pytest.mark.parametrize("params", [
    {"top_p": 1.5}, {"top_k": 0}, {"min_p": -0.1},
    {"presence_penalty": 9}, {"repetition_penalty": 0},
    {"top_p": True}, {"top_p": float("nan")},
])
def test_invalid_native_values_are_rejected(params):
    model = _first_model_with("top_p")
    if model is None:
        pytest.skip("the effective registry registers no route with documented sampling")
    with pytest.raises(_InvalidBody):
        request(model, **params)


def test_no_global_4096_model_ceiling_and_explicit_values_unchanged():
    model = _first_model_with("reasoning_effort") or a_model_id()
    assert request(model, max_tokens=65536)["max_tokens"] == 65536
    assert request(model, temperature=1.0)["temperature"] == 1.0
    assert request(model, max_tokens=2147483648)["max_tokens"] == 2147483648
    assert PilotChatRequest(model="x", messages=[{"role": "user", "content": "hi"}]).temperature is None
    assert _build_upstream_request("k", [{"role": "user", "content": "hi"}], None, None, "exact") == {
        "model": "exact", "messages": [{"role": "user", "content": "hi"}],
    }


@pytest.fixture
def google_native_transport(monkeypatch):
    from app.pilot import platform_secrets as ps
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    # Only mock transport, no real Provider or credentials.
    monkeypatch.setattr(ps, "resolve_secret", lambda spec: "synthetic-placeholder-for-mock-123456")
    # Routing tests use a test-only provider rather than altering live registry.
    return ps


def _reasoning_route():
    """An installed exact id that documents the reasoning choice, or ``None``."""
    return _first_model_with("reasoning_effort")


def _registry_silent_route():
    """An installed exact id the registry gives no native override for, or ``None``."""
    silent = _models_rejecting("reasoning_effort")
    return silent[0] if silent else None


@pytest.mark.asyncio
async def test_platform_completed_exact_native_parameters(google_native_transport, monkeypatch):
    seen = {}
    from app.pilot import platform as plt
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    model_id = _reasoning_route()
    if model_id is None:
        pytest.skip("the effective registry registers no route with a reasoning choice")
    upstream = next(row["upstream_model"] for row in model_rows() if row["id"] == model_id)
    async def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "id": "synthetic", "model": upstream,
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })
    await call_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream,
        provider=_provider_label(model_id),
        platform_provider_id=provider_of(model_id),
        messages=[{"role": "user", "content": "hi"}],
        model_parameters={"reasoning_effort": "low"},
        max_tokens=65536,
        transport=httpx.MockTransport(handler),
    )
    assert seen["body"]["model"] == upstream
    # #6838: a caller's reasoning value never reaches the platform lane. The
    # public registry declares no support here, so the option is omitted.
    assert "reasoning_effort" not in seen["body"]
    assert seen["body"]["max_tokens"] == 65536
    assert "temperature" not in seen["body"]


@pytest.mark.asyncio
async def test_platform_rejects_unsupported_before_upstream(monkeypatch):
    from app.pilot import platform as plt
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    async def handler(req):
        raise AssertionError("should not call unsupported upstream")
    model_id = _registry_silent_route()
    if model_id is None:
        pytest.skip("the effective registry registers no route silent about the option")
    upstream = next(row["upstream_model"] for row in model_rows() if row["id"] == model_id)
    with pytest.raises(Exception, match="not documented"):
        await call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider=_provider_label(model_id),
            platform_provider_id=provider_of(model_id),
            messages=[{"role": "user", "content": "hi"}],
            # #6838: only the reasoning choice moved to B14's authority; this
            # other model-native field is still refused before any upstream call.
            model_parameters={"top_p": 0.5},
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.asyncio
async def test_platform_stream_exact_native_parameter_parity(monkeypatch):
    from app.pilot import platform as plt
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers", lambda spec, model_id=None: {"Content-Type": "application/json"})
    seen = {}
    model_id = _reasoning_route()
    if model_id is None:
        pytest.skip("the effective registry registers no route with a reasoning choice")
    upstream = next(row["upstream_model"] for row in model_rows() if row["id"] == model_id)
    async def handler(req):
        seen["body"] = json.loads(req.content)
        sse = (
            'data: {"id":"synthetic","model":"' + upstream + '","choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=sse.encode("utf-8"), headers={"content-type": "text/event-stream"})

    events = []
    async for event in stream_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream,
        provider=_provider_label(model_id),
        platform_provider_id=provider_of(model_id),
        messages=[{"role": "user", "content": "hi"}],
        model_parameters={"reasoning_effort": "high"},
        transport=httpx.MockTransport(handler),
    ):
        events.append(event)
    assert seen["body"]["model"] == upstream
    # #6838: the platform lane no longer forwards a caller's reasoning value.
    # This model declares no support in the public registry, so it is omitted.
    assert "reasoning_effort" not in seen["body"]
    assert seen["body"]["stream"] is True
    assert "temperature" not in seen["body"]
    assert "max_tokens" not in seen["body"]
    assert any(getattr(e, "delta_content", None) == "ok" for e in events)


def test_user_surfaces_do_not_synthesize_02_or_fixed_budget():
    base = Path(__file__).resolve().parents[1]
    start = (base / "static/start.js").read_text(encoding="utf8")
    workspace = (base / "static/workspace.js").read_text(encoding="utf8")
    pilot = (base / "templates/pilot.html").read_text(encoding="utf8")
    assert "temperature: atriaPreview" not in start
    assert "max_tokens: atriaPreview" not in start
    assert "temperature: 0.2" not in workspace
    assert "maxTokens: 512" not in workspace
    assert 'name="temperature" min="0" max="2" step="0.1" value=""' in pilot
