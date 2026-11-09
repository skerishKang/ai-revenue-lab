"""261104: the two per-turn identity reads are cached, refusals are not.

Production measurement (COM2, 2026-11-04): each orchestration turn resolved
the chat owner through `resolve_current_auth_session` and PC turns added
`resolve_connector_owner_scope`, both remote Worker RPCs costing 0.6-1.0 s
because the identity edge attaches to LAX/SJC for this line. The two reads are
pure functions of a verified credential, so successful answers may live in a
60-second memory cache keyed by a hash of the credential or session id — while
a rejection, an error or an authority outage must reach the authority again
immediately, and logout, deletion, permission changes and session revocation
must leave no cached answer standing (including answers whose load was still
in flight when the invalidation landed).
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from app.auth_validation_cache import invalidate_auth_cache
from app.identity_call_cache import CachedIdentityAuthority

UID = "usr_0123456789abcdef0123456789abcdef"
OTHER_UID = "usr_ffffffffffffffffffffffffffffffff"
SESSION = "authsession:b62:123"
OTHER_SESSION = "authsession:b62:456"


class FakeAuthority:
    """Counts every call; each read is individually controllable."""

    def __init__(self) -> None:
        self.owner_calls: list[str] = []
        self.session_calls: list[str] = []
        self.scope_result = {"account_ref": UID, "workspace_ref": "ws-1"}
        self.session_result = object()
        self.owner_error: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.product_user_calls: list[str] = []
        self.auth_session_result = object()

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.session_calls.append(product_user_id)
        if self.gate is not None:
            await self.gate.wait()
        if self.owner_error is not None:
            raise self.owner_error
        return self.session_result

    async def resolve_connector_owner_scope(self, *, session_id):
        self.owner_calls.append(session_id)
        if self.owner_error is not None:
            raise self.owner_error
        return self.scope_result

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        self.product_user_calls.append(product_id + ":" + canonical_subject_id)
        if self.owner_error is not None:
            raise self.owner_error
        return UID

    async def resolve_auth_session(self, *, session_id):
        self.session_calls.append("guard:" + session_id)
        return self.auth_session_result

    binding_marker = "inner-binding"


def test_a_cached_read_hits_the_authority_once() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    first = asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    second = asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))

    assert first is second is inner.session_result
    assert inner.session_calls == [UID]
    # A different product user is a different key.
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=OTHER_UID))
    assert inner.session_calls == [UID, OTHER_UID]


def test_owner_scope_is_cached_per_session_and_never_across_sessions() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    first = asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    second = asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    assert first is second is inner.scope_result
    assert inner.owner_calls == [SESSION]

    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=OTHER_SESSION))
    assert inner.owner_calls == [SESSION, OTHER_SESSION]


def test_a_rejection_is_never_cached() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)
    inner.owner_error = RuntimeError("identity worker unavailable")

    with pytest.raises(RuntimeError):
        asyncio.run(wrapped.resolve_current_auth_session(
            product_id="b62", product_user_id=UID))
    with pytest.raises(RuntimeError):
        asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    assert inner.session_calls == [UID] and inner.owner_calls == [SESSION]

    # The authority recovers: the next read succeeds and is cached from then on.
    inner.owner_error = None
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    assert inner.session_calls == [UID, UID]


def test_entries_expire_at_the_ttl() -> None:
    inner = FakeAuthority()
    clock = [100.0]
    wrapped = CachedIdentityAuthority(inner, ttl_seconds=60, clock=lambda: clock[0])

    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    clock[0] += 59.0
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    assert inner.session_calls == [UID]  # still inside the window

    clock[0] += 2.0  # 61 s after the load
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    assert inner.session_calls == [UID, UID]


def test_ttl_is_capped_at_sixty_seconds() -> None:
    with pytest.raises(ValueError):
        CachedIdentityAuthority(FakeAuthority(), ttl_seconds=61)


def test_invalidate_user_and_session_leave_no_answer_standing() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    wrapped.invalidate_user(UID)
    wrapped.invalidate_session(SESSION)

    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    assert inner.session_calls == [UID, UID]
    assert inner.owner_calls == [SESSION, SESSION]
    # Another user's entries survive a user-level invalidation.
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=OTHER_UID))
    wrapped.invalidate_user(UID)
    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=OTHER_UID))
    assert inner.session_calls == [UID, UID, OTHER_UID]


def test_owner_scope_entries_invalidate_by_the_account_they_resolved() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    # The scope answered with this session's account ref, so the logout of
    # that account drops the entry even though the key is the session hash.
    wrapped.invalidate_user(UID)
    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    assert inner.owner_calls == [SESSION, SESSION]


def test_an_invalidation_fences_a_load_that_was_still_in_flight() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)
    gate = asyncio.Event()
    inner.gate = gate

    async def journey() -> None:
        first = asyncio.create_task(wrapped.resolve_current_auth_session(
            product_id="b62", product_user_id=UID))
        for _ in range(100):  # the load starts and parks on the gate
            if inner.session_calls:
                break
            await asyncio.sleep(0.01)
        assert inner.session_calls == [UID]
        wrapped.invalidate_user(UID)  # logout lands while the load runs
        gate.set()
        await first
        # The fenced answer must not repopulate the cache after the logout.
        await wrapped.resolve_current_auth_session(
            product_id="b62", product_user_id=UID)
        assert inner.session_calls == [UID, UID]

    asyncio.run(journey())


def test_concurrent_callers_share_one_lookup() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    slow_gate = asyncio.Event()
    inner.gate = slow_gate

    async def journey() -> None:
        first = asyncio.create_task(wrapped.resolve_current_auth_session(
            product_id="b62", product_user_id=UID))
        second = asyncio.create_task(wrapped.resolve_current_auth_session(
            product_id="b62", product_user_id=UID))
        for _ in range(100):
            if inner.session_calls:
                break
            await asyncio.sleep(0.01)
        slow_gate.set()
        one, two = await asyncio.gather(first, second)
        assert one is two
        assert inner.session_calls == [UID]  # one lookup, two waiters

    asyncio.run(journey())


def test_the_cached_reads_delegate_and_the_rest_passes_through() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    # The session read is cached for 20 s now: one authority call, two readers.
    first = asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    second = asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    assert first is second is inner.auth_session_result
    assert inner.session_calls == ["guard:" + SESSION]
    # Attribute passthrough keeps composition checks working.
    assert wrapped.binding_marker == "inner-binding"


def test_invalidate_auth_cache_reaches_the_wrapped_authority() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    class State:
        control_plane_identity_authority = wrapped
        auth_validation_cache = None

    class Request:
        app = type("App", (), {"state": State()})()

    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    asyncio.run(invalidate_auth_cache(
        Request(), user_id=UID, session_id=SESSION))

    asyncio.run(wrapped.resolve_current_auth_session(
        product_id="b62", product_user_id=UID))
    assert inner.session_calls == [UID, UID]


def test_product_user_of_a_subject_is_cached_per_product_and_subject() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    first = asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b62", canonical_subject_id="sub_fixture"))
    second = asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b62", canonical_subject_id="sub_fixture"))
    assert first == second == UID
    assert inner.product_user_calls == ["b62:sub_fixture"]

    asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b62", canonical_subject_id="sub_other"))
    asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b54", canonical_subject_id="sub_fixture"))
    assert inner.product_user_calls == [
        "b62:sub_fixture", "b62:sub_other", "b54:sub_fixture"]
    # The key carries the subject id only as a hash.
    key = "productuser:b62:" + hashlib.sha256(b"sub_fixture").hexdigest()
    assert key in wrapped._entries


def test_a_logout_drops_the_product_user_entry_by_the_uid_it_resolved() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b62", canonical_subject_id="sub_fixture"))
    wrapped.invalidate_user(UID)
    asyncio.run(wrapped.resolve_product_user_for_subject(
        product_id="b62", canonical_subject_id="sub_fixture"))
    assert inner.product_user_calls == ["b62:sub_fixture", "b62:sub_fixture"]


def test_the_session_read_uses_the_unified_auth_session_window() -> None:
    inner = FakeAuthority()
    clock = [100.0]
    wrapped = CachedIdentityAuthority(inner, ttl_seconds=60, clock=lambda: clock[0])

    first = asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    clock[0] += 250.0
    second = asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    assert first is second is inner.auth_session_result
    assert inner.session_calls == ["guard:" + SESSION]

    clock[0] += 51.0  # 301 s after the load: the unified window is over
    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    assert inner.session_calls == ["guard:" + SESSION, "guard:" + SESSION]


def test_session_invalidation_drops_both_session_entries() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    wrapped.invalidate_session(SESSION)
    asyncio.run(wrapped.resolve_connector_owner_scope(session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    assert inner.owner_calls == [SESSION, SESSION]
    assert inner.session_calls == ["guard:" + SESSION, "guard:" + SESSION]

    # Another session's answer survives this invalidation.
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    wrapped.invalidate_session(SESSION)
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    assert inner.session_calls.count("guard:" + OTHER_SESSION) == 1


def test_a_logout_drops_every_cached_session_answer() -> None:
    inner = FakeAuthority()
    wrapped = CachedIdentityAuthority(inner)

    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    # The cache cannot map a session to its user, so a logout drops them all.
    wrapped.invalidate_user(OTHER_UID)
    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    assert inner.session_calls == ["guard:" + SESSION, "guard:" + OTHER_SESSION,
                                   "guard:" + SESSION, "guard:" + OTHER_SESSION]


def test_revocation_events_drop_the_pc_path_session_cache_immediately() -> None:
    # The unified window shares its invalidation with the Chat general
    # request cache: every revocation event that reaches
    # `invalidate_auth_cache` (logout, password change, account deletion,
    # admin membership/role change — all call it) must drop the PC-path
    # auth-session entries at once, not at window expiry.
    inner = FakeAuthority()
    clock = [100.0]
    wrapped = CachedIdentityAuthority(inner, ttl_seconds=60, clock=lambda: clock[0])

    class State:
        control_plane_identity_authority = wrapped
        auth_validation_cache = None

    class Request:
        app = type("App", (), {"state": State()})()

    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    # 250 s in: both entries are still inside the unified window...
    clock[0] += 250.0
    assert inner.session_calls == ["guard:" + SESSION, "guard:" + OTHER_SESSION]
    # ...until a revocation event passes through `invalidate_auth_cache`.
    asyncio.run(invalidate_auth_cache(
        Request(), user_id=UID, session_id=SESSION))
    asyncio.run(wrapped.resolve_auth_session(session_id=SESSION))
    assert inner.session_calls == ["guard:" + SESSION, "guard:" + OTHER_SESSION,
                                   "guard:" + SESSION]
    # A user-only invalidation (no session id: the other revocation sites)
    # drops every auth-session entry regardless of user.
    asyncio.run(invalidate_auth_cache(Request(), user_id=UID))
    asyncio.run(wrapped.resolve_auth_session(session_id=OTHER_SESSION))
    assert inner.session_calls[-1] == "guard:" + OTHER_SESSION
    assert inner.session_calls.count("guard:" + OTHER_SESSION) == 2


def test_auth_session_window_matches_the_session_cache_env() -> None:
    import os
    from app.identity_call_cache import _auth_session_ttl_seconds

    os.environ["PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS"] = "45"
    try:
        assert _auth_session_ttl_seconds() == 45
    finally:
        del os.environ["PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS"]
    assert _auth_session_ttl_seconds() == 300
    os.environ["PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS"] = "99999"
    try:
        assert _auth_session_ttl_seconds() == 300  # over cap: default, never above 900
    finally:
        del os.environ["PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS"]
