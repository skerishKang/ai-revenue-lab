"""#4317: the ordinary completed Chat path can reach the owner-pinned Free roster.

The Chat Worker used to pin the upstream attempt count, so a recoverable
provider failure ended the request even though the owner-pinned per-grade
recovery chain was available. The pin was an artificial ceiling, not a safety
boundary.

B14 already owns the whole recovery contract, and this suite pins it:

* the attempt count comes from the candidates the declared product grade
  actually allows, and an explicit caller cap still wins;
* the roster is the owner-pinned per-grade list, in order;
* the walk advances to the next candidate only on a recoverable provider
  error, and it visits each candidate once;
* an arbitrary catalog substitution stays disabled.

No provider is contacted: the platform adapter is patched directly.

#7241 2단계: the roster, the primary and the credential slot are never written
here. The ordering contract is read from ``effective_tier_default()`` /
``effective_tier_fallback()`` — the app's own authority tables — and every
expectation that names a specific model is expressed against those tables. A
synthetic model id replaces the retired stand-in that this suite used to write
for its long-roster case.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.pilot import platform_secrets as ps
from app.pilot import router_core
from app.pilot.errors import UpstreamClientError, UpstreamServerError
from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

from _pilot_lane_paths import chat_surface
from _registry_values import model_rows, provider_of, provider_row, registry

#: The gateway's own chat surface, selected from the mounted router.
CHAT_PATH = chat_surface()

# The effective primary and the effective per-grade rosters: the same source
# the router resolves a request against, shipped document or private registry.
FREE_PRIMARY = effective_tier_default()
FREE_ROSTER = tuple(effective_tier_fallback()["free"])


# The exact option set the ordinary completed Chat path sends: the verified
# product grade, no arbitrary catalog fallback, and no attempt pin.
COMPLETED_CHAT_OPTIONS = {
    "product_tier": "free",
}


# A roster deliberately longer than the effective one, built from registry rows
# that are already registered (so the walk can visit them) but are not part of
# the Free roster, then extended with synthetic identities in the same Provider
# shape the effective rows use: no deployment identity is written here.
def _extra_registered_candidates(count: int) -> tuple[str, ...]:
    taken = {FREE_PRIMARY, *FREE_ROSTER}
    extra = [
        row["id"] for row in model_rows()
        if row["id"] not in taken and row.get("enabled", True)
    ]
    return tuple(extra[:count])


def _synthetic_candidates(count: int) -> list[dict]:
    """Additional registry rows for a roster longer than the catalog.

    The walk only visits installed catalog rows, so a longer roster needs more
    of them. Each row is built from the effective primary's own row shape with
    an identity of this suite's own: no deployment identity is written here.
    """
    from app.pilot.catalog import CATALOG_BY_ID

    primary = next(row for row in model_rows() if row["id"] == FREE_PRIMARY)
    prefix = provider_of(FREE_PRIMARY)
    known = {FREE_PRIMARY, *FREE_ROSTER}
    rows: list[dict] = []
    index = 0
    while len(rows) < count:
        model_id = f"{prefix}/synthetic-walk-candidate-{index:02d}"
        index += 1
        if model_id in known:
            continue
        rows.append(dict(primary, id=model_id))
    return rows


def _install_extra_rows(monkeypatch, rows: list[dict]) -> tuple[str, ...]:
    """Install the extra rows into the catalog for this test only.

    Every insertion goes through ``monkeypatch`` so the process-wide catalog is
    restored afterwards: a leaked row would corrupt later suites that compare
    the installed catalog against the registry document.

    Answers the identities actually installed: a row the effective catalog
    already holds is used as-is rather than replaced.
    """
    from app.pilot.catalog import CATALOG_BY_ID
    from app.pilot.tier_fallback import effective_tier_default

    template = CATALOG_BY_ID.get(effective_tier_default())
    if template is None:
        pytest.skip("the effective catalog does not hold the primary row")
    registry_ids = {row["id"] for row in model_rows()}
    installed: list[str] = []
    for row in rows:
        model_id = row["id"]
        if model_id in CATALOG_BY_ID or model_id in registry_ids:
            installed.append(model_id)
            continue
        monkeypatch.setitem(CATALOG_BY_ID, model_id, replace(template, model_id=model_id))
        installed.append(model_id)
    return tuple(installed)


def _primary_binding() -> str:
    """The credential slot of the registry Provider that owns the primary."""
    return provider_row(provider_of(FREE_PRIMARY))["credential_binding_name"]


def _set_registry_credentials(monkeypatch, model_ids) -> None:
    """Give every registry Provider the walk may dial a synthetic value."""
    providers = registry()["providers"]
    for model_id in model_ids:
        row = providers.get(provider_of(model_id))
        if row is not None:
            monkeypatch.setenv(
                row["credential_binding_name"],
                f"synthetic-{provider_of(model_id)}-0123456789abcdef",
            )


#: The effective roster plus every other installed row: the roster the long-walk
#: case drives. It is topped up with rows of this suite's own at call time so it
#: is always longer than the effective roster, whatever the document holds.
LONG_ROSTER = (*FREE_ROSTER, *_extra_registered_candidates(3))


def _widen_chain_budget(monkeypatch, attempts: int) -> None:
    """Headroom for a roster wider than the deployment's own."""
    from app.pilot import gateway

    floor = max(gateway._UPSTREAM_RETRY_BUDGET_SECONDS,
                gateway.DEFAULT_CHAIN_BUDGET_SECONDS)
    monkeypatch.setattr(gateway, "_UPSTREAM_RETRY_BUDGET_SECONDS",
                        floor * (attempts / 2))


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def test_the_completed_chat_option_set_resolves_the_whole_owner_roster(monkeypatch):
    """The allowed candidate list is the whole budget, with no attempt count."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(FREE_PRIMARY, dict(COMPLETED_CHAT_OPTIONS))
    assert decision.route_mode == "manual"
    assert decision.selected_model == FREE_PRIMARY
    assert decision.fallback_allowed is True
    assert [item["model_id"] for item in decision.eligible_fallback] == list(FREE_ROSTER)
    assert "owner_selected_tier_fallback:free" in decision.reason_codes
    # There is no attempt count on the decision any more.
    assert not hasattr(decision, "max_attempts")


def test_an_explicit_attempt_count_cannot_narrow_the_owner_roster(monkeypatch):
    """#4317: a caller-declared count no longer shortens the owner roster."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(
        FREE_PRIMARY, dict(COMPLETED_CHAT_OPTIONS, max_attempts=1),
    )
    assert decision.fallback_allowed is True
    assert [item["model_id"] for item in decision.eligible_fallback] == list(FREE_ROSTER)


