"""Pydantic v2 request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SyntheticActor(BaseModel):
    actor: str = Field(..., min_length=1, max_length=120)
    role: str


class CommunityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    name_en: str | None = None
    households: int = Field(..., gt=0)
    synthetic: bool = True


class CommunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    name_en: str | None = None
    households: int
    synthetic: bool


class MeetingCreate(BaseModel):
    community_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=200)
    quarter: str | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    community_id: uuid.UUID
    title: str
    quarter: str | None = None
    state: str


class AgendaCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    rule_ref: str | None = None


class AgendaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    rule_ref: str | None = None


class NoticeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    notice_type: str = "meeting"


class NoticePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    reviewed: bool = False


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    body: str
    notice_type: str
    status: str
    reviewed_by: str | None = None
    reviewed_version: int | None = None
    published_by: str | None = None
    published_version: int | None = None


class NoticePublish(BaseModel):
    manualConfirm: bool = False
    idempotencyKey: str | None = None


class AttendanceCreate(BaseModel):
    mode: str = "initial"  # initial | supplement
    roster: list[str] = Field(default_factory=list)
    count: int = Field(..., ge=0)
    reason: str | None = None
    manualConfirm: bool = False
    idempotencyKey: str | None = None


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    revision: int
    mode: str
    count: int
    reason: str | None = None


class QuorumCreate(BaseModel):
    attendanceCount: int = Field(..., ge=0)
    threshold: int = Field(..., ge=0)
    manualConfirm: bool = False
    idempotencyKey: str | None = None


class QuorumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    attendance_count: int
    threshold: int
    quorum_met: bool


class DiscussionCreate(BaseModel):
    agenda_id: uuid.UUID | None = None
    text: str = Field(..., min_length=1)


class DiscussionPatch(BaseModel):
    summary: str | None = None


class DiscussionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    agenda_id: uuid.UUID | None = None
    text: str
    summary: str | None = None


class DissentCreate(BaseModel):
    agenda_id: uuid.UUID | None = None
    text: str = Field(..., min_length=1)


class DissentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    member: str
    text: str
    retained: bool


class ResolutionCreate(BaseModel):
    text: str = Field(..., min_length=1)
    transition: str = "draft"  # draft | submit | approve
    idempotencyKey: str | None = None


class ResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    text: str
    status: str
    dissent_ref: str | None = None


class ActionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    owner: str | None = None
    due: str | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    owner: str | None = None
    due: str | None = None
    overdue: bool


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    metadata: dict | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    metadata_json: dict | None = None


class RedactionCreate(BaseModel):
    document_id: uuid.UUID
    redacted_text: str = Field(..., min_length=1)


class RedactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    document_id: uuid.UUID
    redacted_text: str
    confirmed_by: str | None = None


class DisclosureReviewCreate(BaseModel):
    manualConfirm: bool = False
    packageItems: list[str] = Field(default_factory=list)
    idempotencyKey: str | None = None


class DisclosureReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID
    manual_confirm: bool
    package_items: list
    reviewed_by: str | None = None
    reviewed_version: int | None = None


class PublishCreate(BaseModel):
    manualConfirm: bool = False
    idempotencyKey: str | None = None


class CompleteCreate(BaseModel):
    idempotencyKey: str | None = None


class CancelCreate(BaseModel):
    reason: str | None = None


class PublicProjectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_object_id: str
    projection_type: str
    title: str
    summary: str
    disclosure_state: str
    status: str
    reviewed_by: str | None = None
    reviewed_version: int | None = None
    published_by: str | None = None
    published_version: int | None = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID | None = None
    version: int
    from_state: str
    to_state: str
    action: str
    actor_id: str
    role: str
    sequence: int
    created_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    meeting_id: uuid.UUID | None = None
    entity_type: str
    entity_id: uuid.UUID | None = None
    version: int
    action: str
    from_state: str
    to_state: str
    actor_id: str
    role: str
    sequence: int


class MeetingDetail(BaseModel):
    meeting: MeetingOut
    versions: list[VersionOut]


class ErrorBody(BaseModel):
    error: dict
