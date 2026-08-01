"""Business logic services.

Every domain mutation runs inside one session/transaction and writes exactly:
  domain mutation 1 + Version 1 + AuditEvent 1.
Idempotent mutations store/check IdempotencyRecord; a replay returns the stored
response and never creates new Version/AuditEvent/projections.
"""

import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import DomainError, next_state, require_role
from .models import (
    ActionItem,
    Agenda,
    AttendanceRecord,
    AuditEvent,
    Community,
    DisclosureReview,
    Dissent,
    Discussion,
    Document,
    IdempotencyRecord,
    Meeting,
    Notice,
    PublicProjection,
    QuorumRecord,
    Redaction,
    Resolution,
    RoleAssignment,
    Rule,
    User,
    Version,
    utcnow,
)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def idempotency_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def idempotency_check(db: Session, actor, endpoint: str, key: str, payload: dict):
    """Return a replay response dict if an identical request was already stored;
    raise IDEMPOTENCY_CONFLICT if the same key was used with a different request."""
    if not key:
        raise DomainError("VALIDATION", "idempotencyKey is required for this mutation.")
    rec = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor.actor,
            IdempotencyRecord.endpoint == endpoint,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()
    if rec is None:
        return None
    if rec.request_hash == idempotency_hash(payload):
        return rec.response_snapshot
    raise DomainError(
        "IDEMPOTENCY_CONFLICT",
        "Same idempotency key was used with a different request.",
    )


def idempotency_store(
    db: Session, actor, endpoint: str, key: str, payload: dict, response: dict
) -> None:
    db.add(
        IdempotencyRecord(
            key=key,
            actor_id=actor.actor,
            endpoint=endpoint,
            request_hash=idempotency_hash(payload),
            response_snapshot=response,
            created_at=utcnow(),
        )
    )


def record_audit(
    db: Session,
    meeting: Meeting,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: str,
    actor,
    from_state: str,
    to_state: str,
) -> None:
    max_seq = db.execute(
        select(func.max(AuditEvent.sequence)).where(AuditEvent.meeting_id == meeting.id)
    ).scalar()
    seq = (max_seq if max_seq is not None else 0) + 1
    db.add(
        AuditEvent(
            meeting_id=meeting.id,
            version=seq,
            from_state=from_state,
            to_state=to_state,
            action=action,
            actor_id=actor.actor,
            role=actor.role,
            sequence=seq,
            created_at=utcnow(),
        )
    )
    db.add(
        Version(
            meeting_id=meeting.id,
            entity_type=entity_type,
            entity_id=entity_id,
            version=seq,
            action=action,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor.actor,
            role=actor.role,
            sequence=seq,
            created_at=utcnow(),
        )
    )


def _transition_meeting(db: Session, meeting: Meeting, action: str, actor, *, decided=None, entity_type="meeting") -> str:
    from_state = meeting.state
    to_state = next_state(from_state, action, decided=decided)
    meeting.state = to_state
    record_audit(
        db, meeting, entity_type=entity_type, entity_id=meeting.id, action=action, actor=actor,
        from_state=from_state, to_state=to_state,
    )
    return to_state


def _get_meeting(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.execute(select(Meeting).where(Meeting.id == meeting_id)).scalar_one_or_none()
    if meeting is None:
        raise DomainError("NOT_FOUND", "Meeting not found.")
    return meeting


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def create_community(db: Session, actor, payload) -> Community:
    require_role(actor.role, "community_create")
    community = Community(
        name=payload.name, name_en=payload.name_en, households=payload.households,
        synthetic=payload.synthetic,
    )
    db.add(community)
    return community


def create_meeting(db: Session, actor, payload) -> Meeting:
    require_role(actor.role, "meeting_create")
    community = db.execute(select(Community).where(Community.id == payload.community_id)).scalar_one_or_none()
    if community is None:
        raise DomainError("NOT_FOUND", "Community not found.")
    meeting = Meeting(community_id=community.id, title=payload.title, quarter=payload.quarter, state="draft")
    db.add(meeting)
    db.flush()
    record_audit(
        db, meeting, entity_type="meeting", entity_id=meeting.id, action="meeting.created",
        actor=actor, from_state="none", to_state="draft",
    )
    return meeting


def get_meeting(db: Session, meeting_id: uuid.UUID, actor):
    require_role(actor.role, "meeting_get")
    meeting = _get_meeting(db, meeting_id)
    versions = list(db.execute(select(Version).where(Version.meeting_id == meeting.id).order_by(Version.sequence)).scalars())
    return meeting, versions


# ---------------------------------------------------------------------------
# agenda
# ---------------------------------------------------------------------------

def create_agenda(db: Session, meeting_id: uuid.UUID, actor, payload) -> Agenda:
    require_role(actor.role, "agenda_create")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "agenda", actor, entity_type="agenda")
    agenda = Agenda(meeting_id=meeting.id, title=payload.title, rule_ref=payload.rule_ref)
    db.add(agenda)
    return agenda


