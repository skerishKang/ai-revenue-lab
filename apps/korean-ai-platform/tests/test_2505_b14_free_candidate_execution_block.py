"""#2505: an excluded free candidate never reaches a provider network call.

The owner decision (2026-10-21) keeps an OpenCode Go free model out of the
execution candidates. This slice closes the last common boundary in B14: a
directly supplied model id and a bypassed resolver answer are both refused
before the supplier request, while a paid model, another provider's free
model and the provider adapter itself keep working.

#7241 3단계: the identities below are deployment values. The rule under test
names its own family (``FREE_CANDIDATE_PROVIDER``), so the excluded free rows,
the paid rows of the same provider and the paid row's wire are selected from
the registry and the Go wire table, then asserted against the row that was
selected. Nothing provider-specific is written here.

Every outbound call uses a synthetic transport. No provider traffic.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot import platform as plat
from app.pilot import router_core
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
from app.pilot.model_registry_file import read_registry
from app.pilot.owner_model_exclusions import (
    FREE_CANDIDATE_PROVIDER,
    free_candidate_excluded_from_execution,
)

from _registry_values import model_rows, provider_row, requires_owner_document


#: The provider the exclusion marker belongs to, as the rule itself spells it.
PROVIDER_ID = FREE_CANDIDATE_PROVIDER


def _family():
    """(free rows, paid rows, the paid row the adapter can carry) for the family.

    A registry document that registers none of the family's identities — e.g. a
    placeholder fixture carrying only example rows — answers empty tuples: the
    pins below are owner decisions about a real registration, so they are
    reported as skipped rather than silently passing on rows never selected.
    """
    rows = model_rows()
    free = tuple(
        row for row in rows if free_candidate_excluded_from_execution(row["id"])
    )
    paid = tuple(
        row for row in rows
        if row["provider_id"] == PROVIDER_ID
        and not free_candidate_excluded_from_execution(row["id"])
    )
    return free, paid


FREE_ROWS, PAID_ROWS = _family()
#: The paid row the provider's own adapter table can carry (its wire decides the
#: envelope the answer arrives in).
PAID_ROW = next(
    (row for row in PAID_ROWS if go._WIRE.get(row["upstream_model"])), None
)
_REGISTERED = bool(FREE_ROWS) and len({row["provider_id"] for row in FREE_ROWS}) == 1
_NO_FAMILY = pytest.mark.skipif(
    not _REGISTERED or PAID_ROW is None,
    reason="the effective registry document registers no route of this family",
)
PROVIDER_ROW = provider_row(PROVIDER_ID) if _REGISTERED else {}
#: The provider's display name, which the B14 call surfaces are labelled with.
PROVIDER_NAME = (
    next(row["provider_name"] for row in FREE_ROWS) if _REGISTERED else None
)
#: The credential slot of the provider under test, and another provider's slot
#: that must never be borrowed in its place.
BINDING = PROVIDER_ROW.get("credential_binding_name")
OTHER_BINDING = next(
    (
        entry["credential_binding_name"]
        for pid, entry in read_registry()["providers"].items()
        if pid != PROVIDER_ID
    ),
    None,
)

FREE_MODEL = FREE_ROWS[0]["id"] if _REGISTERED else None
FREE_UPSTREAM = FREE_ROWS[0]["upstream_model"] if _REGISTERED else None
FREE_MODEL_B = next(
    (
        row["id"] for row in FREE_ROWS[1:]
        if row["upstream_model"] != FREE_UPSTREAM
    ),
    FREE_MODEL if _REGISTERED else None,
)
PAID_MODEL = PAID_ROW["id"] if PAID_ROW else None
PAID_UPSTREAM = PAID_ROW["upstream_model"] if PAID_ROW else None
#: The provider's own wire for the paid lane (the adapter's rule table).
PAID_WIRE = PAID_UPSTREAM and go._WIRE[PAID_UPSTREAM] or None
SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "user", "content": "Say hi."}]


@pytest.fixture()
def live_mode(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved_mode = rcfg.provider_mode
    rcfg.provider_mode = "live"
    yield
    rcfg.provider_mode = saved_mode


@pytest.fixture()
def ready_route(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


@pytest.fixture()
def go_auth_stub(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    # The provider credential is server-owned; a synthetic value keeps the
    # credentialed path testable without any real secret.
    monkeypatch.setenv(
        BINDING, "synthetic-owner-key-0123456789abcdef"
    )


def _recording_transport(seen: list, *, upstream_model: str = PAID_UPSTREAM):
    def respond(request):
        seen.append(request)
        if go._WIRE.get(upstream_model) == "responses":
            # A paid lane the provider serves on its responses envelope answers
            # in that envelope, whatever the model is called.
            return httpx.Response(200, json={
                "id": "synthetic",
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "OK"}],
                }],
            })
        return httpx.Response(200, json={
            "id": "synthetic",
            "model": upstream_model,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("model_id", (FREE_MODEL, FREE_MODEL_B))
@_NO_FAMILY
def test_the_manual_route_refuses_an_excluded_free_candidate(ready_route, model_id):
    assert free_candidate_excluded_from_execution(model_id) is True
    with pytest.raises(NoSafeRoute) as caught:
        router_core.resolve_manual_route(
            model_id, product_tier="free",
        )

    assert caught.value.reason_code == "free_candidate_excluded"
    assert caught.value.upstream_called is False


@requires_owner_document
@_NO_FAMILY
def test_the_manual_route_still_resolves_the_paid_opencode_go_model(ready_route):
    assert free_candidate_excluded_from_execution(PAID_MODEL) is False
    decision = router_core.resolve_manual_route(
        PAID_MODEL, product_tier="plus",
    )

    assert decision.selected_model == PAID_MODEL


@pytest.mark.asyncio
@_NO_FAMILY
async def test_the_last_gate_refuses_the_free_family_before_any_transport(
    live_mode, go_auth_stub
):
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        await plat.call_platform_chat_completions(
            model_id=FREE_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER_ID,
            messages=TURNS,
            transport=_recording_transport(seen),
        )

    # The free-family refusal is the reason, not a missing credential or an
    # unregistered provider.
    assert "무료" in str(caught.value)
    assert seen == []


@pytest.mark.asyncio
@_NO_FAMILY
async def test_the_streaming_gate_refuses_the_free_family_before_any_transport(
    live_mode, go_auth_stub
):
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        async for _event in plat.stream_platform_chat_completions(
            model_id=FREE_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER_ID,
            messages=TURNS,
            transport=_recording_transport(seen),
        ):
            pass

    assert "무료" in str(caught.value)
    assert seen == []


@pytest.mark.asyncio
@_NO_FAMILY
async def test_a_paid_model_still_reaches_the_provider(live_mode, go_auth_stub):
    seen: list = []

    result = await plat.call_platform_chat_completions(
        model_id=PAID_MODEL,
        upstream_model=PAID_UPSTREAM,
        provider=PROVIDER_NAME,
        platform_provider_id=PROVIDER_ID,
        messages=TURNS,
        transport=_recording_transport(seen),
    )

    assert len(seen) == 1
    assert json.loads(seen[0].content)["model"] == PAID_UPSTREAM
    assert result["choices"][0]["message"]["content"] == "OK"


@pytest.mark.asyncio
@_NO_FAMILY
async def test_a_benign_public_id_cannot_disguise_an_excluded_free_upstream(
    live_mode, go_auth_stub
):
    """A paid public id with the provider's free upstream is still refused."""
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        await plat.call_platform_chat_completions(
            model_id=PAID_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider=PROVIDER_NAME,
            platform_provider_id=PROVIDER_ID,
            messages=TURNS,
            transport=_recording_transport(seen),
        )

    assert "무료" in str(caught.value)
    assert seen == []


