"""#7078 B — Request-time session verification via padiem-auth + SQLite denylist.

Covers:
1. Valid padiem-auth ES256 access token passes with 0 upstream authority/JWKS calls.
2. Expired, bad-signature, wrong-audience, duplicate, and access-less tokens are refused
   (no cookie bypass through a failed/missing access token; 60 s clock-skew leeway).
3. Legacy-cookie fallback (CTO decision 2026-11-12, #7078 B follow-up): with the switch
   ON, a request carrying only the 7-day padiem_session cookie is NOT refused — it is
   verified through the exact pre-switch path (legacy authority + cache rules) so live
   legacy-cookie traffic is never force-logged-out, the shared denylist still revokes it
   in 0 s, and each fallback request logs a countable ``legacy_session_fallback``
   outcome code with no cookie, token, or user identifiers. #7527's instant refusal of
   access-less requests was a transition-design choice reversed by this decision after
   operations showed 36 h of live legacy-cookie traffic (shadow token=absent_legacy_sid).
4. Revocation semantics & max delay bounds:
   - Same-host single-session logout (/api/auth/logout, /auth/shared/logout): 0 s across
     SQLite-sharing workers, keeping a second device's session alive; forged logout cookies
     never pollute the denylist.
   - Same-host password change & password reset (account-wide): 0 s across workers for all
     existing sessions, while immediate re-login with the new password succeeds.
   - Pending shared-revoke retry on /auth/shared/refresh refuses to mint post-change tokens.
   - Same-host account deletion: 0 s permanent block across workers.
   - Cross-product revocation / account-block: refresh rejected in 0 s, already-issued
     access strictly refused at <= 16 min (960 s = 900 s + 60 s leeway; <= 17 min = 1,020 s
     including up to 60 s host clock lag).
5. Fail-closed (503 session_authority_unavailable) when revocation cache is absent, SQLite
   errors, or   JWKS is unavailable with no usable key set (fetch failed and no fresh/stale keys) — unchanged
   for every path. A merely cold cache now refreshes on the request instead of 503 (#7078 B).
6. Default switch OFF (PADIEM_CHAT_LOCAL_VERIFY_ENABLED unset/false) preserves legacy guard.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import current_user_id, logout
from app.auth_validation_cache import (
    DENYLIST_TTL_SECONDS,
    SqliteAuthValidationCache,
    invalidate_auth_cache,
    record_auth_revocation,
)
from app.config import Settings, session_local_verify_enabled
from app.d1_sqlite import SqliteD1, connect
from app.session_revocation_guard import (
    ACCESS_COOKIE,
    LOCAL_VERIFY_LEEWAY_SECONDS,
    SESSION_AUTHORITY_UNAVAILABLE_CODE,
    SESSION_COOKIE_DUPLICATED_CODE,
    SessionRevocationGuardMiddleware,
    load_padiem_auth_verify_module,
)
from app.shared_auth_adapter import SharedChatAuth
from app.shared_login_flow import REFRESH_COOKIE, REFRESH_PATH, SharedLoginFlow
from app.shared_session_middleware import SharedSessionMiddleware

_verify_mod = load_padiem_auth_verify_module()
ISSUER = _verify_mod.ISSUER
Verifier = _verify_mod.Verifier

USER_ID = "usr_" + "a" * 32
OTHER_USER_ID = "usr_" + "b" * 32
ACCOUNT_ID = "sub_" + "c" * 24
OTHER_ACCOUNT_ID = "sub_" + "d" * 24
SID_ONE = "S" * 43
SID_TWO = "T" * 43
SID_THREE = "U" * 43
SID_NEW = "N" * 43
LEGACY_SID = "authsession:b62:legacy7078"
SESSION_SECRET = "synthetic-7078-b-session-secret-not-production-key"
PUBLIC_BASE = "https://chat.example.invalid"

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class TokenIssuer:
    def __init__(self, kid: str = "k7078") -> None:
        self.kid = kid
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        nums = self.private_key.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "kid": kid,
            "alg": "ES256",
            "use": "sig",
            "x": _b64u(nums.x.to_bytes(32, "big")),
            "y": _b64u(nums.y.to_bytes(32, "big")),
        }

    def mint(
        self,
        *,
        account_id: str = ACCOUNT_ID,
        sid: str = SID_ONE,
        iat: int = 10_000,
        exp: int | None = None,
        aud: str = "b62",
        iss: str = ISSUER,
        token_use: str = "access",
        kid: str | None = None,
        tamper_signature: bool = False,
    ) -> str:
        header = _b64u(
            json.dumps(
                {"alg": "ES256", "typ": "JWT", "kid": kid or self.kid},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        payload = {
            "iss": iss,
            "aud": aud,
            "sub": account_id,
            "account_id": account_id,
            "sid": sid,
            "iat": iat,
            "exp": iat + 900 if exp is None else exp,
            "token_use": token_use,
        }
        body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header}.{body}".encode("ascii")
        der = self.private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        sig = bytearray(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        if tamper_signature:
            sig[0] ^= 0xFF
        return f"{header}.{body}.{_b64u(bytes(sig))}"


class ForbidUpstreamAuthority:
    """Fails immediately if any request-time hot path touches the legacy authority."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve_auth_session(self, **_kwargs):
        self.calls.append("resolve_auth_session")
        raise AssertionError("legacy resolve_auth_session called on local-verify hot path")

    async def resolve_product_user_for_subject(self, **_kwargs):
        self.calls.append("resolve_product_user_for_subject")
        raise AssertionError("resolve_product_user_for_subject called on local-verify hot path")

    async def resolve_current_auth_session(self, **_kwargs):
        self.calls.append("resolve_current_auth_session")
        raise AssertionError("resolve_current_auth_session called on local-verify hot path")