# ---------------------------------------------------------------------------
# notice (Gate 1)
# ---------------------------------------------------------------------------

def create_notice(db: Session, meeting_id: uuid.UUID, actor, payload) -> Notice:
    require_role(actor.role, "notice_create")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "notice_create", actor, entity_type="notice")
    notice = Notice(
        meeting_id=meeting.id, title=payload.title, body=payload.body,
        notice_type=payload.notice_type, status="draft",
    )
    db.add(notice)
    return notice


def update_notice(db: Session, meeting_id: uuid.UUID, notice_id: uuid.UUID, actor, payload) -> Notice:
    require_role(actor.role, "notice_update")
    meeting = _get_meeting(db, meeting_id)
    notice = db.execute(select(Notice).where(Notice.id == notice_id, Notice.meeting_id == meeting.id)).scalar_one_or_none()
    if notice is None:
        raise DomainError("NOT_FOUND", "Notice not found.")
    if notice.status == "published":
        raise DomainError("INVALID_STATE_TRANSITION", "Published notice cannot be modified.", current_state=meeting.state)
    if payload.title is not None:
        notice.title = payload.title
    if payload.body is not None:
        notice.body = payload.body
    if payload.reviewed:
        _transition_meeting(db, meeting, "notice_review", actor, entity_type="notice")
        notice.status = "reviewed"
        notice.reviewed_by = actor.actor
        notice.reviewed_version = _next_sequence(db, meeting)
    return notice


def publish_notice(db: Session, meeting_id: uuid.UUID, notice_id: uuid.UUID, actor, payload) -> Notice:
    require_role(actor.role, "notice_publish")
    if not payload.manualConfirm:
        raise DomainError("VALIDATION", "manualConfirm=true is required to publish the notice.")
    meeting = _get_meeting(db, meeting_id)
    notice = db.execute(select(Notice).where(Notice.id == notice_id, Notice.meeting_id == meeting.id)).scalar_one_or_none()
    if notice is None:
        raise DomainError("NOT_FOUND", "Notice not found.")
    endpoint = "notice_publish"
    replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
    if replay is not None:
        return notice, replay, True
    if notice.status == "published":
        raise DomainError("INVALID_STATE_TRANSITION", "Notice already published.", current_state=meeting.state)
    _transition_meeting(db, meeting, "notice_publish", actor, entity_type="notice")
    seq = _next_sequence(db, meeting)
    notice.status = "published"
    notice.published_by = actor.actor
    notice.published_version = seq
    projection = PublicProjection(
        meeting_id=meeting.id,
        source_object_id="meeting-notice",
        projection_type="notice",
        title=notice.title,
        summary=notice.body,
        disclosure_state="public",
        status="published",
        reviewed_by=actor.actor,
        reviewed_version=seq,
        published_by=actor.actor,
        published_version=seq,
    )
    db.add(projection)
    response = NoticeOut_model(notice)
    idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
    return notice, response, False


def _next_sequence(db: Session, meeting: Meeting) -> int:
    max_seq = db.execute(
        select(func.max(AuditEvent.sequence)).where(AuditEvent.meeting_id == meeting.id)
    ).scalar()
    return (max_seq if max_seq is not None else 0) + 1


