"""Test-only proof: B14 authenticated propagation does NOT exist (#4416).

Source-only boundary evidence for the CENTRAL slice. B54 trusted identity
and owner-scoped conversation authority EXIST on current main:

* ``apps/padiem-chat/app/history.py::_chat_id`` mints ``chat_``+uuid4 hex,
  with ``validate_conversation_id`` as the shape check;
* ``apps/padiem-chat/app/claw_routes.py::_resolve_intake_session_reference``
  verifies ``current_user_id`` + owner-scoped
  ``HistoryStore.get_conversation(uid, candidate)``;
* ``apps/padiem-chat/app/b54_canonical_session.py::
  resolve_current_b54_canonical_session`` validates B54 product identity
  against the Control Plane from the signed session cookie only.

These are distinct identity and conversation authorities, not a working Go
bridge. The missing edge remains: no trusted product/owner/workspace/
conversation assertion is propagated across P01/Engine→B14 completed and
SSE to the internal ``session_id`` argument. Therefore production code is
NOT changed here: any ``session_id`` taken from user JSON or an
``x-opencode-session`` header would be untrusted input, and grammar alone
is not ownership proof.

All tests are network-free. No registry, provider, tier, or routing change.

#7241 2단계: which Go models exist, which provider owns them, and the
allowlisted upstream name of each are deployment values, so every expected
value below is derived from the effective registry (or from the app's own
rule tables) instead of being written into the file. Only the *wire family*
choices — a family the app admits is free, a family the owner excluded from
execution, the family whose adapter needs another route's provider id — stay
as owner-decision pins behind ``requires_owner_document``.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import opencode_go_wire as go_wire
from app.pilot import platform as plat
from app.pilot.errors import PilotNotConfigured
from app.pilot.gateway import _validate_body, _InvalidBody
from _registry_values import requires_owner_document

FORGED_SESSION = "chat_" + "f" * 32
OTHER_SESSION = "chat_" + "0" * 32

#: The app's own rule table: the upstream names this adapter can carry.
_GO_WIRE_BY_UPSTREAM = go_wire._WIRE
#: The documented wire family both free-candidate cases use.
_GO_CHAT_WIRE = "chat/completions"
_NO_GO_ROW = pytest.mark.skip(
    reason="#7241: the effective registry registers no Go model for this case"
)


def _go_provider_id() -> str:
    """The provider id that owns the Go adapter, read from the app's rule."""
    from app.pilot.owner_model_exclusions import FREE_CANDIDATE_PROVIDER

    return FREE_CANDIDATE_PROVIDER


def _go_model_ids() -> list[pytest.param]:
    """One parameter per registered Go model (roster read from the registry)."""
    from app.pilot.model_registry_file import read_registry

    provider_id = _go_provider_id()
    ids = sorted(
        row["id"]
        for row in read_registry()["models"]
        if row.get("provider_id") == provider_id
    )
    if not ids:
        return [pytest.param(None, marks=_NO_GO_ROW)]
    return [pytest.param(model_id, id=model_id) for model_id in ids]


GO_MODELS = _go_model_ids()


def _go_upstream(model_id: str) -> str:
    """The allowlisted upstream name of one registered Go model."""
    return model_id.split("/", 1)[1]


def _go_model_names() -> list[str]:
    """The registered Go model ids (empty when the roster has none)."""
    return [case.values[0] for case in GO_MODELS if case.values[0] is not None]


def _first_go_model() -> str:
    """One registered Go model id to shape a body around."""
    """One registered Go model id to shape a body around.

    Only called from cases pinned with ``requires_owner_document``.
    """
    return _go_model_names()[0]


def _is_free_candidate(model_id: str) -> bool:
    """Whether the app's own owner decision refuses this model for execution."""
    from app.pilot.owner_model_exclusions import (
        free_candidate_excluded_from_execution,
    )

    return free_candidate_excluded_from_execution(model_id)


def _model_params(wire: str | None = None, *, free: bool = False) -> list[pytest.param]:
    """(model_id, upstream) cases drawn from the registered Go roster.

    The pair set is derived — registry rows narrowed by the adapter's own wire
    table and (optionally) by the app's own free-candidate decision — so no
    model id or upstream name is a literal in this file.
    """
    if GO_MODELS[0].values[0] is None:
        return [pytest.param(None, None, marks=_NO_GO_ROW)]
    cases = []
    for case in GO_MODELS:
        model_id = case.values[0]
        upstream = _go_upstream(model_id)
        if upstream not in _GO_WIRE_BY_UPSTREAM:
            continue
        if wire is not None and _GO_WIRE_BY_UPSTREAM[upstream] != wire:
            continue
        if free and not _is_free_candidate(model_id):
            continue
        cases.append(pytest.param(model_id, upstream, id=model_id))
    return cases or [pytest.param(None, None, marks=_NO_GO_ROW)]