@pytest.fixture
def sqlite_workers(tmp_path):
    db_path = tmp_path / "chat_7078_b.sqlite3"
    conn1 = connect(str(db_path))
    conn2 = connect(str(db_path))
    for sql_name in (
        "001_auth_history.sql",
        "007_control_plane_identity_shadow.sql",
        "087_auth_validation_cache.sql",
        "088_shared_account_link_cache.sql",
        "106_shared_session_revoke_pending.sql",
    ):
        conn1.executescript((_MIGRATIONS_DIR / sql_name).read_text(encoding="utf-8"))
    conn1.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
        "VALUES (?, 'google', ?, 'member@example.test', 'Member', '', '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z')",
        (USER_ID, "shared:" + ACCOUNT_ID),
    )
    conn1.execute(
        "INSERT INTO control_plane_identity_shadow "
        "(product_user_id, canonical_subject_id, auth_session_id, session_revision, session_state, session_expires_at, observed_at) "
        "VALUES (?, ?, ?, 1, 'active', '2026-11-19T00:00:00Z', '2026-11-12T00:00:00Z')",
        (USER_ID, ACCOUNT_ID, LEGACY_SID),
    )
    conn1.commit()
    clock = [10_100.0]
    d1_one = SqliteD1(conn1)
    d1_two = SqliteD1(conn2)
    cache1 = SqliteAuthValidationCache(
        d1_one, ttl_seconds=30, session_ttl_seconds=300, link_ttl_seconds=600, clock=lambda: clock[0]
    )
    cache2 = SqliteAuthValidationCache(
        d1_two, ttl_seconds=30, session_ttl_seconds=300, link_ttl_seconds=600, clock=lambda: clock[0]
    )
    yield SimpleNamespace(
        conn1=conn1,
        conn2=conn2,
        d1_one=d1_one,
        d1_two=d1_two,
        cache1=cache1,
        cache2=cache2,
        clock=clock,
    )
    conn1.close()
    conn2.close()


def _build_guarded_app(
    *,
    local_verify: bool,
    cache,
    verifier,
    authority,
    db=None,
):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=PUBLIC_BASE,
        session_secret=SESSION_SECRET,
        local_verify_enabled=local_verify,
    )

    async def protected_whoami(request: Request) -> JSONResponse:
        uid = current_user_id(request)
        if not uid:
            return JSONResponse({"error": {"code": "authentication_required"}}, status_code=401)
        shared_uid = getattr(request.state, "padiem_shared_user_id", None)
        return JSONResponse({"ok": True, "user_id": uid, "shared_user_id": shared_uid})

    app = Starlette(
        routes=[
            Route("/api/whoami", protected_whoami, methods=["GET"]),
            Route("/api/auth/logout", logout, methods=["POST"]),
        ]
    )
    app.state.settings = settings
    app.state.auth_validation_cache = cache
    app.state.local_token_verifier = verifier
    app.state.control_plane_identity_authority = authority
    app.state.account_data_db = db

    shared_auth = SharedChatAuth(
        verifier=verifier if verifier is not None else SimpleNamespace(verify=lambda _t: {}),
        authority=authority,
        legacy=current_user_id,
        canonical_session_lifetime_seconds=604800,
    )
    flow = SimpleNamespace(auth=shared_auth)
    app.state.shared_login_flow = flow
    app.add_middleware(SessionRevocationGuardMiddleware)
    app.add_middleware(SharedSessionMiddleware, flow=flow)
    return app, settings


