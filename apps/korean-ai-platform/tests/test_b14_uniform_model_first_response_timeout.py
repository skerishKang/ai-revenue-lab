"""B14 model first-byte, stream-idle and attempt bounds are shared (offline).

First-byte, full-attempt, and post-byte stream-idle clocks apply uniformly.

#7241 2단계: no model, provider or host identity is written here. The cases are
built from the *effective* registry — the shipped document today, the private
registry once this host is switched — and each case is admitted by the app's own
authority for that lane: the catalog row must be installed and enabled, the
owner's exclusion rules must not refuse it, and the provider's wire must be the
OpenAI-compatible chat lane the mock transport below answers. So the same
uniformity contract is proven over whatever catalog this host serves, including
the per-provider adapter branches.
"""
from __future__ import annotations

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.b14_timeout_policy import (
    CONNECT_SECONDS, READ_SECONDS, WRITE_SECONDS, POOL_SECONDS,
    build_provider_http_timeout,
)
from app.pilot.catalog import get_catalog_by_id
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)

from _registry_values import model_rows, provider_of

#: The endpoint lane these transports model: the plain OpenAI-compatible chat
#: completions wire every platform provider serves.
_CHAT_WIRE = "chat/completions"


def _row(row: dict) -> tuple[str, str, str]:
    """(model_id, upstream_model, platform_provider_id) for one registry row."""
    return row["id"], row["upstream_model"], row.get("provider_id") or provider_of(row["id"])


def _wire_served(upstream_model: str) -> str:
    """The endpoint lane an adapter serves this model on, asked of the adapters.

    A provider adapter that owns a vendor-specific wire declares it in its own
    table; every other platform provider answers on the OpenAI-compatible chat
    completions lane these transports model.
    """
    from app.pilot.opencode_go_wire import _WIRE as _VENDOR_WIRES

    return _VENDOR_WIRES.get(upstream_model) or _CHAT_WIRE


def _adapter_cases() -> list[tuple[str, str, str]]:
    """(model_id, upstream_model, platform_provider_id) per answerable row.

    A row takes this contract when the app would actually route it to the chat
    lane: an installed, enabled catalog row that the owner's exclusion rules do
    not refuse and whose adapter wire is chat/completions. A vendor-specific
    wire envelope is that adapter's own suite, not a uniform-timeout question,
    and an excluded or uninstalled row never reaches a provider at all — both are
    asked as their own contracts elsewhere. ``max_tokens`` is supplied below so
    no row depends on a wire that mandates an output budget.
    """
    cases = []
    for row in model_rows():
        model_id, upstream_model, provider_id = _row(row)
        model = get_catalog_by_id(model_id)
        if model is None or not model.enabled:
            continue
        if _wire_served(upstream_model) != _CHAT_WIRE:
            continue
        if excluded_from_owner_customer_selection(model_id):
            continue
        if free_candidate_excluded_from_execution(
            model_id, upstream_model=upstream_model, platform_provider_id=provider_id
        ):
            continue
        cases.append((model_id, upstream_model, provider_id))
    return cases


@pytest.mark.parametrize("model_id", [None, *[row["id"] for row in model_rows()]])
def test_uniform_wait_all_model_ids(model_id):
    assert CONNECT_SECONDS == 15.0 and READ_SECONDS == 20.0
    timeout = build_provider_http_timeout(model_id)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        15.0, 20.0, WRITE_SECONDS, POOL_SECONDS
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.parametrize("model_id,upstream,provider_id", _adapter_cases())
async def test_completed_and_stream_adapter_transport_no_early_cut(
    monkeypatch, stream, model_id, upstream, provider_id,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id="": {"Content-Type": "application/json"},
    )
    observed = []

    def respond(request):
        observed.append((request.extensions["timeout"]["connect"],
                         request.extensions["timeout"]["read"],
                         request.extensions["timeout"]["write"],
                         request.extensions["timeout"]["pool"]))
        if stream:
            return httpx.Response(
                200, content=(
                    b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                    b'data: [DONE]\n\n'
                ),
            )
        return httpx.Response(200, json={
            "model": upstream,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    arguments = dict(
        model_id=model_id, upstream_model=upstream, provider="synthetic",
        platform_provider_id=provider_id,
        messages=[{"role": "user", "content": "Reply OK."}],
        max_tokens=16,
        transport=httpx.MockTransport(respond),
    )
    if stream:
        events = [event async for event in plat.stream_platform_chat_completions(**arguments)]
        assert any(event.delta_content == "OK" for event in events)
        assert events[-1].done
    else:
        result = await plat.call_platform_chat_completions(**arguments)
        assert result["choices"][0]["message"]["content"] == "OK"
    assert observed == [(15.0, 20.0, 120.0, 60.0)]
