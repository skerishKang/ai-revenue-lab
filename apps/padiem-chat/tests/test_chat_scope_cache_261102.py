"""#6460 4-1 third round: the short Claw connector-scope window.

``/api/claw/local-access/devices`` paid three identity round trips on every
request (b62 -> b54 -> connector scope) and COM2 measured a 4.6 s identity
median for it. These tests pin the window that removes the repeats: a second
request reads nothing, a refusal is never stored, accounts and workspaces never
share an entry, Chat's own pairing/consent/logout paths drop it immediately, and
five concurrent requests still make one round trip.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.auth_routes as auth_routes
import app.claw_connector_enrollment_routes as consent
import app.pc_device_pairing_routes as pairing
import app.pc_work_context as context
import padiem_control_plane.b54_identity_bridge as bridge_module
from app.pc_scope_cache import (
    SCOPE_CACHE_SECONDS_ENV,
    clear_scope_cache,
    invalidate_owner_scope,
    scope_cache_seconds,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

OWNER = "usr_" + "a" * 32
OTHER_OWNER = "usr_" + "b" * 32
WORKSPACE = "tenant_" + "c" * 32
OTHER_WORKSPACE = "tenant_" + "d" * 32
SUBJECT = "sub_shared_owner"


@pytest.fixture(autouse=True)
def _clean_window(monkeypatch):
    monkeypatch.delenv(SCOPE_CACHE_SECONDS_ENV, raising=False)
    clear_scope_cache()
    try:
        yield
    finally:
        clear_scope_cache()


class Authority:
    """Counting stand-in for the canonical identity authority."""

    def __init__(self, *, account: str | None = "acct-1", raises: bool = False,
                 delay: float = 0.0) -> None:
        self.account = account
        self.raises = raises
        self.delay = delay
        self.calls = 0
        self.in_flight = 0
        self.peak = 0

    async def resolve_connector_owner_scope(self, *, session_id):
        assert isinstance(session_id, str) and session_id
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.raises:
                raise RuntimeError("identity unavailable")
            if self.account is None:
                return None
            return {"account_ref": self.account, "workspace_ref": "connector-ws"}
        finally:
            self.in_flight -= 1


def _session(workspace: str, session_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        tenant_id=workspace,
        subject=SimpleNamespace(subject_id=SUBJECT),
    )


def wire(monkeypatch, authority: Authority, *, workspace: str = WORKSPACE,
         calls: dict | None = None):
    """Request + the two authority reads the connector scope composes."""
    state = SimpleNamespace(
        control_plane_identity_authority=authority,
        identity_shadow_store=object(),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    seen = calls if calls is not None else {"b62": 0, "b54": 0}
    seen.setdefault("workspace", workspace)

    async def owner_session(_request, _owner_id):
        seen["b62"] += 1
        current = seen["workspace"]
        return current, _session(current, "sess-b62")

    async def b54(_authority, _owner_id):
        seen["b54"] += 1
        return SimpleNamespace(auth_session=_session(seen["workspace"], "sess-b54"))

    monkeypatch.setattr(context, "_resolve_owner_session", owner_session)
    monkeypatch.setattr(bridge_module, "resolve_current_b54_canonical_session", b54)
    return request, seen


def resolve(request, *, owner: str = OWNER, workspace: str = WORKSPACE):
    return asyncio.run(context.resolve_pc_connector_scope(
        request, owner_id=owner, workspace_id=workspace,
    ))


def test_second_request_reads_no_authority(monkeypatch):
    authority = Authority()
    request, seen = wire(monkeypatch, authority)

    first = resolve(request)
    second = resolve(request)

    assert first.ready and second.ready
    assert authority.calls == 1
    assert (seen["b62"], seen["b54"]) == (1, 1), \
        "a cached answer must not re-bridge identity"
    assert first.account_ref == second.account_ref == "acct-1"


def test_window_expires_and_the_authority_is_read_again(monkeypatch):
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "0.05")
    authority = Authority()
    request, seen = wire(monkeypatch, authority)

    assert resolve(request).ready
    assert resolve(request).ready
    assert authority.calls == 1
    time.sleep(0.08)
    assert resolve(request).ready
    assert authority.calls == 2
    assert seen["b54"] == 2


def test_zero_switches_the_window_off(monkeypatch):
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "0")
    authority = Authority()
    request, _seen = wire(monkeypatch, authority)

    for _ in range(3):
        assert resolve(request).ready
    assert authority.calls == 3


def test_a_refusal_is_never_stored(monkeypatch):
    authority = Authority(account=None)
    request, _seen = wire(monkeypatch, authority)

    denied = resolve(request)
    denied_again = resolve(request)
    assert not denied.ready and not denied_again.ready
    assert authority.calls == 2, "a refusal must be asked again, not remembered"

    authority.account = "acct-1"
    allowed = resolve(request)
    assert allowed.ready
    assert authority.calls == 3


def test_an_authority_error_is_never_stored(monkeypatch):
    authority = Authority(raises=True)
    request, _seen = wire(monkeypatch, authority)

    for _ in range(2):
        assert not resolve(request).ready
    assert authority.calls == 2

    authority.raises = False
    assert resolve(request).ready
    assert authority.calls == 3


def test_accounts_and_workspaces_never_share_an_entry(monkeypatch):
    authority = Authority()
    request, seen = wire(monkeypatch, authority)

    pairs = [(OWNER, WORKSPACE), (OTHER_OWNER, WORKSPACE), (OWNER, OTHER_WORKSPACE)]
    for owner, workspace in pairs:
        seen["workspace"] = workspace
        assert resolve(request, owner=owner, workspace=workspace).ready
    assert authority.calls == 3
    for owner, workspace in pairs:
        seen["workspace"] = workspace
        assert resolve(request, owner=owner, workspace=workspace).ready
    assert authority.calls == 3, "each founder key keeps its own answer"


def test_concurrent_requests_share_one_round_trip(monkeypatch):
    authority = Authority(delay=0.05)
    request, seen = wire(monkeypatch, authority)

    async def burst():
        return await asyncio.gather(*[context.resolve_pc_connector_scope(
            request, owner_id=OWNER, workspace_id=WORKSPACE,
        ) for _ in range(5)])

    results = asyncio.run(burst())
    assert all(result.ready for result in results)
    assert authority.calls == 1
    assert authority.peak == 1, "single-flight, not five parallel identity reads"
    assert seen["b54"] == 1


def test_pairing_revoke_drops_the_window(monkeypatch):
    authority = Authority()
    request, _seen = wire(monkeypatch, authority)
    assert resolve(request).ready
    assert resolve(request).ready
    assert authority.calls == 1

    class Store:
        async def revoke_link(self, **kwargs):
            return True

    monkeypatch.setattr(pairing, "current_user_id", lambda _request: OWNER)
    unlink = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pc_device_pairing_store=Store())),
        path_params={"link_id": "link-1"},
    )
    assert asyncio.run(pairing.pc_pairing_revoke(unlink)).status_code == 200

    assert resolve(request).ready
    assert authority.calls == 2, "an unlinked PC must be seen by the next request"


def test_connector_consent_revoke_drops_the_window(monkeypatch):
    authority = Authority()
    request, _seen = wire(monkeypatch, authority)
    assert resolve(request).ready and resolve(request).ready
    assert authority.calls == 1

    now = datetime.now(timezone.utc)
    session = AuthSessionSnapshot(
        session_id="session.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=now - timedelta(days=1), expires_at=now + timedelta(days=30),
        state=AuthSessionState.ACTIVE, tenant_id=WORKSPACE,
    )

    class Consent:
        async def revoke_connector_enrollment_consent(self, **kwargs):
            return {
                "consent_id": kwargs["consent_id"], "device_id": "device.owner.1",
                "granted_at": (now - timedelta(minutes=5)).isoformat(),
                "withdrawn_at": now.isoformat(),
                "dispatch_authorized": False, "grants_read": False,
                "grants_write": False,
            }

    body = {"consent_id": "consent.owner.1", "confirmed": True,
            "confirmation_version": "pc-enrollment-consent-v1"}

    class ConsentRequest:
        def __init__(self) -> None:
            self.app = SimpleNamespace(state=SimpleNamespace(
                control_plane_identity_authority=Consent(),
                connector_enrollment_browser_csrf=SimpleNamespace(verify=lambda _r: True),
            ))
            self.headers = {
                "content-type": "application/json",
                "content-length": str(len(json.dumps(body))),
            }

        async def body(self):
            return json.dumps(body).encode()

    async def b54(_request):
        return SimpleNamespace(product_user_id=OWNER, auth_session=session)

    monkeypatch.setattr(consent, "auth_ready", lambda _r: True)
    monkeypatch.setattr(consent, "current_user_id", lambda _r: OWNER)
    monkeypatch.setattr(consent, "resolve_current_b54_canonical_session", b54)

    response = asyncio.run(consent.connector_enrollment_consent_revoke(ConsentRequest()))
    assert response.status_code == 200

    assert resolve(request).ready
    assert authority.calls == 2, "a withdrawn consent is read on the next request"


def test_logout_revocation_drops_the_window(monkeypatch):
    authority = Authority()
    request, _seen = wire(monkeypatch, authority)
    assert resolve(request).ready and resolve(request).ready
    assert authority.calls == 1

    class Revoker:
        def __init__(self) -> None:
            self.revoked: list[str] = []

        async def revoke_auth_session(self, *, product_id, session_id):
            self.revoked.append(session_id)
            return None

    revoker = Revoker()
    logout_request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(session_secret="not-a-real-secret"),
            control_plane_identity_authority=revoker,
        )),
        cookies={"padiem_session": "signed-value"},
    )
    monkeypatch.setattr(
        auth_routes, "decode_session_claims",
        lambda _settings, _raw: SimpleNamespace(
            user_id=OWNER, canonical_session_id="session.owner.1",
        ),
    )

    import app.auth_validation_cache as validation_cache

    async def _no_cache(*_a, **_k):
        return None

    monkeypatch.setattr(validation_cache, "invalidate_auth_cache", _no_cache)

    assert asyncio.run(auth_routes._revoke_canonical_session(logout_request)) is None
    assert revoker.revoked == ["session.owner.1"]

    assert resolve(request).ready
    assert authority.calls == 2, "a signed-out account must not keep a live window"


def test_invalidate_owner_scope_ignores_anything_but_an_account_id(monkeypatch):
    authority = Authority()
    request, _seen = wire(monkeypatch, authority)
    assert resolve(request).ready
    invalidate_owner_scope(None)
    invalidate_owner_scope("")
    invalidate_owner_scope(1234)
    assert resolve(request).ready
    assert authority.calls == 1, "nothing was forgotten, so nothing is re-read"

    invalidate_owner_scope(OWNER)
    assert resolve(request).ready
    assert authority.calls == 2


def test_window_is_bounded_and_switchable(monkeypatch):
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "9999")
    assert scope_cache_seconds() == 30.0
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "-1")
    assert scope_cache_seconds() == 30.0
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "nonsense")
    assert scope_cache_seconds() == 30.0
    monkeypatch.setenv(SCOPE_CACHE_SECONDS_ENV, "12")
    assert scope_cache_seconds() == 12.0
