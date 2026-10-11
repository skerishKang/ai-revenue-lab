"""Engine Calendar CP access-lease port tests (#2010 convergence).

Proves the canonical Engine Calendar READ path uses the Control Plane
short-lived access lease with exactly the reviewed Calendar readonly provider
scope, rechecks the server-derived binding/actor references, preserves the
Calendar path/allowlist/host/GET-only gates, performs exactly one retry after a
single provider 401, and never accepts a refresh token or a client secret.
Network-free: httpx.MockTransport plus recording lease fakes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from padiem_ai_core.calendar_capability import (
    CALENDAR_READONLY_AUTH_SCOPE,
    GOOGLE_CALENDAR_BASE_URL,
    GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
)
from padiem_ai_core.tool_runtime import ToolHandlerError
from padiem_ai_core.connectors import GMAIL_READONLY_SCOPE

from app.calendar_port_cp_lease import (
    ACCESS_TOKEN_CACHED,
    ACCESS_TOKEN_PERSISTED,
    CALENDAR_CP_LEASE_CANONICAL,
    CALENDAR_CREATE,
    CALENDAR_DELETE,
    CALENDAR_ENGINE_DIRECT_REFRESH_PRODUCTION_FALLBACK,
    CALENDAR_RESPOND,
    CALENDAR_UPDATE,
    CALENDAR_WRITE,
    MAX_PROVIDER_ATTEMPTS,
    RAW_CLIENT_SECRET_ACCEPTED,
    RAW_REFRESH_TOKEN_ACCEPTED,
    SECOND_GOOGLE_OAUTH_STACK,
    ControlPlaneLeaseGoogleCalendarReadPort,
    parse_calendar_ids,
)
from app.google_oauth_access_lease import (
    CloudflareControlPlaneGoogleOAuthAccessLeaseClient,
    EngineGoogleOAuthAccessLease,
)
from app.service import ServiceContractError


NOW = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
BINDING_REF = "calendar-binding-1"
ACTOR_REF = "actor_1"
TOKEN_ONE = "calendar-token-one"
TOKEN_TWO = "calendar-token-two"
CALENDAR_ID = "primary"
CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar"

APP_ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def lease(*, token: str = TOKEN_ONE, actor_ref: str = ACTOR_REF) -> EngineGoogleOAuthAccessLease:
    return EngineGoogleOAuthAccessLease(
        access_token=token,
        binding_ref=BINDING_REF,
        connector_id="google-calendar",
        actor_ref=actor_ref,
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,),
        expires_at=NOW + timedelta(hours=1),
    )


class FakeLeaseClient:
    def __init__(self, leases=None, error: Exception | None = None) -> None:
        self.leases = list(leases or [lease()])
        self.error = error
        self.calls: list[dict] = []

    async def issue_access_lease(self, *, binding_ref: str, connector_id: str):
        self.calls.append({"binding_ref": binding_ref, "connector_id": connector_id})
        if self.error is not None:
            raise self.error
        if len(self.leases) > 1:
            return self.leases.pop(0)
        return self.leases[0]


class FakeServiceBinding:
    def __init__(self, scopes=None) -> None:
        self.scopes = scopes or [GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE]
        self.calls: list[dict] = []

    async def issue_access_lease(self, payload):
        self.calls.append(dict(payload))
        return {
            "ok": True,
            "lease": {
                "access_token": TOKEN_ONE,
                "binding_ref": BINDING_REF,
                "connector_id": "google-calendar",
                "actor_ref": ACTOR_REF,
                "account_ref": "account_1",
                "workspace_ref": "workspace_1",
                "scopes": list(self.scopes),
                "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        }


def port(**kwargs) -> ControlPlaneLeaseGoogleCalendarReadPort:
    values = dict(
        lease_client=FakeLeaseClient(),
        allowed_calendar_ids=parse_calendar_ids(f"{CALENDAR_ID},work"),
    )
    values.update(kwargs)
    return ControlPlaneLeaseGoogleCalendarReadPort(**values)


def get(port, **overrides):
    values = dict(
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        required_scopes=(CALENDAR_READONLY_AUTH_SCOPE,),
        base_url=GOOGLE_CALENDAR_BASE_URL,
        path="/users/me/calendarList",
        query={},
        timeout_seconds=10,
        max_response_bytes=10000,
    )
    values.update(overrides)
    return port.get_json(**values)


# --- F: engine lease client connector/scope mismatch fails closed -----------


def test_f_private_client_accepts_exact_google_calendar_readonly_lease() -> None:
    binding = FakeServiceBinding()
    client = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(binding, clock=lambda: NOW)
    result = run(client.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-calendar"))

    assert result.connector_id == "google-calendar"
    assert result.scopes == (GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,)
    assert binding.calls == [{"binding_ref": BINDING_REF, "connector_id": "google-calendar"}]
    assert TOKEN_ONE not in repr(result)
    assert TOKEN_ONE not in repr(result.safe_dict())


def test_f_private_client_rejects_calendar_scope_widening_and_unknown_connector() -> None:
    widened = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(
        FakeServiceBinding(scopes=[GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE, CALENDAR_WRITE_SCOPE]),
        clock=lambda: NOW,
    )
    with pytest.raises(ServiceContractError) as scope_error:
        run(widened.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-calendar"))
    assert scope_error.value.code == "google_oauth_access_lease_unavailable"

    binding = FakeServiceBinding()
    unknown = CloudflareControlPlaneGoogleOAuthAccessLeaseClient(binding, clock=lambda: NOW)
    with pytest.raises(ServiceContractError):
        run(unknown.issue_access_lease(binding_ref=BINDING_REF, connector_id="google-calendar-write"))
    assert binding.calls == []


# --- G: port gates ----------------------------------------------------------


def test_g_bounded_calendar_get_uses_server_binding_actor_and_bearer_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    lease_client = FakeLeaseClient()
    subject = port(lease_client=lease_client, transport=httpx.MockTransport(handler))
    result = run(get(subject, path=f"/users/me/calendarList/{CALENDAR_ID}"))

    assert result == {"items": []}
    assert lease_client.calls == [{"binding_ref": BINDING_REF, "connector_id": "google-calendar"}]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN_ONE}"
    assert requests[0].url.host == "www.googleapis.com"
    assert requests[0].url.path == f"/calendar/v3/users/me/calendarList/{CALENDAR_ID}"


def test_g_binding_or_actor_mismatch_blocks_the_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    subject = port(
        lease_client=FakeLeaseClient(leases=[lease(actor_ref="actor_other")]),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError) as caught:
        run(get(subject))
    assert caught.value.code == "calendar_access_lease_mismatch"
    assert provider_calls == 0


def test_g_scope_host_and_path_gates_fail_before_the_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    subject = port(transport=httpx.MockTransport(handler))

    with pytest.raises(ToolHandlerError) as scope_error:
        run(get(subject, required_scopes=(CALENDAR_READONLY_AUTH_SCOPE, CALENDAR_WRITE_SCOPE)))
    assert scope_error.value.code == "calendar_access_lease_mismatch"

    with pytest.raises(ToolHandlerError) as widened_scope:
        run(get(subject, required_scopes=(GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE + "x",)))
    assert widened_scope.value.code == "calendar_access_lease_mismatch"

    with pytest.raises(ToolHandlerError) as host_error:
        run(get(subject, base_url="https://evil.example/calendar/v3"))
    assert host_error.value.code == "calendar_provider_unavailable"

    for path in (
        f"/calendars/{CALENDAR_ID}/events/{CALENDAR_ID}/extra",
        f"/users/me/calendarList/{CALENDAR_ID}/acl",
        "/calendars/primary/acl",
        "/users/me/settings",
    ):
        with pytest.raises(ToolHandlerError) as path_error:
            run(get(subject, path=path))
        assert path_error.value.code == "calendar_provider_unavailable"

    assert provider_calls == 0


def test_g_calendar_allowlist_is_enforced_and_empty_allowlist_fails_closed() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    subject = port(transport=httpx.MockTransport(handler))
    with pytest.raises(ToolHandlerError) as not_allowed:
        run(get(subject, path="/calendars/not-allowed/events"))
    assert not_allowed.value.code == "calendar_provider_unavailable"
    assert provider_calls == 0

    with pytest.raises(ValueError):
        ControlPlaneLeaseGoogleCalendarReadPort(
            lease_client=FakeLeaseClient(),
            allowed_calendar_ids=frozenset(),
        )
    with pytest.raises(ValueError):
        ControlPlaneLeaseGoogleCalendarReadPort(
            lease_client=FakeLeaseClient(),
            allowed_calendar_ids=parse_calendar_ids("bad/id"),
        )
    assert parse_calendar_ids("  ") == frozenset()


def test_g_lease_failure_fails_closed_without_a_provider_call() -> None:
    provider_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal provider_calls
        provider_calls += 1
        return httpx.Response(200, json={})

    subject = port(
        lease_client=FakeLeaseClient(
            error=ServiceContractError(
                "google_oauth_access_lease_unavailable",
                "lease unavailable",
                status_code=503,
            )
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ToolHandlerError) as caught:
        run(get(subject))
    assert caught.value.code == "google_oauth_access_lease_unavailable"
    assert provider_calls == 0


# --- H / I: single 401 -> one fresh lease -> one retry ----------------------


def test_h_provider_401_requests_one_fresh_lease_and_retries_exactly_once() -> None:
    observed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.headers["Authorization"])
        if len(observed) == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"items": []})

    lease_client = FakeLeaseClient(leases=[lease(token=TOKEN_ONE), lease(token=TOKEN_TWO)])
    subject = port(lease_client=lease_client, transport=httpx.MockTransport(handler))
    result = run(get(subject, path=f"/calendars/{CALENDAR_ID}/events"))

    assert result == {"items": []}
    assert observed == [f"Bearer {TOKEN_ONE}", f"Bearer {TOKEN_TWO}"]
    assert lease_client.calls == [
        {"binding_ref": BINDING_REF, "connector_id": "google-calendar"},
        {"binding_ref": BINDING_REF, "connector_id": "google-calendar"},
    ]


def test_i_two_consecutive_401s_stop_after_one_retry() -> None:
    """A second 401 is terminal: no third attempt and no second retry lease."""

    observed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.headers["Authorization"])
        return httpx.Response(401, json={"error": "expired"})

    lease_client = FakeLeaseClient(leases=[lease(token=TOKEN_ONE), lease(token=TOKEN_TWO)])
    subject = port(lease_client=lease_client, transport=httpx.MockTransport(handler))
    with pytest.raises(ToolHandlerError) as caught:
        run(get(subject))

    # Same terminal projection as the canonical Gmail/Drive lease ports: the
    # second 401 is a bounded provider failure, never an unbounded retry loop.
    assert caught.value.code == "calendar_provider_unavailable"
    assert MAX_PROVIDER_ATTEMPTS == 2
    assert len(observed) == 2
    assert len(lease_client.calls) == 2


# --- J / K / L / O: canonical composition and credential containment --------


def test_j_k_canonical_worker_uses_control_plane_lease_without_direct_fallback() -> None:
    worker_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    start = worker_source.index("def _calendar_port_for_env")
    end = worker_source.index("async def _calendar_grants_for_env")
    calendar_block = worker_source[start:end]

    assert "ControlPlaneLeaseGoogleCalendarReadPort" in calendar_block
    assert "CONTROL_PLANE_GOOGLE_OAUTH_BINDING_NAME" in calendar_block
    assert "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN" not in calendar_block
    assert "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET" not in calendar_block
    assert "HttpxGoogleCalendarReadPort" not in worker_source

    assert CALENDAR_CP_LEASE_CANONICAL is True
    assert CALENDAR_ENGINE_DIRECT_REFRESH_PRODUCTION_FALLBACK is False


def test_l_no_refresh_token_or_client_secret_can_reach_the_canonical_port() -> None:
    source = (APP_ROOT / "app" / "calendar_port_cp_lease.py").read_text(encoding="utf-8")

    assert "refresh_token" not in source
    assert "client_secret" not in source
    assert "oauth2.googleapis.com" not in source
    assert RAW_REFRESH_TOKEN_ACCEPTED is False
    assert RAW_CLIENT_SECRET_ACCEPTED is False
    assert ACCESS_TOKEN_CACHED is False
    assert ACCESS_TOKEN_PERSISTED is False
    assert SECOND_GOOGLE_OAUTH_STACK is False

    # The lease dataclass carries no raw refresh material either.
    assert "raw_refresh_token" in lease().safe_dict()
    assert lease().safe_dict()["raw_refresh_token"] is False


def test_o_calendar_write_authority_is_absent_from_the_canonical_port() -> None:
    assert CALENDAR_WRITE is False
    assert CALENDAR_CREATE is False
    assert CALENDAR_UPDATE is False
    assert CALENDAR_DELETE is False
    assert CALENDAR_RESPOND is False

    source = (APP_ROOT / "app" / "calendar_port_cp_lease.py").read_text(encoding="utf-8")
    assert "events.insert" not in source
    # GET is the only HTTP method literal this module can issue.
    assert source.count('"GET"') == 1
    for method in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"'):
        assert method not in source
    # No Calendar mutation path is reachable at all.
    assert "CALENDAR_DELETE = False" in source
    assert "CALENDAR_CREATE = False" in source


def test_gmail_and_drive_reviewed_scopes_are_untouched() -> None:
    """N: the existing Gmail/Drive lease authorities are not weakened."""

    from app.google_oauth_access_lease import _REVIEWED_CONNECTOR_SCOPES
    from padiem_ai_core.drive_capability import DRIVE_READONLY_SCOPE

    assert _REVIEWED_CONNECTOR_SCOPES["gmail"] == (GMAIL_READONLY_SCOPE,)
    assert _REVIEWED_CONNECTOR_SCOPES["google-drive"] == (DRIVE_READONLY_SCOPE,)
    assert _REVIEWED_CONNECTOR_SCOPES["google-calendar"] == (GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,)
