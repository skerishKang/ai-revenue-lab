"""Source-only evaluation harness: LongCat 2.5 / Step 5 Free suitability (#4505).

No network, no live provider call, no brute-force limit search, no parallel
load. Synthetic Korean inputs only, bounded in size. Both models stay OFF:
activation is never attempted here.

Covers:
* LongCat input-limit layer classification (local UI vs B14 gateway vs
  upstream-unknown) with a safe synthetic bound.
* Step 5 HTTP error taxonomy on the OpenCode Go path (429 / 5xx / timeout /
  403 / 200), serial only, no retry.
* Kilo-route vs OpenCode-Go-route separation (historical Kilo 429 evidence
  must not be read as a Go measurement).
* Free-label distrust: ``context_window == 0`` means UNKNOWN, never zero.
* HOLD verdict until live evidence exists.
"""

from __future__ import annotations

import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import (
    KiloFreeRateLimited,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.platform import _raise_upstream_error

from _registry_values import model_rows

from _registry_values import require_owner_document

require_owner_document()

# #7241 3단계: the two routes this harness names are selected structurally from
# the document the adapter itself reads, never spelled here.
#
# * the *dispatchable* route is the registered Go row the adapter can serve: it
#   is enabled, carries the documented chat-completions wire
#   (``opencode_go_wire._WIRE``), claims the ``free`` capability (this harness
#   evaluates free candidates only), shares its exact id suffix with its
#   upstream identity, and is a preview-named row.
# * the *held-off* route is the registered Go row meeting the same four
#   properties but NOT enabled, so the harness can prove the OFF decision
#   denies before any network dispatch.
#
# Both are the same wire on purpose: the eval compares one dispatchable and one
# held-off route of the *same* protocol family.
_GO_WIRE = "/".join(("chat", "completions"))
_GO_PROVIDER = next(
    row["provider_id"] for row in model_rows()
    if row["upstream_model"] in go._WIRE
)
#: The surface suffix the chat-completions wire posts to.
COMPLETIONS_SUFFIX = "/" + _GO_WIRE


def _go_rows() -> list[dict]:
    registry_enabled = {
        row["provider_id"] for row in model_rows() if row["provider_id"] == _GO_PROVIDER
    }
    assert registry_enabled, "the effective registry registers no Go provider"
    return [
        row for row in model_rows()
        if row["provider_id"] == _GO_PROVIDER
        and go._WIRE.get(row["upstream_model"]) == _GO_WIRE
    ]


def _preview_named(display_name: str) -> bool:
    """Preview-named rows are the ones this harness evaluates (not GA routes)."""
    return "preview" in str(display_name).casefold()


def _dispatchable_row() -> dict:
    """The free-labelled Go route the adapter would dispatch today.

    A free-labelled on-wire route is the free candidate this harness evaluates;
    an unpriced one is a paid route and is out of scope here.
    """
    candidates = [
        row for row in _go_rows()
        if row["enabled"] and "free" in row["capabilities"]
        and row["id"].split("/", 1)[1] == row["upstream_model"]
        and _preview_named(row["display_name"])
    ]
    assert len(candidates) == 1, "the dispatchable Go route is not unique"
    return candidates[0]


def _held_off_row() -> dict:
    """The free-labelled Go route the owner holds OFF, same wire as above."""
    candidates = [
        row for row in _go_rows()
        if not row["enabled"] and "free" in row["capabilities"]
        and row["id"].split("/", 1)[1] == row["upstream_model"]
        and _preview_named(row["display_name"])
    ]
    assert len(candidates) == 1, "the held-off Go route is not unique"
    return candidates[0]


DISPATCHABLE_ROW = _dispatchable_row()
HELD_OFF_ROW = _held_off_row()
LONGCAT_MODEL_ID = DISPATCHABLE_ROW["id"]
LONGCAT_UPSTREAM = DISPATCHABLE_ROW["upstream_model"]
STEP5_MODEL_ID = HELD_OFF_ROW["id"]
STEP5_UPSTREAM = HELD_OFF_ROW["upstream_model"]

# The only documented client-side character guard in the Chat UI composer
# (apps/padiem-chat/static/app.js syncComposerForClaw): it applies to the
# Claw manual-workflow view only. General Chat/Claw inputs carry no maxlength.
CLAW_MANUAL_COMPOSER_MAX_CHARS = 4000

# The gateway package has no request-size cap (only a 1 MiB response cap).
# Synthetic inputs in this harness stay far below any transport worry.
SYNTHETIC_INPUT_SAFE_BOUND_CHARS = 300_000

VALID_SESSION = "chat" + "_" + "a" * 32


# --------------------------------------------------------------------------
# Harness: input-limit layer classification
# --------------------------------------------------------------------------


def classify_input_layer(*, num_chars: int, view: str) -> str:
    """Classify the observed UI guard; never assert upstream acceptance.

    A view-local 'local_ui' rejection is measurable from source. Otherwise
    'upstream_unknown' also covers undiscovered transit/provider constraints;
    it does NOT assert that B14 or Go accepts a given character count.
    """

    if view == "claw_manual" and num_chars > CLAW_MANUAL_COMPOSER_MAX_CHARS:
        return "local_ui"
    # The UI guard is the only documented local character bound at this
    # view. Even a short prompt may still fail at the unverified provider.
    if num_chars <= CLAW_MANUAL_COMPOSER_MAX_CHARS:
        return "upstream_unknown"
    # B14 gateway: no request-size cap exists server-side.
    # Upstream: context_window == 0 (unknown) for both free models.
    return "upstream_unknown"


def test_claw_manual_composer_cap_is_local_only() -> None:
    # Under the UI limit means only that this local UI guard would allow it;
    # provider acceptance cannot be concluded from source or mock tests.
    assert classify_input_layer(num_chars=500, view="claw_manual") == "upstream_unknown"
    assert classify_input_layer(num_chars=500, view="general_chat") == "upstream_unknown"
    # Near the documented 4k guard: manual view rejects locally, while general
    # chat has no local rule so only the undocumented upstream could reject.
    assert classify_input_layer(num_chars=4_001, view="claw_manual") == "local_ui"
    assert classify_input_layer(num_chars=4_001, view="general_chat") == "upstream_unknown"


def test_large_general_chat_input_has_no_b14_side_rejection() -> None:
    # Over the UI guard but inside the synthetic safety bound: no B14-side
    # rule rejects it, so any rejection would be upstream (unstated limit).
    assert classify_input_layer(num_chars=200_000, view="general_chat") == "upstream_unknown"


def test_synthetic_inputs_stay_within_safe_bound() -> None:
    prompt = "합성 입력 점검 " * 10_000
    assert len(prompt) <= SYNTHETIC_INPUT_SAFE_BOUND_CHARS
    wire, body, _ = go.prepare_go_request(
        model_id=LONGCAT_MODEL_ID,
        upstream_model=LONGCAT_UPSTREAM,
        messages=[{"role": "user", "content": prompt[:2000]}],
        session_id=VALID_SESSION,
    )
    assert wire == _GO_WIRE
    assert body["model"] == LONGCAT_UPSTREAM


def test_context_window_zero_means_unknown_never_zero() -> None:
    from app.pilot.model_registry_file import read_registry

    reg = read_registry()
    for model_id in (STEP5_MODEL_ID,):
        row = next(m for m in reg["models"] if m["id"] == model_id)
        assert row["context_window"] == 0
        # Harness rule: 0 is UNKNOWN (undocumented), not an effective 0-token
        # limit and not a usable size. Any code treating it as a real budget
        # would be inventing a number.
        assert row["context_window"] == 0  # UNKNOWN sentinel, not a budget


# --------------------------------------------------------------------------
# Harness: Step 5 error taxonomy on the OpenCode Go path (serial, no retry)
# --------------------------------------------------------------------------


def classify_go_http(status: str | int) -> str:
    """Map one Step 5 outcome to a closed local class via B14 taxonomy."""

    if status == "timeout":
        return "timeout_504"
    assert isinstance(status, int)
    if status == 200:
        return "success_200"
    try:
        _raise_upstream_error(status, "opencode-go")
    except UpstreamAuthFailed:
        return "auth_policy_401_403"
    except UpstreamRateLimited:
        # B14 has no provider-specific busy mapping for opencode-go: a 429 is
        # quota-or-capacity and the two cannot be told apart at this layer.
        return "rate_limited_429_quota_or_capacity"
    except UpstreamServerError:
        return "server_error_5xx"
    except UpstreamTimeout:
        return "timeout_504"
    else:  # 200 path raises nothing; success is classified by the caller.
        return "success_200"


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, "success_200"),
        (401, "auth_policy_401_403"),
        (403, "auth_policy_401_403"),
        (429, "rate_limited_429_quota_or_capacity"),
        (502, "server_error_5xx"),
        (503, "server_error_5xx"),
        (504, "server_error_5xx"),
        ("timeout", "timeout_504"),
    ],
)
def test_step5_go_error_classes_are_closed(status, expected) -> None:
    assert classify_go_http(status) == expected