def test_the_owner_roster_never_repeats_a_candidate():
    """A repeated candidate would let the walk loop on the same model."""
    assert len(set(FREE_ROSTER)) == len(FREE_ROSTER)
    assert FREE_PRIMARY not in FREE_ROSTER


def test_only_recoverable_provider_errors_advance_to_the_next_candidate():
    assert router_core.is_error_fallback_allowed("upstream_server_error") is True
    assert router_core.is_error_fallback_allowed("upstream_rate_limited") is True
    assert router_core.is_error_fallback_allowed("upstream_timeout") is True
    # #7389: a candidate-level rejection (401/403/404/429) advances; a bare
    # client error without a status reason stays terminal (fail closed).
    assert router_core.is_error_fallback_allowed("upstream_auth_failed") is True
    assert router_core.is_error_fallback_allowed("upstream_client_error") is False
    assert router_core.is_error_fallback_allowed(
        "upstream_client_error", reason="upstream_http_404") is True
    assert router_core.is_error_fallback_allowed(
        "upstream_client_error", reason="upstream_http_422") is False
    assert router_core.is_error_fallback_allowed("internal_error") is False


def test_the_gateway_walks_the_owner_roster_after_a_recoverable_failure(client, monkeypatch):
    """The primary fails with 5xx; the next roster candidate answers."""
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv(_primary_binding(), "sk-free-primary-0123456789abcdef")
    _ready(monkeypatch)

    original = plat.call_platform_chat_completions
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id, "provider": provider})
        if len(calls) == 1:
            raise UpstreamServerError()
        return {
            "id": "cmpl-free-fallback",
            "object": "chat.completion",
            "model": upstream_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            "_live": True,
            "_requested_upstream_model": upstream_model,
            "_actual_response_model": upstream_model,
        }

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            CHAT_PATH,
            json={
                "model": FREE_PRIMARY,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    assert response.status_code == 200
    assert len(calls) == 2
    # The primary failed and the next owner-roster candidate answered.
    assert calls[0]["model_id"] == FREE_PRIMARY
    assert calls[1]["model_id"] == FREE_ROSTER[0]
    # Each candidate is visited exactly once.
    assert len({call["model_id"] for call in calls}) == len(calls)
    business = response.json()["business14"]
    assert business["fallback_used"] is True
    assert business["attempt_count"] == 2
    assert business["selected_model"] == FREE_ROSTER[0]
    assert business["attempt_evidence"][0]["outcome"] == "error"
    assert business["attempt_evidence"][0]["error_code"] == "upstream_server_error"
    assert business["attempt_evidence"][1]["outcome"] == "success"


def test_the_owner_roster_walk_terminates_when_every_candidate_fails(client, monkeypatch):
    """Every candidate is tried once and the bounded error is surfaced.

    This is the other half of the no-infinite-loop contract: the walk ends
    after the candidates the grade allows, instead of retrying one candidate
    or walking an unbounded list.
    """
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv(_primary_binding(), "sk-free-primary-0123456789abcdef")
    _ready(monkeypatch)

    original = plat.call_platform_chat_completions
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id})
        raise UpstreamServerError()

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            CHAT_PATH,
            json={
                "model": FREE_PRIMARY,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    # The primary plus every roster candidate, each once, and no more — except
    # the chain's final attempt, which #6724 retries once on the same route
    # because there is no candidate left behind it.
    expected = [FREE_PRIMARY, *FREE_ROSTER, FREE_ROSTER[-1]]
    assert [call["model_id"] for call in calls] == expected
    assert len({call["model_id"] for call in calls}) == len(FREE_ROSTER) + 1
    assert response.status_code >= 400
    assert response.json()["error"]["attempt_count"] == len(expected)


def test_the_gateway_does_not_advance_on_a_non_recoverable_failure(client, monkeypatch):
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv(_primary_binding(), "sk-free-primary-0123456789abcdef")
    _ready(monkeypatch)

    original = plat.call_platform_chat_completions
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id})
        # #7389: a request-content rejection (422) is not a candidate failure,
        # so the walk must stop here (401/404 now advance).
        raise UpstreamClientError(422)

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            CHAT_PATH,
            json={
                "model": FREE_PRIMARY,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    assert response.status_code >= 400
    # Exactly one provider call: no substitution on a non-recoverable error.
    assert len(calls) == 1
    assert calls[0]["model_id"] == FREE_PRIMARY


def test_a_roster_longer_than_four_is_walked_in_full_with_no_numeric_cap(
    client, monkeypatch
):
    """#4317: more allowed candidates means more attempts, with no ceiling.

    The Free grade ships three backups today. The mechanism must not carry a
    number that a longer roster would have to raise, so this drives a longer
    roster and proves every candidate is tried in order.
    """
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat
    from app.pilot import tier_fallback

    # The extra rows are installed first, so the roster below is longer than the
    # effective one on whatever document this host serves.
    extra_rows = _synthetic_candidates(len(FREE_ROSTER) + 1)
    long_roster = (*LONG_ROSTER, *_install_extra_rows(monkeypatch, extra_rows))
    assert len(long_roster) > len(FREE_ROSTER)
    # The walk is sized by the roster, and each member is one in-process
    # attempt; give the chain the same headroom the effective roster needs so
    # a wider roster is not cut by the wall clock instead of a numeric cap.
    _widen_chain_budget(monkeypatch, len(long_roster) + 1)
    # The router reads the effective roster, which is the host's own table when
    # the switch is off and the private document's roster when it is on; the
    # wider roster replaces that answer for this test only.
    monkeypatch.setattr(
        tier_fallback, "effective_tier_fallback",
        lambda: {**effective_tier_fallback(), "free": long_roster},
    )
    _ready(monkeypatch)

    rcfg.provider_mode = "live"
    monkeypatch.setenv(_primary_binding(), "sk-free-primary-0123456789abcdef")
    # Every roster Provider's own slot holds a value, so a missing credential can
    # never be the reason a candidate is skipped.
    _set_registry_credentials(monkeypatch, long_roster)

    original = plat.call_platform_chat_completions
    calls: list[str] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append(model_id)
        if len(calls) <= len(long_roster):
            raise UpstreamServerError()
        return {
            "id": "cmpl-long-roster",
            "object": "chat.completion",
            "model": upstream_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            "_live": True,
            "_requested_upstream_model": upstream_model,
            "_actual_response_model": upstream_model,
        }

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            CHAT_PATH,
            json={
                "model": FREE_PRIMARY,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    assert response.status_code == 200
    # The primary plus every roster candidate, each visited exactly once, and
    # the last one answered.
    expected = [FREE_PRIMARY, *long_roster]
    assert calls == expected
    assert len(set(calls)) == len(calls)
    business = response.json()["business14"]
    assert business["fallback_used"] is True
    assert business["attempt_count"] == len(expected)
    assert business["selected_model"] == long_roster[-1]