def NoticeOut_model(notice: Notice) -> dict:
    return {
        "id": str(notice.id),
        "meeting_id": str(notice.meeting_id),
        "title": notice.title,
        "body": notice.body,
        "notice_type": notice.notice_type,
        "status": notice.status,
        "reviewed_by": notice.reviewed_by,
        "reviewed_version": notice.reviewed_version,
        "published_by": notice.published_by,
        "published_version": notice.published_version,
    }


# ---------------------------------------------------------------------------
# attendance + quorum
# ---------------------------------------------------------------------------

def record_attendance(db: Session, meeting_id: uuid.UUID, actor, payload) -> AttendanceRecord:
    require_role(actor.role, "attendance")
    meeting = _get_meeting(db, meeting_id)
    mode = payload.mode
    if mode == "supplement":
        endpoint = "attendance_supplement"
        replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
        if replay is not None:
            return _latest_attendance(db, meeting), replay, True
        if meeting.state != "quorum_incomplete":
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                "Attendance supplement is only allowed from quorum-incomplete.",
                current_state=meeting.state,
            )
        revision = _next_attendance_revision(db, meeting)
        _transition_meeting(db, meeting, "attendance_supplement", actor, entity_type="attendance")
        rec = AttendanceRecord(
            meeting_id=meeting.id, revision=revision, mode="supplement",
            roster=payload.roster, count=payload.count, reason=payload.reason,
            recorded_by=actor.actor,
        )
        db.add(rec)
        response = AttendanceOut_model(rec)
        idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
        return rec, response, False
    # initial
    if meeting.state not in ("notice_published", "attendance_open"):
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            "Attendance can only be recorded after notice publication.",
            current_state=meeting.state,
        )
    _transition_meeting(db, meeting, "attendance", actor, entity_type="attendance")
    revision = _next_attendance_revision(db, meeting)
    rec = AttendanceRecord(
        meeting_id=meeting.id, revision=revision, mode="initial",
        roster=payload.roster, count=payload.count, reason=payload.reason,
        recorded_by=actor.actor,
    )
    db.add(rec)
    return rec, AttendanceOut_model(rec), False


def _latest_attendance(db: Session, meeting: Meeting) -> AttendanceRecord:
    return db.execute(
        select(AttendanceRecord).where(AttendanceRecord.meeting_id == meeting.id)
        .order_by(AttendanceRecord.revision.desc()).limit(1)
    ).scalars().first()


def _next_attendance_revision(db: Session, meeting: Meeting) -> int:
    latest = _latest_attendance(db, meeting)
    return (latest.revision + 1) if latest else 1


def AttendanceOut_model(rec: AttendanceRecord) -> dict:
    return {
        "id": str(rec.id),
        "meeting_id": str(rec.meeting_id),
        "revision": rec.revision,
        "mode": rec.mode,
        "count": rec.count,
        "reason": rec.reason,
    }


def record_quorum(db: Session, meeting_id: uuid.UUID, actor, payload) -> QuorumRecord:
    require_role(actor.role, "quorum")
    if not payload.manualConfirm:
        raise DomainError("VALIDATION", "manualConfirm=true is required to record quorum.")
    meeting = _get_meeting(db, meeting_id)
    endpoint = "quorum_record"
    replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
    if replay is not None:
        return _latest_quorum(db, meeting), replay, True
    if meeting.state == "quorum_incomplete":
        raise DomainError(
            "QUORUM_RECHECK_REQUIRED",
            "Attendance supplement and manual recheck are required.",
            current_state=meeting.state,
        )
    if meeting.state != "attendance_open":
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            "Quorum can only be recorded from attendance-open.",
            current_state=meeting.state,
        )
    quorum_met = payload.attendanceCount >= payload.threshold
    decided = "quorum_recorded" if quorum_met else "quorum_incomplete"
    _transition_meeting(db, meeting, "quorum", actor, decided=decided, entity_type="quorum")
    rec = QuorumRecord(
        meeting_id=meeting.id, attendance_count=payload.attendanceCount,
        threshold=payload.threshold, manual_confirm=True, quorum_met=quorum_met,
        recorded_by=actor.actor,
    )
    db.add(rec)
    response = QuorumOut_model(rec)
    idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
    return rec, response, False