#: Another provider's registered free route: a row of a different provider that
#: carries the free marker in its upstream identity, and any registered row of a
#: provider that is neither of the two.
OTHER_FREE_PROVIDER_ROW = next(
    (
        row for row in model_rows()
        if row["provider_id"] != PROVIDER_ID
        and row["upstream_model"].casefold().endswith("-free")
    ),
    {},
)
THIRD_PROVIDER_ROW = next(
    (
        row for row in model_rows()
        if row["provider_id"] not in {PROVIDER_ID, OTHER_FREE_PROVIDER_ROW.get("provider_id")}
    ),
    {},
)


@_NO_FAMILY
def test_another_providers_free_model_keeps_its_own_status():
    """Only the excluded provider's free family is refused by this rule."""
    assert free_candidate_excluded_from_execution(FREE_MODEL) is True
    assert free_candidate_excluded_from_execution(PAID_MODEL) is False
    for other in (OTHER_FREE_PROVIDER_ROW, THIRD_PROVIDER_ROW):
        assert free_candidate_excluded_from_execution(other["id"]) is False
    # Another provider's free upstream name is never this rule's business.
    assert free_candidate_excluded_from_execution(
        OTHER_FREE_PROVIDER_ROW["id"],
        upstream_model=OTHER_FREE_PROVIDER_ROW["upstream_model"],
        platform_provider_id=OTHER_FREE_PROVIDER_ROW["provider_id"],
    ) is False


@requires_owner_document
@pytest.mark.asyncio
@_NO_FAMILY
async def test_the_provider_adapter_itself_is_untouched(go_auth_stub):
    """The provider wire is below the policy gate, so it still serves the model.

    The OpenCode coding-agent tooling uses the provider adapter directly; the
    customer execution path is the gate above it. The free lane the adapter is
    handed is the one the rule can carry, so the adapter's own table decides
    which envelope answers.
    """
    seen: list = []
    assert go._WIRE.get(FREE_UPSTREAM) is not None

    def respond(request):
        seen.append(request)
        if go._WIRE[FREE_UPSTREAM] == "responses":
            return httpx.Response(200, json={
                "id": "synthetic",
                "status": "completed",
                "output": [{
                    "type": "message", "role": "assistant",
                    "content": [{"type": "output_text", "text": "OK"}],
                }],
            })
        return httpx.Response(200, json={
            "id": "synthetic",
            "model": FREE_UPSTREAM,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    result = await go.call_go_model(
        model_id=FREE_MODEL,
        upstream_model=FREE_UPSTREAM,
        messages=TURNS,
        session_id=SESSION,
        max_tokens=32,
        transport=httpx.MockTransport(respond),
    )

    assert len(seen) == 1
    assert result["choices"][0]["message"]["content"] == "OK"
