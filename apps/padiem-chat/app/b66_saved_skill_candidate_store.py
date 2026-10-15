"""B66 #3186 — durable account-bound Saved Quote Skill candidate (approval request) store.

Authority boundary
------------------
- ``quote-skill.js`` / ``quote-skill-candidate.js`` remain the canonical Saved
  Quote Skill **candidate** semantic authority. This module never re-derives
  layout, calculation, or fingerprint semantics; it persists the exact bounded
  envelope the browser submitted, plus a server-side content digest.
- Padiem signed auth / Control Plane owns user and tenant identity. The
  workspace is resolved server-side; caller-supplied ownership fields are
  rejected before this module is reached.
- A candidate is an approval *request*. It is not a Saved Quote Skill and it can
  never be read back as one. Only the trusted operator review contract
  (``b66_saved_skill_candidate_review``) may convert a pending candidate into an
  approved artifact, and only by calling the existing #3301 store.
- Existing ``PADIEM_CHAT_DB`` D1 is reused; no request-time DDL is allowed.

Integrity
---------
``candidate_digest`` is the SHA-256 of the exact compact JSON bytes that were
stored. Re-reading the row and recomputing that digest proves the reviewed
candidate is byte-identical to the submitted one, so a decision can never
activate content that changed after submission.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .b66_saved_quote_skill_store import _row_to_dict, _rows_from_result

MAX_CANDIDATES = 20
MAX_CANDIDATE_JSON_BYTES = 32 * 1024
MAX_SKILL_NAME_CHARS = 80
MAX_CLIENT_REF_CHARS = 64
MAX_REJECTION_REASON_CHARS = 200
MAX_WORKSPACE_ID_CHARS = 160
MAX_USER_ID_CHARS = 80
MAX_SKILL_VERSION = 1_000_000

CANDIDATE_STATUS_PENDING = "pending"
CANDIDATE_STATUS_APPROVED = "approved"
CANDIDATE_STATUS_REJECTED = "rejected"
CANDIDATE_STATUSES = (
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_STATUS_APPROVED,
    CANDIDATE_STATUS_REJECTED,
)

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID_RE = re.compile(r"^b66cand_[0-9a-f]{32}$")
# The assigned Skill lives in the separate #3301 table; its row id has its own shape.
_SAVED_SKILL_ROW_RE = re.compile(r"^b66skill_[0-9a-f]{32}$")
_CLIENT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_OWNER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")

_CANDIDATE_SCHEMA_VERSION = 1
_REQUIRED_CANDIDATE_OBJECTS = ("fixedDefaults", "variableSchema", "internalTemplate", "provenance")
# The envelope is stored as-is; a candidate must never arrive pre-approved.
_FORBIDDEN_CANDIDATE_KEYS = ("approval", "approved", "owner", "user_id", "workspace_id", "tenant_id")


class SavedQuoteSkillCandidateStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SavedQuoteSkillCandidateSubmission:
    """Validated, bounded candidate envelope ready for durable storage."""

    client_ref: str
    skill_id: str
    skill_name: str
    skill_fingerprint: str
    candidate_digest: str
    candidate_json: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_id() -> str:
    return "b66cand_" + uuid.uuid4().hex


def validate_candidate_row_id(value: object) -> str:
    if not isinstance(value, str) or not _ROW_ID_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillCandidateStoreError("candidate id is invalid")
    return value.strip()


def _clean_owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillCandidateStoreError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise SavedQuoteSkillCandidateStoreError(f"{label} is invalid")
    return text


def _clean_skill_name(value: object) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillCandidateStoreError("skill_name is invalid")
    text = " ".join(value.split())
    if not text or len(text) > MAX_SKILL_NAME_CHARS or _CONTROL_RE.search(text):
        raise SavedQuoteSkillCandidateStoreError("skill_name is invalid")
    return text


def _clean_client_ref(value: object) -> str:
    if not isinstance(value, str) or not _CLIENT_REF_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillCandidateStoreError("client_ref is invalid")
    return value.strip()


def _clean_decision_ref(value: object) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillCandidateStoreError("decision_ref is invalid")
    return value.strip()


def _clean_owner_id(value: object) -> str:
    if not isinstance(value, str) or not _OWNER_ID_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillCandidateStoreError("decision_by is invalid")
    return value.strip()


def _clean_rejection_reason(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SavedQuoteSkillCandidateStoreError("rejection_reason is invalid")
    text = " ".join(value.split())
    if len(text) > MAX_REJECTION_REASON_CHARS or _CONTROL_RE.search(text):
        raise SavedQuoteSkillCandidateStoreError("rejection_reason is invalid")
    return text


def canonicalize_candidate_submission(
    *,
    client_ref: object,
    candidate: object,
) -> SavedQuoteSkillCandidateSubmission:
    """Validate only the storage envelope around a canonical B66 candidate.

    Full candidate semantics stay owned by ``quote-skill-candidate.js``. This
    function proves the envelope is bounded, is not already approved, and
    carries a well-formed fingerprint, and it derives the server-side content
    digest and skill identity used for later review.
    """

    clean_ref = _clean_client_ref(client_ref)
    if not isinstance(candidate, dict):
        raise SavedQuoteSkillCandidateStoreError("candidate is invalid")
    if candidate.get("schemaVersion") != _CANDIDATE_SCHEMA_VERSION:
        raise SavedQuoteSkillCandidateStoreError("candidate schema is unsupported")
    for key in _FORBIDDEN_CANDIDATE_KEYS:
        if candidate.get(key) is not None:
            raise SavedQuoteSkillCandidateStoreError("candidate must not carry approval or ownership")
    if candidate.get("status") != "candidate":
        raise SavedQuoteSkillCandidateStoreError("candidate status is invalid")
    for key in _REQUIRED_CANDIDATE_OBJECTS:
        if not isinstance(candidate.get(key), dict):
            raise SavedQuoteSkillCandidateStoreError("candidate is incomplete")

    sender = candidate["fixedDefaults"].get("sender")
    if not isinstance(sender, dict) or not isinstance(sender.get("company"), str) or not sender["company"].strip():
        raise SavedQuoteSkillCandidateStoreError("candidate sender company is required")

    fingerprint = candidate.get("skillFingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise SavedQuoteSkillCandidateStoreError("candidate skill fingerprint is invalid")

    clean_name = _clean_skill_name(candidate.get("name"))

    try:
        compact = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        encoded = compact.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SavedQuoteSkillCandidateStoreError("candidate is not serializable") from exc
    if len(encoded) > MAX_CANDIDATE_JSON_BYTES:
        raise SavedQuoteSkillCandidateStoreError("candidate is too large")

    digest = hashlib.sha256(encoded).hexdigest()
    # Server-derived, deterministic skill identity. The client cannot choose it,
    # and identical content maps to the same identity on resubmission.
    skill_id = "saved-quote-" + digest[:16]
    if not _SKILL_ID_RE.fullmatch(skill_id):
        raise SavedQuoteSkillCandidateStoreError("derived skill id is invalid")

    return SavedQuoteSkillCandidateSubmission(
        client_ref=clean_ref,
        skill_id=skill_id,
        skill_name=clean_name,
        skill_fingerprint=fingerprint,
        candidate_digest=digest,
        candidate_json=compact,
    )


def candidate_content_digest(candidate_json: object) -> str:
    """Recompute the stored-bytes digest for an integrity re-check."""

    if not isinstance(candidate_json, str) or not candidate_json:
        raise SavedQuoteSkillCandidateStoreError("candidate json is invalid")
    try:
        encoded = candidate_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SavedQuoteSkillCandidateStoreError("candidate json is invalid") from exc
    if len(encoded) > MAX_CANDIDATE_JSON_BYTES:
        raise SavedQuoteSkillCandidateStoreError("candidate json is too large")
    return hashlib.sha256(encoded).hexdigest()


def _public_projection(row: dict[str, Any], *, include_candidate: bool) -> dict[str, Any]:
    """Customer-visible projection.

    The deciding operator identity (``decision_by``) is deliberately not
    projected: a customer may learn *that* and *when* a decision happened, never
    which staff subject made it.
    """

    projected: dict[str, Any] = {
        "candidate_id": str(row.get("id", "")),
        "status": str(row.get("status", "")),
        "skill_id": str(row.get("skill_id", "")),
        "skill_name": str(row.get("skill_name", "")),
        "skill_fingerprint": str(row.get("skill_fingerprint", "")),
        "candidate_digest": str(row.get("candidate_digest", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "decided_at": str(row.get("decision_at") or ""),
        "rejection_reason": str(row.get("rejection_reason") or ""),
        "saved_skill_id": str(row.get("saved_skill_id") or ""),
    }
    raw_version = row.get("skill_version")
    projected["skill_version"] = int(raw_version) if isinstance(raw_version, int) else None
    if include_candidate:
        raw = row.get("candidate_json")
        try:
            projected["candidate"] = json.loads(raw) if isinstance(raw, str) else None
        except json.JSONDecodeError:
            projected["candidate"] = None
    return projected


def _operator_projection(row: dict[str, Any]) -> dict[str, str]:
    """Minimal server-derived B66 admin summary; never expose customer content or digests."""
    return {
        "candidate_id": str(row.get("id", "")),
        "user_id": str(row.get("user_id", "")),
        "status": str(row.get("status", "")),
        "skill_name": str(row.get("skill_name", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "decided_at": str(row.get("decision_at") or ""),
    }


class SavedQuoteSkillCandidateStore(Protocol):
    async def submit(
        self,
        *,
        user_id: str,
        workspace_id: str,
        submission: SavedQuoteSkillCandidateSubmission,
    ) -> dict[str, Any]: ...

    async def list_candidates(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_CANDIDATES,
    ) -> list[dict[str, Any]]: ...

    async def get_candidate(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None: ...

    async def list_operator_candidates(
        self,
        *,
        status: str = CANDIDATE_STATUS_PENDING,
        limit: int = MAX_CANDIDATES,
    ) -> list[dict[str, Any]]: ...

    async def get_operator_candidate(
        self,
        *,
        candidate_id: str,
    ) -> dict[str, Any] | None: ...

    async def read_candidate_envelope(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None: ...

    async def record_decision(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
        decision: str,
        decided_by: str,
        decision_ref: str,
        decided_at: str,
        saved_skill_id: str | None = None,
        skill_version: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any] | None: ...


class D1SavedQuoteSkillCandidateStore:
    """Cloudflare D1 adapter using prepared statement binds only."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    _COLUMNS = (
        "id, user_id, workspace_id, client_ref, skill_id, skill_name, skill_fingerprint, "
        "candidate_digest, candidate_json, status, decision_by, decision_ref, decision_at, "
        "rejection_reason, saved_skill_id, skill_version, created_at, updated_at"
    )

    async def _read_row(
        self,
        *,
        owner: str,
        workspace: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        return await self._first(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
            "WHERE id=? AND user_id=? AND workspace_id=?",
            candidate_id, owner, workspace,
        )

    async def submit(
        self,
        *,
        user_id: str,
        workspace_id: str,
        submission: SavedQuoteSkillCandidateSubmission,
    ) -> dict[str, Any]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        if not isinstance(submission, SavedQuoteSkillCandidateSubmission):
            raise SavedQuoteSkillCandidateStoreError("validated candidate submission is required")

        # Idempotency 1: the same browser request must never open a second row.
        existing = await self._first(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
            "WHERE user_id=? AND workspace_id=? AND client_ref=?",
            owner, workspace, submission.client_ref,
        )
        if existing:
            return {**_public_projection(existing, include_candidate=True), "duplicate": True}

        # Idempotency 2: identical submitted content already awaiting review is the
        # same request. The digest covers the whole envelope, so a renamed or
        # otherwise changed candidate stays a genuinely separate request.
        pending = await self._first(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
            "WHERE user_id=? AND workspace_id=? AND candidate_digest=? AND status='pending'",
            owner, workspace, submission.candidate_digest,
        )
        if pending:
            return {**_public_projection(pending, include_candidate=True), "duplicate": True}

        row_id = _row_id()
        now = _now_iso()
        try:
            await self._run(
                "INSERT INTO b66_saved_skill_candidate "
                "(id, user_id, workspace_id, client_ref, skill_id, skill_name, skill_fingerprint, "
                "candidate_digest, candidate_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                row_id, owner, workspace, submission.client_ref, submission.skill_id,
                submission.skill_name, submission.skill_fingerprint, submission.candidate_digest,
                submission.candidate_json, now, now,
            )
        except Exception as exc:
            # A concurrent identical submit lost the race against the unique
            # index. Return the row that won instead of creating a duplicate.
            raced = await self._first(
                "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
                "WHERE user_id=? AND workspace_id=? AND client_ref=?",
                owner, workspace, submission.client_ref,
            )
            if raced:
                return {**_public_projection(raced, include_candidate=True), "duplicate": True}
            raise SavedQuoteSkillCandidateStoreError("candidate write failed") from exc

        row = await self._read_row(owner=owner, workspace=workspace, candidate_id=row_id)
        if not row:
            raise SavedQuoteSkillCandidateStoreError("candidate write failed")
        return {**_public_projection(row, include_candidate=True), "duplicate": False}

    async def list_candidates(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_CANDIDATES,
    ) -> list[dict[str, Any]]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        bounded = max(1, min(int(limit), MAX_CANDIDATES))
        rows = await self._all(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
            "WHERE user_id=? AND workspace_id=? ORDER BY updated_at DESC LIMIT ?",
            owner, workspace, bounded,
        )
        return [_public_projection(row, include_candidate=False) for row in rows]

    async def get_candidate(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_candidate_row_id(candidate_id)
        row = await self._read_row(owner=owner, workspace=workspace, candidate_id=row_id)
        return _public_projection(row, include_candidate=True) if row else None

    async def list_operator_candidates(
        self,
        *,
        status: str = CANDIDATE_STATUS_PENDING,
        limit: int = MAX_CANDIDATES,
    ) -> list[dict[str, Any]]:
        if status not in CANDIDATE_STATUSES:
            raise SavedQuoteSkillCandidateStoreError("candidate status is invalid")
        bounded = max(1, min(int(limit), MAX_CANDIDATES))
        rows = await self._all(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate "
            "WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            status, bounded,
        )
        return [_operator_projection(row) for row in rows]

    async def get_operator_candidate(
        self,
        *,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        row_id = validate_candidate_row_id(candidate_id)
        row = await self._first(
            "SELECT " + self._COLUMNS + " FROM b66_saved_skill_candidate WHERE id=?",
            row_id,
        )
        return _operator_projection(row) if row else None

    async def read_candidate_envelope(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        """Raw owner-scoped row for the trusted review path.

        Returns the exact stored ``candidate_json`` so the reviewer can recompute
        the content digest before converting the candidate into an approved
        artifact. Never exposed by a customer route.
        """

        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_candidate_row_id(candidate_id)
        row = await self._read_row(owner=owner, workspace=workspace, candidate_id=row_id)
        if not row:
            return None
        return {
            "candidate_id": str(row.get("id", "")),
            "status": str(row.get("status", "")),
            "skill_id": str(row.get("skill_id", "")),
            "skill_name": str(row.get("skill_name", "")),
            "skill_fingerprint": str(row.get("skill_fingerprint", "")),
            "candidate_digest": str(row.get("candidate_digest", "")),
            "candidate_json": row.get("candidate_json"),
            "saved_skill_id": str(row.get("saved_skill_id") or ""),
        }

    async def record_decision(
        self,
        *,
        user_id: str,
        workspace_id: str,
        candidate_id: str,
        decision: str,
        decided_by: str,
        decision_ref: str,
        decided_at: str,
        saved_skill_id: str | None = None,
        skill_version: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any] | None:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_candidate_row_id(candidate_id)
        if decision not in DECISIONS:
            raise SavedQuoteSkillCandidateStoreError("decision is invalid")
        actor = _clean_owner_id(decided_by)
        reference = _clean_decision_ref(decision_ref)
        if not isinstance(decided_at, str) or not decided_at or _CONTROL_RE.search(decided_at):
            raise SavedQuoteSkillCandidateStoreError("decided_at is invalid")
        reason = _clean_rejection_reason(rejection_reason)
        version: int | None = None
        if skill_version is not None:
            if isinstance(skill_version, bool) or not isinstance(skill_version, int) or not (1 <= skill_version <= MAX_SKILL_VERSION):
                raise SavedQuoteSkillCandidateStoreError("skill_version is invalid")
            version = skill_version

        if decision == DECISION_APPROVE:
            if not isinstance(saved_skill_id, str) or not _SAVED_SKILL_ROW_RE.fullmatch(saved_skill_id.strip()):
                raise SavedQuoteSkillCandidateStoreError("saved_skill_id is required for approval")
            status = CANDIDATE_STATUS_APPROVED
            saved_id: str | None = saved_skill_id.strip()
            reason = ""
        else:
            status = CANDIDATE_STATUS_REJECTED
            saved_id = None
            version = None

        # Only a still-pending candidate may be decided. A second decision is a
        # no-op: the caller re-reads the recorded verdict instead of overwriting it.
        await self._run(
            "UPDATE b66_saved_skill_candidate "
            "SET status=?, decision_by=?, decision_ref=?, decision_at=?, rejection_reason=?, "
            "saved_skill_id=?, skill_version=?, updated_at=? "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='pending'",
            status, actor, reference, decided_at, reason, saved_id, version, _now_iso(),
            row_id, owner, workspace,
        )
        row = await self._read_row(owner=owner, workspace=workspace, candidate_id=row_id)
        if not row:
            return None
        return _public_projection(row, include_candidate=False)