def _latest_quorum(db: Session, meeting: Meeting) -> QuorumRecord:
    return db.execute(
        select(QuorumRecord).where(QuorumRecord.meeting_id == meeting.id)
        .order_by(QuorumRecord.created_at.desc()).limit(1)
    ).scalars().first()


def QuorumOut_model(rec: QuorumRecord) -> dict:
    return {
        "id": str(rec.id),
        "meeting_id": str(rec.meeting_id),
        "attendance_count": rec.attendance_count,
        "threshold": rec.threshold,
        "quorum_met": rec.quorum_met,
    }


# ---------------------------------------------------------------------------
# discussion / dissent
# ---------------------------------------------------------------------------

def create_discussion(db: Session, meeting_id: uuid.UUID, actor, payload) -> Discussion:
    require_role(actor.role, "discussion_create")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "discussion", actor, entity_type="discussion")
    disc = Discussion(meeting_id=meeting.id, agenda_id=payload.agenda_id, text=payload.text)
    db.add(disc)
    return disc


def update_discussion(db: Session, meeting_id: uuid.UUID, discussion_id: uuid.UUID, actor, payload) -> Discussion:
    require_role(actor.role, "discussion_update")
    meeting = _get_meeting(db, meeting_id)
    disc = db.execute(select(Discussion).where(Discussion.id == discussion_id, Discussion.meeting_id == meeting.id)).scalar_one_or_none()
    if disc is None:
        raise DomainError("NOT_FOUND", "Discussion not found.")
    _transition_meeting(db, meeting, "discussion", actor, entity_type="discussion")
    if payload.summary is not None:
        disc.summary = payload.summary
    return disc


def record_dissent(db: Session, meeting_id: uuid.UUID, actor, payload) -> Dissent:
    require_role(actor.role, "dissent")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "dissent", actor, entity_type="dissent")
    dissent = Dissent(
        meeting_id=meeting.id, agenda_id=payload.agenda_id, member=actor.actor,
        text=payload.text, retained=True,
    )
    db.add(dissent)
    return dissent


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------

def create_resolution(db: Session, meeting_id: uuid.UUID, actor, payload) -> Resolution:
    require_role(actor.role, "resolution")
    meeting = _get_meeting(db, meeting_id)
    transition = payload.transition
    if transition == "approve":
        if not payload.idempotencyKey:
            raise DomainError("VALIDATION", "idempotencyKey is required for resolution approval.")
        endpoint = "resolution_approve"
        replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
        if replay is not None:
            return _latest_resolution(db, meeting), replay, True
    else:
        replay = None
    if transition == "draft":
        _transition_meeting(db, meeting, "resolution", actor, entity_type="resolution")
        resolution = Resolution(meeting_id=meeting.id, text=payload.text, status="draft")
        db.add(resolution)
        return resolution, ResolutionOut_model(resolution), False
    if transition == "submit":
        _transition_meeting(db, meeting, "resolution_submit", actor, entity_type="resolution")
        resolution = _latest_resolution(db, meeting)
        resolution.status = "review"
        return resolution, ResolutionOut_model(resolution), False
    if transition == "approve":
        _transition_meeting(db, meeting, "resolution_approve", actor, entity_type="resolution")
        resolution = _latest_resolution(db, meeting)
        resolution.status = "approved"
        response = ResolutionOut_model(resolution)
        idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
        return resolution, response, False
    raise DomainError("VALIDATION", "Unknown resolution transition.")


def _latest_resolution(db: Session, meeting: Meeting) -> Resolution:
    return db.execute(
        select(Resolution).where(Resolution.meeting_id == meeting.id)
        .order_by(Resolution.created_at.desc()).limit(1)
    ).scalars().first()


def ResolutionOut_model(res: Resolution) -> dict:
    return {
        "id": str(res.id),
        "meeting_id": str(res.meeting_id),
        "text": res.text,
        "status": res.status,
        "dissent_ref": res.dissent_ref,
    }