def test_default_switch_is_off(monkeypatch):
    monkeypatch.delenv("PADIEM_CHAT_LOCAL_VERIFY_ENABLED", raising=False)
    default_settings = Settings.from_values(runtime_mode="mock")
    assert default_settings.local_verify_enabled is None
    assert session_local_verify_enabled(default_settings) is False
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_VERIFY_ENABLED", "true")
    assert session_local_verify_enabled(default_settings) is True
    explicit_off = Settings.from_values(runtime_mode="mock", local_verify_enabled=False)
    assert session_local_verify_enabled(explicit_off) is False


@pytest.mark.asyncio
async def test_valid_access_token_passes_with_zero_upstream_calls(sqlite_workers):
    issuer = TokenIssuer()
    jwks_fetches = 0

    def fetch_jwks():
        nonlocal jwks_fetches
        jwks_fetches += 1
        return {"keys": [issuer.jwk]}

    verifier = Verifier(
        "b62",
        fetcher=fetch_jwks,
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    # Startup prewarm loads JWKS once off the request path.
    verifier._keys(True)
    assert jwks_fetches == 1
    jwks_fetches = 0

    authority = ForbidUpstreamAuthority()
    app, settings = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=authority,
        db=sqlite_workers.d1_one,
    )
    access = issuer.mint(iat=10_000)
    legacy = create_session_token(settings, USER_ID, now=10_000, canonical_session_id=LEGACY_SID)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_BASE) as client:
        for _ in range(5):
            res = await client.get(
                "/api/whoami",
                headers={"Cookie": f"{ACCESS_COOKIE}={access}; {SESSION_COOKIE}={legacy}"},
            )
            assert res.status_code == 200
            assert res.json() == {
                "ok": True,
                "user_id": USER_ID,
                "shared_user_id": USER_ID,
            }

    assert authority.calls == []
    assert jwks_fetches == 0


@pytest.mark.asyncio
async def test_expired_forged_wrong_aud_duplicate_and_accessless_cookies_refused(sqlite_workers):
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)
    authority = ForbidUpstreamAuthority()
    app, settings = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=authority,
    )
    # Still-valid 7-day legacy cookie (real wall-clock now): must NEVER bypass a failed/missing access token.
    valid_legacy = create_session_token(settings, USER_ID, canonical_session_id=LEGACY_SID)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_BASE) as client:
        # 1. Expired beyond 60 s leeway (exp = 9_900, clock = 10_100 -> expired by 200 s)
        expired_tok = issuer.mint(iat=9_000, exp=9_900)
        r_exp = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={expired_tok}; {SESSION_COOKIE}={valid_legacy}"},
        )
        assert r_exp.status_code == 401

        # 2. Clock skew within 60 s leeway passes; 1 s past leeway is refused.
        skew_ok = issuer.mint(iat=10_155, exp=11_055)  # iat 55 s ahead of host clock
        r_skew_ok = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={skew_ok}"})
        assert r_skew_ok.status_code == 200

        skew_over = issuer.mint(iat=10_161, exp=11_061)  # iat 61 s ahead -> refused
        r_skew_over = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={skew_over}; {SESSION_COOKIE}={valid_legacy}"},
        )
        assert r_skew_over.status_code == 401

        # 3. Tampered ES256 signature -> refused
        forged_tok = issuer.mint(iat=10_000, tamper_signature=True)
        r_forged = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={forged_tok}; {SESSION_COOKIE}={valid_legacy}"},
        )
        assert r_forged.status_code == 401

        # 4. Wrong audience (BookAI b61 token sent to Chat b62) -> refused
        wrong_aud = issuer.mint(iat=10_000, aud="b61")
        r_aud = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={wrong_aud}; {SESSION_COOKIE}={valid_legacy}"},
        )
        assert r_aud.status_code == 401

        # 5. Unknown kid -> refused without remote JWKS fetch
        unknown_kid = issuer.mint(iat=10_000, kid="unknown-kid")
        r_kid = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={unknown_kid}"})
        assert r_kid.status_code == 401

        # 6. Access cookie absent with an unparsable legacy cookie: the guard
        # does not apply at all (no fallback, no verdict). A valid legacy-only
        # cookie is now covered by the legacy-path fallback tests below.
        r_legacy_only = await client.get(
            "/api/whoami", headers={"Cookie": f"{SESSION_COOKIE}=not-a-valid-cookie"}
        )
        assert r_legacy_only.status_code == 401

        # 7. Cross-account cookie mismatch (access=USER_ID, padiem_session=OTHER_USER_ID) -> refused
        other_legacy = create_session_token(
            settings, OTHER_USER_ID, canonical_session_id="authsession:b62:other"
        )
        valid_tok = issuer.mint(iat=10_000)
        r_mismatch = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={valid_tok}; {SESSION_COOKIE}={other_legacy}"},
        )
        assert r_mismatch.status_code == 401

        # 8. Duplicate __Host-padiem-shared-access cookies -> 401 session_cookie_duplicated
        r_dup = await client.get(
            "/api/whoami",
            headers={"Cookie": f"{ACCESS_COOKIE}={valid_tok}; {ACCESS_COOKIE}={forged_tok}"},
        )
        assert r_dup.status_code == 401
        assert r_dup.json()["error"]["code"] == SESSION_COOKIE_DUPLICATED_CODE

    assert authority.calls == []


