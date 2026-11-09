"""#7156: the last completed candidate is not cut at the streaming first-byte bound.

A completed (non-streaming) provider response sends its first body byte only
after the whole answer, reasoning included, is generated. The first-byte clock is
therefore a total-generation clock on that path. Cutting at it is right while a
fallback candidate remains (the chain moves on sooner), but on the last candidate
it only turns a slow answer into a 504: the nightly Pro grade smoke on
2026-11-07 failed with ``upstream_timeout`` / ``first_byte`` at 15.04 s while the
same model answered the other paid grades in 10.6 s and 14.6 s that night.

Pinned here:

* outside the final completed attempt nothing changes (first-byte cut, httpx
  read = stream idle);
* inside it, a late first byte inside the attempt budget is returned, a first
  byte past the attempt budget is still cut (``attempt_total``), and connect
  stays bound by the first-byte value;
* the gateway marks only the last candidate of the chain.

No provider is contacted.

#7241 3단계: the default policy numbers, the single-candidate route and the
gateway surface are read from the app. The paid route driven below is the one
whose Provider is served by a single pinned candidate (so the route is its own
last candidate) and whose readiness can be satisfied from an environment
binding — both discovered from the registry and the registered Provider specs.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.pilot import router_core
from app.pilot.b14_timeout_policy import (
    ATTEMPT_TIMEOUT_ENV,
    CHAIN_BUDGET_ENV,
    FIRST_BYTE_TIMEOUT_ENV,
    STREAM_IDLE_TIMEOUT_ENV,
    ProviderAttemptTimeout,
    build_provider_http_timeout,
    effective_first_byte_seconds,
    final_completed_attempt,
    first_byte_bound_is_attempt_total,
    get_timeout_policy,
    iter_provider_response_bytes,
    send_provider_request,
)
from app.pilot.errors import UpstreamServerError
from app.pilot.model_registry_file import retired_model_ids
from app.pilot.owner_model_exclusions import (
    excluded_from_owner_customer_selection,
    free_candidate_excluded_from_execution,
)
from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

from _pilot_lane_paths import chat_surface
from _registry_values import model_rows, provider_row

#: The gateway surface these cases call, read from the mounted router.
CHAT_COMPLETIONS = chat_surface()

#: The graded route the chain cases drive: the free grade's primary and the
#: remaining pinned candidates behind it, in the order the walk visits them.
TIER_DEFAULT_MODEL = effective_tier_default()
FREE_ROSTER = tuple(effective_tier_fallback()["free"])


def _roster_ids() -> set[str]:
    """Every identity a product grade pins on its own (primary + fallbacks)."""
    roster = {effective_tier_default()}
    for fallback in effective_tier_fallback().values():
        roster.update(fallback)
    return roster


#: Capabilities a plain chat route may declare; anything else is a specialised
#: route onboarded for its own contract.
_PLAIN_CHAT_PROFILE = frozenset({"chat", "coding"})


def _single_candidate_route() -> dict:
    """The route whose own candidate list is a single entry: an explicit pin.

    A route qualifies when its Provider

    * serves exactly one registered model,
    * owns no retirement metadata (a Provider that retired an identity is
      served through the chain that still carries it),
    * is addressed on the OpenAI-compatible wire (``platform_secret``),
    * publishes the context window its Provider bills against (a route that
      leaves it unpublished is a separate intake question, not the timeout
      contract pinned here),

    and that model is not on any product grade roster, so nothing but its own
    id selects it, neither owner exclusion removes it from an execution
    candidate, it declares no capability beyond the plain chat/agent profile,
    and it is not a free-marked lane identity (those are the free family, whose
    routing is the separate free-route contract). Such a route has no fallback
    behind it and is, in the gateway's own terms, its own last candidate.
    """
    rows = [row for row in model_rows() if row.get("enabled", True)]
    roster = _roster_ids()
    retired = retired_model_ids()
    per_provider: dict[str, int] = {}
    for row in rows:
        per_provider[row["provider_id"]] = per_provider.get(row["provider_id"], 0) + 1
    candidates = [
        row for row in rows
        if row["id"] not in roster
        and not excluded_from_owner_customer_selection(row["id"])
        and not free_candidate_excluded_from_execution(row["id"])
        and per_provider[row["provider_id"]] == 1
        and row["provider_id"] not in {item.split("/", 1)[0] for item in retired}
        and provider_row(row["provider_id"]).get("credential_source") == "platform_secret"
        and (row.get("context_window") or 0) > 0
        and set(row.get("capabilities") or ()) <= _PLAIN_CHAT_PROFILE
        and not str(row["upstream_model"]).casefold().endswith("-free")
    ]
    assert len(candidates) <= 1, "the single-candidate route is not unique"
    return candidates[0] if candidates else None


class _EvidencedRow(dict):
    """A selected registry row that reports whether it was actually selected.

    Reading the row is guarded by :meth:`is_evidenced` so a document with no
    such route skips the pin instead of failing on a route it never selected.
    """

    @staticmethod
    def is_evidenced() -> bool:
        return True


class _NoEvidencedRow(_EvidencedRow):
    @staticmethod
    def is_evidenced() -> bool:
        return False


_SELECTED_ROW = _single_candidate_route()
SINGLE_ROW = _EvidencedRow(_SELECTED_ROW) if _SELECTED_ROW else _NoEvidencedRow()
SINGLE_MODEL = SINGLE_ROW["id"] if _SELECTED_ROW else ""
SINGLE_BINDING = (
    provider_row(SINGLE_ROW["provider_id"])["credential_binding_name"]
    if _SELECTED_ROW else ""
)


def _present_credentials(monkeypatch, model_ids) -> None:
    """Make a platform credential available for every Provider routed here.

    The binding slot is the one the app registered for that Provider, so no
    credential name is written in this suite.
    """
    from app.pilot import platform_secrets as ps

    for model_id in model_ids:
        spec = ps.get_platform_provider(model_id.split("/", 1)[0])
        binding = getattr(spec, "credential_binding_name", "")
        if binding:
            monkeypatch.setenv(binding, "synthetic-credential-not-a-secret")


class _DelayedByteStream(httpx.AsyncByteStream):
    def __init__(self, pieces: list[tuple[float, bytes]]) -> None:
        self.pieces = pieces

    async def __aiter__(self):
        for delay, chunk in self.pieces:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


@pytest.fixture(autouse=True)
def _clear_overrides(monkeypatch):
    for name in (FIRST_BYTE_TIMEOUT_ENV, ATTEMPT_TIMEOUT_ENV,
                 STREAM_IDLE_TIMEOUT_ENV, CHAIN_BUDGET_ENV):
        monkeypatch.delenv(name, raising=False)


def _policy(monkeypatch, *, first, attempt, idle, chain):
    monkeypatch.setenv(FIRST_BYTE_TIMEOUT_ENV, str(first))
    monkeypatch.setenv(ATTEMPT_TIMEOUT_ENV, str(attempt))
    monkeypatch.setenv(STREAM_IDLE_TIMEOUT_ENV, str(idle))
    monkeypatch.setenv(CHAIN_BUDGET_ENV, str(chain))


async def _read(pieces):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=_DelayedByteStream(pieces))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        try:
            return b"".join([
                chunk async for chunk in iter_provider_response_bytes(
                    response, started_at=started_at,
                )
            ])
        finally:
            await response.aclose()


# --------------------------------------------------------------- policy level
def test_the_flag_is_off_by_default_and_resets_after_the_block():
    assert first_byte_bound_is_attempt_total() is False
    with final_completed_attempt(True):
        assert first_byte_bound_is_attempt_total() is True
        with final_completed_attempt(False):
            assert first_byte_bound_is_attempt_total() is False
        assert first_byte_bound_is_attempt_total() is True
    assert first_byte_bound_is_attempt_total() is False


def test_effective_first_byte_is_the_attempt_budget_only_on_the_final_attempt():
    """Outside the final attempt the shipped first-byte bound applies verbatim."""
    policy = get_timeout_policy()
    assert effective_first_byte_seconds(policy) == policy.first_byte_seconds
    with final_completed_attempt(True):
        assert effective_first_byte_seconds(policy) == policy.attempt_seconds


@pytest.mark.asyncio
async def test_a_late_whole_answer_is_cut_when_a_fallback_remains(monkeypatch):
    """Unchanged behavior: a candidate with a fallback after it is cut early."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with pytest.raises(ProviderAttemptTimeout) as raised:
        await _read([(0.15, b'{"choices":[]}')])
    assert raised.value.reason == "first_byte"


