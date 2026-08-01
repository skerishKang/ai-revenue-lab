"""Domain contract: states, transitions, roles, guards, error codes.

Backend domain states map the frontend 24-state UX model (PR #352) to explicit
domain transitions. Server-side guards block the transitions prohibited by the
architecture contract (Issue #356).
"""

ROLES = [
    "대표회의 관리자",
    "동대표·위원",
    "관리사무소",
    "감사",
    "일반 주민",
    "외부 검토자",
]

# ASCII header slugs -> canonical role names (headers must be ASCII-safe).
SLUG_TO_ROLE = {
    "admin": "대표회의 관리자",
    "rep": "동대표·위원",
    "office": "관리사무소",
    "auditor": "감사",
    "resident": "일반 주민",
    "reviewer": "외부 검토자",
}

# backend domain states (meeting.state)
STATES = [
    "draft",
    "agenda_ready",
    "notice_draft",
    "notice_reviewed",
    "notice_published",
    "attendance_open",
    "quorum_incomplete",
    "quorum_recorded",
    "discussion_open",
    "dissent_recorded",
    "resolution_draft",
    "resolution_review",
    "resolution_approved",
    "action_pending",
    "disclosure_review",
    "redaction_required",
    "public_notice_ready",
    "public_notice_published",
    "completed",
    "cancelled",
]

# (from_state, action) -> to_state; None means decided by the service/data
TRANSITIONS = {
    ("draft", "agenda"): "agenda_ready",
    ("agenda_ready", "notice_create"): "notice_draft",
    ("notice_draft", "notice_update"): "notice_draft",
    ("notice_draft", "notice_review"): "notice_reviewed",
    ("notice_reviewed", "notice_publish"): "notice_published",
    ("notice_published", "attendance"): "attendance_open",
    ("attendance_open", "attendance"): "attendance_open",
    ("quorum_incomplete", "attendance_supplement"): "attendance_open",
    ("attendance_open", "quorum"): None,  # quorum_recorded | quorum_incomplete
    ("quorum_recorded", "discussion"): "discussion_open",
    ("discussion_open", "discussion"): "discussion_open",
    ("dissent_recorded", "discussion"): "discussion_open",
    ("discussion_open", "dissent"): "dissent_recorded",
    ("discussion_open", "resolution"): "resolution_draft",
    ("dissent_recorded", "resolution"): "resolution_draft",
    ("resolution_draft", "resolution_submit"): "resolution_review",
    ("resolution_review", "resolution_approve"): "resolution_approved",
    ("resolution_approved", "action"): "action_pending",
    ("action_pending", "disclosure"): "disclosure_review",
    ("disclosure_review", "redaction"): "disclosure_review",
    ("redaction_required", "redaction"): "disclosure_review",
    ("disclosure_review", "disclosure_approve"): "public_notice_ready",
    ("public_notice_ready", "publish"): "public_notice_published",
    ("public_notice_published", "complete"): "completed",
    ("quorum_incomplete", "cancel"): "cancelled",
}

# action -> allowed roles
ROLE_ALLOW = {
    "community_create": ["대표회의 관리자"],
    "meeting_create": ["대표회의 관리자"],
    "meeting_get": ["대표회의 관리자", "동대표·위원", "관리사무소", "감사"],
    "agenda_create": ["대표회의 관리자", "동대표·위원"],
    "notice_create": ["대표회의 관리자", "관리사무소"],
    "notice_update": ["대표회의 관리자"],
    "notice_publish": ["대표회의 관리자"],
    "attendance": ["대표회의 관리자", "관리사무소"],
    "quorum": ["대표회의 관리자"],
    "discussion_create": ["대표회의 관리자", "동대표·위원", "관리사무소"],
    "discussion_update": ["대표회의 관리자", "동대표·위원"],
    "dissent": ["동대표·위원", "대표회의 관리자"],
    "resolution": ["대표회의 관리자"],
    "action": ["대표회의 관리자", "관리사무소"],
    "disclosure": ["대표회의 관리자"],
    "document": ["대표회의 관리자", "관리사무소"],
    "redaction": ["외부 검토자", "대표회의 관리자"],
    "disclosure_approve": ["외부 검토자"],
    "publish": ["대표회의 관리자"],
    "complete": ["대표회의 관리자"],
    "cancel": ["대표회의 관리자"],
    "audit_read": ["감사", "대표회의 관리자"],
    "public_read": [],  # no restriction
}

# domain error codes -> HTTP status
HTTP_BY_CODE = {
    "VALIDATION": 400,
    "ROLE_NOT_PERMITTED": 403,
    "NOT_FOUND": 404,
    "IDEMPOTENCY_CONFLICT": 409,
    "QUORUM_RECHECK_REQUIRED": 409,
    "REDACTION_INCOMPLETE": 409,
    "DISCLOSURE_NOT_APPROVED": 409,
    "PROJECTION_PROVENANCE_MISSING": 409,
    "BINARY_UPLOAD_NOT_ALLOWED": 413,
    "INVALID_STATE_TRANSITION": 422,
}


class DomainError(Exception):
    def __init__(self, code: str, message: str, current_state: str | None = None):
        self.code = code
        self.message = message
        self.current_state = current_state
        super().__init__(message)

    @property
    def http_status(self) -> int:
        return HTTP_BY_CODE.get(self.code, 400)

    def to_body(self) -> dict:
        body = {"error": {"code": self.code, "message": self.message}}
        if self.current_state is not None:
            body["error"]["currentState"] = self.current_state
        return body


def next_state(from_state: str, action: str, *, decided: str | None = None) -> str:
    key = (from_state, action)
    if key not in TRANSITIONS:
        raise DomainError(
            "INVALID_STATE_TRANSITION",
            f"Action '{action}' is not allowed from state '{from_state}'.",
            current_state=from_state,
        )
    target = TRANSITIONS[key]
    if target is None:
        if decided is None:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                f"Action '{action}' requires a decided outcome.",
                current_state=from_state,
            )
        target = decided
    return target


def require_role(role: str, action: str) -> None:
    allowed = ROLE_ALLOW.get(action, [])
    if allowed and role not in allowed:
        raise DomainError(
            "ROLE_NOT_PERMITTED",
            f"Role '{role}' is not permitted for action '{action}'.",
            current_state=None,
        )
