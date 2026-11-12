"""#7554 — a sign-out whose server-side session could not be ended is not a success.

Covered:

- LOCAL_LOGOUT_REFUSES: /api/auth/logout answers 503 session_revocation_failed
  when the canonical revocation fails, clears the cookies, journals one closed
  line, and keeps the unrevoked session denied past the ordinary marker window
- LOCAL_LOGOUT_SUCCESS_UNCHANGED: a confirmed revocation still answers ok
- SHARED_LOGOUT_REFUSES: /auth/shared/logout answers the same refusal when the
  legacy canonical session behind the browser could not be ended
- NO_AUTHORITY_NOTHING_TO_END: a deployment with no canonical authority bound
  has nothing to revoke and still answers ok
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_7078_b_local_session_verify import (  # noqa: E402
    ACCOUNT_ID,
    LOCAL_VERIFY_LEEWAY_SECONDS,
    PUBLIC_BASE,
    USER_ID,
    TokenIssuer,
    Verifier,
    _build_guarded_app,
    sqlite_workers,  # noqa: F401  (pytest fixture)
)

from app.auth import SESSION_COOKIE, create_session_token  # noqa: E402
from app.auth_validation_cache import DENYLIST_TTL_SECONDS  # noqa: E402
from app.shared_login_flow import ACCESS_COOKIE, REFRESH_COOKIE, SharedLoginFlow  # noqa: E402

LEGACY = "authsession:b62:logout7554"


class CanonicalAuthority:
    """An authority whose session stays active unless a revocation lands."""

    def __init__(self, *, revoke_fails: bool) -> None:
        self.revoke_fails = revoke_fails
        self.revoked: set[str] = set()
        self.revoke_calls = 0

    async def resolve_auth_session(self, *, session_id):
        from padiem_control_plane import AuthSessionSnapshot, AuthSessionState
        from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

        now = datetime.now(timezone.utc)
        return AuthSessionSnapshot(
            session_id=session_id,
            product_id="b62",
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=ACCOUNT_ID),
            issued_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=6),
            state=AuthSessionState.REVOKED if session_id in self.revoked else AuthSessionState.ACTIVE,
        )

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoke_calls += 1
        if self.revoke_fails:
            raise TimeoutError("authority did not answer")
        self.revoked.add(session_id)


def _verifier(workers):
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)
    return verifier


def _cleared(response, name):
    return any(c.startswith(name + "=") and "Max-Age=0" in c for c in response.headers.get_list("set-cookie"))


def _closed_lines(out: str) -> list[str]:
    lines = [line for line in out.splitlines() if line.startswith("logout_revocation_failed ")]
    for line in lines:
        assert USER_ID not in line and ACCOUNT_ID not in line and LEGACY not in line
    return lines


@pytest.mark.asyncio
async def test_local_logout_refuses_when_the_canonical_session_could_not_be_ended(sqlite_workers, capsys):
    authority = CanonicalAuthority(revoke_fails=True)
    app, settings = _build_guarded_app(
        local_verify=True, cache=sqlite_workers.cache1,
        verifier=_verifier(sqlite_workers), authority=authority,
    )
    cookie = create_session_token(settings, USER_ID, canonical_session_id=LEGACY)
    headers = {"Cookie": f"{SESSION_COOKIE}={cookie}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        assert (await client.get("/api/whoami", headers=headers)).status_code == 200
        out = await client.post("/api/auth/logout", headers=headers)
        assert out.status_code == 503
        body = out.json()["error"]
        assert body["code"] == "session_revocation_failed" and body["retryable"] is True
        assert body["message"]
        assert _cleared(out, SESSION_COOKIE) and _cleared(out, ACCESS_COOKIE)
        assert authority.revoke_calls == 1
        # A copy of the cookie made before the sign-out stays refused, also
        # after the ordinary deny window — the authority still holds it active.
        assert (await client.get("/api/whoami", headers=headers)).status_code == 401
        sqlite_workers.clock[0] += DENYLIST_TTL_SECONDS + 60
        assert (await client.get("/api/whoami", headers=headers)).status_code == 401
    assert _closed_lines(capsys.readouterr().out)


@pytest.mark.asyncio
async def test_local_logout_still_answers_ok_when_the_session_is_ended(sqlite_workers, capsys):
    authority = CanonicalAuthority(revoke_fails=False)
    app, settings = _build_guarded_app(
        local_verify=True, cache=sqlite_workers.cache1,
        verifier=_verifier(sqlite_workers), authority=authority,
    )
    cookie = create_session_token(settings, USER_ID, canonical_session_id=LEGACY)
    headers = {"Cookie": f"{SESSION_COOKIE}={cookie}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        out = await client.post("/api/auth/logout", headers=headers)
        assert out.status_code == 200 and out.json() == {"ok": True}
        assert LEGACY in authority.revoked
        sqlite_workers.clock[0] += DENYLIST_TTL_SECONDS + 60
        assert (await client.get("/api/whoami", headers=headers)).status_code == 401
    assert not _closed_lines(capsys.readouterr().out)


def _shared_flow(workers, *, remote_fails: bool):
    flow = object.__new__(SharedLoginFlow)
    flow.client_id = "b62"
    flow.public_base_url = PUBLIC_BASE
    flow.allowed_origins = (PUBLIC_BASE,)
    flow.clock = lambda: workers.clock[0]

    async def assertion(_now):
        return "synthetic-assertion"

    async def remote_revoke(_data):
        if remote_fails:
            raise RuntimeError("remote unreachable")

    flow._assertion = assertion
    flow.revoke_session = remote_revoke
    return flow


@pytest.mark.asyncio
@pytest.mark.parametrize("local_verify", [True, False])
async def test_shared_logout_refuses_when_the_legacy_session_could_not_be_ended(
    sqlite_workers, capsys, local_verify,
):
    verifier = _verifier(sqlite_workers)
    authority = CanonicalAuthority(revoke_fails=True)
    app, settings = _build_guarded_app(
        local_verify=local_verify, cache=sqlite_workers.cache1,
        verifier=verifier, authority=authority,
    )
    flow = _shared_flow(sqlite_workers, remote_fails=False)
    flow.auth = SimpleNamespace(verifier=verifier)
    app.router.routes.extend(flow.login_routes())
    cookie = create_session_token(settings, USER_ID, canonical_session_id=LEGACY)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        out = await client.post("/auth/shared/logout", headers={
            "Origin": PUBLIC_BASE,
            "Cookie": f"{SESSION_COOKIE}={cookie}; {REFRESH_COOKIE}={'O' * 43}.{'S' * 43}.{'R' * 43}",
        })
    assert out.status_code == 503
    assert out.json()["error"]["code"] == "session_revocation_failed"
    assert _cleared(out, SESSION_COOKIE) and _cleared(out, REFRESH_COOKIE)
    assert authority.revoke_calls == 1
    assert _closed_lines(capsys.readouterr().out)


@pytest.mark.asyncio
async def test_shared_logout_without_a_canonical_authority_has_nothing_to_end(sqlite_workers):
    verifier = _verifier(sqlite_workers)
    app, settings = _build_guarded_app(
        local_verify=True, cache=sqlite_workers.cache1, verifier=verifier, authority=None,
    )
    flow = _shared_flow(sqlite_workers, remote_fails=False)
    flow.auth = SimpleNamespace(verifier=verifier)
    app.router.routes.extend(flow.login_routes())
    cookie = create_session_token(settings, USER_ID, canonical_session_id=LEGACY)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        out = await client.post("/auth/shared/logout", headers={
            "Origin": PUBLIC_BASE,
            "Cookie": f"{SESSION_COOKIE}={cookie}; {REFRESH_COOKIE}={'O' * 43}.{'S' * 43}.{'R' * 43}",
        })
    assert out.status_code == 200 and out.json() == {"ok": True}
