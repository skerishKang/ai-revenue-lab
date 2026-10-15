"""B66 #3186 — Saved Quote Skill candidate (approval request) server contract tests.

Covers the customer submission/read routes, the durable store, and the trusted
operator review contract. Network-free: sqlite-backed D1 fake, synthetic accounts,
no production data, no provider calls.

The candidate envelope fixture is produced by the B66 JavaScript contract
(``quote-skill-manual.js``) so the server is exercised against the real client
payload rather than a hand-written approximation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from app.b66_saved_quote_skill_store import (
    D1SavedQuoteSkillStore,
    canonicalize_approved_artifact,
)
from app.b66_saved_skill_candidate_review import (
    B66CandidateReviewError,
    B66SavedQuoteSkillCandidateReviewer,
)
from app.b66_saved_skill_candidate_store import (
    D1SavedQuoteSkillCandidateStore,
    SavedQuoteSkillCandidateStoreError,
    canonicalize_candidate_submission,
)
from app.config import Settings
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32
WA = "owner:" + A
WB = "owner:" + B
NOW = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)
OPERATOR = "usr_operator1"
GRANT_REF = "b66grant_" + "d" * 32

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "035_b66_saved_skill_candidate.sql"
# The reviewer writes approved Skills through the existing #3301 store, so the
# candidate table is exercised against the real Saved Quote Skill schema too.
SKILL_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "021_b66_saved_quote_skill.sql"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "b66_manual_candidate_v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _candidate() -> dict:
    return _fixture()["candidate"]


def _client_ref() -> str:
    return _fixture()["clientRef"]


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


def _grant(*actions, issued_at=None, expires_at=None):
    return TrustedB66ProvisioningGrant(
        grant_ref=GRANT_REF,
        operator_subject=CanonicalSubjectRef(SubjectType.USER, OPERATOR),
        authority_ref="authority:b66:ops",
        allowed_actions=tuple(actions or (B66ProvisioningAction.REVIEW_CANDIDATE,)),
        issued_at=issued_at or (NOW - timedelta(minutes=5)),
        expires_at=expires_at or (NOW + timedelta(minutes=30)),
    )


def _target(user_id=A, workspace_id=WA):
    return ResolvedB66ProvisioningTarget(
        user_id=user_id,
        workspace_id=workspace_id,
        tenant_id="tenant_" + "c" * 32,
        canonical_subject_id="subject_customer_a",
    )


@pytest.fixture
def source():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO users(id) VALUES (?)", [(A,), (B,)])
    db.executescript(SKILL_MIGRATION.read_text(encoding="utf-8"))
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield db
    db.close()


def _stores(db):
    return D1SavedQuoteSkillCandidateStore(SQLiteD1(db)), D1SavedQuoteSkillStore(SQLiteD1(db))


def _client(candidate_store, skill_store, user=A, signed_in=True):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url="https://chat.example.test",
        google_client_id="candidate.apps.googleusercontent.com",
        google_client_secret="synthetic-only-google-secret",
        session_secret="synthetic-only-candidate-test-session-secret",
        session_max_age_seconds=3600, live_enabled="false",
    )
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=skill_store,
        b66_saved_skill_candidate_store=candidate_store,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE, create_session_token(settings, user),
            domain="chat.example.test", path="/",
        )
    return client


# ── store ────────────────────────────────────────────────────────────────────


async def test_store_submit_is_owner_scoped_and_idempotent(source):
    candidate_store, _ = _stores(source)
    submission = canonicalize_candidate_submission(
        client_ref=_client_ref(), candidate=_candidate()
    )
    first = await candidate_store.submit(user_id=A, workspace_id=WA, submission=submission)
    assert first["status"] == "pending"
    assert first["candidate_id"].startswith("b66cand_")
    assert first["duplicate"] is False
    assert first["candidate_digest"]
    # The stored envelope is exactly what the client sent.
    assert first["candidate"]["skillFingerprint"] == _candidate()["skillFingerprint"]

    # Same browser request (same client ref) must not open a second row.
    again = await candidate_store.submit(user_id=A, workspace_id=WA, submission=submission)
    assert again["duplicate"] is True
    assert again["candidate_id"] == first["candidate_id"]
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 1

    # Identical content with a different client ref is still the same request.
    other_ref = canonicalize_candidate_submission(client_ref="manual-retry-0001", candidate=_candidate())
    third = await candidate_store.submit(user_id=A, workspace_id=WA, submission=other_ref)
    assert third["duplicate"] is True
    assert third["candidate_id"] == first["candidate_id"]
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 1

    # A different owner is a different scope entirely.
    foreign = await candidate_store.submit(user_id=B, workspace_id=WB, submission=submission)
    assert foreign["candidate_id"] != first["candidate_id"]
    assert await candidate_store.get_candidate(user_id=B, workspace_id=WB, candidate_id=first["candidate_id"]) is None
    assert await candidate_store.get_candidate(user_id=A, workspace_id=WB, candidate_id=first["candidate_id"]) is None
    assert await candidate_store.get_candidate(user_id=A, workspace_id=WA, candidate_id=first["candidate_id"]) is not None


async def test_store_changed_content_opens_a_new_request(source):
    candidate_store, _ = _stores(source)
    first = await candidate_store.submit(
        user_id=A, workspace_id=WA,
        submission=canonicalize_candidate_submission(client_ref=_client_ref(), candidate=_candidate()),
    )
    changed = _candidate()
    changed["name"] = "다른 견적서"
    second = await candidate_store.submit(
        user_id=A, workspace_id=WA,
        submission=canonicalize_candidate_submission(client_ref="manual-changed-0002", candidate=changed),
    )
    assert second["candidate_id"] != first["candidate_id"]
    assert second["duplicate"] is False
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 2

    listed = await candidate_store.list_candidates(user_id=A, workspace_id=WA, limit=50)
    assert len(listed) == 2
    assert all("candidate" not in row for row in listed)


async def test_store_refuses_preapproved_and_invalid_candidates():
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="manual-bad-0003", candidate={"schemaVersion": 1})
    preapproved = _candidate()
    preapproved["approval"] = {"status": "approved"}
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="manual-bad-0004", candidate=preapproved)
    already = _candidate()
    already["status"] = "approved"
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="manual-bad-0005", candidate=already)
    bad_fingerprint = _candidate()
    bad_fingerprint["skillFingerprint"] = "not-hex"
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="manual-bad-0006", candidate=bad_fingerprint)
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="short", candidate=_candidate())
    owner_field = _candidate()
    owner_field["user_id"] = B
    with pytest.raises(SavedQuoteSkillCandidateStoreError):
        canonicalize_candidate_submission(client_ref="manual-bad-0007", candidate=owner_field)


async def test_store_decision_is_pending_only(source):
    candidate_store, skill_store = _stores(source)
    row = await candidate_store.submit(
        user_id=A, workspace_id=WA,
        submission=canonicalize_candidate_submission(client_ref=_client_ref(), candidate=_candidate()),
    )
    saved = await skill_store.put_approved_skill(
        user_id=A, workspace_id=WA,
        artifact=canonicalize_approved_artifact(
            skill_id="saved-quote-1", skill_name="우리회사 견적서", fingerprint="a" * 64, version=1,
            serialized_json=json.dumps(_approved_payload("a" * 64), ensure_ascii=False),
        ),
    )
    decided = await candidate_store.record_decision(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"],
        decision="approve", decided_by=OPERATOR, decision_ref=GRANT_REF,
        decided_at="2026-10-11T06:00:00.000Z", saved_skill_id=saved["saved_skill_id"], skill_version=1,
    )
    assert decided["status"] == "approved"
    assert decided["saved_skill_id"] == saved["saved_skill_id"]
    assert "decision_by" not in decided  # operator identity is never projected

    # A second decision cannot overwrite the recorded verdict.
    replayed = await candidate_store.record_decision(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"],
        decision="reject", decided_by=OPERATOR, decision_ref=GRANT_REF,
        decided_at="2026-10-11T07:00:00.000Z", rejection_reason="late",
    )
    assert replayed["status"] == "approved"
    assert replayed["rejection_reason"] == ""

    assert await candidate_store.record_decision(
        user_id=B, workspace_id=WB, candidate_id=row["candidate_id"],
        decision="approve", decided_by=OPERATOR, decision_ref=GRANT_REF,
        decided_at="2026-10-11T07:00:00.000Z", saved_skill_id=saved["saved_skill_id"], skill_version=1,
    ) is None


def _approved_payload(fingerprint: str, skill_id: str = "saved-quote-1") -> dict:
    return {
        "schemaVersion": 1, "id": skill_id, "name": "우리회사 견적서",
        "fixedDefaults": {}, "variableSchema": {}, "internalTemplate": {}, "provenance": {},
        "approval": {
            "schemaVersion": 1, "status": "approved", "skillFingerprint": fingerprint,
            "approvedBy": "operator:test", "approvedAt": "2026-10-11T00:00:00Z",
            "approvalRef": "manual:test",
        },
        "fingerprint": fingerprint,
        "rendererContract": "quote-template-renderer.v1", "calculationAuthority": "quote-core",
        "createdAt": "2026-10-11T00:00:00Z", "updatedAt": "2026-10-11T00:00:00Z",
    }


# ── routes ───────────────────────────────────────────────────────────────────


def test_route_requires_login_and_rejects_client_owner(source):
    candidate_store, skill_store = _stores(source)
    anonymous = _client(candidate_store, skill_store, signed_in=False)
    body = {"client_ref": _client_ref(), "candidate": _candidate()}
    assert anonymous.post("/api/b66/saved-skill-candidates", json=body).status_code == 401
    assert anonymous.get("/api/b66/saved-skill-candidates").status_code == 401

    owner = _client(candidate_store, skill_store)
    for key in ("user_id", "owner", "workspaceId", "tenant_id"):
        payload = dict(body)
        payload[key] = B
        assert owner.post("/api/b66/saved-skill-candidates", json=payload).status_code == 400
    assert owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": _candidate(), "status": "approved"},
    ).status_code == 400
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 0


def test_route_submit_list_and_detail(source):
    candidate_store, skill_store = _stores(source)
    owner = _client(candidate_store, skill_store)
    created = owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": _candidate()},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["ok"] is True
    assert payload["duplicate"] is False
    assert payload["candidate"]["status"] == "pending"
    assert payload["approval"]["requested"] is True
    assert payload["approval"]["approved"] is False
    assert payload["approval"]["decided_by_customer"] is False
    assert created.headers["cache-control"].startswith("no-store")
    candidate_id = payload["candidate"]["candidate_id"]

    duplicate = owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": _candidate()},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["candidate"]["candidate_id"] == candidate_id
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 1

    listed = owner.get("/api/b66/saved-skill-candidates")
    assert listed.status_code == 200
    assert [row["candidate_id"] for row in listed.json()["candidates"]] == [candidate_id]
    assert "candidate" not in listed.json()["candidates"][0]
    assert owner.get("/api/b66/saved-skill-candidates?limit=0").status_code == 400

    detail = owner.get(f"/api/b66/saved-skill-candidates/{candidate_id}")
    assert detail.status_code == 200
    assert detail.json()["candidate"]["candidate_id"] == candidate_id
    assert owner.get("/api/b66/saved-skill-candidates/b66cand_" + "z" * 32).status_code == 400
    assert owner.get("/api/b66/saved-skill-candidates/b66cand_" + "0" * 32).status_code == 404


def test_route_other_account_cannot_read_or_submit_as_owner(source):
    candidate_store, skill_store = _stores(source)
    owner = _client(candidate_store, skill_store)
    created = owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": _candidate()},
    ).json()
    candidate_id = created["candidate"]["candidate_id"]

    foreign = _client(candidate_store, skill_store, user=B)
    assert foreign.get("/api/b66/saved-skill-candidates").json()["candidates"] == []
    assert foreign.get(f"/api/b66/saved-skill-candidates/{candidate_id}").status_code == 404


def test_route_exposes_no_customer_approval_path(source):
    candidate_store, skill_store = _stores(source)
    owner = _client(candidate_store, skill_store)
    created = owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": _candidate()},
    ).json()
    candidate_id = created["candidate"]["candidate_id"]

    # No customer-facing decision route exists in any method or spelling.
    for path in (
        f"/api/b66/saved-skill-candidates/{candidate_id}",
        f"/api/b66/saved-skill-candidates/{candidate_id}/approve",
        f"/api/b66/saved-skill-candidates/{candidate_id}/decision",
        "/api/b66/saved-skill-candidates/approve",
        "/api/b66/saved-skill-candidate-review",
    ):
        for method in ("post", "put", "patch", "delete"):
            reply = getattr(owner, method)(path)
            assert reply.status_code in {404, 405}, f"{method} {path} must not exist"
        # A decision body is rejected the same way, not interpreted.
        assert owner.post(path, json={"status": "approved", "decision": "approve"}).status_code in {404, 405}

    # The submitted candidate is still pending and no Saved Quote Skill exists.
    detail = owner.get(f"/api/b66/saved-skill-candidates/{candidate_id}").json()
    assert detail["candidate"]["status"] == "pending"
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0


def test_route_oversized_body_is_rejected(source):
    candidate_store, skill_store = _stores(source)
    owner = _client(candidate_store, skill_store)
    huge = _candidate()
    huge["name"] = "N" * 20000
    reply = owner.post(
        "/api/b66/saved-skill-candidates",
        json={"client_ref": _client_ref(), "candidate": huge},
    )
    assert reply.status_code in {400, 413}
    assert source.execute("SELECT COUNT(*) FROM b66_saved_skill_candidate").fetchone()[0] == 0


# ── trusted operator review ──────────────────────────────────────────────────


async def _pending(source):
    candidate_store, skill_store = _stores(source)
    row = await candidate_store.submit(
        user_id=A, workspace_id=WA,
        submission=canonicalize_candidate_submission(client_ref=_client_ref(), candidate=_candidate()),
    )
    return candidate_store, skill_store, row


async def test_reviewer_requires_an_authorized_grant(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)

    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant="not-a-grant", target=_target(), candidate_id=row["candidate_id"],
            action="approve", now=NOW,
        )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(B66ProvisioningAction.ASSIGN), target=_target(),
            candidate_id=row["candidate_id"], action="approve", now=NOW,
        )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(issued_at=NOW - timedelta(hours=2), expires_at=NOW - timedelta(hours=1)),
            target=_target(), candidate_id=row["candidate_id"], action="approve", now=NOW,
        )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
            action="activate", now=NOW,
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0
    assert await candidate_store.get_candidate(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"]
    ) is not None
    assert (await candidate_store.get_candidate(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"]
    ))["status"] == "pending"


async def test_reviewer_approve_assigns_skill_to_the_target_account_only(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)

    receipt = await reviewer.review(
        grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
        action="approve", now=NOW,
    )
    assert receipt.action.value == "approve"
    assert receipt.saved_skill_id.startswith("b66skill_")
    assert receipt.operator_subject_id == OPERATOR
    assert receipt.target_user_id == A
    assert receipt.candidate_id == row["candidate_id"]
    safe = receipt.safe_dict()
    assert safe["grant_ref"] == GRANT_REF
    assert safe["occurred_at"] == NOW.isoformat()

    decided = await candidate_store.get_candidate(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"]
    )
    assert decided["status"] == "approved"
    assert decided["saved_skill_id"] == receipt.saved_skill_id
    assert decided["skill_version"] == 1
    assert decided["decided_at"]

    # The assigned Skill is readable only by the target account/workspace.
    assigned = await skill_store.get_skill(
        user_id=A, workspace_id=WA, saved_skill_id=receipt.saved_skill_id
    )
    assert assigned is not None
    assert assigned["skill_id"] == row["skill_id"]
    assert assigned["skill_fingerprint"] == _candidate()["skillFingerprint"]
    assert await skill_store.get_skill(
        user_id=B, workspace_id=WB, saved_skill_id=receipt.saved_skill_id
    ) is None

    stored = json.loads(
        source.execute("SELECT skill_json FROM b66_saved_quote_skill").fetchone()[0]
    )
    assert stored["approval"]["status"] == "approved"
    assert stored["approval"]["approvedBy"] == OPERATOR
    assert stored["approval"]["approvalRef"] == GRANT_REF
    assert stored["approval"]["skillFingerprint"] == _candidate()["skillFingerprint"]
    assert stored["fingerprint"] == _candidate()["skillFingerprint"]
    # Candidate-only keys must not survive into the approved Skill.
    assert "status" not in stored
    assert "candidateId" not in stored
    assert "skillFingerprint" not in stored
    assert stored["rendererContract"] == "quote-template-renderer.v1"
    assert stored["calculationAuthority"] == "quote-core"


async def test_reviewer_cannot_redecide_or_reactivate(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)
    first = await reviewer.review(
        grant=_grant(), target=_target(), candidate_id=row["candidate_id"], action="approve", now=NOW,
    )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
            action="approve", now=NOW + timedelta(minutes=5),
        )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
            action="reject", now=NOW + timedelta(minutes=5), rejection_reason="changed my mind",
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 1
    assert source.execute(
        "SELECT saved_skill_id FROM b66_saved_skill_candidate"
    ).fetchone()[0] == first.saved_skill_id

    # A rejected candidate can never be activated by a later approval.
    rejected = await candidate_store.submit(
        user_id=A, workspace_id=WA,
        submission=canonicalize_candidate_submission(
            client_ref="manual-rejected-0008", candidate=_candidate()
        ),
    )
    await reviewer.review(
        grant=_grant(), target=_target(), candidate_id=rejected["candidate_id"],
        action="reject", now=NOW, rejection_reason="회사 정보가 부족합니다",
    )
    detail = await candidate_store.get_candidate(
        user_id=A, workspace_id=WA, candidate_id=rejected["candidate_id"]
    )
    assert detail["status"] == "rejected"
    assert detail["rejection_reason"] == "회사 정보가 부족합니다"
    assert detail["saved_skill_id"] == ""
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(), candidate_id=rejected["candidate_id"],
            action="approve", now=NOW + timedelta(minutes=5),
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 1


async def test_reviewer_refuses_tampered_candidate_bytes(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)

    tampered = json.loads(json.dumps(_candidate()))
    tampered["fixedDefaults"]["sender"]["company"] = "다른회사"
    source.execute(
        "UPDATE b66_saved_skill_candidate SET candidate_json=? WHERE id=?",
        (json.dumps(tampered, ensure_ascii=False, separators=(",", ":"), sort_keys=True), row["candidate_id"]),
    )
    source.commit()

    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
            action="approve", now=NOW,
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0
    still = await candidate_store.get_candidate(
        user_id=A, workspace_id=WA, candidate_id=row["candidate_id"]
    )
    assert still["status"] == "pending"


async def test_reviewer_cross_account_target_is_not_found(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=_grant(), target=_target(user_id=B, workspace_id=WB),
            candidate_id=row["candidate_id"], action="approve", now=NOW,
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0


async def test_reviewer_reject_keeps_existing_customer_state(source):
    candidate_store, skill_store, row = await _pending(source)
    # An unrelated approved Skill already exists for this account.
    existing = await skill_store.put_approved_skill(
        user_id=A, workspace_id=WA,
        artifact=canonicalize_approved_artifact(
            skill_id="saved-quote-existing", skill_name="우리회사 견적서", fingerprint="e" * 64, version=1,
            serialized_json=json.dumps(_approved_payload("e" * 64, "saved-quote-existing"), ensure_ascii=False),
        ),
    )
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)
    receipt = await reviewer.review(
        grant=_grant(), target=_target(), candidate_id=row["candidate_id"],
        action="reject", now=NOW, rejection_reason="필요한 회사 정보가 없습니다",
    )
    assert receipt.action.value == "reject"
    assert receipt.saved_skill_id == ""
    assert receipt.skill_version is None

    # The existing assignment is untouched and no new Skill row appeared.
    rows = source.execute("SELECT id, status FROM b66_saved_quote_skill").fetchall()
    assert [tuple(row) for row in rows] == [(existing["saved_skill_id"], "approved")]
    assert await skill_store.get_skill(
        user_id=A, workspace_id=WA, saved_skill_id=existing["saved_skill_id"]
    ) is not None


async def test_reviewer_requires_expressible_operator_identity(source):
    candidate_store, skill_store, row = await _pending(source)
    reviewer = B66SavedQuoteSkillCandidateReviewer(candidate_store, skill_store)
    weird = TrustedB66ProvisioningGrant(
        grant_ref=GRANT_REF,
        operator_subject=CanonicalSubjectRef(SubjectType.USER, "운영자 이름"),
        authority_ref="authority:b66:ops",
        allowed_actions=(B66ProvisioningAction.REVIEW_CANDIDATE,),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
    )
    with pytest.raises(B66CandidateReviewError):
        await reviewer.review(
            grant=weird, target=_target(), candidate_id=row["candidate_id"],
            action="approve", now=NOW,
        )
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0


def test_migration_declares_candidate_table_and_open_request_index():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS b66_saved_skill_candidate" in sql
    assert "status IN ('pending', 'approved', 'rejected')" in sql
    assert "UNIQUE (user_id, workspace_id, client_ref)" in sql
    assert "candidate_digest" in sql
    assert "WHERE status = 'pending'" in sql


def test_operator_candidate_read_only_routes_authority_and_projection(source):
    """The administrator queue is a B66-global staff view, never a customer view."""
    from unittest.mock import AsyncMock

    candidate_store, skill_store = _stores(source)
    owner_a = _client(candidate_store, skill_store, user=A)
    owner_b = _client(candidate_store, skill_store, user=B)
    body = {"client_ref": _client_ref(), "candidate": _candidate()}
    row_a = owner_a.post("/api/b66/saved-skill-candidates", json=body).json()["candidate"]
    row_b = owner_b.post("/api/b66/saved-skill-candidates", json=body).json()["candidate"]
    assert row_a["candidate_id"] != row_b["candidate_id"]

    # Existing B66 Google administrator authority, backed by the verified
    # server-side subject rather than client-provided email or owner fields.
    admins = MagicMock()
    admins.is_google_admin = AsyncMock(side_effect=lambda user_id: user_id == A)
    owner_a.app.state.b66_member_admin_store = admins
    owner_b.app.state.b66_member_admin_store = admins
    anonymous = _client(candidate_store, skill_store, signed_in=False)
    anonymous.app.state.b66_member_admin_store = admins

    path = "/api/b66/admin/saved-skill-candidates"
    assert anonymous.get(path).status_code == 401
    assert owner_b.get(path).status_code == 403
    assert owner_b.get(path + "/" + row_a["candidate_id"]).status_code == 403

    listed = owner_a.get(path)
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"].startswith("no-store")
    assert listed.json()["status"] == "pending"
    records = listed.json()["candidates"]
    assert {x["candidate_id"] for x in records} == {
        row_a["candidate_id"], row_b["candidate_id"]
    }
    assert {x["user_id"] for x in records} == {A, B}
    safe = {"candidate_id", "user_id", "status", "skill_name",
            "created_at", "updated_at", "decided_at"}
    assert all(set(x) == safe for x in records)
    assert owner_a.get(path + "?status=approved").json()["candidates"] == []
    assert owner_a.get(path + "?status=invalid").status_code == 400
    assert owner_a.get(path + "?limit=0").status_code == 400
    assert owner_a.get(path + "?user_id=" + B).status_code == 400

    detail = owner_a.get(path + "/" + row_b["candidate_id"])
    assert detail.status_code == 200, detail.text
    assert set(detail.json()["candidate"]) == safe
    assert detail.json()["candidate"]["user_id"] == B
    assert owner_a.get(path + "/b66cand_" + "0" * 32).status_code == 404
    assert owner_a.get(path + "/not-a-candidate").status_code == 400

    # No mutation path, no customer self-approval and no new registered Skill.
    assert owner_a.post(path, json={"decision": "approve"}).status_code == 405
    assert owner_a.patch(path + "/" + row_a["candidate_id"],
                         json={"decision": "approve"}).status_code == 405
    assert source.execute("SELECT COUNT(*) FROM b66_saved_quote_skill").fetchone()[0] == 0
    assert source.execute(
        "SELECT COUNT(*) FROM b66_saved_skill_candidate WHERE status='pending'"
    ).fetchone()[0] == 2
