"""Repository-local backend tests — no network, no real DB accounts.

Run:  python -m pytest apps/business-29-apartment-governance/tests -q
"""

import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from app.models import (
    ActionItem,
    AuditEvent,
    Community,
    DisclosureReview,
    Document,
    PublicProjection,
    Redaction,
    RoleAssignment,
    Rule,
    User,
    Version,
)
from app.services import seed_synthetic

from conftest import (
    ADMIN,
    AUDITOR,
    OFFICE,
    REP,
    RESIDENT,
    REVIEWER,
    make_community,
    make_meeting,
    state,
)

WORKSPACE = os.path.join(os.path.dirname(__file__), "..")


def journey_steps(client, *, meeting_id=None):
    """Run the full meeting-to-public-notice flow; return meeting_id."""
    if meeting_id is None:
        cid = make_community(client)
        meeting_id = make_meeting(client, cid)

    def step(method, path, payload, headers=ADMIN):
        r = client.request(method, path, json=payload, headers=headers)
        assert r.status_code == 200, f"{method} {path} -> {r.status_code}: {r.text}"
        return r.json()

    step("POST", f"/api/meetings/{meeting_id}/agendas", {"title": "합성 안건 1", "rule_ref": "rule-1"})
    notice = step("POST", f"/api/meetings/{meeting_id}/notices", {"title": "회의 개최 공고 (합성)", "body": "2026년 3분기 합성 대표회의"}, headers=OFFICE)
    step("PATCH", f"/api/meetings/{meeting_id}/notices/{notice['id']}", {"reviewed": True})
    step("POST", f"/api/meetings/{meeting_id}/notices/{notice['id']}/publish", {"manualConfirm": True, "idempotencyKey": "n1"})
    step("POST", f"/api/meetings/{meeting_id}/attendance", {"mode": "initial", "roster": ["동대표 갑", "동대표 을"], "count": 8}, headers=OFFICE)
    step("POST", f"/api/meetings/{meeting_id}/quorum", {"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"})
    step("POST", f"/api/meetings/{meeting_id}/attendance", {"mode": "supplement", "roster": ["동대표 갑", "동대표 을", "동대표 병"], "count": 11, "reason": "출석 보완 (합성)", "idempotencyKey": "a2"}, headers=OFFICE)
    step("POST", f"/api/meetings/{meeting_id}/quorum", {"attendanceCount": 11, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q2"})
    step("POST", f"/api/meetings/{meeting_id}/discussions", {"text": "공용부 정비 견적 비교 검토 (합성)"})
    step("POST", f"/api/meetings/{meeting_id}/dissent", {"text": "정비 범위가 과해 예산 낭비 우려 (합성)"}, headers=REP)
    step("POST", f"/api/meetings/{meeting_id}/resolutions", {"text": "합성 의결안", "transition": "draft"})
    step("POST", f"/api/meetings/{meeting_id}/resolutions", {"text": "합성 의결안", "transition": "submit"})
    step("POST", f"/api/meetings/{meeting_id}/resolutions", {"text": "합성 의결안", "transition": "approve", "idempotencyKey": "r1"})
    step("POST", f"/api/meetings/{meeting_id}/actions", {"title": "정비 견적 비교자료 취합", "owner": "관리사무소(합성)", "due": "2026-08-05"}, headers=OFFICE)
    step("POST", f"/api/meetings/{meeting_id}/disclosure", {})
    doc = step("POST", f"/api/meetings/{meeting_id}/documents", {"title": "합성 예산 자료", "metadata": {"redactable": True}}, headers=OFFICE)
    step("POST", f"/api/meetings/{meeting_id}/redactions", {"document_id": doc["id"], "redacted_text": "[비공개 내용 마스킹] 예산 총액만 공개 (합성)"}, headers=REVIEWER)
    step("POST", f"/api/meetings/{meeting_id}/disclosure-reviews", {"manualConfirm": True, "packageItems": ["resolution", "dissent"], "idempotencyKey": "d1"}, headers=REVIEWER)
    step("POST", f"/api/meetings/{meeting_id}/publish", {"manualConfirm": True, "idempotencyKey": "p1"})
    step("POST", f"/api/meetings/{meeting_id}/complete", {"idempotencyKey": "c1"})
    return meeting_id


def _first_doc_id(session, meeting_id):
    from app.models import Document
    return session.execute(select(Document).where(Document.meeting_id == uuid.UUID(str(meeting_id)))).scalars().first().id


# ---------------------------------------------------------------------------

def test_schema_creation(tables):
    expected = {
        "communities", "users", "role_assignments", "meetings", "agendas", "rules",
        "notices", "attendance_records", "quorum_records", "discussions", "dissents",
        "resolutions", "action_items", "documents", "redactions", "disclosure_reviews",
        "public_projections", "versions", "audit_events", "idempotency_records",
    }
    assert expected.issubset(tables)


def test_migration_upgrade_downgrade(tmp_path):
    db_file = tmp_path / "migrate.db"
    os.environ["B29_DATABASE_URL"] = f"sqlite:///{db_file}"
    cfg = Config(os.path.join(WORKSPACE, "alembic.ini"))
    try:
        command.upgrade(cfg, "head")
        from sqlalchemy import create_engine
        eng = create_engine(f"sqlite:///{db_file}")
        names = set(inspect(eng).get_table_names())
        assert "meetings" in names and "public_projections" in names and "idempotency_records" in names
        eng.dispose()
        command.downgrade(cfg, "base")
        eng = create_engine(f"sqlite:///{db_file}")
        names = set(inspect(eng).get_table_names())
        assert "meetings" not in names, "downgrade should drop schema"
        eng.dispose()
    finally:
        os.environ.pop("B29_DATABASE_URL", None)


def test_synthetic_seed(session):
    community = seed_synthetic(session)
    session.commit()
    assert community.households == 420
    assert session.execute(select(User).where(User.community_id == community.id)).scalars().all()
    assert len(list(session.execute(select(RoleAssignment).where(RoleAssignment.community_id == community.id)).scalars())) == 6
    assert session.execute(select(Rule).where(Rule.community_id == community.id)).scalars().first()


def test_role_matrix(client):
    # 감사/일반 주민 cannot create communities or meetings
    assert client.post("/api/communities", json={"name": "x", "households": 1}, headers=AUDITOR).status_code == 403
    assert client.post("/api/communities", json={"name": "x", "households": 1}, headers=RESIDENT).status_code == 403
    cid = make_community(client)
    assert client.post("/api/meetings", json={"community_id": cid, "title": "t"}, headers=RESIDENT).status_code == 403
    # 주민 cannot read internal meeting detail
    mid = make_meeting(client, cid)
    assert client.get(f"/api/meetings/{mid}", headers=RESIDENT).status_code == 403
    # 감사 can read
    assert client.get(f"/api/meetings/{mid}", headers=AUDITOR).status_code == 200


def test_normal_meeting_journey(client):
    meeting_id = journey_steps(client)
    assert state(client, meeting_id) == "completed"
    pub = client.get(f"/api/public/meetings/{meeting_id}").json()
    assert len(pub) >= 3, "published projections present"


def test_quorum_incomplete_block(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    r = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    assert r.status_code == 200
    assert state(client, mid) == "quorum_incomplete"
    assert client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN).status_code == 422
    assert client.post(f"/api/meetings/{mid}/resolutions", json={"text": "x", "transition": "draft"}, headers=ADMIN).status_code == 422


def test_attendance_supplement_and_recheck(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    assert state(client, mid) == "quorum_incomplete"
    r = client.post(f"/api/meetings/{mid}/attendance", json={"mode": "supplement", "roster": ["a", "b", "c"], "count": 11, "idempotencyKey": "a2"}, headers=OFFICE)
    assert r.status_code == 200 and r.json()["revision"] == 2 and r.json()["mode"] == "supplement"
    assert state(client, mid) == "attendance_open"
    r = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 11, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q2"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["quorum_met"] is True
    assert state(client, mid) == "quorum_recorded"


def test_direct_quorum_bypass_rejected(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    assert state(client, mid) == "quorum_incomplete"
    r = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 11, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q9"}, headers=ADMIN)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "QUORUM_RECHECK_REQUIRED"
    assert state(client, mid) == "quorum_incomplete", "direct quorum-incomplete→recorded must be rejected"


def test_notice_gate1(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    # publish before review → INVALID_STATE_TRANSITION (Gate 1 requires review first)
    r = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n0"}, headers=ADMIN)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    # office cannot review (only 관리자)
    r = client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=OFFICE)
    assert r.status_code == 403
    r = client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    assert r.status_code == 200
    # publish without manualConfirm → blocked
    r = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": False, "idempotencyKey": "n1"}, headers=ADMIN)
    assert r.status_code == 400
    # office cannot publish (only 관리자)
    r = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n2"}, headers=OFFICE)
    assert r.status_code == 403
    r = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n3"}, headers=ADMIN)
    assert r.status_code == 200
    assert state(client, mid) == "notice_published"
    pub = client.get(f"/api/public/meetings/{mid}").json()
    assert any(p["source_object_id"] == "meeting-notice" for p in pub), "meeting-notice projection public after Gate 1"


def test_discussion_blocked_before_quorum(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    assert state(client, mid) == "quorum_incomplete"
    r = client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_dissent_retention(client):
    meeting_id = journey_steps(client)
    r = client.get(f"/api/meetings/{meeting_id}/audit-events", headers=AUDITOR)
    assert r.status_code == 200
    events = r.json()
    assert any(e["action"] == "dissent" for e in events)
    pub = client.get(f"/api/public/meetings/{meeting_id}").json()
    assert any(p["source_object_id"] == "dissent" for p in pub), "dissent retained in final projections"


def test_resolution_approval(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    r = client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "draft"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert state(client, mid) == "resolution_draft"
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "submit"}, headers=ADMIN)
    assert state(client, mid) == "resolution_review"
    r = client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert state(client, mid) == "resolution_approved"


def test_redaction_not_equal_approval(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "draft"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "submit"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/actions", json={"title": "act", "owner": "사무소(합성)"}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/disclosure", headers=ADMIN)
    client.post(f"/api/meetings/{mid}/documents", json={"title": "합성 예산 자료", "metadata": {"redactable": True}}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/redactions", json={"document_id": str(_first_doc_id(session, mid)), "redacted_text": "[마스킹] 합성"}, headers=REVIEWER)
    # redaction alone must NOT approve disclosure — no approved projections, still disclosure_review
    approved = session.execute(select(PublicProjection).where(PublicProjection.status == "approved")).scalars().all()
    assert len(approved) == 0, "redaction is not approval"
    assert state(client, mid) == "disclosure_review"


def test_external_reviewer_disclosure_gate(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "draft"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "submit"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "합성 의결안", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/actions", json={"title": "act", "owner": "사무소(합성)"}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/disclosure", headers=ADMIN)
    client.post(f"/api/meetings/{mid}/documents", json={"title": "합성 예산 자료", "metadata": {"redactable": True}}, headers=OFFICE)
    # disclosure approval before redaction → 409 REDACTION_INCOMPLETE, state → redaction_required
    r = client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution", "dissent"], "idempotencyKey": "d1"}, headers=REVIEWER)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "REDACTION_INCOMPLETE"
    assert state(client, mid) == "redaction_required"
    # wrong role (관리자) cannot approve disclosure even with redaction done
    client.post(f"/api/meetings/{mid}/redactions", json={"document_id": str(_first_doc_id(session, mid)), "redacted_text": "[마스킹] 합성"}, headers=REVIEWER)
    r = client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution", "dissent"], "idempotencyKey": "d2"}, headers=ADMIN)
    assert r.status_code == 403
    # reviewer approves
    r = client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution", "dissent"], "idempotencyKey": "d3"}, headers=REVIEWER)
    assert r.status_code == 200
    assert state(client, mid) == "public_notice_ready"


def test_administrator_publication_gate(client):
    meeting_id = journey_steps(client)
    assert state(client, meeting_id) == "completed"


def test_administrator_publication_gate_blocked(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "draft"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "submit"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/actions", json={"title": "act"}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/disclosure", headers=ADMIN)
    client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution"], "idempotencyKey": "d1"}, headers=REVIEWER)
    assert state(client, mid) == "public_notice_ready"
    # reviewer cannot publish
    r = client.post(f"/api/meetings/{mid}/publish", json={"manualConfirm": True, "idempotencyKey": "p1"}, headers=REVIEWER)
    assert r.status_code == 403
    # publish without manualConfirm → blocked
    r = client.post(f"/api/meetings/{mid}/publish", json={"manualConfirm": False, "idempotencyKey": "p2"}, headers=ADMIN)
    assert r.status_code == 400
    # admin publishes
    r = client.post(f"/api/meetings/{mid}/publish", json={"manualConfirm": True, "idempotencyKey": "p3"}, headers=ADMIN)
    assert r.status_code == 200
    assert state(client, mid) == "public_notice_published"


def test_missing_provenance_publish_block(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "draft"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "submit"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/actions", json={"title": "act"}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/disclosure", headers=ADMIN)
    client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution"], "idempotencyKey": "d1"}, headers=REVIEWER)
    # corrupt provenance directly
    proj = session.execute(select(PublicProjection).where(PublicProjection.status == "approved")).scalars().first()
    proj.reviewed_version = None
    session.commit()
    r = client.post(f"/api/meetings/{mid}/publish", json={"manualConfirm": True, "idempotencyKey": "p1"}, headers=ADMIN)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROJECTION_PROVENANCE_MISSING"
    assert state(client, mid) == "public_notice_ready"


def test_public_endpoint_leakage_zero(client):
    meeting_id = journey_steps(client)
    pub = client.get(f"/api/public/meetings/{meeting_id}").json()
    blob = str(pub)
    assert "동대표 갑" not in blob, "roster leaked"
    assert "정비 견적 비교 검토" not in blob, "raw discussion leaked"
    assert "비공개 내용" not in blob, "unredacted content leaked"
    assert "사무소(합성)" not in blob or "owner" not in blob, "action owner leaked"
    assert "회장(합성)" not in blob, "audit actor leaked"
    assert "role" not in blob, "internal role leaked"
    assert all(p["status"] == "published" for p in pub), "unpublished projections leaked"


def test_idempotent_retry(client, session):
    meeting_id = journey_steps(client)
    # re-run a mutation with the same key + same request → replay, no new events
    before_v = len(list(session.execute(select(Version)).scalars()))
    before_a = len(list(session.execute(select(AuditEvent)).scalars()))
    notice = client.get(f"/api/meetings/{meeting_id}", headers=ADMIN)
    assert notice.status_code == 200
    # replay the final publish
    r = client.post(f"/api/meetings/{meeting_id}/publish", json={"manualConfirm": True, "idempotencyKey": "p1"}, headers=ADMIN)
    assert r.status_code == 200
    after_v = len(list(session.execute(select(Version)).scalars()))
    after_a = len(list(session.execute(select(AuditEvent)).scalars()))
    assert after_v == before_v, "no new Version on idempotent replay"
    assert after_a == before_a, "no new AuditEvent on idempotent replay"
    projs = session.execute(select(PublicProjection).where(PublicProjection.status == "published")).scalars().all()
    # no duplicate projections
    keys = [(p.meeting_id, p.source_object_id, p.projection_type, p.reviewed_version) for p in projs]
    assert len(keys) == len(set(keys)), "duplicate projection on retry"


def test_idempotency_conflict(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    r1 = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "k1"}, headers=ADMIN)
    assert r1.status_code == 200
    r2 = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "k1"}, headers=ADMIN)
    assert r2.status_code == 200  # replay (same request)
    r3 = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 5, "threshold": 10, "manualConfirm": True, "idempotencyKey": "k2"}, headers=ADMIN)
    # different request with a key already used? use publish key k1 with different payload
    r4 = client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "k1"}, headers=ADMIN)
    assert r4.status_code == 200


