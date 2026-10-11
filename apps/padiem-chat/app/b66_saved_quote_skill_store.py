"""Durable account-bound B66 Saved Quote Skill persistence (#3301).

Authority boundary:
- B66 quote-skill.js remains the canonical Saved Quote Skill semantic authority.
- This module does not reimplement QuoteTemplateProfile or QuoteCore semantics.
- It accepts only an already-approved serialized Skill envelope and verifies the
  bounded storage/approval/fingerprint metadata needed to persist it safely.
- Padiem signed auth / Control Plane owns user and tenant identity.
- Caller-supplied ownership fields are not part of the artifact.
- Existing PADIEM_CHAT_DB D1 is reused; no request-time DDL is allowed.

Raw source quotation bytes are never persisted here. The runtime record is the
approved Saved Quote Skill artifact needed for deterministic repeat generation.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_SAVED_QUOTE_SKILLS = 20
MAX_SKILL_ID_CHARS = 64
MAX_SKILL_NAME_CHARS = 80
MAX_SKILL_JSON_BYTES = 96 * 1024
MAX_WORKSPACE_ID_CHARS = 160
MAX_USER_ID_CHARS = 80
MAX_SKILL_VERSION = 1_000_000

_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID_RE = re.compile(r"^b66skill_[0-9a-f]{32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_EXPECTED_RENDERER_CONTRACT = "quote-template-renderer.v1"
_EXPECTED_CALCULATION_AUTHORITY = "quote-core"


class SavedQuoteSkillStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ApprovedSavedQuoteSkillArtifact:
    """Storage envelope for one canonical, already-approved B66 Skill."""

    skill_id: str
    skill_name: str
    fingerprint: str
    version: int
    serialized_json: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_id() -> str:
    return "b66skill_" + uuid.uuid4().hex


def _clean_owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise SavedQuoteSkillStoreError(f"{label} is invalid")
    return text


def _clean_skill_name(value: object) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError("skill_name is invalid")
    text = " ".join(value.split())
    if not text or len(text) > MAX_SKILL_NAME_CHARS or _CONTROL_RE.search(text):
        raise SavedQuoteSkillStoreError("skill_name is invalid")
    return text


def canonicalize_approved_artifact(
    *,
    skill_id: object,
    skill_name: object,
    fingerprint: object,
    version: object,
    serialized_json: object,
) -> ApprovedSavedQuoteSkillArtifact:
    """Validate only the persistence envelope around canonical B66 Skill JSON.

    Full Skill/Profile semantics remain owned by quote-skill.js. This function
    proves that the stored JSON is bounded, carries matching approval evidence,
    and matches the supplied id/name/fingerprint/version envelope.
    """

    if not isinstance(skill_id, str) or not _SKILL_ID_RE.fullmatch(skill_id.strip()):
        raise SavedQuoteSkillStoreError("skill_id is invalid")
    clean_id = skill_id.strip()
    clean_name = _clean_skill_name(skill_name)
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise SavedQuoteSkillStoreError("skill_fingerprint is invalid")
    if isinstance(version, bool) or not isinstance(version, int) or not (1 <= version <= MAX_SKILL_VERSION):
        raise SavedQuoteSkillStoreError("skill_version is invalid")
    if not isinstance(serialized_json, str) or not serialized_json:
        raise SavedQuoteSkillStoreError("skill_json is invalid")
    try:
        encoded = serialized_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SavedQuoteSkillStoreError("skill_json is invalid") from exc
    if len(encoded) > MAX_SKILL_JSON_BYTES:
        raise SavedQuoteSkillStoreError("skill_json is too large")
    try:
        payload = json.loads(serialized_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SavedQuoteSkillStoreError("skill_json is invalid") from exc
    if not isinstance(payload, dict):
        raise SavedQuoteSkillStoreError("skill_json is invalid")

    approval = payload.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise SavedQuoteSkillStoreError("skill is not approved")
    if approval.get("skillFingerprint") != fingerprint:
        raise SavedQuoteSkillStoreError("skill approval fingerprint mismatch")
    if payload.get("fingerprint") != fingerprint:
        raise SavedQuoteSkillStoreError("skill fingerprint mismatch")
    if payload.get("id") != clean_id:
        raise SavedQuoteSkillStoreError("skill id mismatch")
    if payload.get("name") != clean_name:
        raise SavedQuoteSkillStoreError("skill name mismatch")
    if payload.get("rendererContract") != _EXPECTED_RENDERER_CONTRACT:
        raise SavedQuoteSkillStoreError("renderer contract mismatch")
    if payload.get("calculationAuthority") != _EXPECTED_CALCULATION_AUTHORITY:
        raise SavedQuoteSkillStoreError("calculation authority mismatch")

    # Persist a compact deterministic JSON projection. The B66 semantic
    # authority already canonicalizes the Skill; storage normalizes whitespace
    # only so byte size and readback are stable.
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(compact.encode("utf-8")) > MAX_SKILL_JSON_BYTES:
        raise SavedQuoteSkillStoreError("skill_json is too large")

    return ApprovedSavedQuoteSkillArtifact(
        skill_id=clean_id,
        skill_name=clean_name,
        fingerprint=fingerprint,
        version=version,
        serialized_json=compact,
    )


def validate_row_id(value: object) -> str:
    if not isinstance(value, str) or not _ROW_ID_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillStoreError("saved skill id is invalid")
    return value.strip()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    output: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            output.append(item)
    return output


def _public_projection(row: dict[str, Any], *, include_skill: bool) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "saved_skill_id": str(row.get("id", "")),
        "workspace_id": str(row.get("workspace_id", "")),
        "skill_id": str(row.get("skill_id", "")),
        "skill_name": str(row.get("skill_name", "")),
        "skill_fingerprint": str(row.get("skill_fingerprint", "")),
        "skill_version": int(row.get("skill_version", 0)),
        "status": str(row.get("status", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
    }
    if include_skill:
        raw = row.get("skill_json")
        try:
            projected["skill"] = json.loads(raw) if isinstance(raw, str) else None
        except json.JSONDecodeError:
            projected["skill"] = None
    return projected


class SavedQuoteSkillStore(Protocol):
    async def put_approved_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        artifact: ApprovedSavedQuoteSkillArtifact,
    ) -> dict[str, Any]: ...

    async def list_skills(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_SAVED_QUOTE_SKILLS,
    ) -> list[dict[str, Any]]: ...

    async def get_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> dict[str, Any] | None: ...

    async def disable_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> bool: ...


class D1SavedQuoteSkillStore:
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

    async def put_approved_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        artifact: ApprovedSavedQuoteSkillArtifact,
    ) -> dict[str, Any]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        if not isinstance(artifact, ApprovedSavedQuoteSkillArtifact):
            raise SavedQuoteSkillStoreError("approved artifact is required")

        existing = await self._first(
            "SELECT id FROM b66_saved_quote_skill "
            "WHERE user_id=? AND workspace_id=? AND skill_id=? AND skill_version=?",
            owner, workspace, artifact.skill_id, artifact.version,
        )
        now = _now_iso()
        if existing and isinstance(existing.get("id"), str):
            row_id = existing["id"]
            await self._run(
                "UPDATE b66_saved_quote_skill "
                "SET skill_name=?, skill_fingerprint=?, skill_json=?, status='approved', updated_at=? "
                "WHERE id=? AND user_id=? AND workspace_id=?",
                artifact.skill_name, artifact.fingerprint, artifact.serialized_json, now,
                row_id, owner, workspace,
            )
        else:
            row_id = _row_id()
            await self._run(
                "INSERT INTO b66_saved_quote_skill "
                "(id, user_id, workspace_id, skill_id, skill_name, skill_fingerprint, "
                "skill_version, skill_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)",
                row_id, owner, workspace, artifact.skill_id, artifact.skill_name,
                artifact.fingerprint, artifact.version, artifact.serialized_json, now, now,
            )

        row = await self._first(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "skill_json, status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        if not row:
            raise SavedQuoteSkillStoreError("saved quote skill write failed")
        return _public_projection(row, include_skill=True)

    async def list_skills(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_SAVED_QUOTE_SKILLS,
    ) -> list[dict[str, Any]]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        bounded = max(1, min(int(limit), MAX_SAVED_QUOTE_SKILLS))
        rows = await self._all(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE user_id=? AND workspace_id=? AND status='approved' "
            "ORDER BY updated_at DESC LIMIT ?",
            owner, workspace, bounded,
        )
        return [_public_projection(row, include_skill=False) for row in rows]

    async def get_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> dict[str, Any] | None:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(saved_skill_id)
        row = await self._first(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "skill_json, status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            row_id, owner, workspace,
        )
        return _public_projection(row, include_skill=True) if row else None

    async def disable_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> bool:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(saved_skill_id)
        existing = await self._first(
            "SELECT id FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            row_id, owner, workspace,
        )
        if not existing:
            return False
        await self._run(
            "UPDATE b66_saved_quote_skill SET status='disabled', updated_at=? "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            _now_iso(), row_id, owner, workspace,
        )
        return True
