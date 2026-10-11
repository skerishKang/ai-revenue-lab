"""Contract tests for the private Calendar credential-presence read (#2010).

The surface answers exactly one bounded question (does an existing reviewed
google-calendar Control Plane credential exist) through the private
``CONTROL_PLANE_GOOGLE_OAUTH`` Service Binding. It must add no public route, no
access lease, no token unseal, no D1 write, and must never emit refs, tokens,
scopes, calendar ids or the workspace reference.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from app.calendar_credential_presence import (  # noqa: E402
    ACCESS_LEASE_ISSUE,
    CALENDAR_CREDENTIAL_PRESENCE_PATH,
    CALENDAR_PRESENCE_CONNECTOR_ID,
    CALENDAR_PRESENCE_INTERNAL_ROUTE_ONLY,
    CALENDAR_PRESENCE_READ_ONLY,
    D1_MUTATION,
    MAX_PRESENCE_ENTRIES,
    MAX_PRESENCE_RPC_ATTEMPTS,
    PAYLOAD_CLOSED,
    PRESENCE_BINDING_NAME,
    PRESENCE_TOKEN_ENV,
    PRESENCE_TOKEN_HEADER,
    PROVIDER_CALL,
    PUBLIC_ROUTE_ADDED,
    TOKEN_UNSEAL,
    calendar_presence_response,
    presence_locks,
    project_presence,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "worker_identity.py"
SERVICE_PATH = ROOT / "app" / "service.py"

TOKEN = "presence-operator-token-" + "x" * 40
WORKSPACE_REF = "workspace.a"


class FakeBinding:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def workspace_calendar_connector_state(self, payload):
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error
        return self.result


class Env:
    def __init__(
        self,
        binding=None,
        *,
        token: str | None = TOKEN,
        rpc_name: str = PRESENCE_BINDING_NAME,
    ) -> None:
        if binding is not None:
            setattr(self, rpc_name, binding)
        if token is not None:
            setattr(self, PRESENCE_TOKEN_ENV, token)


def _entry(**overrides) -> dict:
    values = {
        "connector_id": CALENDAR_PRESENCE_CONNECTOR_ID,
        "state": "connected",
        "usable": True,
        "expires_present": False,
        "ambiguous": False,
    }
    values.update(overrides)
    return values


def _rpc(*entries) -> dict:
    return {"ok": True, "connectors": list(entries)}


def _headers(token: str | None = TOKEN) -> dict[str, str]:
    return {} if token is None else {PRESENCE_TOKEN_HEADER: token}


def _call(env, body: bytes | None, *, method: str = "POST", token: str | None = TOKEN):
    return asyncio.run(
        calendar_presence_response(env, method, _headers(token), body)
    )


def test_route_is_internal_only_and_read_only() -> None:
    assert CALENDAR_CREDENTIAL_PRESENCE_PATH.startswith("/internal/v1/")
    assert CALENDAR_PRESENCE_READ_ONLY is True
    assert CALENDAR_PRESENCE_INTERNAL_ROUTE_ONLY is True
    assert PUBLIC_ROUTE_ADDED is False
    assert PAYLOAD_CLOSED is True
    assert TOKEN_UNSEAL is False
    assert ACCESS_LEASE_ISSUE is False
    assert D1_MUTATION is False
    assert PROVIDER_CALL is False
    assert MAX_PRESENCE_RPC_ATTEMPTS == 1
    assert MAX_PRESENCE_ENTRIES == 1
    assert PRESENCE_BINDING_NAME == "CONTROL_PLANE_GOOGLE_OAUTH"
    worker_source = WORKER_PATH.read_text(encoding="utf-8")
    assert (
        'CONTROL_PLANE_GOOGLE_OAUTH_BINDING_NAME = "CONTROL_PLANE_GOOGLE_OAUTH"'
        in worker_source
    )


@pytest.mark.parametrize(
    ("state", "usable", "expires_present", "ambiguous"),
    [
        ("connected", True, False, False),
        ("connected", True, True, False),
        ("not_connected", False, False, False),
        ("ambiguous", False, False, True),
    ],
)
def test_bounded_projection_maps_every_reviewed_state(
    state: str, usable: bool, expires_present: bool, ambiguous: bool
) -> None:
    projected = project_presence(
        _rpc(
            _entry(
                state=state,
                usable=usable,
                expires_present=expires_present,
                ambiguous=ambiguous,
            )
        )
    )

    assert projected["CALENDAR_CREDENTIAL_PRESENCE_STATE"] == state
    assert projected["CALENDAR_CREDENTIAL_USABLE"] == ("YES" if usable else "NO")
    assert projected["CALENDAR_CREDENTIAL_EXPIRES_PRESENT"] == (
        "YES" if expires_present else "NO"
    )
    assert projected["CALENDAR_CREDENTIAL_AMBIGUOUS"] == ("YES" if ambiguous else "NO")
    assert set(projected) == {
        "CALENDAR_CREDENTIAL_PRESENCE_STATE",
        "CALENDAR_CREDENTIAL_USABLE",
        "CALENDAR_CREDENTIAL_EXPIRES_PRESENT",
        "CALENDAR_CREDENTIAL_AMBIGUOUS",
    }


def test_connected_result_is_reported_without_reconnect_authority() -> None:
    binding = FakeBinding(_rpc(_entry()))
    status, body = _call(Env(binding), json.dumps({"workspace_ref": WORKSPACE_REF}).encode())

    assert status == 200
    assert body["CALENDAR_CREDENTIAL_PRESENCE_STATE"] == "connected"
    assert len(binding.calls) == 1
    assert binding.calls[0] == {"workspace_ref": WORKSPACE_REF}
    assert body["ACCESS_LEASE_ISSUE"] == "0"
    assert body["TOKEN_UNSEAL"] == "0"
    assert body["PRESENCE_READ_ATTEMPT"] == "1"


def test_response_never_leaks_refs_tokens_scopes_or_identifiers() -> None:
    binding = FakeBinding(_rpc(_entry()))
    status, body = _call(Env(binding), json.dumps({"workspace_ref": WORKSPACE_REF}).encode())
    rendered = json.dumps(body, sort_keys=True)

    assert status == 200
    for forbidden in (
        WORKSPACE_REF,
        "workspace_ref",
        "binding_ref",
        "actor_ref",
        "account_ref",
        "token",
        "refresh_token",
        "scope",
        "credential",
        "googleapis.com",
        "calendar_id",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{}",
        b'{"workspace_ref": "workspace.a", "connector_id": "google-calendar"}',
        b'{"workspace_ref": "workspace.a", "scopes": ["calendar.readonly"]}',
        b'{"workspace_ref": "workspace.a", "binding_ref": "bind.x"}',
        b'{"workspace_ref": "workspace;drop"}',
        b'{"workspace_ref": 42}',
        b"not-json",
    ],
)
def test_payload_is_closed_and_rejects_connector_scope_and_ref_injection(payload: bytes) -> None:
    binding = FakeBinding(_rpc(_entry()))
    status, body = _call(Env(binding), payload)

    assert status == 400
    assert body["error"]["code"] == "invalid_request"
    assert binding.calls == []


def test_missing_or_wrong_operator_token_fails_closed() -> None:
    binding = FakeBinding(_rpc(_entry()))
    body_bytes = json.dumps({"workspace_ref": WORKSPACE_REF}).encode()

    status, body = _call(Env(binding, token=None), body_bytes)
    assert (status, body["error"]["code"]) == (503, "calendar_presence_unavailable")

    status, body = _call(Env(binding, token="short"), body_bytes)
    assert (status, body["error"]["code"]) == (503, "calendar_presence_unavailable")

    status, body = _call(Env(binding), body_bytes, token=None)
    assert (status, body["error"]["code"]) == (401, "calendar_presence_unauthorized")

    status, body = _call(Env(binding), body_bytes, token="wrong-" + "y" * 40)
    assert (status, body["error"]["code"]) == (401, "calendar_presence_unauthorized")
    assert binding.calls == []


def test_missing_service_binding_fails_closed_without_a_call() -> None:
    status, body = _call(
        Env(None, rpc_name="SOMETHING_ELSE"),
        json.dumps({"workspace_ref": WORKSPACE_REF}).encode(),
    )

    assert status == 503
    assert body["error"]["code"] == "calendar_presence_unavailable"


def test_rpc_failure_is_bounded_and_not_retried() -> None:
    binding = FakeBinding(error=RuntimeError("upstream detail"))
    status, body = _call(Env(binding), json.dumps({"workspace_ref": WORKSPACE_REF}).encode())

    assert status == 503
    assert body["error"]["code"] == "calendar_presence_unavailable"
    assert len(binding.calls) == 1
    assert "upstream detail" not in json.dumps(body)


@pytest.mark.parametrize(
    "result",
    [
        {"ok": False},
        {"ok": True, "connectors": []},
        {"ok": True, "connectors": [_entry(), _entry()]},
        {"ok": True, "connectors": [_entry(connector_id="gmail")]},
        {"ok": True, "connectors": [_entry(state="unknown")]},
        {"ok": True, "connectors": [_entry(usable=False)]},
        {"ok": True, "connectors": [_entry(state="not_connected", usable=True)]},
        {"ok": True, "connectors": [_entry(state="ambiguous", usable=False, ambiguous=False)]},
        # canonical invariant, both directions (CENTRAL #2010 tri-state hardening)
        {"ok": True, "connectors": [_entry(ambiguous=True)]},
        {"ok": True, "connectors": [_entry(state="not_connected", usable=False, ambiguous=True)]},
        {"ok": True, "connectors": [_entry(state="ambiguous", usable=True, ambiguous=True)]},
        {"ok": True, "connectors": [{**_entry(), "binding_ref": "bind.x"}]},
        "not-an-envelope",
    ],
)
def test_noncanonical_rpc_results_fail_closed(result: object) -> None:
    binding = FakeBinding(result)
    status, body = _call(Env(binding), json.dumps({"workspace_ref": WORKSPACE_REF}).encode())

    assert status == 502
    assert body["error"]["code"] == "calendar_presence_noncanonical"


@pytest.mark.parametrize(
    "entry",
    [
        _entry(ambiguous=True),
        _entry(state="not_connected", usable=False, ambiguous=True),
        _entry(state="ambiguous", usable=True, ambiguous=True),
    ],
    ids=["connected_ambiguous", "not_connected_ambiguous", "ambiguous_usable"],
)
def test_noncanonical_flag_combinations_fail_closed_with_502(entry: dict) -> None:
    """The three flag combinations CENTRAL flagged must fail closed at the surface."""

    binding = FakeBinding(_rpc(entry))
    status, body = _call(Env(binding), json.dumps({"workspace_ref": WORKSPACE_REF}).encode())

    assert status == 502
    assert body["error"]["code"] == "calendar_presence_noncanonical"


@pytest.mark.parametrize(
    ("state", "usable", "ambiguous", "canonical"),
    [
        # usable == (state == "connected") and ambiguous == (state == "ambiguous")
        ("connected", True, False, True),
        ("not_connected", False, False, True),
        ("ambiguous", False, True, True),
        ("connected", False, False, False),
        ("connected", True, True, False),
        ("not_connected", True, False, False),
        ("not_connected", False, True, False),
        ("ambiguous", True, True, False),
        ("ambiguous", True, False, False),
        ("ambiguous", False, False, False),
    ],
)
def test_tri_state_invariant_is_enforced_in_both_directions(
    state: str, usable: bool, ambiguous: bool, canonical: bool
) -> None:
    """Both directions of the authoritative Control Plane invariant are pinned."""

    payload = _rpc(_entry(state=state, usable=usable, ambiguous=ambiguous))

    if canonical:
        projected = project_presence(payload)
        assert projected["CALENDAR_CREDENTIAL_PRESENCE_STATE"] == state
        assert projected["CALENDAR_CREDENTIAL_USABLE"] == ("YES" if usable else "NO")
        assert projected["CALENDAR_CREDENTIAL_AMBIGUOUS"] == ("YES" if ambiguous else "NO")
        return

    with pytest.raises(ValueError):
        project_presence(payload)


def test_response_uses_only_post() -> None:
    binding = FakeBinding(_rpc(_entry()))
    status, body = _call(
        Env(binding),
        json.dumps({"workspace_ref": WORKSPACE_REF}).encode(),
        method="GET",
    )

    assert status == 405
    assert body["error"]["code"] == "method_not_allowed"
    assert binding.calls == []


def test_locks_are_fixed_evidence() -> None:
    locks = presence_locks()

    assert locks["PRESENCE_READ_MODE"] == "PRIVATE_RPC"
    assert locks["PUBLIC_ROUTE_ADDED"] == "NO"
    assert locks["PAYLOAD_CLOSED"] == "YES"
    assert locks["TOKEN_UNSEAL"] == "0"
    assert locks["ACCESS_LEASE_ISSUE"] == "0"
    assert locks["D1_MUTATION"] == "0"
    assert locks["PROVIDER_CALL"] == "0"
    assert locks["RAW_REF_OUTPUT"] == "0"
    assert locks["RAW_TOKEN_OUTPUT"] == "0"
    assert locks["RAW_WORKSPACE_REF_OUTPUT"] == "0"
    assert locks["CALLER_SELECTED_CONNECTOR"] == "0"


def test_worker_dispatches_the_route_before_the_default_fetch() -> None:
    worker_source = WORKER_PATH.read_text(encoding="utf-8")
    service_source = SERVICE_PATH.read_text(encoding="utf-8")

    dispatch = worker_source.index("CALENDAR_CREDENTIAL_PRESENCE_PATH:")
    fallback = worker_source.index("return await super().fetch(request)")
    assert dispatch < fallback
    assert "from app.calendar_credential_presence import" in worker_source
    assert "calendar_presence_response" in worker_source
    # The route is not part of the public service composition.
    assert CALENDAR_CREDENTIAL_PRESENCE_PATH not in service_source
    assert "calendar_credential_presence" not in service_source