@pytest.mark.asyncio
async def test_revocation_logout_password_change_deletion_and_cross_product_max_delay(sqlite_workers):
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)
    authority = ForbidUpstreamAuthority()

    app_w1, _ = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=authority,
        db=sqlite_workers.d1_one,
    )
    app_w2, _ = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache2,
        verifier=verifier,
        authority=authority,
        db=sqlite_workers.d1_two,
    )

    tok_dev1 = issuer.mint(sid=SID_ONE, iat=10_050)
    tok_dev2 = issuer.mint(sid=SID_TWO, iat=10_050)
    tok_dev3 = issuer.mint(sid=SID_THREE, iat=10_050)

    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app_w1), base_url=PUBLIC_BASE) as w1,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app_w2), base_url=PUBLIC_BASE) as w2,
    ):
        # Both devices initially pass across workers.
        assert (await w1.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev1}"})).status_code == 200
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev2}"})).status_code == 200

        # Forged cookie logout must NEVER denylist SID_TWO.
        forged_dev2 = issuer.mint(sid=SID_TWO, iat=10_050, tamper_signature=True)
        await w1.post("/api/auth/logout", headers={"Cookie": f"{ACCESS_COOKIE}={forged_dev2}"})
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev2}"})).status_code == 200

        # A. Single-session logout on worker 1 cuts SID_ONE in 0 s on worker 2, keeping SID_TWO alive.
        r_logout = await w1.post("/api/auth/logout", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev1}"})
        assert r_logout.status_code == 200
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev1}"})).status_code == 401
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev2}"})).status_code == 200

        # Positive cache invalidations (e.g. role change / expired logout) must NOT erase denylist rows.
        await sqlite_workers.cache1.invalidate_all()
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev1}"})).status_code == 401

        # B. Account-wide credential change / reset cuts ALL existing sessions (SID_TWO & unseen SID_THREE) in 0 s,
        # while an immediate new login (SID_NEW) succeeds and stays valid across the 20-min denylist window.
        req_w1 = SimpleNamespace(app=app_w1)
        await record_auth_revocation(req_w1, user_ids=(USER_ID,), account_ids=(ACCOUNT_ID,))
        await invalidate_auth_cache(req_w1, user_id=USER_ID)
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev2}"})).status_code == 401
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev3}"})).status_code == 401

        tok_new = issuer.mint(sid=SID_NEW, iat=10_105)
        await sqlite_workers.cache1.record_allowed_session(
            session_id=SID_NEW,
            user_id=USER_ID,
            account_id=ACCOUNT_ID,
            valid_until=10_105 + 960,
        )
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_new}"})).status_code == 200
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_dev2}"})).status_code == 401

        # C. Cross-product revocation / account-block bound:
        # Already-issued access (iat=10_105, exp=11_005) has max local residual of 16 min (960 s = 900 s + 60 s leeway).
        sqlite_workers.clock[0] = 10_105 + 959  # 15m 59s -> last valid second
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_new}"})).status_code == 200
        sqlite_workers.clock[0] = 10_105 + 960  # 16m 00s -> strictly refused
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_new}"})).status_code == 401

        # D. Account deletion permanent revocation cuts even a freshly allowed token in 0 s.
        sqlite_workers.clock[0] = 10_200
        tok_after = issuer.mint(sid="D" * 43, iat=10_200)
        await sqlite_workers.cache1.record_allowed_session(
            session_id="D" * 43,
            user_id=USER_ID,
            account_id=ACCOUNT_ID,
            valid_until=10_200 + 960,
        )
        assert (await w1.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_after}"})).status_code == 200
        await record_auth_revocation(
            req_w1, user_ids=(USER_ID,), account_ids=(ACCOUNT_ID,), permanent=True
        )
        assert (await w2.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_after}"})).status_code == 401
        assert DENYLIST_TTL_SECONDS == 1200


