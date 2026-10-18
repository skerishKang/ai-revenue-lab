"""#5094 — B66-only host composition for candidate review.

The review route must keep returning 503 until real server authorities exist.
These tests prove that the composed issuer only projects a *verified* Google
B66 administrator into a short-lived review grant, and that the target resolver
only accepts the candidate's stored owner scope when the shared canonical
identity contract still resolves to the same tenant.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_candidate_review_host_composition import (
    B66CanonicalCandidateTargetResolver,
    B66VerifiedAdminReviewGrantIssuer,
    build_b66_candidate_review_host,
)
from app.b66_member_admin import D1B66MemberAdminStore
from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from app.b66_saved_quote_skill_store import D1SavedQuoteSkillStore
from app.b66_saved_skill_candidate_store import (
    D1SavedQuoteSkillCandidateStore,
    canonicalize_candidate_submission,
)
from app.config import Settings

ADMIN = "usr_" + "a" * 32
CUSTOMER = "usr_" + "b" * 32
TENANT = "tenant_" + "c" * 32
SUBJECT = "subject:padiem:user:customer-b"
SESSION_ID = "authsession:b62:customer-b"
CANDIDATE_ID = "b66cand_" + "d" * 32
NOW = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "035_b66_saved_skill_candidate.sql"
SKILL_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "021_b66_saved_quote_skill.sql"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "b66_manual_candidate_v1.json"


class AdminStore:
    def __init__(self, admin: str = ADMIN) -> None:
        self.admin = admin
        self.calls: list[str] = []

    async def is_google_admin(self, user_id: str) -> bool:
        self.calls.append(user_id)
        return user_id == self.admin


class ShadowStore:
    def __init__(self, record) -> None:
        self.record = record

    async def load_projection(self, product_user_id: str):
        return self.record if product_user_id == self.record.product_user_id else None


class Authority:
    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[str] = []

    async def resolve_auth_session(self, *, session_id: str):
        self.calls.append(session_id)
        return self.session


def shadow_record(user_id: str = CUSTOMER, subject: str = SUBJECT, session_id: str = SESSION_ID):
    return SimpleNamespace(
        product_user_id=user_id,
        canonical_subject_id=subject,
        auth_session_id=session_id,
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=2),
        observed_at=NOW,
    )


def canonical_session(*, tenant_id: str | None = TENANT, subject: str = SUBJECT, now=NOW):
    return AuthSessionSnapshot(
        session_id=SESSION_ID,
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, subject),
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=2),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=tenant_id,
    )


def request_with(*, shadow=True, authority=True):
    state = SimpleNamespace(
        identity_shadow_store=ShadowStore(shadow_record()) if shadow else None,
        control_plane_identity_authority=Authority(canonical_session()) if authority else None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def scope(**overrides):
    value = {
        "candidate_id": CANDIDATE_ID,
        "user_id": CUSTOMER,
        "workspace_id": TENANT,
        "status": "pending",
    }
    value.update(overrides)
    return value


# ── grant issuer ─────────────────────────────────────────────────────────────


async def test_issuer_projects_only_the_verified_admin_into_a_bounded_grant():
    store = AdminStore()
    issuer = B66VerifiedAdminReviewGrantIssuer(member_admin_store=store, now=lambda: NOW)

    grant = await issuer(
        request=object(),
        operator_user_id=ADMIN,
        action=B66ProvisioningAction.REVIEW_CANDIDATE,
    )

    assert isinstance(grant, TrustedB66ProvisioningGrant)
    assert grant.operator_subject == CanonicalSubjectRef(SubjectType.USER, ADMIN)
    assert grant.allowed_actions == (B66ProvisioningAction.REVIEW_CANDIDATE,)
    assert grant.grant_ref.startswith("b66rgrant_")
    assert grant.authority_ref == "authority:b66:verified-google-admin"
    assert grant.issued_at == NOW
    assert grant.expires_at == NOW + timedelta(minutes=5)
    assert store.calls == [ADMIN]


async def test_issuer_refuses_unknown_operator_wrong_action_and_failing_store():
    issuer = B66VerifiedAdminReviewGrantIssuer(member_admin_store=AdminStore(), now=lambda: NOW)
    assert await issuer(
        request=object(), operator_user_id=CUSTOMER,
        action=B66ProvisioningAction.REVIEW_CANDIDATE,
    ) is None
    assert await issuer(
        request=object(), operator_user_id=ADMIN,
        action=B66ProvisioningAction.ASSIGN,
    ) is None
    assert await issuer(
        request=object(), operator_user_id="", action=B66ProvisioningAction.REVIEW_CANDIDATE,
    ) is None

    broken = AdminStore()

    async def explode(_uid):
        raise RuntimeError("membership unavailable")

    broken.is_google_admin = explode
    issuer = B66VerifiedAdminReviewGrantIssuer(member_admin_store=broken, now=lambda: NOW)
    assert await issuer(
        request=object(), operator_user_id=ADMIN,
        action=B66ProvisioningAction.REVIEW_CANDIDATE,
    ) is None


@pytest.mark.parametrize("minutes", [0, 16, True, "5", None])
def test_issuer_rejects_invalid_grant_windows(minutes):
    with pytest.raises(ValueError):
        B66VerifiedAdminReviewGrantIssuer(
            member_admin_store=AdminStore(), grant_minutes=minutes,
        )


async def test_issuer_rejects_a_naive_clock():
    issuer = B66VerifiedAdminReviewGrantIssuer(
        member_admin_store=AdminStore(), now=lambda: datetime(2026, 10, 19, 3, 0),
    )
    assert await issuer(
        request=object(), operator_user_id=ADMIN,
        action=B66ProvisioningAction.REVIEW_CANDIDATE,
    ) is None


# ── target resolver ──────────────────────────────────────────────────────────


def resolver_for(candidate_scope):
    store = SimpleNamespace(read_candidate_scope=AsyncMock(return_value=candidate_scope))
    return B66CanonicalCandidateTargetResolver(candidate_store=store, now=lambda: NOW)


async def test_resolver_uses_the_stored_scope_and_current_canonical_tenant():
    resolver = resolver_for(scope())
    target = await resolver(request=request_with(), candidate_id=CANDIDATE_ID)

    assert isinstance(target, ResolvedB66ProvisioningTarget)
    assert target.user_id == CUSTOMER
    assert target.workspace_id == TENANT
    assert target.tenant_id == TENANT
    assert target.canonical_subject_id == SUBJECT


@pytest.mark.parametrize(
    "candidate_scope, mode",
    [
        (None, None),
        (scope(status="approved"), None),
        (scope(workspace_id="owner:" + CUSTOMER), None),
        (scope(user_id=""), None),
        (scope(), "no_shadow"),
        (scope(), "no_authority"),
    ],
)
async def test_resolver_fails_closed_without_a_real_canonical_target(candidate_scope, mode):
    resolver = resolver_for(candidate_scope)
    if mode == "no_shadow":
        req = request_with(shadow=False)
    elif mode == "no_authority":
        req = request_with(authority=False)
    else:
        req = request_with()
    assert await resolver(request=req, candidate_id=CANDIDATE_ID) is None


async def test_resolver_refuses_missing_tenant_authority_failure_and_bad_id():
    resolver = resolver_for(scope())
    no_tenant = request_with()
    no_tenant.app.state.control_plane_identity_authority = Authority(canonical_session(tenant_id=None))
    assert await resolver(request=no_tenant, candidate_id=CANDIDATE_ID) is None

    unavailable = request_with()
    async def explode(*, session_id):
        raise RuntimeError("control plane unavailable")
    unavailable.app.state.control_plane_identity_authority.resolve_auth_session = explode
    assert await resolver(request=unavailable, candidate_id=CANDIDATE_ID) is None

    assert await resolver(request=request_with(), candidate_id="candidate-from-browser") is None


def test_host_builder_requires_both_real_inputs():
    assert build_b66_candidate_review_host(
        member_admin_store=None, candidate_store=object(),
    ) is None
    assert build_b66_candidate_review_host(
        member_admin_store=AdminStore(), candidate_store=None,
    ) is None
    composed = build_b66_candidate_review_host(
        member_admin_store=AdminStore(), candidate_store=object(),
    )
    assert composed is not None
    assert isinstance(composed[0], B66VerifiedAdminReviewGrantIssuer)
    assert isinstance(composed[1], B66CanonicalCandidateTargetResolver)


# ── factory wiring and end-to-end decision ───────────────────────────────────


class Prepared:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.execute(self.sql, self.args)
        self.db.commit()
        rows = cursor.fetchall()
        return {"results": [dict(row) for row in rows]}


class SQLiteD1:
    def __init__(self, db):
        self.db = db

    def prepare(self, sql):
        return Prepared(self.db, sql)


@pytest.fixture
def source():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO users(id) VALUES (?)", [(ADMIN,), (CUSTOMER,)])
    db.executescript(SKILL_MIGRATION.read_text(encoding="utf-8"))
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield db
    db.close()


def _settings():
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url="https://chat.example.test",
        google_client_id="candidate.apps.googleusercontent.com",
        google_client_secret="synthetic-only-google-secret",
        session_secret="synthetic-only-host-composition-session-secret",
        session_max_age_seconds=3600, live_enabled="false",
    )


def _member_admin():
    store = D1B66MemberAdminStore(MagicMock(), admin_email="admin@example.test")
    store.is_google_admin = AsyncMock(side_effect=lambda uid: uid == ADMIN)
    return store


def _app(source, *, canonical: bool):
    candidate_store = D1SavedQuoteSkillCandidateStore(SQLiteD1(source))
    skill_store = D1SavedQuoteSkillStore(SQLiteD1(source))
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        b66_saved_quote_skill_store=skill_store,
        b66_saved_skill_candidate_store=candidate_store,
        b66_member_admin_store=_member_admin(),
        identity_shadow_store=ShadowStore(shadow_record()) if canonical else None,
        control_plane_identity_authority=(
            Authority(canonical_session(now=datetime.now(timezone.utc))) if canonical else None
        ),
    )
    return app, candidate_store


def _client(app, user):
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(_settings(), user),
        domain="chat.example.test", path="/",
    )
    return client


def _fixture_candidate():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


async def test_factory_composes_review_host_and_approves_with_real_authorities(source):
    app, candidate_store = _app(source, canonical=True)
    assert callable(app.state.b66_operator_grant_resolver)
    assert callable(app.state.b66_operator_target_resolver)

    customer = _client(app, CUSTOMER)
    admin = _client(app, ADMIN)
    fixture = _fixture_candidate()
    submitted = customer.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": fixture["clientRef"], "candidate": fixture["candidate"]},
    )
    assert submitted.status_code == 200, submitted.text
    candidate_id = submitted.json()["candidate"]["candidate_id"]
    row = source.execute(
        "SELECT user_id, workspace_id FROM b66_saved_skill_candidate WHERE id=?",
        (candidate_id,),
    ).fetchone()
    assert dict(row) == {"user_id": CUSTOMER, "workspace_id": TENANT}

    decided = admin.post(
        f"/api/b66/admin/saved-skill-candidates/{candidate_id}/decision",
        json={"action": "approve"},
    )
    assert decided.status_code == 200, decided.text
    approval = decided.json()["approval"]
    assert approval["operator_subject_id"] == ADMIN
    assert approval["target_user_id"] == CUSTOMER
    assert approval["target_workspace_id"] == TENANT
    assert approval["target_tenant_id"] == TENANT
    assert approval["skill_fingerprint"] == fixture["candidate"]["skillFingerprint"]

    approved = customer.get(f"/api/b66/saved-skill-candidates/{candidate_id}")
    assert approved.status_code == 200
    assert approved.json()["candidate"]["status"] == "approved"


async def test_missing_canonical_identity_leaves_the_decision_fail_closed(source):
    app, candidate_store = _app(source, canonical=False)
    assert app.state.b66_operator_grant_resolver is not None
    assert app.state.b66_operator_target_resolver is not None

    fixture = _fixture_candidate()
    stored = await candidate_store.submit(
        user_id=CUSTOMER,
        workspace_id="owner:" + CUSTOMER,
        submission=canonicalize_candidate_submission(
            client_ref=fixture["clientRef"], candidate=fixture["candidate"],
        ),
    )
    admin = _client(app, ADMIN)
    decided = admin.post(
        f"/api/b66/admin/saved-skill-candidates/{stored['candidate_id']}/decision",
        json={"action": "approve"},
    )
    assert decided.status_code == 503
    assert decided.json()["error"]["code"] == "operator_target_unavailable"