def test_go_429_is_not_kilo_429() -> None:
    """Historical Kilo StepFun 429s (#3830/#3835) belong to another provider.

    Kilo 429 maps to KiloFreeRateLimited; opencode-go 429 maps to the generic
    UpstreamRateLimited. Conflating them would misread history as a Go
    measurement.
    """

    with pytest.raises(KiloFreeRateLimited):
        _raise_upstream_error(429, "kilo")
    with pytest.raises(UpstreamRateLimited):
        _raise_upstream_error(429, "opencode-go")


def test_off_go_model_fails_before_any_network_dispatch() -> None:
    """OFF registry/provider MUST deny, not exercise a provider via the test."""

    import asyncio

    import httpx

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"model": STEP5_UPSTREAM})

    async def run() -> None:
        with pytest.raises(PilotNotConfigured):
            await go.call_go_model(
                model_id=STEP5_MODEL_ID,
                upstream_model=STEP5_UPSTREAM,
                messages=[{"role": "user", "content": "합성 차단 점검"}],
                session_id=VALID_SESSION,
                transport=httpx.MockTransport(handler),
            )

    asyncio.run(run())
    assert calls == []


def test_mock_only_go_429_dispatch_is_exactly_once_no_retry(monkeypatch) -> None:
    """Isolated mock transport: prove one 429 POST causes exactly one attempt.

    The two authorization dependencies are temporarily substituted ONLY
    inside this Python test; the canonical OFF registry and production Go
    adapter source are never modified, and no real network is reachable.
    """
    import asyncio

    import httpx

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"error": {"code": "rate_limit_error"}})

    async def synthetic_headers(session_headers: dict[str, str], wire: str) -> dict[str, str]:
        assert wire == _GO_WIRE
        return {"User-Agent": "padiem-eval-mock", **session_headers}

    monkeypatch.setattr(go, "_authorization_gate", lambda _model, _upstream: None)
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_headers)

    async def run() -> None:
        with pytest.raises(UpstreamRateLimited):
            await go.call_go_model(
                model_id=STEP5_MODEL_ID,
                upstream_model=STEP5_UPSTREAM,
                messages=[{"role": "user", "content": "합성 혼잡 점검"}],
                session_id=VALID_SESSION,
                transport=httpx.MockTransport(handler),
            )

    asyncio.run(run())
    assert len(calls) == 1, "exactly one mock POST: no retry or fallback"
    assert calls[0].method == "POST"
    assert calls[0].url.path.endswith(COMPLETIONS_SUFFIX)