@pytest.mark.asyncio
async def test_pending_shared_revoke_blocks_refresh_from_issuing_new_tokens(sqlite_workers):
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    # Seed a pending shared-session revocation row (simulating transient outage during password reset).
    sqlite_workers.conn1.execute(
        "INSERT INTO shared_session_revoke_pending (user_id, created_at, attempts) VALUES (?, '2026-11-12T00:00:00Z', 1)",
        (USER_ID,),
    )
    sqlite_workers.conn1.commit()

    revoke_calls: list[dict] = []

    async def rpc_transport(**kwargs):
        revoke_calls.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "accounts": 1, "revoked_sessions": 1})

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=PUBLIC_BASE,
        session_secret=SESSION_SECRET,
        account_delete_rpc_secret="synthetic-account-delete-secret-32chars",
        local_verify_enabled=True,
    )
    flow = object.__new__(SharedLoginFlow)
    flow.client_id = "b62"
    flow.public_base_url = PUBLIC_BASE
    flow.allowed_origins = (PUBLIC_BASE,)
    flow.clock = lambda: sqlite_workers.clock[0]

    async def fake_assertion(_now):
        return "synthetic-assertion"

    flow._assertion = fake_assertion
    renewed_access = issuer.mint(sid=SID_TWO, iat=10_100)
    flow.exchange = lambda _url, _data: {
        "access_token": renewed_access,
        "refresh_token": "O" * 43 + "." + SID_TWO + "." + "R" * 43,
    }
    flow.resolve_account = lambda _req, _acc: USER_ID
    flow.auth = SimpleNamespace(verifier=verifier)

    app = Starlette(routes=flow.login_routes())
    app.state.settings = settings
    app.state.auth_validation_cache = sqlite_workers.cache1
    app.state.account_data_db = sqlite_workers.d1_one
    app.state.account_delete_rpc_transport = rpc_transport

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        res = await client.post(
            "/auth/shared/refresh",
            headers={
                "Origin": PUBLIC_BASE,
                "Cookie": f"{REFRESH_COOKIE}={'O'*43}.{SID_TWO}.{'R'*43}",
            },
        )
    assert res.status_code == 401
    assert len(revoke_calls) == 1
    sent_payload = json.loads(revoke_calls[0]["body"].decode("utf-8"))
    assert sent_payload["product_user_id"] == USER_ID
    assert sent_payload["account_id"] == ACCOUNT_ID
    assert await sqlite_workers.cache2.is_revoked(session_ids=(SID_TWO,), account_id=ACCOUNT_ID, user_id=USER_ID)


@pytest.mark.asyncio
async def test_revocation_check_unavailable_fails_closed_503(sqlite_workers):
    from app.auth_shadow_verify import _short_fetch

    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)
    tok = issuer.mint(iat=10_050)
    authority = ForbidUpstreamAuthority()

    # 1. Missing auth_validation_cache (None) -> 503 fail-closed
    app_no_cache, _ = _build_guarded_app(
        local_verify=True,
        cache=None,
        verifier=verifier,
        authority=authority,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_no_cache), base_url=PUBLIC_BASE) as client:
        r1 = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok}"})
        assert r1.status_code == 503
        assert r1.json()["error"]["code"] == SESSION_AUTHORITY_UNAVAILABLE_CODE

    # 2. Broken SQLite DB (missing auth_validation_cache table) -> 503 fail-closed
    broken_conn = connect(":memory:")
    broken_cache = SqliteAuthValidationCache(SqliteD1(broken_conn), clock=lambda: sqlite_workers.clock[0])
    app_broken_db, _ = _build_guarded_app(
        local_verify=True,
        cache=broken_cache,
        verifier=verifier,
        authority=authority,
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_broken_db), base_url=PUBLIC_BASE) as client:
            r2 = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok}"})
            assert r2.status_code == 503
            assert r2.json()["error"]["code"] == SESSION_AUTHORITY_UNAVAILABLE_CODE
    finally:
        broken_conn.close()

    # 3. Cold JWKS with an unreachable key endpoint -> 503 fail-closed (no keys).
    cold_verifier = Verifier(
        "b62",
        fetcher=_short_fetch,
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    cold_verifier.fetcher = lambda: (_ for _ in ()).throw(OSError("jwks down"))
    app_cold_jwks, _ = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=cold_verifier,
        authority=authority,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_cold_jwks), base_url=PUBLIC_BASE) as client:
        r3 = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok}"})
        assert r3.status_code == 503
        assert r3.json()["error"]["code"] == SESSION_AUTHORITY_UNAVAILABLE_CODE

    # 4. Cold JWKS with a reachable endpoint -> refresh on the request, not 503.
    warm_verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    app_warm_jwks, _ = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=warm_verifier,
        authority=authority,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_warm_jwks), base_url=PUBLIC_BASE) as client:
        r4 = await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok}"})
        assert r4.status_code == 200
        assert warm_verifier.last_refresh_reason == "jwks_refreshed"


