"""FastAPI routes for the minimal governance ledger.

Synthetic actor context comes from request headers:
  X-Synthetic-Actor, X-Synthetic-Role
SYNTHETIC DEVELOPMENT AUTHORITY ONLY — NOT AUTHENTICATION — MUST NOT BE ENABLED IN PRODUCTION
"""

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from . import services
from .database import get_db
from .domain import DomainError, ROLES, SLUG_TO_ROLE
from .models import (
    ActionItem,
    Agenda,
    AttendanceRecord,
    AuditEvent,
    Community,
    DisclosureReview,
    Discussion,
    Dissent,
    Document,
    Meeting,
    Notice,
    PublicProjection,
    QuorumRecord,
    Redaction,
    Resolution,
)
from .schemas import (
    ActionCreate,
    ActionOut,
    AgendaCreate,
    AgendaOut,
    AttendanceCreate,
    AttendanceOut,
    AuditEventOut,
    CancelCreate,
    CommunityCreate,
    CommunityOut,
    CompleteCreate,
    DiscussionCreate,
    DiscussionOut,
    DiscussionPatch,
    DissentCreate,
    DissentOut,
    DocumentCreate,
    DocumentOut,
    DisclosureReviewCreate,
    MeetingCreate,
    MeetingDetail,
    MeetingOut,
    NoticeCreate,
    NoticeOut,
    NoticePatch,
    NoticePublish,
    PublicProjectionOut,
    PublishCreate,
    QuorumCreate,
    QuorumOut,
    RedactionCreate,
    RedactionOut,
    ResolutionCreate,
    ResolutionOut,
    SyntheticActor,
    VersionOut,
)


def get_actor(
    x_synthetic_actor: str = Header(default="synthetic"),
    x_synthetic_role: str = Header(default=""),
):
    role = SLUG_TO_ROLE.get(x_synthetic_role, x_synthetic_role)
    if role not in ROLES:
        raise DomainError("ROLE_NOT_PERMITTED", f"Invalid synthetic role: '{x_synthetic_role}'.")
    return SyntheticActor(actor=x_synthetic_actor, role=role)