# ---------------------------------------------------------------------------
# action / document
# ---------------------------------------------------------------------------

def create_action(db: Session, meeting_id: uuid.UUID, actor, payload) -> ActionItem:
    require_role(actor.role, "action")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "action", actor, entity_type="action")
    item = ActionItem(
        meeting_id=meeting.id, title=payload.title, owner=payload.owner,
        due=payload.due, overdue=False,
    )
    db.add(item)
    return item


def create_document(db: Session, meeting_id: uuid.UUID, actor, payload) -> Document:
    require_role(actor.role, "document")
    meeting = _get_meeting(db, meeting_id)
    if meeting.state in ("public_notice_published", "completed", "cancelled"):
        raise DomainError("INVALID_STATE_TRANSITION", "Documents cannot be added after publication.", current_state=meeting.state)
    doc = Document(meeting_id=meeting.id, title=payload.title, metadata_json=payload.metadata or {})
    db.add(doc)
    return doc


def open_disclosure(db: Session, meeting_id: uuid.UUID, actor) -> Meeting:
    """Open the disclosure review (action_pending → disclosure_review)."""
    require_role(actor.role, "disclosure")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "disclosure", actor, entity_type="meeting")
    return meeting


# ---------------------------------------------------------------------------
# redaction / disclosure / publish
# ---------------------------------------------------------------------------

def _redactions_complete(db: Session, meeting: Meeting) -> bool:
    docs = list(db.execute(select(Document).where(Document.meeting_id == meeting.id)).scalars())
    if not docs:
        return True
    redacted_ids = set(
        db.execute(select(Redaction.document_id).where(Redaction.meeting_id == meeting.id)).scalars()
    )
    for doc in docs:
        meta = doc.metadata_json or {}
        if meta.get("redactable") and doc.id not in redacted_ids:
            return False
    return True


def create_redaction(db: Session, meeting_id: uuid.UUID, actor, payload) -> Redaction:
    require_role(actor.role, "redaction")
    meeting = _get_meeting(db, meeting_id)
    if meeting.state not in ("disclosure_review", "redaction_required"):
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            "Redaction is only allowed during disclosure review.",
            current_state=meeting.state,
        )
    doc = db.execute(select(Document).where(Document.id == payload.document_id, Document.meeting_id == meeting.id)).scalar_one_or_none()
    if doc is None:
        raise DomainError("NOT_FOUND", "Document not found.")
    redaction = Redaction(
        meeting_id=meeting.id, document_id=doc.id, redacted_text=payload.redacted_text,
        confirmed_by=actor.actor,
    )
    db.add(redaction)
    # redaction은 승인이 아니다 — 검토(disclosure-review)로 복귀
    _transition_meeting(db, meeting, "redaction", actor, entity_type="redaction")
    return redaction


def approve_disclosure(db: Session, meeting_id: uuid.UUID, actor, payload) -> DisclosureReview:
    require_role(actor.role, "disclosure_approve")
    if not payload.manualConfirm:
        raise DomainError("VALIDATION", "manualConfirm=true is required to approve disclosure.")
    meeting = _get_meeting(db, meeting_id)
    endpoint = "disclosure_approve"
    replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
    if replay is not None:
        return _latest_disclosure_review(db, meeting), replay, True
    if meeting.state != "disclosure_review":
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            "Disclosure approval is only allowed from disclosure-review.",
            current_state=meeting.state,
        )
    if not _redactions_complete(db, meeting):
        from_state = meeting.state
        meeting.state = "redaction_required"
        record_audit(
            db, meeting, entity_type="meeting", entity_id=meeting.id,
            action="disclosure_review_blocked", actor=actor,
            from_state=from_state, to_state="redaction_required",
        )
        raise DomainError(
            "REDACTION_INCOMPLETE",
            "All required redactions must be completed before disclosure approval.",
            current_state="redaction_required",
        )
    seq = _next_sequence(db, meeting)
    _transition_meeting(db, meeting, "disclosure_approve", actor, entity_type="disclosure_review")
    review = DisclosureReview(
        meeting_id=meeting.id, manual_confirm=True,
        package_items=payload.packageItems or [], reviewed_by=actor.actor,
        reviewed_version=seq,
    )
    db.add(review)
    # approved projections (bulk) — one Version + one AuditEvent only
    for item in (payload.packageItems or []):
        db.add(
            PublicProjection(
                meeting_id=meeting.id,
                source_object_id=item,
                projection_type="package",
                title=_projection_title(db, meeting, item),
                summary=_projection_summary(db, meeting, item),
                disclosure_state="public",
                status="approved",
                reviewed_by=actor.actor,
                reviewed_version=seq,
            )
        )
    response = DisclosureReviewOut_model(review, len(payload.packageItems or []))
    idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
    return review, response, False