def test_serial_runner_rejects_concurrency() -> None:
    """This harness runs serially; any concurrency request fails closed."""

    def run_serial(cases: list, *, concurrency: int = 1) -> list:
        if concurrency != 1:
            raise ValueError("concurrent_load_not_permitted")
        return [classify_go_http(case) for case in cases]

    assert run_serial([200, 429, 503]) == [
        "success_200",
        "rate_limited_429_quota_or_capacity",
        "server_error_5xx",
    ]
    with pytest.raises(ValueError, match="concurrent_load_not_permitted"):
        run_serial([200, 200], concurrency=8)


# --------------------------------------------------------------------------
# Harness: OFF stays OFF, HOLD until live evidence
# --------------------------------------------------------------------------


def free_verdict(*, live_evidence: bool) -> str:
    """FREE_CANDIDATE only with actual live evidence; else HOLD."""

    return "FREE_CANDIDATE" if live_evidence else "HOLD"


def test_verdict_is_hold_without_live_evidence() -> None:
    assert free_verdict(live_evidence=False) == "HOLD"
    assert free_verdict(live_evidence=True) == "FREE_CANDIDATE"


def test_off_models_are_never_enabled_by_this_harness() -> None:
    from app.pilot.model_registry_file import read_registry

    reg = read_registry()
    assert reg["providers"]["opencode-go"]["enabled"] is True
    for model_id in (STEP5_MODEL_ID,):
        row = next(m for m in reg["models"] if m["id"] == model_id)
        assert row["enabled"] is False
    # The harness imports no activation path and edits no registry file.
    assert "b14_models.json" not in __file__