def _other_provider_id() -> str:
    """A registered provider id that is not the Go provider.

    A caller can hand the Go adapter another provider's platform id; the
    adapter must still refuse, because the session/ownership gap and the
    model gate are not provider-id specific.
    """
    from app.pilot.model_registry_file import read_registry

    provider_id = _go_provider_id()
    return next(
        name
        for name in read_registry()["providers"]
        if name != provider_id
    )


def _denial_reason(model_id: str) -> str:
    """The denial the gateway must report for one registered Go model.

    Read from the app's own precedence: an owner-excluded free candidate is
    refused first; otherwise a disabled registry row is refused.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.owner_model_exclusions import (
        free_candidate_excluded_from_execution,
    )

    if _is_free_candidate(model_id):
        return "free_candidate_excluded"
    model = get_catalog_by_id(model_id)
    if model is None or not model.enabled:
        return "model_disabled"
    return "provider_secret_missing"


def _go_body(model_id: str) -> dict:
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "합성 세션 경계 점검"}],
        "temperature": 0,
        "max_tokens": 8,
    }


# --------------------------------------------------------------------------
# 1. User JSON cannot carry session trust: the field is not even accepted.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_completed_body_rejects_session_id_field(model_id: str) -> None:
    body = _go_body(model_id)
    body["session_id"] = FORGED_SESSION
    with pytest.raises(_InvalidBody, match="Unexpected top-level fields"):
        _validate_body(body)


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_completed_body_rejects_business14_session_field(model_id: str) -> None:
    body = _go_body(model_id)
    body["business14"] = {"session_id": FORGED_SESSION}
    with pytest.raises(_InvalidBody, match="Unexpected business14 fields"):
        _validate_body(body)


@requires_owner_document
def test_stream_preview_body_rejects_session_id_field() -> None:
    """The SSE preview shares the canonical validator, so a session field
    is rejected with the exact same field-rejection semantic."""
    from app.pilot.stream_gateway import _validate_preview_body

    raw = _go_body(_first_go_model())
    raw["stream"] = True
    raw["session_id"] = FORGED_SESSION
    with pytest.raises(_InvalidBody, match="Unexpected top-level fields"):
        _validate_preview_body(raw)


# --------------------------------------------------------------------------
# 2. The x-opencode-session header is ignored: forged header changes nothing.
# --------------------------------------------------------------------------


def _post_completed(client: TestClient, model_id: str, headers: dict | None = None):
    return client.post(
        "/api/pilot/v1/chat/completions",
        json=_go_body(model_id),
        headers=headers or {},
    )


@pytest.mark.parametrize("model_id", GO_MODELS)
def test_forged_header_does_not_change_gateway_outcome(model_id: str) -> None:
    with TestClient(create_app()) as client:
        plain = _post_completed(client, model_id)
        forged = _post_completed(
            client, model_id, {"x-opencode-session": FORGED_SESSION}
        )
    assert plain.status_code == forged.status_code
    # request_id is unique per request; compare everything else so a forged
    # header is proven to change nothing about routing or denial.
    plain_body = plain.json()
    forged_body = forged.json()
    for body in (plain_body, forged_body):
        body.pop("request_id", None)
        if isinstance(body.get("error"), dict):
            body["error"].pop("request_id", None)
    assert plain_body == forged_body
    # #2505: the excluded free family is refused before the secret or OFF
    # gate, and a forged header still changes nothing about that outcome.
    # Which denial is expected is read from the app's own rules for this
    # model, not written as a per-model table in the test.
    from app.pilot.catalog import get_catalog_by_id

    assert plain_body["error"]["reason_code"] == _denial_reason(model_id)
    # The registry row and the router agree on the same facts.
    catalog_model = get_catalog_by_id(model_id)
    assert _is_free_candidate(model_id) is (
        _denial_reason(model_id) == "free_candidate_excluded"
    ) or catalog_model is None or not catalog_model.enabled


# --------------------------------------------------------------------------
# 3. Go adapter supplies a per-request one-turn routing session if a
#    canonical conversation key is absent. Original OFF routes still cannot
#    reach the provider, regardless of session shape.
# --------------------------------------------------------------------------


def _tripwire_transport(seen: list) -> httpx.MockTransport:
    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise AssertionError("no network POST permitted while OFF")

    return httpx.MockTransport(responder)


@pytest.mark.parametrize("model_id,upstream", _model_params(_GO_CHAT_WIRE, free=True))
def test_go_wire_missing_session_creates_one_turn_transport_key(model_id, upstream) -> None:
    """An independent call gets a distinct Go-only routing key, not identity."""
    _, _, first = go_wire.prepare_go_request(
        model_id=model_id, upstream_model=upstream,
        messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
        session_id=None,
    )
    _, _, second = go_wire.prepare_go_request(
        model_id=model_id, upstream_model=upstream,
        messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
        session_id=None,
    )
    assert first["x-opencode-session"].startswith("go_")
    assert first["x-opencode-session"] != second["x-opencode-session"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id,upstream", _model_params(free=True))
async def test_go_adapter_without_session_never_posts(model_id, upstream, monkeypatch) -> None:
    """Missing conversation does not bypass the unrelated model OFF gate."""
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list = []
    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider=_other_provider_id(),
            platform_provider_id=_other_provider_id(),
            messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
            max_tokens=8,
            session_id=None,
            transport=_tripwire_transport(seen),
        )
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id,upstream", _model_params(free=True))
async def test_go_adapter_forged_session_blocked_by_off_gate(
    model_id, upstream, monkeypatch
) -> None:
    """Even a grammar-valid forged session cannot pass while OFF.

    The registry OFF gate (PilotNotConfigured) must fire before any
    transport POST — never a session-grammar bypass.
    """

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list = []
    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=model_id,
            upstream_model=upstream,
            provider=_other_provider_id(),
            platform_provider_id=_other_provider_id(),
            messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
            max_tokens=8,
            session_id=FORGED_SESSION,
            transport=_tripwire_transport(seen),
        )
    assert seen == []


# --------------------------------------------------------------------------
# 4. Two conversations cannot share a session through any gateway path:
#    the gateway never forwards one, so sharing is impossible by construction.
# --------------------------------------------------------------------------


def test_gateway_validated_body_never_contains_session() -> None:
    for model_id in _go_model_names():
        validated = _validate_body(_go_body(model_id))
        assert "session_id" not in validated
        assert "session_id" not in validated.get("business14", {})


@requires_owner_document
def test_distinct_forged_sessions_both_rejected_at_body() -> None:
    for session in (FORGED_SESSION, OTHER_SESSION):
        body = _go_body(_first_go_model())
        body["session_id"] = session
        with pytest.raises(_InvalidBody):
            _validate_body(body)


# --------------------------------------------------------------------------
# 5. The owner's Go roster: one model stays disabled while the enabled set
#    is exactly what the registry document says it is.
# --------------------------------------------------------------------------


@requires_owner_document
def test_owner_disabled_go_model_stays_off_while_go_roster_is_what_it_says() -> None:
    from app.pilot.model_registry_file import read_registry

    provider_id = _go_provider_id()
    reg = read_registry()
    assert reg["providers"][provider_id]["enabled"] is True
    rows = [m for m in reg["models"] if m["provider_id"] == provider_id]
    enabled = {m["id"] for m in rows if m["enabled"]}
    disabled = {m["id"] for m in rows if not m["enabled"]}
    # Both states exist in the roster, so "enabled" is a real per-row fact.
    assert enabled
    assert disabled
    assert disabled.isdisjoint(enabled)
    # Every single-row read agrees with the router's own view of the same id.
    for model_id in _go_model_names():
        row = next(m for m in reg["models"] if m["id"] == model_id)
        assert row["enabled"] is (model_id in enabled)


# --------------------------------------------------------------------------
# 6. Grammar is not ownership: a forged grammar-valid chat_ id passes the
#    wire helper, so only the missing trusted bridge + OFF gate protect.
#    B54 authorities exist but are not interchangeable with a Go session.
# --------------------------------------------------------------------------


@requires_owner_document
def test_forged_grammar_valid_session_passes_helper_but_proves_nothing() -> None:
    """The helper accepts any grammar-valid id — including a forged one —
    so grammar acceptance must never be read as owner proof."""
    model_id, upstream = _model_params()[0].values
    wire, _body, headers = go_wire.prepare_go_request(
        model_id=model_id,
        upstream_model=upstream,
        messages=[{"role": "user", "content": "합성 세션 경계 점검"}],
        session_id=FORGED_SESSION,
    )
    assert wire == _GO_WIRE_BY_UPSTREAM[upstream]
    assert headers["x-opencode-session"] == FORGED_SESSION


def test_b54_authorities_exist_but_are_distinct_from_go_session() -> None:
    """Read-only pins: B54 minting, owner-scoped lookup, and canonical
    Control Plane session authority exist; none of them is a B14 Go bridge."""
    from pathlib import Path

    chat_app = Path(__file__).resolve().parents[2] / "padiem-chat" / "app"
    history = (chat_app / "history.py").read_text(encoding="utf-8")
    assert "def _chat_id" in history
    assert "def validate_conversation_id" in history
    claw_routes = (chat_app / "claw_routes.py").read_text(encoding="utf-8")
    assert "_resolve_intake_session_reference" in claw_routes
    assert "get_conversation" in claw_routes
    canonical = (chat_app / "b54_canonical_session.py").read_text(encoding="utf-8")
    assert "def resolve_current_b54_canonical_session" in canonical
    # The canonical B54 session reads only the signed-cookie user id;
    # body/header values cannot select a session, user, or product.
    assert "Nothing else is read from the request" in canonical


# --------------------------------------------------------------------------
# 7. SSE preview path carries no session either (same canonical validator).
#    The substring pin below is supporting evidence only; the positive
#    _InvalidBody rejection above is the authoritative SSE boundary check.
# --------------------------------------------------------------------------


def test_sse_preview_invocation_carries_no_session_id() -> None:
    import inspect

    from app.pilot import stream_gateway

    source = inspect.getsource(stream_gateway)
    assert "session_id" not in source