def _latest_disclosure_review(db: Session, meeting: Meeting) -> DisclosureReview:
    return db.execute(
        select(DisclosureReview).where(DisclosureReview.meeting_id == meeting.id)
        .order_by(DisclosureReview.created_at.desc()).limit(1)
    ).scalars().first()


def _projection_title(db: Session, meeting: Meeting, item: str) -> str:
    if item == "resolution":
        res = _latest_resolution(db, meeting)
        return "의결 결과"
    if item.startswith("agenda-"):
        return "안건"
    if item.startswith("doc-"):
        doc = db.execute(select(Document).where(Document.id == uuid.UUID(item[4:]))).scalar_one_or_none()
        return doc.title if doc else item
    return item


def _projection_summary(db: Session, meeting: Meeting, item: str) -> str:
    if item == "resolution":
        res = _latest_resolution(db, meeting)
        return res.text if res else ""
    if item.startswith("doc-"):
        red = db.execute(
            select(Redaction).where(Redaction.document_id == uuid.UUID(item[4:]))
        ).scalars().first()
        return red.redacted_text if red else "(redacted)"
    if item == "dissent":
        dissent = db.execute(select(Dissent).where(Dissent.meeting_id == meeting.id)).scalars().first()
        return dissent.text if dissent else "이견"
    return item


def DisclosureReviewOut_model(review: DisclosureReview, projection_count: int) -> dict:
    return {
        "id": str(review.id),
        "meeting_id": str(review.meeting_id),
        "manual_confirm": review.manual_confirm,
        "package_items": review.package_items,
        "reviewed_by": review.reviewed_by,
        "reviewed_version": review.reviewed_version,
        "projection_count": projection_count,
    }


def publish_final(db: Session, meeting_id: uuid.UUID, actor, payload):
    require_role(actor.role, "publish")
    if not payload.manualConfirm:
        raise DomainError("VALIDATION", "manualConfirm=true is required to publish.")
    meeting = _get_meeting(db, meeting_id)
    endpoint = "final_publish"
    replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
    if replay is not None:
        return [], replay, True
    if meeting.state != "public_notice_ready":
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            "Final publication is only allowed from public-notice-ready.",
            current_state=meeting.state,
        )
    review = _latest_disclosure_review(db, meeting)
    if review is None or not review.reviewed_version:
        raise DomainError(
            "DISCLOSURE_NOT_APPROVED",
            "Disclosure approval is required before final publication.",
            current_state=meeting.state,
        )
    projections = list(
        db.execute(select(PublicProjection).where(
            PublicProjection.meeting_id == meeting.id,
            PublicProjection.status == "approved",
        )).scalars()
    )
    for p in projections:
        if not p.reviewed_by or not p.reviewed_version:
            raise DomainError(
                "PROJECTION_PROVENANCE_MISSING",
                "A projection is missing review provenance.",
                current_state=meeting.state,
            )
    seq = _next_sequence(db, meeting)
    _transition_meeting(db, meeting, "publish", actor, entity_type="public_projection")
    for p in projections:
        p.status = "published"
        p.published_by = actor.actor
        p.published_version = seq
    response = {"published_projections": [ProjectionOut_model(p) for p in projections]}
    idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
    return projections, response, False