def test_idempotency_conflict_different_request(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    r1 = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 8, "threshold": 10, "manualConfirm": True, "idempotencyKey": "k1"}, headers=ADMIN)
    assert r1.status_code == 200
    # same key, different request content → 409 IDEMPOTENCY_CONFLICT
    r2 = client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 11, "threshold": 10, "manualConfirm": True, "idempotencyKey": "k1"}, headers=ADMIN)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_transaction_rollback(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 8}, headers=OFFICE)
    before_state = state(client, mid)
    before_v = len(list(session.execute(select(Version)).scalars()))
    before_a = len(list(session.execute(select(AuditEvent)).scalars()))
    # blocked mutation (discussion before quorum) must persist nothing
    r = client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    assert r.status_code == 422
    after_v = len(list(session.execute(select(Version)).scalars()))
    after_a = len(list(session.execute(select(AuditEvent)).scalars()))
    assert after_v == before_v, "blocked mutation wrote a Version"
    assert after_a == before_a, "blocked mutation wrote an AuditEvent"
    assert state(client, mid) == before_state, "state unchanged after rollback"


def test_version_audit_exactly_once(client, session):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    client.post(f"/api/meetings/{mid}/agendas", json={"title": "a"}, headers=ADMIN)
    notice = client.post(f"/api/meetings/{mid}/notices", json={"title": "n", "body": "b"}, headers=OFFICE).json()
    client.patch(f"/api/meetings/{mid}/notices/{notice['id']}", json={"reviewed": True}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/notices/{notice['id']}/publish", json={"manualConfirm": True, "idempotencyKey": "n1"}, headers=ADMIN)
    versions = list(session.execute(select(Version)).scalars())
    events = list(session.execute(select(AuditEvent)).scalars())
    assert len(versions) == len(events), "one Version per AuditEvent"
    # disclosure approval creates N projections but exactly 1 Version + 1 AuditEvent
    client.post(f"/api/meetings/{mid}/attendance", json={"roster": ["a"], "count": 10}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/quorum", json={"attendanceCount": 10, "threshold": 10, "manualConfirm": True, "idempotencyKey": "q1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/discussions", json={"text": "x"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "draft"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "submit"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/resolutions", json={"text": "r", "transition": "approve", "idempotencyKey": "r1"}, headers=ADMIN)
    client.post(f"/api/meetings/{mid}/actions", json={"title": "act"}, headers=OFFICE)
    client.post(f"/api/meetings/{mid}/disclosure", headers=ADMIN)
    before_v = len(list(session.execute(select(Version)).scalars()))
    r = client.post(f"/api/meetings/{mid}/disclosure-reviews", json={"manualConfirm": True, "packageItems": ["resolution", "dissent", "agenda-a"], "idempotencyKey": "d1"}, headers=REVIEWER)
    assert r.status_code == 200
    after_v = len(list(session.execute(select(Version)).scalars()))
    after_a = len(list(session.execute(select(AuditEvent)).scalars()))
    assert after_v - before_v == 1, "disclosure approval adds exactly 1 Version"
    assert after_a - before_v == 1, "disclosure approval adds exactly 1 AuditEvent"
    new_projs = session.execute(select(PublicProjection).where(PublicProjection.status == "approved")).scalars().all()
    assert len(new_projs) == 3, "N projections created"


def test_audit_immutable(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for p in paths:
        if p.endswith("/audit-events"):
            for method in ("patch", "delete", "put"):
                assert method not in paths[p], f"audit event {method} endpoint must not exist"
    # also no update/delete for versions
    for p in paths:
        if p.endswith("/versions") or "audit" in p:
            for method in ("patch", "delete", "put"):
                assert method not in paths[p], f"immutable resource {method} endpoint must not exist"


def test_binary_document_rejection(client):
    cid = make_community(client)
    mid = make_meeting(client, cid)
    r = client.post(
        f"/api/meetings/{mid}/documents",
        files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=ADMIN,
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "BINARY_UPLOAD_NOT_ALLOWED"


def test_openapi_generation(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "/api/meetings/{meeting_id}/publish" in schema["paths"]
    assert "/api/meetings/{meeting_id}/notices/{notice_id}/publish" in schema["paths"]
    assert "/api/meetings/{meeting_id}/discussions" in schema["paths"]
    assert "/api/public/meetings/{meeting_id}" in schema["paths"]
    desc = schema.get("info", {}).get("description", "")
    assert "SYNTHETIC DEVELOPMENT AUTHORITY ONLY" in desc
    assert "MUST NOT BE ENABLED IN PRODUCTION" in desc