@pytest.mark.asyncio
async def test_switch_off_keeps_legacy_authority_behavior(sqlite_workers):
    from datetime import datetime, timedelta, timezone
    from padiem_control_plane import AuthSessionSnapshot, AuthSessionState
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    now_dt = datetime.now(timezone.utc)
    resolve_calls = 0

    class LegacyAuthority:
        async def resolve_auth_session(self, *, session_id):
            nonlocal resolve_calls
            resolve_calls += 1
            return AuthSessionSnapshot(
                session_id=session_id,
                product_id="b62",
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=ACCOUNT_ID),
                issued_at=now_dt,
                expires_at=now_dt + timedelta(hours=1),
                state=AuthSessionState.ACTIVE,
            )

    app_off, settings_off = _build_guarded_app(
        local_verify=False,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=LegacyAuthority(),
    )
    legacy_cookie = create_session_token(
        settings_off, USER_ID, canonical_session_id="authsession:b62:switch-off"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_off), base_url=PUBLIC_BASE) as client:
        res = await client.get("/api/whoami", headers={"Cookie": f"{SESSION_COOKIE}={legacy_cookie}"})
        assert res.status_code == 200
        assert res.json()["user_id"] == USER_ID
    assert resolve_calls == 1


@pytest.mark.asyncio
async def test_switch_on_legacy_only_cookie_uses_legacy_path_with_reason_code(
    sqlite_workers, capsys
):
    """CTO decision 2026-11-12 (#7078 B follow-up) — NOT a weakening of #7527.

    #7527 refused a request carrying only the 7-day padiem_session cookie the
    moment the local-verify switch turned on, and operations then saw 36 h of
    live legacy-cookie traffic (shadow token=absent_legacy_sid, 2,845 requests)
    fail as session_unverified. The transition design changed: with the switch
    ON, a legacy-only cookie is verified through the exact pre-switch path —
    legacy authority + cache rules, upstream calls exactly per the legacy cache
    rules — while the access-table fast path keeps 0 upstream calls. Every
    fallback request logs a countable ``legacy_session_fallback`` outcome code
    with no cookie, token, or user identifiers.
    """
    from datetime import datetime, timedelta, timezone
    from padiem_control_plane import AuthSessionSnapshot, AuthSessionState
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    now_dt = datetime.now(timezone.utc)
    resolve_calls = 0

    class LegacyAuthority:
        async def resolve_auth_session(self, *, session_id):
            nonlocal resolve_calls
            resolve_calls += 1
            return AuthSessionSnapshot(
                session_id=session_id,
                product_id="b62",
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=ACCOUNT_ID),
                issued_at=now_dt,
                expires_at=now_dt + timedelta(hours=1),
                state=AuthSessionState.ACTIVE,
            )

    authority = LegacyAuthority()
    app, settings = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=authority,
    )
    legacy_cookie = create_session_token(
        settings, USER_ID, canonical_session_id="authsession:b62:legacy-fallback"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        first = await client.get("/api/whoami", headers={"Cookie": f"{SESSION_COOKIE}={legacy_cookie}"})
        assert first.status_code == 200
        assert first.json()["user_id"] == USER_ID
        # Cache miss follows the legacy rule: exactly one authority call.
        assert resolve_calls == 1
        second = await client.get("/api/whoami", headers={"Cookie": f"{SESSION_COOKIE}={legacy_cookie}"})
        assert second.status_code == 200
        # Cache hit within the legacy TTL serves without another authority call.
        assert resolve_calls == 1

    captured = capsys.readouterr().out
    assert "legacy_session_fallback outcome=active" in captured
    # The reason-code line never carries identifiers.
    for line in captured.splitlines():
        if line.startswith("legacy_session_fallback"):
            assert USER_ID not in line
            assert "authsession:" not in line


@pytest.mark.asyncio
async def test_switch_on_legacy_only_cookie_with_deny_marker_is_refused(
    sqlite_workers, capsys
):
    """The shared denylist applies to legacy-path requests with 0 s delay.

    A logout / password-change / deletion deny marker recorded by another
    worker refuses the legacy-only cookie before the legacy authority is even
    consulted, so Chat-internal revocation stays instant on the fallback path.
    """
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    class ForbidLegacyAuthority:
        async def resolve_auth_session(self, **_kwargs):
            raise AssertionError("legacy authority must not run after a deny marker")

    authority = ForbidLegacyAuthority()
    app, settings = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=authority,
    )
    legacy_cookie = create_session_token(
        settings, USER_ID, canonical_session_id="authsession:b62:legacy-denied"
    )
    await sqlite_workers.cache1.record_revocation(
        session_ids=("authsession:b62:legacy-denied",),
        user_ids=(USER_ID,),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        refused = await client.get(
            "/api/whoami", headers={"Cookie": f"{SESSION_COOKIE}={legacy_cookie}"}
        )
        assert refused.status_code == 401

    captured = capsys.readouterr().out
    assert "legacy_session_fallback outcome=revoked" in captured


@pytest.mark.asyncio
async def test_per_request_latency_comparison_local_vs_legacy_authority(sqlite_workers):
    """Measure local verification latency and verify it stays well under 5 ms/req."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from padiem_control_plane import AuthSessionSnapshot, AuthSessionState
    from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)
    tok = issuer.mint(iat=10_050)

    guard = SessionRevocationGuardMiddleware(None)
    local_settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=PUBLIC_BASE,
        session_secret=SESSION_SECRET,
        local_verify_enabled=True,
    )
    local_app = SimpleNamespace(
        state=SimpleNamespace(
            settings=local_settings,
            auth_validation_cache=sqlite_workers.cache1,
            local_token_verifier=verifier,
            control_plane_identity_authority=ForbidUpstreamAuthority(),
        )
    )
    local_scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/whoami",
        "headers": [(b"cookie", f"{ACCESS_COOKIE}={tok}".encode("latin-1"))],
        "app": local_app,
    }
    # Warm once, then sample 100 local checks.
    assert (await guard.resolve_verdict(local_scope)).authenticated is True
    local_samples_ms: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        verdict = await guard.resolve_verdict(local_scope)
        local_samples_ms.append((time.perf_counter() - t0) * 1000.0)
        assert verdict is not None and verdict.authenticated is True

    # Simulated legacy upstream miss (conservative 20 ms mock vs ~400-1,217 ms Production LAX RTT).
    now_dt = datetime.now(timezone.utc)

    class SimulatedRemoteAuthority:
        async def resolve_auth_session(self, *, session_id):
            await asyncio.sleep(0.020)
            return AuthSessionSnapshot(
                session_id=session_id,
                product_id="b62",
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=ACCOUNT_ID),
                issued_at=now_dt,
                expires_at=now_dt + timedelta(hours=1),
                state=AuthSessionState.ACTIVE,
            )

    legacy_settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=PUBLIC_BASE,
        session_secret=SESSION_SECRET,
        local_verify_enabled=False,
    )
    legacy_cookie = create_session_token(
        legacy_settings, USER_ID, canonical_session_id="authsession:b62:bench"
    )
    legacy_app = SimpleNamespace(
        state=SimpleNamespace(
            settings=legacy_settings,
            auth_validation_cache=None,
            control_plane_identity_authority=SimulatedRemoteAuthority(),
        )
    )
    legacy_scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/whoami",
        "headers": [(b"cookie", f"{SESSION_COOKIE}={legacy_cookie}".encode("latin-1"))],
        "app": legacy_app,
    }
    t0 = time.perf_counter()
    legacy_verdict = await guard.resolve_verdict(legacy_scope)
    legacy_miss_ms = (time.perf_counter() - t0) * 1000.0
    assert legacy_verdict is not None and legacy_verdict.authenticated is True

    median_local_ms = statistics.median(local_samples_ms)
    assert median_local_ms < 5.0
    assert legacy_miss_ms > median_local_ms * 5


@pytest.mark.asyncio
async def test_shared_logout_records_local_denylist_even_when_remote_revoke_fails(sqlite_workers):
    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: sqlite_workers.clock[0],
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=PUBLIC_BASE,
        session_secret=SESSION_SECRET,
        local_verify_enabled=True,
    )
    flow = object.__new__(SharedLoginFlow)
    flow.client_id = "b62"
    flow.public_base_url = PUBLIC_BASE
    flow.allowed_origins = (PUBLIC_BASE,)
    flow.clock = lambda: sqlite_workers.clock[0]

    async def fake_assertion(_now):
        return "synthetic-assertion"

    flow._assertion = fake_assertion

    async def broken_remote_revoke(_data):
        raise RuntimeError("auth.padiem.net unreachable")

    flow.revoke_session = broken_remote_revoke
    flow.auth = SimpleNamespace(verifier=verifier)

    app, _ = _build_guarded_app(
        local_verify=True,
        cache=sqlite_workers.cache1,
        verifier=verifier,
        authority=ForbidUpstreamAuthority(),
    )
    app.router.routes.extend(flow.login_routes())

    tok_1 = issuer.mint(sid=SID_ONE, iat=10_050)
    tok_2 = issuer.mint(sid=SID_TWO, iat=10_050)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=PUBLIC_BASE) as client:
        assert (await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_1}"})).status_code == 200
        out = await client.post(
            "/auth/shared/logout",
            headers={
                "Origin": PUBLIC_BASE,
                "Cookie": f"{ACCESS_COOKIE}={tok_1}; {REFRESH_COOKIE}={'O'*43}.{SID_ONE}.{'R'*43}",
            },
        )
        assert out.status_code == 200
        # Even though remote /logout raised, local SQLite denylist immediately blocks tok_1 while keeping tok_2.
        assert (await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_1}"})).status_code == 401
        assert (await client.get("/api/whoami", headers={"Cookie": f"{ACCESS_COOKIE}={tok_2}"})).status_code == 200


def test_password_change_and_reset_in_local_mode_denylist_and_fail_closed_without_cache():
    from test_5434_password_change import (
        CURRENT_PASSWORD as CHANGE_CURRENT,
        NEW_PASSWORD as CHANGE_NEW,
        build_app as build_change_app,
        seed_db as seed_change_db,
    )
    from test_5441_password_reset import (
        RecordingDelivery,
        _token_from_mail,
        build_app as build_reset_app,
        confirm_reset,
        request_reset,
        seed_db as seed_reset_db,
    )

    issuer = TokenIssuer()
    verifier = Verifier(
        "b62",
        fetcher=lambda: {"keys": [issuer.jwk]},
        clock=lambda: 10_100.0,
        leeway_seconds=LOCAL_VERIFY_LEEWAY_SECONDS,
    )
    verifier._keys(True)

    # 1. Password change with local_verify_enabled=True and missing cache -> 503 fail-closed (credential untouched)
    db_c, ids_c = seed_change_db()
    app_c, settings_c, _ = build_change_app(db_c)
    app_c.state.settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.padiem.test",
        session_secret=settings_c.session_secret,
        local_verify_enabled=True,
    )
    app_c.state.local_token_verifier = verifier
    # Seed local subject mapping in SQLite so local verify authenticates the request
    raw_conn = connect(":memory:")
    for sql_name in ("087_auth_validation_cache.sql", "088_shared_account_link_cache.sql"):
        raw_conn.executescript((_MIGRATIONS_DIR / sql_name).read_text(encoding="utf-8"))
    cache_c = SqliteAuthValidationCache(SqliteD1(raw_conn), link_ttl_seconds=600, clock=lambda: 10_100.0)
    import asyncio
    asyncio.run(cache_c.record_allowed_session(
        session_id=SID_ONE, user_id=ids_c["member"], account_id=ACCOUNT_ID, valid_until=11_000.0
    ))
    app_c.state.auth_validation_cache = cache_c
    app_c.state.control_plane_identity_authority = None
    access_c = issuer.mint(sid=SID_ONE, iat=10_050)

    async def _run_change():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_c), base_url="https://chat.padiem.test"
        ) as client:
            r = await client.post(
                "/api/auth/password/change",
                headers={
                    "Origin": "https://chat.padiem.test",
                    "Cookie": f"{ACCESS_COOKIE}={access_c}",
                },
                json={"current_password": CHANGE_CURRENT, "new_password": CHANGE_NEW},
            )
            return r

    res_ok = asyncio.run(_run_change())
    assert res_ok.status_code == 200
    assert asyncio.run(cache_c.is_revoked(session_ids=(SID_TWO,), account_id=ACCOUNT_ID, user_id=ids_c["member"])) is True
    raw_conn.close()

    # 2. Password reset with local_verify_enabled=True and NO cache -> 503 fail-closed
    db_r, ids_r = seed_reset_db()
    delivery = RecordingDelivery()
    app_r, settings_r = build_reset_app(db_r, delivery=delivery)
    app_r.state.settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.padiem.test",
        session_secret=settings_r.session_secret,
        local_verify_enabled=True,
    )
    app_r.state.auth_validation_cache = None
    app_r.state.control_plane_identity_authority = None
    request_reset(app_r, ids_r["member_email"])
    reset_tok = _token_from_mail(delivery)
    res_fail = confirm_reset(app_r, reset_tok)
    assert res_fail.status_code == 503


@pytest.mark.asyncio
async def test_bare_request_without_app_in_scope_does_not_raise_key_error():
    """Starlette Request.app raises KeyError when scope has no 'app' key."""
    bare = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/shared/logout",
            "headers": [(b"origin", PUBLIC_BASE.encode())],
        }
    )
    flow = object.__new__(SharedLoginFlow)
    flow.public_base_url = PUBLIC_BASE
    flow.allowed_origins = (PUBLIC_BASE,)
    flow.auth = None
    out = await flow.logout(bare)
    assert out.status_code == 200