@pytest.mark.asyncio
async def test_a_late_whole_answer_is_returned_on_the_final_attempt(monkeypatch):
    """The same late answer is kept when no candidate remains after it."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with final_completed_attempt(True):
        body = await _read([(0.15, b'{"choices":'), (0.0, b'[]}')])
    assert body == b'{"choices":[]}'


@pytest.mark.asyncio
async def test_the_final_attempt_is_still_bounded_by_the_attempt_budget(monkeypatch):
    _policy(monkeypatch, first=0.05, attempt=0.20, idle=0.10, chain=1.0)
    with final_completed_attempt(True):
        with pytest.raises(ProviderAttemptTimeout) as raised:
            await _read([(0.40, b'{"choices":[]}')])
    assert raised.value.reason == "attempt_total"


async def _read_after_header_delay(delay: float):
    async def respond(request):
        await asyncio.sleep(delay)
        return httpx.Response(200, content=b'{"choices":[]}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        response, started_at = await send_provider_request(
            client, "POST", "https://synthetic-provider.example/chat",
            json={"input": "offline fixture"},
        )
        try:
            return b"".join([
                chunk async for chunk in iter_provider_response_bytes(
                    response, started_at=started_at,
                )
            ])
        finally:
            await response.aclose()


@pytest.mark.asyncio
async def test_late_response_headers_follow_the_same_rule(monkeypatch):
    """A provider that holds its headers until the answer is done is treated alike."""
    _policy(monkeypatch, first=0.05, attempt=0.50, idle=0.20, chain=1.0)
    with pytest.raises(ProviderAttemptTimeout) as raised:
        await _read_after_header_delay(0.15)
    assert raised.value.reason == "first_byte"
    with final_completed_attempt(True):
        assert await _read_after_header_delay(0.15) == b'{"choices":[]}'


def test_the_socket_read_wait_follows_the_attempt_budget_but_connect_stays_bound():
    """The socket bounds restate the same policy, so they are read off it."""
    policy = get_timeout_policy()
    default = build_provider_http_timeout("any/model")
    assert (default.connect, default.read) == (
        policy.first_byte_seconds, policy.stream_idle_seconds,
    )
    with final_completed_attempt(True):
        final = build_provider_http_timeout("any/model")
    assert (final.connect, final.read) == (
        policy.first_byte_seconds, policy.attempt_seconds,
    )
    assert (final.write, final.pool) == (default.write, default.pool)


# -------------------------------------------------------------- gateway level
def _ok(upstream_model: str) -> dict:
    return {
        "id": "cmpl-7156",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


def test_the_gateway_marks_only_the_last_candidate_of_a_fallback_chain(client, monkeypatch):
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    _present_credentials(monkeypatch, FREE_ROSTER)
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)
    roster = [TIER_DEFAULT_MODEL, *FREE_ROSTER]
    seen: list[tuple[str, bool]] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        seen.append((model_id, first_byte_bound_is_attempt_total()))
        if len(seen) < len(roster):
            raise UpstreamServerError()
        return _ok(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = client.post(CHAT_COMPLETIONS, json={
        "model": TIER_DEFAULT_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "business14": {"product_tier": "free"},
    })

    assert response.status_code == 200
    assert [model for model, _ in seen] == roster
    assert [flag for _, flag in seen] == [False] * (len(roster) - 1) + [True]
    assert first_byte_bound_is_attempt_total() is False


def test_a_single_candidate_route_is_its_own_last_candidate(client, monkeypatch):
    """A route with no fallback is marked final."""
    from app.pilot import platform as plat

    if not SINGLE_ROW.is_evidenced():
        pytest.skip("the effective registry document carries no evidenced single-candidate route")
    monkeypatch.setenv(SINGLE_BINDING, "synthetic-credential-not-a-secret")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list[bool] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        seen.append(first_byte_bound_is_attempt_total())
        return _ok(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = client.post(CHAT_COMPLETIONS, json={
        "model": SINGLE_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    })

    assert response.status_code == 200
    assert seen == [True]