def ProjectionOut_model(p: PublicProjection) -> dict:
    return {
        "id": str(p.id),
        "source_object_id": p.source_object_id,
        "projection_type": p.projection_type,
        "title": p.title,
        "summary": p.summary,
        "disclosure_state": p.disclosure_state,
        "status": p.status,
        "reviewed_by": p.reviewed_by,
        "reviewed_version": p.reviewed_version,
        "published_by": p.published_by,
        "published_version": p.published_version,
    }


# ---------------------------------------------------------------------------
# completion / cancellation / public / audit
# ---------------------------------------------------------------------------

def complete_meeting(db: Session, meeting_id: uuid.UUID, actor, payload) -> Meeting:
    require_role(actor.role, "complete")
    meeting = _get_meeting(db, meeting_id)
    endpoint = "meeting_complete"
    replay = idempotency_check(db, actor, endpoint, payload.idempotencyKey, payload.model_dump())
    if replay is not None:
        return meeting, replay, True
    _transition_meeting(db, meeting, "complete", actor, entity_type="meeting")
    response = {"meeting_id": str(meeting.id), "state": meeting.state}
    idempotency_store(db, actor, endpoint, payload.idempotencyKey, payload.model_dump(), response)
    return meeting, response, False


def cancel_meeting(db: Session, meeting_id: uuid.UUID, actor, payload) -> Meeting:
    require_role(actor.role, "cancel")
    meeting = _get_meeting(db, meeting_id)
    _transition_meeting(db, meeting, "cancel", actor, entity_type="meeting")
    notice = Notice(
        meeting_id=meeting.id,
        title="정족수 미달로 인한 회의 연기·재소집 공고 (합성)",
        body=payload.reason or "출석 미달 — 법적 효력/유효성 판단 없음",
        notice_type="postponed",
        status="published",
        reviewed_by=actor.actor,
        reviewed_version=_next_sequence(db, meeting),
        published_by=actor.actor,
        published_version=_next_sequence(db, meeting),
    )
    db.add(notice)
    db.add(
        PublicProjection(
            meeting_id=meeting.id,
            source_object_id="postponed-notice",
            projection_type="notice",
            title=notice.title,
            summary=notice.body,
            disclosure_state="public",
            status="published",
            reviewed_by=actor.actor,
            reviewed_version=notice.reviewed_version,
            published_by=actor.actor,
            published_version=notice.published_version,
        )
    )
    return meeting


def public_projections(db: Session, meeting_id: uuid.UUID):
    meeting = db.execute(select(Meeting).where(Meeting.id == meeting_id)).scalar_one_or_none()
    if meeting is None:
        raise DomainError("NOT_FOUND", "Meeting not found.")
    return list(
        db.execute(select(PublicProjection).where(
            PublicProjection.meeting_id == meeting.id,
            PublicProjection.status == "published",
        ).order_by(PublicProjection.created_at)).scalars()
    )


def audit_events(db: Session, meeting_id: uuid.UUID, actor):
    require_role(actor.role, "audit_read")
    meeting = _get_meeting(db, meeting_id)
    return list(
        db.execute(select(AuditEvent).where(AuditEvent.meeting_id == meeting.id).order_by(AuditEvent.sequence)).scalars()
    )


# ---------------------------------------------------------------------------
# synthetic seed
# ---------------------------------------------------------------------------

def seed_synthetic(db: Session) -> Community:
    """Synthetic fixture seed — 솔빛마루 2단지 / Solbit Maru 2 (420 households)."""
    community = Community(name="솔빛마루 2단지", name_en="Solbit Maru 2", households=420, synthetic=True)
    db.add(community)
    db.flush()
    roles = ["대표회의 관리자", "동대표·위원", "관리사무소", "감사", "일반 주민", "외부 검토자"]
    for i, role in enumerate(roles, start=1):
        user = User(community_id=community.id, name=f"{role} 갑(합성)")
        db.add(user)
        db.flush()
        db.add(RoleAssignment(user_id=user.id, community_id=community.id, role=role))
    db.add(Rule(community_id=community.id, title="관리규약 제N조(회의 성립) — 합성 예시 조항", excerpt="대표회의는 재적 대표의 3분의 1 이상 출석으로 성립한다. (합성 예시 — 법적 효력 없음)"))
    db.flush()
    return community
