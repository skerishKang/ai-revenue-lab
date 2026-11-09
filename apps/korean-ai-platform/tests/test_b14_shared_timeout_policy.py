"""B14 phase and cumulative timeout policy across offline provider adapters.

The Cloudflare Python Fetch/HTTPX patch is not simulated here. Tests check
shared B14 configuration and mock-only request behavior.

#7241 3a: the adapters exercised below are selected from the effective
registry rather than named, and the OpenAI-compatible wire suffix is read back
from the adapter's own URL construction. Only the shared timeout policy
constants (the subject under test) are written here.
"""
import asyncio
import ast
import logging
from pathlib import Path

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot import gateway as gw
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.b14_timeout_policy import (
    CONNECT_SECONDS, READ_SECONDS, ATTEMPT_SECONDS, WRITE_SECONDS, POOL_SECONDS,
    GATEWAY_WALL_SECONDS, ENGINE_MAX_WALL_SECONDS,
    build_provider_http_timeout,
)
from app.pilot.errors import UpstreamTimeout
from app.pilot.owner_model_exclusions import free_candidate_excluded_from_execution
from app.pilot.gateway import _protocol_for
from _registry_values import adapter_for, model_rows

from _registry_values import require_owner_document

require_owner_document()

FIXED = (15.0, 20.0, 120.0, 60.0)


def values(timeout):
    return timeout.connect, timeout.read, timeout.write, timeout.pool


def _compatible_suffix() -> str:
    """The OpenAI-compatible completion suffix, from the shared adapter.

    The suffix names a wire, which is a deployment surface, so it is read out
    of the shared platform adapter's own URL construction instead of being
    written here (#7241 3a).
    """
    source = Path(plat.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if (
                isinstance(part, ast.Constant)
                and isinstance(part.value, str)
                and part.value.startswith("/")
                and "completion" in part.value
            ):
                return part.value
    raise AssertionError("the shared adapter no longer builds a completion URL")


def _adapter_cases() -> list[tuple[str, str, str]]:
    """One ``(provider, model, upstream)`` case per shared-adapter Provider.

    The cases are registry rows whose Provider speaks the shared
    OpenAI-compatible adapter wire, is not an owner-excluded free candidate
    (that lane never reaches the wire, so it cannot stand for the timeout
    contract), and is not served by a Provider-specific transport. One row per
    Provider keeps the parameters short.
    """
    compatible = _compatible_suffix().strip("/")
    cases: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in model_rows():
        provider_id = row["provider_id"]
        if provider_id in seen:
            continue
        try:
            adapter_for(provider_id)
        except AssertionError:
            continue
        if free_candidate_excluded_from_execution(
            row["id"],
            upstream_model=row["upstream_model"],
            platform_provider_id=provider_id,
        ):
            continue
        if _protocol_for(provider_id, row["upstream_model"]) != compatible:
            continue
        seen.add(provider_id)
        cases.append((provider_id, row["id"], row["upstream_model"]))
    assert cases, "the effective registry declares no shared-adapter Provider"
    return cases


def _first_adapter_case() -> tuple[str, str, str]:
    return _adapter_cases()[0]


def test_single_source_all_surfaces_and_engine_budget_remain_bounded():
    assert (CONNECT_SECONDS, READ_SECONDS, WRITE_SECONDS, POOL_SECONDS) == FIXED
    assert values(build_provider_http_timeout()) == FIXED
    assert values(runtime_config.build_http_timeout()) == FIXED
    assert gw._UPSTREAM_RETRY_BUDGET_SECONDS == GATEWAY_WALL_SECONDS == 55.0
    assert ATTEMPT_SECONDS == 40.0
    assert ENGINE_MAX_WALL_SECONDS == 60.0
    assert 0 < min(FIXED)
    assert CONNECT_SECONDS == 15.0
    assert READ_SECONDS == 20.0
    assert gw._UPSTREAM_RETRY_MAX_RETRIES == 2
    assert values(build_provider_http_timeout()) == values(build_provider_http_timeout())


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider,model,upstream", _adapter_cases())
async def test_actual_adapter_has_shared_phase_values_and_exact_upstream(
    monkeypatch, stream, provider, model, upstream,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    native_client = httpx.AsyncClient
    effective = []
    urls = []
    # The shared adapter's own completion suffix decides the address; the case
    # already proved this Provider speaks that wire, so the address is read
    # from the app rather than spelled here.
    compatible_suffix = _compatible_suffix()

    def client(*args, **kwargs):
        t=kwargs["timeout"]
        effective.append(values(t))
        assert isinstance(kwargs.get("transport"), httpx.MockTransport)
        return native_client(*args, **kwargs)

    async def handler(request):
        urls.append(str(request.url))
        assert request.headers["Content-Type"] == "application/json"
        assert request.method == "POST"
        assert request.url.path.endswith(compatible_suffix)
        import json
        obj=json.loads(request.content)
        assert obj["model"] == upstream
        assert obj["messages"] == [{"role":"user","content":"safe synthetic"}]
        assert obj.get("stream") is True if stream else "stream" not in obj
        if stream:
            return httpx.Response(
                200, content=(
                    'data: {"id":"mock-one","model":"'+upstream+
                    '","choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                    'data: [DONE]\n\n'
                ).encode(),
            )
        return httpx.Response(
            200, json={"id":"mock-one","model":upstream,
                       "choices":[{"message":{"role":"assistant","content":"OK"},
                                   "finish_reason":"stop"}]},
        )

    monkeypatch.setattr(plat.httpx, "AsyncClient", client)
    kwargs=dict(model_id=model, upstream_model=upstream, provider=provider,
                platform_provider_id=provider,
                messages=[{"role":"user","content":"safe synthetic"}],
                transport=httpx.MockTransport(handler))
    if stream:
        chunks=[c async for c in plat.stream_platform_chat_completions(**kwargs)]
        assert any(c.done is True for c in chunks)
    else:
        result=await plat.call_platform_chat_completions(**kwargs)
        assert result["choices"][0]["message"]["content"] == "OK"
    assert effective == [FIXED]
    assert len(urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_sensenova_timeout_is_logged_without_exception_secrets(
    monkeypatch, caplog, stream,
):
    provider, model, upstream = _first_adapter_case()
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    calls=[]

    async def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("PRIVATE_TOKEN_AND_MODEL_OUTPUT")
    kwargs=dict(model_id=model,
                upstream_model=upstream,
                platform_provider_id=provider,provider=provider,
                messages=[{"role":"user","content":"safe synthetic"}],
                transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plat.stream_platform_chat_completions(**kwargs):
                    pass
            else:
                await plat.call_platform_chat_completions(**kwargs)
    assert len(calls)==1
    assert f"b14_provider_attempt_timeout provider={provider} reason=first_byte mode={'stream' if stream else 'completed'}" in caplog.text
    assert "PRIVATE_TOKEN_AND_MODEL_OUTPUT" not in caplog.text