def reject_binary(request: Request):
    """Reject binary/multipart uploads before body parsing (metadata only)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type or "octet-stream" in content_type:
        raise DomainError(
            "BINARY_UPLOAD_NOT_ALLOWED",
            "Binary or multipart upload is not allowed — document metadata only.",
        )


def _model_out(model, schema):
    return schema.model_validate(model, from_attributes=True)


def _meeting_out(m: Meeting) -> MeetingOut:
    return _model_out(m, MeetingOut)


router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# communities / meetings
# ---------------------------------------------------------------------------

@router.post("/communities", response_model=CommunityOut)
def create_community(payload: CommunityCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    community = services.create_community(db, actor, payload)
    db.commit()
    return _model_out(community, CommunityOut)


@router.post("/meetings", response_model=MeetingOut)
def create_meeting(payload: MeetingCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    meeting = services.create_meeting(db, actor, payload)
    db.commit()
    return _model_out(meeting, MeetingOut)


@router.get("/meetings/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: uuid.UUID, actor=Depends(get_actor), db: Session = Depends(get_db)):
    meeting, versions = services.get_meeting(db, meeting_id, actor)
    return MeetingDetail(
        meeting=_model_out(meeting, MeetingOut),
        versions=[_model_out(v, VersionOut) for v in versions],
    )


# ---------------------------------------------------------------------------
# agendas
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/agendas", response_model=AgendaOut)
def create_agenda(meeting_id: uuid.UUID, payload: AgendaCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    agenda = services.create_agenda(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(agenda, AgendaOut)


# ---------------------------------------------------------------------------
# notices
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/notices", response_model=NoticeOut)
def create_notice(meeting_id: uuid.UUID, payload: NoticeCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    notice = services.create_notice(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(notice, NoticeOut)


@router.patch("/meetings/{meeting_id}/notices/{notice_id}", response_model=NoticeOut)
def update_notice(meeting_id: uuid.UUID, notice_id: uuid.UUID, payload: NoticePatch, actor=Depends(get_actor), db: Session = Depends(get_db)):
    notice = services.update_notice(db, meeting_id, notice_id, actor, payload)
    db.commit()
    return _model_out(notice, NoticeOut)


@router.post("/meetings/{meeting_id}/notices/{notice_id}/publish", response_model=NoticeOut)
def publish_notice(meeting_id: uuid.UUID, notice_id: uuid.UUID, payload: NoticePublish, actor=Depends(get_actor), db: Session = Depends(get_db)):
    notice, response, replayed = services.publish_notice(db, meeting_id, notice_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return _model_out(notice, NoticeOut)


# ---------------------------------------------------------------------------
# attendance / quorum
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/attendance", response_model=AttendanceOut)
def record_attendance(meeting_id: uuid.UUID, payload: AttendanceCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    rec, response, replayed = services.record_attendance(db, meeting_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return _model_out(rec, AttendanceOut)


@router.post("/meetings/{meeting_id}/quorum", response_model=QuorumOut)
def record_quorum(meeting_id: uuid.UUID, payload: QuorumCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    rec, response, replayed = services.record_quorum(db, meeting_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return _model_out(rec, QuorumOut)


# ---------------------------------------------------------------------------
# discussions / dissent
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/discussions", response_model=DiscussionOut)
def create_discussion(meeting_id: uuid.UUID, payload: DiscussionCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    disc = services.create_discussion(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(disc, DiscussionOut)


@router.patch("/meetings/{meeting_id}/discussions/{discussion_id}", response_model=DiscussionOut)
def update_discussion(meeting_id: uuid.UUID, discussion_id: uuid.UUID, payload: DiscussionPatch, actor=Depends(get_actor), db: Session = Depends(get_db)):
    disc = services.update_discussion(db, meeting_id, discussion_id, actor, payload)
    db.commit()
    return _model_out(disc, DiscussionOut)


@router.post("/meetings/{meeting_id}/dissent", response_model=DissentOut)
def record_dissent(meeting_id: uuid.UUID, payload: DissentCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    dissent = services.record_dissent(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(dissent, DissentOut)


# ---------------------------------------------------------------------------
# resolutions / actions / documents
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/resolutions", response_model=ResolutionOut)
def create_resolution(meeting_id: uuid.UUID, payload: ResolutionCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    res, response, replayed = services.create_resolution(db, meeting_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return _model_out(res, ResolutionOut)


@router.post("/meetings/{meeting_id}/actions", response_model=ActionOut)
def create_action(meeting_id: uuid.UUID, payload: ActionCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    item = services.create_action(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(item, ActionOut)


@router.post("/meetings/{meeting_id}/documents", response_model=DocumentOut)
def create_document(meeting_id: uuid.UUID, payload: DocumentCreate, actor=Depends(get_actor), db: Session = Depends(get_db), _binary: None = Depends(reject_binary)):
    doc = services.create_document(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(doc, DocumentOut)


@router.post("/meetings/{meeting_id}/disclosure", response_model=MeetingOut)
def open_disclosure(meeting_id: uuid.UUID, actor=Depends(get_actor), db: Session = Depends(get_db)):
    meeting = services.open_disclosure(db, meeting_id, actor)
    db.commit()
    return _model_out(meeting, MeetingOut)


# ---------------------------------------------------------------------------
# redaction / disclosure / publish / complete / cancel
# ---------------------------------------------------------------------------

@router.post("/meetings/{meeting_id}/redactions", response_model=RedactionOut)
def create_redaction(meeting_id: uuid.UUID, payload: RedactionCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    redaction = services.create_redaction(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(redaction, RedactionOut)


@router.post("/meetings/{meeting_id}/disclosure-reviews", response_model=dict)
def approve_disclosure(meeting_id: uuid.UUID, payload: DisclosureReviewCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    try:
        review, response, replayed = services.approve_disclosure(db, meeting_id, actor, payload)
    except DomainError as exc:
        if exc.code == "REDACTION_INCOMPLETE":
            db.commit()  # persist the redaction_required state + audit
        raise
    if replayed:
        db.rollback()
        return response
    db.commit()
    return response


@router.post("/meetings/{meeting_id}/publish", response_model=dict)
def publish_final(meeting_id: uuid.UUID, payload: PublishCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    projections, response, replayed = services.publish_final(db, meeting_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return response


@router.post("/meetings/{meeting_id}/complete", response_model=dict)
def complete_meeting(meeting_id: uuid.UUID, payload: CompleteCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    meeting, response, replayed = services.complete_meeting(db, meeting_id, actor, payload)
    if replayed:
        db.rollback()
        return response
    db.commit()
    return response


@router.post("/meetings/{meeting_id}/cancel", response_model=MeetingOut)
def cancel_meeting(meeting_id: uuid.UUID, payload: CancelCreate, actor=Depends(get_actor), db: Session = Depends(get_db)):
    meeting = services.cancel_meeting(db, meeting_id, actor, payload)
    db.commit()
    return _model_out(meeting, MeetingOut)


# ---------------------------------------------------------------------------
# public / audit
# ---------------------------------------------------------------------------

@router.get("/public/meetings/{meeting_id}", response_model=list[PublicProjectionOut])
def public_meeting(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    projections = services.public_projections(db, meeting_id)
    return [_model_out(p, PublicProjectionOut) for p in projections]


@router.get("/meetings/{meeting_id}/audit-events", response_model=list[AuditEventOut])
def audit_events(meeting_id: uuid.UUID, actor=Depends(get_actor), db: Session = Depends(get_db)):
    events = services.audit_events(db, meeting_id, actor)
    return [_model_out(e, AuditEventOut) for e in events]
